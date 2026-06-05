"""通用 T0 采集标的列表 · 唯一读表入口。

执行区 `executing_collect_symbols` 与雷达 `radar_t0_collect_symbols` 并集驱动
所有 scope=COLLECT 的 Cron（T0-2/3/8…）；表内新增标的即自动纳入通用指标采集。

[Ref: 27_ §2.1.1 · 28_ §4.2 · §4.7]
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import utc_now_naive
from apps.copilot.db.models import ExecutingCollectSymbol, RadarT0CollectSymbol

logger = logging.getLogger(__name__)


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().zfill(6)[-6:]


async def load_t0_collect_symbols(
    session: AsyncSession,
    *,
    enabled_only: bool = True,
) -> list[str]:
    """雷达工作台采集表（候选/行业标的）。"""
    q = select(RadarT0CollectSymbol.symbol).order_by(RadarT0CollectSymbol.symbol)
    if enabled_only:
        q = q.where(RadarT0CollectSymbol.enabled.is_(True))
    rows = await session.scalars(q)
    return [str(s) for s in rows.all() if s]


async def load_generic_t0_collect_symbols(
    session: AsyncSession,
    *,
    enabled_only: bool = True,
) -> list[str]:
    """通用 T0 采集宇宙：executing_collect_symbols ∪ radar_t0_collect_symbols（去重排序）。

    执行区标的列表新增一行 → 全部 scope=COLLECT 的 Cron 自动采该标的的通用 T0 指标。
    """
    from apps.copilot.modules.executing.universe import load_executing_collect_symbols

    executing = await load_executing_collect_symbols(session)
    radar = await load_t0_collect_symbols(session, enabled_only=enabled_only)
    merged = sorted({str(s).zfill(6)[-6:] for s in executing + radar if s})
    if not merged:
        logger.warning("generic_t0_collect_empty")
    return merged


async def sync_executing_collect_mirror(session: AsyncSession) -> int:
    """将 executing_collect_symbols enabled 行镜像到 radar_t0_collect_symbols（便于 last_collect 追踪）。"""
    rows = (
        await session.scalars(
            select(ExecutingCollectSymbol).where(ExecutingCollectSymbol.enabled.is_(True))
        )
    ).all()
    n = 0
    for ex in rows:
        sym = _norm_symbol(ex.symbol)
        if not sym:
            continue
        existing = await session.get(RadarT0CollectSymbol, sym)
        if existing is None:
            session.add(
                RadarT0CollectSymbol(
                    symbol=sym,
                    name=sym,
                    enabled=True,
                    enrolled_by="executing_mirror",
                )
            )
            n += 1
        elif not existing.enabled:
            existing.enabled = True
            n += 1
    if n:
        await session.flush()
    return n


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


async def touch_generic_collect_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    job_id: str,
    trade_date: date | None = None,
) -> None:
    """通用 T0 采集完成后更新 last_collect（含 executing 镜像行）。"""
    sym = _norm_symbol(symbol)
    row = await session.get(RadarT0CollectSymbol, sym)
    if row is None:
        await upsert_collect_symbol(
            session,
            symbol=sym,
            enrolled_by="executing_mirror",
            enabled=True,
        )
    await touch_collect_symbol(session, sym, job_id=job_id, trade_date=trade_date)


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
