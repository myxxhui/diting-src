"""step_19：雷达持久化 + 漏斗 UI 移除字段。

- campaign_symbols.ui_removed_at / last_analyzed_at
- radar_symbol_versions 表（create_all 亦会建；此处补列容错）

[Ref: 24_需求实现表 · 波次四持久化]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_STEP19_COLUMNS = (
    ("campaign_symbols", "ui_removed_at", "DATETIME"),
    ("campaign_symbols", "last_analyzed_at", "DATETIME"),
)


async def migrate_step19(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, col, ddl in _STEP19_COLUMNS:
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            names = {r[1] for r in rows.fetchall()}
            if col in names:
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            logger.info("migrate_step19: added %s.%s", table, col)
