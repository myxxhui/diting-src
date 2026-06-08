#!/usr/bin/env python3
"""导出 #15 qmt_atr_trailing T0 底库样本（PG 日线 + Redis 盘中草稿 + 腾讯实时拉取）。

[Ref: 28_ §2.2.2]

用法:
  # 生产 Pod 内（推荐，含 PG/SQLite 全量）
  python scripts/dump_executing_qmt_t0.py --symbols 601138,002837,300502

  # 本机：Redis( prod.conn ) + 腾讯 fqkline + 可选 COPILOT_API
  REDIS_URL=redis://... python scripts/dump_executing_qmt_t0.py --local
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from typing import Any

# repo root on PYTHONPATH
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().zfill(6)[-6:] for s in raw.split(",") if s.strip()]


async def _dump_pg_and_t0(symbols: list[str]) -> dict[str, Any]:
    from sqlalchemy import func, select

    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.db.models import (
        ExecutingDailyBar,
        ExecutingT0Raw,
        ExecutingT0SyncWatermark,
    )
    from apps.copilot.modules.executing.collectors.daily_bars import rows_to_ohlcv_lists
    from apps.copilot.modules.executing.storage import load_daily_bars

    await init_db()
    out: dict[str, Any] = {"symbols": {}, "watermarks": []}
    async with AsyncSessionLocal() as session:
        wms = (await session.scalars(select(ExecutingT0SyncWatermark))).all()
        for w in wms:
            if w.job_id in ("quote-intraday", "quote-intraday-close", "l4-atr-bars-sync"):
                out["watermarks"].append(
                    {
                        "job_id": w.job_id,
                        "symbol": w.symbol,
                        "last_success_at": w.last_success_at.isoformat() if w.last_success_at else None,
                        "last_trade_date": w.last_trade_date.isoformat() if w.last_trade_date else None,
                        "last_row_count": w.last_row_count,
                        "last_error": w.last_error,
                    }
                )
        for sym in symbols:
            rows = await load_daily_bars(session, sym, limit=250)
            cnt = await session.scalar(
                select(func.count())
                .select_from(ExecutingDailyBar)
                .where(ExecutingDailyBar.symbol == sym, ExecutingDailyBar.adjust == "qfq")
            )
            t0_rows = (
                await session.scalars(
                    select(ExecutingT0Raw)
                    .where(
                        ExecutingT0Raw.symbol == sym,
                        ExecutingT0Raw.probe_key == "qmt_atr_trailing",
                    )
                    .order_by(ExecutingT0Raw.collected_at.desc())
                    .limit(3)
                )
            ).all()
            out["symbols"][sym] = {
                "pg_daily_bars": {
                    "count": int(cnt or 0),
                    "loaded": len(rows),
                    "date_range": (
                        [rows[0].trade_date.isoformat(), rows[-1].trade_date.isoformat()]
                        if rows
                        else None
                    ),
                    "source": "executing_daily_bars",
                    "last_5_bars": rows_to_ohlcv_lists(rows[-5:]) if rows else {},
                    "tail_bar": (
                        {
                            "trade_date": rows[-1].trade_date.isoformat(),
                            "open": rows[-1].open,
                            "high": rows[-1].high,
                            "low": rows[-1].low,
                            "close": rows[-1].close,
                            "volume": rows[-1].volume,
                        }
                        if rows
                        else None
                    ),
                },
                "executing_t0_raw_latest": [
                    {
                        "trade_date": r.trade_date.isoformat() if r.trade_date else None,
                        "collected_at": r.collected_at.isoformat() if r.collected_at else None,
                        "source": r.source,
                        "payload": r.payload_json,
                    }
                    for r in t0_rows
                ],
            }
    return out


def _dump_redis(symbols: list[str]) -> dict[str, Any]:
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return {"error": "REDIS_URL 未设置"}
    try:
        import redis  # type: ignore
    except ImportError:
        return {"error": "redis 包未安装"}

    client = redis.from_url(url, decode_responses=True)
    out: dict[str, Any] = {}
    for sym in symbols:
        keys = {
            "draft_bar": f"executing:draft_bar:{sym}",
            "quote": f"executing:quote:{sym}",
            "atr_intraday": f"executing:atr_intraday:{sym}",
        }
        sym_out: dict[str, Any] = {}
        for label, key in keys.items():
            raw = client.get(key)
            if not raw:
                sym_out[label] = None
                continue
            try:
                sym_out[label] = json.loads(raw)
            except json.JSONDecodeError:
                sym_out[label] = raw
        out[sym] = sym_out
    return out


def _dump_tencent_live(symbols: list[str]) -> dict[str, Any]:
    from apps.copilot.modules.executing.collectors.daily_bars import (
        fetch_tencent_daily_bars,
        rows_to_ohlcv_lists,
    )

    out: dict[str, Any] = {}
    for sym in symbols:
        rows, source = fetch_tencent_daily_bars(sym, days=5, min_bars=1)
        out[sym] = {
            "source": source,
            "count": len(rows),
            "bars": rows_to_ohlcv_lists(rows),
            "today_draft_candidate": (
                {
                    "trade_date": rows[-1].trade_date.isoformat(),
                    "open": rows[-1].open,
                    "high": rows[-1].high,
                    "low": rows[-1].low,
                    "close": rows[-1].close,
                    "volume": rows[-1].volume,
                    "is_today": rows[-1].trade_date == date.today(),
                }
                if rows
                else None
            ),
        }
    return out


def _fetch_api(base: str) -> dict[str, Any]:
    import urllib.request

    api: dict[str, Any] = {}
    for path in ("/api/executing/sync-status", "/api/executing/t1-batch"):
        try:
            with urllib.request.urlopen(f"{base.rstrip('/')}{path}", timeout=30) as resp:
                api[path] = json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001
            api[path] = {"error": str(exc)}
    return api


async def main() -> int:
    parser = argparse.ArgumentParser(description="导出 qmt_atr_trailing T0 数据")
    parser.add_argument(
        "--symbols",
        default=os.environ.get("EXECUTING_SYMBOLS", "601138,002837,300502"),
    )
    parser.add_argument(
        "--output",
        default="",
        help="输出 JSON 路径；默认 stdout",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="跳过 PG（仅 Redis + 腾讯 + API）",
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("COPILOT_API_BASE", "http://8.217.142.179:30080"),
    )
    args = parser.parse_args()
    symbols = _parse_symbols(args.symbols)

    report: dict[str, Any] = {
        "probe_key": "qmt_atr_trailing",
        "spec": "28_ §2.2.2 · PG executing_daily_bars + Redis draft_bar",
        "symbols_requested": symbols,
        "dumped_at": date.today().isoformat(),
    }

    if not args.local:
        try:
            report["pg_and_t0_raw"] = await _dump_pg_and_t0(symbols)
        except Exception as exc:  # noqa: BLE001
            report["pg_and_t0_raw"] = {"error": str(exc)}

    report["redis_intraday"] = _dump_redis(symbols)
    report["tencent_fqkline_live"] = _dump_tencent_live(symbols)
    if args.api_base:
        report["copilot_api"] = _fetch_api(args.api_base)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"✅ 已写入 {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
