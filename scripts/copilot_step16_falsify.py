#!/usr/bin/env python3
"""step_16 demo：建 4 类证伪任务 + 跑判定。"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, CampaignSymbol
from apps.copilot.modules.planning.falsify import (
    ensure_default_falsify_tasks,
    list_falsify_tasks,
    refresh_falsify_verdicts,
)
from apps.copilot.services.redis_wait import wait_for_sync_redis
from sqlalchemy import select


async def main() -> None:
    await init_db()
    redis = wait_for_sync_redis()
    async with AsyncSessionLocal() as session:
        camp = await session.scalar(select(Campaign).order_by(Campaign.id).limit(1))
        if camp is None:
            print("❌ 无 Campaign · 请先 make copilot-step12-campaign")
            return
        sym_row = await session.scalar(
            select(CampaignSymbol)
            .where(CampaignSymbol.campaign_id == camp.id)
            .order_by(CampaignSymbol.id)
            .limit(1)
        )
        sym = sym_row.symbol if sym_row and sym_row.symbol else "601138"
        subs = await ensure_default_falsify_tasks(session, camp.id, sym)
        await session.flush()
        updated = await refresh_falsify_verdicts(session, camp.id, redis)
        await session.commit()
        tasks = await list_falsify_tasks(session, camp.id, sym)
        print(f"campaign_id={camp.id} symbol={sym} tasks={len(subs)} refreshed={updated}")
        for t in tasks:
            print(
                f"  {t['falsify_type']:8} verdict={t['verdict']:7} "
                f"hypothesis={ (t.get('hypothesis') or '')[:40]}"
            )
        print("✅ step16 falsify demo 完成")


if __name__ == "__main__":
    asyncio.run(main())
