#!/usr/bin/env python3
"""watch-step07 publisher smoke — 1 节点 force transition → XLEN+1。

[Ref: 03_/03_维度三/.../step_07 §7.2 watch-step07-publisher-smoke]
"""
from __future__ import annotations

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
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

import redis

from apps.state_watch.events.publisher import HEALTH_CHANGE_STREAM
from apps.state_watch.health.orchestrator import HealthOrchestrator, PositionSnapshot


def main() -> int:
    url = os.environ.get("STATE_WATCH_REDIS_URL") or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    r = redis.from_url(url, decode_responses=True)
    try:
        r.ping()
    except Exception as exc:
        print(f"❌ Redis 不可达 {url}: {exc}", file=sys.stderr)
        return 1

    before = r.xlen(HEALTH_CHANGE_STREAM)
    orch = HealthOrchestrator()
    result = orch.process(
        PositionSnapshot(
            symbol="601138",
            name="工业富联",
            state="growing",
            health_score=55.0,
            previous_health=80.0,
            push_level=0,
        )
    )
    after = r.xlen(HEALTH_CHANGE_STREAM)
    print(f"▶ Redis {url}")
    print(f"▶ {HEALTH_CHANGE_STREAM} XLEN {before} → {after}")
    print(f"▶ transition {result.old_state}→{result.new_state} published={result.published} msg_id={result.msg_id}")

    if not result.published or after <= before:
        print("❌ publisher smoke 失败：XLEN 未增加", file=sys.stderr)
        return 1
    print("✅ publisher smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
