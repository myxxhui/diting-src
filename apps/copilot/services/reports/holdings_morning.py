"""W1+W2 合并持仓早报：health 四色 + market_phase 四档 + SoT 持仓.

[Ref: MVP-A health 日报 + MVP-B market_phase]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.common.holdings_sot import HoldingEntry, load_holdings_sot
from apps.copilot.services.reports.base import BaseReportGenerator, ReportContext
from apps.copilot.services.sot_importer import import_sot_holdings
from apps.state_watch.config import settings as sw_settings
from apps.state_watch.db.models import Base as SwBase
from apps.state_watch.db.models import HoldingState, MarketPhaseRecord, NodeSLIValue
from apps.state_watch.health.sli_aggregator import SLIDef, aggregate
from apps.state_watch.market_phase.rules_config import load_rules

log = logging.getLogger(__name__)

PHASE_EMOJI = {
    "concept": "⚪",
    "expectation": "🟡",
    "realization": "🟢",
    "exhaustion": "🔴",
}
COLOR_EMOJI = {0: "🟢", 1: "🟡", 2: "🟠", 3: "🔴"}
COLOR_LABEL = {0: "正常", 1: "关注", 2: "警惕", 3: "高危"}


def health_score_to_push_level(score: float) -> int:
    if score < 40:
        return 3
    if score < 60:
        return 2
    if score < 80:
        return 1
    return 0


@dataclass
class HoldingMorningRow:
    symbol: str
    name: str
    role: str
    health_score: float | None
    push_level: int
    color: str
    market_phase: str | None
    phase_label_zh: str
    phase_confidence: float | None
    reasoning_tags: list[str]
    shares: float
    cost_price: float
    last_close: float | None
    pct_change_1d: float | None
    note: str | None = None

    def sort_key(self) -> tuple[int, float]:
        """health 降序；无数据排后."""
        h = self.health_score if self.health_score is not None else -1.0
        return (self.push_level, h)


class HoldingsMorningBriefGenerator(BaseReportGenerator):
    kind = "holdings_morning"

    def __init__(self, copilot_session: AsyncSession) -> None:
        self.copilot_session = copilot_session
        self._sw_engine = create_async_engine(sw_settings.db_url, echo=False)
        self._sw_factory = async_sessionmaker(self._sw_engine, expire_on_commit=False)

    async def close(self) -> None:
        await self._sw_engine.dispose()

    async def aggregate(self, user_id: str, period_date: date) -> ReportContext:
        await import_sot_holdings(self.copilot_session, user_id=user_id)
        if os.environ.get("MORNING_BRIEF_REFRESH", "1") == "1":
            await self._refresh_state_watch()

        rows = await self._build_rows()
        phase_dist = _phase_distribution(rows)
        color_dist = _color_distribution(rows)
        watchlist = [asdict(r) for r in rows if r.role == "watchlist"]
        portfolio = [asdict(r) for r in rows if r.role == "portfolio"]
        portfolio.sort(key=lambda x: (-x["push_level"], -(x["health_score"] or 0)))
        watchlist.sort(key=lambda x: (-x["push_level"], -(x["health_score"] or 0)))
        focus = _pick_focus(rows)

        labels_zh = load_rules().get("phase_labels_zh") or {}
        payload: dict[str, Any] = {
            "rows": [asdict(r) for r in sorted(rows, key=lambda r: r.sort_key(), reverse=True)],
            "portfolio": portfolio,
            "watchlist": watchlist,
            "phase_distribution": phase_dist,
            "color_distribution": color_dist,
            "phase_labels_zh": labels_zh,
            "focus": focus,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "active_count": len(rows),
        }
        is_demo = all(r.health_score is None for r in rows) and all(
            not r.market_phase for r in rows
        )
        return ReportContext(
            user_id=user_id,
            period_label=period_date.isoformat(),
            period_start=period_date,
            period_end=period_date,
            is_demo=is_demo,
            payload=payload,
        )

    async def _refresh_state_watch(self) -> None:
        """SoT 同步 + 探针 tick + 当日 market_phase（可环境变量跳过）."""
        async with self._sw_engine.begin() as conn:
            await conn.run_sync(SwBase.metadata.create_all)

        try:
            from scripts.watch_step04_run import _ensure_holdings_from_sot, _run_once_all

            await _ensure_holdings_from_sot()
            if os.environ.get("MORNING_BRIEF_RUN_PROBES", "1") == "1":
                await _run_once_all()
        except Exception as exc:
            log.warning("morning brief probe refresh skipped: %s", exc)

        if os.environ.get("MORNING_BRIEF_RUN_PHASE", "1") != "1":
            return
        try:
            from apps.state_watch.market_phase.orchestrator import classify_all_active

            await classify_all_active(publish=False)
        except Exception as exc:
            log.warning("morning brief phase classify skipped: %s", exc)

    async def _build_rows(self) -> list[HoldingMorningRow]:
        sot = load_holdings_sot()
        labels_zh = load_rules().get("phase_labels_zh") or {}
        rows: list[HoldingMorningRow] = []

        async with self._sw_factory() as sw_session:
            holdings_state = {
                h.symbol: h
                for h in (await sw_session.scalars(select(HoldingState))).all()
            }
            for entry in sot.holdings:
                if not entry.active:
                    continue
                sym = entry.symbol.zfill(6)[-6:]
                node = holdings_state.get(sym)
                health, push = await self._health_for_node(sw_session, node)
                phase, conf, tags = await self._phase_for_symbol(sw_session, sym, node)
                last_close, pct_1d = await self._quote_snapshot(sym)
                rows.append(
                    HoldingMorningRow(
                        symbol=sym,
                        name=entry.name or sym,
                        role=entry.role,
                        health_score=health,
                        push_level=push,
                        color=COLOR_LABEL.get(push, "未知"),
                        market_phase=phase,
                        phase_label_zh=labels_zh.get(phase or "", phase or "—"),
                        phase_confidence=conf,
                        reasoning_tags=tags,
                        shares=float(entry.quantity or 0),
                        cost_price=float(entry.cost_price or 0),
                        last_close=last_close,
                        pct_change_1d=pct_1d,
                        note=entry.notes,
                    )
                )
        return rows

    async def _health_for_node(
        self, session: AsyncSession, node: HoldingState | None
    ) -> tuple[float | None, int]:
        if node is None:
            return None, 0
        if node.health_score and node.health_score != 100.0:
            pl = node.push_level if node.push_level else health_score_to_push_level(node.health_score)
            return float(node.health_score), int(pl)
        sli_rows = (
            await session.scalars(
                select(NodeSLIValue).where(NodeSLIValue.holding_id == node.id)
            )
        ).all()
        if not sli_rows:
            return float(node.health_score), int(node.push_level or 0)
        defs = [
            SLIDef(
                id=r.sli_id,
                metric=r.metric,
                threshold=r.threshold,
                operator=r.operator,
                weight=r.weight,
                probe_type=r.probe_type,
                current_value=r.current_value,
            )
            for r in sli_rows
        ]
        score, _ = aggregate(defs)
        return score, health_score_to_push_level(score)

    async def _phase_for_symbol(
        self,
        session: AsyncSession,
        symbol: str,
        node: HoldingState | None,
    ) -> tuple[str | None, float | None, list[str]]:
        if node and node.context:
            ph = node.context.get("market_phase")
            if ph:
                return (
                    str(ph),
                    float(node.context.get("market_phase_confidence") or 0),
                    list(node.context.get("market_phase_reasoning") or []),
                )
        today = date.today().isoformat()
        rec = await session.scalar(
            select(MarketPhaseRecord)
            .where(MarketPhaseRecord.symbol == symbol)
            .where(func.date(MarketPhaseRecord.classified_at) == today)
            .order_by(desc(MarketPhaseRecord.classified_at))
            .limit(1)
        )
        if rec:
            return rec.market_phase, float(rec.confidence), list(rec.reasoning_tags or [])
        return None, None, []

    async def _quote_snapshot(self, symbol: str) -> tuple[float | None, float | None]:
        try:
            from apps.state_watch.probes.price import compute_price_metrics
            from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_60d

            bars = await asyncio.wait_for(asyncio.to_thread(fetch_bars_60d, symbol), timeout=8.0)
            if not bars:
                return None, None
            m = compute_price_metrics(bars)
            return m.get("last_close"), m.get("pct_change_1d")
        except Exception:
            return None, None


def _phase_distribution(rows: list[HoldingMorningRow]) -> dict[str, int]:
    dist = {k: 0 for k in PHASE_EMOJI}
    for r in rows:
        if r.market_phase in dist:
            dist[r.market_phase] += 1
    return dist


def _color_distribution(rows: list[HoldingMorningRow]) -> dict[str, int]:
    dist = {"green": 0, "yellow": 0, "orange": 0, "red": 0}
    for r in rows:
        key = {0: "green", 1: "yellow", 2: "orange", 3: "red"}.get(r.push_level, "green")
        dist[key] += 1
    return dist


def _pick_focus(rows: list[HoldingMorningRow]) -> list[str]:
    lines: list[str] = []
    for r in rows:
        if r.push_level >= 2:
            lines.append(f"{r.name} health={r.health_score or 'N/A'} {COLOR_EMOJI.get(r.push_level,'')}")
        if r.market_phase == "exhaustion":
            lines.append(f"{r.name} 市场阶段=利好透支，建议关注止盈")
    for r in rows:
        if r.health_score is not None and r.health_score < 70 and r.push_level < 2:
            if len(lines) < 5:
                lines.append(f"{r.name} health 偏低 ({r.health_score:.0f})")
    return lines[:6]
