"""Copilot UI 设置 PG 持久化（工作台偏好 / 展示布局 / 搜索历史）。

PG 为权威底库；进程内缓存供同步读路径；启动时从 PG 预热并迁移旧 PVC/磁盘文件。

[Ref: 28_ · 部署可恢复]
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import CopilotUiSetting

logger = logging.getLogger(__name__)

SETTING_WORKBENCH_PREFS = "workbench_prefs"
SETTING_DISPLAY_LAYOUT = "display_layout"
SETTING_RADAR_QUERY_HISTORY = "radar_query_history"

_cache: dict[str, Any] = {}


def get_cached(key: str) -> Any | None:
    return _cache.get(key)


def set_cached(key: str, value: Any) -> None:
    _cache[key] = value


async def load_setting_row(session: AsyncSession, key: str) -> dict[str, Any] | None:
    row = await session.scalar(
        select(CopilotUiSetting).where(CopilotUiSetting.setting_key == key)
    )
    if row is None or not row.payload_json:
        return None
    if isinstance(row.payload_json, dict):
        return dict(row.payload_json)
    return None


async def save_setting_row(
    session: AsyncSession, key: str, payload: dict[str, Any]
) -> dict[str, Any]:
    row = await session.scalar(
        select(CopilotUiSetting).where(CopilotUiSetting.setting_key == key)
    )
    if row is None:
        row = CopilotUiSetting(setting_key=key, payload_json=payload)
        session.add(row)
    else:
        row.payload_json = payload
    await session.flush()
    set_cached(key, payload)
    return payload


async def delete_setting_row(session: AsyncSession, key: str) -> None:
    row = await session.scalar(
        select(CopilotUiSetting).where(CopilotUiSetting.setting_key == key)
    )
    if row is not None:
        await session.delete(row)
        await session.flush()
    _cache.pop(key, None)


def _read_json_file(path: Any) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 UI 设置文件失败 %s: %s", path, exc)
    return None


async def warm_ui_settings_from_pg(session: AsyncSession) -> dict[str, int]:
    """启动时加载 PG → 内存缓存；PG 空则从旧磁盘文件迁移写入 PG。"""
    from apps.copilot.modules.radar.display_layout import LAYOUT_FILENAME, radar_cache_root
    from apps.copilot.modules.radar.workbench_prefs import PREFS_FILENAME

    stats = {"loaded": 0, "migrated": 0}
    file_sources: dict[str, Any] = {
        SETTING_WORKBENCH_PREFS: radar_cache_root() / PREFS_FILENAME,
        SETTING_DISPLAY_LAYOUT: radar_cache_root() / LAYOUT_FILENAME,
    }

    for key in (
        SETTING_WORKBENCH_PREFS,
        SETTING_DISPLAY_LAYOUT,
        SETTING_RADAR_QUERY_HISTORY,
    ):
        payload = await load_setting_row(session, key)
        if payload is not None:
            set_cached(key, payload)
            stats["loaded"] += 1
            continue

        if key in file_sources:
            migrated = _read_json_file(file_sources[key])
            if migrated is not None:
                await save_setting_row(session, key, migrated)
                stats["migrated"] += 1
                stats["loaded"] += 1

    if stats["migrated"]:
        await session.commit()
        logger.info("UI 设置从磁盘迁移至 PG migrated=%d", stats["migrated"])
    logger.info("UI 设置 PG 预热 loaded=%d", stats["loaded"])
    return stats


async def load_query_history(session: AsyncSession) -> dict[str, Any]:
    cached = get_cached(SETTING_RADAR_QUERY_HISTORY)
    if cached is not None:
        return cached
    row = await load_setting_row(session, SETTING_RADAR_QUERY_HISTORY)
    if row is not None:
        set_cached(SETTING_RADAR_QUERY_HISTORY, row)
        return row
    return {"queries": [], "last": ""}


async def remember_query(session: AsyncSession, query: str, *, max_items: int = 10) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return await load_query_history(session)
    data = await load_query_history(session)
    queries = [x for x in (data.get("queries") or []) if x != q]
    queries.insert(0, q)
    payload = {"queries": queries[:max_items], "last": q}
    await save_setting_row(session, SETTING_RADAR_QUERY_HISTORY, payload)
    return payload
