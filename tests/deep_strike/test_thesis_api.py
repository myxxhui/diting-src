"""D2 thesis API + timer_signal Redis 投递单测。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.deep_strike.db.database import init_db
from apps.deep_strike.events.publisher import DEEP_STRIKE_TIMER_STREAM, RedisPublisher
from apps.deep_strike.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_thesis_generate_api(monkeypatch):
    await init_db()
    monkeypatch.setattr(
        "apps.deep_strike.engines.thesis.generator.ThesisCardGenerator._get_timer",
        lambda self: None,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/thesis/generate",
            json={
                "symbol": "300308",
                "name": "中际旭创",
                "playbook_id": "profit_capture",
                "confidence": 0.8,
                "decision_hint": "watch",
                "enable_timer": False,
                "publish_redis": False,
                "evidence": [
                    {"evidence_type": "financial", "content": "毛利率连续三季改善，经营现金流显著好转。"},
                    {"evidence_type": "announcement", "content": "公司公告海外大客户订单落地，交付节奏明确。"},
                    {"evidence_type": "industry", "content": "光模块行业景气度回升，龙头份额提升。"},
                ],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["thesis_id"]
    assert body["symbol"] == "300308"
    assert body["status"] == "proposed"


def test_timer_publisher_payload():
    pub = RedisPublisher(redis_url="redis://127.0.0.1:9")
    msg_id = pub.publish_timer_signal(
        thesis_card_id="t-1",
        symbol="300308",
        stage="retreat",
        evidence_url="https://example.com",
        financial_report_date="2026-08-31",
    )
    assert msg_id is None  # 无 Redis 时落本地队列
    assert pub.pending_count == 1
    item = pub._local_queue[0]
    assert item["stream"] == DEEP_STRIKE_TIMER_STREAM
    assert item["payload"]["stage"] == "retreat"
    assert item["payload"]["execute_mode"] == "advisory"
