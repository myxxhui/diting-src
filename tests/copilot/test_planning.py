"""M6 行情解析与规划工作台 pytest。

[Ref: 03_/00_维度零/.../step_12_行情解析与规划工作台.md]
[Ref: 24_行情解析与规划工作台_需求实现表.md]
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.copilot.main import app
from apps.copilot.modules.planning.schema import CampaignCreate, CampaignNodeCreate

FORBIDDEN = re.compile(
    r"buy|qmt|auto_trade|order_id|webhook_target|立即|一键|下单",
    re.IGNORECASE,
)


@pytest.fixture(autouse=True)
def _planning_fake_redis(monkeypatch):
    """单测不连真 Redis：用 fakeredis，避免 wait_for_sync_redis 阻塞。"""
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        monkeypatch.setattr(
            "apps.copilot.routers.planning_routes.wait_for_sync_redis",
            _fake_wait,
        )
        monkeypatch.setattr(
            "apps.copilot.services.redis_wait.wait_for_sync_redis",
            _fake_wait,
        )
        monkeypatch.setattr(
            "apps.copilot.modules.planning.service.wait_for_sync_redis",
            _fake_wait,
        )
    except ImportError:
        pass


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_nav_workbench_entry(client):
    r = client.get("/")
    assert r.status_code == 200
    for label in ("持仓监护", "工作台", "产业图谱"):
        assert label in r.text
    assert "投资工作台" not in r.text
    assert "工作区入口" not in r.text
    # 决策复盘仅在工作台内五区 Tab，不再占顶栏独立入口
    assert 'href="/planning?view=ledger"' not in r.text
    assert '">决策复盘</span>' not in r.text


def test_planning_page_200(client):
    r = client.get("/planning")
    assert r.status_code == 200
    for label in ("产业风向", "机会雷达", "买入论证", "持仓监护", "决策复盘"):
        assert label in r.text


def test_planning_nav_highlights_workbench_entry(client):
    for view in ("roadmap", "radar", "planning", "executing", "ledger"):
        r = client.get(f"/planning?view={view}")
        assert r.status_code == 200
        assert "工作台" in r.text
        assert 'class="nav-active"' in r.text
        assert r.text.count('href="/planning"') >= 1


def test_planning_default_view_is_roadmap(client):
    r = client.get("/planning")
    assert r.status_code == 200
    assert "产业风向台" in r.text
    # Tab：产业风向须在机会雷达之前出现
    assert r.text.index("产业风向") < r.text.index("机会雷达")


def test_planning_ledger_view(client):
    r = client.get("/planning?view=ledger")
    assert r.status_code == 200
    assert "决策复盘库" in r.text


def test_value_redirects_to_ledger_tab(client):
    r = client.get("/value", follow_redirects=False)
    assert r.status_code == 302
    assert "view=ledger" in (r.headers.get("location") or "")


def test_ledger_redirects_to_planning_tab(client):
    r = client.get("/ledger?symbol=601138", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers.get("location") or ""
    assert "view=ledger" in loc
    assert "symbol=601138" in loc


def test_planning_view_planning_filters(client):
    # 标的级漏斗：planning 视图返回 funnel_stage=planning 的标的
    client.post("/api/campaigns/import-portfolio")
    r = client.get("/api/campaigns?view=planning")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert all(d["funnel_stage"] in ("planning", "roadmap") for d in data)
    assert "symbol" in data[0]


def test_timeline_api(client):
    client.post("/api/campaigns/import-portfolio")
    r = client.get("/api/timeline")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_radar_symbols_api(client):
    # 标的级漏斗：雷达区=扫描候选工作台（未扫描时为空，持仓在规划区不混入）
    client.post("/api/campaigns/import-portfolio")
    r = client.get("/api/radar/symbols")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_graph_with_center(client):
    r = client.get("/graph?center=601138")
    assert r.status_code == 200
    assert "601138" in r.text


def test_portfolio_guard_redirects_to_executing(client):
    r = client.get("/portfolio-guard", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/planning?view=executing"
    r2 = client.get("/portfolio-guard")
    assert r2.status_code == 200
    assert "持仓监护" in r2.text


def test_graph_placeholder(client):
    r = client.get("/graph")
    assert r.status_code == 200
    assert "产业" in r.text


def test_settings_page_links(client):
    r = client.get("/settings", follow_redirects=False)
    assert r.status_code == 200
    assert "/holdings" in r.text
    assert "行情雷达" in r.text

    r2 = client.get("/system", follow_redirects=False)
    assert r2.status_code in (302, 307)
    assert "/settings" in (r2.headers.get("location") or "")


def test_audit_and_opus_pages(client):
    r = client.get("/audit")
    assert r.status_code == 200
    assert "查询版本" in r.text
    r2 = client.get("/opus")
    assert r2.status_code == 200
    assert "Opus" in r2.text
    r3 = client.get("/planning?view=audit&symbol=002837", follow_redirects=False)
    assert r3.status_code in (302, 307)
    assert "/audit" in (r3.headers.get("location") or "")


def test_create_campaign_api(client):
    r = client.post("/api/campaigns", json={"theme": "测试主题", "status": "planning"})
    assert r.status_code == 201
    assert r.json()["theme"] == "测试主题"


def test_import_portfolio_campaign(client):
    r = client.post("/api/campaigns/import-portfolio")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] >= 1
    assert body["total_symbols"] >= 1


def test_list_campaigns_has_symbols(client):
    client.post("/api/campaigns/import-portfolio")
    r = client.get("/api/campaigns")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert len(data[0]["symbols"]) >= 1


def test_symbol_dossier_six_blocks(client):
    client.post("/api/campaigns/import-portfolio")
    camps = client.get("/api/campaigns").json()
    cid = camps[0]["id"]
    sym = camps[0]["symbols"][0]["symbol"]
    r = client.get(f"/api/campaigns/{cid}/symbols/{sym}")
    assert r.status_code == 200
    body = r.json()
    for key in ("quote", "phase", "niche", "moat", "risk", "monitors"):
        assert key in body


def test_monitors_three_pillars(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    r = client.get(f"/api/campaigns/{cid}/monitors")
    assert r.status_code == 200
    pillars = {m["pillar"] for m in r.json()}
    assert pillars >= {"moat", "catalyst", "risk"}


def test_nodes_all_advisory(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    nodes = client.get(f"/api/campaigns/{cid}/nodes").json()
    assert nodes
    assert set(n["execute_mode"] for n in nodes) == {"advisory"}


def test_node_schema_rejects_forbidden():
    with pytest.raises(ValueError):
        CampaignNodeCreate(
            name="bad",
            advice_action="auto_" + "trade now",
        )


def test_node_schema_requires_advisory():
    with pytest.raises(ValueError):
        CampaignNodeCreate(name="x", advice_action="观察", execute_mode="live")


def test_campaign_create_schema():
    c = CampaignCreate(theme="AI 算力")
    assert c.status == "planning"


def test_no_auto_execute_in_planning_module():
    root = Path(__file__).resolve().parents[2] / "apps" / "copilot"
    hits = []
    for sub in ("modules/planning", "templates/planning"):
        p = root / sub
        if not p.exists():
            continue
        for f in p.rglob("*"):
            if f.suffix not in (".py", ".html"):
                continue
            text = f.read_text(encoding="utf-8")
            if FORBIDDEN.search(text):
                hits.append(str(f))
    assert hits == [], f"禁止字段命中: {hits}"


def test_dossier_niche_moat_pending_without_monitor_dict(client):
    """无 monitor:dict 时生态位/壁垒为 pending（非 Redis 降级）。"""
    client.post("/api/campaigns/import-portfolio")
    camps = client.get("/api/campaigns").json()
    sym = camps[0]["symbols"][0]["symbol"]
    r = client.get(f"/api/campaigns/{camps[0]['id']}/symbols/{sym}")
    body = r.json()
    assert body["niche"]["status"] == "pending"
    assert body["moat"]["status"] == "pending"


def test_get_campaign_detail(client):
    client.post("/api/campaigns/import-portfolio")
    cid = client.get("/api/campaigns").json()[0]["id"]
    r = client.get(f"/api/campaigns/{cid}")
    assert r.status_code == 200
    assert "symbols" in r.json()


def test_campaign_not_found(client):
    r = client.get("/api/campaigns/99999")
    assert r.status_code == 404
