#!/usr/bin/env python3
"""step_15 demo：2 标的入时间线 + 合理性 flag。"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign
from apps.copilot.modules.roadmap.service import add_timeline_entry


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        camp = await session.scalar(
            __import__("sqlalchemy", fromlist=["select"]).select(Campaign).limit(1)
        )
        if camp is None:
            camp = Campaign(theme="step15-demo", status="planning", funnel_stage="roadmap")
            session.add(camp)
            await session.flush()

        today = date.today()
        d1 = today + timedelta(days=45)
        d2 = today + timedelta(days=50)
        await add_timeline_entry(
            session,
            camp.id,
            symbol=os.environ.get("ROADMAP_SYMBOL_A", "601138"),
            anchor_date=d1,
            title="demo A 爆发点",
            sequence_no=1,
            target_weight_pct=60,
        )
        await add_timeline_entry(
            session,
            camp.id,
            symbol=os.environ.get("ROADMAP_SYMBOL_B", "300308"),
            anchor_date=d2,
            title="demo B 爆发点",
            sequence_no=2,
            target_weight_pct=60,
        )
        await session.commit()
        from apps.copilot.modules.roadmap.service import list_campaign_timeline

        items = await list_campaign_timeline(session, camp.id)
        print(f"campaign_id={camp.id} timeline_nodes={len(items)}")
        for it in items:
            print(
                f"  {it['symbol']} seq={it['sequence_no']} flags={it.get('feasibility_flags')}"
            )


if __name__ == "__main__":
    asyncio.run(main())
