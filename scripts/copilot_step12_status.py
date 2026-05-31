#!/usr/bin/env python3
"""step_12 状态快照。"""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, CampaignSymbol, MonitorSubscription


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        campaigns = await session.scalars(select(Campaign))
        rows = list(campaigns)
        sym_count = await session.scalar(select(func.count()).select_from(CampaignSymbol))
        verdict_rows = await session.scalars(select(MonitorSubscription.verdict))
        dist: dict[str, int] = {}
        for v in verdict_rows:
            dist[v] = dist.get(v, 0) + 1
        print(
            json.dumps(
                {
                    "campaigns": len(rows),
                    "statuses": {c.status: sum(1 for x in rows if x.status == c.status) for c in rows},
                    "campaign_symbols": sym_count,
                    "verdict_distribution": dist,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
