"""执行区 T0 探针 PVC 快照（ETF / level2 · 渠道 [B] 时回读）。

[Ref: 28_ · RADAR_T0_CACHE_DIR]
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    raw = os.environ.get("RADAR_T0_CACHE_DIR", "data/cache/radar_t0")
    return Path(raw)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("probe_cache 读失败 %s: %s", path, exc)
        return None


def _write_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


def _age_hours(written_at: str | None) -> float | None:
    if not written_at:
        return None
    try:
        ts = datetime.fromisoformat(written_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except ValueError:
        return None


def read_etf_snapshot(*, max_age_hours: float | None = None) -> dict[str, Any] | None:
    max_h = max_age_hours if max_age_hours is not None else float(
        os.environ.get("EXECUTING_ETF_CACHE_MAX_AGE_HOURS", "48")
    )
    path = _cache_root() / "_global" / "executing_etf_spot.json"
    doc = _read_json(path)
    if not doc or doc.get("status") != "ok":
        return None
    age = _age_hours(doc.get("written_at"))
    if age is not None and age > max_h:
        logger.info("ETF 快照过期 age_h=%.1f max=%.1f", age, max_h)
        return None
    return doc.get("payload")


def write_etf_snapshot(payload: dict[str, Any], *, source: str) -> None:
    path = _cache_root() / "_global" / "executing_etf_spot.json"
    _write_json(
        path,
        {
            "status": "ok",
            "written_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "payload": payload,
        },
    )
    logger.info("ETF 快照已写入 %s", path)


def read_level2_snapshot(
    symbol: str,
    *,
    max_age_hours: float | None = None,
) -> dict[str, Any] | None:
    max_h = max_age_hours if max_age_hours is not None else float(
        os.environ.get("EXECUTING_LEVEL2_CACHE_MAX_AGE_HOURS", "24")
    )
    sym = symbol.zfill(6)[-6:]
    path = _cache_root() / "_executing" / f"{sym}_level2.json"
    doc = _read_json(path)
    if not doc or doc.get("status") != "ok":
        return None
    age = _age_hours(doc.get("written_at"))
    if age is not None and age > max_h:
        return None
    return doc.get("payload")


def write_level2_snapshot(symbol: str, payload: dict[str, Any], *, source: str) -> None:
    sym = symbol.zfill(6)[-6:]
    path = _cache_root() / "_executing" / f"{sym}_level2.json"
    _write_json(
        path,
        {
            "status": "ok",
            "written_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "payload": payload,
        },
    )
    logger.info("level2 快照已写入 symbol=%s", sym)
