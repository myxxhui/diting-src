"""P4·事件探针测试.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from apps.state_watch.probes.datasource.announcement_adapter import CorporateEvent
from apps.state_watch.probes.event import EventProbe, aggregate_events


class TestAggregate:
    def test_no_events_returns_zero(self):
        out = aggregate_events([])
        assert out["major_reduce_30d"] == 0
        assert out["pledge_ratio"] == 0
        assert out["exec_change_count_90d"] == 0
        assert out["litigation_count_180d"] == 0
        assert out["penalty_count_180d"] == 0
        assert out["events_recent"] == []

    def test_reduce_within_30d(self):
        evs = [CorporateEvent("reduce", datetime.utcnow() - timedelta(days=5), "...", "medium", 0.012)]
        out = aggregate_events(evs)
        assert out["major_reduce_30d"] == pytest.approx(0.012, abs=1e-6)

    def test_reduce_outside_30d_excluded(self):
        evs = [CorporateEvent("reduce", datetime.utcnow() - timedelta(days=60), "...", "medium", 0.05)]
        out = aggregate_events(evs)
        assert out["major_reduce_30d"] == 0

    def test_max_severity(self):
        evs = [
            CorporateEvent("penalty", datetime.utcnow() - timedelta(days=30), "...", "high", 0),
            CorporateEvent("pledge", datetime.utcnow() - timedelta(days=10), "...", "low", 0.05),
        ]
        out = aggregate_events(evs)
        assert out["max_severity_90d"] == pytest.approx(1.0, abs=1e-6)

    def test_pledge_ratio_max(self):
        evs = [
            CorporateEvent("pledge", datetime.utcnow() - timedelta(days=10), "...", "low", 0.05),
            CorporateEvent("pledge", datetime.utcnow() - timedelta(days=20), "...", "low", 0.30),
        ]
        out = aggregate_events(evs)
        assert out["pledge_ratio"] == pytest.approx(0.30, abs=1e-6)


class TestProbeIntegration:
    async def test_sot_symbol_from_cryo_db(self):
        """读 cryo DB 公告；SoT 标的 601138 在 step_02 已采集。"""
        probe = EventProbe()
        result = await probe.fetch("601138")
        assert result.success is True
        assert "penalty_count_180d" in result.data
        assert "exec_change_count_90d" in result.data

    async def test_unknown_no_events(self):
        probe = EventProbe()
        result = await probe.fetch("UNK")
        assert result.success is True
        assert result.data["penalty_count_180d"] == 0
