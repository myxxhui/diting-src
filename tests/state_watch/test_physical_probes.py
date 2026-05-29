"""物理探针 P5/P6/P7 单测.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03 §3.5.4]
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from apps.state_watch.probes.physical.p5_tender import (
    TenderProbe,
    _compute_signal,
    _parse_amount_yuan,
)
from apps.state_watch.probes.physical.p6_customs import (
    CustomsProbe,
    _signal_from_yoy,
)
from apps.state_watch.probes.physical.p7_capacity import (
    CapacityProbe,
    _compute_signal as p7_signal,
    _extract_utilization,
    _has_large_capex,
)


# ─── P5 TenderProbe ────────────────────────────────────────────────────────────

class TestP5TenderUnits:
    def test_parse_amount_yi(self):
        assert _parse_amount_yuan("合同金额1.5亿元") == pytest.approx(1.5e8)

    def test_parse_amount_wan(self):
        assert _parse_amount_yuan("中标金额50万元") == pytest.approx(5e5)

    def test_parse_amount_none(self):
        assert _parse_amount_yuan("无金额信息") is None

    @pytest.mark.parametrize(
        "hit,mom,expected",
        [
            (0, None, "red"),
            (1, None, "yellow"),
            (3, 10.0, "green"),
            (3, -5.0, "yellow"),
            (5, 0.0, "green"),
        ],
    )
    def test_signal_cases(self, hit, mom, expected):
        assert _compute_signal(hit, mom) == expected


class TestP5TenderProbe:
    def test_upstream_pending_when_no_data(self):
        """无公告时应返回 upstream_pending，不抛异常。"""
        with patch("apps.state_watch.probes.physical.p5_tender.session_scope") as mock_scope:
            mock_sess = MagicMock()
            mock_sess.scalars.return_value.all.return_value = []
            mock_scope.return_value.__enter__ = lambda _: mock_sess
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)
            probe = TenderProbe()
            result = asyncio.run(probe.fetch("000001"))
        assert result.success is True
        assert result.data["status"] == "upstream_pending"

    def test_hit_count_and_signal(self):
        """有 3 条招标公告 → hit=3 → 应产出 signal 字段。"""
        today = date.today()
        mock_ann = MagicMock()
        mock_ann.ann_type = "ccgp"
        mock_ann.title = "中标公告5万元"
        mock_ann.ann_date = today - timedelta(days=5)
        mock_ann.url = "https://www.ccgp.gov.cn/xxx"

        with patch("apps.state_watch.probes.physical.p5_tender.session_scope") as mock_scope:
            mock_sess = MagicMock()

            def scalars_side_effect(stmt):
                r = MagicMock()
                r.all.return_value = [mock_ann, mock_ann, mock_ann]
                return r

            mock_sess.scalars.side_effect = scalars_side_effect
            mock_scope.return_value.__enter__ = lambda _: mock_sess
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)
            probe = TenderProbe()
            result = asyncio.run(probe.fetch("000001"))
        assert result.success is True
        assert result.data["status"] == "ok"
        assert result.data["tender_hit_count_30d"] == 3
        assert "physical_signal" in result.data


# ─── P6 CustomsProbe ────────────────────────────────────────────────────────────

class TestP6CustomsUnits:
    @pytest.mark.parametrize(
        "exports,imports,expected",
        [
            (8.0, 3.0, "green"),
            (-7.0, -2.0, "red"),
            (2.0, 1.0, "yellow"),
            (None, None, "unknown"),
            (None, 10.0, "green"),
        ],
    )
    def test_signal_from_yoy(self, exports, imports, expected):
        assert _signal_from_yoy(exports, imports) == expected


class TestP6CustomsProbe:
    def test_data_unavailable_on_double_source_fail(self):
        """双源都失败时应返回 data_unavailable。"""
        with (
            patch("apps.state_watch.probes.physical.p6_customs._akshare_exports_yoy", return_value=None),
            patch("apps.state_watch.probes.physical.p6_customs._akshare_imports_yoy", return_value=None),
        ):
            probe = CustomsProbe()
            result = asyncio.run(probe.fetch("600519"))
        assert result.success is True
        assert result.data["status"] == "data_unavailable"
        assert result.data["physical_signal"] == "unknown"

    def test_ok_with_primary_source(self):
        """主源返回 8.5% → green 信号。"""
        with (
            patch("apps.state_watch.probes.physical.p6_customs._akshare_exports_yoy", return_value=8.5),
            patch("apps.state_watch.probes.physical.p6_customs._akshare_imports_yoy", return_value=None),
        ):
            probe = CustomsProbe()
            result = asyncio.run(probe.fetch("600519"))
        assert result.success is True
        assert result.data["status"] == "ok"
        assert result.data["physical_signal"] == "green"
        assert result.data["customs_export_yoy_pct"] == pytest.approx(8.5)


# ─── P7 CapacityProbe ────────────────────────────────────────────────────────────

class TestP7CapacityUnits:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("产能利用率达85.3%，超出行业平均", 85.3),
            ("开工率为92%，处于高位", 92.0),
            ("公司当前设备利用率约65%", 65.0),
            ("公司业绩良好，营收增长", None),
            # 扩充模式
            ("满产率维持在94%左右", 94.0),
            ("产能开工率约88%", 88.0),
            ("产线开工率为76%，同比提升", 76.0),
            # 反向措辞
            ("目前达到95%满产状态", 95.0),
            ("约80%的产能利用，整体平稳", 80.0),
        ],
    )
    def test_extract_utilization(self, text, expected):
        result = _extract_utilization(text)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected, abs=0.1)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("新增产能60%，大规模扩张", True),
            ("扩建产能20%，适度扩张", False),
            ("无扩产计划", False),
        ],
    )
    def test_has_large_capex(self, text, expected):
        assert _has_large_capex(text) == expected

    @pytest.mark.parametrize(
        "util,capex,expected",
        [
            (95.0, False, "green"),
            (80.0, False, "yellow"),
            (65.0, False, "red"),
            (91.0, True, "red"),
            (None, False, "unknown"),
        ],
    )
    def test_p7_signal(self, util, capex, expected):
        assert p7_signal(util, capex) == expected


class TestP7CapacityProbe:
    def test_extraction_failed_on_no_match(self):
        """无产能利用率关键词时应返回 extraction_failed。"""
        mock_ann = MagicMock()
        mock_ann.ann_type = "announcement"
        mock_ann.title = "公司发布年度报告"
        mock_ann.content = "营收同比增长10%。"
        mock_ann.ann_date = date.today() - timedelta(days=30)

        with patch("apps.state_watch.probes.physical.p7_capacity.session_scope") as mock_scope:
            mock_sess = MagicMock()
            mock_sess.scalars.return_value.all.return_value = [mock_ann]
            mock_scope.return_value.__enter__ = lambda _: mock_sess
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)
            probe = CapacityProbe()
            result = asyncio.run(probe.fetch("600519"))
        assert result.success is True
        assert result.data["status"] == "extraction_failed"

    def test_ok_with_match(self):
        """公告含产能利用率 92% → green 信号。"""
        mock_ann = MagicMock()
        mock_ann.ann_type = "performance"
        mock_ann.title = "公司产能利用率92%"
        mock_ann.content = "本报告期产能利用率达到92%，处于满产状态。"
        mock_ann.ann_date = date.today() - timedelta(days=30)

        with patch("apps.state_watch.probes.physical.p7_capacity.session_scope") as mock_scope:
            mock_sess = MagicMock()
            mock_sess.scalars.return_value.all.return_value = [mock_ann]
            mock_scope.return_value.__enter__ = lambda _: mock_sess
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)
            probe = CapacityProbe()
            result = asyncio.run(probe.fetch("600519"))
        assert result.success is True
        assert result.data["status"] == "ok"
        assert result.data["physical_signal"] == "green"
        assert result.data["capacity_utilization_pct"] == pytest.approx(92.0)
