"""step_38：#23 insider_sell_actual · executing_insider_trade_events 底库。

[Ref: 28_ §3.2.7]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step38(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step38: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_insider_trade_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol VARCHAR(6) NOT NULL,
                  ann_date DATE NOT NULL,
                  trade_date DATE NOT NULL,
                  holder_name VARCHAR(120) NOT NULL,
                  holder_type VARCHAR(32),
                  in_out VARCHAR(8) NOT NULL,
                  change_vol_shares REAL NOT NULL DEFAULT 0,
                  source VARCHAR(96) NOT NULL DEFAULT 'Tushare Pro (stk_holdertrade)',
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  UNIQUE(symbol, ann_date, trade_date, holder_name, in_out, change_vol_shares)
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_insider_trade_symbol "
                "ON executing_insider_trade_events (symbol)"
            )
        )
        logger.info("migrate_step38(sqlite): executing_insider_trade_events ensured")
