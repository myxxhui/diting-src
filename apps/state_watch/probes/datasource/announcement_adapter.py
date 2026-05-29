"""公告事件适配器 — 读 cryo_guard.announcements（禁止 stub 假事件）.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
event_type: reduce / placement / pledge / exec_change / litigation / penalty
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_ANN_TYPE_MAP = {
    "reduce": "reduce",
    "减持": "reduce",
    "pledge": "pledge",
    "质押": "pledge",
    "exec_change": "exec_change",
    "人事变动": "exec_change",
    "litigation": "litigation",
    "诉讼": "litigation",
    "penalty": "penalty",
    "监管问询": "penalty",
}


@dataclass
class CorporateEvent:
    event_type: str
    event_date: datetime
    description: str
    severity: str = "low"
    amount: float = 0.0


def _cryo_db_path() -> Path:
    env = os.environ.get("CRYO_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "data" / "cryo_guard.db"


def _map_ann_type(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _ANN_TYPE_MAP.get(key, key or "neutral")


def fetch_events(symbol: str, days: int = 180) -> list[CorporateEvent]:
    db = _cryo_db_path()
    if not db.is_file():
        return []
    cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            """
            SELECT ann_type, ann_date, title
            FROM announcements
            WHERE symbol = ? AND ann_date >= ?
            ORDER BY ann_date DESC
            LIMIT 100
            """,
            (symbol, cutoff),
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.warning("cryo announcements 事件读取失败 symbol=%s err=%s", symbol, exc)
        return []

    events: list[CorporateEvent] = []
    for ann_type, ann_date, title in rows:
        et = _map_ann_type(str(ann_type))
        try:
            dt = datetime.strptime(str(ann_date), "%Y-%m-%d")
        except ValueError:
            continue
        severity = "high" if et in ("penalty", "litigation") else "medium" if et == "reduce" else "low"
        events.append(
            CorporateEvent(
                event_type=et,
                event_date=dt,
                description=str(title or "")[:256],
                severity=severity,
            )
        )
    return events
