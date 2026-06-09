"""step_37：#22 retail_concentration · executing_retail_holder_snapshots 底库。

[Ref: 28_ §3.2.6]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step37(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step37: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_retail_holder_snapshots (
                  symbol VARCHAR(6) NOT NULL,
                  end_date DATE NOT NULL,
                  announce_date DATE,
                  holder_num REAL NOT NULL DEFAULT 0,
                  previous_holder_num REAL,
                  holder_num_change REAL,
                  avg_hold_vol REAL,
                  free_float_shares REAL,
                  source VARCHAR(96) NOT NULL DEFAULT 'AkShare Interactive Platform Scraper (Event-Driven)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, end_date)
                )
                """
            )
        )
        logger.info("migrate_step37(sqlite): executing_retail_holder_snapshots ensured")
