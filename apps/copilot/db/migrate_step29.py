"""step_29：执行区日线底库 executing_daily_bars（#15 腾讯 250 日 K）。

[Ref: 28_ §2.2.2]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step29(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step29: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_daily_bars (
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  adjust VARCHAR(8) NOT NULL DEFAULT 'qfq',
                  open REAL NOT NULL,
                  high REAL NOT NULL,
                  low REAL NOT NULL,
                  close REAL NOT NULL,
                  volume REAL NOT NULL DEFAULT 0,
                  source VARCHAR(32) NOT NULL DEFAULT 'tencent_fqkline',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, trade_date, adjust)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_executing_daily_bars_sym_date
                ON executing_daily_bars (symbol, trade_date DESC)
                """
            )
        )
        logger.info("migrate_step29(sqlite): executing_daily_bars ensured")
