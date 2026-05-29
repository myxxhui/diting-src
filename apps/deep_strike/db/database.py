"""SQLAlchemy 异步引擎与 session 工厂.

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.deep_strike.config import settings

engine = create_async_engine(settings.db_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    from pathlib import Path

    from sqlalchemy import text

    from apps.deep_strike.db.models import Base

    Path("./data").mkdir(exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for ddl in (
            "ALTER TABLE evidence_records ADD COLUMN scan_id VARCHAR(32) DEFAULT 'legacy'",
            "ALTER TABLE evidence_records ADD COLUMN evidence_idx INTEGER DEFAULT 0",
            "ALTER TABLE evidence_records ADD COLUMN source_id VARCHAR(128)",
            "ALTER TABLE evidence_records ADD COLUMN confidence FLOAT",
            "ALTER TABLE evidence_records ADD COLUMN physical_gate BOOLEAN",
            "ALTER TABLE thesis_cards ADD COLUMN timer_signal TEXT",
        ):
            try:
                await conn.execute(text(ddl))
            except Exception:
                pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
