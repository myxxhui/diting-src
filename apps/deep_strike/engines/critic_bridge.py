"""证据链 build 前：从 DB 公告 + SoT segment 构造 CriticInput，供 The Critic 入链。

启动期策略（控制成本）：
  - Sniffer 走 etl/local（不调 Opus）
  - 每标的最多 2 个 cluster 调 Critic（remote 有 key 时；无 key 则 mock 降级）
  - 无公告时用 segment 兜底 1 个 synthetic cluster

[Ref: 03_/02_维度二/.../step_03 §3.5.4 LC1~LC6]
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import date, timedelta
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.deep_strike.db.models import Announcement, FinancialIndicator
from apps.deep_strike.lighthouse import TheCritic, TheSniffer
from apps.deep_strike.lighthouse.schemas import (
    CriticInput,
    SnifferCluster,
    SnifferInput,
)

if TYPE_CHECKING:
    from apps.deep_strike.lighthouse.critic import TheCritic as TheCriticType

logger = logging.getLogger(__name__)

_MAX_CLUSTERS = int(os.getenv("DEEP_STEP03_CRITIC_MAX_CLUSTERS", "1"))
_CRITIC_ENABLED = os.getenv("DEEP_STEP03_CRITIC", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def critic_enabled() -> bool:
    return _CRITIC_ENABLED


def _revenue_base_yuan(ind: FinancialIndicator | None) -> float | None:
    if ind is None or not ind.raw:
        return None
    raw = ind.raw if isinstance(ind.raw, dict) else {}
    for key in ("revenue_yuan", "revenue", "total_revenue", "operating_revenue", "营业收入"):
        v = raw.get(key)
        if isinstance(v, (int, float)) and v > 0:
            val = float(v)
            # 启发式：小于 1e6 可能是「万元」
            if val < 1e6:
                val *= 1e4
            return val
    return None


def _announcement_texts(rows: Sequence[Announcement], limit: int = 12) -> list[str]:
    out: list[str] = []
    for a in rows[:limit]:
        body = (a.full_text or a.summary or a.title or "").strip()
        if body:
            out.append(body[:800])
    return out


def _fallback_cluster(symbol: str, segment: str | None, n_docs: int) -> SnifferCluster:
    keyword = (segment or symbol).strip()
    cid = hashlib.md5(f"{symbol}:{keyword}".encode()).hexdigest()[:12]
    return SnifferCluster(
        cluster_id=cid,
        keyword=keyword,
        summary=f"{keyword} 启动期题材（segment 兜底）",
        freq_growth_pct=0.0,
        confidence=0.4,
        sample_doc_idx=list(range(min(n_docs, 8))),
    )


async def _load_symbol_context(
    session: AsyncSession, symbol: str
) -> tuple[list[str], FinancialIndicator | None]:
    ann_rows = (
        await session.scalars(
            select(Announcement)
            .where(Announcement.symbol == symbol)
            .order_by(Announcement.published_at.desc())
            .limit(12)
        )
    ).all()
    texts = _announcement_texts(list(ann_rows))

    ind = await session.scalar(
        select(FinancialIndicator)
        .where(FinancialIndicator.symbol == symbol)
        .order_by(FinancialIndicator.period_end.desc())
        .limit(1)
    )
    return texts, ind


def _sniffer_clusters(texts: list[str], symbol: str, segment: str | None) -> list[SnifferCluster]:
    if not texts:
        return [_fallback_cluster(symbol, segment, 0)]

    today = date.today()
    sniffer = TheSniffer()
    try:
        out = sniffer.call(
            SnifferInput(
                raw_texts=texts,
                window_start=today - timedelta(days=365),
                window_end=today,
                source_hint="research",
            )
        )
        clusters = list(out.clusters)
    except Exception as exc:
        logger.warning("[critic_bridge] sniffer 失败 symbol=%s: %s", symbol, exc)
        clusters = []

    if not clusters:
        clusters = [_fallback_cluster(symbol, segment, len(texts))]
    return clusters[:_MAX_CLUSTERS]


async def prepare_critic_inputs(
    session: AsyncSession,
    symbol: str,
    *,
    segment: str | None = None,
) -> list[CriticInput]:
    """为单标的构造 CriticInput 列表（供 EvidenceChainBuilder.build 使用）。"""
    if not _CRITIC_ENABLED:
        return []

    texts, ind = await _load_symbol_context(session, symbol)
    revenue_base = _revenue_base_yuan(ind)
    clusters = _sniffer_clusters(texts, symbol, segment)

    inputs: list[CriticInput] = []
    for cluster in clusters:
        sample_idx = cluster.sample_doc_idx or list(range(min(len(texts), 8)))
        sample_texts = [texts[i] for i in sample_idx if 0 <= i < len(texts)]
        if not sample_texts and texts:
            sample_texts = texts[:8]

        inputs.append(
            CriticInput(
                cluster_id=cluster.cluster_id,
                cluster_keyword=cluster.keyword,
                candidate_symbol=symbol,
                candidate_revenue_base_yuan=revenue_base,
                candidate_order_size_yuan=None,
                sample_raw_texts=sample_texts,
            )
        )
    return inputs


def default_critic() -> "TheCriticType":
    return TheCritic()
