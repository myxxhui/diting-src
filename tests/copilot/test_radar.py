"""模式 C 深度研报 · 三段流水线 pytest（akshare 直采 + Opus 9 维 + 成本 + no-mock）。

[Ref: step_14 · 24_ §9 · 25_ §2]
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.copilot.main import app
from apps.copilot.modules.radar.context_matrix import build_context_matrix
from apps.copilot.modules.radar.schema import (
    DIM_KEYS,
    estimate_cost_yuan,
    parse_opus_verdict,
)

FORBIDDEN = re.compile(
    r"\b(auto_trade|auto_execute|order_id|webhook_target)\b|立即执行|一键下单",
    re.IGNORECASE,
)

MOCK_T0 = {
    "symbol": "601138",
    "name": "工业富联",
    "collected_at": "2026-05-30T00:00:00",
    "source": "akshare",
    "quote": {
        "status": "ok", "last_close": 20.5, "pct_chg_1d": 1.2, "pct_chg_5d": 3.0,
        "pct_chg_20d": 8.0, "pct_chg_60d": 15.0, "volume_ratio_5d": 1.1,
        "bars": 60, "as_of": "2026-05-30",
    },
    "profile": {
        "status": "ok", "name": "工业富联", "industry": "电子制造",
        "total_mv_yi": 4000.0, "float_mv_yi": 3000.0, "listing_date": "20180608",
    },
    "financials": {
        "status": "ok", "report_period": "20240930", "revenue": 4500.0,
        "net_profit_parent": 150.0, "gross_margin": 7.5, "roe": 12.0, "debt_ratio": 55.0,
    },
    "valuation": {
        "status": "ok", "pe_ttm": 22.0, "pe_percentile": 45.0, "pb": 3.0,
        "history_points": 2000, "as_of": "2026-05-30",
    },
}

OPUS_VERDICT = {
    "overall": {
        "conclusion": "AI 服务器 ODM 龙头，业绩兑现初期",
        "action_advisory": "可纳入观察池深度研究",
        "confidence": 0.75,
    },
    "dimensions": {
        "niche": {"verdict": "AI服务器ODM核心供应商", "reasoning": "代工份额领先", "evidence": ["营收 4500 亿"], "confidence": 0.8},
        "value_chain": {"verdict": "中游", "reasoning": "处于制造组装环节", "evidence": [], "confidence": 0.7},
        "is_leader": {"verdict": "yes", "reasoning": "细分龙头", "evidence": [], "confidence": 0.82},
        "moat": {"verdict": "中", "reasoning": "规模+客户绑定", "evidence": [], "confidence": 0.6},
        "profit_quality": {"verdict": "中", "reasoning": "毛利率偏低但现金流稳", "evidence": ["毛利率 7.5%"], "confidence": 0.65},
        "market_phase": {"verdict": "expectation", "reasoning": "炒预期阶段", "evidence": [], "confidence": 0.7},
        "catalyst_timeline": {
            "verdict": "H2 算力放量",
            "items": [{"window": "1-2 季度", "event": "GB200 放量", "probability": "高"}],
            "reasoning": "下半年订单确认", "evidence": [], "confidence": 0.6,
        },
        "risk": {"verdict": "毛利率偏低", "reasoning": "代工议价弱", "evidence": [], "confidence": 0.7},
        "valuation": {"verdict": "合理", "davis_double": "双击可能", "pe_percentile": 45, "reasoning": "PE 历史中位", "evidence": [], "confidence": 0.6},
    },
}


class _FakeAIResponse:
    def __init__(self, text, model="claude-opus-4-6", route="remote"):
        self.text = text
        self.model = model
        self.scene = "radar_assess"
        self.route = route
        self.latency_ms = 10
        self.tokens_in = 1200
        self.tokens_out = 800
        self.cost_yuan_est = 0.5
        self.raw = {}


class _FakeDispatcher:
    def __init__(self, text, model="claude-opus-4-6"):
        self._text = text
        self._model = model

    def call(self, scene, messages, **kwargs):
        return _FakeAIResponse(self._text, model=self._model)


@pytest.fixture(autouse=True)
def _planning_fake_redis(monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        for mod in (
            "apps.copilot.routers.planning_routes",
            "apps.copilot.services.redis_wait",
            "apps.copilot.modules.planning.service",
        ):
            monkeypatch.setattr(f"{mod}.wait_for_sync_redis", _fake_wait)
    except ImportError:
        pass


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _patch_pipeline(monkeypatch, *, opus_text: str, opus_model: str = "claude-opus-4-6"):
    """mock akshare T0 + 开启 T2 + mock Opus dispatcher（跑真实 pipeline）。"""
    async def _fake_collect(symbol, **_k):
        return {**MOCK_T0, "symbol": symbol.zfill(6)[-6:]}

    monkeypatch.setattr("apps.copilot.modules.radar.scanner.collect_t0_raw", _fake_collect)
    monkeypatch.setattr("apps.copilot.modules.radar.pipeline.collect_t0_raw", _fake_collect)
    monkeypatch.setattr("apps.copilot.modules.radar.pipeline.load_cached", lambda *_a, **_k: None)
    monkeypatch.setattr("apps.copilot.modules.radar.pipeline.radar_t2_enabled", lambda: True)

    fake = _FakeDispatcher(opus_text, model=opus_model)
    import apps.common.ai_dispatcher as aidisp

    monkeypatch.setattr(aidisp.AIDispatcher, "default", staticmethod(lambda: fake))


@pytest.fixture
def mock_pipeline(monkeypatch):
    _patch_pipeline(monkeypatch, opus_text=json.dumps(OPUS_VERDICT, ensure_ascii=False))


def _poll_scan_done(client, scan_id: int, *, timeout: float = 120.0) -> dict:
    """POST /api/radar/scans 现为异步；轮询直至 done/error。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = client.get(f"/api/radar/scans/{scan_id}").json()
        st = got.get("status")
        if st == "done":
            return got
        if st == "error":
            pytest.fail(f"scan {scan_id} error: {got.get('summary_json')}")
        time.sleep(0.5)
    pytest.fail(f"scan {scan_id} 未在 {timeout}s 内完成")


