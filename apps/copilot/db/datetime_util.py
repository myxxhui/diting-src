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


def shanghai_now() -> datetime:
    """Cron/盘中热数据日志用北京时间（Asia/Shanghai）。"""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai"))


def shanghai_today():
    """A 股交易日对齐用北京时间日历日。"""
    return shanghai_now().date()


def shanghai_now_iso() -> str:
    return shanghai_now().strftime("%Y-%m-%d %H:%M:%S")


def utc_naive_to_shanghai_display(dt: datetime | str | None) -> str | None:
    """DB/API 的 naive UTC → 北京时间展示串（YYYY-MM-DD HH:MM:SS）。"""
    if dt is None:
        return None
    from zoneinfo import ZoneInfo

    if isinstance(dt, str):
        raw = dt.strip().replace("Z", "")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return dt
        dt = parsed
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return aware.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
