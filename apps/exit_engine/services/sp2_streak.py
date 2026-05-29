"""SP2 连续交易日缓冲计数（pending n/3 → 触发）.

[Ref: 03_/04_维度四/.../step_04_SP2止盈协议.md §3.5 L2~L5]
"""
from __future__ import annotations

from datetime import date

from apps.exit_engine.services.trading_calendar import previous_trading_day, trading_days_before


def buffer_state_label(streak: int, buffer_days: int, *, hit_today: bool) -> str:
    if not hit_today:
        return "not_met"
    if streak < buffer_days:
        return f"pending_{streak}_{buffer_days}"
    return "triggered"


def count_consecutive_hits(hit_by_date: dict[date, bool], before: date) -> int:
    """统计 before 之前（不含 before）从最近交易日往回连续 hit 天数."""
    count = 0
    cur = before
    while True:
        cur = previous_trading_day(cur)
        if hit_by_date.get(cur):
            count += 1
        else:
            break
        if count > 365:
            break
    return count


def evaluate_streak(
    *,
    hit_today: bool,
    hit_by_date: dict[date, bool],
    trade_date: date,
    buffer_days: int,
) -> tuple[str, bool, int]:
    """返回 (buffer_state, should_trigger, streak_including_today)."""
    if not hit_today:
        return "not_met", False, 0
    prior = count_consecutive_hits(hit_by_date, trade_date)
    streak = prior + 1
    state = buffer_state_label(streak, buffer_days, hit_today=True)
    should_trigger = streak >= buffer_days
    return state, should_trigger, streak


def warmup_trading_dates(end: date, buffer_days: int) -> list[date]:
    """预热评估用的最近 buffer_days 个交易日（含 end）."""
    days = trading_days_before(end, buffer_days - 1)
    return sorted(days + [end])
