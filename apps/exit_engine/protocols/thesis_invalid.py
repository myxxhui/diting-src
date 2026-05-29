"""SP3 Thesis 失效协议（step_05 实现）。

触发逻辑：
  path A: context['new_state'] == 'exit'
  path B: context['narrative_label'] == 'contradiction' AND context['narrative_invalid_count'] >= 3

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_05_SP3_Thesis失效协议.md]
"""
from __future__ import annotations

from datetime import datetime, timezone

from apps.exit_engine.config import settings
from apps.exit_engine.models.position import Position
from apps.exit_engine.models.sell_signal import SellSignal, SellSignalEvent, SignalSeverity, SignalType
from apps.exit_engine.protocols.base import BaseProtocol, CheckResult


class ThesisInvalidProtocol(BaseProtocol):
    """SP3 优先级=1，buffer_days=0，与 SP1 同优先级。"""

    protocol_name = SignalType.THESIS_INVALID
    priority = settings.sp3_thesis_invalid_priority
    buffer_days = settings.sp3_thesis_invalid_buffer_days

    def check(self, position: Position, context: dict) -> CheckResult:
        """
        context 期待字段（来自 D3 health_change 事件 payload）：
          new_state: str               path A
          narrative_label: str         path B
          narrative_invalid_count: int path B
          health_change_event_id: str  用于 evidence_ref
        """
        new_state = context.get("new_state", "")
        narrative_label = context.get("narrative_label", "")
        invalid_count = context.get("narrative_invalid_count", 0)

        # path A: 直接退出信号
        path_a = new_state == "exit"

        # path B: NLI 叙事矛盾且累计违规 ≥3
        path_b = (
            narrative_label == "contradiction"
            and isinstance(invalid_count, int)
            and invalid_count >= 3
        )

        triggered = path_a or path_b
        trigger_path = "A" if path_a else ("B" if path_b else "none")

        return CheckResult(
            triggered=triggered,
            context={
                "trigger_path": trigger_path,
                "new_state": new_state,
                "narrative_label": narrative_label,
                "narrative_invalid_count": invalid_count,
                "evidence_ref": context.get("health_change_event_id", ""),
            },
        )

    def trigger(self, position: Position, check_result: CheckResult) -> SellSignal:
        path = check_result.context.get("trigger_path", "?")
        evidence_ref = check_result.context.get("evidence_ref", "")
        reason = (
            f"SP3 thesis 失效（path {path}）："
            f"new_state={check_result.context.get('new_state', '-')}；"
            f"narrative={check_result.context.get('narrative_label', '-')} "
            f"×{check_result.context.get('narrative_invalid_count', '-')}"
        )
        return SellSignal(
            protocol_name=self.protocol_name,
            priority=self.priority,
            symbol=position.symbol,
            position_id=position.id,
            trigger_price=position.cost_price if hasattr(position, "cost_price") else 0.0,
            current_price=position.current_price if hasattr(position, "current_price") and position.current_price else 0.0,
            sell_ratio=1.0,
            reason=reason,
            advice="thesis 失效建议清仓",
            buffer_days=self.buffer_days,
            is_revocable=False,
            extra={"evidence_ref": evidence_ref, "trigger_path": path},
        )

    def output_event(self, signal: SellSignal) -> SellSignalEvent:
        return SellSignalEvent(
            symbol=signal.symbol,
            signal_type=signal.protocol_name,
            trigger_price=signal.trigger_price,
            current_price=signal.current_price,
            protocol="SP3",
            advice=signal.advice,
            severity=SignalSeverity.EMERGENCY,
            sell_ratio=signal.sell_ratio,
            reason=signal.reason,
            position_id=signal.position_id,
            triggered_at=signal.triggered_at,
        )
