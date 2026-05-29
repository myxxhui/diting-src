"""从持仓 SoT 导入 copilot holdings 表（upsert，不删人工录入）.

[Ref: 03_/00_维度零/.../step_02]
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.holdings_sot import load_holdings_sot
from apps.copilot.db.models import Holding, User


async def ensure_default_user(session: AsyncSession, user_id: str = "default") -> User:
    row = await session.scalar(select(User).where(User.user_id == user_id))
    if row is not None:
        return row
    user = User(user_id=user_id, name="默认用户")
    session.add(user)
    await session.flush()
    return user


async def import_sot_holdings(session: AsyncSession, user_id: str = "default") -> dict:
    sot = load_holdings_sot()
    user = await ensure_default_user(session, user_id=user_id)
    imported = 0
    for entry in sot.holdings:
        if not entry.active:
            continue
        qty = float(entry.quantity or 0.0)
        cost = float(entry.cost_price or 0.0)
        existing = await session.scalar(
            select(Holding).where(Holding.user_pk == user.id, Holding.symbol == entry.symbol)
        )
        if existing is None:
            session.add(
                Holding(
                    user_pk=user.id,
                    symbol=entry.symbol,
                    name=entry.name or entry.symbol,
                    shares=qty,
                    cost_price=cost,
                )
            )
            imported += 1
        else:
            existing.name = entry.name or entry.symbol
            existing.shares = qty
            existing.cost_price = cost
            imported += 1
    await session.commit()
    return {
        "imported": imported,
        "active_symbols": sot.active_symbols(),
        "source": str(sot.source_path),
    }
