"""ProbeScheduler 测试(用 _is_trading_hours 模拟 + 单 tick 直接调).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_04_探针调度器与SLI聚合.md]
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from apps.state_watch.probes.scheduler import ProbeScheduler, _is_trading_hours


class TestTradingHours:
    def test_weekend_false(self):
        sat = datetime(2026, 5, 16, 3, 0)
        assert _is_trading_hours(sat) is False

    def test_weekday_morning_true(self):
        d = datetime(2026, 5, 18, 2, 0)
        assert _is_trading_hours(d) is True

    def test_weekday_lunch_false(self):
        d = datetime(2026, 5, 18, 4, 0)
        assert _is_trading_hours(d) is False

    def test_weekday_afternoon_true(self):
        d = datetime(2026, 5, 18, 6, 0)
        assert _is_trading_hours(d) is True


class TestSchedulerRegister:
    def test_register_jobs_creates_4(self):
        sched = ProbeScheduler(redis_client=MagicMock())
        sched.register_jobs()
        ids = {j.id for j in sched.scheduler.get_jobs()}
        assert ids == {
            "probe-price-30m",
            "probe-news-1h",
            "probe-event-6h",
            "probe-financial-daily",
        }
