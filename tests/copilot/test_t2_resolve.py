"""T2 回退与 bundle 防污染。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.copilot.modules.radar.t2_resolve import (
    find_ok_t2_verdict,
    merge_bundle_preserve_ok_t2,
    ok_t2_from_bundle,
)


def _ok_t2() -> dict:
    dims = {k: {"verdict": "x", "reasoning": "r", "evidence": [], "confidence": 0.5} for k in [
        "niche", "value_chain", "is_leader", "moat", "profit_quality",
        "market_phase", "catalyst_timeline", "risk", "valuation",
    ]}
    return {
        "status": "ok",
        "deep_analysis": {"overall": {"confidence": 0.7}, "dimensions": dims},
        "model_id": "anthropic:opus",
    }


def test_ok_t2_from_bundle_requires_nine_dims():
    assert ok_t2_from_bundle({"t2_verdict": {"status": "ok", "deep_analysis": {"dimensions": {}}}}) is None
    assert ok_t2_from_bundle({"t2_verdict": _ok_t2()}) is not None


def test_merge_bundle_preserve_ok_t2(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_T0_CACHE_DIR", str(tmp_path))
    sym = "002837"
    good = {
        "symbol": sym,
        "collected_at": "2026-06-01T10:00:00+00:00",
        "t2_verdict": _ok_t2(),
    }
    from apps.copilot.modules.radar.t0_cache import save_cache

    save_cache(good)
    bad = {
        "symbol": sym,
        "collected_at": "2026-06-03T11:00:00+00:00",
        "t2_verdict": {"status": "error", "detail": "403"},
    }
    merged = merge_bundle_preserve_ok_t2(bad)
    assert merged["t2_verdict"]["status"] == "ok"
    assert find_ok_t2_verdict(sym) is not None
