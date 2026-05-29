"""Stream 消费者状态 API。

[Ref: 03_/04_维度四/.../step_05 §1 E]
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.exit_engine.config import settings
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.models.event_log import EventLogORM
from apps.exit_engine.services.stream_consumer import HEALTH_CHANGE_STREAM, TIMER_SIGNAL_STREAM

router = APIRouter(prefix="/api/consumer", tags=["consumer"])


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/health_change/status")
def health_change_consumer_status(db: Session = Depends(get_db)) -> dict:
    total = db.scalar(
        select(func.count()).select_from(EventLogORM).where(
            EventLogORM.stream_key == HEALTH_CHANGE_STREAM
        )
    ) or 0
    handled = db.scalar(
        select(func.count()).select_from(EventLogORM).where(
            EventLogORM.stream_key == HEALTH_CHANGE_STREAM,
            EventLogORM.handled.is_(True),
        )
    ) or 0
    recent = db.scalars(
        select(EventLogORM)
        .where(EventLogORM.stream_key == HEALTH_CHANGE_STREAM)
        .order_by(EventLogORM.id.desc())
        .limit(5)
    ).all()
    return {
        "stream": HEALTH_CHANGE_STREAM,
        "consumer_group": settings.health_consumer_group,
        "total": total,
        "handled": handled,
        "handled_rate": round(handled / total, 4) if total else 1.0,
        "recent": [
            {"msg_id": r.msg_id, "handled": r.handled, "error": r.error}
            for r in recent
        ],
    }


@router.get("/timer_signal/status")
def timer_signal_consumer_status(db: Session = Depends(get_db)) -> dict:
    total = db.scalar(
        select(func.count()).select_from(EventLogORM).where(
            EventLogORM.stream_key == TIMER_SIGNAL_STREAM
        )
    ) or 0
    handled = db.scalar(
        select(func.count()).select_from(EventLogORM).where(
            EventLogORM.stream_key == TIMER_SIGNAL_STREAM,
            EventLogORM.handled.is_(True),
        )
    ) or 0
    return {
        "stream": TIMER_SIGNAL_STREAM,
        "consumer_group": settings.sp5_consumer_group,
        "total": total,
        "handled": handled,
    }
