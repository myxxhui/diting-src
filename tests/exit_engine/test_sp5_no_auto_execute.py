"""SP5 永久 no-auto-execute 单测（AU1~AU3）。

[Ref: 03_/04_维度四/.../step_05 §11 AU1~AU3]
"""
from __future__ import annotations

from dataclasses import fields

from apps.exit_engine.models.sell_signal import SellSignalEvent
from apps.exit_engine.protocols.sp5_financial_window import Sp5FinancialWindowProtocol


def _position(symbol="300308", pos_id="p-sp5"):
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class _Pos:
        id: str
        symbol: str
        name: str
        cost_price: float
        current_price: Optional[float]

    return _Pos(id=pos_id, symbol=symbol, name="中际旭创", cost_price=100.0, current_price=110.0)


FORBIDDEN = {
    "buy", "execute", "order_id", "auto_trade", "qmt_signal",
    "webhook_target", "webhook", "auto_buy", "auto_execute",
}


def test_event_schema_clean():
    """AU1：SellSignalEvent 无禁词字段。"""
    names = {f.name for f in fields(SellSignalEvent)}
    assert names.isdisjoint(FORBIDDEN), f"禁字段: {names & FORBIDDEN}"


def test_sp5_output_no_forbidden_in_advice():
    proto = Sp5FinancialWindowProtocol()
    pos = _position()
    for stage in ("left_accumulate", "main_wave", "retreat"):
        check = proto.check(pos, {"stage": stage, "evidence_url": "https://example.com/report"})
        signal = proto.trigger(pos, check)
        event = proto.output_event(signal)
        blob = (signal.advice + signal.reason + str(signal.extra)).lower()
        for word in ("建仓量", "止损位", "买入价", "卖出价", "qmt", "auto_trade"):
            assert word not in blob


def test_sp5_sell_ratio_zero():
    """SP5 仅 advice，sell_ratio=0。"""
    proto = Sp5FinancialWindowProtocol()
    pos = _position()
    check = proto.check(pos, {"stage": "retreat"})
    signal = proto.trigger(pos, check)
    assert signal.sell_ratio == 0.0
    assert signal.extra.get("execute_mode") == "advisory"


def test_sp5_three_stages_trigger():
    proto = Sp5FinancialWindowProtocol()
    pos = _position()
    for stage in ("left_accumulate", "main_wave", "retreat"):
        assert proto.check(pos, {"stage": stage}).triggered is True
