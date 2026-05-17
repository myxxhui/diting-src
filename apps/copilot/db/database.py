"""SQLAlchemy 2.0 异步引擎与会话工厂。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
[DNA: _System_DNA/00_co_pilot/dna_stage_1_启动期.yaml#tech_stack.database]
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from apps.copilot.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_async_engine(
    settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.db_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Session 工厂别名（M3 AlertDispatcher / Deduper / SLA）
async_session_factory = AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from apps.copilot.db import models  # noqa: F401 — 触发 mapper 注册
    from apps.copilot.services.alerts.models import AlertLog  # noqa: F401
    from apps.copilot.services.ledger import models as ledger_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