def _post_scan_and_wait(client, *, enable_t0: bool = True, enable_t1: bool = True, enable_t2: bool = True, **form_data) -> dict:
    if enable_t0:
        form_data.setdefault("enable_t0", "on")
    if enable_t1:
        form_data.setdefault("enable_t1", "on")
    if enable_t2:
        form_data.setdefault("enable_t2", "on")
    created = client.post("/api/radar/scans", data=form_data)
    assert created.status_code == 201
    body = created.json()
    if body.get("status") == "done":
        return body
    return _poll_scan_done(client, int(body["id"]))


# ── 单元：schema / 成本 / T1 ────────────────────────────────────────────────
def test_estimate_cost_positive():
    cost = estimate_cost_yuan(1000, 1000)
    assert cost > 0


def test_parse_opus_verdict_all_dims():
    deep = parse_opus_verdict(json.dumps(OPUS_VERDICT, ensure_ascii=False))
    assert set(deep["dimensions"].keys()) == set(DIM_KEYS)
    assert deep["dimensions"]["valuation"]["davis_double"] == "双击可能"
    assert deep["overall"]["confidence"] == 0.75


def test_parse_opus_verdict_strips_codeblock():
    wrapped = "```json\n" + json.dumps(OPUS_VERDICT, ensure_ascii=False) + "\n```"
    deep = parse_opus_verdict(wrapped)
    assert deep["dimensions"]["is_leader"]["verdict"] == "yes"


