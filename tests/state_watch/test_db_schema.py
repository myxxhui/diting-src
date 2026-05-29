"""DB 三表 schema 测试.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.state_watch.db.models import Base, HealthRecord, HoldingState, StateTransition


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_holding(session: AsyncSession) -> None:
    h = HoldingState(
        symbol="600519",
        name="贵州茅台",
        thesis_id="t-1",
        thesis_summary="高端白酒龙头",
        state="growing",
        health_score=85.0,
    )
    session.add(h)
    await session.commit()
    assert h.id is not None
    assert len(h.id) == 32


@pytest.mark.asyncio
async def test_health_record_fk(session: AsyncSession) -> None:
    h = HoldingState(
        symbol="000001",
        name="平安银行",
        thesis_id="t-2",
        thesis_summary="银行龙头",
    )
    session.add(h)
    await session.commit()

    r = HealthRecord(
        holding_id=h.id,
        total_score=80,
        sli_score=85,
        narrative_score=70,
        freshness_score=80,
        sli_details={"sli_1": 100},
    )
    session.add(r)
    await session.commit()
    assert r.id is not None


@pytest.mark.asyncio
async def test_transition_history(session: AsyncSession) -> None:
    h = HoldingState(symbol="X", name="X", thesis_id="t", thesis_summary="x")
    session.add(h)
    await session.commit()

    t = StateTransition(
        holding_id=h.id,
        from_state="growing",
        to_state="warning",
        from_health=85,
        to_health=55,
        rule_id="T2",
        reason="GROWING 健康度 < 60",
    )
    session.add(t)
    await session.commit()
    assert t.id is not None
