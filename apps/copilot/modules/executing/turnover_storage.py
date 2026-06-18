"""#20 turnover_acceleration · PG 底库 + Redis 热缓存。

[Ref: 28_ §3.2.4 · executing_turnover_daily]
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingTurnoverDaily

logger = logging.getLogger(__name__)

TURNOVER_REDIS_KEY = "executing:turnover:{symbol}"
TURNOVER_REDIS_TTL_SEC = 86400 * 14
TURNOVER_TARGET_TRADING_DAYS = 140
TURNOVER_MIN_TRADING_DAYS = 120
TURNOVER_BASELINE_DAYS = 20
TURNOVER_PERCENTILE_WINDOW = 120


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _parse_trade_date(raw: str) -> date:
    s = str(raw).strip().replace("-", "")
    if len(s) == 8:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(str(raw)[:10])


def row_to_dict(row: ExecutingTurnoverDaily) -> dict[str, Any]:
    return {
        "trade_date": row.trade_date.strftime("%Y%m%d"),
        "turnover_rate_f": float(row.turnover_rate_f),
        "volume_ratio": float(row.volume_ratio) if row.volume_ratio is not None else None,
    }


async def count_turnover_rows(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count()).select_from(ExecutingTurnoverDaily).where(ExecutingTurnoverDaily.symbol == sym)
    )
    return int(n or 0)


async def load_turnover_rows(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = TURNOVER_TARGET_TRADING_DAYS,
) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    db_rows = (
        await session.scalars(
            select(ExecutingTurnoverDaily)
            .where(ExecutingTurnoverDaily.symbol == sym)
            .order_by(ExecutingTurnoverDaily.trade_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(db_rows, key=lambda r: r.trade_date)
    return [row_to_dict(r) for r in ordered]


async def upsert_turnover_rows(
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
        rate = r.get("turnover_rate_f")
        if rate is None:
            continue
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            continue
        if math.isnan(rate_f) or rate_f <= 0:
            continue
        td = _parse_trade_date(str(r.get("trade_date", "")))
        existing = await session.get(ExecutingTurnoverDaily, {"symbol": sym, "trade_date": td})
        payload: dict[str, Any] = {
            "turnover_rate_f": rate_f,
            "volume_ratio": r.get("volume_ratio"),
            "source": source,
            "collected_at": now,
        }
        if existing is None:
            session.add(ExecutingTurnoverDaily(symbol=sym, trade_date=td, **payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        n += 1
    await session.flush()
    return n


def save_turnover_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    sym = _sym(symbol)
    body = dict(payload)
    body["cached_at"] = shanghai_now_iso()
    redis_client.setex(
        TURNOVER_REDIS_KEY.format(symbol=sym),
        TURNOVER_REDIS_TTL_SEC,
        json.dumps(body, ensure_ascii=False),
    )


def load_turnover_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(TURNOVER_REDIS_KEY.format(symbol=_sym(symbol)))
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
    limit: int = TURNOVER_TARGET_TRADING_DAYS,
) -> dict[str, Any]:
    rows = await load_turnover_rows(session, symbol, limit=limit)
    last_date = rows[-1]["trade_date"] if rows else ""
    return {
        "turnover_rows": rows,
        "last_update_date": last_date,
        "rows_in_pg": len(rows),
        "history_store": "executing_turnover_daily",
    }


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("turnover_rows") or [])
    return {
        "last_update_date": payload.get("last_update_date"),
        "rows_in_pg": payload.get("rows_in_pg", len(rows)),
        "history_store": payload.get("history_store", "executing_turnover_daily"),
        "turnover_rows_count": len(rows),
        "turnover_rows_tail": rows[-3:] if rows else [],
    }
