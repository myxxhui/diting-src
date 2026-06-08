"""SQLAlchemy 2.0 异步引擎与会话工厂。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
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


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """单会话 async-for 片段（日报/周报 job、CLI）。"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from apps.copilot.db import models  # noqa: F401 — 触发 mapper 注册
    from apps.copilot.services.alerts.models import AlertLog  # noqa: F401
    from apps.copilot.services.ledger import models as ledger_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from apps.copilot.db.migrate_step14 import migrate_step14
    from apps.copilot.db.migrate_step15 import migrate_step15
    from apps.copilot.db.migrate_step17 import migrate_step17
    from apps.copilot.db.migrate_step18 import migrate_step18
    from apps.copilot.db.migrate_step19 import migrate_step19
    from apps.copilot.db.migrate_step20 import migrate_step20
    from apps.copilot.db.migrate_step27 import migrate_step27
    from apps.copilot.db.migrate_step28 import migrate_step28
    from apps.copilot.db.migrate_step29 import migrate_step29
    from apps.copilot.db.migrate_step30 import migrate_step30

    await migrate_step14(engine)
    await migrate_step15(engine)
    await migrate_step17(engine)
    await migrate_step18(engine)
    await migrate_step19(engine)
    await migrate_step20(engine)
    await migrate_step27(engine)
    await migrate_step28(engine)
    await migrate_step29(engine)
    await migrate_step30(engine)
