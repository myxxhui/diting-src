"""推荐池模块 pytest:schema + handler + service + PDF。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import ThesisCard, UserDecision
from apps.copilot.events.handlers.thesis_proposed import handle_thesis_proposed
from apps.copilot.main import app
from apps.copilot.modules.recommendation.schema import (
    ThesisProposedPayload,
    UserActionPayload,
)
from apps.copilot.modules.recommendation.service import (
    export_pdf,
    list_pool,
    record_action,
)


def _payload(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "event_type": "thesis_proposed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thesis_id": str(uuid.uuid4()),
        "symbol": "600519",
        "name": "贵州茅台",
        "thesis_summary": "高端白酒龙头,品牌护城河深厚,具备长期持有价值,估值合理。",
        "evidence_chain": ["毛利率 93%", "库存历史低位", "直销占比提升"],
        "risks": ["高端需求不确定", "估值中位数"],
        "valuation_anchor": {"method": "PE", "target_pe": 35},
        "action": "buy",
    }
    base.update(overrides)
    return base


def test_schema_accepts_full_payload():
    parsed = ThesisProposedPayload.model_validate(_payload())
    assert parsed.symbol == "600519"
    assert len(parsed.evidence_chain) == 3
    assert parsed.action == "buy"


def test_schema_rejects_insufficient_evidence():
    bad = _payload(evidence_chain=["仅一条"])
    with pytest.raises(ValidationError) as exc:
        ThesisProposedPayload.model_validate(bad)
    assert "evidence_chain" in str(exc.value)


def test_schema_rejects_invalid_action():
    bad = _payload(action="explode")
    with pytest.raises(ValidationError):
        ThesisProposedPayload.model_validate(bad)


def test_schema_rejects_short_summary():
    bad = _payload(thesis_summary="太短")
    with pytest.raises(ValidationError):
        ThesisProposedPayload.model_validate(bad)


def test_handler_writes_valid_event():
    async def _run():
        await init_db()
        async with AsyncSessionLocal() as s:
            await handle_thesis_proposed(s, _payload(), msg_id="1-0")
            return await s.scalar(select(func.count(ThesisCard.id)))

    assert asyncio.run(_run()) == 1


def test_handler_skips_invalid_event():
    async def _run():
        await init_db()
        async with AsyncSessionLocal() as s:
            await handle_thesis_proposed(s, _payload(action="bad"), msg_id="1-0")
            return await s.scalar(select(func.count(ThesisCard.id)))

    assert asyncio.run(_run()) == 0


def test_record_action_filters_pool():
    async def _run():
        await init_db()
        p = _payload()
        async with AsyncSessionLocal() as s:
            await handle_thesis_proposed(s, p, msg_id="1-0")
        async with AsyncSessionLocal() as s:
            before = await list_pool(s)
            assert len(before) == 1

            await record_action(s, p["thesis_id"], UserActionPayload(action="join"))
            after = await list_pool(s)
            count_decisions = await s.scalar(select(func.count(UserDecision.id)))
        return len(after), count_decisions

    after_count, decisions = asyncio.run(_run())
    assert after_count == 0
    assert decisions == 1


def test_pdf_generation_returns_bytes():
    async def _run():
        await init_db()
        p = _payload()
        async with AsyncSessionLocal() as s:
            await handle_thesis_proposed(s, p, msg_id="1-0")
        async with AsyncSessionLocal() as s:
            return await export_pdf(s, p["thesis_id"])

    try:
        data = asyncio.run(_run())
    except OSError as exc:
        pytest.skip(
            f"WeasyPrint 在本机未就绪: {exc}；"
            f"产品准出请以 L3 step_04 §3.10（docker build + docker run pytest）为权威。"
        )
    assert data is not None
    assert data[:4] == b"%PDF"


def test_api_action_endpoint():
    async def _seed():
        await init_db()
        p = _payload()
        async with AsyncSessionLocal() as s:
            await handle_thesis_proposed(s, p, msg_id="1-0")
        return p["thesis_id"]

    thesis_id = asyncio.run(_seed())
    with TestClient(app) as client:
        r = client.post(
            f"/api/recommendations/{thesis_id}/action",
            json={"action": "join"},
        )
        assert r.status_code == 200
        assert "已操作" in r.text
