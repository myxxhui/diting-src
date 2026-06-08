"""统一货币单位单测。"""
from __future__ import annotations

from apps.copilot.modules.executing.money_unit import (
    EXECUTING_MONEY_UNIT,
    attach_money_unit,
    format_price_display,
    round_price,
)


def test_money_unit_in_batch_meta():
    meta = attach_money_unit({"execution_id": "x"})
    assert meta["money_unit"] == EXECUTING_MONEY_UNIT == "人民币"
    assert format_price_display(70.48) == "70.48元"
    assert round_price(56.8213) == 56.82