def test_context_matrix_real_facts():
    m = build_context_matrix(MOCK_T0)
    assert m["t1_fallback"] == "rule"
    assert "行情" in m["matrix"] and "财务摘要" in m["matrix"]
    assert m["fact_count"] >= 3
    assert m["unavailable"] == []


def test_context_matrix_marks_unavailable():
    t0 = {**MOCK_T0, "valuation": {"status": "error", "detail": "未取到估值序列"}}
    m = build_context_matrix(t0)
    assert any("估值" in u for u in m["unavailable"])
    assert "估值" not in m["matrix"]


# ── 集成：真扫（mock Opus）非 pending + 成本透出 ─────────────────────────────
def test_radar_scan_real_dims_no_pending(client, mock_pipeline):
    data = _post_scan_and_wait(
        client, input_type="symbol", query_text="601138"
    )
    c = data["candidates"][0]
    assert c["symbol"] == "601138"
    assert c["market_phase"] == "expectation"
    assert c["is_leader"] == "yes"
    assert c["t2_status"] == "ok"
    deep = c["deep_analysis"]
    assert set(deep["dimensions"].keys()) == set(DIM_KEYS)
    # 无任何维度落到 pending（恪守 no-mock）
    for d in deep["dimensions"].values():
        assert d["verdict"] != "pending"
    cost = c["cost"]
    assert cost["cost_yuan"] > 0
    assert cost["tokens_in"] > 0


def test_radar_scan_html_human_readable(client, mock_pipeline):
    r = client.post(
        "/api/radar/scans",
        data={"input_type": "symbol", "query_text": "601138"},
        headers={"hx-request": "true"},
    )
    assert r.status_code in (200, 201)
    text = r.text
    assert "生态位" in text and "估值" in text and "利好时间线" in text
    assert "💸" in text  # 成本徽章
    assert "炒预期" in text  # market_phase 中文化
    assert "pending" not in text


def test_radar_summary_cost(client, mock_pipeline):
    created = _post_scan_and_wait(
        client, input_type="symbol", query_text="601138"
    )
    got = client.get(f"/api/radar/scans/{created['id']}").json()
    assert got["summary_json"]["t2_status"] == "ok"
    assert got["summary_json"]["cost"]["cost_yuan"] > 0


# ── 集成：no-mock 硬失败显式 error（不伪造）────────────────────────────────
def test_radar_t2_mock_fallback_is_error(client, monkeypatch):
    """Opus 降级 mock（无 key/异常）→ t2_status=error，不伪造 9 维内容。"""
    _patch_pipeline(monkeypatch, opus_text="{}", opus_model="mock")
    data = _post_scan_and_wait(
        client, input_type="symbol", query_text="601138"
    )
    c = data["candidates"][0]
    assert c["t2_status"] == "error"
    assert c["niche_text"] is None  # 不伪造
    assert data["summary_json"]["t2_status"] == "error"


def test_radar_t2_error_html_shows_banner(client, monkeypatch):
    _patch_pipeline(monkeypatch, opus_text="{}", opus_model="mock")
    r = client.post(
        "/api/radar/scans",
        data={"input_type": "symbol", "query_text": "601138"},
        headers={"hx-request": "true"},
    )
    assert "深度研报失败" in r.text
    assert "no-mock" in r.text


# ── 三段溯源 / 晋级 / 红线 ────────────────────────────────────────────────
def test_radar_artifacts_three_stages(client, mock_pipeline):
    data = _post_scan_and_wait(
        client, input_type="symbol", query_text="601138"
    )
    cid = data["candidates"][0]["id"]
    arts = client.get(f"/api/radar/candidates/{cid}/artifacts").json()
    stages = {a["stage"] for a in arts}
    assert stages == {"T0_raw", "T1_distilled", "T2_verdict"}
    t2 = next(a for a in arts if a["stage"] == "T2_verdict")
    assert t2["token_cost"] > 0


