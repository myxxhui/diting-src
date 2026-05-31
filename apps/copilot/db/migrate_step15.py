"""step_15 轻量迁移：timeline 扩展列 + regime_assessments + monitor 扩展。

[Ref: step_15_滚动路线图双层锚定.md]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_STEP15_COLUMNS = (
    ("campaign_timeline", "symbol", "VARCHAR(16)"),
    ("campaign_timeline", "window_start", "DATE"),
    ("campaign_timeline", "window_end", "DATE"),
    ("campaign_timeline", "build_lead_days", "INTEGER NOT NULL DEFAULT 15"),
    ("campaign_timeline", "sequence_no", "INTEGER"),
    ("campaign_timeline", "target_weight_pct", "REAL NOT NULL DEFAULT 50.0"),
    ("campaign_timeline", "feasibility_flags", "JSON"),
    ("campaign_timeline", "advisories", "JSON"),
    ("campaign_timeline", "candidate_id", "INTEGER"),
    ("monitor_subscriptions", "falsify_type", "VARCHAR(32)"),
    ("monitor_subscriptions", "hypothesis", "VARCHAR(512)"),
)


async def migrate_step15(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, col, ddl in _STEP15_COLUMNS:
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            names = {r[1] for r in rows.fetchall()}
            if col in names:
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            logger.info("migrate_step15: added %s.%s", table, col)
