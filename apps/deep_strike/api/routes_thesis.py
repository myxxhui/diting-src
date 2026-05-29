"""thesis 卡片生成 API。

[Ref: 03_/02_维度二/.../step_05_thesis卡片生成器.md §7.1 F]
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.deep_strike.db.database import get_db
from apps.deep_strike.engines.evidence_models import Evidence, EvidenceChain, EvidenceType
from apps.deep_strike.engines.thesis.completeness import check_one
from apps.deep_strike.engines.thesis.generator import ThesisCardGenerator
from apps.deep_strike.engines.thesis.persistence import publish_timer_to_redis, save_thesis_card

router = APIRouter(prefix="/api/thesis", tags=["thesis"])


class EvidenceInput(BaseModel):
    evidence_type: str = "financial"
    content: str = Field(min_length=5)
    url: Optional[str] = None


class ThesisGenerateRequest(BaseModel):
    symbol: str
    name: str = ""
    playbook_id: str = "profit_capture"
    confidence: float = Field(ge=0.0, le=1.0, default=0.75)
    decision_hint: Literal["buy", "add", "watch", "strong_buy", "pass"] = "watch"
    evidence: list[EvidenceInput] = Field(min_length=3)
    scan_log_id: Optional[int] = None
    pass_event_id: Optional[str] = None
    enable_timer: bool = True
    publish_redis: bool = True


@router.post("/generate")
async def generate_thesis(body: ThesisGenerateRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """生成 thesis 卡（status=proposed）并落库；可选投递 timer_signal 到 Redis。"""
    items = []
    for e in body.evidence:
        try:
            et = EvidenceType(e.evidence_type)
        except ValueError:
            et = EvidenceType.FINANCIAL
        items.append(
            Evidence(
                type=et,
                source="api",
                content=e.content,
                url=e.url,
            )
        )
    chain = EvidenceChain(symbol=body.symbol, items=items)
    gen = ThesisCardGenerator(session=db, enable_timer=body.enable_timer)
    card = await gen.generate(
        symbol=body.symbol,
        name=body.name or body.symbol,
        playbook_id=body.playbook_id,
        confidence=body.confidence,
        decision_hint=body.decision_hint,
        evidence_chain=chain,
        scan_log_id=body.scan_log_id,
        pass_event_id=body.pass_event_id,
    )
    errors = check_one(card)
    if errors:
        raise HTTPException(status_code=422, detail={"completeness_errors": errors})

    row = await save_thesis_card(db, card)
    redis_msg_ids: list[str] = []
    if body.publish_redis and card.timer_signal:
        redis_msg_ids = publish_timer_to_redis(card)

    return {
        "thesis_id": card.thesis_id,
        "symbol": card.symbol,
        "status": card.status,
        "action": card.action,
        "timer_signal": card.timer_signal,
        "db_id": row.id,
        "redis_timer_msg_ids": redis_msg_ids,
    }
