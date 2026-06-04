"""P2 · §2.8 CronJob registry / watermark / status。"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.copilot.db.database import Base
from apps.copilot.db.models import RadarT0SyncWatermark
from apps.copilot.modules.radar.t0.jobs.registry import cron_jobs, get_job_spec
from apps.copilot.modules.radar.t0.jobs.runner import is_watermark_stale
from apps.copilot.modules.radar.t0.jobs.status import build_pipeline_status
from apps.copilot.modules.radar.t0.jobs.watermarks import upsert_watermark
from apps.copilot.modules.radar.t0.symbol_list import upsert_collect_symbol


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_job_registry_has_bars_reconcile():
    spec = get_job_spec("bars-reconcile-daily")
    assert spec.implemented
    assert spec.micro_key == "bars_250d"
    assert len(cron_jobs()) >= 14


@pytest.mark.asyncio
async def test_pipeline_status_collect_list_only(db_session: AsyncSession):
    await upsert_collect_symbol(db_session, symbol="601138", name="工业富联")
    await upsert_watermark(
        db_session,
        "bars-reconcile-daily",
        success=True,
        row_count=1,
    )
    await db_session.commit()

    out = await build_pipeline_status(db_session)
    assert out["collect_symbol_count"] == 1
    assert out["collect_symbols"][0]["symbol"] == "601138"
    jobs = {j["job_id"]: j for j in out["jobs"]}
    assert "bars-reconcile-daily" in jobs
    assert jobs["bars-reconcile-daily"]["last_row_count"] == 1


def test_stale_watermark_none():
    spec = get_job_spec("micro-northbound-daily")
    assert is_watermark_stale(spec, last_success_at=None) is True
