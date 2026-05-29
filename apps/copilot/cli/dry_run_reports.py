"""本地干跑生成报告（不入库 / 不推送），写入 ./tmp/reports/。

用法：
    python -m apps.copilot.cli.dry_run_reports --kind daily --date 2026-05-15 --user default

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.services.reports.daily import DailyReportGenerator
from apps.copilot.services.reports.ledger_adapter import ReportLedgerAdapter
from apps.copilot.services.reports.renderer import ReportRenderer
from apps.copilot.services.reports.weekly import WeeklyReportGenerator


async def run(kind: str, day: date, user: str) -> None:
    await init_db()
    out = Path("./tmp/reports")
    out.mkdir(parents=True, exist_ok=True)
    async with AsyncSessionLocal() as session:
        ledger = ReportLedgerAdapter(AsyncSessionLocal)
        if kind == "daily":
            gen = DailyReportGenerator(session, ledger)
        else:
            gen = WeeklyReportGenerator(session, ledger)
        ctx = await gen.aggregate(user, day)
        r = ReportRenderer()
        html_path = out / f"{kind}_{ctx.period_label}.html"
        md_path = out / f"{kind}_{ctx.period_label}.md"
        html_path.write_text(r.render(kind, "html", ctx), encoding="utf-8")
        md_path.write_text(r.render(kind, "md", ctx), encoding="utf-8")
        print(f"✅ 写出 {html_path} 与 {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--user", default="default")
    args = parser.parse_args()
    asyncio.run(run(args.kind, date.fromisoformat(args.date), args.user))


if __name__ == "__main__":
    main()
