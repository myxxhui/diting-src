"""单协议评估 + 自动审计落库。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_03_SP1止损协议.md]
[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from apps.exit_engine.models.audit import AuditEntry
from apps.exit_engine.models.buffer import PendingSignal
from apps.exit_engine.models.position import Position
from apps.exit_engine.models.sell_signal import SellSignal, SellSignalEvent
from apps.exit_engine.protocols.base import BaseProtocol
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.services.audit_logger import AuditLogger
from apps.exit_engine.services.buffer_manager import BufferManager


@dataclass
class ProtocolEvaluation:
    protocol_name: str
    triggered: bool
    signal: Optional[SellSignal]
    event: Optional[SellSignalEvent]
    audit_id: str
    buffer_enqueued: Optional[bool] = None


def evaluate_and_audit(
    protocol: BaseProtocol,
    position: Position,
    context: dict | None = None,
    session: Optional[Session] = None,
    user_id: str = "default",
) -> ProtocolEvaluation:
    context = context or {}
    check_result = protocol.check(position, context)
    audit_id = str(uuid.uuid4())
    if check_result.triggered:
        signal = protocol.trigger(position, check_result)
        event = protocol.output_event(signal)
        decision = "trigger"
        reason = signal.reason
        advice = signal.advice
        trigger_price = signal.trigger_price
        sell_ratio = signal.sell_ratio
    else:
        signal = None
        event = None
        decision = "abstain"
        reason = str(check_result.context.get("reason", "条件未满足"))
        advice = ""
        trigger_price = check_result.context.get("trigger_price")
        if trigger_price is not None:
            trigger_price = float(trigger_price)
        sell_ratio = None

    if session is not None:
        entry = AuditEntry(
            audit_id=audit_id,
            position_id=position.id,
            symbol=position.symbol,
            protocol_name=protocol.protocol_name.value,
            decision=decision,
            priority=protocol.priority,
            trigger_price=trigger_price,
            current_price=position.current_price,
            return_pct=position.return_pct,
            sell_ratio=sell_ratio,
            reason=reason,
            advice=advice,
            triggered_protocols=[protocol.protocol_name.value] if check_result.triggered else [],
            user_id=user_id,
        )
        AuditLogger(session).log(entry)

    return ProtocolEvaluation(
        protocol_name=protocol.protocol_name.value,
        triggered=check_result.triggered,
        signal=signal,
        event=event,
        audit_id=audit_id,
        buffer_enqueued=None,
    )


def evaluate_with_buffer(
    protocol: BaseProtocol,
    position: Position,
    *,
    session: Session,
    context: dict | None = None,
    user_id: str = "default",
) -> ProtocolEvaluation:
    """带缓冲期的评估：触发且 buffer_days>0 时写入 pending_signals，仅记一条 buffer_pending 审计。"""
    ctx = context or {}
    check_result = protocol.check(position, ctx)
    audit_id = str(uuid.uuid4())

    if not check_result.triggered:
        reason = str(check_result.context.get("reason", "条件未满足"))
        trigger_price = check_result.context.get("trigger_price")
        if trigger_price is not None:
            trigger_price = float(trigger_price)
        else:
            trigger_price = None
        AuditLogger(session).log(
            AuditEntry(
                audit_id=audit_id,
                position_id=position.id,
                symbol=position.symbol,
                protocol_name=protocol.protocol_name.value,
                decision="abstain",
                priority=protocol.priority,
                trigger_price=trigger_price,
                current_price=position.current_price,
                return_pct=position.return_pct,
                reason=reason,
                advice="",
                user_id=user_id,
            )
        )
        if isinstance(protocol, TakeProfitProtocol) and protocol.is_reverse_condition(position):
            cancelled = BufferManager(session).cancel_by_position(
                position_id=position.id,
                protocol_name=protocol.protocol_name.value,
                reason=f"反向条件触发:return_pct={position.return_pct}",
            )
            if cancelled:
                AuditLogger(session).log(
                    AuditEntry(
                        audit_id=str(uuid.uuid4()),
                        position_id=position.id,
                        symbol=position.symbol,
                        protocol_name=protocol.protocol_name.value,
                        decision="buffer_cancelled",
                        priority=protocol.priority,
                        current_price=position.current_price,
                        return_pct=position.return_pct,
                        reason=f"缓冲期内反向条件触发,自动取消 {cancelled} 笔挂起信号",
                        user_id=user_id,
                    )
                )
        return ProtocolEvaluation(
            protocol_name=protocol.protocol_name.value,
            triggered=False,
            signal=None,
            event=None,
            audit_id=audit_id,
            buffer_enqueued=None,
        )

    signal = protocol.trigger(position, check_result)
    event = protocol.output_event(signal)
    event.audit_id = audit_id

    if protocol.buffer_days <= 0:
        AuditLogger(session).log(
            AuditEntry(
                audit_id=audit_id,
                position_id=position.id,
                symbol=position.symbol,
                protocol_name=protocol.protocol_name.value,
                decision="trigger",
                priority=protocol.priority,
                trigger_price=signal.trigger_price,
                current_price=position.current_price,
                return_pct=position.return_pct,
                sell_ratio=signal.sell_ratio,
                reason=signal.reason,
                advice=signal.advice,
                triggered_protocols=[protocol.protocol_name.value],
                user_id=user_id,
            )
        )
        return ProtocolEvaluation(
            protocol_name=protocol.protocol_name.value,
            triggered=True,
            signal=signal,
            event=event,
            audit_id=audit_id,
            buffer_enqueued=None,
        )

    buffer_end_at = signal.triggered_at + timedelta(days=protocol.buffer_days)
    pending = PendingSignal(
        audit_id=audit_id,
        protocol_name=protocol.protocol_name.value,
        priority=protocol.priority,
        position_id=position.id,
        symbol=position.symbol,
        trigger_price=signal.trigger_price,
        triggered_price=signal.current_price,
        sell_ratio=signal.sell_ratio,
        reason=signal.reason,
        advice=signal.advice,
        triggered_at=signal.triggered_at,
        buffer_end_at=buffer_end_at,
        status="pending",
        extra=signal.extra,
        user_id=user_id,
    )
    pending_saved, is_new = BufferManager(session).enqueue(pending)
    if is_new:
        AuditLogger(session).log(
            AuditEntry(
                audit_id=audit_id,
                position_id=position.id,
                symbol=position.symbol,
                protocol_name=protocol.protocol_name.value,
                decision="buffer_pending",
                priority=protocol.priority,
                trigger_price=signal.trigger_price,
                current_price=position.current_price,
                return_pct=position.return_pct,
                sell_ratio=signal.sell_ratio,
                reason=f"已挂起 {protocol.buffer_days} 天缓冲期,到期前可被反向条件取消",
                advice=signal.advice,
                triggered_protocols=[protocol.protocol_name.value],
                user_id=user_id,
            )
        )
    else:
        audit_id = pending_saved.audit_id
        event.audit_id = audit_id

    return ProtocolEvaluation(
        protocol_name=protocol.protocol_name.value,
        triggered=True,
        signal=signal,
        event=event,
        audit_id=audit_id,
        buffer_enqueued=is_new,
    )
