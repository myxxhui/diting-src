"""审计日志记录器。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_03_SP1止损协议.md]
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.exit_engine.models.audit import AuditEntry, ExitAuditORM

logger = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self, session: Session):
        self.session = session

    def log(self, entry: AuditEntry) -> str:
        if not entry.audit_id:
            entry.audit_id = str(uuid.uuid4())
        self.session.add(entry.to_orm())
        self.session.commit()
        logger.debug(
            "audit logged: protocol=%s decision=%s symbol=%s",
            entry.protocol_name,
            entry.decision,
            entry.symbol,
        )
        return entry.audit_id

    def list(
        self,
        position_id: Optional[str] = None,
        symbol: Optional[str] = None,
        protocol_name: Optional[str] = None,
        decision: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 200,
    ) -> list[ExitAuditORM]:
        stmt = select(ExitAuditORM)
        if position_id:
            stmt = stmt.where(ExitAuditORM.position_id == position_id)
        if symbol:
            stmt = stmt.where(ExitAuditORM.symbol == symbol)
        if protocol_name:
            stmt = stmt.where(ExitAuditORM.protocol_name == protocol_name)
        if decision:
            stmt = stmt.where(ExitAuditORM.decision == decision)
        if start:
            stmt = stmt.where(ExitAuditORM.triggered_at >= start)
        if end:
            stmt = stmt.where(ExitAuditORM.triggered_at <= end)
        stmt = stmt.order_by(ExitAuditORM.triggered_at.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())
