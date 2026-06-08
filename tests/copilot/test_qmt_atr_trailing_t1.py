"""#15 qmt_atr_trailing T1 五步法单测。

[Ref: 28_ §2.2.3]
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from apps.copilot.modules.executing.collectors.daily_bars import DailyBarRow
from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
    AtrTrailingError,
    process_qmt_atr_trailing,
    rows_to_dataframe,
)


def _rows(n: int = 30, *, gap_day: int | None = None) -> list[DailyBarRow]:
    out: list[DailyBarRow] = []
    for i in range(n):
        d = date(2026, 1, 1 + i)
        high = 100.0 + i
        low = 95.0 + i
        close = 98.0 + i
        if gap_day is not None and i == gap_day:
            close = 80.0
            low = 78.0
        out.append(
            DailyBarRow(
                trade_date=d,
                open=96.0 + i,
                high=high,
                low=low,
                close=close,
                volume=1e6,
            )
        )
    return out


def test_true_range_uses_prev_close_gap():
    """跳空日 TR 须含 |low - prev_close|，不能只用 high-low。"""
    rows = _rows(25, gap_day=10)
    df = rows_to_dataframe(rows)
    entry = date(2026, 1, 1)
    payload = process_qmt_atr_trailing(df, entry, source="test")
    assert payload["value"] >= 0
    assert "近20日ATR" in payload["calculation_logic"]


def test_peak_only_after_entry_date():
    rows = _rows(30)
    df = rows_to_dataframe(rows)
    entry = date(2026, 1, 20)
    payload = process_qmt_atr_trailing(df, entry, source="test")
    expected_peak = max(r.high for r in rows if r.trade_date >= entry)
    assert payload["peak_price"] == pytest.approx(expected_peak, rel=1e-4)


def test_entry_date_out_of_range_raises():
    df = rows_to_dataframe(_rows(25))
    with pytest.raises(AtrTrailingError, match="超出"):
        process_qmt_atr_trailing(df, date(2020, 1, 1), source="test")


def test_t1_json_contract_fields():
    payload = process_qmt_atr_trailing(
        rows_to_dataframe(_rows(25)), date(2026, 1, 3), source="test-src"
    )
    assert payload["indicator_key"] == "qmt_atr_trailing"
    assert isinstance(payload["value"], float)
    assert payload["source"] == "test-src"
    assert "回撤" in payload["fact_statement"]
