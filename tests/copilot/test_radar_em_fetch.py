"""东财直连与采集器 fallback 单测。"""
from __future__ import annotations

from apps.copilot.modules.radar.t0.collectors._em_fetch import match_industry_row
from apps.copilot.modules.radar.t0.collectors.risk import _collect_regulatory, _collect_unlock


def test_match_industry_row_fuzzy():
    rows = [
        {"board_name": "消费电子", "pct_chg": 1.2, "net_inflow": 1e9},
        {"board_name": "航空机场", "pct_chg": -0.5, "net_inflow": -1e8},
    ]
    hit = match_industry_row(rows, "电子制造")
    assert hit is not None
    assert hit["board_name"] == "消费电子"


def test_collect_unlock_from_queue(monkeypatch):
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "解禁时间": "2026-01-01",
                "占总市值比例": 0.02,
                "解禁数量": 1000,
            }
        ]
    )

    def fake_call(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "stock_restricted_release_queue_em":
            return df
        return None

    monkeypatch.setattr(
        "apps.copilot.modules.radar.t0.collectors.risk.ak_call",
        fake_call,
    )
    out = _collect_unlock("601138")
    assert out["status"] == "ok"
    assert out["events"][0]["date"]


def test_collect_regulatory_cninfo(monkeypatch):
    def fake_iter(sym, start, end, **kwargs):
        _ = sym, start, end, kwargs
        yield {"announcementTitle": "关于股票交易异常波动问询函的回复"}

    monkeypatch.setattr(
        "apps.cryo_guard.cninfo_client.iter_cninfo_announcements",
        fake_iter,
    )
    out = _collect_regulatory("601138")
    assert out["status"] == "ok"
    assert "问询" in out["raw_text"]
