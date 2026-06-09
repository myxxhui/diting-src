"""#22 retail_concentration · PG 股东户数快照底库 + Redis 热缓存。

[Ref: 28_ §3.2.6 · executing_retail_holder_snapshots]
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingRetailHolderSnapshot

logger = logging.getLogger(__name__)

RETAIL_REDIS_KEY = "executing:retail_concentration:{symbol}"
RETAIL_REDIS_TTL_SEC = 86400 * 14
RETAIL_MIN_SNAPSHOTS = 12
RETAIL_LOOKBACK_QUARTERS = 12


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


def row_to_dict(row: ExecutingRetailHolderSnapshot) -> dict[str, Any]:
    return {
        "end_date": row.end_date.strftime("%Y%m%d"),
        "announce_date": row.announce_date.strftime("%Y%m%d") if row.announce_date else "",
        "holder_num": float(row.holder_num),
        "previous_holder_num": float(row.previous_holder_num) if row.previous_holder_num else None,
        "holder_num_change": float(row.holder_num_change) if row.holder_num_change is not None else None,
        "avg_hold_vol": float(row.avg_hold_vol) if row.avg_hold_vol is not None else None,
        "free_float_shares": float(row.free_float_shares) if row.free_float_shares else None,
    }


async def count_retail_snapshots(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count()).select_from(ExecutingRetailHolderSnapshot).where(
            ExecutingRetailHolderSnapshot.symbol == sym
        )
    )
    return int(n or 0)


async def load_retail_snapshots(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    db_rows = (
        await session.scalars(
            select(ExecutingRetailHolderSnapshot)
            .where(ExecutingRetailHolderSnapshot.symbol == sym)
            .order_by(ExecutingRetailHolderSnapshot.end_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(db_rows, key=lambda r: r.end_date)
    return [row_to_dict(r) for r in ordered]


async def upsert_retail_snapshots(
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
        ed = _parse_date(r.get("end_date"))
        if ed is None:
            continue
        ad = _parse_date(r.get("announce_date"))
        existing = await session.get(
            ExecutingRetailHolderSnapshot, {"symbol": sym, "end_date": ed}
        )
        payload = {
            "announce_date": ad,
            "holder_num": float(r.get("holder_num") or 0),
            "previous_holder_num": (
                float(r["previous_holder_num"]) if r.get("previous_holder_num") is not None else None
            ),
            "holder_num_change": (
                float(r["holder_num_change"]) if r.get("holder_num_change") is not None else None
            ),
            "avg_hold_vol": float(r["avg_hold_vol"]) if r.get("avg_hold_vol") is not None else None,
            "free_float_shares": (
                float(r["free_float_shares"]) if r.get("free_float_shares") is not None else None
            ),
            "source": source,
            "collected_at": now,
        }
        if existing is None:
            session.add(ExecutingRetailHolderSnapshot(symbol=sym, end_date=ed, **payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
        n += 1
    await session.flush()
    return n


def save_retail_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    body = dict(payload)
    body["cached_at"] = shanghai_now_iso()
    redis_client.setex(
        RETAIL_REDIS_KEY.format(symbol=_sym(symbol)),
        RETAIL_REDIS_TTL_SEC,
        json.dumps(body, ensure_ascii=False, default=str),
    )


def load_retail_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(RETAIL_REDIS_KEY.format(symbol=_sym(symbol)))
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
) -> dict[str, Any]:
    rows = await load_retail_snapshots(session, symbol)
    return {
        "snapshots": rows,
        "snapshot_count": len(rows),
        "history_store": "executing_retail_holder_snapshots",
    }


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("snapshots") or [])
    return {
        "snapshot_count": payload.get("snapshot_count", len(rows)),
        "history_store": payload.get("history_store", "executing_retail_holder_snapshots"),
        "snapshots_tail": rows[-2:] if rows else [],
    }
