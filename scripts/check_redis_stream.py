#!/usr/bin/env python3
"""检查 Redis Stream 是否存在（tier-2 就绪探测）。"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", required=True)
    args = parser.parse_args()

    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        import redis

        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        info = client.xinfo_stream(args.stream)
        print(f"✅ Redis OK · stream={args.stream} · length={info.get('length', 0)}")
        return 0
    except Exception as exc:
        print(f"❌ Redis/stream 不可用: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
