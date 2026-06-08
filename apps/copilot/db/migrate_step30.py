"""step_30：执行区标的基础数据列 + 全局可用资金设置。

[Ref: 28_ §5.3]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_COLLECT_BASE_COLUMNS = (
    ("name", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("quantity", "REAL NOT NULL DEFAULT 0"),
    ("cost_price", "REAL NOT NULL DEFAULT 0"),
    ("position_pct", "REAL"),
    ("opened_at", "DATE"),
)


def _is_sqlite(engine: AsyncEngine) -> bool:
    return engine.url.get_backend_name().startswith("sqlite")


async def _ensure_collect_columns(conn, *, sqlite: bool) -> None:
    if sqlite:
        rows = await conn.execute(text("PRAGMA table_info(executing_collect_symbols)"))
        existing = {r[1] for r in rows.fetchall()}
        for col, ddl in _COLLECT_BASE_COLUMNS:
            if col in existing:
                continue
            await conn.execute(
                text(f"ALTER TABLE executing_collect_symbols ADD COLUMN {col} {ddl}")
            )
            logger.info("migrate_step30(sqlite): added executing_collect_symbols.%s", col)
        return

    for col, ddl in _COLLECT_BASE_COLUMNS:
        pg_ddl = ddl.replace("REAL", "DOUBLE PRECISION")
        await conn.execute(
            text(
                f"ALTER TABLE executing_collect_symbols "
                f"ADD COLUMN IF NOT EXISTS {col} {pg_ddl}"
            )
        )
    logger.info("migrate_step30(postgres): ensured executing_collect_symbols base columns")


async def migrate_step30(engine: AsyncEngine) -> None:
    sqlite = _is_sqlite(engine)
    settings_ddl = """
        CREATE TABLE IF NOT EXISTS executing_workspace_settings (
          id VARCHAR(16) PRIMARY KEY DEFAULT 'default',
          available_cash REAL,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """
    if not sqlite:
        settings_ddl = """
            CREATE TABLE IF NOT EXISTS executing_workspace_settings (
              id VARCHAR(16) PRIMARY KEY DEFAULT 'default',
              available_cash DOUBLE PRECISION,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """

    async with engine.begin() as conn:
        await conn.execute(text(settings_ddl))
        await _ensure_collect_columns(conn, sqlite=sqlite)
        if sqlite:
            await conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO executing_workspace_settings (id, available_cash)
                    VALUES ('default', NULL)
                    """
                )
            )
        else:
            await conn.execute(
                text(
                    """
                    INSERT INTO executing_workspace_settings (id, available_cash)
                    VALUES ('default', NULL)
                    ON CONFLICT (id) DO NOTHING
                    """
                )
            )
    logger.info("migrate_step30: executing_workspace_settings + collect base columns OK")
