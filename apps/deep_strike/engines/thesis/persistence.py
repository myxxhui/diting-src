"""thesis 卡片持久化 + Redis 投递。

[Ref: 03_/02_维度二/.../step_05_thesis卡片生成器.md §7.1 D/H]
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from apps.deep_strike.config import settings
from apps.deep_strike.db.models import ThesisCard, TimerSignalRecord
from apps.deep_strike.engines.thesis.schema import ThesisCardSchema
from apps.deep_strike.events.publisher import get_publisher

logger = logging.getLogger(__name__)


async def save_thesis_card(session: AsyncSession, card: ThesisCardSchema) -> ThesisCard:
    row = ThesisCard(
        thesis_id=card.thesis_id,
        symbol=card.symbol,
        name=card.name,
        playbook_id=card.playbook_id,
        confidence=card.confidence,
        thesis_summary=card.thesis_summary,
        evidence_chain=[e.model_dump() for e in card.evidence_chain],
        risks=card.risks,
        valuation_anchor=card.valuation_anchor.model_dump(),
        action=card.action,
        pass_event_id=card.pass_event_id,
        scan_log_id=card.scan_log_id,
        status=card.status,
        timer_signal=card.timer_signal,
    )
    session.add(row)
    await session.flush()

    if card.timer_signal:
        meta = card.timer_signal.get("metadata") or {}
        session.add(
            TimerSignalRecord(
                thesis_card_id=card.thesis_id,
                symbol=card.symbol,
                timer_signal=card.timer_signal,
                generated_by=meta if isinstance(meta, dict) else None,
            )
        )
    await session.commit()
    await session.refresh(row)
    return row


def publish_timer_to_redis(card: ThesisCardSchema) -> list[str]:
    if not card.timer_signal:
        return []
    pub = get_publisher(settings.redis_url)
    return pub.publish_timer_phases_from_card(
        thesis_card_id=card.thesis_id,
        symbol=card.symbol,
        timer_signal=card.timer_signal,
    )
