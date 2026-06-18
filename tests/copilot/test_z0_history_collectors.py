"""M1/M5 历史序列与政策全文采集单元测试（无网络）。"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from apps.copilot.metrics.collectors._series_util import df_to_series, metric_ok
from apps.copilot.metrics.collectors.m1_macro import collect_m1_bundle
from apps.copilot.services.deepsea.policy_ingest import _strip_html, fetch_policy_full_text


def test_df_to_series_tail():
    df = pd.DataFrame(
        {"月份": ["2024-01", "2024-02", "2024-03"], "制造业-指数": [49.0, 50.2, 51.1]}
    )
    series = df_to_series(df, period_col="月份", fields={"pmi": "制造业-指数"}, tail=2)
    assert len(series) == 2
    assert series[-1]["pmi"] == 51.1


def test_metric_ok_history_gap():
    snap = metric_ok(
        "M.macro.pmi",
        {"pmi": 50.0},
        "test",
        series=[{"period": "2024-01", "pmi": 50.0}],
        history_required="36个月",
        min_points=24,
    )
    assert snap["series_count"] == 1
    assert "history_gap" in snap


@patch("apps.copilot.metrics.collectors.m1_macro.collect_pmi")
@patch("apps.copilot.metrics.collectors.m1_macro.collect_cpi_ppi_spread")
@patch("apps.copilot.metrics.collectors.m1_macro.collect_gdp_yoy")
@patch("apps.copilot.metrics.collectors.m1_macro.collect_social_financing")
@patch("apps.copilot.metrics.collectors.m1_macro.collect_m2_yoy")
@patch("apps.copilot.metrics.collectors.m1_macro.collect_us10y")
@patch("apps.copilot.metrics.collectors.m1_macro.collect_vix")
def test_m1_bundle_dedup_by_metric_id(
    mock_vix,
    mock_us10y,
    mock_m2,
    mock_sf,
    mock_gdp,
    mock_cpi,
    mock_pmi,
):
    ok = lambda mid: {"status": "ok", "metric_id": mid, "data": {}}
    mock_pmi.return_value = ok("M.macro.pmi")
    mock_cpi.return_value = ok("M.macro.cpi_ppi_spread")
    mock_gdp.return_value = ok("M.macro.gdp_yoy")
    mock_sf.return_value = ok("M.macro.social_financing")
    mock_m2.return_value = ok("M.macro.m2_yoy")
    mock_us10y.return_value = ok("M.macro.us10y")
    mock_vix.return_value = ok("M.macro.vix")

    bundle = collect_m1_bundle()
    assert bundle["status"] == "ok"
    assert len(bundle["parts"]) == 7
    assert "M.macro.pmi" in bundle["parts"]


def test_strip_html_removes_tags():
    html = "<div><p>关于加快<strong>算力</strong>基础设施建设的通知</p></div>"
    text = _strip_html(html)
    assert "算力" in text
    assert "<p>" not in text


@patch("apps.copilot.services.deepsea.policy_ingest.httpx.get")
def test_fetch_policy_full_text_pages_content(mock_get):
    mock_get.return_value.status_code = 200
    body = "<p>国务院关于印发实施就业优先战略十五五规划的通知。</p>" * 20
    mock_get.return_value.text = f'<html><div class="pages_content">{body}</div></html>'
    mock_get.return_value.raise_for_status = lambda: None
    text, err = fetch_policy_full_text("https://www.gov.cn/zhengce/content/202606/content_1.htm")
    assert err is None
    assert "十五五规划" in text
    assert len(text) > 100
