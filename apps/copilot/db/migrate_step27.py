"""step_27：radar_t0_collect_symbols + radar_t0_sync_watermarks。

[Ref: 27_行情雷达全链路架构设计优化 §2.1.1 · §2.8.3]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _sqlite(engine: AsyncEngine) -> bool:
    return engine.url.get_backend_name().startswith("sqlite")


async def migrate_step27(engine: AsyncEngine) -> None:
    if not _sqlite(engine):
        logger.info("migrate_step27: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radar_t0_collect_symbols (
                  symbol VARCHAR(6) PRIMARY KEY,
                  name TEXT NOT NULL DEFAULT '',
                  enabled BOOLEAN NOT NULL DEFAULT 1,
                  enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                  enrolled_by VARCHAR(32) NOT NULL DEFAULT 'workbench',
                  last_collect_at DATETIME,
                  last_collect_job VARCHAR(64),
                  last_trade_date DATE,
                  notes TEXT
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radar_t0_sync_watermarks (
                  job_id VARCHAR(64) PRIMARY KEY,
                  last_success_at DATETIME,
                  last_trade_date DATE,
                  last_row_count INTEGER,
                  last_error TEXT,
                  catch_up_pending BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radar_sector_daily (
                  symbol VARCHAR(6) NOT NULL,
                  trade_date DATE NOT NULL,
                  industry VARCHAR(64),
                  board_code VARCHAR(16),
                  board_name VARCHAR(64),
                  pct_chg_3d REAL,
                  net_inflow_5d_yi REAL,
                  momentum_json TEXT NOT NULL DEFAULT '{}',
                  flow_json TEXT NOT NULL DEFAULT '{}',
                  collected_at DATETIME,
                  source VARCHAR(64),
                  PRIMARY KEY (symbol, trade_date)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radar_market_sentiment_daily (
                  trade_date DATE PRIMARY KEY,
                  total_turnover_yi REAL,
                  turnover_vs_prev_pct REAL,
                  advance_ratio REAL,
                  limit_up_height INTEGER,
                  snapshot_json TEXT NOT NULL DEFAULT '{}',
                  finalized_at DATETIME,
                  source VARCHAR(64)
                )
                """
            )
        )
        logger.info("migrate_step27(sqlite): ensured radar T0 collect tables")
