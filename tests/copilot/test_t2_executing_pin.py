"""T2 手动同步执行区 pin 单测。"""
from __future__ import annotations

import pytest

from apps.copilot.modules.executing.t2_advice_summary import extract_symbol_advice
from apps.copilot.modules.executing.t2_executing_pin import (
    load_pinned_t2_summaries_for_symbols,
    pin_t2_to_executing,
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
        assert loaded["601138.SH"]["summary"] == "工业富联持有"
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
