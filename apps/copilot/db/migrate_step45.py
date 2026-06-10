"""step_45：战略板块表 · M12 滚动路线图升维（SQLite 兜底）。

[Ref: 30_战略板块与滚动路线图_前端与数据契约.md §9]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step45(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step45: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS strategic_boards (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name VARCHAR(256) NOT NULL,
                  horizon_start INTEGER NOT NULL,
                  horizon_end INTEGER NOT NULL,
                  qualitative_md TEXT,
                  barbell_config_json JSON,
                  color_token VARCHAR(32) NOT NULL DEFAULT 'indigo',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS strategic_phases (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  board_id INTEGER NOT NULL REFERENCES strategic_boards(id),
                  wave_no INTEGER NOT NULL DEFAULT 1,
                  name VARCHAR(256) NOT NULL,
                  start_year INTEGER NOT NULL,
                  end_year INTEGER NOT NULL,
                  situation_md TEXT,
                  playbook_md TEXT,
                  cso_barbell_pct_json JSON,
                  sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_strategic_phases_board_id "
                "ON strategic_phases (board_id)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS strategic_phase_symbols (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                  symbol VARCHAR(16) NOT NULL,
                  role_tag VARCHAR(64),
                  watch_only BOOLEAN NOT NULL DEFAULT 1,
                  source VARCHAR(32) NOT NULL DEFAULT 'manual',
                  added_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  UNIQUE(phase_id, symbol)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS strategic_phase_probes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                  probe_key VARCHAR(64) NOT NULL,
                  layer VARCHAR(8) NOT NULL,
                  red_flag_rule_json JSON,
                  cadence VARCHAR(32),
                  enabled BOOLEAN NOT NULL DEFAULT 1,
                  UNIQUE(phase_id, probe_key)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS symbol_strategic_tags (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol VARCHAR(16) NOT NULL,
                  board_id INTEGER NOT NULL REFERENCES strategic_boards(id),
                  phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                  role_tag VARCHAR(64),
                  is_primary BOOLEAN NOT NULL DEFAULT 1,
                  tagged_from VARCHAR(32) NOT NULL DEFAULT 'manual',
                  tagged_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_symbol_strategic_tags_symbol "
                "ON symbol_strategic_tags (symbol)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS strategic_tag_audit (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol VARCHAR(16) NOT NULL,
                  old_phase_id INTEGER,
                  new_phase_id INTEGER,
                  reason_md TEXT,
                  operator VARCHAR(64),
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS strategic_phase_reviews (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phase_id INTEGER NOT NULL REFERENCES strategic_phases(id),
                  review_md TEXT NOT NULL,
                  trigger_summary_json JSON,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        logger.info("migrate_step45(sqlite): strategic board tables ensured")
