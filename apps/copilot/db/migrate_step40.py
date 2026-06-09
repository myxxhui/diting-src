"""step_40：#25 tech_beta_correlation · executing_beta_correlation_daily 底库。

[Ref: 28_ §2.2.8]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step40(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step40: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_beta_correlation_daily (
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  sector_index_code VARCHAR(16) NOT NULL,
                  stock_pct_chg REAL NOT NULL DEFAULT 0,
                  index_pct_chg REAL NOT NULL DEFAULT 0,
                  source VARCHAR(96) NOT NULL DEFAULT 'Tushare Pro Index/Daily',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, trade_date)
                )
                """
            )
        )
        logger.info("migrate_step40(sqlite): executing_beta_correlation_daily ensured")
