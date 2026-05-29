"""交易时段与 stale 判定。"""
from __future__ import annotations

from datetime import datetime, time


def is_market_hours(dt: datetime) -> bool:
    t = dt.time()
    morning = time(9, 30) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 0)
    return morning or afternoon


def compute_is_stale(quote_ts: datetime, now: datetime | None = None) -> bool:
    """闭市时段且数据时间戳与当前差 > 30 分钟 → stale。"""
    now = now or datetime.now()
    if is_market_hours(now):
        return False
    return (now - quote_ts).total_seconds() > 30 * 60


def kline_cache_ttl_sec(now: datetime | None = None) -> int:
    """K 线缓存 TTL：开市 30s / 闭市 1h。"""
    now = now or datetime.now()
    return 30 if is_market_hours(now) else 3600
