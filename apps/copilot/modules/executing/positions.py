"""user_positions CRUD + 行情浮盈。

[Ref: 28_ §5.3 · 21_]
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import UserPosition

logger = logging.getLogger(__name__)


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


async def get_position(session: AsyncSession, symbol: str) -> UserPosition | None:
    return await session.get(UserPosition, _sym(symbol))


async def list_positions(session: AsyncSession) -> list[UserPosition]:
    return list((await session.scalars(select(UserPosition).order_by(UserPosition.symbol))).all())


async def upsert_position(session: AsyncSession, data: dict[str, Any]) -> UserPosition:
    sym = _sym(str(data["symbol"]))
    row = await session.get(UserPosition, sym)
    if row is None:
        row = UserPosition(symbol=sym, name=str(data.get("name", sym)))
        session.add(row)
    for field in ("name", "quantity", "cost_price", "position_pct", "notes", "source"):
        if field in data and data[field] is not None:
            setattr(row, field, data[field])
    if data.get("opened_at"):
        oa = data["opened_at"]
        if isinstance(oa, str):
            row.opened_at = date.fromisoformat(oa[:10])
        elif isinstance(oa, date):
            row.opened_at = oa
    await session.flush()
    return row


async def delete_position(session: AsyncSession, symbol: str) -> bool:
    row = await session.get(UserPosition, _sym(symbol))
    if row is None:
        return False
    await session.delete(row)
    return True


def fetch_mark_price(symbol: str, redis_client: Any = None) -> tuple[float | None, bool]:
    try:
        if redis_client is not None:
            raw = redis_client.get(f"executing:quote:{_sym(symbol)}")
            if raw:
                import json

                d = json.loads(raw)
                p = float(d.get("close") or 0)
                if p > 0:
                    return p, bool(d.get("is_stale", False))
        from apps.common.market_quote import MarketQuoteClient

        client = MarketQuoteClient()
        q = client.get_realtime([_sym(symbol)]).get(_sym(symbol))
        if q and q.close > 0:
            return q.close, q.is_stale
    except Exception as exc:
        logger.debug("mark price %s: %s", symbol, exc)
    return None, True


async def profit_context(
    session: AsyncSession,
    symbol: str,
    redis_client: Any = None,
) -> dict[str, Any]:
    row = await get_position(session, symbol)
    if row is None:
        return {"symbol": _sym(symbol), "has_position": False}
    price, stale = fetch_mark_price(symbol, redis_client)
    cost = float(row.cost_price or 0)
    pnl = ((price - cost) / cost * 100) if price and cost > 0 else None
    return {
        "symbol": row.symbol,
        "has_position": True,
        "name": row.name,
        "quantity": float(row.quantity),
        "cost_price": cost,
        "position_pct": float(row.position_pct) if row.position_pct is not None else None,
        "mark_price": price,
        "price_stale": stale,
        "unrealized_pnl_pct": round(pnl, 2) if pnl is not None else None,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
    }
