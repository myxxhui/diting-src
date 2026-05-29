#!/usr/bin/env python3
"""SP5 recent advice 分布（只读 event_logs）。"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from apps.exit_engine.db.init_db import init
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.models.event_log import EventLogORM
from apps.exit_engine.services.stream_consumer import TIMER_SIGNAL_STREAM


def main() -> int:
    init()
    db = SessionLocal()
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        db.query(EventLogORM)
        .filter(
            EventLogORM.stream_key == TIMER_SIGNAL_STREAM,
            EventLogORM.handled.is_(True),
            EventLogORM.created_at >= since,
        )
        .all()
    )
    stages: Counter[str] = Counter()
    for row in rows:
        try:
            payload = json.loads(row.payload)
            stages[payload.get("stage", "unknown")] += 1
        except json.JSONDecodeError:
            stages["invalid_json"] += 1
    db.close()
    print(f"近 7 日 SP5 event_logs: {len(rows)} 条")
    for stage, cnt in stages.most_common():
        print(f"  {stage}: {cnt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
