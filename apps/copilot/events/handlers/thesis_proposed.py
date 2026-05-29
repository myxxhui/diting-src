"""维度二 thesis_proposed 事件处理器。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import EventLog, ThesisCard
from apps.copilot.modules.recommendation.schema import ThesisProposedPayload

logger = logging.getLogger("copilot.handler.thesis_proposed")

STREAM_KEY = "events:thrust:thesis_proposed"


async def handle_thesis_proposed(
    session: AsyncSession, payload: dict[str, Any], msg_id: str
) -> None:
    raw_event_id = str(payload.get("event_id") or msg_id)
    session.add(
        EventLog(
            stream_key=STREAM_KEY,
            msg_id=msg_id,
            event_type=str(payload.get("event_type") or "thesis_proposed"),
            symbol=str(payload.get("symbol") or ""),
            payload=payload,
            trace_id=payload.get("trace_id"),
        )
    )
    try:
        parsed = ThesisProposedPayload.model_validate(payload)
    except ValidationError as exc:
        logger.warning(
            "thesis_proposed 5 必填校验失败 event_id=%s errors=%s",
            raw_event_id,
            exc.errors(),
        )
        await session.commit()
        return

    existing = await session.scalar(
        select(ThesisCard).where(ThesisCard.thesis_id == parsed.thesis_id)
    )
    if existing is not None:
        await session.commit()
        return

    ts = parsed.timestamp
    proposed_at = ts.replace(tzinfo=None) if ts.tzinfo else ts

    session.add(
        ThesisCard(
            thesis_id=parsed.thesis_id,
            symbol=parsed.symbol,
            name=parsed.name,
            thesis_summary=parsed.thesis_summary,
            evidence_chain=parsed.evidence_chain,
            risks=parsed.risks,
            valuation_anchor=parsed.valuation_anchor.model_dump(),
            action=parsed.action,
            pass_event_id=parsed.pass_event_id,
            proposed_at=proposed_at,
        )
    )
    await session.commit()
