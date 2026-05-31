#!/usr/bin/env python3
"""step_12：从持仓 SoT 导入 Campaign + 三支柱订阅（等待 Redis 就绪）。"""
from __future__ import annotations

import asyncio
import json
import sys

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.modules.planning.service import import_portfolio_to_campaign
from apps.copilot.services.redis_wait import wait_for_sync_redis


async def main() -> int:
    await init_db()
    print("▶ 等待 Redis PONG…", file=sys.stderr)
    r = wait_for_sync_redis()
    print("✅ Redis 就绪", file=sys.stderr)

    async with AsyncSessionLocal() as session:
        result = await import_portfolio_to_campaign(session, redis_client=r)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
