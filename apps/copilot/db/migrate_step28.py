"""step_28：执行中工作区表（user_positions · collect · watermarks · t0_raw · audits）。

[Ref: 28_ §4 §5.3 §8]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step28(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step28: skip（非 sqlite · PG 由 create_all）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS user_positions (
                  symbol VARCHAR(6) PRIMARY KEY,
                  name TEXT NOT NULL DEFAULT '',
                  quantity REAL NOT NULL DEFAULT 0,
                  cost_price REAL NOT NULL DEFAULT 0,
                  position_pct REAL,
                  opened_at DATE,
                  notes TEXT,
                  source VARCHAR(16) NOT NULL DEFAULT 'ui',
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_collect_symbols (
                  symbol VARCHAR(6) PRIMARY KEY,
                  profile VARCHAR(32) NOT NULL DEFAULT '601138',
                  enabled BOOLEAN NOT NULL DEFAULT 1,
                  funnel_stage VARCHAR(32),
                  enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  notes TEXT
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_t0_sync_watermarks (
                  job_id VARCHAR(64) NOT NULL,
                  symbol VARCHAR(6) NOT NULL DEFAULT '*',
                  last_success_at DATETIME,
                  last_trade_date DATE,
                  last_period_key VARCHAR(32),
                  last_row_count INTEGER,
                  last_error TEXT,
                  catch_up_pending BOOLEAN NOT NULL DEFAULT 0,
                  PRIMARY KEY (job_id, symbol)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_t0_probe_state (
                  symbol VARCHAR(6) NOT NULL,
                  probe_key VARCHAR(64) NOT NULL,
                  as_of DATE,
                  collected_at DATETIME,
                  stale_after DATETIME,
                  status VARCHAR(16) NOT NULL DEFAULT 'missing',
                  blocker TEXT,
                  PRIMARY KEY (symbol, probe_key)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_t0_raw (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol VARCHAR(6) NOT NULL,
                  probe_key VARCHAR(64) NOT NULL,
                  trade_date DATE,
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  source VARCHAR(256),
                  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_executing_t0_raw_sym_key
                ON executing_t0_raw (symbol, probe_key, collected_at DESC)
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_daily_audits (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  telemetry_json TEXT NOT NULL DEFAULT '{}',
                  audit_json TEXT NOT NULL DEFAULT '{}',
                  run_id VARCHAR(64),
                  t2_status VARCHAR(16) NOT NULL DEFAULT 'pending',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS executing_pipeline_runs (
                  run_id VARCHAR(64) PRIMARY KEY,
                  symbol VARCHAR(6) NOT NULL,
                  status VARCHAR(32) NOT NULL DEFAULT 'running',
                  stage VARCHAR(8),
                  progress_json TEXT,
                  error TEXT,
                  started_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  finished_at DATETIME
                )
                """
            )
        )
        logger.info("migrate_step28(sqlite): executing workspace tables ensured")
