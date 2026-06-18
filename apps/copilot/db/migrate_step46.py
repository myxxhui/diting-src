"""step_46：Z0 指标先行表（wind_scan · CVM · scan_dispatch）。

[Ref: 33_五区工作台_前端区际联动与数据携带契约.md §9.1a]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step46(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step46: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS wind_scans (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  as_of DATETIME,
                  p0_snapshot_json JSON,
                  candidates_json JSON,
                  status VARCHAR(32) NOT NULL DEFAULT 'empty',
                  blocker TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cvm_scorecards (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                  niche_id VARCHAR(64),
                  symbol VARCHAR(16) NOT NULL,
                  scores_json JSON,
                  anchor_path VARCHAR(32),
                  role_suggested VARCHAR(32),
                  pool_eligible BOOLEAN NOT NULL DEFAULT 1,
                  dispatch_selected BOOLEAN NOT NULL DEFAULT 0,
                  provisional BOOLEAN NOT NULL DEFAULT 1,
                  human_confirmed BOOLEAN NOT NULL DEFAULT 0,
                  role_override VARCHAR(32),
                  override_reason TEXT,
                  confirmed_at DATETIME,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  UNIQUE(phase_id, symbol)
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_cvm_scorecards_phase_id "
                "ON cvm_scorecards (phase_id)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS scan_dispatches (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  board_id INTEGER NOT NULL REFERENCES strategic_boards(id),
                  phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                  layer VARCHAR(64),
                  theme VARCHAR(256) NOT NULL,
                  symbols_json JSON NOT NULL,
                  symbol_roles_json JSON,
                  cvm_scorecard_ref VARCHAR(256),
                  ecosystem_e1_e5_json JSON,
                  p0_snapshot_json JSON,
                  genesis_ref_json JSON,
                  status VARCHAR(32) NOT NULL DEFAULT 'draft',
                  supersedes_id INTEGER,
                  human_confirmed BOOLEAN NOT NULL DEFAULT 1,
                  dispatched_at DATETIME,
                  revoked_at DATETIME,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_scan_dispatches_phase_id "
                "ON scan_dispatches (phase_id)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS scan_dispatch_audit (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  dispatch_id INTEGER NOT NULL REFERENCES scan_dispatches(id),
                  action VARCHAR(32) NOT NULL,
                  actor VARCHAR(64),
                  reason_md TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        for col, ddl in (
            ("source_wind_scan_id", "INTEGER"),
            ("layer", "VARCHAR(64)"),
            ("s_curve_position", "VARCHAR(32)"),
            ("concurrent_with_json", "JSON"),
            ("niche_template_json", "JSON"),
        ):
            table = "strategic_boards" if col == "source_wind_scan_id" else "strategic_phases"
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            except Exception:
                pass
        logger.info("migrate_step46(sqlite): Z0 wind_scan/CVM/dispatch tables ensured")
