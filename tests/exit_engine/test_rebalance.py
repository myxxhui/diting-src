"""D4 step_06 — SP4 RebalanceProtocol 测试。

[Ref: 03_/04_维度四/.../step_06_SP4再平衡协议.md]
"""
from __future__ import annotations

import pytest

from apps.exit_engine.models.sell_signal import SignalType
from apps.exit_engine.protocols.rebalance import RebalanceProtocol


def _position(symbol="002837", pos_id="pos-sp4", cost=40.0, current=50.0):
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class _Pos:
        id: str
        symbol: str
        name: str
        cost_price: float
        current_price: Optional[float]

    return _Pos(id=pos_id, symbol=symbol, name="英维克", cost_price=cost, current_price=current)


@pytest.fixture
def proto():
    return RebalanceProtocol()


class TestRebalanceProtocol:
    # ─── 触发 ────────────────────────────────────────────────────────────────
    def test_overweight_triggers(self, proto):
        pos = _position()
        ctx = {"current_weight": 0.50, "target_weight": 0.20}  # 偏离 30% > 阈值 25%
        result = proto.check(pos, ctx)
        assert result.triggered is True
        assert result.context["direction"] == "overweight"
        assert result.context["deviation"] == pytest.approx(0.30, abs=0.001)

    def test_underweight_triggers(self, proto):
        pos = _position()
        ctx = {"current_weight": 0.05, "target_weight": 0.35}  # 偏离 30%
        result = proto.check(pos, ctx)
        assert result.triggered is True
        assert result.context["direction"] == "underweight"

    # ─── 不触发 ──────────────────────────────────────────────────────────────
    def test_deviation_below_threshold_not_trigger(self, proto):
        pos = _position()
        ctx = {"current_weight": 0.22, "target_weight": 0.20}  # 偏离 2% < 25%
        result = proto.check(pos, ctx)
        assert result.triggered is False

    def test_exact_threshold_not_trigger(self, proto):
        pos = _position()
        ctx = {"current_weight": 0.45, "target_weight": 0.20}  # 偏离恰好 25%
        result = proto.check(pos, ctx)
        # 25% 不超过阈值（>，非≥）
        assert result.triggered is False

    def test_missing_weights_not_trigger(self, proto):
        pos = _position()
        result = proto.check(pos, {})
        assert result.triggered is False

    def test_invalid_weight_type_not_trigger(self, proto):
        pos = _position()
        result = proto.check(pos, {"current_weight": "heavy", "target_weight": 0.2})
        assert result.triggered is False

    # ─── SellSignal 属性 ─────────────────────────────────────────────────────
    def test_trigger_produces_sell_signal(self, proto):
        pos = _position()
        check = proto.check(pos, {"current_weight": 0.50, "target_weight": 0.20})
        signal = proto.trigger(pos, check)
        assert signal.protocol_name == SignalType.REBALANCE
        assert signal.priority == 3
        assert signal.is_revocable is True
        assert signal.buffer_days == 7

    def test_trigger_sell_ratio_not_exceed_1(self, proto):
        pos = _position()
        ctx = {"current_weight": 0.90, "target_weight": 0.10}
        check = proto.check(pos, ctx)
        signal = proto.trigger(pos, check)
        assert 0.0 <= signal.sell_ratio <= 1.0

    def test_output_event_protocol_sp4(self, proto):
        pos = _position()
        check = proto.check(pos, {"current_weight": 0.50, "target_weight": 0.20})
        signal = proto.trigger(pos, check)
        event = proto.output_event(signal)
        assert event.protocol == "SP4"
        assert "再平衡" in event.advice

    # ─── evaluate 一体调用 ────────────────────────────────────────────────────
    def test_evaluate_returns_signal(self, proto):
        pos = _position()
        signal = proto.evaluate(pos, {"current_weight": 0.50, "target_weight": 0.20})
        assert signal is not None

    def test_evaluate_returns_none(self, proto):
        pos = _position()
        signal = proto.evaluate(pos, {"current_weight": 0.22, "target_weight": 0.20})
        assert signal is None

    # ─── T1 严格比较（L3 §3.5.1 T1）：mv/total 模式 ─────────────────────────
    def test_t1_ratio_exactly_025_not_trigger(self, proto):
        """ratio=0.25 严格不触发（> 而非 >=）。"""
        pos = _position()
        ctx = {"mv": 250_000.0, "total": 1_000_000.0}  # ratio=0.25
        result = proto.check(pos, ctx)
        assert result.triggered is False

    def test_t1_ratio_just_above_025_triggers(self, proto):
        """ratio=0.2501 严格触发。"""
        pos = _position()
        ctx = {"mv": 250_100.0, "total": 1_000_000.0}  # ratio=0.2501
        result = proto.check(pos, ctx)
        assert result.triggered is True

    def test_t2_total_zero_not_trigger(self, proto):
        """T2：total_value ≤ 0 不触发，防止除零。"""
        pos = _position()
        result = proto.check(pos, {"mv": 100_000.0, "total": 0.0})
        assert result.triggered is False

    def test_t3_mv_none_falls_back_to_weight(self, proto):
        """T3：mv 缺失时降级用 current_weight，缺 target_weight 则不触发。"""
        pos = _position()
        result = proto.check(pos, {"mv": None, "total": None, "current_weight": None, "target_weight": None})
        assert result.triggered is False

    # ─── F1/F2 sell_ratio 公式（L3 §3.5.2）────────────────────────────────────
    def test_f2_sell_ratio_formula_30pct(self, proto):
        """F2：30% 仓位 / 总值 100 万 → sell_ratio ≈ 0.1667。
        公式：(mv - total*0.25) / mv = (30 - 25) / 30 ≈ 0.1667。
        """
        pos = _position()
        ctx = {"mv": 300_000.0, "total": 1_000_000.0}  # ratio=0.30
        check = proto.check(pos, ctx)
        assert check.triggered is True
        signal = proto.trigger(pos, check)
        assert abs(signal.sell_ratio - 0.1667) < 0.0001

    def test_f1_sell_ratio_clipped_at_1(self, proto):
        """F1：sell_ratio clip [0, 1]，极端 ratio 不超过 1.0。"""
        pos = _position()
        ctx = {"mv": 900_000.0, "total": 1_000_000.0}  # ratio=0.90
        check = proto.check(pos, ctx)
        signal = proto.trigger(pos, check)
        assert 0.0 <= signal.sell_ratio <= 1.0

    # ─── B3 反向条件（L3 §3.5.3）──────────────────────────────────────────────
    def test_b3_reverse_condition_ratio_drops(self, proto):
        """B3：ratio 回落至 ≤0.25 → is_reverse_condition=True。"""
        pos = _position()
        assert proto.is_reverse_condition(pos, {"mv": 250_000.0, "total": 1_000_000.0}) is True
        assert proto.is_reverse_condition(pos, {"mv": 200_000.0, "total": 1_000_000.0}) is True

    def test_b3_reverse_condition_still_high(self, proto):
        """B3：ratio 仍 >0.25 → is_reverse_condition=False。"""
        pos = _position()
        assert proto.is_reverse_condition(pos, {"mv": 300_000.0, "total": 1_000_000.0}) is False

    # ─── E2 no-auto-execute（L3 §3.5.4 E2）─────────────────────────────────────
    def test_e2_no_auto_execute_fields(self, proto):
        """E2：SellSignalEvent 不含 buy/execute/order_id 等禁字段（SP4 永久规则）。"""
        pos = _position()
        check = proto.check(pos, {"mv": 300_000.0, "total": 1_000_000.0})
        signal = proto.trigger(pos, check)
        event = proto.output_event(signal)
        forbidden = {"buy", "execute", "order_id", "auto_trade", "qmt_signal", "webhook_target"}
        event_fields = set(vars(event).keys())
        assert event_fields.isdisjoint(forbidden), f"禁字段出现：{event_fields & forbidden}"

    # ─── T4 多仓独立评估（L3 §3.5.1 T4）────────────────────────────────────────
    def test_t4_only_overweight_position_triggers(self, proto):
        """T4：多持仓中仅 ratio>0.25 的触发，其余 abstain。"""
        pos_a = _position(symbol="002837", pos_id="a")
        pos_b = _position(symbol="300499", pos_id="b")

        ctx_a = {"mv": 300_000.0, "total": 1_000_000.0}  # 30%，触发
        ctx_b = {"mv": 200_000.0, "total": 1_000_000.0}  # 20%，不触发

        assert proto.check(pos_a, ctx_a).triggered is True
        assert proto.check(pos_b, ctx_b).triggered is False
