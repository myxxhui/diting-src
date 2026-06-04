"""雷达 T0 缓存读写 + scanner 缓存优先。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.copilot.modules.radar import t0_cache
from apps.copilot.modules.radar.scanner import collect_t0_raw


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_T0_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_T0_CACHE_MAX_AGE_HOURS", "24")
    return tmp_path


SAMPLE_T0 = {
    "symbol": "601138",
    "name": "工业富联",
    "collected_at": datetime.now(timezone.utc).isoformat(),
    "source": "prefetch",
    "quote": {"status": "ok", "last_close": 20.0},
    "profile": {"status": "ok", "name": "工业富联", "industry": "电子"},
    "financials": {"status": "ok", "revenue": 100.0},
    "valuation": {"status": "ok", "pe_ttm": 22.0},
}

NINE_DIMS = {f"d{i}": {"summary": f"s{i}"} for i in range(1, 10)}


def test_cached_t2_verdict_ok(cache_root):
    bundle = {
        **SAMPLE_T0,
        "t2_verdict": {
            "status": "ok",
            "model_id": "anthropic:opus",
            "deep_analysis": {"dimensions": NINE_DIMS},
            "cost_yuan": 0.12,
        },
    }
    t0_cache.save_cache(bundle)
    loaded = t0_cache.load_cached("601138")
    t2 = t0_cache.cached_t2_verdict(loaded)
    assert t2 is not None
    assert t2["cache_hit"] is True
    assert t2["route"] == "cache"
    assert len(t2["deep_analysis"]["dimensions"]) == 9


def test_cached_t2_verdict_rejects_incomplete(cache_root):
    bundle = {
        **SAMPLE_T0,
        "t2_verdict": {
            "status": "ok",
            "deep_analysis": {"dimensions": {"d1": {}}},
        },
    }
    assert t0_cache.cached_t2_verdict(bundle) is None


@pytest.mark.asyncio
async def test_collect_t0_raw_miss_tries_live(cache_root, monkeypatch):
    called = {"live": False}

    async def _live(*_a, **_k):
        called["live"] = True
        return {**SAMPLE_T0, "cache_hit": False, "source": "live:test"}

    monkeypatch.setattr("apps.copilot.modules.radar.scanner.collect_t0_live", _live)
    out = await collect_t0_raw("601138")
    assert called["live"] is True
    assert out.get("cache_hit") is False


@pytest.mark.asyncio
async def test_pipeline_enable_t2_skipped(cache_root, monkeypatch):
    from apps.copilot.modules.radar.pipeline import run_radar_pipeline

    t0_cache.save_cache(SAMPLE_T0)

    async def _fail_t2(*_a, **_k):
        raise AssertionError("不应 live Opus")

    monkeypatch.setattr("apps.copilot.modules.radar.pipeline.run_t2_live", _fail_t2)

    class _Sess:
        _n = 0

        def add(self, obj):
            type(self)._n += 1
            if hasattr(obj, "id"):
                obj.id = type(self)._n

        async def flush(self):
            pass

    _Sess._n = 0
    result = await run_radar_pipeline(_Sess(), symbol="601138", enable_t2=False)
    assert result["t2_verdict"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_pipeline_t2_cache_hit(cache_root, monkeypatch):
    from apps.copilot.modules.radar.pipeline import run_radar_pipeline

    bundle = {
        **SAMPLE_T0,
        "t1_distilled": {"matrix": {"quote": {"last_close": 20.0}}, "unavailable": []},
        "t2_verdict": {
            "status": "ok",
            "model_id": "anthropic:opus",
            "route": "remote",
            "deep_analysis": {"dimensions": NINE_DIMS, "overall": {"confidence": 0.8}},
            "confidence": 0.8,
            "cost_yuan": 0.15,
            "token_cost": 0.15,
        },
    }
    t0_cache.save_cache(bundle)

    async def _fail_t2(*_a, **_k):
        raise AssertionError("不应 live Opus")

    monkeypatch.setattr("apps.copilot.modules.radar.pipeline.run_t2_live", _fail_t2)

    class _Sess:
        _n = 0

        def add(self, obj):
            type(self)._n += 1
            if hasattr(obj, "id"):
                obj.id = type(self)._n

        async def flush(self):
            pass

    _Sess._n = 0

    result = await run_radar_pipeline(_Sess(), symbol="601138", name="工业富联")
    assert result["t2_verdict"]["cache_hit"] is True
    assert result["t0_raw"].get("cache_hit") is True


def test_save_and_load_fresh(cache_root):
    t0_cache.save_cache(SAMPLE_T0)
    loaded = t0_cache.load_cached("601138")
    assert loaded is not None
    assert loaded["name"] == "工业富联"
    assert t0_cache.is_fresh(loaded)


def test_expired_cache_not_returned(cache_root):
    old = {
        **SAMPLE_T0,
        "collected_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
    }
    t0_cache.save_cache(old)
    assert t0_cache.load_cached("601138") is None


@pytest.mark.asyncio
async def test_collect_t0_raw_cache_hit(cache_root, monkeypatch):
    t0_cache.save_cache(SAMPLE_T0)

    async def _fail_live(*_a, **_k):
        raise AssertionError("不应 live 采集")

    monkeypatch.setattr("apps.copilot.modules.radar.scanner.collect_t0_live", _fail_live)
    out = await collect_t0_raw("601138")
    assert out.get("cache_hit") is True
    assert out["quote"]["last_close"] == 20.0


def test_status_summary(cache_root):
    t0_cache.save_cache(SAMPLE_T0)
    t0_cache.write_manifest([{"symbol": "601138", "ok_parts": 4}])
    s = t0_cache.status_summary()
    assert s["symbol_count"] == 1
    assert s["symbols"][0]["fresh"] is True
    assert s["symbols"][0]["version_count"] >= 1


def test_list_versions_multiple_saves(cache_root):
    vid1 = t0_cache.save_cache({**SAMPLE_T0, "source": "v1"})
    vid2 = t0_cache.save_cache({**SAMPLE_T0, "source": "v2"})
    versions = t0_cache.list_versions("601138")
    ids = {v["version_id"] for v in versions}
    assert vid1 in ids
    assert vid2 in ids
    assert versions[0]["is_latest"] or versions[0]["version_id"] == vid2


@pytest.mark.asyncio
async def test_collect_t0_raw_force_refresh_skips_cache(cache_root, monkeypatch):
    t0_cache.save_cache(SAMPLE_T0)
    called = {"live": False}

    async def _live(*_a, **_k):
        called["live"] = True
        return {**SAMPLE_T0, "cache_hit": False, "source": "live:force"}

    monkeypatch.setattr("apps.copilot.modules.radar.scanner.collect_t0_live", _live)
    out = await collect_t0_raw("601138", force_refresh=True)
    assert called["live"] is True
    assert out.get("cache_hit") is False


def test_collect_profile_cninfo_fallback(monkeypatch):
    from apps.copilot.modules.radar import scanner

    def _fail_em(_sym):
        raise ValueError("em down")

    monkeypatch.setattr(scanner, "_collect_profile_em", _fail_em)
    monkeypatch.setattr(
        scanner,
        "_collect_profile_cninfo",
        lambda sym: {
            "status": "ok",
            "source": "test:cninfo",
            "name": "工业富联",
            "industry": "电子设备",
            "total_mv_yi": 15000.0,
            "float_mv_yi": 15000.0,
            "listing_date": "20180608",
        },
    )
    out = scanner._collect_profile("601138")
    assert out["status"] == "ok"
    assert out["industry"] == "电子设备"


def test_collect_valuation_em_fallback(monkeypatch):
    from apps.copilot.modules.radar import scanner

    def _fail_lg(_sym):
        raise ValueError("lg down")

    monkeypatch.setattr(scanner, "_collect_valuation_lg", _fail_lg)
    monkeypatch.setattr(
        scanner,
        "_collect_valuation_em",
        lambda sym: {
            "status": "ok",
            "source": "test:value_em",
            "pe_ttm": 39.0,
            "pe_percentile": 55.0,
            "pb": 9.0,
            "history_points": 100,
            "as_of": "2026-06-02",
        },
    )
    out = scanner._collect_valuation("601138")
    assert out["status"] == "ok"
    assert out["pe_percentile"] == 55.0


def test_utc_naive_for_db_from_aware_iso():
    from apps.copilot.modules.radar.persistence import utc_naive_for_db

    bundle = {
        **SAMPLE_T0,
        "collected_at": "2026-06-04T03:02:29+00:00",
    }
    dt = utc_naive_for_db(t0_cache._parse_collected_at(bundle))
    assert dt is not None
    assert dt.tzinfo is None
    assert dt.year == 2026 and dt.hour == 3
