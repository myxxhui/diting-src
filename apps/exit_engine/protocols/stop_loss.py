"""SP1 止损协议。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_03_SP1止损协议.md]

触发条件: current_price / cost_price - 1 <= -0.15
优先级: 1；缓冲期: 0；卖出比例: 1.0；不可撤销。
"""
from __future__ import annotations

from datetime import datetime, timezone

from apps.exit_engine.config import settings
from apps.exit_engine.protocol_config import load_sp1_config
from apps.exit_engine.models.position import Position
from apps.exit_engine.models.sell_signal import (
    SellSignal,
    SellSignalEvent,
    SignalSeverity,
    SignalType,
)
from apps.exit_engine.protocols.base import BaseProtocol, CheckResult


class StopLossProtocol(BaseProtocol):
    protocol_name = SignalType.STOP_LOSS

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config if config is not None else load_sp1_config()
        self.threshold: float = float(
            cfg.get("threshold", cfg.get("stop_loss_threshold", settings.sp1_stop_loss_threshold))
        )
        self.advice_template: str = str(
            cfg.get(
                "advice_template",
                "建议立即止损。成本 {cost_price:.2f} 元，当前 {current_price:.2f} 元，"
                "浮动 {pnl:+.2%}，已触发 {threshold:.0%} 止损线。",
            )
        )
        self.priority = int(cfg.get("priority", settings.sp1_stop_loss_priority))
        self.buffer_days = int(cfg.get("buffer_days", settings.sp1_stop_loss_buffer_days))
        if self.threshold > 0:
            raise ValueError(f"stop_loss_threshold 必须 <= 0,实际 {self.threshold}")

    def check(self, position: Position, context: dict) -> CheckResult:
        if position.current_price is None:
            return CheckResult(triggered=False, context={"reason": "current_price 缺失"})
        if position.cost_price <= 0:
            return CheckResult(triggered=False, context={"reason": "cost_price <= 0 异常"})
        if position.quantity <= 0:
            return CheckResult(triggered=False, context={"reason": "quantity <= 0 异常"})
        return_pct = position.return_pct
        if return_pct is None:
            return CheckResult(triggered=False, context={"reason": "return_pct 计算失败"})
        triggered = return_pct <= self.threshold
        return CheckResult(
            triggered=triggered,
            context={
                "return_pct": return_pct,
                "threshold": self.threshold,
                "trigger_price": position.cost_price * (1 + self.threshold),
            },
        )

    def trigger(self, position: Position, check_result: CheckResult) -> SellSignal:
        ctx = check_result.context
        return_pct = float(ctx["return_pct"])
        trigger_price = float(ctx["trigger_price"])
        reason = (
            f"收益率 {return_pct * 100:.2f}% 已触及止损线 {self.threshold * 100:.1f}%;"
            f"成本价 {position.cost_price:.2f} 现价 {position.current_price:.2f}"
        )
        pnl = return_pct
        try:
            advice = self.advice_template.format(
                cost_price=position.cost_price,
                current_price=float(position.current_price or 0.0),
                pnl=pnl,
                threshold=self.threshold,
            )
        except (KeyError, ValueError):
            advice = (
                f"建议止损：成本 {position.cost_price:.2f} 现价 "
                f"{float(position.current_price or 0):.2f} 收益率 {return_pct * 100:.2f}%"
            )
        return SellSignal(
            protocol_name=self.protocol_name,
            priority=self.priority,
            symbol=position.symbol,
            position_id=position.id,
            trigger_price=trigger_price,
            current_price=float(position.current_price or 0.0),
            sell_ratio=1.0,
            reason=reason,
            advice=advice,
            triggered_at=datetime.now(timezone.utc),
            buffer_days=self.buffer_days,
            is_revocable=False,
            extra={"return_pct": return_pct, "threshold": self.threshold},
        )

    def output_event(self, signal: SellSignal) -> SellSignalEvent:
        return SellSignalEvent(
            symbol=signal.symbol,
            signal_type=self.protocol_name,
            trigger_price=signal.trigger_price,
            current_price=signal.current_price,
            protocol=self.protocol_name.value,
            advice=signal.advice,
            severity=SignalSeverity.EMERGENCY,
            sell_ratio=signal.sell_ratio,
            reason=signal.reason,
            position_id=signal.position_id,
            triggered_at=signal.triggered_at,
            buffer_end_at=None,
            is_revocable=False,
        )
