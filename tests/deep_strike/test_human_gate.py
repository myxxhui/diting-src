"""D2 step_08 · HumanGate 单测。

覆盖：confirm / reject / defer + publisher + 防 bypass。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_08_人工确认门禁与一致率.md §3.5]
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.deep_strike.db.models import ThesisCard, HumanConfirmation
from apps.deep_strike.human_gate.gate import HumanGate, THRUST_PROPOSED_STREAM, _infer_consistency


# ---------- helpers ----------

def _make_card(thesis_id: str, confidence: float = 0.6, action: str = "买入观察", status: str = "proposed") -> ThesisCard:
    card = MagicMock(spec=ThesisCard)
    card.thesis_id = thesis_id
    card.symbol = "601138"
    card.name = "工商银行"
    card.confidence = confidence
    card.action = action
    card.status = status
    card.thesis_summary = "工商银行具有护城河，营收稳健，风险可控。估值处于历史低位区间，有安全边际。"
    card.evidence_chain = ["盈利能力强", "市值低估", "ROE 稳定"]
    card.risks = ["利率风险"]
    card.valuation_anchor = {"method": "PB", "target": 0.8}
    card.pass_event_id = "pass-001"
    return card


def _make_session(card: Optional[ThesisCard] = None) -> AsyncSession:
    session = AsyncMock(spec=AsyncSession)
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=card)
    session.execute = AsyncMock(return_value=mock_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


# ---------- _infer_consistency ----------

class TestInferConsistency:
    def test_agree_when_high_confidence_and_buy_action(self):
        card = _make_card("t1", confidence=0.65, action="买入")
        assert _infer_consistency(card) == "agree"

    def test_partial_when_low_confidence(self):
        card = _make_card("t2", confidence=0.40, action="买入")
        assert _infer_consistency(card) == "partial"

    def test_partial_when_watch_action(self):
        card = _make_card("t3", confidence=0.65, action="观察")
        assert _infer_consistency(card) == "partial"

    def test_none_returns_unknown(self):
        assert _infer_consistency(None) == "unknown"


# ---------- HumanGate.confirm ----------

@pytest.mark.asyncio
class TestHumanGateConfirm:
    async def test_confirm_sets_status_and_adds_confirmation(self):
        card = _make_card("thesis-001")
        session = _make_session(card)

        gate = HumanGate(redis_client=None)
        result = await gate.confirm(session, thesis_id="thesis-001", reviewer="arch", comment="LGTM")

        assert result["ok"] is True
        assert result["reason"] == "confirmed"
        assert card.status == "confirmed"
        assert session.add.called
        assert session.commit.called

    async def test_confirm_not_found_returns_error(self):
        session = _make_session(None)
        gate = HumanGate(redis_client=None)
        result = await gate.confirm(session, thesis_id="missing", reviewer="arch")
        assert result["ok"] is False
        assert result["reason"] == "thesis_not_found"

    async def test_confirm_already_confirmed_is_idempotent(self):
        card = _make_card("thesis-002", status="confirmed")
        session = _make_session(card)
        gate = HumanGate(redis_client=None)
        result = await gate.confirm(session, thesis_id="thesis-002", reviewer="arch")
        assert result["ok"] is True
        assert result["reason"] == "already_confirmed"

    async def test_confirm_publishes_to_redis_when_available(self):
        card = _make_card("thesis-003")
        session = _make_session(card)

        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="1779999-0")
        gate = HumanGate(redis_client=mock_redis)
        result = await gate.confirm(session, thesis_id="thesis-003", reviewer="arch")

        assert result["ok"] is True
        assert result["stream_msg_id"] == "1779999-0"
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args[0]
        assert call_args[0] == THRUST_PROPOSED_STREAM
        payload = json.loads(call_args[1]["json"])
        assert payload["event_type"] == "thesis_proposed"
        assert payload["symbol"] == card.symbol
        assert payload["thesis_id"] == card.thesis_id
        assert len(payload["evidence_chain"]) >= 3

    async def test_confirm_stream_msg_none_when_no_redis(self):
        card = _make_card("thesis-004")
        session = _make_session(card)
        gate = HumanGate(redis_client=None)
        result = await gate.confirm(session, thesis_id="thesis-004", reviewer="arch")
        assert result["stream_msg_id"] is None


# ---------- HumanGate.reject ----------

@pytest.mark.asyncio
class TestHumanGateReject:
    async def test_reject_sets_status_rejected(self):
        card = _make_card("thesis-005")
        session = _make_session(card)
        gate = HumanGate(redis_client=None)
        result = await gate.reject(session, thesis_id="thesis-005", reviewer="arch")
        assert result["ok"] is True
        assert card.status == "rejected"

    async def test_reject_does_not_publish_to_redis(self):
        card = _make_card("thesis-006")
        session = _make_session(card)
        mock_redis = MagicMock()
        gate = HumanGate(redis_client=mock_redis)
        await gate.reject(session, thesis_id="thesis-006", reviewer="arch")
        mock_redis.xadd.assert_not_called()

    async def test_reject_not_found(self):
        session = _make_session(None)
        gate = HumanGate(redis_client=None)
        result = await gate.reject(session, thesis_id="missing", reviewer="arch")
        assert result["ok"] is False


# ---------- HumanGate.defer ----------

@pytest.mark.asyncio
class TestHumanGateDefer:
    async def test_defer_sets_status_deferred(self):
        card = _make_card("thesis-007")
        session = _make_session(card)
        gate = HumanGate(redis_client=None)
        result = await gate.defer(session, thesis_id="thesis-007", reviewer="arch")
        assert result["ok"] is True
        assert card.status == "deferred"

    async def test_defer_does_not_publish_to_redis(self):
        card = _make_card("thesis-008")
        session = _make_session(card)
        mock_redis = MagicMock()
        gate = HumanGate(redis_client=mock_redis)
        await gate.defer(session, thesis_id="thesis-008", reviewer="arch")
        mock_redis.xadd.assert_not_called()


# ---------- 防 bypass 验证 ----------

class TestNoBypass:
    def test_only_promote_to_confirmed_can_set_confirmed_status(self):
        """验证没有其他路径直接 UPDATE status=confirmed。"""
        import ast, pathlib
        gate_src = pathlib.Path(
            __file__
        ).parents[2] / "apps" / "deep_strike" / "human_gate" / "gate.py"
        tree = ast.parse(gate_src.read_text())
        confirmed_assignments = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "status":
                        if isinstance(node.value, ast.Constant) and node.value.value == "confirmed":
                            confirmed_assignments.append(node.lineno)
        # 只有 _promote_to_confirmed 一处
        assert len(confirmed_assignments) == 1, (
            f"发现多处 status='confirmed' 赋值（行 {confirmed_assignments}），违反防 bypass 规则"
        )
