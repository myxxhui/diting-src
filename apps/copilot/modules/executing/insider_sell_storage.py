"""#23 insider_sell_actual · PG 内部人增减持事件底库 + Redis 热缓存。

[Ref: 28_ §3.2.7 · executing_insider_trade_events]
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingInsiderTradeEvent

logger = logging.getLogger(__name__)

INSIDER_REDIS_KEY = "executing:insider_sell:{symbol}"
INSIDER_BACKFILL_KEY = "executing:insider_sell:backfill:{symbol}"
INSIDER_REDIS_TTL_SEC = 86400 * 14
INSIDER_LOOKBACK_CALENDAR_DAYS = 1200


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _parse_date(raw: str | date | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    s = str(raw).strip().replace("-", "")[:8]
    if len(s) == 8:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    return None


def _event_key(r: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(r.get("ann_date", "")),
        str(r.get("trade_date", "")),
        str(r.get("holder_name", "")),
        str(r.get("in_out", "")),
        str(r.get("change_vol_shares", "")),
    )


def row_to_dict(row: ExecutingInsiderTradeEvent) -> dict[str, Any]:
    return {
        "ann_date": row.ann_date.strftime("%Y%m%d"),
        "trade_date": row.trade_date.strftime("%Y%m%d"),
        "holder_name": row.holder_name,
        "holder_type": row.holder_type or "",
        "in_out": row.in_out,
        "change_vol_shares": float(row.change_vol_shares),
    }


async def count_insider_events(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count()).select_from(ExecutingInsiderTradeEvent).where(
            ExecutingInsiderTradeEvent.symbol == sym
        )
    )
    return int(n or 0)


async def load_insider_events(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    db_rows = (
        await session.scalars(
            select(ExecutingInsiderTradeEvent)
            .where(ExecutingInsiderTradeEvent.symbol == sym)
            .order_by(ExecutingInsiderTradeEvent.trade_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(db_rows, key=lambda r: (r.trade_date, r.ann_date))
    return [row_to_dict(r) for r in ordered]


async def upsert_insider_events(
    session: AsyncSession,
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> int:
    sym = _sym(symbol)
    if not rows:
        return 0
    now = utc_now_naive()
    n = 0
    seen: set[tuple[str, str, str, str, str]] = set()
    for r in rows:
        key = _event_key(r)
        if key in seen:
            continue
        seen.add(key)
        ann = _parse_date(r.get("ann_date"))
        td = _parse_date(r.get("trade_date"))
        if ann is None or td is None:
            continue
        holder = str(r.get("holder_name") or "")[:120]
        in_out = str(r.get("in_out") or "").upper()[:8]
        vol = float(r.get("change_vol_shares") or 0)
        existing = await session.scalar(
            select(ExecutingInsiderTradeEvent).where(
                ExecutingInsiderTradeEvent.symbol == sym,
                ExecutingInsiderTradeEvent.ann_date == ann,
                ExecutingInsiderTradeEvent.trade_date == td,
                ExecutingInsiderTradeEvent.holder_name == holder,
                ExecutingInsiderTradeEvent.in_out == in_out,
                ExecutingInsiderTradeEvent.change_vol_shares == vol,
            )
        )
        payload = {
            "holder_type": str(r.get("holder_type") or "")[:32],
            "source": source,
            "collected_at": now,
        }
        if existing is None:
            session.add(
                ExecutingInsiderTradeEvent(
                    symbol=sym,
                    ann_date=ann,
                    trade_date=td,
                    holder_name=holder,
                    in_out=in_out,
                    change_vol_shares=vol,
                    **payload,
                )
            )
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        n += 1
    await session.flush()
    return n


def save_insider_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    body = dict(payload)
    body["cached_at"] = shanghai_now_iso()
    redis_client.setex(
        INSIDER_REDIS_KEY.format(symbol=_sym(symbol)),
        INSIDER_REDIS_TTL_SEC,
        json.dumps(body, ensure_ascii=False, default=str),
    )


def load_insider_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(INSIDER_REDIS_KEY.format(symbol=_sym(symbol)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def is_insider_backfill_done(redis_client: Any, symbol: str) -> bool:
    if redis_client is None:
        return False
    return bool(redis_client.get(INSIDER_BACKFILL_KEY.format(symbol=_sym(symbol))))


def mark_insider_backfill_done(redis_client: Any, symbol: str) -> None:
    if redis_client is None:
        return
    redis_client.setex(
        INSIDER_BACKFILL_KEY.format(symbol=_sym(symbol)),
        86400 * 365,
        "1",
    )


async def build_payload_from_pg(
    session: AsyncSession,
    symbol: str,
    *,
    free_float_shares: float | None = None,
) -> dict[str, Any]:
    events = await load_insider_events(session, symbol)
    return {
        "events": events,
        "event_count": len(events),
        "free_float_shares": free_float_shares,
        "history_store": "executing_insider_trade_events",
    }


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    events = list(payload.get("events") or [])
    return {
        "event_count": payload.get("event_count", len(events)),
        "free_float_shares": payload.get("free_float_shares"),
        "history_store": payload.get("history_store", "executing_insider_trade_events"),
        "events_tail": events[-3:] if events else [],
    }
