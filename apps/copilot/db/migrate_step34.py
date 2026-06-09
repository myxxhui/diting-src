"""step_34：#19 margin_short_skew · executing_margin_daily 底库。

[Ref: 28_ §3.2.3]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step34(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step34: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_margin_daily (
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  rzye REAL NOT NULL DEFAULT 0,
                  rqye REAL NOT NULL DEFAULT 0,
                  rzmre REAL NOT NULL DEFAULT 0,
                  margin_short_ratio REAL,
                  free_float_mkt_cap REAL,
                  margin_to_float_ratio REAL,
                  source VARCHAR(96) NOT NULL DEFAULT 'Tushare Margin Detail (T+1 Lag)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, trade_date)
                )
                """
            )
        )
        logger.info("migrate_step34(sqlite): executing_margin_daily ensured")
