#!/usr/bin/env python3
"""D3 step_02 · 对 SoT active 标的批量跑 P1/P2 探针.

[Ref: 03_/03_维度三/.../step_02 §7.2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from apps.common.holdings_sot import load_holdings_sot
from apps.state_watch.probes.financial import FinancialProbe
from apps.state_watch.probes.news import NewsProbe

FINANCIAL_KEYS = (
    "revenue_yoy",
    "net_profit_yoy",
    "gross_margin",
    "operating_cf",
    "debt_ratio",
    "roe",
)


async def _run_financial(symbols: list[str]) -> dict:
    probe = FinancialProbe()
    rows = []
    for sym in symbols:
        result = await probe.fetch(sym)
        non_null = 0
        if result.success and result.data:
            non_null = sum(1 for k in FINANCIAL_KEYS if result.data.get(k) is not None)
        rows.append(
            {
                "symbol": sym,
                "success": result.success,
                "metrics_non_null": non_null,
                "coverage": round(non_null / len(FINANCIAL_KEYS), 2) if result.success else 0.0,
                "error": result.error or None,
            }
        )
    ok = sum(1 for r in rows if r["success"])
    avg_cov = sum(r["coverage"] for r in rows) / len(rows) if rows else 0.0
    return {"probe": "P1", "total": len(rows), "ok": ok, "avg_coverage": round(avg_cov, 2), "rows": rows}


async def _run_news(symbols: list[str]) -> dict:
    probe = NewsProbe()
    rows = []
    for sym in symbols:
        result = await probe.fetch(sym)
        count = int(result.data.get("total_count_7d", 0)) if result.success else 0
        rows.append(
            {
                "symbol": sym,
                "success": result.success,
                "total_count_7d": count,
                "sentiment_score_7d": result.data.get("sentiment_score_7d") if result.success else None,
                "error": result.error or None,
            }
        )
    ok = sum(1 for r in rows if r["success"])
    return {"probe": "P2", "total": len(rows), "ok": ok, "rows": rows}


async def _main(mode: str) -> int:
    sot = load_holdings_sot()
    symbols = sot.active_symbols()
    if not symbols:
        print("❌ SoT 无 active 标的", file=sys.stderr)
        return 1
    if mode == "financial":
        report = await _run_financial(symbols)
    elif mode == "news":
        report = await _run_news(symbols)
    elif mode == "coverage":
        fin = await _run_financial(symbols)
        news = await _run_news(symbols)
        report = {
            "financial": fin,
            "news": news,
            "summary": {
                "symbols": len(symbols),
                "p1_avg_coverage": fin["avg_coverage"],
                "p2_ok": news["ok"],
            },
        }
    else:
        print(f"未知 mode: {mode}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok", report.get("summary", {}).get("p2_ok", 1)) else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["financial", "news", "coverage"],
        help="financial=P1 | news=P2 | coverage=汇总",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.mode)))


if __name__ == "__main__":
    main()
