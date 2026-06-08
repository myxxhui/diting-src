"""step_32：#17 moneyflow 250 日底库 executing_moneyflow_daily。

[Ref: 28_ §3.2.1]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step32(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step32: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_moneyflow_daily (
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  buy_elg_vol REAL NOT NULL DEFAULT 0,
                  sell_elg_vol REAL NOT NULL DEFAULT 0,
                  buy_lg_vol REAL NOT NULL DEFAULT 0,
                  sell_lg_vol REAL NOT NULL DEFAULT 0,
                  buy_md_vol REAL NOT NULL DEFAULT 0,
                  sell_md_vol REAL NOT NULL DEFAULT 0,
                  buy_sm_vol REAL NOT NULL DEFAULT 0,
                  sell_sm_vol REAL NOT NULL DEFAULT 0,
                  net_mf_vol REAL NOT NULL DEFAULT 0,
                  source VARCHAR(64) NOT NULL DEFAULT 'Tushare API (moneyflow)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, trade_date)
                )
                """
            )
        )
        logger.info("migrate_step32(sqlite): executing_moneyflow_daily ensured")
