"""ExitEngine 顶层编排：评估 → 冲突 → 缓冲到期 → 发布 sell_signal。

[Ref: 03_/04_维度四/.../step_07_冲突处理与回测.md §7.1 B]
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from apps.exit_engine.events.sell_signal_publisher import SellSignalPublisher
from apps.exit_engine.models.audit import AuditEntry
from apps.exit_engine.models.buffer import PendingSignal
from apps.exit_engine.models.position import Portfolio, Position
from apps.exit_engine.models.sell_signal import SellSignalEvent, SignalType
from apps.exit_engine.protocols import PROTOCOL_CLASSES
from apps.exit_engine.protocols.base import BaseProtocol
from apps.exit_engine.protocols.rebalance import RebalanceProtocol
from apps.exit_engine.protocols.take_profit import TakeProfitProtocol
from apps.exit_engine.services.audit_logger import AuditLogger
from apps.exit_engine.services.buffer_manager import BufferManager
from apps.exit_engine.services.conflict_resolver import ConflictResolution, ConflictResolver
from apps.exit_engine.services.protocol_runner import ProtocolEvaluation, evaluate_and_audit, evaluate_with_buffer


@dataclass
class OrchestratorResult:
    position_id: str
    symbol: str
    evaluations: list[ProtocolEvaluation] = field(default_factory=list)
    publishable_events: list[SellSignalEvent] = field(default_factory=list)
    winner: Optional[SellSignalEvent] = None
    published: bool = False
    stream_msg_id: Optional[str] = None
    conflict_audit_id: Optional[str] = None
    triggered_protocols: list[str] = field(default_factory=list)


def _build_context(position: Position, portfolio: Portfolio, extra: Optional[dict]) -> dict[str, Any]:
    ctx = dict(extra or {})
    mv = position.market_value
    if mv is not None:
        ctx.setdefault("mv", mv)
        ctx.setdefault("market_value", mv)
    ctx.setdefault("total", portfolio.total_value)
    ctx.setdefault("portfolio_value", portfolio.total_value)
    if portfolio.total_value > 0 and mv is not None:
        ctx.setdefault("current_weight", mv / portfolio.total_value)
    return ctx


def _pending_to_event(pending: PendingSignal) -> SellSignalEvent:
    try:
        signal_type = SignalType(pending.protocol_name)
    except ValueError:
        signal_type = SignalType.STOP_LOSS
    return SellSignalEvent(
        symbol=pending.symbol,
        signal_type=signal_type,
        trigger_price=pending.trigger_price,
        current_price=pending.triggered_price,
        protocol=pending.protocol_name,
        advice=pending.advice or "",
        reason=pending.reason or "",
        position_id=pending.position_id,
        audit_id=pending.audit_id,
        sell_ratio=pending.sell_ratio,
        triggered_at=pending.triggered_at,
        buffer_end_at=None,
        is_revocable=True,
    )


def _is_publishable(eval_result: ProtocolEvaluation, protocol: BaseProtocol) -> bool:
    if not eval_result.triggered or eval_result.event is None:
        return False
    if eval_result.buffer_enqueued:
        return False
    if protocol.buffer_days > 0 and isinstance(protocol, (TakeProfitProtocol, RebalanceProtocol)):
        return False
    return True


class ExitEngineOrchestrator:
    def __init__(
        self,
        session: Session,
        *,
        publisher: Optional[SellSignalPublisher] = None,
        resolver: Optional[ConflictResolver] = None,
        publish: bool = True,
    ) -> None:
        self.session = session
        self.publisher = publisher or SellSignalPublisher()
        self.resolver = resolver or ConflictResolver()
        self.publish = publish
        self._protocols: list[BaseProtocol] = [cls() for cls in PROTOCOL_CLASSES]

    def evaluate_position(
        self,
        position: Position,
        portfolio: Portfolio,
        *,
        context: Optional[dict[str, Any]] = None,
        user_id: str = "default",
        now: Optional[datetime] = None,
    ) -> OrchestratorResult:
        ctx = _build_context(position, portfolio, context)
        evaluations: list[ProtocolEvaluation] = []
        publishable: list[SellSignalEvent] = []

        for protocol in self._protocols:
            if isinstance(protocol, (TakeProfitProtocol, RebalanceProtocol)):
                result = evaluate_with_buffer(protocol, position, session=self.session, context=ctx, user_id=user_id)
            else:
                result = evaluate_and_audit(protocol, position, context=ctx, session=self.session, user_id=user_id)
            evaluations.append(result)
            if _is_publishable(result, protocol):
                event = result.event
                if event is not None:
                    event.audit_id = result.audit_id
                    event.position_id = position.id
                    publishable.append(event)

        fired = BufferManager(self.session).expire_due(now=now)
        for pending in fired:
            if pending.position_id == position.id:
                publishable.append(_pending_to_event(pending))

        resolution = self.resolver.resolve(publishable)
        result = OrchestratorResult(
            position_id=position.id,
            symbol=position.symbol,
            evaluations=evaluations,
            publishable_events=publishable,
            winner=resolution.winner,
            triggered_protocols=resolution.triggered_protocols,
        )

        if resolution.winner is None:
            for ev in evaluations:
                if ev.triggered and ev.audit_id:
                    pass
            return result

        conflict_audit_id = resolution.audit_id
        winner = resolution.winner
        AuditLogger(self.session).log(
            AuditEntry(
                audit_id=conflict_audit_id,
                position_id=position.id,
                symbol=position.symbol,
                protocol_name=winner.signal_type.value,
                decision="conflict_resolved",
                priority=None,
                trigger_price=winner.trigger_price,
                current_price=winner.current_price,
                reason=winner.reason,
                advice=winner.advice,
                triggered_protocols=resolution.triggered_protocols,
                event_id=winner.event_id,
                user_id=user_id,
            )
        )
        result.conflict_audit_id = conflict_audit_id
        winner.audit_id = conflict_audit_id

        if self.publish:
            msg_id = self.publisher.publish(
                winner,
                session=self.session,
                triggered_protocols=resolution.triggered_protocols,
                user_id=user_id,
            )
            result.published = True
            result.stream_msg_id = msg_id

        return result

    def evaluate_portfolio(
        self,
        portfolio: Portfolio,
        *,
        context_by_symbol: Optional[dict[str, dict[str, Any]]] = None,
        user_id: str = "default",
    ) -> list[OrchestratorResult]:
        ctx_map = context_by_symbol or {}
        return [
            self.evaluate_position(
                pos,
                portfolio,
                context=ctx_map.get(pos.symbol),
                user_id=user_id,
            )
            for pos in portfolio.positions
        ]


def evaluate_protocols_dry(
    position: Position,
    portfolio: Portfolio,
    *,
    context: Optional[dict[str, Any]] = None,
) -> ConflictResolution:
    """回测用：仅跑协议 check+trigger，无 DB/Redis。"""
    ctx = _build_context(position, portfolio, context)
    events: list[SellSignalEvent] = []
    for cls in PROTOCOL_CLASSES:
        protocol = cls()
        check = protocol.check(position, ctx)
        if check.triggered:
            signal = protocol.trigger(position, check)
            events.append(protocol.output_event(signal))
    return ConflictResolver().resolve(events)
