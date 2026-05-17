"""月报生成：聚合 SCS / EV / 8 象限；WeasyPrint PDF 或 HTML 降级。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

import logging
import os
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from apps.copilot.services.ledger.ev import EVCalculator
from apps.copilot.services.ledger.models import AttributionRecord, MonthlyReport
from apps.copilot.services.ledger.scs import SCSCalculator

logger = logging.getLogger(__name__)


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)
    return start, end


class MonthlyReportGenerator:
    def __init__(
        self,
        session_factory,
        scs: SCSCalculator,
        ev: EVCalculator,
        reports_dir: str,
        template_dir: str = "apps/copilot/templates",
        css_path: str = "apps/copilot/static/css/monthly_report.css",
        base_url: str = ".",
    ):
        self._sf = session_factory
        self._scs = scs
        self._ev = ev
        self._reports_dir = reports_dir
        self._base_url = base_url
        self._env = Environment(loader=FileSystemLoader(template_dir))
        self._template = self._env.get_template("value/monthly_report.html")
        self._css_path = css_path
        os.makedirs(reports_dir, exist_ok=True)

    async def generate(self, *, user_id: str, year: int, month: int) -> MonthlyReport:
        start, end = _month_range(year, month)
        scs_result = await self._scs.calculate(user_id=user_id, start=start, end=end)
        ev_result = await self._ev.calculate(user_id=user_id, start=start, end=end)

        async with self._sf() as session:
            dist_rows = (
                await session.execute(
                    select(AttributionRecord.octant, func.count())
                    .where(
                        and_(
                            AttributionRecord.user_id == user_id,
                            AttributionRecord.created_at >= start,
                            AttributionRecord.created_at < end,
                        )
                    )
                    .group_by(AttributionRecord.octant)
                )
            ).all()
        distribution: dict[str, int] = {o: 0 for o in "ABCDEFGH"}
        for o, c in dist_rows:
            distribution[o] = int(c)

        summary = {
            "scs": scs_result.__dict__,
            "ev": ev_result.__dict__,
            "octant_distribution": distribution,
            "highlights": self._build_highlights(scs_result, ev_result, distribution),
        }

        pdf_path: Optional[str] = None
        html_content = self._template.render(
            user_id=user_id,
            year=year,
            month=month,
            scs=scs_result.score,
            ev=ev_result.total,
            scs_detail=scs_result.__dict__,
            ev_detail=ev_result.__dict__,
            distribution=distribution,
            highlights=summary["highlights"],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            from weasyprint import CSS, HTML  # type: ignore[import-not-found]

            pdf_path = os.path.join(self._reports_dir, f"{user_id}_{year:04d}-{month:02d}.pdf")
            sheets = [CSS(filename=self._css_path)] if os.path.exists(self._css_path) else []
            HTML(string=html_content, base_url=self._base_url).write_pdf(pdf_path, stylesheets=sheets)
            logger.info("monthly report pdf generated: %s", pdf_path)
        except Exception as e:
            logger.warning("WeasyPrint 不可用，跳过 PDF（HTML-only 降级）: %s", e)
            html_path = os.path.join(self._reports_dir, f"{user_id}_{year:04d}-{month:02d}.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            pdf_path = html_path

        async with self._sf() as session:
            stmt = sqlite_insert(MonthlyReport).values(
                user_id=user_id,
                year=year,
                month=month,
                scs=scs_result.score,
                ev=ev_result.total,
                octant_distribution=distribution,
                summary=summary,
                pdf_path=pdf_path,
                generated_at=datetime.now(timezone.utc),
            ).on_conflict_do_update(
                index_elements=["user_id", "year", "month"],
                set_={
                    "scs": scs_result.score,
                    "ev": ev_result.total,
                    "octant_distribution": distribution,
                    "summary": summary,
                    "pdf_path": pdf_path,
                    "generated_at": datetime.now(timezone.utc),
                },
            )
            await session.execute(stmt)
            await session.commit()

            row = (
                await session.execute(
                    select(MonthlyReport)
                    .where(MonthlyReport.user_id == user_id)
                    .where(MonthlyReport.year == year)
                    .where(MonthlyReport.month == month)
                )
            ).scalar_one()

        return row

    @staticmethod
    def _build_highlights(scs, ev, dist: dict[str, int]) -> list[str]:
        bullets: list[str] = []
        bullets.append(
            f"系统贡献分（SCS）={scs.score}（基础 50 + 净贡献 {scs.contribution_sum} - 迟滞 {scs.lag_penalty}）"
        )
        bullets.append(
            f"经济价值（EV）= ¥{ev.total}（避险 ¥{ev.hedge_value} + 增益 ¥{ev.gain_value} - 卖飞 ¥{ev.cost_value}）"
        )
        if dist.get("A", 0):
            bullets.append(f"亮点：A 象限 {dist['A']} 次（系统建议买 + 用户买 + 盈利）")
        if dist.get("C", 0):
            bullets.append(f"亮点：C 象限 {dist['C']} 次（系统建议卖 + 用户卖 + 避亏）")
        if dist.get("B", 0):
            bullets.append(f"待改进：B 象限 {dist['B']} 次（推荐失误，复盘选股逻辑）")
        if dist.get("H", 0):
            bullets.append(f"待改进：H 象限 {dist['H']} 次（卖飞误判，复盘卖出协议）")
        return bullets
