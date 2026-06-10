"""T2 手动同步执行区 pin 单测。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.executing.t2_advice_summary import (
    extract_symbol_advice,
    load_executing_t2_summaries_for_symbols,
    render_executing_t2_banner,
)
from apps.copilot.modules.executing.t2_executing_pin import (
    load_pinned_t2_summaries_for_symbols,
    pin_t2_to_executing,
    unpin_t2_from_executing,
)


def _sample_payload() -> dict:
    return {
        "api_connected": True,
        "model_id": "claude-opus-4-6",
        "symbols": ["601138.SH"],
        "opus_audit": {
            "Execution_Command": {
                "action": "hold",
                "one_sentence_summary": "工业富联持有",
                "targets": [{"symbol": "601138.SH", "advice": "hold", "rationale": "逻辑完好"}],
            },
            "symbol_audits": {
                "601138.SH": {
                    "near_term_advice": "hold",
                    "holding_honesty": "维持仓位",
                }
            },
        },
    }


@pytest.mark.asyncio
async def test_pin_and_load_pinned_only(db_session):
    from apps.copilot.db.models import ExecutingT2AnalystRequest
    from apps.copilot.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        row = ExecutingT2AnalystRequest(
            request_id="pinreq001",
            session_id="sess1",
            user_question="测试",
            model_id="claude-opus-4-6",
            symbols_json=["601138.SH"],
            dry_run=False,
            api_connected=True,
            payload_json=_sample_payload(),
        )
        session.add(row)
        await session.commit()

    async with AsyncSessionLocal() as session:
        empty = await load_pinned_t2_summaries_for_symbols(session, ["601138.SH"])
        assert empty == {}

        result = await pin_t2_to_executing(
            session, request_id="pinreq001", symbols=["601138"]
        )
        await session.commit()
        assert "601138.SH" in result["pinned_symbols"]

        loaded = await load_pinned_t2_summaries_for_symbols(session, ["601138.SH"])
        assert "601138.SH" in loaded
        assert loaded["601138.SH"]["summary"] == "逻辑完好"
        assert loaded["601138.SH"].get("pinned") is True


@pytest.mark.asyncio
async def test_pin_requires_symbols(db_session):
    from apps.copilot.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="勾选"):
            await pin_t2_to_executing(session, request_id="x", symbols=[])


def test_extract_symbol_advice_ok():
    advice = extract_symbol_advice(_sample_payload(), "601138.SH", request_id="r1")
    assert advice
    assert advice["action_label"] == "持有"


@pytest.mark.asyncio
async def test_load_executing_t2_summaries_latest_fallback(db_session):
    from apps.copilot.db.models import ExecutingT2AnalystRequest
    from apps.copilot.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        row = ExecutingT2AnalystRequest(
            request_id="latestreq01",
            session_id="sess2",
            user_question="测试",
            model_id="claude-opus-4-6",
            symbols_json=["601138.SH"],
            dry_run=False,
            api_connected=True,
            payload_json=_sample_payload(),
        )
        session.add(row)
        await session.commit()

    async with AsyncSessionLocal() as session:
        loaded = await load_executing_t2_summaries_for_symbols(session, ["601138"])
        assert "601138" in loaded
        assert loaded["601138"]["source"] == "latest"
        assert loaded["601138"]["summary"] == "逻辑完好"


@pytest.mark.asyncio
async def test_load_executing_t2_summaries_pin_overrides_latest(db_session):
    from apps.copilot.db.models import ExecutingT2AnalystRequest
    from apps.copilot.db.database import AsyncSessionLocal

    old_payload = _sample_payload()
    new_payload = dict(old_payload)
    new_payload["opus_audit"] = {
        **old_payload["opus_audit"],
        "Execution_Command": {
            **old_payload["opus_audit"]["Execution_Command"],
            "one_sentence_summary": "较新的自动分析",
            "targets": [
                {"symbol": "601138.SH", "advice": "hold", "rationale": "较新的自动分析"}
            ],
        },
    }

    async with AsyncSessionLocal() as session:
        session.add(
            ExecutingT2AnalystRequest(
                request_id="oldreq001",
                session_id="s1",
                user_question="旧",
                model_id="claude-opus-4-6",
                symbols_json=["601138.SH"],
                dry_run=False,
                api_connected=True,
                payload_json=old_payload,
            )
        )
        session.add(
            ExecutingT2AnalystRequest(
                request_id="newreq001",
                session_id="s2",
                user_question="新",
                model_id="claude-opus-4-6",
                symbols_json=["601138.SH"],
                dry_run=False,
                api_connected=True,
                payload_json=new_payload,
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        await pin_t2_to_executing(session, request_id="oldreq001", symbols=["601138"])
        await session.commit()

    async with AsyncSessionLocal() as session:
        loaded = await load_executing_t2_summaries_for_symbols(session, ["601138"])
        assert loaded["601138"]["source"] == "pinned"
        assert loaded["601138"]["summary"] == "逻辑完好"


def test_render_executing_t2_banner_empty_text():
    html = render_executing_t2_banner("601138", None)
    assert "暂无 T2 持仓分析" in html


def test_render_executing_t2_banner_pinned_has_unpin():
    html = render_executing_t2_banner(
        "601138",
        {"source": "pinned", "action_label": "持有", "summary": "测试", "request_id": "abc"},
    )
    assert "自动同步已阻塞" in html
    assert "解除固定" in html
    assert "executing-t2-unpin-btn" in html


@pytest.mark.asyncio
async def test_unpin_restores_latest(db_session):
    from apps.copilot.db.database import AsyncSessionLocal
    from apps.copilot.db.models import ExecutingT2AnalystRequest

    old_payload = _sample_payload()
    new_payload = dict(old_payload)
    new_payload["opus_audit"] = {
        **old_payload["opus_audit"],
        "Execution_Command": {
            **old_payload["opus_audit"]["Execution_Command"],
            "one_sentence_summary": "较新的自动分析",
            "targets": [
                {"symbol": "601138.SH", "advice": "hold", "rationale": "较新的自动分析"}
            ],
        },
    }

    async with AsyncSessionLocal() as session:
        session.add(
            ExecutingT2AnalystRequest(
                request_id="oldreq002",
                session_id="s1",
                user_question="旧",
                model_id="claude-opus-4-6",
                symbols_json=["601138.SH"],
                dry_run=False,
                api_connected=True,
                payload_json=old_payload,
            )
        )
        session.add(
            ExecutingT2AnalystRequest(
                request_id="newreq002",
                session_id="s2",
                user_question="新",
                model_id="claude-opus-4-6",
                symbols_json=["601138.SH"],
                dry_run=False,
                api_connected=True,
                payload_json=new_payload,
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        await pin_t2_to_executing(session, request_id="oldreq002", symbols=["601138"])
        await session.commit()

    async with AsyncSessionLocal() as session:
        pinned = await load_executing_t2_summaries_for_symbols(session, ["601138"])
        assert pinned["601138"]["source"] == "pinned"

    async with AsyncSessionLocal() as session:
        await unpin_t2_from_executing(session, "601138")
        await session.commit()

    async with AsyncSessionLocal() as session:
        restored = await load_executing_t2_summaries_for_symbols(session, ["601138"])
        assert restored["601138"]["source"] == "latest"
        assert restored["601138"]["summary"] == "较新的自动分析"
