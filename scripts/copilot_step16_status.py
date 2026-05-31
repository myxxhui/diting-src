#!/usr/bin/env python3
"""step_16 状态快照。"""
from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import func, select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import MonitorSubscription, StageArtifact
from apps.copilot.modules.planning.falsify import FALSIFY_TYPES


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        falsify_count = await session.scalar(
            select(func.count())
            .select_from(MonitorSubscription)
            .where(MonitorSubscription.falsify_type.in_(tuple(FALSIFY_TYPES)))
        )
        art_count = await session.scalar(
            select(func.count())
            .select_from(StageArtifact)
            .where(StageArtifact.workspace == "planning")
        )
        rows = await session.scalars(
            select(MonitorSubscription).where(
                MonitorSubscription.falsify_type.in_(tuple(FALSIFY_TYPES))
            )
        )
        verdict_counter = Counter(r.verdict for r in rows)
        type_counter = Counter(r.falsify_type for r in rows)
        print(f"falsify_subscriptions={falsify_count} planning_artifacts={art_count}")
        print(f"verdict_distribution={dict(verdict_counter)}")
        print(f"type_distribution={dict(type_counter)}")


if __name__ == "__main__":
    asyncio.run(main())
