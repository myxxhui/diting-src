"""step_39：#24 etf_redemption_impact · executing_etf_stock_link / executing_etf_share_daily。

[Ref: 28_ §3.2.8]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step39(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step39: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_etf_stock_link (
                  symbol VARCHAR(6) NOT NULL,
                  etf_ts_code VARCHAR(16) NOT NULL,
                  stock_weight REAL NOT NULL DEFAULT 0,
                  report_end_date DATE,
                  link_source VARCHAR(64),
                  source VARCHAR(96) NOT NULL DEFAULT 'Tushare Pro Fund Share & Portfolio (T+1 Lag)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, etf_ts_code)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_etf_share_daily (
                  etf_ts_code VARCHAR(16) NOT NULL,
                  trade_date DATE NOT NULL,
                  fd_share REAL NOT NULL DEFAULT 0,
                  fd_share_change REAL,
                  unit_nav REAL,
                  source VARCHAR(96) NOT NULL DEFAULT 'Tushare Pro Fund Share & Portfolio (T+1 Lag)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (etf_ts_code, trade_date)
                )
                """
            )
        )
        logger.info("migrate_step39(sqlite): etf redemption tables ensured")
