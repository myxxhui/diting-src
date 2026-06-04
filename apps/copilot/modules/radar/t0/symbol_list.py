"""基础数据采集标的列表 · 唯一读表入口。

[Ref: 27_ §2.1.1]
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import utc_now_naive
from apps.copilot.db.models import RadarT0CollectSymbol


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().zfill(6)[-6:]


async def load_t0_collect_symbols(
    session: AsyncSession,
    *,
    enabled_only: bool = True,
) -> list[str]:
    """CronJob · bootstrap · 一次性 Job · status 检查均调用。"""
    q = select(RadarT0CollectSymbol.symbol).order_by(RadarT0CollectSymbol.symbol)
    if enabled_only:
        q = q.where(RadarT0CollectSymbol.enabled.is_(True))
    rows = await session.scalars(q)
    return [str(s) for s in rows.all() if s]


async def list_collect_symbol_rows(
    session: AsyncSession,
    *,
    enabled_only: bool = False,
) -> list[RadarT0CollectSymbol]:
    q = select(RadarT0CollectSymbol).order_by(RadarT0CollectSymbol.enrolled_at.desc())
    if enabled_only:
        q = q.where(RadarT0CollectSymbol.enabled.is_(True))
    return list((await session.scalars(q)).all())


async def upsert_collect_symbol(
    session: AsyncSession,
    *,
    symbol: str,
    name: str = "",
    enrolled_by: str = "workbench",
    enabled: bool = True,
) -> RadarT0CollectSymbol:
    sym = _norm_symbol(symbol)
    if not sym:
        raise ValueError("symbol 无效")
    row = await session.get(RadarT0CollectSymbol, sym)
    if row is None:
        row = RadarT0CollectSymbol(
            symbol=sym,
            name=(name or sym).strip(),
            enabled=enabled,
            enrolled_by=enrolled_by,
        )
        session.add(row)
    else:
        if name and name.strip() and name.strip() != sym:
            row.name = name.strip()
        row.enabled = enabled
        if not row.enrolled_by:
            row.enrolled_by = enrolled_by
    await session.flush()
    return row


async def set_collect_symbol_enabled(
    session: AsyncSession,
    symbol: str,
    *,
    enabled: bool,
) -> RadarT0CollectSymbol | None:
    sym = _norm_symbol(symbol)
    row = await session.get(RadarT0CollectSymbol, sym)
    if row is None:
        return None
    row.enabled = enabled
    await session.flush()
    return row


async def touch_collect_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    job_id: str,
    trade_date: date | None = None,
) -> None:
    sym = _norm_symbol(symbol)
    now = utc_now_naive()
    await session.execute(
        update(RadarT0CollectSymbol)
        .where(RadarT0CollectSymbol.symbol == sym)
        .values(
            last_collect_at=now,
            last_collect_job=job_id,
            last_trade_date=trade_date,
        )
    )


def row_to_dict(row: RadarT0CollectSymbol) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "name": row.name,
        "enabled": row.enabled,
        "enrolled_at": row.enrolled_at.isoformat() if row.enrolled_at else None,
        "enrolled_by": row.enrolled_by,
        "last_collect_at": row.last_collect_at.isoformat() if row.last_collect_at else None,
        "last_collect_job": row.last_collect_job,
        "last_trade_date": row.last_trade_date.isoformat() if row.last_trade_date else None,
        "notes": row.notes,
    }
