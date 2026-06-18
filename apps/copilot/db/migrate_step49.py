"""step_49：Z0 战略表列 + wind_scan 族表 · PostgreSQL 增量补丁。

create_all 不补已有表新列；step_46 此前仅 SQLite 执行 ALTER。
[Ref: migrate_step46 · 33_ §9.1a]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def _pg_add_column(conn, table: str, column: str, ddl: str) -> None:
    exists = await conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            LIMIT 1
            """
        ),
        {"table": table, "column": column},
    )
    if exists.first() is not None:
        return
    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    logger.info("migrate_step49: added %s.%s", table, column)


async def migrate_step49(engine: AsyncEngine) -> None:
    if engine.dialect.name != "postgresql":
        logger.info("migrate_step49: skip（非 PostgreSQL）")
        return

    async with engine.begin() as conn:
        for col, ddl in (
            ("source_wind_scan_id", "INTEGER"),
            ("layer", "VARCHAR(64)"),
            ("s_curve_position", "VARCHAR(32)"),
            ("concurrent_with_json", "JSONB"),
            ("niche_template_json", "JSONB"),
        ):
            table = "strategic_boards" if col == "source_wind_scan_id" else "strategic_phases"
            await _pg_add_column(conn, table, col, ddl)

        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS wind_scans (
                    id SERIAL PRIMARY KEY,
                    as_of TIMESTAMPTZ,
                    p0_snapshot_json JSONB,
                    candidates_json JSONB,
                    status VARCHAR(32) NOT NULL DEFAULT 'empty',
                    blocker TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cvm_scorecards (
                    id SERIAL PRIMARY KEY,
                    phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                    niche_id VARCHAR(64),
                    symbol VARCHAR(16) NOT NULL,
                    scores_json JSONB,
                    anchor_path VARCHAR(32),
                    role_suggested VARCHAR(32),
                    pool_eligible BOOLEAN NOT NULL DEFAULT TRUE,
                    dispatch_selected BOOLEAN NOT NULL DEFAULT FALSE,
                    provisional BOOLEAN NOT NULL DEFAULT TRUE,
                    human_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
                    role_override VARCHAR(32),
                    override_reason TEXT,
                    confirmed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
                    UNIQUE (phase_id, symbol)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS scan_dispatches (
                    id SERIAL PRIMARY KEY,
                    board_id INTEGER NOT NULL REFERENCES strategic_boards(id),
                    phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                    layer VARCHAR(64),
                    theme VARCHAR(256) NOT NULL,
                    symbols_json JSONB NOT NULL,
                    symbol_roles_json JSONB,
                    cvm_scorecard_ref VARCHAR(256),
                    ecosystem_e1_e5_json JSONB,
                    p0_snapshot_json JSONB,
                    genesis_ref_json JSONB,
                    status VARCHAR(32) NOT NULL DEFAULT 'draft',
                    supersedes_id INTEGER,
                    human_confirmed BOOLEAN NOT NULL DEFAULT TRUE,
                    dispatched_at TIMESTAMPTZ,
                    revoked_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS scan_dispatch_audit (
                    id SERIAL PRIMARY KEY,
                    dispatch_id INTEGER NOT NULL REFERENCES scan_dispatches(id),
                    action VARCHAR(32) NOT NULL,
                    actor VARCHAR(64),
                    reason_md TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                )
                """
            )
        )

    logger.info("migrate_step49(postgresql): Z0 strategic columns + wind_scan tables ensured")
