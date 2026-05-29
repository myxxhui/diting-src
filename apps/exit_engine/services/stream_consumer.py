"""exit_engine Redis Stream 消费逻辑（SP3 health_change + SP5 timer_signal）。

[Ref: 03_/04_维度四/.../step_05_SP3_Thesis失效协议.md §7.1 B/I]
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from apps.exit_engine.config import settings
from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.models.event_log import EventLogORM
from apps.exit_engine.models.sell_signal import SellSignalEvent
from apps.exit_engine.protocols.sp5_financial_window import Sp5FinancialWindowProtocol, normalize_stage
from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol

logger = logging.getLogger(__name__)

HEALTH_CHANGE_STREAM = settings.health_change_stream
TIMER_SIGNAL_STREAM = "events:deep_strike:timer_signal"
HEALTH_CONSUMER_GROUP = "dim_four"
SP5_CONSUMER_GROUP = "dim_four_sp5"


def parse_stream_payload(data: dict[str, str]) -> dict[str, Any]:
    if "json" in data:
        return json.loads(data["json"])
    out: dict[str, Any] = {}
    for k, v in data.items():
        try:
            out[k] = json.loads(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


def record_event_log(
    session: Session,
    *,
    stream_key: str,
    msg_id: str,
    payload: dict[str, Any],
    handled: bool,
    error: str | None = None,
) -> EventLogORM:
    existing = (
        session.query(EventLogORM)
        .filter_by(stream_key=stream_key, msg_id=msg_id)
        .one_or_none()
    )
    if existing:
        return existing
    row = EventLogORM(
        stream_key=stream_key,
        msg_id=msg_id,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        handled=handled,
        error=error,
    )
    session.add(row)
    session.commit()
    return row


@dataclass
class ConsumerProcessResult:
    handled: bool
    triggered: bool
    protocol: str
    event: Optional[SellSignalEvent] = None
    reason: str = ""


def process_health_change(
    session: Session,
    payload: dict[str, Any],
    msg_id: str = "test-msg",
    *,
    skip_if_logged: bool = True,
) -> ConsumerProcessResult:
    """SP3：处理 D3 health_change 事件 payload。"""
    if skip_if_logged:
        existing = (
            session.query(EventLogORM)
            .filter_by(stream_key=HEALTH_CHANGE_STREAM, msg_id=msg_id)
            .one_or_none()
        )
        if existing and existing.handled:
            return ConsumerProcessResult(handled=True, triggered=False, protocol="SP3", reason="duplicate")

    symbol = payload.get("symbol", "")
    repo = HoldingsRepository(session)
    positions = [p for p in repo.list_active() if p.symbol == symbol] if symbol else []
    if not positions:
        record_event_log(
            session,
            stream_key=HEALTH_CHANGE_STREAM,
            msg_id=msg_id,
            payload=payload,
            handled=True,
            error=None,
        )
        return ConsumerProcessResult(handled=True, triggered=False, protocol="SP3", reason="not_in_holdings")

    proto = ThesisInvalidProtocol()
    ctx = {
        "new_state": payload.get("new_state", payload.get("thesis_status", "")),
        "narrative_label": payload.get("narrative_label", ""),
        "narrative_invalid_count": payload.get("narrative_invalid_count", 0),
        "health_change_event_id": payload.get("event_id", msg_id),
    }
    if ctx["new_state"] == "invalid":
        ctx["new_state"] = "exit"

    triggered_any = False
    last_event: Optional[SellSignalEvent] = None
    for pos in positions:
        signal = proto.evaluate(pos, ctx)
        if signal:
            triggered_any = True
            last_event = proto.output_event(signal)

    record_event_log(
        session,
        stream_key=HEALTH_CHANGE_STREAM,
        msg_id=msg_id,
        payload=payload,
        handled=True,
    )
    return ConsumerProcessResult(
        handled=True,
        triggered=triggered_any,
        protocol="SP3",
        event=last_event,
        reason="triggered" if triggered_any else "no_trigger",
    )


def process_timer_signal(
    session: Session,
    payload: dict[str, Any],
    msg_id: str = "test-msg",
    *,
    skip_if_logged: bool = True,
) -> ConsumerProcessResult:
    """SP5：处理 D2 timer_signal 事件。"""
    if skip_if_logged:
        existing = (
            session.query(EventLogORM)
            .filter_by(stream_key=TIMER_SIGNAL_STREAM, msg_id=msg_id)
            .one_or_none()
        )
        if existing and existing.handled:
            return ConsumerProcessResult(handled=True, triggered=False, protocol="SP5", reason="duplicate")

    symbol = payload.get("symbol", "")
    stage = normalize_stage(payload.get("stage"))
    if stage is None:
        record_event_log(
            session,
            stream_key=TIMER_SIGNAL_STREAM,
            msg_id=msg_id,
            payload=payload,
            handled=True,
            error="invalid stage",
        )
        return ConsumerProcessResult(handled=True, triggered=False, protocol="SP5", reason="invalid_stage")

    repo = HoldingsRepository(session)
    positions = [p for p in repo.list_active() if p.symbol == symbol] if symbol else []
    if not positions:
        record_event_log(
            session,
            stream_key=TIMER_SIGNAL_STREAM,
            msg_id=msg_id,
            payload=payload,
            handled=True,
        )
        return ConsumerProcessResult(handled=True, triggered=False, protocol="SP5", reason="not_in_holdings")

    proto = Sp5FinancialWindowProtocol()
    ctx = {
        "stage": stage,
        "timer_signal_event_id": payload.get("event_id", msg_id),
        "evidence_url": payload.get("evidence_url", ""),
        "financial_report_date": payload.get("financial_report_date", ""),
    }
    triggered_any = False
    last_event: Optional[SellSignalEvent] = None
    for pos in positions:
        signal = proto.evaluate(pos, ctx)
        if signal:
            triggered_any = True
            last_event = proto.output_event(signal)

    record_event_log(
        session,
        stream_key=TIMER_SIGNAL_STREAM,
        msg_id=msg_id,
        payload=payload,
        handled=True,
    )
    return ConsumerProcessResult(
        handled=True,
        triggered=triggered_any,
        protocol="SP5",
        event=last_event,
        reason="triggered" if triggered_any else "no_trigger",
    )
