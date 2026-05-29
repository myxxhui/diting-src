#!/usr/bin/env python3
"""watch-step07 latency — state 变化到 XADD P95 <30s（本机应 ms 级）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from apps.state_watch.events.publisher import HealthChangePublisher
from apps.state_watch.health.orchestrator import HealthOrchestrator, PositionSnapshot


def main() -> int:
    mock_redis = MagicMock()
    mock_redis.xadd.return_value = "lat-0"
    orch = HealthOrchestrator(publisher=HealthChangePublisher(redis_client=mock_redis))

    samples: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        orch.process(
            PositionSnapshot(
                symbol="601138",
                state="growing",
                health_score=55.0,
                previous_health=80.0,
                push_level=0,
            )
        )
        samples.append(time.perf_counter() - t0)

    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    print(f"▶ orchestrator→XADD 延迟 P95={p95*1000:.2f}ms (n={len(samples)})")
    if p95 >= 30.0:
        print(f"❌ P95 {p95:.2f}s >= 30s", file=sys.stderr)
        return 1
    print("✅ latency OK (<30s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
