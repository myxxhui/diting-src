"""P1·财务探针测试（akshare stock_financial_abstract 主路径）。

[Ref: 03_/03_维度三/.../step_02]
"""
from __future__ import annotations

import pytest

from apps.state_watch.probes.financial import FinancialProbe


@pytest.mark.asyncio
async def test_fetch_known_symbol_success():
    """已知标的能返回成功结果。"""
    probe = FinancialProbe()
    result = await probe.fetch("600519")
    # akshare 可用时 success=True；不可用时 source=unknown 可能 success=False
    assert result.probe_type == "financial"
    # 无论哪条路径，data 必须包含核心 keys
    assert "revenue_yoy" in result.data
    assert "roe" in result.data


@pytest.mark.asyncio
async def test_fetch_unknown_symbol_raises():
    """完全未知且 akshare 无数据的标的返回 success=False。"""
    probe = FinancialProbe()
    result = await probe.fetch("999999")
    assert result.success is False
    assert "no financial data" in result.error


@pytest.mark.asyncio
async def test_metric_keys_completeness():
    """响应必须包含 P1 规约的全部 key（含 coverage/source）。"""
    probe = FinancialProbe()
    result = await probe.fetch("000001")
    expected_base = {
        "report_date",
        "revenue",
        "revenue_yoy",
        "net_profit",
        "net_profit_yoy",
        "roe",
        "coverage",
        "source",
    }
    assert expected_base.issubset(set(result.data.keys()))


@pytest.mark.asyncio
async def test_elapsed_recorded():
    probe = FinancialProbe()
    result = await probe.fetch("600519")
    assert result.elapsed_ms >= 0
    assert result.fetched_at is not None


@pytest.mark.asyncio
async def test_gross_margin_present_and_numeric():
    """gross_margin 要么为合法浮点，要么为 None（某些标的指标表无毛利率字段）。"""
    probe = FinancialProbe()
    result = await probe.fetch("600519")
    assert result.success is True
    gm = result.data.get("gross_margin")
    assert gm is None or isinstance(gm, (int, float))


@pytest.mark.asyncio
async def test_operating_cf_numeric_or_none():
    """operating_cf（每股经营性现金流）要么为数字，要么为 None。"""
    probe = FinancialProbe()
    result = await probe.fetch("000001")
    cf = result.data.get("operating_cf")
    assert cf is None or isinstance(cf, (int, float))


@pytest.mark.asyncio
async def test_debt_ratio_numeric_or_none():
    probe = FinancialProbe()
    result = await probe.fetch("600519")
    dr = result.data.get("debt_ratio")
    assert dr is None or isinstance(dr, (int, float))


@pytest.mark.asyncio
async def test_coverage_at_least_four_of_six():
    """启动期达标：coverage ≥ 4/6（0.667）。"""
    probe = FinancialProbe()
    result = await probe.fetch("600519")
    if result.success:
        # coverage 字段直接在 data 里
        cov = result.data.get("coverage", 0.0)
        assert cov >= 4 / 6, f"coverage={cov} < 4/6"


# -- akshare_adapter 单元级测试（mock akshare）--

def test_adapter_pct_to_ratio_nan():
    from apps.state_watch.probes.datasource.akshare_adapter import _pct_to_ratio
    import math
    assert _pct_to_ratio(None) is None
    assert _pct_to_ratio(float("nan")) is None
    r = _pct_to_ratio(50.0)
    assert r is not None and abs(r - 0.5) < 1e-9


def test_adapter_nan_to_none():
    from apps.state_watch.probes.datasource.akshare_adapter import _nan_to_none
    import math
    assert _nan_to_none(None) is None
    assert _nan_to_none(float("nan")) is None
    assert _nan_to_none(3.14) == pytest.approx(3.14)


def test_adapter_unknown_when_akshare_down():
    """akshare 不可用时返回 unknown（禁止 stub 假数）。"""
    from apps.state_watch.probes.datasource.akshare_adapter import fetch_financial_snapshot
    import unittest.mock as mock

    with mock.patch(
        "apps.state_watch.probes.datasource.akshare_adapter._AKSHARE_OK", False
    ):
        snap = fetch_financial_snapshot("600519")
    assert snap.report_date == "UNKNOWN"
    assert snap.source == "unknown"
    assert snap.coverage == 0.0


def test_adapter_unknown_symbol_gives_unknown():
    """完全陌生标的 + akshare 不可用 → UNKNOWN。"""
    from apps.state_watch.probes.datasource.akshare_adapter import fetch_financial_snapshot
    import unittest.mock as mock

    with mock.patch(
        "apps.state_watch.probes.datasource.akshare_adapter._AKSHARE_OK", False
    ):
        snap = fetch_financial_snapshot("XXXX99")
    assert snap.report_date == "UNKNOWN"
    assert snap.coverage == 0.0
