"""审计日志 ORM 与 DTO。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_03_SP1止损协议.md]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.exit_engine.models.position import Base


class ExitAuditORM(Base):
    """卖出协议评估审计日志。"""

    __tablename__ = "exit_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    position_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    protocol_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    trigger_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sell_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    advice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triggered_protocols: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_published: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[str] = mapped_column(String, default="default")


@dataclass
class AuditEntry:
    """审计条目 DTO。"""

    audit_id: str
    position_id: str
    symbol: str
    protocol_name: str
    decision: str
    priority: Optional[int] = None
    trigger_price: Optional[float] = None
    current_price: Optional[float] = None
    return_pct: Optional[float] = None
    sell_ratio: Optional[float] = None
    reason: str = ""
    advice: str = ""
    triggered_protocols: list[str] = field(default_factory=list)
    event_id: Optional[str] = None
    event_published: bool = False
    user_id: str = "default"
    triggered_at: datetime = field(default_factory=datetime.utcnow)

    def to_orm(self) -> ExitAuditORM:
        return ExitAuditORM(
            audit_id=self.audit_id,
            position_id=self.position_id,
            symbol=self.symbol,
            protocol_name=self.protocol_name,
            decision=self.decision,
            priority=self.priority,
            triggered_at=self.triggered_at,
            trigger_price=self.trigger_price,
            current_price=self.current_price,
            return_pct=self.return_pct,
            sell_ratio=self.sell_ratio,
            reason=self.reason,
            advice=self.advice,
            triggered_protocols=json.dumps(self.triggered_protocols, ensure_ascii=False),
            event_id=self.event_id,
            event_published=self.event_published,
            user_id=self.user_id,
        )
