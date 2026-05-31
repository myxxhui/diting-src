"""step_17 迁移：建 execution_advices 表。

[Ref: step_17_执行中仓位指导.md]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS execution_advices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    symbol VARCHAR(16) NOT NULL,
    current_price REAL,
    cost_price REAL,
    quantity REAL,
    position_pct REAL,
    unrealized_pnl_pct REAL,
    price_stale BOOLEAN NOT NULL DEFAULT 0,
    advice_action VARCHAR(64) NOT NULL DEFAULT '持有',
    rationale VARCHAR(512),
    evidence_chain JSON,
    safety_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    execute_mode VARCHAR(32) NOT NULL DEFAULT 'advisory',
    human_confirmation_required BOOLEAN NOT NULL DEFAULT 1,
    as_of DATETIME DEFAULT (CURRENT_TIMESTAMP)
)
"""


async def migrate_step17(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_SQL))
        logger.info("migrate_step17: execution_advices table ensured")
