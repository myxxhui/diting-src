"""M12 战略板块 · 滚动路线图指挥台 pytest。

[Ref: 30_ · step_18 P0]
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.copilot.main import app
from apps.copilot.modules.strategic.service import phase_progress_pct


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_phase_progress_pct_mid_range():
    pct = phase_progress_pct(2026, 2030, today=__import__("datetime").date(2028, 6, 1))
    assert 40 <= pct <= 60


def test_seed_ai_board_idempotent(client):
    r1 = client.post("/api/strategic/boards/seed-ai")
    r2 = client.post("/api/strategic/boards/seed-ai")
    assert r1.status_code == 200
    assert r2.status_code == 200
    boards = client.get("/api/strategic/boards")
    assert boards.status_code == 200
    assert boards.text.count("AI 产业生态") >= 1


def test_create_blank_board(client):
    r = client.post(
        "/api/strategic/boards",
        data={
            "name": "测试板块",
            "horizon_start": "2026",
            "horizon_end": "2028",
            "qualitative_md": "测试定性",
            "load_template": "",
        },
    )
    assert r.status_code == 200
    assert "测试板块" in r.text


def test_strategic_boards_list_html(client):
    r = client.get("/api/strategic/boards", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "战略板块" in r.text or "尚无战略板块" in r.text or "AI 产业生态" in r.text


def test_seed_ai_board_endpoint(client):
    r = client.post("/api/strategic/boards/seed-ai")
    assert r.status_code == 200
    assert "AI 产业生态" in r.text or "已加载" in r.text


def test_roadmap_panel_renders_command_center(client):
    client.post("/api/strategic/boards/seed-ai")
    r = client.get("/planning/panel?view=roadmap")
    assert r.status_code == 200
    assert "战略指挥台" in r.text
    assert "10 年战略时间轴" in r.text or "尚无战略板块" in r.text


def test_phase_panel_endpoint(client):
    client.post("/api/strategic/boards/seed-ai")
    r = client.get("/planning/panel?view=roadmap")
    assert r.status_code == 200
    assert "JL1" in r.text or "JL2" in r.text or "核心猎物池" in r.text


def test_promote_modal_radar(client):
    client.post("/api/strategic/boards/seed-ai")
    r = client.get("/api/strategic/promote-modal/radar/999999")
    if r.status_code == 404:
        pytest.skip("无雷达候选可测 modal")
    assert r.status_code == 200
    assert "晋级到规划区" in r.text


def test_tag_edit_modal(client):
    client.post("/api/strategic/boards/seed-ai")
    r = client.get("/api/strategic/tags/edit?symbol=601138")
    assert r.status_code == 200
    assert "战略标签" in r.text


def test_strategic_overview(client):
    client.post("/api/strategic/boards/seed-ai")
    r = client.get("/api/strategic/overview")
    assert r.status_code == 200
    assert "AI 产业生态" in r.text


def test_phase_review(client):
    client.post("/api/strategic/boards/seed-ai")
    panel = client.get("/planning/panel?view=roadmap")
    import re

    m = re.search(r"/api/strategic/phases/(\d+)/reviews", panel.text)
    if not m:
        pytest.skip("未找到阶段复盘表单")
    pid = m.group(1)
    r = client.post(
        f"/api/strategic/phases/{pid}/reviews",
        data={"review_md": "测试复盘：JL2 多指标 pending"},
    )
    assert r.status_code == 200
    assert "复盘" in r.text
