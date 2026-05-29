"""Redis Stream 消费审计（msg_id 幂等）。

[Ref: 03_/04_维度四/.../step_05_SP3_Thesis失效协议.md §3 C1~C5]
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.exit_engine.models.position import Base


class EventLogORM(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stream_key: Mapped[str] = mapped_column(String(128), nullable=False)
    msg_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    handled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("stream_key", "msg_id", name="uq_event_logs_stream_msg"),
    )
