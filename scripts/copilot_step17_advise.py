"""step_17 demo：对持仓首只标的生成 advisory 建议。

[Ref: step_17_执行中仓位指导.md §9]
"""
from __future__ import annotations
import asyncio
import json
import sys
sys.path.insert(0, ".")

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, CampaignSymbol
from apps.copilot.modules.execution.advisor import generate_execution_advice
from apps.common.holdings_sot import load_holdings_sot
from sqlalchemy import select


async def main():
    await init_db()

    # 找或建 executing campaign
    async with AsyncSessionLocal() as s:
        camp = await s.scalar(
            select(Campaign).where(Campaign.status == "executing").limit(1)
        )
        if camp is None:
            camp = await s.scalar(select(Campaign).limit(1))
        if camp is None:
            camp = Campaign(name="step17-demo", theme="执行演示", status="executing")
            s.add(camp)
            await s.flush()
        cid = camp.id

        # 确保 campaign 有标的
        sot = load_holdings_sot()
        symbols = sot.portfolio_symbols() or sot.active_symbols()[:3]
        for sym in symbols[:3]:
            existing = await s.scalar(
                select(CampaignSymbol).where(
                    CampaignSymbol.campaign_id == cid,
                    CampaignSymbol.symbol == sym,
                )
            )
            if not existing:
                entry = sot.by_symbol(sym)
                s.add(CampaignSymbol(
                    campaign_id=cid,
                    symbol=sym,
                    name=entry.name if entry else sym,
                ))
        await s.commit()

        # 生成建议
        results = []
        for sym in symbols[:3]:
            try:
                result = await generate_execution_advice(s, cid, sym)
                results.append(result)
                print(f"  {sym}: {result['advice_action']}")
                print(f"    理由: {result.get('rationale', '')[:80]}")
                print(f"    实时价={result.get('current_price')} 成本={result.get('cost_price')} "
                      f"浮盈亏={result.get('unrealized_pnl_pct')} 安全={result.get('safety_status')}")
            except Exception as e:
                print(f"  {sym}: ⚠️ {e}")
        await s.commit()

    print("\n✅ step17 advise demo 完成")
    if results:
        print(json.dumps(results[0], ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
