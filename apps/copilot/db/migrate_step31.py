"""step_31：T1 探针快照 executing_t1_probe_snapshots（#16/#17 PG 落库）。

[Ref: 28_ §4.2]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step31(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step31: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_t1_probe_snapshots (
                  symbol VARCHAR(6) NOT NULL,
                  probe_key VARCHAR(64) NOT NULL,
                  trade_date DATE,
                  node_json JSON NOT NULL DEFAULT '{}',
                  source VARCHAR(256),
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  PRIMARY KEY (symbol, probe_key)
                )
                """
            )
        )
        logger.info("migrate_step31(sqlite): executing_t1_probe_snapshots ensured")
