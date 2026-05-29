"""D4 step_07 ConflictResolver 七场景单测。

[Ref: 03_/04_维度四/.../step_07 §3.5.1 C1~C7]
"""
from __future__ import annotations

import pytest

from apps.exit_engine.models.sell_signal import SellSignalEvent, SignalSeverity, SignalType
from apps.exit_engine.services.conflict_resolver import ConflictResolver


def _ev(signal_type: SignalType, protocol: str | None = None) -> SellSignalEvent:
    return SellSignalEvent(
        symbol="300308",
        signal_type=signal_type,
        trigger_price=10.0,
        current_price=9.0,
        protocol=protocol or signal_type.value,
        advice=f"advice-{signal_type.value}",
        severity=SignalSeverity.EMERGENCY,
        position_id="p1",
    )


@pytest.fixture
def resolver() -> ConflictResolver:
    return ConflictResolver()


def test_c1_sp1_over_sp3(resolver: ConflictResolver):
    """C1: SP1 + SP3 同 priority=1 → stop_loss。"""
    r = resolver.resolve([_ev(SignalType.THESIS_INVALID, "SP3"), _ev(SignalType.STOP_LOSS)])
    assert r.winner is not None
    assert r.winner.signal_type == SignalType.STOP_LOSS
    assert len(r.triggered_protocols) == 2


def test_c2_sp2_over_sp4(resolver: ConflictResolver):
    """C2: SP2 + SP4 → SP2。"""
    r = resolver.resolve([_ev(SignalType.REBALANCE), _ev(SignalType.TAKE_PROFIT)])
    assert r.winner.signal_type == SignalType.TAKE_PROFIT


def test_c3_sp1_over_sp2_sp4(resolver: ConflictResolver):
    """C3: SP1 + SP2 + SP4 → SP1。"""
    events = [
        _ev(SignalType.REBALANCE),
        _ev(SignalType.TAKE_PROFIT),
        _ev(SignalType.STOP_LOSS),
    ]
    r = resolver.resolve(events)
    assert r.winner.signal_type == SignalType.STOP_LOSS


def test_c4_all_four_trigger(resolver: ConflictResolver):
    """C4: 四协议全触发 → SP1；triggered_protocols=4。"""
    events = [
        _ev(SignalType.REBALANCE),
        _ev(SignalType.TAKE_PROFIT),
        _ev(SignalType.THESIS_INVALID, "SP3"),
        _ev(SignalType.STOP_LOSS),
    ]
    r = resolver.resolve(events)
    assert r.winner.signal_type == SignalType.STOP_LOSS
    assert len(r.triggered_protocols) == 4


def test_c5_only_sp4(resolver: ConflictResolver):
    """C5: 仅 SP4 → SP4 直返。"""
    r = resolver.resolve([_ev(SignalType.REBALANCE)])
    assert r.winner.signal_type == SignalType.REBALANCE


def test_c6_zero_trigger(resolver: ConflictResolver):
    """C6: 0 触发 → 无 winner。"""
    r = resolver.resolve([])
    assert r.winner is None
    assert r.triggered_protocols == []


def test_c7_all_recorded_in_resolution(resolver: ConflictResolver):
    """C7: 全部触发入审计列表。"""
    events = [
        _ev(SignalType.FINANCIAL_WINDOW, "SP5"),
        _ev(SignalType.STOP_LOSS),
        _ev(SignalType.THESIS_INVALID, "SP3"),
    ]
    r = resolver.resolve(events)
    assert set(r.triggered_protocols) == {"SP5", "stop_loss", "SP3"}
    assert r.audit_id
