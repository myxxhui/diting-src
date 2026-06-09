"""step_35：#20 turnover_acceleration · executing_turnover_daily 底库。

[Ref: 28_ §3.2.4]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step35(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step35: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_turnover_daily (
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  turnover_rate_f REAL NOT NULL DEFAULT 0,
                  volume_ratio REAL,
                  source VARCHAR(96) NOT NULL DEFAULT 'Tushare Daily Basic (turnover_rate_f)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, trade_date)
                )
                """
            )
        )
        logger.info("migrate_step35(sqlite): executing_turnover_daily ensured")
