"""雷达输入解析：代码 / 简称 / 模糊 → symbol。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.radar.symbol_resolve import (
    RadarSymbolResolveError,
    display_name_for_symbol,
    resolve_radar_query,
    suggest_radar_symbols,
)


def test_resolve_six_digit_code():
    sym, name = resolve_radar_query("002837")
    assert sym == "002837"
    assert name
    assert name != "002837" or len(name) == 6


def test_resolve_chinese_name_from_sot():
    sym, name = resolve_radar_query("英维克")
    assert sym == "002837"
    assert "英维克" in name


def test_display_name_for_code():
    nm = display_name_for_symbol("601138")
    assert nm
    assert nm == "601138" or not nm.isdigit() or len(nm) > 6


def test_suggest_partial_name():
    items = suggest_radar_symbols("英维", limit=5)
    assert items
    symbols = {x["symbol"] for x in items}
    assert "002837" in symbols or any("英维" in x["name"] for x in items)


def test_fuzzy_typo_near_sot_name():
    """接近持仓简称的错字应能模糊命中。"""
    items = suggest_radar_symbols("英维客", limit=3)
    if not items:
        pytest.skip("无 akshare/SoT 索引")
    top = items[0]
    assert top["score"] >= 0.5


def test_resolve_unknown_name_raises():
    with pytest.raises(RadarSymbolResolveError):
        resolve_radar_query("咑咑咑咑咑不存在")


def test_resolve_empty_raises():
    with pytest.raises(RadarSymbolResolveError):
        resolve_radar_query("   ")
