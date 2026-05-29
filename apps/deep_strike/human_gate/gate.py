"""HumanGate — 人工确认门禁（唯一 confirmed 入口）。

永久规则：
  - 仅 HumanGate._promote_to_confirmed() 可将 thesis_cards.status 改为 confirmed
  - confirmed 后由 ThesisPublisher 推送 events:thrust:thesis_proposed → D0 推荐池

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_08_人工确认门禁与一致率.md]
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from apps.deep_strike.db.models import HumanConfirmation, ThesisCard

logger = logging.getLogger(__name__)

THRUST_PROPOSED_STREAM = "events:thrust:thesis_proposed"


def _event_id() -> str:
    return f"hg-{uuid.uuid4().hex[:12]}"


class HumanGate:
    """人工确认门禁。confirm/reject/defer 三条路径。"""

    def __init__(self, redis_client=None) -> None:
        """
        Args:
            redis_client: 已连接的 redis-py 客户端（sync），用于发布 thesis_proposed；
                          为 None 时仅更新 DB，不发布。
        """
        self._redis = redis_client

    async def confirm(
        self,
        session: AsyncSession,
        *,
        thesis_id: str,
        reviewer: str,
        comment: str = "",
    ) -> dict:
        """人工 confirm：唯一合法的 status→confirmed 路径。"""
        card = await self._get_card(session, thesis_id)
        if card is None:
            return {"ok": False, "reason": "thesis_not_found"}
        if card.status == "confirmed":
            return {"ok": True, "reason": "already_confirmed"}

        consistency_label = _infer_consistency(card)
        conf = HumanConfirmation(
            thesis_id=thesis_id,
            reviewer=reviewer,
            decision="confirm",
            comment=comment or None,
            consistency_label=consistency_label,
        )
        session.add(conf)

        # 唯一 confirmed 入口
        await self._promote_to_confirmed(session, card)
        await session.commit()

        msg_id = self._publish_thesis_proposed(card)
        logger.info(
            "HumanGate.confirm thesis_id=%s reviewer=%s stream_msg=%s",
            thesis_id,
            reviewer,
            msg_id,
        )
        return {"ok": True, "reason": "confirmed", "stream_msg_id": msg_id}

    async def reject(
        self,
        session: AsyncSession,
        *,
        thesis_id: str,
        reviewer: str,
        comment: str = "",
    ) -> dict:
        """人工 reject：status→rejected，不推送 stream。"""
        card = await self._get_card(session, thesis_id)
        if card is None:
            return {"ok": False, "reason": "thesis_not_found"}

        conf = HumanConfirmation(
            thesis_id=thesis_id,
            reviewer=reviewer,
            decision="reject",
            comment=comment or None,
            consistency_label=_infer_consistency(card),
        )
        session.add(conf)
        card.status = "rejected"
        await session.commit()
        logger.info("HumanGate.reject thesis_id=%s reviewer=%s", thesis_id, reviewer)
        return {"ok": True, "reason": "rejected"}

    async def defer(
        self,
        session: AsyncSession,
        *,
        thesis_id: str,
        reviewer: str,
        comment: str = "",
    ) -> dict:
        """人工 defer：status→deferred，不推送 stream。"""
        card = await self._get_card(session, thesis_id)
        if card is None:
            return {"ok": False, "reason": "thesis_not_found"}

        conf = HumanConfirmation(
            thesis_id=thesis_id,
            reviewer=reviewer,
            decision="defer",
            comment=comment or None,
            consistency_label=_infer_consistency(card),
        )
        session.add(conf)
        card.status = "deferred"
        await session.commit()
        logger.info("HumanGate.defer thesis_id=%s reviewer=%s", thesis_id, reviewer)
        return {"ok": True, "reason": "deferred"}

    # ---------- 内部 ----------

    @staticmethod
    async def _get_card(session: AsyncSession, thesis_id: str) -> Optional[ThesisCard]:
        result = await session.execute(
            select(ThesisCard).where(ThesisCard.thesis_id == thesis_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _promote_to_confirmed(session: AsyncSession, card: ThesisCard) -> None:
        """唯一允许写 confirmed 的私有方法。"""
        card.status = "confirmed"

    def _publish_thesis_proposed(self, card: ThesisCard) -> Optional[str]:
        """向 events:thrust:thesis_proposed 发布 ThesisProposedPayload 格式消息。"""
        if self._redis is None:
            logger.warning("HumanGate: redis_client 未配置，跳过 thesis_proposed 发布")
            return None

        evidence_chain = []
        if card.evidence_chain:
            try:
                ec = card.evidence_chain if isinstance(card.evidence_chain, list) else json.loads(card.evidence_chain)
                evidence_chain = [str(e) for e in ec] if ec else []
            except Exception:
                pass
        if len(evidence_chain) < 3:
            evidence_chain = (evidence_chain + ["证据待补充"] * 3)[:3]

        risks = []
        if card.risks:
            try:
                r = card.risks if isinstance(card.risks, list) else json.loads(card.risks)
                risks = [str(x) for x in r] if r else []
            except Exception:
                pass
        if not risks:
            risks = ["风险待评估"]

        payload = {
            "event_id": _event_id(),
            "event_type": "thesis_proposed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thesis_id": card.thesis_id,
            "symbol": card.symbol,
            "name": card.name,
            "thesis_summary": card.thesis_summary or "",
            "evidence_chain": evidence_chain,
            "risks": risks,
            "valuation_anchor": {
                "method": "PB",
                "target": None,
                "current": None,
                "upside_pct": None,
            },
            "action": card.action or "持有观察",
            "pass_event_id": card.pass_event_id,
        }
        try:
            msg_id = self._redis.xadd(
                THRUST_PROPOSED_STREAM,
                {"json": json.dumps(payload, ensure_ascii=False, default=str)},
            )
            return msg_id
        except Exception as exc:
            logger.warning("thesis_proposed publish failed: %s", exc)
            return None


def _infer_consistency(card: ThesisCard) -> str:
    """根据 ThesisCard confidence 与 action 推断 AI 决策方向，与人工 confirm 对比。

    启动期简化：confidence ≥0.55 且 action 含「买入/增持」 → agree；否则 partial。
    """
    if card is None:
        return "unknown"
    confidence = float(card.confidence or 0.0)
    action = str(card.action or "").lower()
    if confidence >= 0.55 and any(k in action for k in ("买入", "增持", "建仓")):
        return "agree"
    return "partial"
