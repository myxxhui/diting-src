"""executing_collect_symbols SoT。

[Ref: 28_ §4.2]
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import ExecutingCollectSymbol

logger = logging.getLogger(__name__)


async def load_executing_collect_symbols(session: AsyncSession) -> list[str]:
    rows = (
        await session.scalars(
            select(ExecutingCollectSymbol.symbol).where(ExecutingCollectSymbol.enabled.is_(True))
        )
    ).all()
    if not rows:
        logger.info("executing_collect_empty")
    return [str(s).zfill(6)[-6:] for s in rows]


async def enroll_executing_collect(
    session: AsyncSession,
    symbol: str,
    *,
    profile: str = "601138",
    name: str | None = None,
    funnel_stage: str | None = "executing",
) -> ExecutingCollectSymbol:
    """仅入采集宇宙 · 不要求层 A 持仓完备（待建仓可开层 B 独立 JL4）。"""
    sym = symbol.zfill(6)[-6:]
    coll = await session.get(ExecutingCollectSymbol, sym)
    if coll is None:
        coll = ExecutingCollectSymbol(
            symbol=sym,
            profile=profile,
            enabled=True,
            funnel_stage=funnel_stage,
            name=name or sym,
        )
        session.add(coll)
    else:
        coll.enabled = True
        if profile:
            coll.profile = profile
        if funnel_stage:
            coll.funnel_stage = funnel_stage
        if name:
            coll.name = name
    await session.flush()
    return coll


async def upsert_executing_collect(
    session: AsyncSession,
    symbol: str,
    *,
    profile: str = "601138",
    funnel_stage: str | None = "executing",
    enabled: bool = True,
    name: str | None = None,
    quantity: float | None = None,
    cost_price: float | None = None,
    position_pct: float | None = None,
    opened_at: str | None = None,
    notes: str | None = None,
) -> ExecutingCollectSymbol:
    from apps.copilot.modules.executing.symbol_base import save_symbol_base_data

    sym = symbol.zfill(6)[-6:]
    payload: dict = {"symbol": sym, "name": name or sym}
    if quantity is not None:
        payload["quantity"] = quantity
    if cost_price is not None:
        payload["cost_price"] = cost_price
    if position_pct is not None:
        payload["position_pct"] = position_pct
    if opened_at:
        payload["opened_at"] = opened_at
    if notes is not None:
        payload["notes"] = notes
    _, row = await save_symbol_base_data(
        session,
        payload,
        enabled=enabled,
        profile=profile,
        funnel_stage=funnel_stage,
    )
    return row
