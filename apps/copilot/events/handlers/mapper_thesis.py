"""The Mapper thesis_proposed 事件处理器（轻量候选卡）。

处理 events:deep_strike:thesis_proposed（payload.event_type = 'mapper_thesis_proposed'）；
将 Mapper 产出的弹性闸门候选转为 ThesisCard（status 标注来源 'mapper_candidate'）。

区别于 handle_thesis_proposed：
  - 该 handler 处理的是纯规则 Mapper 产出的轻量候选，无 LLM 生成的 thesis 全文
  - evidence_chain/risks/valuation_anchor 用结构化摘要填充（非 LLM 输出）
  - thesis_id = 'mapper:{cluster_id}'（避免与 LLM thesis 冲突）

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04 §3.5.4 M6]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import EventLog, ThesisCard

logger = logging.getLogger("copilot.handler.mapper_thesis")

STREAM_KEY = "events:deep_strike:thesis_proposed"


def _build_thesis_from_mapper(payload: dict[str, Any]) -> ThesisCard | None:
    """将 Mapper 候选 payload 转为 ThesisCard（缺必要字段则返回 None）。"""
    cluster_id = payload.get("cluster_id")
    target_symbol = payload.get("target_symbol") or payload.get("symbol")
    if not cluster_id or not target_symbol:
        return None

    elasticity = payload.get("elasticity_ratio", 0.0)
    market_cap_tier = payload.get("market_cap_tier", "unknown")
    scan_date = payload.get("scan_date", "")

    # generated_at → proposed_at
    gen_at_str = payload.get("generated_at")
    try:
        proposed_at = datetime.fromisoformat(gen_at_str).replace(tzinfo=None)
    except Exception:
        proposed_at = datetime.utcnow()

    thesis_id = f"mapper:{cluster_id}"
    return ThesisCard(
        thesis_id=thesis_id,
        symbol=target_symbol,
        name=f"候选标的 {target_symbol}",
        thesis_summary=(
            f"[Mapper 候选] 标的 {target_symbol} 通过 Critic 物理证伪门禁，"
            f"业绩弹性比 {elasticity:.1%}，市值段 {market_cap_tier}，"
            f"扫描日期 {scan_date}。等待 thesis 生成器进一步分析。"
        ),
        evidence_chain=[
            f"Critic 物理证伪门禁通过（cluster_id={cluster_id}）",
            f"业绩弹性比: {elasticity:.1%}（市值段 {market_cap_tier} 门限 met）",
            f"来源: The Mapper 自动产出，scan_date={scan_date}",
        ],
        risks=["Mapper 候选仅完成物理证伪和弹性阈值检查，需 thesis 生成器补全完整逻辑链"],
        valuation_anchor={"method": "待定", "note": "Mapper 候选，需 thesis 生成器补全估值"},
        action="watch",
        pass_event_id=payload.get("mapper_output_id") and str(payload["mapper_output_id"]),
        proposed_at=proposed_at,
    )


async def handle_mapper_thesis(
    session: AsyncSession, payload: dict[str, Any], msg_id: str
) -> None:
    """处理 events:deep_strike:thesis_proposed 中的 mapper_thesis_proposed 事件。"""
    event_type = str(payload.get("event_type") or "mapper_thesis_proposed")
    symbol = str(payload.get("target_symbol") or payload.get("symbol") or "")

    # 先记录原始事件日志
    session.add(
        EventLog(
            stream_key=STREAM_KEY,
            msg_id=msg_id,
            event_type=event_type,
            symbol=symbol,
            payload=payload,
            trace_id=payload.get("cluster_id"),
        )
    )

    # 非 mapper 事件（如 thrust 使用同流时）交由其他处理逻辑
    if event_type not in ("mapper_thesis_proposed",):
        logger.info(
            "[mapper_thesis] 未知 event_type=%s, 仅记录日志 msg_id=%s", event_type, msg_id
        )
        await session.commit()
        return

    # 幂等：cluster_id 对应的 thesis 已存在则跳过
    cluster_id = payload.get("cluster_id")
    thesis_id = f"mapper:{cluster_id}" if cluster_id else None
    if thesis_id:
        existing = await session.scalar(
            select(ThesisCard).where(ThesisCard.thesis_id == thesis_id)
        )
        if existing is not None:
            await session.commit()
            return

    card = _build_thesis_from_mapper(payload)
    if card is None:
        logger.warning(
            "[mapper_thesis] payload 缺 cluster_id 或 target_symbol, 跳过 msg_id=%s", msg_id
        )
        await session.commit()
        return

    session.add(card)
    await session.commit()
    logger.info(
        "[mapper_thesis] ThesisCard 入库 thesis_id=%s symbol=%s msg_id=%s",
        card.thesis_id,
        card.symbol,
        msg_id,
    )
