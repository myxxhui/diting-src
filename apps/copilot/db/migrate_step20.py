"""step_20：Planning 沙盒三表迁移（asset_states/probe_tasks/probe_results）。

[Ref: 24_行情解析与规划工作台_需求实现表.md]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _sqlite(engine: AsyncEngine) -> bool:
    return engine.url.get_backend_name().startswith("sqlite")


async def migrate_step20(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        if _sqlite(engine):
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS asset_states (
                      id TEXT PRIMARY KEY,
                      symbol_code VARCHAR(16) NOT NULL UNIQUE,
                      core_logic TEXT,
                      radar_initial_analysis JSON,
                      status VARCHAR(32) NOT NULL DEFAULT 'planning',
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS probe_tasks (
                      id TEXT PRIMARY KEY,
                      asset_id TEXT NOT NULL,
                      probe_blueprint JSON NOT NULL,
                      status VARCHAR(32) NOT NULL DEFAULT 'pending_code',
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                      FOREIGN KEY(asset_id) REFERENCES asset_states(id)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS probe_results (
                      id TEXT PRIMARY KEY,
                      probe_task_id TEXT NOT NULL UNIQUE,
                      refined_data JSON NOT NULL,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                      FOREIGN KEY(probe_task_id) REFERENCES probe_tasks(id)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_asset_states_symbol_code ON asset_states(symbol_code)"
                )
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_asset_states_status ON asset_states(status)")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_probe_tasks_asset_id ON probe_tasks(asset_id)")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_probe_tasks_status ON probe_tasks(status)")
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_probe_results_probe_task_id ON probe_results(probe_task_id)"
                )
            )
            logger.info("migrate_step20(sqlite): ensured planning sandbox tables")
            return

        # PostgreSQL
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asset_states (
                  id VARCHAR(36) PRIMARY KEY,
                  symbol_code VARCHAR(16) NOT NULL UNIQUE,
                  core_logic TEXT,
                  radar_initial_analysis JSONB,
                  status VARCHAR(32) NOT NULL DEFAULT 'planning',
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS probe_tasks (
                  id VARCHAR(36) PRIMARY KEY,
                  asset_id VARCHAR(36) NOT NULL REFERENCES asset_states(id) ON DELETE CASCADE,
                  probe_blueprint JSONB NOT NULL,
                  status VARCHAR(32) NOT NULL DEFAULT 'pending_code',
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS probe_results (
                  id VARCHAR(36) PRIMARY KEY,
                  probe_task_id VARCHAR(36) NOT NULL UNIQUE REFERENCES probe_tasks(id) ON DELETE CASCADE,
                  refined_data JSONB NOT NULL,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_asset_states_symbol_code ON asset_states(symbol_code)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_asset_states_status ON asset_states(status)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_probe_tasks_asset_id ON probe_tasks(asset_id)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_probe_tasks_status ON probe_tasks(status)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_probe_results_probe_task_id ON probe_results(probe_task_id)")
        )
        logger.info("migrate_step20(postgres): ensured planning sandbox tables")
