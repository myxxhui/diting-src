#!/usr/bin/env python3
"""D4 step_07 状态：sell_signal stream + sell_signals 表 + 兜底队列。

[Ref: 03_/04_维度四/.../step_07 §7.2 exit-step07-status]
"""
from __future__ import annotations

import os
import sys

import redis
from sqlalchemy import func, select

from apps.exit_engine.config import settings
from apps.exit_engine.db.init_db import init
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.models.failed_publish import FailedStreamPublishORM
from apps.exit_engine.models.sell_signal_record import SellSignalRecordORM


def main() -> int:
    init()
    url = os.environ.get("EXIT_REDIS_URL") or os.environ.get("REDIS_URL") or settings.redis_url
    try:
        client = redis.from_url(url, decode_responses=True)
        client.ping()
        xlen = client.xlen(settings.output_stream)
        print(f"Redis OK · {settings.output_stream} XLEN={xlen}")
    except Exception as exc:
        print(f"⚠️  Redis 不可达: {exc}", file=sys.stderr)

    db = SessionLocal()
    try:
        n_signals = db.scalar(select(func.count()).select_from(SellSignalRecordORM)) or 0
        n_failed = db.scalar(
            select(func.count()).select_from(FailedStreamPublishORM).where(
                FailedStreamPublishORM.retried_at.is_(None)
            )
        ) or 0
        recent = list(
            db.scalars(
                select(SellSignalRecordORM).order_by(SellSignalRecordORM.published_at.desc()).limit(5)
            ).all()
        )
        print(f"sell_signals 表: {n_signals} 条 · failed_stream_publish 待重试: {n_failed}")
        for row in recent:
            print(f"  · {row.symbol} {row.signal_type} @ {row.published_at}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
