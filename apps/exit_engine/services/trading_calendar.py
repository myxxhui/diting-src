"""简易 A 股交易日历（启动期：跳过周末，不含法定假日）.

[Ref: 03_/04_维度四/.../step_04_SP2止盈协议.md §3.5 E4]
"""
from __future__ import annotations

from datetime import date, timedelta


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5


def previous_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def trading_days_before(d: date, n: int) -> list[date]:
    """返回 d 之前（不含 d）最近 n 个交易日，由近到远."""
    out: list[date] = []
    cur = d
    while len(out) < n:
        cur = previous_trading_day(cur)
        out.append(cur)
    return out
