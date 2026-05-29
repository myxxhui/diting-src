"""SQLite 表初始化脚本。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from apps.cryo_guard.db import models  # noqa: F401  确保模型注册
from apps.cryo_guard.db.session import Base, engine


async def init_db() -> None:
    Path("./data").mkdir(exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[cryo-guard] tables created.")


if __name__ == "__main__":
    asyncio.run(init_db())
