#!/usr/bin/env python3
"""step_15 demo：生命周期判定 + regime 巡检订阅。"""
from __future__ import annotations

import asyncio

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, CampaignSymbol
from apps.copilot.modules.roadmap.service import assess_campaign_regime
from apps.copilot.services.redis_wait import wait_for_sync_redis
from sqlalchemy import select


async def main() -> None:
    await init_db()
    redis = wait_for_sync_redis(timeout_sec=5.0)
    async with AsyncSessionLocal() as session:
        camp = await session.scalar(select(Campaign).limit(1))
        if camp is None:
            camp = Campaign(theme="step15-regime-demo", status="planning", funnel_stage="roadmap")
            session.add(camp)
            await session.flush()
        sym = await session.scalar(
            select(CampaignSymbol).where(CampaignSymbol.campaign_id == camp.id).limit(1)
        )
        if sym is None:
            session.add(
                CampaignSymbol(
                    campaign_id=camp.id,
                    symbol="601138",
                    name="工业富联",
                    analysis_snapshot={"market_phase": "expectation"},
                )
            )
            await session.flush()
        rows = await assess_campaign_regime(session, camp.id, redis_client=redis)
        await session.commit()
        print(f"campaign_id={camp.id} regime_assessments={len(rows)}")
        for r in rows:
            print(
                f"  {r['symbol']} horizon={r['horizon_class']} "
                f"confirm={r['confirm_state']} next={r.get('next_wave_window')}"
            )


if __name__ == "__main__":
    asyncio.run(main())
