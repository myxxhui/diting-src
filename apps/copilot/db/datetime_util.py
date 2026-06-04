"""PostgreSQL TIMESTAMP WITHOUT TIME ZONE / asyncpg 兼容的 UTC 时间工具。"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_naive_for_db(dt: datetime | None) -> datetime | None:
    """写入 naive UTC，避免 asyncpg 对 TIMESTAMP WITHOUT TIME ZONE 报 offset 混用错误。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def utc_now_naive() -> datetime:
    return utc_naive_for_db(datetime.now(timezone.utc))  # type: ignore[return-value]


def as_utc_aware(dt: datetime) -> datetime:
    """比较/算龄时用 aware UTC；兼容 DB 读出的 naive UTC。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
