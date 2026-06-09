"""step_41：executing_t2_analyst_requests · T2 预分析数据集审计表。

[Ref: 28_ §5]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step41(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step41: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_t2_analyst_requests (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id VARCHAR(32) NOT NULL UNIQUE,
                  session_id VARCHAR(32),
                  user_question TEXT NOT NULL DEFAULT '',
                  model_id VARCHAR(64),
                  include_t1_jl4 BOOLEAN NOT NULL DEFAULT 1,
                  symbols_json JSON NOT NULL DEFAULT '[]',
                  dry_run BOOLEAN NOT NULL DEFAULT 1,
                  api_connected BOOLEAN NOT NULL DEFAULT 0,
                  payload_json JSON NOT NULL DEFAULT '{}',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_executing_t2_analyst_requests_created_at "
                "ON executing_t2_analyst_requests (created_at)"
            )
        )
        logger.info("migrate_step41(sqlite): executing_t2_analyst_requests ensured")
