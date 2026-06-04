"""Planning 沙盒探针数据 TTL 清理。

规则：
- 活跃标的（planning/executing/archived）：保留 3 年。
- 淘汰标的（discarded）：保留 7 天。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from apps.copilot.db.database import AsyncSessionLocal
from apps.copilot.db.models import AssetState, ProbeResult, ProbeTask

ACTIVE_KEEP_DAYS = 365 * 3
DISCARDED_KEEP_DAYS = 7


async def run_cleanup() -> dict:
    now = datetime.now(timezone.utc)
    active_cutoff = now - timedelta(days=ACTIVE_KEEP_DAYS)
    discarded_cutoff = now - timedelta(days=DISCARDED_KEEP_DAYS)
    deleted_results = 0
    deleted_tasks = 0
    deleted_assets = 0

    async with AsyncSessionLocal() as session:
        active_ids = list(
            (
                await session.scalars(
                    select(AssetState.id).where(AssetState.status.in_(("planning", "executing", "archived")))
                )
            ).all()
        )
        discarded_ids = list(
            (await session.scalars(select(AssetState.id).where(AssetState.status == "discarded"))).all()
        )

        if active_ids:
            rs = await session.execute(
                delete(ProbeResult).where(
                    ProbeResult.probe_task_id.in_(
                        select(ProbeTask.id).where(ProbeTask.asset_id.in_(active_ids), ProbeResult.updated_at < active_cutoff)
                    )
                )
            )
            deleted_results += rs.rowcount or 0
            ts = await session.execute(
                delete(ProbeTask).where(ProbeTask.asset_id.in_(active_ids), ProbeTask.updated_at < active_cutoff)
            )
            deleted_tasks += ts.rowcount or 0

        if discarded_ids:
            rs2 = await session.execute(
                delete(ProbeResult).where(
                    ProbeResult.probe_task_id.in_(
                        select(ProbeTask.id).where(
                            ProbeTask.asset_id.in_(discarded_ids), ProbeResult.updated_at < discarded_cutoff
                        )
                    )
                )
            )
            deleted_results += rs2.rowcount or 0
            ts2 = await session.execute(
                delete(ProbeTask).where(
                    ProbeTask.asset_id.in_(discarded_ids), ProbeTask.updated_at < discarded_cutoff
                )
            )
            deleted_tasks += ts2.rowcount or 0
            aset = await session.execute(
                delete(AssetState).where(AssetState.status == "discarded", AssetState.updated_at < discarded_cutoff)
            )
            deleted_assets += aset.rowcount or 0

        await session.commit()

    return {
        "deleted_probe_results": deleted_results,
        "deleted_probe_tasks": deleted_tasks,
        "deleted_assets": deleted_assets,
    }


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(run_cleanup()))
