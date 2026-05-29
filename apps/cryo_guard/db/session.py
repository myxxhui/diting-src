"""SQLAlchemy 异步 Session。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from apps.cryo_guard.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.db_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


from apps.cryo_guard.db.sync_session import session_scope  # noqa: E402  re-export for scripts

__all__ = ["Base", "engine", "AsyncSessionLocal", "get_session", "session_scope"]
