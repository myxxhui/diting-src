#!/usr/bin/env python3
"""D2 ThesisCard → D0 ThesisProposedPayload 字段级对齐检查（diff=0 准出）。

[Ref: 03_/02_维度二/.../step_05 §7.2 deep-step05-schema-d0]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from apps.copilot.modules.recommendation.schema import ThesisProposedPayload
from apps.deep_strike.db.database import AsyncSessionLocal, init_db
from apps.deep_strike.engines.evidence_models import Evidence, EvidenceChain, EvidenceType
from apps.deep_strike.engines.thesis.d0_payload import card_to_d0_payload, d0_field_diff
from apps.deep_strike.engines.thesis.generator import ThesisCardGenerator
from apps.deep_strike.engines.thesis.schema import ThesisCardSchema
from sqlalchemy import select

from apps.deep_strike.db.models import ThesisCard


def _sample_evidence(symbol: str) -> EvidenceChain:
    base = f"标的 {symbol} schema 对齐样本"
    return EvidenceChain(
        symbol=symbol,
        items=[
            Evidence(type=EvidenceType.FINANCIAL, source="schema", content=base + "：财务面经营现金流改善，毛利率企稳回升。"),
            Evidence(type=EvidenceType.ANNOUNCEMENT, source="schema", content=base + "：近期公告披露订单落地，交付节奏可跟踪验证。"),
            Evidence(type=EvidenceType.INDUSTRY, source="schema", content=base + "：行业景气度回升，龙头份额有提升空间与逻辑。"),
        ],
    )


async def _sample_card() -> ThesisCardSchema:
    gen = ThesisCardGenerator(enable_timer=False)
    return await gen.generate(
        symbol="300308",
        name="中际旭创",
        playbook_id="profit_capture",
        confidence=0.82,
        decision_hint="watch",
        evidence_chain=_sample_evidence("300308"),
    )


async def _db_cards(limit: int = 5) -> list[ThesisCardSchema]:
    await init_db()
    out: list[ThesisCardSchema] = []
    async with AsyncSessionLocal() as session:
        rows = (
            await session.scalars(select(ThesisCard).order_by(ThesisCard.id.desc()).limit(limit))
        ).all()
        for row in rows:
            from apps.deep_strike.engines.thesis.schema import EvidenceItem, ValuationAnchor

            out.append(
                ThesisCardSchema(
                    thesis_id=row.thesis_id,
                    symbol=row.symbol,
                    name=row.name,
                    playbook_id=row.playbook_id,
                    confidence=row.confidence,
                    thesis_summary=row.thesis_summary,
                    evidence_chain=[EvidenceItem.model_validate(e) for e in row.evidence_chain],
                    risks=row.risks,
                    valuation_anchor=ValuationAnchor.model_validate(row.valuation_anchor),
                    action=row.action,
                    pass_event_id=row.pass_event_id,
                    scan_log_id=row.scan_log_id,
                    status=row.status,
                    timer_signal=row.timer_signal,
                )
            )
    return out


def _check_one(card: ThesisCardSchema, label: str) -> tuple[bool, str]:
    payload = card_to_d0_payload(card)
    extra = d0_field_diff(payload)
    if extra:
        return False, f"{label}: 多余字段 {extra}"
    try:
        ThesisProposedPayload.model_validate(payload)
    except Exception as exc:
        return False, f"{label}: D0 校验失败 {exc}"
    return True, f"{label}: diff=0 · D0 validate OK · thesis_id={card.thesis_id[:8]}..."


async def main() -> int:
    cards: list[tuple[str, ThesisCardSchema]] = []
    sample = await _sample_card()
    cards.append(("sample_generator", sample))

    db_cards = await _db_cards(5)
    for i, c in enumerate(db_cards):
        cards.append((f"db_card_{i}_{c.symbol}", c))

    if not cards:
        print("❌ 无样本卡可检查", file=sys.stderr)
        return 1

    ok = 0
    for label, card in cards:
        passed, msg = _check_one(card, label)
        print(("✅" if passed else "❌") + " " + msg)
        if passed:
            ok += 1

    total = len(cards)
    print(f"\nschema_check_d0: {ok}/{total} passed · field_diff=0")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
