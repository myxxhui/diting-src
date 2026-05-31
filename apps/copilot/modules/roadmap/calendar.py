"""交易日历工具（T0 · 启动期工作日近似降级）。

[Ref: step_15 §3.1 · §12]
"""
from __future__ import annotations

from datetime import date, timedelta


def trading_days_between(start: date, end: date) -> int:
    """start 与 end 之间交易日数（含 end 当日若其为交易日）。"""
    if end < start:
        start, end = end, start
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        days = {date.fromisoformat(str(d)[:10]) for d in df[col].tolist()}
        return sum(1 for d in _daterange(start, end) if d in days)
    except Exception:  # noqa: BLE001
        return _weekday_approx(start, end)


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _weekday_approx(start: date, end: date) -> int:
    n = 0
    for d in _daterange(start, end):
        if d.weekday() < 5:
            n += 1
    return n
