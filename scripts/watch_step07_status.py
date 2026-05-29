#!/usr/bin/env python3
"""watch-step07 status — stream XLEN + 兜底表行数。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _load_dotenv() -> None:
    env_file = _ROOT / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    except ImportError:
        pass


_load_dotenv()

import redis
from sqlalchemy import func, select

from apps.state_watch.db.models import FailedStreamPublish
from apps.state_watch.db.session import init_db, session_ctx
from apps.state_watch.events.publisher import HEALTH_CHANGE_STREAM


async def _failed_count() -> int:
    await init_db()
    async with session_ctx() as session:
        return int(await session.scalar(select(func.count()).select_from(FailedStreamPublish)) or 0)


def main() -> int:
    url = os.environ.get("STATE_WATCH_REDIS_URL") or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    r = redis.from_url(url, decode_responses=True)
    xlen = r.xlen(HEALTH_CHANGE_STREAM)
    failed = asyncio.run(_failed_count())
    print(f"▶ Redis: {url}")
    print(f"▶ {HEALTH_CHANGE_STREAM} XLEN={xlen}")
    print(f"▶ failed_stream_publish 待重试={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
