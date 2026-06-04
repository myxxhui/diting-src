"""行情雷达工作台偏好：前端可改、服务端 JSON 热加载（覆盖 env 默认值）。

[Ref: 24_行情解析工作台]
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PREFS_FILENAME = "workbench_prefs.json"
PREFS_STORAGE_KEY = "radar_workbench_prefs_v1"


def radar_cache_root() -> Path:
    """雷达 T0 缓存 / 工作台偏好 / 展示布局 共用目录（生产挂载 PVC）。"""
    raw = os.getenv("RADAR_T0_CACHE_DIR", "").strip()
    return Path(raw) if raw else Path("data/cache/radar_t0")


def _cache_root() -> Path:
    return radar_cache_root()


def _prefs_path() -> Path:
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / PREFS_FILENAME


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


def _env_defaults() -> dict[str, Any]:
    return {
        "version": 1,
        "enable_t2_default": True,
        "force_refresh_default": False,
        "file_cache_hours": _env_float("RADAR_FILE_RETENTION_HOURS", 24.0),
        "db_retention_days": _env_float("RADAR_DB_RETENTION_DAYS", 30.0),
        "max_versions_per_symbol": _env_int("RADAR_DB_MAX_VERSIONS", 7),
        "recent_analysis_days": _env_float("RADAR_RECENT_ANALYSIS_DAYS", 7.0),
        "t2_cache_hours": _env_float(
            "RADAR_T2_CACHE_MAX_AGE_HOURS",
            _env_float("RADAR_RECENT_ANALYSIS_DAYS", 7.0) * 24.0,
        ),
        "collect_auto_t1": True,
        "fuzzy_suggest": True,
    }


def load_prefs() -> dict[str, Any]:
    """合并 env 默认 + 磁盘覆盖（PUT 后即时生效）。"""
    base = _env_defaults()
    path = _prefs_path()
    if not path.is_file():
        return base
    try:
        override = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 workbench_prefs 失败: %s", exc)
        return base
    if isinstance(override, dict):
        for k, v in override.items():
            if k != "version" and v is not None:
                base[k] = v
    return base


def reset_prefs() -> dict[str, Any]:
    path = _prefs_path()
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("删除 workbench_prefs 失败: %s", exc)
    return _env_defaults()


def save_prefs(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "enable_t2_default",
        "force_refresh_default",
        "file_cache_hours",
        "db_retention_days",
        "max_versions_per_symbol",
        "recent_analysis_days",
        "t2_cache_hours",
        "collect_auto_t1",
        "fuzzy_suggest",
    }
    current = load_prefs()
    for k in allowed:
        if k in payload:
            current[k] = payload[k]
    path = _prefs_path()
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("workbench_prefs 已写入 %s", path)
    return current


def effective_float(key: str, env_name: str, fallback: float) -> float:
    """运行时读取：prefs 文件优先于 env。"""
    prefs = load_prefs()
    if key in prefs:
        try:
            return float(prefs[key])
        except (TypeError, ValueError):
            pass
    raw = os.getenv(env_name, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return fallback
