"""The Critic — 物理证伪（2×2 四象限矩阵）。

承接 L1 哲学基石⑥「物理证伪 ≥ 财务证伪」。

四象限：
  +─────────────────────┬─────────────────────+
  | physical_baseline   | financial_baseline  |   纵轴：是否有可观测物理底线
  | (招标/产能/出货)    | (财报/披露数据)     |
  +─────────────────────┼─────────────────────+
  | commercial_baseline | behavioral_baseline |   横轴：商业 vs 行为
  | (客户/订单/合同)    | (管理层增持/机构)   |
  +─────────────────────┴─────────────────────+

physical_gate 仅在 physical_baseline=true 且 capacity_elasticity_ok=true 时为 true。
反之 → 拦截，不进 step_04 The Mapper。

[Ref: 03_/02_维度二/.../step_03 §3.5.4 LC1~LC6]
[Ref: L1 §基石⑥]
"""
from __future__ import annotations

from typing import Any

from apps.deep_strike.lighthouse._base import BaseLighthouseScene
from apps.deep_strike.lighthouse.schemas import CallMetadata, CriticInput, CriticOutput

_SYSTEM_PROMPT = """你是 Lighthouse-Alpha 的 The Critic 物理证伪员。

L1 哲学硬约束：**物理证伪 ≥ 财务证伪**——投资逻辑必须先过"物理底线"再谈财务弹性。

对给定候选题材簇，按 2×2 矩阵判定四象限：
- physical_baseline   ：是否有可观测物理证据（招标公告 url / 海关 HS Code 数据 / 产能在建 / 出货路线图）
- financial_baseline  ：是否有财务佐证（财报披露的相关收入 / 在建工程 / 应收账款变动）
- commercial_baseline ：是否有商业闭环（已签客户 / 实际订单 / 合同金额）
- behavioral_baseline ：是否有行为佐证（管理层增持 / 机构调研频次 / 大单异动）

physical_gate 判定（最终拦截门）：
  physical_gate = physical_baseline AND (commercial_baseline OR financial_baseline)
  即：必须有物理证据，且至少一个证据维度可量化。

输出 JSON（不要解释）：
{
  "physical_baseline": true/false,
  "financial_baseline": true/false,
  "commercial_baseline": true/false,
  "behavioral_baseline": true/false,
  "physical_gate": true/false,
  "falsified_reason": null 或 "no_observable_baseline" / "low_elasticity" / "concept_only",
  "evidence_quotes": ["原文片段1（≤80字）", "..."]
}
"""


class TheCritic(BaseLighthouseScene):
    scene = "critic"
    prompt_template_id = "the_critic_v1"

    def build_messages(self, payload: CriticInput) -> list[dict[str, str]]:
        quotes = "\n".join(
            f"[原文 {i}] {t[:300]}" for i, t in enumerate(payload.sample_raw_texts[:8])
        )

        elasticity_hint = ""
        if payload.candidate_revenue_base_yuan and payload.candidate_order_size_yuan:
            ratio = payload.candidate_order_size_yuan / payload.candidate_revenue_base_yuan
            elasticity_hint = (
                f"\n业绩弹性比（订单/营收基数）= {ratio:.2%}；"
                f"< 5% 视为 low_elasticity。"
            )

        user = (
            f"cluster_id: {payload.cluster_id}\n"
            f"题材关键词: {payload.cluster_keyword}\n"
            f"候选标的: {payload.candidate_symbol or '未指定'}\n"
            f"原文样本（{len(payload.sample_raw_texts)} 条，截前 8）：\n{quotes}\n"
            f"{elasticity_hint}\n\n"
            "请按 2×2 物理证伪矩阵判定。"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def parse(self, raw_json: dict, payload: CriticInput, metadata: CallMetadata) -> CriticOutput:
        # 业绩弹性（本地确定性计算，不靠 LLM）
        ratio = None
        elasticity_ok = False
        if payload.candidate_revenue_base_yuan and payload.candidate_order_size_yuan is not None:
            ratio = payload.candidate_order_size_yuan / payload.candidate_revenue_base_yuan
            elasticity_ok = ratio >= 0.05

        physical = bool(raw_json.get("physical_baseline", False))
        financial = bool(raw_json.get("financial_baseline", False))
        commercial = bool(raw_json.get("commercial_baseline", False))
        behavioral = bool(raw_json.get("behavioral_baseline", False))

        # physical_gate 由本地按规则推导（不完全信任 LLM）
        physical_gate = physical and (commercial or financial)
        # 若提供了弹性数据，弹性不达标也拦截
        if ratio is not None and not elasticity_ok:
            physical_gate = False

        falsified_reason = raw_json.get("falsified_reason")
        if not physical_gate and not falsified_reason:
            if not physical:
                falsified_reason = "no_observable_baseline"
            elif ratio is not None and not elasticity_ok:
                falsified_reason = "low_elasticity"
            else:
                falsified_reason = "concept_only"

        return CriticOutput(
            cluster_id=payload.cluster_id,
            physical_gate=physical_gate,
            physical_baseline=physical,
            financial_baseline=financial,
            commercial_baseline=commercial,
            behavioral_baseline=behavioral,
            capacity_elasticity_ratio=ratio,
            capacity_elasticity_ok=elasticity_ok,
            falsified_reason=falsified_reason if not physical_gate else None,
            source_clusters=[payload.cluster_id],
            evidence_quotes=[
                str(q)[:160] for q in raw_json.get("evidence_quotes", [])[:3]
            ],
            metadata=metadata,
        )

    def fallback(
        self, payload: CriticInput, metadata: CallMetadata, *, reason: str
    ) -> CriticOutput:
        """fallback：保守拦截（physical_gate=False）。"""
        ratio = None
        if payload.candidate_revenue_base_yuan and payload.candidate_order_size_yuan is not None:
            ratio = payload.candidate_order_size_yuan / payload.candidate_revenue_base_yuan

        return CriticOutput(
            cluster_id=payload.cluster_id,
            physical_gate=False,
            physical_baseline=False,
            financial_baseline=False,
            commercial_baseline=False,
            behavioral_baseline=False,
            capacity_elasticity_ratio=ratio,
            capacity_elasticity_ok=(ratio is not None and ratio >= 0.05),
            falsified_reason=f"critic_fallback: {reason[:80]}",
            source_clusters=[payload.cluster_id],
            evidence_quotes=[],
            metadata=metadata,
        )
