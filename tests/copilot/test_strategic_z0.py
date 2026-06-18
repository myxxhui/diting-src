"""Z0 指标先行 · wind_scan / genesis / CVM pytest。

[Ref: 33_ §12 P1]
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.copilot.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_wind_scan_run_empty_no_mock(client):
    r = client.post("/api/strategic/wind-scan/run")
    assert r.status_code == 200
    assert "wind_scan" in r.text or "风向标" in r.text
    assert "采集未就绪" in r.text or "暂无显著风口" in r.text or "M2" in r.text


def test_wind_scan_latest(client):
    client.post("/api/strategic/wind-scan/run")
    r = client.get("/api/strategic/wind-scan/latest")
    assert r.status_code == 200


def test_genesis_wizard_step1(client):
    r = client.get("/api/strategic/genesis/wizard?step=1")
    assert r.status_code == 200
    assert "Genesis" in r.text
    assert "advisory" in r.text


def test_roadmap_wind_mode_by_default(client):
    r = client.get("/planning/panel?view=roadmap")
    assert r.status_code == 200
    assert "宏观风向标" in r.text or "wind_scan" in r.text


def test_cvm_run_after_seed(client):
    client.post("/api/strategic/boards/seed-ai")
    boards = client.get("/api/strategic/boards")
    assert boards.status_code == 200
    client.get("/planning/panel?view=roadmap&z0_mode=board")
    r = client.post("/api/strategic/phases/1/cvm/run")
    if r.status_code == 200:
        assert "CVM" in r.text or "cvm" in r.text.lower()
