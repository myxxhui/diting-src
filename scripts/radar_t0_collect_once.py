#!/usr/bin/env python3
"""T0 一次性采集 · 读 ``radar_t0_collect_symbols`` SoT（禁止 holdings 自动灌表）。

用法:
  python scripts/radar_t0_collect_once.py --list
  python scripts/radar_t0_collect_once.py --symbol 601138
  python scripts/radar_t0_collect_once.py --all

[Ref: 27_ §2.1.1 · §5.2 radar-t0-collect]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass


async def _list_symbols() -> None:
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.radar.t0.symbol_list import (
        list_collect_symbol_rows,
        row_to_dict,
    )

    await init_db()
    async with AsyncSessionLocal() as session:
        rows = await list_collect_symbol_rows(session, enabled_only=False)
    print(json.dumps([row_to_dict(r) for r in rows], ensure_ascii=False, indent=2))


async def _run(*, symbol: str | None, all_enabled: bool) -> int:
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.radar.t0.jobs.collect_once import collect_once
    from apps.copilot.modules.radar.t0.symbol_list import upsert_collect_symbol

    await init_db()
    symbols: list[str] | None = None
    if symbol:
        symbols = [symbol.zfill(6)[-6:]]
    elif not all_enabled:
        print("请指定 --symbol 或 --all", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as session:
        if symbol:
            await upsert_collect_symbol(
                session,
                symbol=symbols[0],
                enrolled_by="cli",
                enabled=True,
            )
            await session.commit()
        results = await collect_once(session, symbols=symbols, job_id="collect-once-cli")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    errors = [r for r in results if r.get("status") == "error"]
    if not results and all_enabled:
        print("⚠️ collect 表无 enabled 标的", file=sys.stderr)
        return 0
    return 1 if errors else 0


def main() -> None:
    p = argparse.ArgumentParser(description="雷达 T0 collect-once（SoT: radar_t0_collect_symbols）")
    p.add_argument("--list", action="store_true", help="打印采集标的列表")
    p.add_argument("--symbol", help="单标的 6 位代码（UPSERT 入表后采集）")
    p.add_argument("--all", action="store_true", help="采集表内全部 enabled 标的")
    args = p.parse_args()

    if args.list:
        asyncio.run(_list_symbols())
        return
    raise SystemExit(asyncio.run(_run(symbol=args.symbol, all_enabled=args.all)))


if __name__ == "__main__":
    main()
