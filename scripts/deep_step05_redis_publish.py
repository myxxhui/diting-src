#!/usr/bin/env python3
"""D2 timer_signal 真流 xadd → 供 D4 SP5 消费验证。"""
from __future__ import annotations

import os
import sys

from apps.deep_strike.events.publisher import RedisPublisher, DEEP_STRIKE_TIMER_STREAM


def main() -> int:
    url = os.environ.get("REDIS_URL", "redis://8.217.158.218:30379/0")
    pub = RedisPublisher(redis_url=url)
    msg_id = pub.publish_timer_signal(
        thesis_card_id="deep-e2e-thesis",
        symbol="300308",
        stage="main_wave",
        evidence_url="https://example.com/deep-e2e",
        financial_report_date="2026-08-15",
    )
    if not msg_id:
        print(f"❌ xadd 失败 · stream={DEEP_STRIKE_TIMER_STREAM}", file=sys.stderr)
        return 1
    print(f"✅ D2 timer_signal xadd OK · msg_id={msg_id} · stream={DEEP_STRIKE_TIMER_STREAM}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
