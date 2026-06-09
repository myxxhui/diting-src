"""step_36：#21 block_trade_discount · executing_block_trade_daily 底库。

[Ref: 28_ §3.2.5]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step36(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step36: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_block_trade_daily (
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  vwap_price REAL NOT NULL DEFAULT 0,
                  total_vol_wan REAL NOT NULL DEFAULT 0,
                  total_amount_yuan REAL NOT NULL DEFAULT 0,
                  trades_count INTEGER NOT NULL DEFAULT 0,
                  close_price REAL NOT NULL DEFAULT 0,
                  free_float_mv_yuan REAL NOT NULL DEFAULT 0,
                  vwap_discount_rate REAL NOT NULL DEFAULT 0,
                  float_impact_ratio REAL NOT NULL DEFAULT 0,
                  buyers_sellers JSON,
                  source VARCHAR(96) NOT NULL DEFAULT 'Tushare Block Trade (VWAP Aggregated)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, trade_date)
                )
                """
            )
        )
        logger.info("migrate_step36(sqlite): executing_block_trade_daily ensured")
