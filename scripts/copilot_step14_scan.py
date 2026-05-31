#!/usr/bin/env python3
"""step_14 migrate + 可选模式 C 扫描。"""
from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    from apps.copilot.db.database import AsyncSessionLocal, engine, init_db
    from apps.copilot.db.migrate_step14 import migrate_step14
    from apps.copilot.modules.radar.service import create_symbol_scan, ensure_model_profiles
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    await init_db()
    await migrate_step14(engine)

    symbol = os.environ.get("RADAR_SYMBOL", "601138").strip().zfill(6)[-6:]
    redis = None
    try:
        redis = wait_for_sync_redis(timeout_sec=90)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Redis 未就绪，扫描将以无 Redis 模式运行: {exc}")

    async with AsyncSessionLocal() as session:
        await ensure_model_profiles(session)
        result = await create_symbol_scan(
            session, query_text=symbol, redis_client=redis
        )
        await session.commit()
        c = (result.get("candidates") or [{}])[0]
        print(
            f"✅ scan_id={result['id']} symbol={c.get('symbol')} "
            f"phase={c.get('market_phase')} profit={c.get('profit_quality')} "
            f"confidence={c.get('confidence')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
