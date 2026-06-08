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


def test_suggest_partial_name(monkeypatch):
    import apps.copilot.modules.radar.symbol_resolve as sr

    monkeypatch.setattr(sr, "market_name_index_ready", lambda: True)
    monkeypatch.setattr(
        sr,
        "_CODE_MAP_CACHE",
        {"002837": "英维克", "300502": "新易盛"},
    )
    monkeypatch.setattr(sr, "_CODE_MAP_PINNED", True)
    items = suggest_radar_symbols("英维", limit=5)
    assert items
    symbols = {x["symbol"] for x in items}
    assert "002837" in symbols or any("英维" in x["name"] for x in items)


def test_fuzzy_typo_near_sot_name(monkeypatch):
    """接近持仓简称的错字应能模糊命中。"""
    import apps.copilot.modules.radar.symbol_resolve as sr

    monkeypatch.setattr(sr, "market_name_index_ready", lambda: True)
    monkeypatch.setattr(sr, "_CODE_MAP_CACHE", {"002837": "英维克"})
    monkeypatch.setattr(sr, "_CODE_MAP_PINNED", True)
    items = suggest_radar_symbols("英维客", limit=3)
    assert items
    top = items[0]
    assert top["score"] >= 0.5


def test_resolve_unknown_name_raises():
    with pytest.raises(RadarSymbolResolveError):
        resolve_radar_query("咑咑咑咑咑不存在")


def test_resolve_empty_raises():
    with pytest.raises(RadarSymbolResolveError):
        resolve_radar_query("   ")


def test_code_name_map_not_pinned_when_only_sot(monkeypatch):
    """首次仅加载到 SoT 时不应永久缓存，避免全市场简称搜不到。"""
    import apps.copilot.modules.radar.symbol_resolve as sr

    sr._CODE_MAP_CACHE = {}
    sr._CODE_MAP_PINNED = False
    sr._a_share_name_index.cache_clear()

    monkeypatch.setattr(sr, "_build_code_name_map", lambda: {"002837": "英维克"})
    m1 = sr._code_name_map()
    assert m1.get("002837") == "英维克"
    assert sr._CODE_MAP_PINNED is False

    monkeypatch.setattr(
        sr,
        "_build_code_name_map",
        lambda: {"002837": "英维克", "300502": "新易盛"},
    )
    m2 = sr._code_name_map(force_refresh=True)
    assert m2.get("300502") == "新易盛"


def test_suggest_exact_name_via_market(monkeypatch):
    import apps.copilot.modules.radar.symbol_resolve as sr

    monkeypatch.setattr(sr, "market_name_index_ready", lambda: True)
    monkeypatch.setattr(sr, "_CODE_MAP_CACHE", {"300502": "新易盛"})
    monkeypatch.setattr(sr, "_CODE_MAP_PINNED", True)
    monkeypatch.setattr(sr, "_code_name_map", lambda **kw: {"300502": "新易盛"})
    monkeypatch.setattr(sr, "_resolve_from_sot", lambda raw: None)
    monkeypatch.setattr(
        sr, "_resolve_from_akshare_name", lambda raw: ("300502", "新易盛") if raw == "新易盛" else None
    )
    items = suggest_radar_symbols("新易盛", limit=3)
    assert items and items[0]["symbol"] == "300502"
