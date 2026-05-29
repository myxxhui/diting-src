"""缓冲期挂起信号 ORM 与 DTO。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.exit_engine.models.position import Base


class PendingSignalORM(Base):
    __tablename__ = "pending_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    protocol_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    position_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    trigger_price: Mapped[float] = mapped_column(Float, nullable=False)
    triggered_price: Mapped[float] = mapped_column(Float, nullable=False)
    sell_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    advice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    buffer_end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[str] = mapped_column(String, default="default")


@dataclass
class PendingSignal:
    audit_id: str
    protocol_name: str
    priority: int
    position_id: str
    symbol: str
    trigger_price: float
    triggered_price: float
    sell_ratio: float
    reason: str
    advice: str
    triggered_at: datetime
    buffer_end_at: datetime
    status: str = "pending"
    cancel_reason: Optional[str] = None
    extra: dict = field(default_factory=dict)
    user_id: str = "default"

    @classmethod
    def from_orm(cls, row: PendingSignalORM) -> PendingSignal:
        return cls(
            audit_id=row.audit_id,
            protocol_name=row.protocol_name,
            priority=row.priority,
            position_id=row.position_id,
            symbol=row.symbol,
            trigger_price=row.trigger_price,
            triggered_price=row.triggered_price,
            sell_ratio=row.sell_ratio,
            reason=row.reason or "",
            advice=row.advice or "",
            triggered_at=row.triggered_at,
            buffer_end_at=row.buffer_end_at,
            status=row.status,
            cancel_reason=row.cancel_reason,
            extra=json.loads(row.extra_json) if row.extra_json else {},
            user_id=row.user_id,
        )
