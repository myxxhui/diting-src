"""SP4 再平衡协议（step_06 实现）。

触发逻辑（L3 §3.5.1 T1~T5）：
  单仓占比（ratio = mv/total）> 0.25 严格触发；ratio=0.25 不触发。

context 支持两种模式：
  ① mv-based（推荐，对应 L3 F1 公式）：
    mv: float           单仓市值
    total: float        总仓市值（>0）
  ② weight-based（兼容旧接口）：
    current_weight: float  当前持仓权重 (0-1)，等同于 mv/total
    target_weight: float   目标权重（供偏离度计算，可选）

sell_ratio 公式（L3 §3.5.2 F1）：
  sell_ratio = (mv - total * 0.25) / mv，clip [0, 1]
  等价：sell_ratio = (ratio - 0.25) / ratio

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_06_SP4再平衡协议.md]
"""
from __future__ import annotations

from apps.exit_engine.config import settings
from apps.exit_engine.models.position import Position
from apps.exit_engine.models.sell_signal import SellSignal, SellSignalEvent, SignalSeverity, SignalType
from apps.exit_engine.protocols.base import BaseProtocol, CheckResult

_THRESHOLD = 0.25  # L3 DNA SP4_THRESHOLD


def _compute_sell_ratio(ratio: float, threshold: float = _THRESHOLD) -> float:
    """L3 F1: sell_ratio = (ratio - threshold) / ratio，clip [0, 1]。
    等价于 (mv - total*threshold) / mv。
    """
    if ratio <= 0:
        return 0.0
    return max(0.0, min(1.0, (ratio - threshold) / ratio))


class RebalanceProtocol(BaseProtocol):
    """SP4：单仓占比 >25% 严格触发，priority=3，buffer_days=7（可撤销）。"""

    protocol_name = SignalType.REBALANCE
    priority = settings.sp4_rebalance_priority
    buffer_days = settings.sp4_rebalance_buffer_days

    def check(self, position: Position, context: dict) -> CheckResult:  # noqa: C901
        threshold = settings.sp4_rebalance_threshold  # 0.25

        # ── 模式①：mv/total ─────────────────────────────────────────────────
        mv = context.get("mv") or context.get("market_value")
        total = context.get("total") or context.get("portfolio_value")

        if mv is not None and total is not None:
            try:
                mv = float(mv)
                total = float(total)
            except (TypeError, ValueError):
                return CheckResult(triggered=False, context={"reason": "mv/total 类型转换失败"})
            if total <= 0:
                return CheckResult(triggered=False, context={"reason": "total_value <= 0"})
            ratio = mv / total
            return CheckResult(
                triggered=ratio > threshold,
                context={
                    "ratio": round(ratio, 6),
                    "mv": mv,
                    "total": total,
                    "threshold": threshold,
                    "mode": "mv_based",
                },
            )

        # ── 模式②：current_weight（兼容旧接口）──────────────────────────────
        current_weight = context.get("current_weight")
        target_weight = context.get("target_weight")

        if current_weight is None or target_weight is None:
            return CheckResult(triggered=False, context={"reason": "缺少 mv/total 或 current_weight/target_weight"})

        try:
            current_weight = float(current_weight)
            target_weight = float(target_weight)
        except (TypeError, ValueError):
            return CheckResult(triggered=False, context={"reason": "weight 类型转换失败"})

        deviation = abs(current_weight - target_weight)
        triggered = deviation > threshold
        return CheckResult(
            triggered=triggered,
            context={
                "current_weight": current_weight,
                "target_weight": target_weight,
                "ratio": current_weight,
                "deviation": round(deviation, 4),
                "threshold": threshold,
                "direction": "overweight" if current_weight > target_weight else "underweight",
                "mode": "weight_based",
            },
        )

    def is_reverse_condition(self, position: Position, context: dict) -> bool:
        """B3：ratio 回落至 ≤threshold → 反向条件成立，自动 cancelled。"""
        mv = context.get("mv") or context.get("market_value")
        total = context.get("total") or context.get("portfolio_value")
        threshold = settings.sp4_rebalance_threshold
        if mv is not None and total is not None and float(total) > 0:
            return float(mv) / float(total) <= threshold
        ratio = context.get("current_weight")
        if ratio is not None:
            return float(ratio) <= threshold
        return False

    def trigger(self, position: Position, check_result: CheckResult) -> SellSignal:
        ctx = check_result.context
        ratio = ctx.get("ratio", 0.0)
        threshold = ctx.get("threshold", _THRESHOLD)
        mv = ctx.get("mv")
        total = ctx.get("total")
        mode = ctx.get("mode", "weight_based")

        if mode == "mv_based" and mv and total:
            sell_ratio = _compute_sell_ratio(ratio, threshold)
            amount_to_sell = mv - total * threshold
            advice = (
                f"占比 {ratio:.0%}→{threshold:.0%}，"
                f"建议减仓约 {amount_to_sell / 10000:.1f} 万"
            )
            reason = f"SP4 再平衡：单仓占比 {ratio:.2%} > 阈值 {threshold:.0%}（mv={mv:.0f} total={total:.0f}）"
        else:
            cw = ctx.get("current_weight", ratio)
            tw = ctx.get("target_weight", threshold)
            deviation = ctx.get("deviation", 0.0)
            direction = ctx.get("direction", "overweight")
            sell_ratio = min(deviation / cw, 1.0) if direction == "overweight" and cw > 0 else 0.0
            advice = f"再平衡建议：减持约 {sell_ratio:.0%} 仓位，使权重回归目标 {tw:.0%}"
            reason = (
                f"SP4 再平衡：持仓权重 {cw:.1%}，目标 {tw:.1%}，"
                f"偏离 {deviation:.1%} > 阈值 {threshold:.1%}（{direction}）"
            )

        return SellSignal(
            protocol_name=self.protocol_name,
            priority=self.priority,
            symbol=position.symbol,
            position_id=position.id,
            trigger_price=getattr(position, "cost_price", 0.0),
            current_price=getattr(position, "current_price", None) or 0.0,
            sell_ratio=round(sell_ratio, 4),
            reason=reason,
            advice=advice,
            buffer_days=self.buffer_days,
            is_revocable=True,
            extra=ctx,
        )

    def output_event(self, signal: SellSignal) -> SellSignalEvent:
        return SellSignalEvent(
            symbol=signal.symbol,
            signal_type=signal.protocol_name,
            trigger_price=signal.trigger_price,
            current_price=signal.current_price,
            protocol="SP4",
            advice=signal.advice,
            severity=SignalSeverity.NORMAL,
            sell_ratio=signal.sell_ratio,
            reason=signal.reason,
            position_id=signal.position_id,
            triggered_at=signal.triggered_at,
        )
