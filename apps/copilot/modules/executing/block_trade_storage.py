"""#21 block_trade_discount · PG 底库 + Redis 热缓存。

[Ref: 28_ §3.2.5 · executing_block_trade_daily]
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingBlockTradeDaily

logger = logging.getLogger(__name__)

BLOCK_TRADE_REDIS_KEY = "executing:block_trade:{symbol}"
BLOCK_TRADE_BACKFILL_KEY = "executing:block_trade:backfill:{symbol}"
BLOCK_TRADE_REDIS_TTL_SEC = 86400 * 14
BLOCK_TRADE_LOOKBACK_TRADING_DAYS = 750
BLOCK_TRADE_MIN_HISTORY_DAYS = 750


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _parse_trade_date(raw: str) -> date:
    s = str(raw).strip().replace("-", "")
    if len(s) == 8:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(str(raw)[:10])


def row_to_dict(row: ExecutingBlockTradeDaily) -> dict[str, Any]:
    return {
        "trade_date": row.trade_date.strftime("%Y%m%d"),
        "vwap_price": float(row.vwap_price),
        "total_vol_wan": float(row.total_vol_wan),
        "total_amount_yuan": float(row.total_amount_yuan),
        "trades_count": int(row.trades_count),
        "close_price": float(row.close_price),
        "free_float_mv_yuan": float(row.free_float_mv_yuan),
        "vwap_discount_rate": float(row.vwap_discount_rate),
        "float_impact_ratio": float(row.float_impact_ratio),
        "buyers_sellers": row.buyers_sellers,
    }


async def count_block_trade_rows(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count()).select_from(ExecutingBlockTradeDaily).where(
            ExecutingBlockTradeDaily.symbol == sym
        )
    )
    return int(n or 0)


async def count_distinct_trade_dates(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count(func.distinct(ExecutingBlockTradeDaily.trade_date))).where(
            ExecutingBlockTradeDaily.symbol == sym
        )
    )
    return int(n or 0)


async def load_block_trade_rows(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    db_rows = (
        await session.scalars(
            select(ExecutingBlockTradeDaily)
            .where(ExecutingBlockTradeDaily.symbol == sym)
            .order_by(ExecutingBlockTradeDaily.trade_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(db_rows, key=lambda r: r.trade_date)
    return [row_to_dict(r) for r in ordered]


async def upsert_block_trade_rows(
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
        existing = await session.get(ExecutingBlockTradeDaily, {"symbol": sym, "trade_date": td})
        payload = {
            "vwap_price": float(r.get("vwap_price") or 0),
            "total_vol_wan": float(r.get("total_vol_wan") or 0),
            "total_amount_yuan": float(r.get("total_amount_yuan") or 0),
            "trades_count": int(r.get("trades_count") or 0),
            "close_price": float(r.get("close_price") or 0),
            "free_float_mv_yuan": float(r.get("free_float_mv_yuan") or 0),
            "vwap_discount_rate": float(r.get("vwap_discount_rate") or 0),
            "float_impact_ratio": float(r.get("float_impact_ratio") or 0),
            "buyers_sellers": r.get("buyers_sellers"),
            "source": source,
            "collected_at": now,
        }
        if existing is None:
            session.add(ExecutingBlockTradeDaily(symbol=sym, trade_date=td, **payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        n += 1
    await session.flush()
    return n


def save_block_trade_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    sym = _sym(symbol)
    body = dict(payload)
    body["cached_at"] = shanghai_now_iso()
    redis_client.setex(
        BLOCK_TRADE_REDIS_KEY.format(symbol=sym),
        BLOCK_TRADE_REDIS_TTL_SEC,
        json.dumps(body, ensure_ascii=False, default=str),
    )


def load_block_trade_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(BLOCK_TRADE_REDIS_KEY.format(symbol=_sym(symbol)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def is_block_trade_backfill_done(redis_client: Any, symbol: str) -> bool:
    if redis_client is None:
        return False
    return bool(redis_client.get(BLOCK_TRADE_BACKFILL_KEY.format(symbol=_sym(symbol))))


def mark_block_trade_backfill_done(redis_client: Any, symbol: str) -> None:
    if redis_client is None:
        return
    redis_client.setex(
        BLOCK_TRADE_BACKFILL_KEY.format(symbol=_sym(symbol)),
        86400 * 365,
        "1",
    )


async def build_payload_from_pg(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    rows = await load_block_trade_rows(session, symbol, limit=limit)
    last_date = rows[-1]["trade_date"] if rows else ""
    return {
        "block_trade_rows": rows,
        "last_update_date": last_date,
        "rows_in_pg": len(rows),
        "history_store": "executing_block_trade_daily",
    }


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("block_trade_rows") or [])
    return {
        "last_update_date": payload.get("last_update_date"),
        "rows_in_pg": payload.get("rows_in_pg", len(rows)),
        "history_store": payload.get("history_store", "executing_block_trade_daily"),
        "block_trade_rows_count": len(rows),
        "block_trade_rows_tail": rows[-3:] if rows else [],
    }
