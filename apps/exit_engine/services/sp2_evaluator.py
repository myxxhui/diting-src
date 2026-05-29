"""SP2 带连续交易日缓冲的评估入口.

[Ref: 03_/04_维度四/.../step_04_SP2止盈协议.md]
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.exit_engine.models.audit import AuditEntry
from apps.exit_engine.models.position import Position
from apps.exit_engine.models.protocol_log import ProtocolLogORM
from apps.exit_engine.protocol_config import load_sp2_config
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.services.audit_logger import AuditLogger
from apps.exit_engine.services.protocol_runner import ProtocolEvaluation, evaluate_with_buffer
from apps.exit_engine.services.sp2_streak import evaluate_streak
from apps.exit_engine.services.trading_calendar import is_trading_day


def _load_hit_map(
    session: Session,
    *,
    position_id: str,
    protocol_name: str,
    exclude_date: Optional[date] = None,
) -> dict[date, bool]:
    stmt = select(ProtocolLogORM).where(
        ProtocolLogORM.position_id == position_id,
        ProtocolLogORM.protocol_name == protocol_name,
    )
    rows = session.scalars(stmt).all()
    out: dict[date, bool] = {}
    for row in rows:
        if exclude_date is not None and row.trade_date == exclude_date:
            continue
        out[row.trade_date] = bool(row.hit)
    return out


def _upsert_protocol_log(
    session: Session,
    *,
    position: Position,
    protocol_name: str,
    trade_date: date,
    hit: bool,
    buffer_state: str,
    return_pct: Optional[float],
) -> ProtocolLogORM:
    stmt = select(ProtocolLogORM).where(
        ProtocolLogORM.position_id == position.id,
        ProtocolLogORM.protocol_name == protocol_name,
        ProtocolLogORM.trade_date == trade_date,
    )
    row = session.scalars(stmt).first()
    if row is None:
        row = ProtocolLogORM(
            position_id=position.id,
            symbol=position.symbol,
            protocol_name=protocol_name,
            trade_date=trade_date,
            hit=hit,
            buffer_state=buffer_state,
            return_pct=return_pct,
        )
        session.add(row)
    else:
        row.hit = hit
        row.buffer_state = buffer_state
        row.return_pct = return_pct
    return row


def evaluate_sp2_with_streak(
    position: Position,
    *,
    session: Session,
    trade_date: Optional[date] = None,
    user_id: str = "default",
) -> ProtocolEvaluation:
    """按交易日记录 protocol_logs；连续 buffer_days 日命中才触发 SP2."""
    trade_date = trade_date or date.today()
    if not is_trading_day(trade_date):
        audit_id = str(uuid.uuid4())
        AuditLogger(session).log(
            AuditEntry(
                audit_id=audit_id,
                position_id=position.id,
                symbol=position.symbol,
                protocol_name="take_profit",
                decision="skip_non_trading_day",
                priority=2,
                current_price=position.current_price,
                return_pct=position.return_pct,
                reason=f"{trade_date} 非交易日，跳过 SP2 评估",
                user_id=user_id,
            )
        )
        return ProtocolEvaluation(
            protocol_name="take_profit",
            triggered=False,
            signal=None,
            event=None,
            audit_id=audit_id,
            buffer_enqueued=None,
        )

    proto = TakeProfitProtocol(config=load_sp2_config())
    check = proto.check(position, {})
    hit_today = check.triggered
    hit_map = _load_hit_map(
        session,
        position_id=position.id,
        protocol_name=proto.protocol_name.value,
        exclude_date=trade_date,
    )
    buffer_state, should_trigger, streak = evaluate_streak(
        hit_today=hit_today,
        hit_by_date=hit_map,
        trade_date=trade_date,
        buffer_days=proto.buffer_days,
    )

    if not hit_today:
        _upsert_protocol_log(
            session,
            position=position,
            protocol_name=proto.protocol_name.value,
            trade_date=trade_date,
            hit=False,
            buffer_state="not_met",
            return_pct=position.return_pct,
        )
        audit_id = str(uuid.uuid4())
        AuditLogger(session).log(
            AuditEntry(
                audit_id=audit_id,
                position_id=position.id,
                symbol=position.symbol,
                protocol_name=proto.protocol_name.value,
                decision="abstain",
                priority=proto.priority,
                current_price=position.current_price,
                return_pct=position.return_pct,
                reason=str(check.context.get("reason", "条件未满足")),
                user_id=user_id,
            )
        )
        session.flush()
        return ProtocolEvaluation(
            protocol_name=proto.protocol_name.value,
            triggered=False,
            signal=None,
            event=None,
            audit_id=audit_id,
            buffer_enqueued=None,
        )

    if not should_trigger:
        _upsert_protocol_log(
            session,
            position=position,
            protocol_name=proto.protocol_name.value,
            trade_date=trade_date,
            hit=True,
            buffer_state=buffer_state,
            return_pct=position.return_pct,
        )
        audit_id = str(uuid.uuid4())
        AuditLogger(session).log(
            AuditEntry(
                audit_id=audit_id,
                position_id=position.id,
                symbol=position.symbol,
                protocol_name=proto.protocol_name.value,
                decision="buffer_progress",
                priority=proto.priority,
                current_price=position.current_price,
                return_pct=position.return_pct,
                reason=f"SP2 连续命中 {streak}/{proto.buffer_days} 交易日，待发信号",
                advice=f"pending({streak}/{proto.buffer_days})",
                user_id=user_id,
            )
        )
        session.flush()
        return ProtocolEvaluation(
            protocol_name=proto.protocol_name.value,
            triggered=False,
            signal=None,
            event=None,
            audit_id=audit_id,
            buffer_enqueued=None,
        )

    _upsert_protocol_log(
        session,
        position=position,
        protocol_name=proto.protocol_name.value,
        trade_date=trade_date,
        hit=True,
        buffer_state="triggered",
        return_pct=position.return_pct,
    )
    session.flush()
    return evaluate_with_buffer(proto, position, session=session, user_id=user_id)
