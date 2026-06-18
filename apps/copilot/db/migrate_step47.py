"""step_47：Z0 指标快照表（metric_store 底库）。

[Ref: 34_ §3 · 29_ §1.2]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step47(engine: AsyncEngine) -> None:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS z0_metric_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        metric_id VARCHAR(128) NOT NULL,
                        as_of DATETIME,
                        payload_json JSON,
                        status VARCHAR(32) NOT NULL DEFAULT 'ok',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_z0_metric_snapshots_metric_id "
                    "ON z0_metric_snapshots (metric_id)"
                )
            )
        logger.info("migrate_step47(sqlite): z0_metric_snapshots ensured")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS z0_metric_snapshots (
                    id SERIAL PRIMARY KEY,
                    metric_id VARCHAR(128) NOT NULL,
                    as_of TIMESTAMPTZ,
                    payload_json JSONB,
                    status VARCHAR(32) NOT NULL DEFAULT 'ok',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_z0_metric_snapshots_metric_id "
                "ON z0_metric_snapshots (metric_id)"
            )
        )
    logger.info("migrate_step47(%s): z0_metric_snapshots ensured", dialect)
