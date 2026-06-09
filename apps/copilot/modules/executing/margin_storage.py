"""#19 margin_short_skew · PG 底库 + Redis 热缓存。

[Ref: 28_ §3.2.3 · executing_margin_daily]
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingMarginDaily

logger = logging.getLogger(__name__)

MARGIN_REDIS_KEY = "executing:margin:{symbol}"
MARGIN_REDIS_TTL_SEC = 86400 * 14
MARGIN_TARGET_TRADING_DAYS = 250
MARGIN_MIN_TRADING_DAYS = 250


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _parse_trade_date(raw: str) -> date:
    s = str(raw).strip().replace("-", "")
    if len(s) == 8:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(str(raw)[:10])


def row_to_dict(row: ExecutingMarginDaily) -> dict[str, Any]:
    return {
        "trade_date": row.trade_date.strftime("%Y%m%d"),
        "rzye": float(row.rzye),
        "rqye": float(row.rqye),
        "rzmre": float(row.rzmre),
        "margin_short_ratio": float(row.margin_short_ratio) if row.margin_short_ratio is not None else None,
        "free_float_mkt_cap": float(row.free_float_mkt_cap) if row.free_float_mkt_cap else None,
        "margin_to_float_ratio": float(row.margin_to_float_ratio)
        if row.margin_to_float_ratio is not None
        else None,
    }


async def count_margin_rows(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count()).select_from(ExecutingMarginDaily).where(ExecutingMarginDaily.symbol == sym)
    )
    return int(n or 0)


async def load_margin_rows(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = MARGIN_TARGET_TRADING_DAYS,
) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    db_rows = (
        await session.scalars(
            select(ExecutingMarginDaily)
            .where(ExecutingMarginDaily.symbol == sym)
            .order_by(ExecutingMarginDaily.trade_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(db_rows, key=lambda r: r.trade_date)
    return [row_to_dict(r) for r in ordered]


async def upsert_margin_rows(
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
    for r in rows:
        td = _parse_trade_date(str(r.get("trade_date", "")))
        existing = await session.get(ExecutingMarginDaily, {"symbol": sym, "trade_date": td})
        payload = {
            "rzye": float(r.get("rzye") or 0),
            "rqye": float(r.get("rqye") or 0),
            "rzmre": float(r.get("rzmre") or 0),
            "margin_short_ratio": r.get("margin_short_ratio"),
            "free_float_mkt_cap": r.get("free_float_mkt_cap"),
            "margin_to_float_ratio": r.get("margin_to_float_ratio"),
            "source": source,
            "collected_at": now,
        }
        if existing is None:
            session.add(ExecutingMarginDaily(symbol=sym, trade_date=td, **payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        n += 1
    await session.flush()
    return n


def save_margin_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    sym = _sym(symbol)
    body = dict(payload)
    body["cached_at"] = shanghai_now_iso()
    redis_client.setex(
        MARGIN_REDIS_KEY.format(symbol=sym),
        MARGIN_REDIS_TTL_SEC,
        json.dumps(body, ensure_ascii=False),
    )


def load_margin_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(MARGIN_REDIS_KEY.format(symbol=_sym(symbol)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def build_payload_from_pg(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = MARGIN_TARGET_TRADING_DAYS,
) -> dict[str, Any]:
    rows = await load_margin_rows(session, symbol, limit=limit)
    last_date = rows[-1]["trade_date"] if rows else ""
    return {
        "margin_rows": rows,
        "last_update_date": last_date,
        "rows_in_pg": len(rows),
        "history_store": "executing_margin_daily",
    }


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("margin_rows") or [])
    return {
        "last_update_date": payload.get("last_update_date"),
        "inferred_trade_date": payload.get("inferred_trade_date"),
        "settlement_lag_days": payload.get("settlement_lag_days"),
        "rows_in_pg": payload.get("rows_in_pg", len(rows)),
        "history_store": payload.get("history_store", "executing_margin_daily"),
        "margin_rows_count": len(rows),
        "margin_rows_tail": rows[-3:] if rows else [],
    }
