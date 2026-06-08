"""执行区标的基础数据 · user_positions ↔ executing_collect_symbols 同步。

[Ref: 28_ §5.3]
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import ExecutingCollectSymbol, UserPosition
from apps.copilot.modules.executing.positions import _sym


def _parse_opened_at(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return None


async def save_symbol_base_data(
    session: AsyncSession,
    data: dict[str, Any],
    *,
    enabled: bool = True,
    profile: str = "601138",
    funnel_stage: str | None = "executing",
) -> tuple[UserPosition, ExecutingCollectSymbol]:
    """写入标的基础数据：同步 user_positions 与 executing_collect_symbols。"""
    sym = _sym(str(data["symbol"]))
    opened = _parse_opened_at(data.get("opened_at"))

    pos = await session.get(UserPosition, sym)
    if pos is None:
        pos = UserPosition(symbol=sym, name=str(data.get("name") or sym), source="ui")
        session.add(pos)
    for field in ("name", "quantity", "cost_price", "position_pct", "notes", "source"):
        if field in data and data[field] is not None:
            setattr(pos, field, data[field])
    if opened is not None:
        pos.opened_at = opened
    elif "opened_at" in data and data["opened_at"] in (None, ""):
        pos.opened_at = None

    coll = await session.get(ExecutingCollectSymbol, sym)
    if coll is None:
        coll = ExecutingCollectSymbol(
            symbol=sym,
            profile=profile,
            enabled=enabled,
            funnel_stage=funnel_stage,
            name=str(data.get("name") or sym),
        )
        session.add(coll)
    else:
        coll.enabled = enabled
        if profile:
            coll.profile = profile
        if funnel_stage:
            coll.funnel_stage = funnel_stage

    coll.name = str(data.get("name") or pos.name or sym)
    if "quantity" in data and data["quantity"] is not None:
        coll.quantity = float(data["quantity"])
    else:
        coll.quantity = float(pos.quantity or 0)
    if "cost_price" in data and data["cost_price"] is not None:
        coll.cost_price = float(data["cost_price"])
    else:
        coll.cost_price = float(pos.cost_price or 0)
    if "position_pct" in data:
        coll.position_pct = (
            float(data["position_pct"]) if data.get("position_pct") is not None else None
        )
    elif pos.position_pct is not None:
        coll.position_pct = float(pos.position_pct)
    coll.opened_at = opened if opened is not None else pos.opened_at
    if data.get("notes") is not None:
        coll.notes = data.get("notes")

    await session.flush()
    return pos, coll


async def load_symbol_base(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """读取单标的合并基础数据（collect 与 position 字段并集）。"""
    sym = _sym(symbol)
    coll = await session.get(ExecutingCollectSymbol, sym)
    pos = await session.get(UserPosition, sym)
    if coll is None and pos is None:
        return {"symbol": sym, "has_base": False}

    def _pick(attr: str, default=None):
        for row in (coll, pos):
            if row is None:
                continue
            v = getattr(row, attr, None)
            if v is not None and v != "":
                return v
        return default

    opened = _pick("opened_at")
    pct = _pick("position_pct")
    return {
        "symbol": sym,
        "has_base": True,
        "name": _pick("name") or sym,
        "quantity": float(_pick("quantity") or 0),
        "cost_price": float(_pick("cost_price") or 0),
        "position_pct": float(pct) if pct is not None else None,
        "opened_at": opened.isoformat() if hasattr(opened, "isoformat") else opened,
        "notes": _pick("notes"),
        "enabled": coll.enabled if coll else True,
    }
