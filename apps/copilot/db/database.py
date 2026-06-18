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
    from apps.copilot.db.migrate_step31 import migrate_step31
    from apps.copilot.db.migrate_step32 import migrate_step32
    from apps.copilot.db.migrate_step33 import migrate_step33
    from apps.copilot.db.migrate_step34 import migrate_step34
    from apps.copilot.db.migrate_step35 import migrate_step35
    from apps.copilot.db.migrate_step36 import migrate_step36
    from apps.copilot.db.migrate_step37 import migrate_step37
    from apps.copilot.db.migrate_step38 import migrate_step38
    from apps.copilot.db.migrate_step39 import migrate_step39
    from apps.copilot.db.migrate_step40 import migrate_step40
    from apps.copilot.db.migrate_step41 import migrate_step41
    from apps.copilot.db.migrate_step42 import migrate_step42
    from apps.copilot.db.migrate_step43 import migrate_step43
    from apps.copilot.db.migrate_step44 import migrate_step44

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
    await migrate_step31(engine)
    await migrate_step32(engine)
    await migrate_step33(engine)
    await migrate_step34(engine)
    await migrate_step35(engine)
    await migrate_step36(engine)
    await migrate_step37(engine)
    await migrate_step38(engine)
    await migrate_step39(engine)
    await migrate_step40(engine)
    await migrate_step41(engine)
    await migrate_step42(engine)
    await migrate_step43(engine)
    await migrate_step44(engine)
    from apps.copilot.db.migrate_step45 import migrate_step45

    await migrate_step45(engine)
    from apps.copilot.db.migrate_step46 import migrate_step46

    await migrate_step46(engine)
    from apps.copilot.db.migrate_step47 import migrate_step47

    await migrate_step47(engine)
    from apps.copilot.db.migrate_step48 import migrate_step48

    await migrate_step48(engine)
    from apps.copilot.db.migrate_step49 import migrate_step49

    await migrate_step49(engine)
