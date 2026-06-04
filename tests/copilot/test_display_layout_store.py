"""display_layout.json 服务端持久化（PVC 目录）。"""
from __future__ import annotations

import json

import pytest

from apps.copilot.modules.radar import display_layout as dl


@pytest.fixture()
def layout_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_T0_CACHE_DIR", str(tmp_path))
    dl._layout_path.cache_clear() if hasattr(dl._layout_path, "cache_clear") else None
    return tmp_path


def test_save_and_load_layout_roundtrip(layout_dir):
    payload = {
        "version": 1,
        "order": ["market_phase", "valuation", "catalyst"],
        "hidden": ["risk"],
        "custom": [],
        "show_summary": True,
    }
    saved = dl.save_saved_layout(payload)
    assert saved["order"][:3] == ["market_phase", "valuation", "catalyst"]
    assert "risk" in saved["hidden"]

    loaded = dl.load_saved_layout()
    assert loaded is not None
    assert list(loaded["order"])[:3] == ["market_phase", "valuation", "catalyst"]
    assert "risk" in loaded.get("hidden", set())

    path = layout_dir / dl.LAYOUT_FILENAME
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["order"][0] == "market_phase"


def test_resolve_layout_falls_back_to_saved(layout_dir):
    dl.save_saved_layout({"order": ["catalyst", "market_phase"], "hidden": []})
    resolved = dl.resolve_layout_for_request(None)
    assert resolved["order"][0] == "catalyst"


def test_reset_saved_layout(layout_dir):
    dl.save_saved_layout({"order": ["catalyst"], "hidden": []})
    dl.reset_saved_layout()
    assert dl.load_saved_layout() is None
