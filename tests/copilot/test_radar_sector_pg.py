"""T0-2 PG UPSERT。

[Ref: 27_ §2.2]
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.copilot.db.models import Base, RadarSectorDaily
from apps.copilot.modules.radar.t0.collectors.sector import upsert_sector_pg


@pytest.mark.asyncio
async def test_upsert_sector_pg_writes_momentum():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    ctx = {
        "sector_momentum": {
            "status": "ok",
            "source": "eastmoney:push2delay/board_clist_3d",
            "symbol": "601138",
            "industry": "消费电子",
            "board_code": "BK1037",
            "board_name": "消费电子",
            "pct_chg_3d": -1.02,
        },
        "sector_flow": {
            "status": "ok",
            "net_inflow_5d_yi": -132.76,
        },
    }
    async with session_factory() as session:
        ok = await upsert_sector_pg(session, "601138", ctx)
        await session.commit()
        assert ok is True

    async with session_factory() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(RadarSectorDaily))).scalars().all()
        assert len(rows) == 1
        assert rows[0].symbol == "601138"
        assert rows[0].pct_chg_3d == -1.02
        assert rows[0].net_inflow_5d_yi == -132.76

    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_sector_pg_skips_on_momentum_error():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        ok = await upsert_sector_pg(
            session,
            "601138",
            {"sector_momentum": {"status": "error"}, "sector_flow": {"status": "ok"}},
        )
        assert ok is False

    await engine.dispose()
