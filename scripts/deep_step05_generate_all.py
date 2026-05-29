#!/usr/bin/env python3
"""为 my_holdings.yaml active 标的各生成 ≥1 thesis 卡（规则模板 · enable_timer=False）。"""
from __future__ import annotations

import asyncio
import sys

from apps.common.holdings_sot import load_holdings_sot
from apps.deep_strike.db.database import AsyncSessionLocal, init_db
from apps.deep_strike.engines.evidence_models import Evidence, EvidenceChain, EvidenceType
from apps.deep_strike.engines.thesis.completeness import check_one
from apps.deep_strike.engines.thesis.generator import ThesisCardGenerator
from apps.deep_strike.engines.thesis.persistence import save_thesis_card


def _sample_evidence(symbol: str) -> EvidenceChain:
    base = f"标的 {symbol} 启动期规则模板证据"
    items = [
        Evidence(type=EvidenceType.FINANCIAL, source="generate-all", content=base + "：财务面经营现金流改善，毛利率企稳。"),
        Evidence(type=EvidenceType.ANNOUNCEMENT, source="generate-all", content=base + "：近期公告披露订单落地，交付节奏可跟踪。"),
        Evidence(type=EvidenceType.INDUSTRY, source="generate-all", content=base + "：行业景气度回升，龙头份额有提升空间。"),
    ]
    return EvidenceChain(symbol=symbol, items=items)


async def _run() -> int:
    await init_db()
    holdings = [h for h in load_holdings_sot().holdings if h.active]
    if not holdings:
        print("❌ 无 active 持仓", file=sys.stderr)
        return 1

    ok = 0
    async with AsyncSessionLocal() as session:
        for h in holdings:
            symbol = h.symbol
            name = h.name or symbol
            gen = ThesisCardGenerator(session=session, enable_timer=False)
            card = await gen.generate(
                symbol=symbol,
                name=name,
                playbook_id="profit_capture",
                confidence=0.75,
                decision_hint="watch",
                evidence_chain=_sample_evidence(symbol),
            )
            errors = check_one(card)
            if errors:
                print(f"❌ {symbol} completeness 失败: {errors}", file=sys.stderr)
                return 1
            await save_thesis_card(session, card)
            ok += 1
            print(f"✅ {symbol} thesis_id={card.thesis_id}")

    print(f"✅ deep-step05-generate-all: {ok}/{len(holdings)} 卡已落库")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
