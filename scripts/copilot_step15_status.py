#!/usr/bin/env python3
"""step_15 状态快照。"""
from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import func, select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import CampaignTimeline, MonitorSubscription, RegimeAssessment


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        tl_count = await session.scalar(select(func.count()).select_from(CampaignTimeline))
        regime_count = await session.scalar(select(func.count()).select_from(RegimeAssessment))
        rows = await session.scalars(select(CampaignTimeline))
        flag_counter: Counter[str] = Counter()
        for r in rows:
            for f in r.feasibility_flags or []:
                flag_counter[f] += 1
        regime_rows = await session.scalars(select(RegimeAssessment))
        hc_counter = Counter(r.horizon_class for r in regime_rows)
        regime_mon = await session.scalar(
            select(func.count())
            .select_from(MonitorSubscription)
            .where(MonitorSubscription.pillar == "regime")
        )
        print(f"timeline_nodes={tl_count} regime_assessments={regime_count} regime_monitors={regime_mon}")
        print(f"flag_distribution={dict(flag_counter)}")
        print(f"horizon_distribution={dict(hc_counter)}")


if __name__ == "__main__":
    asyncio.run(main())
