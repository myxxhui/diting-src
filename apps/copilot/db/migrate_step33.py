"""step_33：#18 level2_super_order · moneyflow 表补 elg 金额列。

[Ref: 28_ §3.2 #18]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_ELG_AMOUNT_COLUMNS = (
    ("buy_elg_amount", "REAL NOT NULL DEFAULT 0"),
    ("sell_elg_amount", "REAL NOT NULL DEFAULT 0"),
    ("net_elg_amount", "REAL NOT NULL DEFAULT 0"),
)


async def migrate_step33(engine: AsyncEngine) -> None:
    sqlite = engine.url.get_backend_name().startswith("sqlite")
    async with engine.begin() as conn:
        if sqlite:
            rows = await conn.execute(text("PRAGMA table_info(executing_moneyflow_daily)"))
            existing = {r[1] for r in rows.fetchall()}
            for col, ddl in _ELG_AMOUNT_COLUMNS:
                if col in existing:
                    continue
                await conn.execute(
                    text(f"ALTER TABLE executing_moneyflow_daily ADD COLUMN {col} {ddl}")
                )
                logger.info("migrate_step33(sqlite): added executing_moneyflow_daily.%s", col)
            return

        for col, ddl in _ELG_AMOUNT_COLUMNS:
            pg_ddl = ddl.replace("REAL", "DOUBLE PRECISION")
            await conn.execute(
                text(
                    f"ALTER TABLE executing_moneyflow_daily "
                    f"ADD COLUMN IF NOT EXISTS {col} {pg_ddl}"
                )
            )
        logger.info("migrate_step33(postgres): ensured executing_moneyflow_daily elg amount columns")
