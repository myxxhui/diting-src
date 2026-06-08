#!/usr/bin/env python3
"""导出 #16 15min K 线 T0（拉取 + 可选 Redis）。"""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="601138,002837,300502")
    parser.add_argument("--output", default="")
    parser.add_argument("--redis", action="store_true")
    args = parser.parse_args()
    syms = [s.strip().zfill(6)[-6:] for s in args.symbols.split(",") if s.strip()]

    from apps.copilot.modules.executing.collectors.bars_15m import (
        bars_to_payload,
        fetch_bars_15m_em,
        load_bars_15m_redis,
    )
    from apps.copilot.modules.executing.t1_operators.volume_price_div import (
        process_volume_price_div,
    )

    redis_client = None
    if args.redis:
        url = os.environ.get("REDIS_URL", "").strip()
        if url:
            import redis  # type: ignore

            redis_client = redis.from_url(url, decode_responses=True)

    out: dict = {"probe_key": "volume_price_div", "symbols": {}}
    for sym in syms:
        bars, source = fetch_bars_15m_em(sym)
        entry: dict = {"fetch": {"bars_count": len(bars), "source": source}}
        if bars:
            payload = bars_to_payload(sym, bars, source=source)
            entry["fetch"]["first_datetime"] = bars[0].datetime
            entry["fetch"]["last_datetime"] = bars[-1].datetime
            entry["fetch"]["tail_3"] = payload["bars"][-3:]
            try:
                entry["t1_preview"] = process_volume_price_div(bars, source=source)
            except Exception as exc:  # noqa: BLE001
                entry["t1_preview_error"] = str(exc)
        if redis_client:
            cached = load_bars_15m_redis(redis_client, sym)
            if cached:
                entry["redis"] = {
                    "collected_at": cached.get("collected_at"),
                    "bars_count": cached.get("bars_count"),
                    "last_bar": (cached.get("bars") or [])[-1:] if cached.get("bars") else [],
                }
            else:
                entry["redis"] = None
        out["symbols"][sym] = entry

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"✅ 已写入 {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0 if any(v.get("fetch", {}).get("bars_count", 0) >= 160 for v in out["symbols"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
