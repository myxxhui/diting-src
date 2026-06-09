"""#25 tech_beta_correlation · PG 底库 + Redis 热缓存。

[Ref: 28_ §2.2.8 · executing_beta_correlation_daily]
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingBetaCorrelationDaily

logger = logging.getLogger(__name__)

BETA_REDIS_KEY = "executing:beta_corr:{symbol}"
BETA_REDIS_TTL_SEC = 86400 * 14
BETA_MIN_TRADING_DAYS = 120
BETA_LOOKBACK_WINDOW = 60
BETA_TARGET_TRADING_DAYS = 150


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _parse_trade_date(raw: str) -> date:
    s = str(raw).strip().replace("-", "")
    if len(s) == 8:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(str(raw)[:10])


def row_to_dict(row: ExecutingBetaCorrelationDaily) -> dict[str, Any]:
    return {
        "trade_date": row.trade_date.strftime("%Y%m%d"),
        "sector_index_code": row.sector_index_code,
        "stock_pct_chg": float(row.stock_pct_chg),
        "index_pct_chg": float(row.index_pct_chg),
    }


async def count_beta_rows(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count())
        .select_from(ExecutingBetaCorrelationDaily)
        .where(ExecutingBetaCorrelationDaily.symbol == sym)
    )
    return int(n or 0)


async def load_beta_rows(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = BETA_TARGET_TRADING_DAYS,
) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    db_rows = (
        await session.scalars(
            select(ExecutingBetaCorrelationDaily)
            .where(ExecutingBetaCorrelationDaily.symbol == sym)
            .order_by(ExecutingBetaCorrelationDaily.trade_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(db_rows, key=lambda r: r.trade_date)
    return [row_to_dict(r) for r in ordered]


async def upsert_beta_rows(
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
        existing = await session.get(
            ExecutingBetaCorrelationDaily, {"symbol": sym, "trade_date": td}
        )
        payload = {
            "sector_index_code": str(r.get("sector_index_code") or ""),
            "stock_pct_chg": float(r.get("stock_pct_chg") or 0),
            "index_pct_chg": float(r.get("index_pct_chg") or 0),
            "source": source,
            "collected_at": now,
        }
        if existing is None:
            session.add(ExecutingBetaCorrelationDaily(symbol=sym, trade_date=td, **payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        n += 1
    await session.flush()
    return n


def save_beta_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    sym = _sym(symbol)
    body = dict(payload)
    body["cached_at"] = shanghai_now_iso()
    redis_client.setex(
        BETA_REDIS_KEY.format(symbol=sym),
        BETA_REDIS_TTL_SEC,
        json.dumps(body, ensure_ascii=False),
    )


def load_beta_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(BETA_REDIS_KEY.format(symbol=_sym(symbol)))
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
    sector_index_code: str,
    sector_index_name: str = "",
    limit: int = BETA_TARGET_TRADING_DAYS,
) -> dict[str, Any]:
    rows = await load_beta_rows(session, symbol, limit=limit)
    last_date = rows[-1]["trade_date"] if rows else ""
    return {
        "aligned_rows": rows,
        "last_update_date": last_date,
        "rows_in_pg": len(rows),
        "sector_index_code": sector_index_code,
        "sector_index_name": sector_index_name,
        "history_store": "executing_beta_correlation_daily",
    }


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("aligned_rows") or [])
    return {
        "last_update_date": payload.get("last_update_date"),
        "rows_in_pg": payload.get("rows_in_pg", len(rows)),
        "sector_index_code": payload.get("sector_index_code"),
        "sector_index_name": payload.get("sector_index_name"),
        "history_store": payload.get("history_store", "executing_beta_correlation_daily"),
        "aligned_rows_count": len(rows),
        "aligned_rows_tail": rows[-3:] if rows else [],
    }
