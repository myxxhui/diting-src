"""证据链 4 段流水线：采集 → 计算 → 时序对比 → 同业对比 → 物理证伪。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_03_证据链构建器.md]
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from statistics import median
from typing import TYPE_CHECKING, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.deep_strike.db.models import (
    Announcement,
    EvidenceRecord,
    FinancialIndicator,
    IndustryPeer,
)
from apps.deep_strike.engines.evidence_models import Evidence, EvidenceChain, EvidenceType

if TYPE_CHECKING:
    from apps.deep_strike.lighthouse.critic import TheCritic
    from apps.deep_strike.lighthouse.schemas import CriticInput, CriticOutput

logger = logging.getLogger(__name__)

HISTORY_QUARTERS = 8


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


class EvidenceChainBuilder:
    """4 段流水线核心。不做任何买入决策；仅返回结构化证据。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(
        self,
        symbol: str,
        scan_id: str | None = None,
        *,
        critic_inputs: "Sequence[CriticInput] | None" = None,
        critic: "TheCritic | None" = None,
    ) -> EvidenceChain:
        """构建证据链。

        Args:
            symbol: 标的代码。
            scan_id: 扫描批次号；缺省按当日 UTC `YYYYMMDD`。
            critic_inputs: 可选，Lighthouse-Alpha [L-α] 嗅探候选簇上下文；每个 CriticInput
                对应一个 sniffer_cluster，会调 The Critic 产出 type=PHYSICAL 的证据入链。
            critic: 注入的 TheCritic 实例；与 ``critic_inputs`` 同时给定才会启用。
                测试可注入 mock dispatcher 的 TheCritic 跳过远程调用。

        L3 §3.5.4 LC1：每条 sniffer_cluster 产出一条 type=physical 的 evidence；
        physical_gate 字段由 from_critic_output() 编码到 content/confidence 中。
        """
        sid = scan_id or datetime.now(timezone.utc).strftime("%Y%m%d")
        logger.info("[evidence] build start symbol=%s scan_id=%s", symbol, sid)
        ind_rows, ann_rows, peer_rows = await self._collect_raw(symbol)

        items: list[Evidence] = []
        items.extend(self._compute_metrics(symbol, ind_rows))
        items.extend(self._compare_timeseries(symbol, ind_rows))
        items.extend(self._compare_industry(symbol, ind_rows, peer_rows))
        items.extend(self._from_announcements(symbol, ann_rows))

        critic_evidence_count = 0
        if critic_inputs and critic is not None:
            critic_evidence_count = self._append_critic_evidence(
                symbol=symbol,
                items=items,
                critic_inputs=critic_inputs,
                critic=critic,
            )

        items = self._dedup(items)
        items = [
            e for e in items
            if e.type == EvidenceType.PHYSICAL or len(e.content) >= 50
        ]

        if len(items) < 3:
            raise ValueError(
                f"{symbol} 证据不足 {len(items)}/3（禁止 padding 降级）；请先跑 deep-step02 采集"
            )

        await self._persist(symbol, sid, items)

        chain = EvidenceChain(
            symbol=symbol,
            items=items[:12],
            industry_compared=bool(peer_rows and self._peer_has_gm(peer_rows)),
            timeseries_window_quarters=min(len(ind_rows), HISTORY_QUARTERS),
        )
        logger.info(
            "[evidence] build done symbol=%s scan_id=%s count=%s critic_evidence=%s",
            symbol,
            sid,
            len(chain.items),
            critic_evidence_count,
        )
        return chain

    def _append_critic_evidence(
        self,
        *,
        symbol: str,
        items: list[Evidence],
        critic_inputs: "Sequence[CriticInput]",
        critic: "TheCritic",
    ) -> int:
        """对每个 sniffer_cluster 调 The Critic，入链 PHYSICAL 证据。

        失败（pending_critic）按 L3 §3.5.4 LC1 处理：标记 confidence=0.0 仍入库，
        交由下游 step_04 The Mapper 用 `WHERE physical_gate = true` 过滤。
        """
        appended = 0
        for ci in critic_inputs:
            try:
                critic_out = critic.call(ci)
            except Exception as exc:  # pragma: no cover - dispatch 已有 fallback，此处兜底
                logger.warning(
                    "[critic] cluster_id=%s symbol=%s critic.call 抛错: %s",
                    ci.cluster_id,
                    symbol,
                    exc,
                )
                continue
            try:
                evidence = self.from_critic_output(critic_out)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "[critic] cluster_id=%s from_critic_output 失败: %s",
                    ci.cluster_id,
                    exc,
                )
                continue
            items.append(evidence)
            appended += 1
            logger.info(
                "[critic] cluster_id=%s symbol=%s physical_gate=%s reason=%s",
                ci.cluster_id,
                symbol,
                critic_out.physical_gate,
                critic_out.falsified_reason,
            )
        return appended

    @staticmethod
    def _peer_has_gm(peer_rows: Sequence[IndustryPeer]) -> bool:
        for p in peer_rows:
            snap = p.peer_metric_snapshot or {}
            v = snap.get("gross_margin")
            if isinstance(v, (int, float)):
                return True
        return False

    async def _collect_raw(
        self, symbol: str
    ) -> tuple[list[FinancialIndicator], list[Announcement], list[IndustryPeer]]:
        ind_rows = (
            await self.session.scalars(
                select(FinancialIndicator)
                .where(FinancialIndicator.symbol == symbol)
                .order_by(FinancialIndicator.period_end.asc())
            )
        ).all()
        ann_rows = (
            await self.session.scalars(
                select(Announcement)
                .where(Announcement.symbol == symbol)
                .order_by(Announcement.published_at.desc())
            )
        ).all()
        peer_rows = (
            await self.session.scalars(select(IndustryPeer).where(IndustryPeer.symbol == symbol))
        ).all()
        return list(ind_rows), list(ann_rows), list(peer_rows)

    def _compute_metrics(
        self, symbol: str, ind_rows: Sequence[FinancialIndicator]
    ) -> list[Evidence]:
        if not ind_rows:
            return []
        latest = ind_rows[-1]
        out: list[Evidence] = []
        if latest.gross_margin is not None:
            out.append(
                Evidence(
                    type=EvidenceType.FINANCIAL,
                    source=f"financial_indicators#{latest.period}",
                    source_id=f"fin:{latest.id}" if getattr(latest, "id", None) else f"fin:{latest.period}",
                    content=(
                        f"标的 {symbol} · {latest.period} 销售毛利率 {_pct(latest.gross_margin)}，"
                        f"环比 {_pct(latest.gross_margin_qoq)}，"
                        f"同比 {_pct(latest.gross_margin_yoy)}（来源：财务指标表，供证据链引用）"
                    ),
                    evidence_date=latest.period_end.date() if latest.period_end else None,
                )
            )
        if latest.revenue_growth_yoy is not None and latest.cost_growth_yoy is not None:
            gap = latest.revenue_growth_yoy - latest.cost_growth_yoy
            out.append(
                Evidence(
                    type=EvidenceType.FINANCIAL,
                    source=f"financial_indicators#{latest.period}",
                    content=(
                        f"标的 {symbol} · {latest.period} 营收增速 {_pct(latest.revenue_growth_yoy)} "
                        f"高于成本增速 {_pct(latest.cost_growth_yoy)}，剪刀差 "
                        f"{_pct(gap)}（经营质量对比）"
                    ),
                    evidence_date=latest.period_end.date() if latest.period_end else None,
                )
            )
        if (
            latest.net_profit_growth_yoy is not None
            and latest.revenue_growth_yoy is not None
            and latest.revenue_growth_yoy != 0
        ):
            ratio = latest.net_profit_growth_yoy / max(latest.revenue_growth_yoy, 1e-6)
            out.append(
                Evidence(
                    type=EvidenceType.FINANCIAL,
                    source=f"financial_indicators#{latest.period}",
                    content=(
                        f"标的 {symbol} · {latest.period} 净利润增速 {_pct(latest.net_profit_growth_yoy)} "
                        f"是营收增速的 {ratio:.2f} 倍，经营杠杆显著释放（同比对比）"
                    ),
                    evidence_date=latest.period_end.date() if latest.period_end else None,
                )
            )
        return out

    def _compare_timeseries(
        self, symbol: str, ind_rows: Sequence[FinancialIndicator]
    ) -> list[Evidence]:
        if len(ind_rows) < 4:
            return []
        window = ind_rows[-HISTORY_QUARTERS:]
        gms = [r.gross_margin for r in window if r.gross_margin is not None]
        out: list[Evidence] = []
        if len(gms) >= 4:
            base = gms[0]
            latest = gms[-1]
            delta = latest - base
            out.append(
                Evidence(
                    type=EvidenceType.FINANCIAL,
                    source=f"timeseries#{symbol}",
                    content=(
                        f"近 {len(gms)} 期毛利率由 {_pct(base)} 升至 {_pct(latest)}，"
                        f"提升 {_pct(delta)}（窗口 {window[0].period} → {window[-1].period}）"
                    ),
                    evidence_date=window[-1].period_end.date() if window[-1].period_end else None,
                )
            )
        rec_t = [r.receivable_turnover for r in window if r.receivable_turnover is not None]
        if len(rec_t) >= 4 and rec_t[-1] > rec_t[0]:
            out.append(
                Evidence(
                    type=EvidenceType.FINANCIAL,
                    source=f"timeseries#{symbol}",
                    content=(
                        f"近 {len(rec_t)} 期应收账款周转率由 {rec_t[0]:.2f} 升至 "
                        f"{rec_t[-1]:.2f}，回款效率改善"
                    ),
                    evidence_date=window[-1].period_end.date() if window[-1].period_end else None,
                )
            )
        return out

    def _compare_industry(
        self,
        symbol: str,
        ind_rows: Sequence[FinancialIndicator],
        peer_rows: Sequence[IndustryPeer],
    ) -> list[Evidence]:
        if not ind_rows or not peer_rows:
            return []
        latest = ind_rows[-1]
        if latest.gross_margin is None:
            return []
        peer_gm: list[float] = []
        for p in peer_rows:
            snap = p.peer_metric_snapshot or {}
            v = snap.get("gross_margin")
            if isinstance(v, (int, float)):
                peer_gm.append(float(v))
        if not peer_gm:
            return []
        med = median(peer_gm)
        diff = latest.gross_margin - med
        sign = "高" if diff >= 0 else "低"
        return [
            Evidence(
                type=EvidenceType.INDUSTRY,
                source=f"industry_median#{peer_rows[0].industry_name}",
                content=(
                    f"行业（{peer_rows[0].industry_name}, n={len(peer_gm)}）毛利率中位数 "
                    f"{_pct(med)}，{symbol} 毛利率 {_pct(latest.gross_margin)} "
                    f"{sign}于中位数 {_pct(abs(diff))}"
                ),
                evidence_date=latest.period_end.date() if latest.period_end else None,
            )
        ]

    def _from_announcements(
        self, symbol: str, ann_rows: Sequence[Announcement], top_n: int = 3
    ) -> list[Evidence]:
        out: list[Evidence] = []
        for a in list(ann_rows)[:top_n]:
            body = (a.full_text or a.summary or a.title or "").strip()
            if not body:
                continue
            content = f"标的 {symbol} · 公告 {a.title[:80]}：{body[:400]}"
            out.append(
                Evidence(
                    type=EvidenceType.ANNOUNCEMENT,
                    source=f"announcement#{a.announcement_id}",
                    source_id=f"ann:{a.announcement_id}",
                    content=content,
                    evidence_date=a.published_at.date() if a.published_at else None,
                    url=a.url,
                )
            )
        return out

    @staticmethod
    def _dedup(items: Iterable[Evidence]) -> list[Evidence]:
        seen: set[str] = set()
        out: list[Evidence] = []
        for e in items:
            key = _hash(f"{e.type.value}|{e.source}|{e.content[:120]}")
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    async def _persist(self, symbol: str, scan_id: str, items: Sequence[Evidence]) -> None:
        for idx, e in enumerate(items):
            row = e.to_db_row(symbol, scan_id, idx)
            existing = await self.session.scalar(
                select(EvidenceRecord).where(
                    EvidenceRecord.symbol == symbol,
                    EvidenceRecord.scan_id == scan_id,
                    EvidenceRecord.evidence_idx == idx,
                )
            )
            if existing is None:
                self.session.add(EvidenceRecord(**row))
            else:
                existing.evidence_type = row["evidence_type"]
                existing.source = row["source"]
                existing.source_id = row["source_id"]
                existing.content = row["content"]
                existing.confidence = row["confidence"]
                existing.occurred_at = row["occurred_at"]
                existing.url = row["url"]
        await self.session.commit()

    @staticmethod
    def from_critic_output(critic_out: "CriticOutput") -> Evidence:
        """将 Critic 物理证伪结果转换为 Evidence 对象。

        [Ref: L1 §基石⑥ 物理证伪 ≥ 财务证伪]
        [Ref: 03_/02_维度二/.../step_03 §3.5.4 LC1~LC6]
        """
        gate_status = "通过" if critic_out.physical_gate else "拦截"
        baselines = []
        if critic_out.physical_baseline:
            baselines.append("物理底线✓")
        if critic_out.financial_baseline:
            baselines.append("财务佐证✓")
        if critic_out.commercial_baseline:
            baselines.append("商业闭环✓")
        if critic_out.behavioral_baseline:
            baselines.append("行为佐证✓")

        elasticity_info = ""
        if critic_out.capacity_elasticity_ratio is not None:
            elasticity_info = f"业绩弹性比 {critic_out.capacity_elasticity_ratio:.2%}"
            if not critic_out.capacity_elasticity_ok:
                elasticity_info += "（低于 5% 阈值）"

        reason_info = ""
        if critic_out.falsified_reason:
            reason_info = f"，证伪原因: {critic_out.falsified_reason}"

        quotes_info = ""
        if critic_out.evidence_quotes:
            quotes_info = f"；证据片段: {'; '.join(critic_out.evidence_quotes[:2])}"

        content = (
            f"物理证伪门禁【{gate_status}】· 题材簇 {critic_out.cluster_id}。"
            f"四象限判定: {', '.join(baselines) if baselines else '无佐证'}。"
            f"{elasticity_info}{reason_info}{quotes_info}"
        )

        return Evidence(
            type=EvidenceType.PHYSICAL,
            source=f"critic#{critic_out.cluster_id}",
            source_id=f"critic:{critic_out.cluster_id}",
            content=content[:2048],
            confidence=0.9 if critic_out.physical_gate else 0.5,
            physical_gate=critic_out.physical_gate,
            raw_data={
                "cluster_id": critic_out.cluster_id,
                "physical_gate": critic_out.physical_gate,
                "capacity_elasticity_ratio": critic_out.capacity_elasticity_ratio,
                "capacity_elasticity_ok": critic_out.capacity_elasticity_ok,
                "source_clusters": critic_out.source_clusters,
                "falsified_reason": critic_out.falsified_reason,
            },
        )
