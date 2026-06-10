"""step_44：radar_chat_sessions + copilot_ui_settings · 部署可恢复 PG 底库。

[Ref: 28_ · 雷达对话 / UI 设置 / 搜索历史]
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def migrate_step44(engine: AsyncEngine) -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        logger.info("migrate_step44: skip（PostgreSQL 由 create_all 建表）")
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS radar_chat_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id VARCHAR(32) NOT NULL UNIQUE,
                  messages_json JSON NOT NULL DEFAULT '[]',
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_radar_chat_sessions_updated_at "
                "ON radar_chat_sessions (updated_at)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS copilot_ui_settings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  setting_key VARCHAR(64) NOT NULL UNIQUE,
                  payload_json JSON NOT NULL DEFAULT '{}',
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_copilot_ui_settings_key "
                "ON copilot_ui_settings (setting_key)"
            )
        )
        logger.info("migrate_step44(sqlite): radar_chat_sessions + copilot_ui_settings ensured")
