"""LighthouseOrchestrator — Sniffer → Critic → Scorer → Architect → Timer 端到端编排。

执行链：
  1. Sniffer  : raw_texts → clusters
  2. Critic   : 每个 cluster → physical_gate（false 拦截）
  3. Scorer   : 过 critic 的 cluster → composite + decision
  4. Architect: propose/watch 档 → monitor_matrix
  5. Timer    : 同上 → 三段时间窗口

事件链与永久规则：
  - 任何环节出错不阻塞下一个候选，错误聚合到 OrchestratorResult.errors[]
  - propose 不等于建仓（永久规则）；编排器从不写入持仓表
  - 全程通过 AIDispatcher，符合预算软上限

[Ref: 03_/02_维度二/.../step_02~07]
[Ref: L1 §基石⑥ 物理证伪 ≥ 财务证伪]
[Ref: D2 __init__.py 永久规则 1~3]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from apps.deep_strike.lighthouse.architect import TheArchitect
from apps.deep_strike.lighthouse.critic import TheCritic
from apps.deep_strike.lighthouse.schemas import (
    ArchitectInput,
    CriticInput,
    CriticOutput,
    MonitorMatrix,
    ScorerInput,
    ScorerOutput,
    SnifferCluster,
    SnifferInput,
    SnifferOutput,
    TimerInput,
    TimerOutput,
)
from apps.deep_strike.lighthouse.scorer import TheScorer
from apps.deep_strike.lighthouse.sniffer import TheSniffer
from apps.deep_strike.lighthouse.timer import TheTimer

logger = logging.getLogger(__name__)


@dataclass
class CandidateOutcome:
    cluster: SnifferCluster
    critic: Optional[CriticOutput] = None
    scorer: Optional[ScorerOutput] = None
    architect: Optional[MonitorMatrix] = None
    timer: Optional[TimerOutput] = None
    status: str = "pending"  # passed / dropped_by_critic / dropped_by_scorer / pending
    drop_reason: Optional[str] = None


@dataclass
class OrchestratorResult:
    sniffer: SnifferOutput
    outcomes: list[CandidateOutcome] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def propose_count(self) -> int:
        return sum(1 for o in self.outcomes if o.scorer and o.scorer.decision == "propose")

    @property
    def passed_critic(self) -> int:
        return sum(1 for o in self.outcomes if o.critic and o.critic.physical_gate)

    def summary(self) -> dict:
        return {
            "total_clusters": len(self.outcomes),
            "passed_critic": self.passed_critic,
            "propose": self.propose_count,
            "errors": len(self.errors),
        }


class LighthouseOrchestrator:
    """五场景顺序编排（同步接口）。

    内部按 AIDispatcher 单实例，每个场景单独构造（共享同一 dispatcher）。
    """

    def __init__(
        self,
        *,
        force_route: Optional[str] = None,
    ) -> None:
        self.sniffer = TheSniffer()
        self.critic = TheCritic()
        self.scorer = TheScorer()
        self.architect = TheArchitect()
        self.timer = TheTimer()
        self.force_route = force_route  # 测试时传 "mock" 强制走 mock

    def run_for_clusters(
        self,
        sniffer_input: SnifferInput,
        candidate_context: Optional[dict[str, Any]] = None,
    ) -> OrchestratorResult:
        """端到端运行：原文 → 候选 → 拦截 → 打分 → 监控字典 → 时机。

        candidate_context 可包含每个 cluster 的额外信息：
          {
            "<cluster_keyword>": {
              "candidate_symbol": "300308",
              "candidate_revenue_base_yuan": 1.2e10,
              "candidate_order_size_yuan": 8e8,
              "policy_text_excerpts": [...],
              "industry_research_excerpts": [...],
              "a_share_mapping_excerpts": [...],
              "target_company": "中际旭创",
              "logic_chain_nodes": [...],
            },
            ...
          }
        """
        candidate_context = candidate_context or {}
        errors: list[str] = []

        # ── ① Sniffer ──
        try:
            sniffer_out: SnifferOutput = self.sniffer.call(sniffer_input, force_route=self.force_route)
        except Exception as exc:
            logger.exception("[orchestrator] sniffer 失败")
            errors.append(f"sniffer: {exc}")
            return OrchestratorResult(
                sniffer=SnifferOutput(clusters=[], total_docs=len(sniffer_input.raw_texts),
                                       metadata=_empty_metadata()),
                outcomes=[],
                errors=errors,
            )

        result = OrchestratorResult(sniffer=sniffer_out, outcomes=[], errors=errors)

        # ── 对每个 cluster 走 critic → scorer → architect → timer ──
        for cluster in sniffer_out.clusters:
            ctx = candidate_context.get(cluster.keyword, {})
            outcome = CandidateOutcome(cluster=cluster)
            result.outcomes.append(outcome)

            # ② Critic
            try:
                critic_in = CriticInput(
                    cluster_id=cluster.cluster_id,
                    cluster_keyword=cluster.keyword,
                    candidate_symbol=ctx.get("candidate_symbol"),
                    candidate_revenue_base_yuan=ctx.get("candidate_revenue_base_yuan"),
                    candidate_order_size_yuan=ctx.get("candidate_order_size_yuan"),
                    sample_raw_texts=[
                        sniffer_input.raw_texts[i]
                        for i in cluster.sample_doc_idx
                        if 0 <= i < len(sniffer_input.raw_texts)
                    ][:8],
                )
                outcome.critic = self.critic.call(critic_in, force_route=self.force_route)
            except Exception as exc:
                errors.append(f"critic[{cluster.cluster_id}]: {exc}")
                outcome.status = "dropped_by_critic"
                outcome.drop_reason = f"critic_error: {exc}"
                continue

            if not outcome.critic.physical_gate:
                outcome.status = "dropped_by_critic"
                outcome.drop_reason = outcome.critic.falsified_reason or "physical_gate_false"
                continue

            # ③ Scorer
            try:
                scorer_in = ScorerInput(
                    cluster_id=cluster.cluster_id,
                    cluster_keyword=cluster.keyword,
                    candidate_symbols=[ctx["candidate_symbol"]] if ctx.get("candidate_symbol") else [],
                    policy_text_excerpts=ctx.get("policy_text_excerpts", []),
                    industry_research_excerpts=ctx.get("industry_research_excerpts", []),
                    a_share_mapping_excerpts=ctx.get("a_share_mapping_excerpts", []),
                )
                outcome.scorer = self.scorer.call(scorer_in, force_route=self.force_route)
            except Exception as exc:
                errors.append(f"scorer[{cluster.cluster_id}]: {exc}")
                outcome.status = "dropped_by_scorer"
                outcome.drop_reason = f"scorer_error: {exc}"
                continue

            if outcome.scorer.decision == "discard":
                outcome.status = "dropped_by_scorer"
                outcome.drop_reason = f"composite={outcome.scorer.composite} < 7.0"
                continue

            # ④ Architect（仅 propose/watch 才生成监控字典）
            if ctx.get("logic_chain_nodes"):
                try:
                    arch_in = ArchitectInput(
                        thesis_card_id=f"thesis_{cluster.cluster_id}",
                        target_company=ctx.get("target_company", cluster.keyword),
                        symbol=ctx.get("candidate_symbol") or "000000",
                        logic_chain_nodes=ctx["logic_chain_nodes"],
                    )
                    outcome.architect = self.architect.call(arch_in, force_route=self.force_route)
                except Exception as exc:
                    errors.append(f"architect[{cluster.cluster_id}]: {exc}")

                # ⑤ Timer
                try:
                    timer_in = TimerInput(
                        thesis_card_id=f"thesis_{cluster.cluster_id}",
                        symbol=ctx.get("candidate_symbol") or "000000",
                        current_date=sniffer_input.window_end,
                        monitor_alert_triggered_at=sniffer_input.window_end,
                        scan_hit_signals=[cluster.keyword],
                    )
                    outcome.timer = self.timer.call(timer_in, force_route=self.force_route)
                except Exception as exc:
                    errors.append(f"timer[{cluster.cluster_id}]: {exc}")

            outcome.status = "passed"

        return result


def _empty_metadata():
    from datetime import datetime
    from apps.deep_strike.lighthouse.schemas import CallMetadata
    return CallMetadata(
        model_name="none",
        prompt_template_id="empty",
        generated_at=datetime.utcnow(),
        route="mock",
    )
