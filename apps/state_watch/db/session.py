"""SQLAlchemy 异步引擎与会话工厂.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.state_watch.config import settings
from apps.state_watch.db.models import Base

_engine = create_async_engine(settings.db_url, echo=False, future=True)
_SessionFactory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    Path("./data").mkdir(exist_ok=True)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _SessionFactory() as session:
        yield session


@asynccontextmanager
async def session_ctx():
    """供调度器等非 FastAPI 调用方使用的会话上下文（不自动 commit）。"""
    async with _SessionFactory() as session:
        yield session


async def ping_db() -> bool:
    from sqlalchemy import text

    try:
        async with _SessionFactory() as s:
            await s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
