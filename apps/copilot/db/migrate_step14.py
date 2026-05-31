"""step_14 轻量迁移：新表 create_all + 已有表补列（SQLite）。

[Ref: step_14_行情雷达扫描与三段流水线.md]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_STEP14_COLUMNS = (
    ("campaigns", "funnel_stage", "VARCHAR(32) NOT NULL DEFAULT 'radar_intake'"),
    ("campaign_symbols", "analysis_snapshot", "JSON"),
    ("campaign_symbols", "promoted_from_candidate_id", "INTEGER"),
)


async def migrate_step14(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, col, ddl in _STEP14_COLUMNS:
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            names = {r[1] for r in rows.fetchall()}
            if col in names:
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            logger.info("migrate_step14: added %s.%s", table, col)
