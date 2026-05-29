#!/usr/bin/env python3
"""P1 tier-2 · XADD sell_signal 到云上 platform Redis，等待 K3s Copilot 消费（不本地抢消费）。

[Ref: 23_持仓标的售卖条件监控_需求实现表 · P1 M4]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import redis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", default=os.environ.get("EXIT_REDIS_URL") or os.environ.get("REDIS_URL"))
    parser.add_argument("--symbol", default="601138")
    parser.add_argument("--name", default="工业富联")
    parser.add_argument("--wait-sec", type=int, default=90)
    args = parser.parse_args()
    if not args.redis_url:
        print("❌ 请设 EXIT_REDIS_URL 或 --redis-url", file=sys.stderr)
        return 1

    stream = "events:exit:sell_signal"
    group = "copilot_alert_group"
    r = redis.from_url(args.redis_url, decode_responses=True)
    r.ping()
    print(f"▶ Redis OK · {args.redis_url}")

    before = r.xlen(stream)
    payload = {
        "symbol": args.symbol,
        "signal_type": "stop_loss",
        "trigger_price": "58.0",
        "current_price": "55.0",
        "protocol": "stop_loss",
        "advice": f"【tier-2 e2e】{args.name} 止损触发（仅建议，须人工确认）",
        "severity": "emergency",
        "sell_ratio": "1.0",
        "reason": "tier2 e2e stop_loss",
        "position_id": f"tier2-{args.symbol}",
        "event_id": str(uuid.uuid4()),
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "is_revocable": "False",
        "source": "exit-engine",
        "name": args.name,
    }
    msg_id = r.xadd(stream, payload)
    print(f"▶ XADD {stream} id={msg_id} (len {before} → {r.xlen(stream)})")

    deadline = time.time() + args.wait_sec
    while time.time() < deadline:
        try:
            groups = r.xinfo_groups(stream)
        except redis.ResponseError:
            groups = []
        pending = 0
        for g in groups:
            if g.get("name") == group:
                pending = int(g.get("pending", 0))
                last = g.get("last-delivered-id", "?")
                print(f"  … group={group} pending={pending} last={last}")
                break
        else:
            print(f"  … 等待 consumer group {group} 出现…")
        if pending == 0 and r.xlen(stream) > before:
            # 消息存在且无人 pending，可能已 ack
            try:
                info = r.xpending(stream, group)
                if isinstance(info, dict) and int(info.get("pending", 0)) == 0:
                    print("✅ 消息已被 Copilot consumer 处理（pending=0）")
                    print("   请查 Gmail/收件箱或: kubectl logs -n platform deploy/diting-copilot --tail=30")
                    return 0
            except redis.ResponseError:
                pass
        time.sleep(3)

    print("❌ 超时：Copilot 可能未消费（查 kubectl logs / SMTP secret）", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
