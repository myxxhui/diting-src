#!/usr/bin/env python3
"""T0 → T1 fact_matrix CLI（27_ §5.2 radar-t1-build）。

用法:
  PYTHONPATH=. python3 scripts/radar_t1_build.py --symbol 601138
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from apps.copilot.modules.radar.scanner import collect_t0_live
from apps.copilot.modules.radar.t1_distill import build_t1_payload


async def main() -> int:
    parser = argparse.ArgumentParser(description="雷达 T0→T1 fact_matrix")
    parser.add_argument("--symbol", required=True, help="6 位标的代码")
    parser.add_argument("--t1-mode", default="rule", choices=("rule", "deepseek", "auto"))
    args = parser.parse_args()
    sym = str(args.symbol).zfill(6)[-6:]

    t0 = await collect_t0_live(sym)
    t1 = await build_t1_payload(t0, t1_mode=args.t1_mode if args.t1_mode != "auto" else None)

    out = {
        "symbol": sym,
        "fact_matrix": t1.get("fact_matrix"),
        "unavailable_data": t1.get("unavailable_data"),
        "micro": t0.get("micro"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    ms = (t1.get("fact_matrix") or {}).get("microstructure") or {}
    bars = (t0.get("micro") or {}).get("bars_250d") or {}
    print(
        f"\n摘要: bars_250d={bars.get('bars_count')} "
        f"price_action={ms.get('price_action', {}).get('tag')} "
        f"dragon_tiger={ms.get('dragon_tiger', {}).get('tag')}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
