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


async def upsert_executing_collect(
    session: AsyncSession,
    symbol: str,
    *,
    profile: str = "601138",
    funnel_stage: str | None = "executing",
    enabled: bool = True,
) -> ExecutingCollectSymbol:
    sym = symbol.zfill(6)[-6:]
    row = await session.get(ExecutingCollectSymbol, sym)
    if row is None:
        row = ExecutingCollectSymbol(
            symbol=sym,
            profile=profile,
            enabled=enabled,
            funnel_stage=funnel_stage,
        )
        session.add(row)
    else:
        row.profile = profile
        row.enabled = enabled
        if funnel_stage:
            row.funnel_stage = funnel_stage
    await session.flush()
    return row
