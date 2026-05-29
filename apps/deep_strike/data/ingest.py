"""一键采集并写入 deep_strike SQLite。

用法：DEEP_STRIKE_MOCK=1 python -m apps.deep_strike.data.ingest 600519

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from apps.deep_strike.data import normalizer, validator
from apps.deep_strike.data.sources import akshare_source
from apps.deep_strike.data.sources.cninfo_source import fetch_full_announcement_text
from apps.deep_strike.db.database import AsyncSessionLocal, init_db
from apps.deep_strike.db.models import Announcement, FinancialIndicator, FinancialReport, IndustryPeer

logger = logging.getLogger(__name__)


async def ingest_symbol(symbol: str) -> dict[str, int]:
    await init_db()
    stats = {"financial_reports": 0, "financial_indicators": 0, "announcements": 0, "industry_peers": 0}

    async with AsyncSessionLocal() as session:
        for row in akshare_source.fetch_financial_report(symbol):
            if not validator.validate_financial_report(row):
                continue
            m = normalizer.to_financial_report(symbol, row)
            exists = await session.scalar(
                select(FinancialReport.id).where(
                    FinancialReport.symbol == m.symbol,
                    FinancialReport.report_type == m.report_type,
                    FinancialReport.period == m.period,
                )
            )
            if exists:
                continue
            session.add(m)
            stats["financial_reports"] += 1

        for row in akshare_source.fetch_financial_indicator(symbol):
            if not validator.validate_financial_indicator(row):
                continue
            m = normalizer.to_financial_indicator(symbol, row)
            exists = await session.scalar(
                select(FinancialIndicator.id).where(
                    FinancialIndicator.symbol == m.symbol,
                    FinancialIndicator.period == m.period,
                )
            )
            if exists:
                continue
            session.add(m)
            stats["financial_indicators"] += 1

        for row in akshare_source.fetch_announcements(symbol):
            if not validator.validate_announcement(row):
                continue
            full = row.get("full_text")
            aid = row.get("announcement_id")
            if not full and aid and not str(aid).startswith("mock-"):
                full = fetch_full_announcement_text(str(aid))
            row["full_text"] = full
            m = normalizer.to_announcement(symbol, row)
            exists = await session.scalar(
                select(Announcement.id).where(
                    Announcement.symbol == m.symbol,
                    Announcement.announcement_id == m.announcement_id,
                )
            )
            if exists:
                continue
            session.add(m)
            stats["announcements"] += 1

        for row in akshare_source.fetch_industry_peers(symbol):
            m = normalizer.to_industry_peer(symbol, row)
            exists = await session.scalar(
                select(IndustryPeer.id).where(
                    IndustryPeer.symbol == m.symbol,
                    IndustryPeer.peer_symbol == m.peer_symbol,
                )
            )
            if exists:
                continue
            session.add(m)
            stats["industry_peers"] += 1

        _ = akshare_source.fetch_realtime_quote(symbol)

        await session.commit()

    logger.info("ingest %s -> %s", symbol, stats)
    print(f"[deep-strike] ingest {symbol} done: {stats}")
    return stats


async def run(symbol: str, *, mock: bool = False) -> dict[str, int]:
    """测试/CLI 入口：mock=True 时等价于 DEEP_STRIKE_MOCK=1。"""
    import os

    if mock:
        os.environ["DEEP_STRIKE_MOCK"] = "1"
    return await ingest_symbol(symbol)


def main() -> None:
    import sys

    logging.basicConfig(level=logging.INFO)
    sym = sys.argv[1] if len(sys.argv) > 1 else "600519"
    asyncio.run(ingest_symbol(sym))


if __name__ == "__main__":
    main()
