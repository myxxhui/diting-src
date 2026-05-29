#!/usr/bin/env python3
"""D0 step_05 状态：alert_logs + sell_signal stream。

[Ref: 03_/00_维度零/.../step_05 §7.2 copilot-step05-status]
"""
from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as aioredis
from sqlalchemy import func, select

from apps.copilot.config import settings
from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.services.alerts.models import AlertLog


async def main() -> int:
    await init_db()
    url = (
        os.environ.get("COPILOT_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or settings.redis_url
    )
    client = aioredis.from_url(url, decode_responses=True)
    try:
        await client.ping()
        xlen = await client.xlen("events:exit:sell_signal")
        print(f"Redis OK · events:exit:sell_signal XLEN={xlen}")
    except Exception as exc:
        print(f"⚠️  Redis: {exc}", file=sys.stderr)
    finally:
        await client.aclose()

    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(AlertLog)) or 0
        sell = await session.scalar(
            select(func.count())
            .select_from(AlertLog)
            .where(AlertLog.alert_type.like("sell_signal:%"))
        ) or 0
        recent = (
            await session.scalars(
                select(AlertLog).order_by(AlertLog.created_at.desc()).limit(5)
            )
        ).all()
        print(f"alert_logs: {total} 条 · sell_signal 类: {sell}")
        for row in recent:
            ch = row.channels_sent or {}
            email_ok = ch.get("email", {}).get("ok") if isinstance(ch, dict) else None
            print(f"  · {row.symbol} {row.alert_type} email_ok={email_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
