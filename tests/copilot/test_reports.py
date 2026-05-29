"""日报 / 周报测试。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import HealthRecord, Holding, User, UserDecision
from apps.copilot.scheduler.jobs.report_jobs import register_report_jobs
from apps.copilot.services.alerts.models import AlertLog, AlertType
from apps.copilot.services.reports.daily import DailyReportGenerator
from apps.copilot.services.reports.renderer import ReportRenderer
from apps.copilot.services.reports.weekly import WeeklyReportGenerator


class _StubLedger:
    async def snapshot_scs(self, user_id, d):
        _ = user_id
        today = date.today()
        return 62.5 if d == today else 60.0

    async def compute_avoided_loss(self, user_id, s, e):
        _ = user_id, s, e
        return 1234.56

    async def compute_earned(self, user_id, s, e):
        _ = user_id, s, e
        return 0.0


@pytest.fixture
async def seeded_session() -> AsyncSession:
    await init_db()
    today = date.today()
    yesterday = today - timedelta(days=1)
    async with AsyncSessionLocal() as session:
        u = User(user_id="u1", name="u1")
        session.add(u)
        await session.flush()
        session.add(
            Holding(
                user_pk=u.id,
                symbol="600519",
                name="贵州茅台",
                shares=100,
                cost_price=1500,
            )
        )
        session.add(
            HealthRecord(
                symbol="600519",
                name="贵州茅台",
                event_id="h1",
                old_health=85.0,
                new_health=88.0,
                health_delta=3.0,
                push_level=0,
                change_reason="ok",
                occurred_at=datetime.combine(today, time.min, tzinfo=timezone.utc),
            )
        )
        session.add(
            HealthRecord(
                symbol="600519",
                name="贵州茅台",
                event_id="h2",
                old_health=80.0,
                new_health=85.0,
                health_delta=5.0,
                push_level=1,
                change_reason="ok",
                occurred_at=datetime.combine(yesterday, time.min, tzinfo=timezone.utc),
            )
        )
        now = datetime.now(timezone.utc)
        session.add(
            AlertLog(
                alert_id="a1",
                user_id="u1",
                level="red",
                alert_type=AlertType.STOP_LOSS.value,
                symbol="600519",
                name="测试",
                message="测试红色",
                payload={},
                dedup_key="u1:600519:sell_signal:stop_loss",
                created_at=now,
            )
        )
        session.add(
            AlertLog(
                alert_id="a2",
                user_id="u1",
                level="orange",
                alert_type=AlertType.DEGRADE.value,
                symbol="000001",
                name="other",
                message="测试橙色",
                payload={},
                dedup_key="u1:000001:degrade",
                created_at=now,
            )
        )
        session.add(
            UserDecision(
                user_pk=u.id,
                thesis_id="t1",
                action="join",
                decided_at=datetime.combine(today, time.min, tzinfo=timezone.utc),
            )
        )
        await session.commit()
        yield session


@pytest.mark.asyncio
async def test_daily_aggregates(seeded_session: AsyncSession):
    gen = DailyReportGenerator(seeded_session, _StubLedger())
    ctx = await gen.aggregate("u1", date.today())
    assert ctx.payload["alerts"]["red"] == 1
    assert ctx.payload["alerts"]["orange"] == 1
    assert ctx.payload["exec_rate"]["join"] == 1
    assert ctx.payload["exec_rate"]["rate"] == 1.0
    assert ctx.payload["scs_delta"]["delta"] == pytest.approx(2.5)


@pytest.mark.asyncio
async def test_weekly_aggregates(seeded_session: AsyncSession):
    gen = WeeklyReportGenerator(seeded_session, _StubLedger())
    ctx = await gen.aggregate("u1", date.today())
    assert ctx.payload["alerts"]["total"] == 2
    assert ctx.payload["avoided_loss"] == pytest.approx(1234.56)
    assert ctx.payload["iso_year"] == date.today().isocalendar()[0]


@pytest.mark.asyncio
async def test_renderer_html_contains_label(seeded_session: AsyncSession):
    gen = DailyReportGenerator(seeded_session, _StubLedger())
    ctx = await gen.aggregate("u1", date.today())
    html = ReportRenderer().render("daily", "html", ctx)
    assert ctx.period_label in html
    assert "红色" in html
    assert "持仓体检日报" in html


@pytest.mark.asyncio
async def test_renderer_markdown_contains_pct(seeded_session: AsyncSession):
    gen = DailyReportGenerator(seeded_session, _StubLedger())
    ctx = await gen.aggregate("u1", date.today())
    md = ReportRenderer().render("daily", "md", ctx)
    assert "推荐执行率" in md
    assert "100%" in md


def test_scheduler_registers_report_jobs():
    scheduler = AsyncIOScheduler()
    mock_ad = MagicMock()
    mock_sf = MagicMock()
    register_report_jobs(
        scheduler, session_factory=mock_sf, alert_dispatcher=mock_ad
    )
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "copilot.daily_report" in job_ids
    assert "copilot.weekly_report" in job_ids
    assert "copilot.monthly_report" in job_ids


def test_weekly_iso_range_alignment():
    monday, sunday, y, w = WeeklyReportGenerator.iso_week_range(date(2026, 5, 13))
    assert monday == date(2026, 5, 11)
    assert sunday == date(2026, 5, 17)
    assert (y, w) == (2026, 20)
