"""执行区仓位指导引擎（T0 规则 + 规划证伪证据 · 全 advisory · 永不下单）。

永久红线：execute_mode='advisory'; human_confirmation_required=1;
schema/模板/路由绝无 buy/qmt/auto_trade/order_id/webhook_target/立即/一键/下单。

[Ref: step_17_执行中仓位指导.md §3 §3.1 §3.2]
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import (
    CampaignSymbol,
    CampaignTimeline,
    ExecutionAdvice,
    StageArtifact,
)
from apps.copilot.modules.planning.falsify import compute_readiness, list_falsify_tasks
from apps.common.holdings_sot import HoldingEntry, load_holdings_sot

logger = logging.getLogger(__name__)

# ── 配置驱动阈值（ConfigMap / env）──────────────────────────────────────
TAKE_PROFIT_PCT = float(os.environ.get("EXEC_PNL_TAKE_PROFIT_PCT", "20"))
STOP_LOSS_PCT = float(os.environ.get("EXEC_PNL_STOP_PCT", "-10"))
MAX_SINGLE_POS_PCT = float(os.environ.get("EXEC_MAX_SINGLE_POS_PCT", "25"))

ADVICE_HOLD = "维持持仓"
ADVICE_BUILD = "建议分批建仓"
ADVICE_ADD = "可考虑加仓"
ADVICE_TRIM = "建议浮盈分批减仓"
ADVICE_LOSS = "逻辑被证伪/破坏，建议评估止损"
ADVICE_EXIT = "重大风险，建议评估清仓"
ADVICE_RISK_HOLD = "风险未排除，暂缓加仓（advisory）"


def _get_holding(symbol: str) -> Optional[HoldingEntry]:
    try:
        sot = load_holdings_sot()
        return sot.by_symbol(symbol)
    except Exception as exc:
        logger.debug("holdings_sot %s: %s", symbol, exc)
        return None


def _fetch_realtime_price(symbol: str, redis_client: Any) -> tuple[float | None, bool]:
    """拉实时价：先 Redis 缓存 → 再 MarketQuoteClient；限流 stale 标注。"""
    try:
        if redis_client is not None:
            raw = redis_client.get(f"quote:rt:{symbol}")
            if raw:
                import json
                d = json.loads(raw)
                price = float(d.get("close") or 0)
                stale = bool(d.get("is_stale", False))
                if price > 0:
                    return price, stale

        from apps.common.market_quote import MarketQuoteClient
        redis_url = os.environ.get("COPILOT_REDIS_URL", "redis://localhost:6379/0")
        client = MarketQuoteClient(redis_url=redis_url)
        quotes = client.get_realtime([symbol])
        q = quotes.get(symbol)
        if q:
            return q.close, q.is_stale
    except Exception as exc:
        logger.debug("realtime price %s: %s", symbol, exc)
    return None, True


async def _safety_status(session: AsyncSession, symbol: str) -> str:
    """调 FinancialFraudEngine 判安全；未就绪 → pending（不拦截不放行）。"""
    try:
        from apps.cryo_guard.engines.financial_fraud.engine import FinancialFraudEngine
        from apps.cryo_guard.engines.financial_fraud.schemas import FraudLabel, RiskLevel

        engine = FinancialFraudEngine(vllm_url=os.environ.get("VLLM_BASE_URL"))
        report = engine.analyze(symbol, "latest")
        if report.history_insufficient or len(report.missing_fields) > 3:
            return "pending"
        if report.label == FraudLabel.FRAUD or report.risk_level == RiskLevel.HIGH:
            return "fraud"
        return "ok"
    except Exception as exc:
        logger.debug("safety scan %s: %s", symbol, exc)
        return "pending"


def _build_advice(
    holding: Optional[HoldingEntry],
    current_price: Optional[float],
    price_stale: bool,
    falsify_tasks: list[dict[str, Any]],
    readiness: dict[str, Any],
    market_phase: Optional[str],
    build_window_ok: bool,
    safety: str,
) -> tuple[str, str, dict[str, Any]]:
    """T0 规则表 → (advice_action, rationale, evidence_chain)。全 advisory。"""
    evidence: dict[str, Any] = {
        "falsify_summary": {
            "ok_rate": readiness.get("ok_rate", 0),
            "falsified": readiness.get("falsified", 0),
            "pending": readiness.get("pending", 0),
        },
        "safety_status": safety,
        "market_phase": market_phase,
        "build_window_ok": build_window_ok,
        "price_stale": price_stale,
    }

    # 1. 严重风险 / fraud → 清仓提示
    if safety == "fraud":
        return (
            ADVICE_EXIT,
            "财务安全扫描发现重大风险（fraud），建议评估清仓（advisory）",
            evidence,
        )

    # 2. 证伪告警 → 逻辑被推翻，止损提示
    falsified = readiness.get("falsified", 0)
    if falsified >= 2:
        return (
            ADVICE_LOSS,
            f"{falsified} 条核心论点被证伪（alert），逻辑破坏，建议评估止损（advisory）",
            evidence,
        )

    # 3. 计算浮盈亏
    unrealized: Optional[float] = None
    if holding and holding.cost_price > 0 and current_price is not None:
        unrealized = (current_price - holding.cost_price) / holding.cost_price * 100

    # 4. 浮盈减仓阈值
    if unrealized is not None and unrealized >= TAKE_PROFIT_PCT:
        trigger = market_phase in ("realization", "exhaustion") if market_phase else False
        if trigger or unrealized >= TAKE_PROFIT_PCT * 1.5:
            return (
                ADVICE_TRIM,
                f"浮盈 {unrealized:.1f}% 已达目标（≥{TAKE_PROFIT_PCT}%），阶段={market_phase}，建议分批减仓锁定（advisory）",
                {**evidence, "unrealized_pnl_pct": unrealized},
            )

    # 5. 浮亏止损阈值
    if unrealized is not None and unrealized <= STOP_LOSS_PCT:
        if falsified >= 1:
            return (
                ADVICE_LOSS,
                f"浮亏 {unrealized:.1f}%（≤{STOP_LOSS_PCT}%）且 {falsified} 条论点被证伪，建议评估止损（advisory）",
                {**evidence, "unrealized_pnl_pct": unrealized},
            )

    # 6. 未持仓 → 建仓建议（须就绪度达标 + 在建仓窗）
    no_position = holding is None or (holding.quantity or 0) <= 0
    if no_position:
        if readiness.get("ready_for_executing") and build_window_ok:
            phase_ok = market_phase not in ("exhaustion",) if market_phase else True
            if phase_ok:
                target = MAX_SINGLE_POS_PCT
                return (
                    f"{ADVICE_BUILD}（目标仓位 ≤{target:.0f}%）",
                    f"证伪就绪度达标（ok_rate={readiness['ok_rate']:.0%}），在建仓窗内，阶段={market_phase}（advisory）",
                    {**evidence, "target_position_pct": target},
                )
        return (
            ADVICE_HOLD,
            "证伪评估未达标或不在建仓窗，维持观察（advisory）",
            evidence,
        )

    # 7. 已持仓加仓（须无 fraud 且证伪 ok）
    if safety == "ok" and readiness.get("ok_rate", 0) >= 0.75 and falsified == 0:
        pos_pct = (holding.quantity or 0) * (current_price or holding.cost_price) / 1e6  # 示意
        if (holding.quantity or 0) > 0:
            if safety != "fraud":
                hint = ADVICE_RISK_HOLD if safety != "ok" else ADVICE_ADD
                return (
                    hint,
                    f"证伪论点成立率 {readiness['ok_rate']:.0%}，阶段={market_phase}，可考虑加仓（注意单一仓位上限 {MAX_SINGLE_POS_PCT}%，advisory）",
                    evidence,
                )

    # 8. 安全扫描 pending + 持仓 → 暂缓加仓但不清仓
    if safety == "pending" and holding and (holding.quantity or 0) > 0:
        return (
            ADVICE_RISK_HOLD,
            "安全扫描结果 pending（LoRA 未就绪），暂缓加仓，维持现有持仓观察（advisory）",
            evidence,
        )

    # 9. 默认持有
    return (
        ADVICE_HOLD,
        f"证伪论点成立率 {readiness.get('ok_rate', 0):.0%}，无显著信号，维持持仓继续监控（advisory）",
        evidence,
    )


async def generate_execution_advice(
    session: AsyncSession,
    campaign_id: int,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any]:
    """生成单标的执行建议快照（T0 + 安全扫描）并写库。"""
    sym = symbol.zfill(6)[-6:]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 持仓 SoT
    holding = _get_holding(sym)

    # 实时价
    current_price, price_stale = _fetch_realtime_price(sym, redis_client)

    # 证伪就绪度
    tasks = await list_falsify_tasks(session, campaign_id, sym)
    readiness = compute_readiness(tasks)

    # 最新建仓窗
    tl_row = await session.scalar(
        select(CampaignTimeline)
        .where(
            CampaignTimeline.campaign_id == campaign_id,
            CampaignTimeline.symbol == sym,
            CampaignTimeline.status == "expected",
        )
        .order_by(CampaignTimeline.anchor_date)
        .limit(1)
    )
    build_window_ok = False
    if tl_row and tl_row.window_start and tl_row.window_end:
        today = datetime.utcnow().date()
        build_window_ok = tl_row.window_start <= today <= tl_row.window_end

    # 市场阶段（从 campaign_symbols analysis_snapshot）
    cs = await session.scalar(
        select(CampaignSymbol).where(
            CampaignSymbol.campaign_id == campaign_id,
            CampaignSymbol.symbol == sym,
        )
    )
    market_phase: Optional[str] = None
    if cs and cs.analysis_snapshot:
        market_phase = (cs.analysis_snapshot.get("assessment") or {}).get(
            "market_phase"
        ) or cs.analysis_snapshot.get("market_phase")

    # 安全扫描（T1 · LoRA）
    safety = await _safety_status(session, sym)

    # 仓位计算
    cost_price = holding.cost_price if holding else None
    quantity = holding.quantity if holding else None
    unrealized_pnl_pct: Optional[float] = None
    if cost_price and cost_price > 0 and current_price:
        unrealized_pnl_pct = (current_price - cost_price) / cost_price * 100
    position_pct: Optional[float] = None
    if holding and quantity and quantity > 0:
        position_pct = min(quantity * (current_price or cost_price or 1) / 1e6 * 100, 100.0)

    # 规则引擎
    advice_action, rationale, evidence_chain = _build_advice(
        holding,
        current_price,
        price_stale,
        tasks,
        readiness,
        market_phase,
        build_window_ok,
        safety,
    )

    # 写 stage_artifacts(workspace=executing)
    session.add(
        StageArtifact(
            symbol=sym,
            workspace="executing",
            stage="execution_advice",
            model_id="code:advisor_t0",
            payload_json={
                "advice_action": advice_action,
                "rationale": rationale,
                "safety_status": safety,
                "readiness": readiness,
                "build_window_ok": build_window_ok,
                "market_phase": market_phase,
            },
        )
    )

    # 写 execution_advices
    row = ExecutionAdvice(
        campaign_id=campaign_id,
        symbol=sym,
        current_price=current_price,
        cost_price=cost_price,
        quantity=quantity,
        position_pct=position_pct,
        unrealized_pnl_pct=unrealized_pnl_pct,
        price_stale=price_stale,
        advice_action=advice_action,
        rationale=rationale,
        evidence_chain=evidence_chain,
        safety_status=safety,
        execute_mode="advisory",
        human_confirmation_required=True,
        as_of=now,
    )
    session.add(row)
    await session.flush()

    return _advice_to_dict(row)


async def list_execution_advices(
    session: AsyncSession,
    campaign_id: int,
    symbol: Optional[str] = None,
) -> list[dict[str, Any]]:
    q = (
        select(ExecutionAdvice)
        .where(ExecutionAdvice.campaign_id == campaign_id)
        .order_by(ExecutionAdvice.as_of.desc())
    )
    if symbol:
        q = q.where(ExecutionAdvice.symbol == symbol.zfill(6)[-6:])
    rows = await session.scalars(q)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.symbol not in seen:
            seen.add(r.symbol)
            out.append(_advice_to_dict(r))
    return out


def _advice_to_dict(r: ExecutionAdvice) -> dict[str, Any]:
    return {
        "id": r.id,
        "campaign_id": r.campaign_id,
        "symbol": r.symbol,
        "current_price": r.current_price,
        "cost_price": r.cost_price,
        "quantity": r.quantity,
        "position_pct": r.position_pct,
        "unrealized_pnl_pct": (
            round(r.unrealized_pnl_pct, 2) if r.unrealized_pnl_pct is not None else None
        ),
        "price_stale": r.price_stale,
        "advice_action": r.advice_action,
        "rationale": r.rationale,
        "evidence_chain": r.evidence_chain,
        "safety_status": r.safety_status,
        "execute_mode": r.execute_mode,
        "human_confirmation_required": r.human_confirmation_required,
        "as_of": r.as_of.isoformat() if r.as_of else None,
    }
