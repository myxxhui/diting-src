"""step_43：executing_t2_executing_pins · T2 手动同步执行区 pin 表。

[Ref: 28_ §5 · Opus 分析区手动同步]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step43(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step43: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_t2_executing_pins (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol VARCHAR(16) NOT NULL UNIQUE,
                  request_id VARCHAR(32) NOT NULL,
                  pinned_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_executing_t2_executing_pins_request_id "
                "ON executing_t2_executing_pins (request_id)"
            )
        )
        logger.info("migrate_step43(sqlite): executing_t2_executing_pins ensured")
