"""The Mapper — 业绩弹性闸门 + 标的映射（纯规则，无 LLM）。

5 节点流水线（全部同步）：
  load_critic_passed_clusters  →  fetch_revenue_base
  →  compute_elasticity  →  segment_filter  →  emit_thesis_proposed

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04_利润截留扫描仪剧本.md §3.5.4 M1~M7]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

_THRESHOLDS_PATH = Path(__file__).parent.parent.parent / "configs" / "elasticity_thresholds.yaml"

# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class CriticCluster:
    """从 evidence_records 加载的 Critic 通过簇。"""

    evidence_id: int
    symbol: str
    scan_id: str
    cluster_id: str
    capacity_elasticity_ratio: Optional[float]
    raw: dict


@dataclass
class MapperCandidate:
    """中间处理结果。"""

    cluster: CriticCluster
    trailing_12m_revenue: Optional[float]
    elasticity_ratio: Optional[float]
    market_cap_yuan: Optional[float]
    market_cap_tier: str
    status: str  # "proposed" | "dropped" | "pending_elasticity"
    dropped_reason: Optional[str]
    target_symbol: Optional[str]
    reasons: dict = field(default_factory=dict)


@dataclass
class MapperRunResult:
    """Mapper 整体运行结果。"""

    symbol: str
    scan_date: str
    total_clusters: int
    proposed: int
    dropped: int
    pending: int
    candidates: list[MapperCandidate]
    events_emitted: int
    local_queue_pending: int


# ---------------------------------------------------------------------------
# 阈值加载（配置驱动，禁止代码硬编码）
# ---------------------------------------------------------------------------


def load_elasticity_thresholds(path: str | Path | None = None) -> dict:
    """加载 elasticity_thresholds.yaml；文件不存在则抛 FileNotFoundError（yaml 缺失不准出）。"""
    p = Path(path or _THRESHOLDS_PATH)
    if not p.exists():
        raise FileNotFoundError(
            f"elasticity_thresholds.yaml 不存在: {p}；请先创建配置文件（M2 准出条件）"
        )
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 节点 1：加载 Critic 通过的簇
# ---------------------------------------------------------------------------


def load_critic_passed_clusters(
    symbol: str,
    *,
    session,  # SQLAlchemy sync Session
    scan_id: Optional[str] = None,
) -> list[CriticCluster]:
    """从 evidence_records 查 physical_gate=True 的物理证伪记录。

    M1: 只有 physical_gate=True 的 cluster 才能进入 Mapper。
    """
    from sqlalchemy import select

    from apps.deep_strike.db.models import EvidenceRecord

    stmt = (
        select(EvidenceRecord)
        .where(
            EvidenceRecord.symbol == symbol,
            EvidenceRecord.evidence_type == "physical",
            EvidenceRecord.physical_gate.is_(True),
        )
        .order_by(EvidenceRecord.created_at.desc())
    )
    if scan_id:
        stmt = stmt.where(EvidenceRecord.scan_id == scan_id)

    rows = session.scalars(stmt).all()
    clusters: list[CriticCluster] = []
    for r in rows:
        raw = r.raw or {}
        cluster_id = raw.get("cluster_id") or (r.source_id or "").replace("critic:", "")
        clusters.append(
            CriticCluster(
                evidence_id=r.id,
                symbol=r.symbol,
                scan_id=r.scan_id,
                cluster_id=cluster_id,
                capacity_elasticity_ratio=raw.get("capacity_elasticity_ratio"),
                raw=raw,
            )
        )
    logger.info("[mapper] symbol=%s critic_passed_clusters=%d", symbol, len(clusters))
    return clusters


# ---------------------------------------------------------------------------
# 节点 2：获取营收基数
# ---------------------------------------------------------------------------


def fetch_revenue_base(
    symbol: str,
    *,
    session,
) -> Optional[float]:
    """查最近一期年报 revenue（trailing 12m）。

    M3: trailing_12m_revenue 用于计算 elasticity_ratio。
    """
    from sqlalchemy import select

    from apps.deep_strike.db.models import FinancialReport

    stmt = (
        select(FinancialReport)
        .where(
            FinancialReport.symbol == symbol,
            FinancialReport.report_type == "annual",
        )
        .order_by(FinancialReport.period_end.desc())
        .limit(1)
    )
    row = session.scalars(stmt).first()
    if row and row.revenue is not None:
        return float(row.revenue)
    return None


# ---------------------------------------------------------------------------
# 节点 3：计算弹性比
# ---------------------------------------------------------------------------


def compute_elasticity(
    cluster: CriticCluster,
    trailing_12m_revenue: Optional[float],
) -> Optional[float]:
    """M3: elasticity_ratio = capacity_elasticity_ratio（已由 Critic 算好）。

    如果 Critic 没有提供弹性比（没有传入 revenue_base + order_size），
    则标记 pending_elasticity（M3 降级路径）。
    """
    ratio = cluster.capacity_elasticity_ratio
    if ratio is not None:
        return float(ratio)
    # Critic 未提供时，尝试从 raw 推断（容错）
    raw = cluster.raw
    order_size = raw.get("candidate_order_size_yuan")
    if order_size is not None and trailing_12m_revenue and trailing_12m_revenue > 0:
        return float(order_size) / float(trailing_12m_revenue)
    return None


# ---------------------------------------------------------------------------
# 节点 4：市值分层过滤
# ---------------------------------------------------------------------------


def _estimate_market_cap(symbol: str, session) -> Optional[float]:
    """尝试从 financial_indicators.raw 获取市值（total_market_cap 字段，元）。

    启动期允许降级：若 raw 无该字段，返回 None（由外层取 mid_cap 作为默认档）。
    """
    from sqlalchemy import select

    from apps.deep_strike.db.models import FinancialIndicator

    stmt = (
        select(FinancialIndicator)
        .where(FinancialIndicator.symbol == symbol)
        .order_by(FinancialIndicator.period_end.desc())
        .limit(1)
    )
    row = session.scalars(stmt).first()
    if row:
        raw = row.raw or {}
        mc = raw.get("total_market_cap") or raw.get("market_cap")
        if mc is not None:
            return float(mc)
        # 尝试用 PE × net_profit 粗估市值（单位：元）
        if row.pe and row.raw:
            net_profit = row.raw.get("net_profit")
            if net_profit and row.pe > 0:
                return float(row.pe) * float(net_profit)
    return None


def _classify_market_cap(market_cap_yuan: Optional[float], thresholds: dict) -> str:
    """将市值映射到 4 档市值段标签。

    若市值未知，默认 mid_cap（启动期标的池较小，保守起见用 mid_cap 阈值）。
    """
    if market_cap_yuan is None:
        return "mid_cap"
    tiers = thresholds.get("tiers", {})
    order = ["small_cap", "mid_cap", "large_cap", "extra_large"]
    for name in order:
        cfg = tiers.get(name, {})
        max_mc = cfg.get("max_market_cap_yuan")
        if max_mc is None or market_cap_yuan < max_mc:
            return name
    return "extra_large"


def segment_filter(
    cluster: CriticCluster,
    elasticity_ratio: Optional[float],
    trailing_12m_revenue: Optional[float],
    *,
    symbol: str,
    session,
    thresholds: dict,
) -> MapperCandidate:
    """M2/M4/M5: 弹性阈值过滤 + 稀释型大盘排雷 + 标的映射（简化）。"""
    market_cap_yuan = _estimate_market_cap(symbol, session)
    tier = _classify_market_cap(market_cap_yuan, thresholds)
    tier_cfg = thresholds.get("tiers", {}).get(tier, {})
    min_elasticity = tier_cfg.get("min_elasticity", 0.05)
    dilution_guard = tier_cfg.get("dilution_guard", False)

    reasons: dict[str, Any] = {
        "market_cap_tier": tier,
        "min_elasticity_threshold": min_elasticity,
        "actual_elasticity_ratio": elasticity_ratio,
        "market_cap_yuan": market_cap_yuan,
        "trailing_12m_revenue": trailing_12m_revenue,
    }

    # 弹性比未知 → pending_elasticity（M3 降级，不入 mapper_outputs 正式记录）
    if elasticity_ratio is None:
        return MapperCandidate(
            cluster=cluster,
            trailing_12m_revenue=trailing_12m_revenue,
            elasticity_ratio=None,
            market_cap_yuan=market_cap_yuan,
            market_cap_tier=tier,
            status="pending_elasticity",
            dropped_reason="no_elasticity_data",
            target_symbol=None,
            reasons=reasons,
        )

    # M4: extra_large 稀释排雷
    if dilution_guard and elasticity_ratio < min_elasticity:
        reasons["dropped_reason"] = "base_dilution"
        return MapperCandidate(
            cluster=cluster,
            trailing_12m_revenue=trailing_12m_revenue,
            elasticity_ratio=elasticity_ratio,
            market_cap_yuan=market_cap_yuan,
            market_cap_tier=tier,
            status="dropped",
            dropped_reason="base_dilution",
            target_symbol=None,
            reasons=reasons,
        )

    # 弹性不达标 → drop
    if elasticity_ratio < min_elasticity:
        reasons["dropped_reason"] = "elasticity_below_threshold"
        return MapperCandidate(
            cluster=cluster,
            trailing_12m_revenue=trailing_12m_revenue,
            elasticity_ratio=elasticity_ratio,
            market_cap_yuan=market_cap_yuan,
            market_cap_tier=tier,
            status="dropped",
            dropped_reason="elasticity_below_threshold",
            target_symbol=None,
            reasons=reasons,
        )

    # M5: 标的映射（启动期：cluster → 来源标的本身，不强制龙头映射）
    # 启动期允许 1 cluster → 1 symbol（M5 ⚠️ 降级）
    target_symbol = cluster.symbol
    reasons["target_symbol_note"] = "startup_phase: cluster→source_symbol（非龙头映射）"

    return MapperCandidate(
        cluster=cluster,
        trailing_12m_revenue=trailing_12m_revenue,
        elasticity_ratio=elasticity_ratio,
        market_cap_yuan=market_cap_yuan,
        market_cap_tier=tier,
        status="proposed",
        dropped_reason=None,
        target_symbol=target_symbol,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# 节点 5：持久化 + 发布事件
# ---------------------------------------------------------------------------


def emit_thesis_proposed(
    candidate: MapperCandidate,
    *,
    session,
    publisher,
    scan_date: str,
) -> Optional[str]:
    """持久化 MapperOutput 并向 Redis Stream 投递 mapper_thesis_proposed 事件。

    M6: 每条 target_symbol 非空 → 投递 events:deep_strike:thesis_proposed。
    M7: 不含 buy/execute 字段。
    """
    from apps.deep_strike.db.models import MapperOutput

    row = MapperOutput(
        scan_id=candidate.cluster.scan_id,
        symbol=candidate.cluster.symbol,
        cluster_id=candidate.cluster.cluster_id,
        target_symbol=candidate.target_symbol,
        elasticity_ratio=candidate.elasticity_ratio,
        market_cap_tier=candidate.market_cap_tier,
        status=candidate.status,
        reasons_json=candidate.reasons,
    )
    session.add(row)
    session.flush()

    if candidate.status != "proposed" or candidate.target_symbol is None:
        return None

    msg_id = publisher.publish_mapper_thesis(
        cluster_id=candidate.cluster.cluster_id,
        symbol=candidate.cluster.symbol,
        target_symbol=candidate.target_symbol,
        elasticity_ratio=candidate.elasticity_ratio or 0.0,
        market_cap_tier=candidate.market_cap_tier,
        scan_date=scan_date,
        mapper_output_id=row.id,
    )
    return msg_id


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run_mapper(
    symbol: str,
    *,
    session,
    publisher,
    thresholds_path: str | Path | None = None,
    scan_id: Optional[str] = None,
) -> MapperRunResult:
    """对单个 symbol 跑完整 5 节点 Mapper 流水线。

    Args:
        symbol: 标的代码。
        session: SQLAlchemy 同步 Session。
        publisher: RedisPublisher 实例（可注入 mock）。
        thresholds_path: elasticity_thresholds.yaml 路径（None 用默认）。
        scan_id: 指定扫描批次（None 读所有）。
    """
    scan_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    thresholds = load_elasticity_thresholds(thresholds_path)

    # 节点 1: 加载 Critic 通过簇
    clusters = load_critic_passed_clusters(symbol, session=session, scan_id=scan_id)

    if not clusters:
        logger.info("[mapper] symbol=%s 无 Critic 通过簇，跳过", symbol)
        return MapperRunResult(
            symbol=symbol,
            scan_date=scan_date,
            total_clusters=0,
            proposed=0,
            dropped=0,
            pending=0,
            candidates=[],
            events_emitted=0,
            local_queue_pending=publisher.pending_count,
        )

    # 节点 2: 营收基数
    revenue_base = fetch_revenue_base(symbol, session=session)

    candidates: list[MapperCandidate] = []
    events_emitted = 0

    for cluster in clusters:
        # 节点 3: 计算弹性比
        elasticity = compute_elasticity(cluster, revenue_base)

        # 节点 4: 市值分层过滤
        candidate = segment_filter(
            cluster,
            elasticity,
            revenue_base,
            symbol=symbol,
            session=session,
            thresholds=thresholds,
        )
        candidates.append(candidate)

        # 节点 5: 持久化 + 发布事件
        emit_thesis_proposed(
            candidate,
            session=session,
            publisher=publisher,
            scan_date=scan_date,
        )
        if candidate.status == "proposed" and candidate.target_symbol:
            events_emitted += 1

    session.commit()

    proposed = sum(1 for c in candidates if c.status == "proposed")
    dropped = sum(1 for c in candidates if c.status == "dropped")
    pending = sum(1 for c in candidates if c.status == "pending_elasticity")

    logger.info(
        "[mapper] symbol=%s total=%d proposed=%d dropped=%d pending=%d events=%d",
        symbol,
        len(candidates),
        proposed,
        dropped,
        pending,
        events_emitted,
    )
    return MapperRunResult(
        symbol=symbol,
        scan_date=scan_date,
        total_clusters=len(clusters),
        proposed=proposed,
        dropped=dropped,
        pending=pending,
        candidates=candidates,
        events_emitted=events_emitted,
        local_queue_pending=publisher.pending_count,
    )
