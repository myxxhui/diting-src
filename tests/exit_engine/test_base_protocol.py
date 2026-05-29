"""BaseProtocol 与占位协议契约测试.[Ref: step_01]"""
from __future__ import annotations

import pytest

from apps.exit_engine.models.sell_signal import SignalType
from apps.exit_engine.protocols import (
    PROTOCOL_CLASSES,
    BaseProtocol,
    CheckResult,
    RebalanceProtocol,
    Sp5FinancialWindowProtocol,
    StopLossProtocol,
    TakeProfitProtocol,
    ThesisInvalidProtocol,
)


def test_all_protocols_inherit_base() -> None:
    for cls in PROTOCOL_CLASSES:
        assert issubclass(cls, BaseProtocol)


def test_protocols_have_required_attrs() -> None:
    expected = {
        StopLossProtocol: (SignalType.STOP_LOSS, 1, 0),
        TakeProfitProtocol: (SignalType.TAKE_PROFIT, 2, 3),
        ThesisInvalidProtocol: (SignalType.THESIS_INVALID, 1, 0),
        RebalanceProtocol: (SignalType.REBALANCE, 3, 7),
        Sp5FinancialWindowProtocol: (SignalType.FINANCIAL_WINDOW, 3, 0),
    }
    for cls, (name, priority, buffer) in expected.items():
        assert cls.protocol_name == name
        inst = cls()
        assert inst.priority == priority
        assert inst.buffer_days == buffer


def test_implemented_protocols_handle_empty_context(position_factory) -> None:
    """SP3/SP4 已完整实现，空 context 应优雅返回 CheckResult(triggered=False) 而不是 NotImplementedError。"""
    pos = position_factory()
    for cls in (ThesisInvalidProtocol, RebalanceProtocol):
        instance = cls()
        result = instance.check(pos, {})
        assert result is not None
        assert result.triggered is False, f"{cls.__name__}.check({{}}) 应返回 triggered=False"


def test_base_protocol_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseProtocol()  # type: ignore[abstract]


def test_check_result_structure() -> None:
    r = CheckResult(triggered=True, context={"foo": "bar"})
    assert r.triggered is True
    assert r.context == {"foo": "bar"}
