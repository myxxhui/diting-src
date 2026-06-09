"""step_42：executing_t2_analyst_sessions · T2 分析对话会话持久化。

[Ref: 28_ §5]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step42(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step42: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_t2_analyst_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id VARCHAR(32) NOT NULL UNIQUE,
                  messages_json JSON NOT NULL DEFAULT '[]',
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_executing_t2_analyst_sessions_updated_at "
                "ON executing_t2_analyst_sessions (updated_at)"
            )
        )
        logger.info("migrate_step42(sqlite): executing_t2_analyst_sessions ensured")
