"""radar_t0_sync_watermarks 读写。

[Ref: 27_ §2.8.3]
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import utc_now_naive
from apps.copilot.db.models import RadarT0SyncWatermark


async def get_watermark(session: AsyncSession, job_id: str) -> RadarT0SyncWatermark | None:
    return await session.get(RadarT0SyncWatermark, job_id)


async def upsert_watermark(
    session: AsyncSession,
    job_id: str,
    *,
    success: bool,
    row_count: int | None = None,
    trade_date: date | None = None,
    error: str | None = None,
    catch_up_pending: bool = False,
) -> None:
    row = await session.get(RadarT0SyncWatermark, job_id)
    if row is None:
        row = RadarT0SyncWatermark(job_id=job_id)
        session.add(row)
    if success:
        row.last_success_at = utc_now_naive()
        row.last_row_count = row_count
        row.last_trade_date = trade_date
        row.last_error = None
        row.catch_up_pending = catch_up_pending
    else:
        row.last_error = (error or "unknown")[:500]
        row.catch_up_pending = catch_up_pending


def watermark_to_dict(row: RadarT0SyncWatermark | None) -> dict[str, Any]:
    if row is None:
        return {
            "job_id": None,
            "last_success_at": None,
            "last_trade_date": None,
            "last_row_count": None,
            "last_error": None,
            "catch_up_pending": False,
        }
    return {
        "job_id": row.job_id,
        "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        "last_trade_date": row.last_trade_date.isoformat() if row.last_trade_date else None,
        "last_row_count": row.last_row_count,
        "last_error": row.last_error,
        "catch_up_pending": bool(row.catch_up_pending),
    }


async def list_watermarks(session: AsyncSession) -> list[RadarT0SyncWatermark]:
    return list((await session.scalars(select(RadarT0SyncWatermark))).all())