def test_radar_promote_advisory(client, mock_pipeline):
    cid = _post_scan_and_wait(
        client, input_type="symbol", query_text="601138"
    )["candidates"][0]["id"]
    pr = client.post(f"/api/radar/candidates/{cid}/promote", data={"new_theme": "测试晋级"})
    assert pr.status_code == 200
    body = pr.json()
    assert body["campaign_id"]
    assert body["execute_mode"] == "advisory"
    assert body["human_confirmation_required"] is True


def test_radar_concept_not_implemented(client):
    r = client.post("/api/radar/scans", data={"input_type": "concept", "query_text": "AI算力"})
    assert r.status_code == 501


def test_resolve_chat_model_deepseek():
    from apps.copilot.modules.radar.chat import chat_model_route, resolve_chat_model
    from apps.copilot.modules.radar.deepseek_models import resolve_deepseek_api

    assert resolve_chat_model("deepseek-chat") == "deepseek:deepseek-chat"
    assert resolve_chat_model("deepseek-r1") == "deepseek:deepseek-reasoner"
    assert resolve_chat_model("deepseek:deepseek-v4-pro") == "deepseek:deepseek-v4-pro"
    assert chat_model_route("deepseek:deepseek-chat") == "deepseek"
    assert chat_model_route("claude-opus-4-6") == "remote"
    api_model, thinking = resolve_deepseek_api("deepseek:deepseek-v4-pro")
    assert api_model == "deepseek-v4-pro"
    assert thinking is True


def test_resolve_opus_model_remaps_invalid_slug():
    from apps.copilot.modules.radar.chat import resolve_opus_model

    assert resolve_opus_model("claude-opus-4-9") == "claude-opus-4-6"
    assert resolve_opus_model("claude-opus-4-5") == "claude-opus-4-5-20251101"
    assert resolve_opus_model(None) == "claude-opus-4-6"


def test_radar_scan_empty_query_rejected(client):
    r = client.post(
        "/api/radar/scans",
        data={"input_type": "symbol"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert "无法识别标的" in r.text
    assert "请输入股票代码或简称" in r.text


def test_planning_radar_tab_has_scan_form(client):
    r = client.get("/planning?view=radar")
    assert r.status_code == 200
    assert "模式 C" in r.text
    assert "/api/radar/scans" in r.text


def test_no_auto_execute_radar_modules():
    root = Path(__file__).resolve().parents[2] / "apps" / "copilot" / "modules" / "radar"
    hits = []
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if FORBIDDEN.search(text):
            hits.append(str(p))
    assert hits == []


def test_t1_to_candidate_fields_from_verdict(mock_pipeline_unused=None):
    from apps.copilot.modules.radar.scanner import t1_to_candidate_fields

    t1 = build_context_matrix(MOCK_T0)
    t2 = {
        "status": "ok",
        "model_id": "claude-opus-4-6",
        "route": "remote",
        "deep_analysis": OPUS_VERDICT,
        "confidence": 0.75,
        "tokens_in": 1200,
        "tokens_out": 800,
        "cost_yuan": 0.42,
    }
    fields = t1_to_candidate_fields(MOCK_T0, t1, t2)
    assert fields["is_leader"] == "yes"
    assert fields["market_phase"] == "expectation"
    assert fields["raw_json"]["cost"]["cost_yuan"] == 0.42
    assert fields["raw_json"]["deep_analysis"]["overall"]["confidence"] == 0.75


def test_t1_to_candidate_fields_error_no_fake(mock_pipeline_unused=None):
    from apps.copilot.modules.radar.scanner import t1_to_candidate_fields

    t1 = build_context_matrix(MOCK_T0)
    t2 = {"status": "error", "detail": "Opus 不可达", "deep_analysis": {}, "confidence": 0.0}
    fields = t1_to_candidate_fields(MOCK_T0, t1, t2)
    assert fields["is_leader"] is None
    assert fields["market_phase"] is None
    assert fields["risk_summary"] == "Opus 不可达"
