"""user_positions CRUD + 行情浮盈。

[Ref: 28_ §5.3 · 21_]
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import UserPosition

logger = logging.getLogger(__name__)


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


async def get_position(session: AsyncSession, symbol: str) -> UserPosition | None:
    return await session.get(UserPosition, _sym(symbol))


async def get_position_opened_at(session: AsyncSession, symbol: str):
    """建仓日（#15 峰值窗）。"""
    row = await get_position(session, symbol)
    return row.opened_at if row else None


async def list_positions(session: AsyncSession) -> list[UserPosition]:
    return list((await session.scalars(select(UserPosition).order_by(UserPosition.symbol))).all())


async def upsert_position(session: AsyncSession, data: dict[str, Any]) -> UserPosition:
    from apps.copilot.modules.executing.symbol_base import save_symbol_base_data

    data = dict(data)
    data.setdefault("source", "ui")
    row, _ = await save_symbol_base_data(session, data)
    return row


async def delete_position(session: AsyncSession, symbol: str) -> bool:
    row = await session.get(UserPosition, _sym(symbol))
    if row is None:
        return False
    await session.delete(row)
    return True


def _parse_executing_quote(raw: str) -> tuple[float | None, bool, str | None]:
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return None, True, None
    p = float(d.get("close") or 0)
    if p <= 0:
        return None, True, None
    as_of = d.get("collected_at") or d.get("trade_date")
    return p, bool(d.get("is_stale", False)), str(as_of) if as_of else None


def fetch_mark_price(
    symbol: str,
    redis_client: Any = None,
) -> tuple[float | None, bool, str | None]:
    """现价：executing:quote → executing:draft_bar（热数据同源）→ MarketQuoteClient。

    返回 (price, is_stale, as_of_hint)。
    """
    sym = _sym(symbol)
    if redis_client is not None:
        raw = redis_client.get(f"executing:quote:{sym}")
        if raw:
            price, stale, as_of = _parse_executing_quote(raw)
            if price is not None:
                return price, stale, as_of

        from apps.copilot.db.datetime_util import shanghai_today
        from apps.copilot.modules.executing.collectors.intraday_draft import load_draft_bar_dict

        draft_meta = load_draft_bar_dict(redis_client, sym)
        if draft_meta:
            close = float(draft_meta.get("close") or 0)
            if close > 0:
                td = str(draft_meta.get("trade_date") or "")
                today = shanghai_today().isoformat()
                stale = td != today
                as_of = draft_meta.get("collected_at") or td or None
                return close, stale, str(as_of) if as_of else None

    try:
        from apps.common.market_quote import MarketQuoteClient

        client = MarketQuoteClient()
        q = client.get_realtime([sym]).get(sym)
        if q and q.close > 0:
            return q.close, q.is_stale, None
    except Exception as exc:
        logger.debug("mark price %s: %s", symbol, exc)
    return None, True, None


def overlay_intraday_qmt_price(
    qmt_node: dict[str, Any] | None,
    *,
    mark_price: float | None,
    mark_as_of: str | None,
    stale: bool,
) -> dict[str, Any] | None:
    """PG 快照 #15 节点叠加 Redis 热数据现价（层 B 与层 A 对齐）。"""
    if not isinstance(qmt_node, dict) or mark_price is None:
        return qmt_node
    from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import SOURCE_INTRADAY

    node = dict(qmt_node)
    rm = dict(node.get("raw_metrics") or {})
    rm["current_price"] = round(float(mark_price), 2)
    if mark_as_of and not stale:
        rm["last_tick_time"] = mark_as_of
        node["source"] = SOURCE_INTRADAY
    node["raw_metrics"] = rm
    return node


async def profit_context(
    session: AsyncSession,
    symbol: str,
    redis_client: Any = None,
) -> dict[str, Any]:
    row = await get_position(session, symbol)
    if row is None:
        from apps.copilot.modules.executing.symbol_base import load_symbol_base

        base = await load_symbol_base(session, symbol)
        if not base.get("has_base"):
            return {"symbol": _sym(symbol), "has_position": False}
        price, stale, as_of = fetch_mark_price(symbol, redis_client)
        cost = float(base.get("cost_price") or 0)
        pnl = ((price - cost) / cost * 100) if price and cost > 0 else None
        return {
            "symbol": base["symbol"],
            "has_position": True,
            "name": base.get("name"),
            "quantity": float(base.get("quantity") or 0),
            "cost_price": cost,
            "position_pct": base.get("position_pct"),
            "mark_price": price,
            "mark_price_as_of": as_of,
            "price_stale": stale,
            "unrealized_pnl_pct": round(pnl, 2) if pnl is not None else None,
            "opened_at": base.get("opened_at"),
        }
    price, stale, as_of = fetch_mark_price(symbol, redis_client)
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
        "mark_price_as_of": as_of,
        "price_stale": stale,
        "unrealized_pnl_pct": round(pnl, 2) if pnl is not None else None,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
    }
