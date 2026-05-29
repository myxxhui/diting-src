"""SP2 止盈协议。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]

触发条件: current_price / cost_price - 1 >= 0.30
优先级: 2；缓冲期: 3 天；可撤销。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from apps.exit_engine.config import settings
from apps.exit_engine.models.position import Position
from apps.exit_engine.models.sell_signal import (
    SellSignal,
    SellSignalEvent,
    SignalSeverity,
    SignalType,
)
from apps.exit_engine.protocols.base import BaseProtocol, CheckResult


class TakeProfitProtocol(BaseProtocol):
    protocol_name = SignalType.TAKE_PROFIT
    priority = settings.sp2_take_profit_priority
    buffer_days = settings.sp2_take_profit_buffer_days

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config or {}
        self.threshold: float = float(cfg.get("take_profit_threshold", settings.sp2_take_profit_threshold))
        self.sell_ratio_cfg: float = float(cfg.get("take_profit_sell_ratio", 1.0))
        custom_buffer = cfg.get("take_profit_buffer_days")
        if custom_buffer is not None:
            self.buffer_days = int(custom_buffer)
        if self.threshold < 0:
            raise ValueError(f"take_profit_threshold 必须 >= 0,实际 {self.threshold}")
        if not (0 < self.sell_ratio_cfg <= 1):
            raise ValueError(f"take_profit_sell_ratio 必须 ∈ (0, 1],实际 {self.sell_ratio_cfg}")

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
        triggered = return_pct >= self.threshold
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
        now = datetime.utcnow()
        return SellSignal(
            protocol_name=self.protocol_name,
            priority=self.priority,
            symbol=position.symbol,
            position_id=position.id,
            trigger_price=trigger_price,
            current_price=float(position.current_price or 0.0),
            sell_ratio=self.sell_ratio_cfg,
            reason=(
                f"收益率 {return_pct * 100:.2f}% 已达止盈线 {self.threshold * 100:.1f}%;"
                f"成本价 {position.cost_price:.2f} 现价 {position.current_price:.2f}"
            ),
            advice=(
                f"建议卖出 {self.sell_ratio_cfg * 100:.0f}%(P2 高优先级,缓冲 {self.buffer_days} 天,"
                f"期间若回落至 < {self.threshold * 100:.1f}% 自动取消)"
            ),
            triggered_at=now,
            buffer_days=self.buffer_days,
            is_revocable=True,
            extra={"return_pct": return_pct, "threshold": self.threshold},
        )

    def output_event(self, signal: SellSignal) -> SellSignalEvent:
        buffer_end_at = signal.triggered_at + timedelta(days=signal.buffer_days)
        return SellSignalEvent(
            symbol=signal.symbol,
            signal_type=self.protocol_name,
            trigger_price=signal.trigger_price,
            current_price=signal.current_price,
            protocol=self.protocol_name.value,
            advice=signal.advice,
            severity=SignalSeverity.HIGH,
            sell_ratio=signal.sell_ratio,
            reason=signal.reason,
            position_id=signal.position_id,
            audit_id="",
            triggered_at=signal.triggered_at,
            buffer_end_at=buffer_end_at,
            is_revocable=True,
        )

    def is_reverse_condition(self, position: Position) -> bool:
        if position.return_pct is None:
            return False
        return position.return_pct < self.threshold
