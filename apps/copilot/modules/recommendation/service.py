"""推荐池服务(M2)。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import ThesisCard, User, UserDecision
from apps.copilot.modules.recommendation.pdf_generator import render_thesis_pdf
from apps.copilot.modules.recommendation.schema import UserActionPayload

MAX_WEEKLY = 5


@dataclass
class ThesisView:
    thesis_id: str
    symbol: str
    name: str
    thesis_summary: str
    evidence_chain: list[str]
    risks: list[str]
    valuation_anchor: dict
    action: str
    proposed_at: str
    user_action: Optional[str]


async def _ensure_user(session: AsyncSession, user_id: str = "default") -> User:
    user = await session.scalar(select(User).where(User.user_id == user_id))
    if user is None:
        user = User(user_id=user_id, name="默认用户")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def _user_action_map(session: AsyncSession, user_pk: int) -> dict[str, str]:
    rows = await session.scalars(
        select(UserDecision).where(UserDecision.user_pk == user_pk)
    )
    return {r.thesis_id: r.action for r in rows}


async def list_pool(
    session: AsyncSession, user_id: str = "default", days: int = 7
) -> list[ThesisView]:
    user = await _ensure_user(session, user_id)
    since = datetime.utcnow() - timedelta(days=days)

    cards = await session.scalars(
        select(ThesisCard)
        .where(ThesisCard.proposed_at >= since)
        .order_by(desc(ThesisCard.proposed_at))
    )
    actions = await _user_action_map(session, user.id)

    views: list[ThesisView] = []
    for c in cards:
        ua = actions.get(c.thesis_id)
        if ua in ("join", "not_interested"):
            continue
        views.append(_to_view(c, ua))
        if len(views) >= MAX_WEEKLY:
            break
    return views


async def get_thesis(
    session: AsyncSession, thesis_id: str, user_id: str = "default"
) -> Optional[ThesisView]:
    user = await _ensure_user(session, user_id)
    card = await session.scalar(
        select(ThesisCard).where(ThesisCard.thesis_id == thesis_id)
    )
    if card is None:
        return None
    actions = await _user_action_map(session, user.id)
    return _to_view(card, actions.get(thesis_id))


async def record_action(
    session: AsyncSession,
    thesis_id: str,
    payload: UserActionPayload,
    user_id: str = "default",
) -> ThesisView:
    user = await _ensure_user(session, user_id)
    existing = await session.scalar(
        select(UserDecision).where(
            UserDecision.user_pk == user.id, UserDecision.thesis_id == thesis_id
        )
    )
    if existing is None:
        session.add(
            UserDecision(user_pk=user.id, thesis_id=thesis_id, action=payload.action)
        )
    else:
        existing.action = payload.action
    await session.commit()
    view = await get_thesis(session, thesis_id, user_id)
    assert view is not None, "thesis 必须存在才能记录操作"
    return view


async def export_pdf(session: AsyncSession, thesis_id: str) -> Optional[bytes]:
    card = await session.scalar(
        select(ThesisCard).where(ThesisCard.thesis_id == thesis_id)
    )
    if card is None:
        return None
    return render_thesis_pdf({
        "thesis_id": card.thesis_id,
        "symbol": card.symbol,
        "name": card.name,
        "thesis_summary": card.thesis_summary,
        "evidence_chain": card.evidence_chain,
        "risks": card.risks,
        "valuation_anchor": card.valuation_anchor,
        "action": card.action,
        "proposed_at": card.proposed_at.strftime("%Y-%m-%d %H:%M"),
    })


def _to_view(card: ThesisCard, user_action: Optional[str]) -> ThesisView:
    return ThesisView(
        thesis_id=card.thesis_id,
        symbol=card.symbol,
        name=card.name,
        thesis_summary=card.thesis_summary,
        evidence_chain=list(card.evidence_chain or []),
        risks=list(card.risks or []),
        valuation_anchor=dict(card.valuation_anchor or {}),
        action=card.action,
        proposed_at=card.proposed_at.strftime("%Y-%m-%d %H:%M"),
        user_action=user_action,
    )
