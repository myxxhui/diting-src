"""K8s Pod 启动前：建表、SoT 持仓导入、Campaign 导入（等待 Redis）。"""
from __future__ import annotations

import asyncio
import logging

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.modules.planning.service import import_portfolio_to_campaign
from apps.copilot.services.redis_wait import wait_for_sync_redis
from apps.copilot.services.sot_importer import import_sot_holdings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("copilot.k8s.bootstrap")


async def _main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        holdings = await import_sot_holdings(session, user_id="default")
        await session.commit()
    log.info("SoT holdings 导入: %s", holdings)

    log.info("等待 Redis 就绪…")
    redis_client = wait_for_sync_redis(timeout_sec=180.0)
    log.info("Redis 就绪")

    from apps.copilot.modules.executing.executing_warmup import (
        warm_executing_all_redis_from_pg,
    )

    async with AsyncSessionLocal() as session:
        warm_stats = await warm_executing_all_redis_from_pg(session, redis_client)
    log.info("Executing PG→Redis 预热: %s", warm_stats)

    async with AsyncSessionLocal() as session:
        campaign = await import_portfolio_to_campaign(session, redis_client=redis_client)
    log.info("Campaign 导入: %s", campaign)


if __name__ == "__main__":
    asyncio.run(_main())
