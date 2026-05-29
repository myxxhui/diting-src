"""D4 step_05 — SP3 ThesisInvalidProtocol 测试（≥10 个用例）。

[Ref: 03_/04_维度四/.../step_05_SP3_Thesis失效协议.md §F]
"""
from __future__ import annotations

import pytest

from apps.exit_engine.models.sell_signal import SignalType
from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol


def _position(symbol="002837", pos_id="pos-001", cost=40.0, current=38.0):
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
    return ThesisInvalidProtocol()


class TestThesisInvalidProtocol:
    # ─── 触发 path A ──────────────────────────────────────────────────────────
    def test_path_a_exit_triggers(self, proto):
        pos = _position()
        ctx = {"new_state": "exit", "health_change_event_id": "ev-001"}
        result = proto.check(pos, ctx)
        assert result.triggered is True
        assert result.context["trigger_path"] == "A"

    def test_path_a_non_exit_not_trigger(self, proto):
        pos = _position()
        result = proto.check(pos, {"new_state": "warning"})
        assert result.triggered is False

    def test_path_a_stable_not_trigger(self, proto):
        pos = _position()
        result = proto.check(pos, {"new_state": "stable"})
        assert result.triggered is False

    # ─── 触发 path B ──────────────────────────────────────────────────────────
    def test_path_b_contradiction_count_ge_3_triggers(self, proto):
        pos = _position()
        ctx = {"narrative_label": "contradiction", "narrative_invalid_count": 3}
        result = proto.check(pos, ctx)
        assert result.triggered is True
        assert result.context["trigger_path"] == "B"

    def test_path_b_count_5_triggers(self, proto):
        pos = _position()
        ctx = {"narrative_label": "contradiction", "narrative_invalid_count": 5}
        result = proto.check(pos, ctx)
        assert result.triggered is True

    def test_path_b_count_2_not_trigger(self, proto):
        pos = _position()
        ctx = {"narrative_label": "contradiction", "narrative_invalid_count": 2}
        result = proto.check(pos, ctx)
        assert result.triggered is False

    def test_path_b_neutral_not_trigger(self, proto):
        pos = _position()
        ctx = {"narrative_label": "neutral", "narrative_invalid_count": 5}
        result = proto.check(pos, ctx)
        assert result.triggered is False

    def test_path_b_missing_count_not_trigger(self, proto):
        pos = _position()
        ctx = {"narrative_label": "contradiction"}  # 缺 invalid_count
        result = proto.check(pos, ctx)
        assert result.triggered is False

    # ─── trigger & output_event ──────────────────────────────────────────────
    def test_trigger_returns_sell_signal(self, proto):
        pos = _position()
        check = proto.check(pos, {"new_state": "exit", "health_change_event_id": "ev-xyz"})
        signal = proto.trigger(pos, check)
        assert signal.protocol_name == SignalType.THESIS_INVALID
        assert signal.priority == 1
        assert signal.sell_ratio == 1.0
        assert "evidence_ref" in signal.extra
        assert signal.extra["evidence_ref"] == "ev-xyz"

    def test_output_event_protocol_sp3(self, proto):
        pos = _position()
        check = proto.check(pos, {"new_state": "exit"})
        signal = proto.trigger(pos, check)
        event = proto.output_event(signal)
        assert event.protocol == "SP3"
        assert "清仓" in event.advice

    # ─── evaluate 一体调用 ────────────────────────────────────────────────────
    def test_evaluate_returns_signal_when_triggered(self, proto):
        pos = _position()
        signal = proto.evaluate(pos, {"new_state": "exit"})
        assert signal is not None

    def test_evaluate_returns_none_when_not_triggered(self, proto):
        pos = _position()
        signal = proto.evaluate(pos, {"new_state": "stable"})
        assert signal is None

    # ─── buffer_days 与 is_revocable ─────────────────────────────────────────
    def test_buffer_days_zero(self, proto):
        assert proto.buffer_days == 0

    def test_trigger_not_revocable(self, proto):
        pos = _position()
        check = proto.check(pos, {"new_state": "exit"})
        signal = proto.trigger(pos, check)
        assert signal.is_revocable is False
