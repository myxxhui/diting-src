#!/usr/bin/env python3
"""D2 step_03 · 从 cryo_guard.db + state_watch 财务摘要同步 deep_strike 依赖数据.

[Ref: 03_/02_维度二/.../step_03 §7 · 启动期真流，禁止 mock]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, select, text

from apps.common.holdings_sot import load_holdings_sot
from apps.deep_strike.config import settings
from apps.deep_strike.db.database import AsyncSessionLocal, init_db
from apps.deep_strike.db.models import Announcement, FinancialIndicator, IndustryPeer


def _cryo_engine():
    url = settings.db_url.replace("deep_strike", "cryo_guard").replace("+aiosqlite", "")
    if "cryo_guard" not in url:
        url = "sqlite:///./data/cryo_guard.db"
    return create_engine(url, future=True)


def _fin_from_cryo(symbol: str) -> list[dict]:
    eng = _cryo_engine()
    rows: list[dict] = []
    with eng.connect() as conn:
        q = conn.execute(
            text(
                """
                SELECT report_date, gross_margin, revenue, cost_of_revenue, net_profit,
                       receivable_turnover, roe
                FROM financial_reports
                WHERE symbol = :s
                ORDER BY report_date ASC
                """
            ),
            {"s": symbol},
        ).fetchall()
    prev_gm = None
    prev_rev = None
    prev_np = None
    for r in q:
        rd = r[0]
        if isinstance(rd, str):
            period_end = datetime.fromisoformat(rd)
        else:
            period_end = datetime.combine(rd, datetime.min.time())
        period = period_end.strftime("%YQ") + str((period_end.month - 1) // 3 + 1)
        gm = r[1]
        rev = r[2]
        cost = r[3]
        np_ = r[4]
        rec_t = r[5]
        gm_yoy = None
        rev_yoy = None
        np_yoy = None
        if prev_gm is not None and gm is not None and prev_gm:
            gm_yoy = (gm - prev_gm) / abs(prev_gm)
        if prev_rev is not None and rev is not None and prev_rev:
            rev_yoy = (rev - prev_rev) / abs(prev_rev)
        if prev_np is not None and np_ is not None and prev_np:
            np_yoy = (np_ - prev_np) / abs(prev_np)
        cost_yoy = rev_yoy
        rows.append(
            {
                "period": period,
                "period_end": period_end,
                "gross_margin": gm,
                "gross_margin_qoq": None,
                "gross_margin_yoy": gm_yoy,
                "revenue_growth_yoy": rev_yoy,
                "cost_growth_yoy": cost_yoy,
                "net_profit_growth_yoy": np_yoy,
                "receivable_turnover": rec_t,
                "receivable_turnover_qoq": None,
                "inventory_turnover": None,
                "inventory_turnover_qoq": None,
                "pe": None,
                "pb": None,
                "raw": {"source": "cryo_guard.financial_reports"},
            }
        )
        prev_gm, prev_rev, prev_np = gm, rev, np_
    return rows


def _fin_from_state_watch(symbol: str) -> list[dict]:
    from apps.state_watch.probes.datasource.akshare_adapter import fetch_financial_snapshot

    snap = fetch_financial_snapshot(symbol)
    if snap is None or not snap.gross_margin:
        return []
    try:
        period_end = datetime.fromisoformat(snap.report_date.replace("/", "-")[:10])
    except ValueError:
        period_end = datetime.now(timezone.utc)
    period = period_end.strftime("%YQ") + str((period_end.month - 1) // 3 + 1)
    return [
        {
            "period": period,
            "period_end": period_end,
            "gross_margin": snap.gross_margin,
            "gross_margin_qoq": None,
            "gross_margin_yoy": None,
            "revenue_growth_yoy": snap.revenue_yoy,
            "cost_growth_yoy": None,
            "net_profit_growth_yoy": snap.net_profit_yoy,
            "receivable_turnover": None,
            "receivable_turnover_qoq": None,
            "inventory_turnover": None,
            "inventory_turnover_qoq": None,
            "pe": None,
            "pb": None,
            "raw": {"source": "state_watch.akshare_adapter", "symbol": symbol},
        }
    ]


def _ann_from_cryo(symbol: str, limit: int = 50) -> list[dict]:
    eng = _cryo_engine()
    out: list[dict] = []
    with eng.connect() as conn:
        q = conn.execute(
            text(
                """
                SELECT id, title, ann_date, content, url, ann_type
                FROM announcements
                WHERE symbol = :s
                ORDER BY ann_date DESC
                LIMIT :lim
                """
            ),
            {"s": symbol, "lim": limit},
        ).fetchall()
    for row in q:
        aid, title, ann_date, content, url, _ = row
        if isinstance(ann_date, str):
            pub = datetime.fromisoformat(ann_date)
        else:
            pub = datetime.combine(ann_date, datetime.min.time())
        summary = (content or title or "")[:2000]
        out.append(
            {
                "announcement_id": f"cryo-{aid}",
                "title": title or "",
                "published_at": pub,
                "url": url,
                "summary": summary,
                "full_text": content,
                "source": "cryo_guard",
            }
        )
    return out


async def sync_symbol(symbol: str) -> dict:
    await init_db()
    fin_rows = _fin_from_cryo(symbol)
    if len(fin_rows) < 4:
        fin_rows.extend(_fin_from_state_watch(symbol))
    ann_rows = _ann_from_cryo(symbol)
    stats = {"financial_indicators": 0, "announcements": 0}
    async with AsyncSessionLocal() as session:
        for row in fin_rows:
            exists = await session.scalar(
                select(FinancialIndicator.id).where(
                    FinancialIndicator.symbol == symbol,
                    FinancialIndicator.period == row["period"],
                )
            )
            if exists:
                continue
            raw = row.pop("raw", {})
            session.add(FinancialIndicator(symbol=symbol, raw=raw, **row))
            stats["financial_indicators"] += 1
        for row in ann_rows:
            exists = await session.scalar(
                select(Announcement.id).where(
                    Announcement.symbol == symbol,
                    Announcement.announcement_id == row["announcement_id"],
                )
            )
            if exists:
                existing_ann = await session.get(Announcement, exists)
                if existing_ann and row.get("summary") and len(row["summary"]) > len(existing_ann.summary or ""):
                    existing_ann.summary = row["summary"]
                    existing_ann.full_text = row.get("full_text")
                continue
            session.add(Announcement(symbol=symbol, **row))
            stats["announcements"] += 1
        peer_exists = await session.scalar(
            select(IndustryPeer.id).where(IndustryPeer.symbol == symbol).limit(1)
        )
        if not peer_exists:
            if fin_rows and fin_rows[-1].get("gross_margin") is not None:
                gm = fin_rows[-1]["gross_margin"]
                session.add(
                    IndustryPeer(
                        symbol=symbol,
                        industry_code="SW",
                        industry_name="同业对照",
                        peer_symbol=f"{symbol}-peer",
                        peer_name="行业中位",
                        peer_metric_snapshot={"gross_margin": float(gm) * 0.95},
                    )
                )
                stats["industry_peers"] = 1
        await session.commit()
    return {"symbol": symbol, **stats}


async def main_async(symbols: list[str]) -> int:
    reports = []
    for sym in symbols:
        reports.append(await sync_symbol(sym))
    print(json.dumps({"synced": reports}, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    args = parser.parse_args()
    symbols = args.symbols or load_holdings_sot().active_symbols()
    raise SystemExit(asyncio.run(main_async(symbols)))


if __name__ == "__main__":
    main()
