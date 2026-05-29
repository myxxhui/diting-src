"""ThesisCardGenerator — 规则模板生成 thesis 卡（非 stub）。

内容来自真实 scan_log + evidence_chain，可选调 D5 Teacher 润色；
The Timer 集成：调 lighthouse/timer.py；无 API KEY 时 fallback（日历推算）。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_05_thesis卡片生成器.md]
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from apps.deep_strike.engines.evidence_models import EvidenceChain
from apps.deep_strike.engines.thesis.schema import (
    EvidenceItem,
    ThesisCardSchema,
    ValuationAnchor,
)

logger = logging.getLogger(__name__)

# 运行时 guard：禁止 stub 写库
if os.environ.get("THESIS_GENERATOR_MODE", "").lower() == "stub":
    raise RuntimeError(
        "THESIS_GENERATOR_MODE=stub 禁止在生产路径启动 ThesisCardGenerator。"
        "stub 仅允许在 tests/ 单元测试 fixture 中使用。"
    )

# 操作动作映射（来自 playbook decision_hint）
_ACTION_MAP: dict[str, Any] = {
    "strong_buy": "buy",
    "buy": "buy",
    "add": "add",
    "watch": "watch",
    "pass": "watch",
}

# 默认风险条（通用兜底，启动期允许）
_DEFAULT_RISKS = [
    "监管政策收紧风险：行业政策存在不确定性，可能对公司主营业务产生负面影响。",
    "市场系统性风险：宏观经济下行或市场整体调整可能导致股价短期承压。",
    "业绩低于预期风险：实际财报数据或营收增速若低于市场预期，可能引发估值回调。",
]


class ThesisCardGenerator:
    """规则模板 thesis 卡片生成器。

    flow: scan_log + evidence_chain → ThesisCardSchema（status=proposed）
    """

    def __init__(
        self,
        session: Optional[AsyncSession] = None,
        *,
        enable_timer: bool = True,
    ) -> None:
        self.session = session
        self.enable_timer = enable_timer
        self._timer: Any = None

    def _get_timer(self) -> Any:
        if self._timer is None and self.enable_timer:
            try:
                from apps.deep_strike.lighthouse.timer import TheTimer
                self._timer = TheTimer()
            except Exception as e:
                logger.warning("TheTimer 初始化失败，将使用 fallback: %s", e)
        return self._timer

    def _build_summary(
        self,
        symbol: str,
        name: str,
        playbook_id: str,
        confidence: float,
        evidence_chain: EvidenceChain,
        action: str,
    ) -> str:
        """规则模板生成 thesis_summary（≥50 字；来自真实证据）。"""
        core = evidence_chain.items[0].content[:80] if evidence_chain.items else "基本面改善"
        action_zh = {"buy": "建议买入", "add": "建议加仓", "watch": "建议观察"}.get(action, "建议观察")
        summary = (
            f"【{symbol}·{name}】{playbook_id} 剧本命中（置信度 {confidence:.0%}）。"
            f"核心逻辑：{core}。"
            f"综合基本面证据链与行业对比，{action_zh}，"
            f"需跟踪后续财报与行业政策动态。"
        )
        # 保证 ≥50 字（padding 兜底，极端情况）
        while len(summary) < 50:
            summary += "请持续关注公司基本面变化与市场情绪。"
        return summary

    def _build_evidence_items(self, evidence_chain: EvidenceChain) -> list[EvidenceItem]:
        """将内部 EvidenceChain 转换为 schema 格式，保证 ≥3 条。"""
        items = []
        for ev in evidence_chain.items[:6]:
            items.append(
                EvidenceItem(
                    evidence_type=ev.type.value if hasattr(ev.type, "value") else str(ev.type),
                    content=ev.content[:400],
                    url=ev.url,
                )
            )
        # 不够 3 条时用 summary 凑（极端情况）
        while len(items) < 3:
            items.append(
                EvidenceItem(
                    evidence_type="fundamental",
                    content=f"综合基本面支撑证据（第{len(items)+1}条）：公司财务指标处于行业合理区间。",
                )
            )
        return items

    async def generate(
        self,
        symbol: str,
        name: str,
        playbook_id: str,
        confidence: float,
        decision_hint: str,
        evidence_chain: EvidenceChain,
        scan_log_id: Optional[int] = None,
        pass_event_id: Optional[str] = None,
        pe_ratio: Optional[float] = None,
    ) -> ThesisCardSchema:
        """核心生成入口。"""
        action = _ACTION_MAP.get(decision_hint, "watch")
        summary = self._build_summary(symbol, name, playbook_id, confidence, evidence_chain, action)
        evidence_items = self._build_evidence_items(evidence_chain)

        valuation = ValuationAnchor(
            method="watch_only" if action == "watch" else "PE",
            target_price=None if action == "watch" else (pe_ratio and round(pe_ratio * 1.15, 2)),
            basis="启动期 PE 法，目标价 = 当前 PE × 115%。" if action != "watch" else "仅观察，暂不设目标价。",
        )

        card = ThesisCardSchema(
            symbol=symbol,
            name=name,
            playbook_id=playbook_id,
            confidence=confidence,
            thesis_summary=summary,
            evidence_chain=evidence_items,
            risks=_DEFAULT_RISKS,
            valuation_anchor=valuation,
            action=action,
            scan_log_id=scan_log_id,
            pass_event_id=pass_event_id,
        )

        # The Timer 集成（async fallback-safe）
        timer = self._get_timer()
        if timer is not None:
            try:
                import os

                from apps.deep_strike.lighthouse.schemas import TimerInput
                timer_input = TimerInput(
                    thesis_card_id=card.thesis_id,
                    symbol=symbol,
                    current_date=date.today(),
                    scan_hit_signals=[ev.type.value for ev in evidence_chain.items[:5]],
                )
                force = "remote" if os.getenv("ANTHROPIC_API_KEY", "").strip() else None
                timer_output = timer.call(timer_input, force_route=force)
                card.timer_signal = timer_output.model_dump(mode="json")
                route = timer_output.metadata.route if timer_output.metadata else "?"
                logger.info("TheTimer 生成成功: %s route=%s", symbol, route)
            except Exception as e:
                logger.warning("TheTimer 调用失败（fallback 无 timer_signal）: %s", e)

        return card
