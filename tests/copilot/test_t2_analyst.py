"""T2 持仓分析师单测。"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.main import app
from apps.copilot.modules.executing.t2_analyst import (
    DEFAULT_PROMPT_TEMPLATE,
    analyst_chat_turn,
    assemble_t2_analyst_payload,
    clear_analyst_session,
    format_assembly_summary,
    load_analyst_messages,
    new_analyst_session_id,
    strip_jl4_from_t1,
    t2_opus_enabled,
)


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        for mod in (
            "apps.copilot.routers.executing_routes",
            "apps.copilot.services.redis_wait",
        ):
            monkeypatch.setattr(f"{mod}.wait_for_sync_redis", _fake_wait)
        yield fake
    except ImportError:
        yield None


@pytest.fixture
async def db_ready():
    await init_db()
    yield


def _sample_t1() -> dict:
    return {
        "batch_meta": {
            "execution_id": "batch_prod",
            "timestamp": "2026-06-09T00:00:00Z",
            "total_stocks_checked": 1,
            "system_status": "Nominal",
            "account_available_cash": 100000.0,
            "money_unit": "人民币",
        },
        "portfolio_signals": {
            "601138.SH": {
                "stock_name": "工业富联",
                "position_context": {"cost_basis": 50.0, "current_price": 74.0},
                "indicators": {
                    "qmt_atr_trailing": {"value": 2.0, "fact_statement": "sample"},
                },
            }
        },
    }


def test_strip_jl4_from_t1():
    t1 = _sample_t1()
    out = strip_jl4_from_t1(t1)
    sig = out["portfolio_signals"]["601138.SH"]
    assert sig["indicators"] == {}


def test_default_prompt_template():
    assert "T2 持仓审计" in DEFAULT_PROMPT_TEMPLATE
    assert "增、减、清仓" in DEFAULT_PROMPT_TEMPLATE


@pytest.mark.asyncio
async def test_assemble_t2_analyst_payload(db_ready):
    session = AsyncMock()
    with patch(
        "apps.copilot.modules.executing.t2_analyst.assemble_batch_portfolio",
        new_callable=AsyncMock,
        return_value=_sample_t1(),
    ):
        payload = await assemble_t2_analyst_payload(
            session,
            ["601138"],
            user_question="组合风险？",
            model_id="claude-opus-4-6",
            include_t1_jl4=True,
            redis_client=None,
        )
    assert payload["user_question"].startswith("组合风险？")
    assert "JL1–JL3" in payload["user_question"]
    assert payload.get("include_jl13_data") is True
    assert payload["envelope"]["qa_index"]
    assert len(payload["opus_messages"]) == 2


@pytest.mark.asyncio
async def test_analyst_chat_turn_assembly_only(db_ready, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("EXECUTING_T2_ENABLED", "false")
    sid = new_analyst_session_id()
    await clear_analyst_session(sid)
    with patch(
        "apps.copilot.modules.executing.t2_analyst.assemble_batch_portfolio",
        new_callable=AsyncMock,
        return_value=_sample_t1(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/executing/analyst/chat",
                data={
                    "symbols": "601138",
                    "message": DEFAULT_PROMPT_TEMPLATE,
                    "model_id": "claude-opus-4-6",
                    "include_t1_jl4": "1",
                    "session_id": sid,
                },
                headers={"HX-Request": "true"},
            )
    assert r.status_code == 200
    assert "仅数据拼接" in r.text or "未调用 Opus" in r.text


@pytest.mark.asyncio
async def test_analyst_chat_turn_opus_mocked(db_ready, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("EXECUTING_T2_ENABLED", "true")
    sid = new_analyst_session_id()
    await clear_analyst_session(sid)

    mock_resp = MagicMock()
    mock_resp.model = "claude-opus-4-6"
    mock_resp.text = (
        '{"Execution_Command":{"action":"hold","one_sentence_summary":"持有",'
        '"targets":[]},"Executing_Daily_Audit":{"L3_Fundamental_Verdict":"ok",'
        '"L4_Microstructure_Verdict":"ok"}}'
    )
    mock_resp.route = "remote"
    mock_resp.tokens_in = 100
    mock_resp.tokens_out = 200
    mock_resp.cost_yuan_est = 0.5
    mock_resp.latency_ms = 1200
    mock_resp.raw = {}

    with patch(
        "apps.copilot.modules.executing.t2_analyst.assemble_batch_portfolio",
        new_callable=AsyncMock,
        return_value=_sample_t1(),
    ), patch(
        "apps.copilot.modules.executing.t2_analyst.invoke_t2_opus_audit",
        new_callable=AsyncMock,
        return_value={
            "audit": {
                "Execution_Command": {"action": "hold", "one_sentence_summary": "持有", "targets": []},
                "Executing_Daily_Audit": {
                    "L3_Fundamental_Verdict": "ok",
                    "L4_Microstructure_Verdict": "ok",
                },
            },
            "meta": {"model": "claude-opus-4-6", "cost_yuan": 0.5, "tokens_in": 100, "tokens_out": 200},
            "raw_text": "{}",
        },
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/executing/analyst/chat",
                data={
                    "symbols": "601138",
                    "message": "审计",
                    "model_id": "claude-opus-4-6",
                    "include_t1_jl4": "1",
                    "session_id": sid,
                },
                headers={"HX-Request": "true"},
            )
    assert r.status_code == 200
    assert "组合结论" in r.text
    assert "t2-analyst-result" in r.text


@pytest.mark.asyncio
async def test_t2_analyst_panel_html(db_ready):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/executing/analyst-panel-html")
    assert r.status_code == 200
    assert "T2 持仓分析工作台" in r.text
    assert "默认问题模板" in r.text
    assert "JL1–3 数据需求模板" in r.text
    assert "include_jl13_data" in r.text


@pytest.mark.asyncio
async def test_t2_analyst_audit_persisted(db_ready, monkeypatch):
    from apps.copilot.db.models import ExecutingT2AnalystRequest
    from sqlalchemy import select

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sid = new_analyst_session_id()
    with patch(
        "apps.copilot.modules.executing.t2_analyst.assemble_batch_portfolio",
        new_callable=AsyncMock,
        return_value=_sample_t1(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/executing/analyst/chat",
                data={
                    "symbols": "601138",
                    "message": DEFAULT_PROMPT_TEMPLATE,
                    "session_id": sid,
                },
                headers={"HX-Request": "true"},
            )
    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(ExecutingT2AnalystRequest))).all()
    assert rows
    rid = rows[-1].request_id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        jr = await client.get(f"/api/executing/analyst/audit/{rid}")
    assert jr.status_code == 200
    assert jr.json()["user_question"] == DEFAULT_PROMPT_TEMPLATE
    assert "assistant_render_html" in jr.json()


@pytest.mark.asyncio
async def test_t2_analyst_session_persisted_redis_pg(db_ready, monkeypatch, _fake_redis):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sid = new_analyst_session_id()
    await clear_analyst_session(sid)
    with patch(
        "apps.copilot.modules.executing.t2_analyst.assemble_batch_portfolio",
        new_callable=AsyncMock,
        return_value=_sample_t1(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/executing/analyst/chat",
                data={
                    "symbols": "601138",
                    "message": "持久化测试",
                    "session_id": sid,
                },
                headers={"HX-Request": "true"},
            )
            import apps.copilot.modules.executing.t2_analyst as mod

            mod._memory_sessions.pop(sid, None)
            r = await client.get(f"/api/executing/analyst/chat/{sid}")
    assert r.status_code == 200
    assert "持久化测试" in r.text

    from apps.copilot.db.models import ExecutingT2AnalystSession
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ExecutingT2AnalystSession).where(
                ExecutingT2AnalystSession.session_id == sid
            )
        )
    assert row is not None
    assert any(m.get("content") == "持久化测试" for m in (row.messages_json or []))


@pytest.mark.asyncio
async def test_t2_analyst_audit_html_includes_opus_reply(db_ready, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv("EXECUTING_T2_ENABLED", "true")
    sid = new_analyst_session_id()
    with patch(
        "apps.copilot.modules.executing.t2_analyst.assemble_batch_portfolio",
        new_callable=AsyncMock,
        return_value=_sample_t1(),
    ), patch(
        "apps.copilot.modules.executing.t2_analyst.invoke_t2_opus_audit",
        new_callable=AsyncMock,
        return_value={
            "audit": {
                "Execution_Command": {
                    "action": "hold",
                    "one_sentence_summary": "持有工业富联",
                    "targets": [],
                },
                "Executing_Daily_Audit": {
                    "L3_Fundamental_Verdict": "工业富联：逻辑完好",
                    "L4_Microstructure_Verdict": "中性",
                },
            },
            "meta": {"model": "claude-opus-4-6", "cost_yuan": 0.1, "tokens_in": 10, "tokens_out": 20},
            "raw_text": '{"Execution_Command":{"action":"hold"}}',
        },
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/executing/analyst/chat",
                data={"symbols": "601138", "message": "审计回复", "session_id": sid},
                headers={"HX-Request": "true"},
            )
    rid = None
    async with AsyncSessionLocal() as db:
        from apps.copilot.db.models import ExecutingT2AnalystRequest
        from sqlalchemy import select

        row = (await db.scalars(select(ExecutingT2AnalystRequest))).all()[-1]
        rid = row.request_id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ar = await client.get(
            f"/api/executing/analyst/audit/{rid}",
            headers={"Accept": "text/html"},
        )
    assert ar.status_code == 200
    assert "Opus 结构化回复" in ar.text
    assert "组合结论" in ar.text
