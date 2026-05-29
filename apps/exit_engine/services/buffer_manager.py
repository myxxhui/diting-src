"""缓冲期管理器(SP2 / SP4 共用)。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.exit_engine.models.buffer import PendingSignal, PendingSignalORM

logger = logging.getLogger(__name__)


class BufferManager:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, signal: PendingSignal) -> tuple[PendingSignal, bool]:
        stmt = (
            select(PendingSignalORM)
            .where(
                PendingSignalORM.position_id == signal.position_id,
                PendingSignalORM.protocol_name == signal.protocol_name,
                PendingSignalORM.status == "pending",
            )
            .limit(1)
        )
        existing = self.session.scalars(stmt).first()
        if existing is not None:
            logger.info(
                "buffer enqueue 幂等命中:position_id=%s protocol=%s 已有 pending",
                signal.position_id,
                signal.protocol_name,
            )
            return PendingSignal.from_orm(existing), False

        row = PendingSignalORM(
            audit_id=signal.audit_id,
            protocol_name=signal.protocol_name,
            priority=signal.priority,
            position_id=signal.position_id,
            symbol=signal.symbol,
            trigger_price=signal.trigger_price,
            triggered_price=signal.triggered_price,
            sell_ratio=signal.sell_ratio,
            reason=signal.reason,
            advice=signal.advice,
            triggered_at=signal.triggered_at,
            buffer_end_at=signal.buffer_end_at,
            status="pending",
            extra_json=json.dumps(signal.extra, ensure_ascii=False),
            user_id=signal.user_id,
        )
        self.session.add(row)
        self.session.commit()
        return signal, True

    def cancel(self, audit_id: str, reason: str) -> bool:
        stmt = select(PendingSignalORM).where(PendingSignalORM.audit_id == audit_id).limit(1)
        row = self.session.scalars(stmt).first()
        if row is None or row.status != "pending":
            return False
        row.status = "cancelled"
        row.cancel_reason = reason
        self.session.commit()
        logger.info("buffer cancel: audit_id=%s reason=%s", audit_id, reason)
        return True

    def cancel_by_position(self, position_id: str, protocol_name: str, reason: str) -> int:
        stmt = select(PendingSignalORM).where(
            PendingSignalORM.position_id == position_id,
            PendingSignalORM.protocol_name == protocol_name,
            PendingSignalORM.status == "pending",
        )
        rows = list(self.session.scalars(stmt).all())
        for row in rows:
            row.status = "cancelled"
            row.cancel_reason = reason
        if rows:
            self.session.commit()
        return len(rows)

    def list_pending(
        self,
        position_id: Optional[str] = None,
        protocol_name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[PendingSignal]:
        stmt = select(PendingSignalORM).where(PendingSignalORM.status == "pending")
        if position_id:
            stmt = stmt.where(PendingSignalORM.position_id == position_id)
        if protocol_name:
            stmt = stmt.where(PendingSignalORM.protocol_name == protocol_name)
        if user_id:
            stmt = stmt.where(PendingSignalORM.user_id == user_id)
        stmt = stmt.order_by(PendingSignalORM.buffer_end_at.asc())
        return [PendingSignal.from_orm(r) for r in self.session.scalars(stmt).all()]

    def expire_due(self, now: Optional[datetime] = None) -> list[PendingSignal]:
        now = now or datetime.utcnow()
        stmt = select(PendingSignalORM).where(
            PendingSignalORM.status == "pending",
            PendingSignalORM.buffer_end_at <= now,
        )
        rows = list(self.session.scalars(stmt).all())
        fired: list[PendingSignal] = []
        for row in rows:
            row.status = "fired"
            fired.append(PendingSignal.from_orm(row))
        if fired:
            self.session.commit()
        return fired

    def has_pending(self, position_id: str, protocol_name: str) -> bool:
        stmt = (
            select(func.count())
            .select_from(PendingSignalORM)
            .where(
                PendingSignalORM.position_id == position_id,
                PendingSignalORM.protocol_name == protocol_name,
                PendingSignalORM.status == "pending",
            )
        )
        n = self.session.scalar(stmt) or 0
        return n > 0
