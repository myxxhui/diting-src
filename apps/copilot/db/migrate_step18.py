"""step_18 迁移：CampaignSymbol 漏斗状态机（标的级漏斗重构）。

- 新增 campaign_symbols.funnel_stage（radar_intake|roadmap|planning|executing|archived）
- 新增 campaign_symbols.updated_at
- 尝试建 symbol 全局唯一索引（清空脏数据后才会成功；存量重复时容错跳过，
  由应用层 find-or-create 兜底保证一标的一条 funnel 记录）

[Ref: 25_四区漏斗 · 标的级漏斗重构]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_STEP18_COLUMNS = (
    ("campaign_symbols", "funnel_stage", "VARCHAR(32) NOT NULL DEFAULT 'planning'"),
    ("campaign_symbols", "updated_at", "DATETIME"),
)


async def migrate_step18(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, col, ddl in _STEP18_COLUMNS:
            rows = await conn.execute(text(f"PRAGMA table_info({table})"))
            names = {r[1] for r in rows.fetchall()}
            if col in names:
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            logger.info("migrate_step18: added %s.%s", table, col)

        # 回填：旧 stage / status 推断 funnel_stage（保守默认 planning）
        await conn.execute(
            text(
                "UPDATE campaign_symbols SET funnel_stage='planning' "
                "WHERE funnel_stage IS NULL OR funnel_stage=''"
            )
        )

    # 唯一索引单独事务，失败（存量重复）不阻断启动
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_funnel_symbol_idx "
                    "ON campaign_symbols(symbol)"
                )
            )
            logger.info("migrate_step18: uq_funnel_symbol_idx ensured")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "migrate_step18: symbol 唯一索引暂未建立（存量重复，清空后重试）：%s", exc
        )
