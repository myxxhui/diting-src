"""Campaign 服务：建/查/持仓 SoT 导入。

[Ref: 03_/00_维度零/.../step_12_行情解析与规划工作台.md]
[Ref: 24_行情解析与规划工作台_需求实现表.md · 必做②]
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.common.holdings_sot import HoldingEntry, load_holdings_sot
from apps.copilot.db.models import (
    Campaign,
    CampaignNode,
    CampaignSymbol,
    CampaignTimeline,
    MonitorSubscription,
)
from apps.copilot.modules.planning.falsify import (
    compute_readiness,
    ensure_default_falsify_tasks,
    list_falsify_tasks,
    refresh_falsify_verdicts,
)
from apps.copilot.modules.planning.funnel import (
    VIEW_STAGES,
    funnel_symbol_to_dict,
    get_or_create_container,
    list_funnel_symbols,
    set_stage,
    upsert_funnel_symbol,
)
from apps.copilot.modules.planning.monitor import (
    DEFAULT_PILLAR_INDICATORS,
    ensure_three_pillars,
    refresh_verdicts,
)
from apps.copilot.modules.planning.schema import CampaignCreate
from apps.copilot.services.redis_wait import wait_for_sync_redis


async def list_campaigns(
    session: AsyncSession,
    *,
    view: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(Campaign)
        .options(selectinload(Campaign.symbols), selectinload(Campaign.nodes))
        .order_by(Campaign.id)
    )
    out: list[dict[str, Any]] = []
    for c in rows:
        out.append(_campaign_to_dict(c, include_nodes=True))
    return out


async def list_workspace_symbols(
    session: AsyncSession,
    *,
    view: str,
) -> list[dict[str, Any]]:
    """标的级漏斗视图：按 funnel_stage 过滤同一批标的（四区联动单一真相）。

    view ∈ {radar, planning, executing, archived}。每只标的只出现在其当前所属区。
    """
    stages = VIEW_STAGES.get(view)
    rows = await list_funnel_symbols(session, stages=stages)
    container = await get_or_create_container(session)
    out = [{**funnel_symbol_to_dict(s), "container_id": container.id} for s in rows]
    if view == "executing":
        from apps.copilot.modules.executing.symbol_base import load_symbol_base

        merged: list[dict[str, Any]] = []
        for item in out:
            sym = item.get("symbol") or ""
            base = await load_symbol_base(session, sym)
            merged.append({**item, **{k: v for k, v in base.items() if k != "symbol"}})
        return merged
    return out


async def list_timeline_entries(
    session: AsyncSession,
    *,
    campaign_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    q = (
        select(CampaignTimeline, Campaign.theme)
        .join(Campaign, Campaign.id == CampaignTimeline.campaign_id)
        .order_by(CampaignTimeline.anchor_date)
    )
    if campaign_id is not None:
        q = q.where(CampaignTimeline.campaign_id == campaign_id)
    rows = await session.execute(q)
    return [
        {
            "id": tl.id,
            "campaign_id": tl.campaign_id,
            "campaign_theme": theme,
            "anchor_date": tl.anchor_date.isoformat(),
            "title": tl.title,
            "kind": tl.kind,
            "confirm_state": tl.confirm_state,
            "status": tl.status,
        }
        for tl, theme in rows.all()
    ]


async def list_radar_symbols(session: AsyncSession) -> list[dict[str, Any]]:
    """跨 Campaign 汇总标的（行情雷达视图）。"""
    rows = await session.scalars(
        select(CampaignSymbol)
        .options(selectinload(CampaignSymbol.campaign))
        .order_by(CampaignSymbol.symbol)
    )
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for s in rows:
        sym = (s.symbol or "").zfill(6)[-6:]
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(
            {
                "symbol": sym,
                "name": s.name,
                "campaign_id": s.campaign_id,
                "campaign_theme": s.campaign.theme if s.campaign else "",
            }
        )
    return out


async def get_campaign(session: AsyncSession, campaign_id: int) -> Optional[dict[str, Any]]:
    c = await session.scalar(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(
            selectinload(Campaign.symbols),
            selectinload(Campaign.nodes),
            selectinload(Campaign.monitors),
        )
    )
    if c is None:
        return None
    return _campaign_to_dict(c, include_nodes=True, include_monitors=True)


async def create_campaign(
    session: AsyncSession, payload: CampaignCreate
) -> dict[str, Any]:
    c = Campaign(
        theme=payload.theme,
        status=payload.status,
        horizon_to=payload.horizon_to,
        notes=payload.notes,
    )
    session.add(c)
    await session.flush()
    await session.refresh(c, ["symbols"])
    return _campaign_to_dict(c)


async def import_portfolio_to_campaign(
    session: AsyncSession,
    *,
    redis_client: Any = None,
    theme: str | None = None,  # 兼容旧签名，已忽略（统一挂唯一漏斗容器）
) -> dict[str, Any]:
    """把 SoT role=portfolio 标的导入**漏斗容器**，stage=planning + 三支柱 + 证伪。

    标的级漏斗：按 symbol 全局去重 upsert，已存在则补齐订阅，不重复建卡。
    """
    sot = load_holdings_sot()
    portfolio = [h for h in sot.holdings if h.active and h.role == "portfolio"]
    if not portfolio:
        portfolio = [h for h in sot.holdings if h.active]

    container = await get_or_create_container(session)

    added = 0
    seq = await session.scalar(
        select(func.count()).select_from(CampaignNode).where(
            CampaignNode.campaign_id == container.id
        )
    ) or 0
    for entry in portfolio:
        sym = entry.symbol.zfill(6)[-6:]
        existed = await session.scalar(
            select(CampaignSymbol).where(CampaignSymbol.symbol == sym).limit(1)
        )
        await upsert_funnel_symbol(
            session,
            sym,
            entry.name,
            stage="planning",
            is_executing_point=True,
        )
        if not existed:
            session.add(
                CampaignNode(
                    campaign_id=container.id,
                    symbol=sym,
                    seq=seq,
                    name=f"{entry.name} 调研复核",
                    trigger_condition="持仓标的持续监控",
                    advice_action="建议复核标的逻辑与阶段判定（advisory）",
                    execute_mode="advisory",
                    human_confirmation_required=True,
                    status="planning",
                )
            )
            seq += 1
            added += 1
        await ensure_three_pillars(session, container.id, sym)
        await ensure_default_falsify_tasks(session, container.id, sym)

    if added > 0 and not await session.scalar(
        select(CampaignTimeline).where(CampaignTimeline.campaign_id == container.id).limit(1)
    ):
        session.add(
            CampaignTimeline(
                campaign_id=container.id,
                anchor_date=date.today() + timedelta(days=90),
                title="持仓复盘节点",
                kind="plan_gen",
                confirm_state="inferred",
                status="expected",
            )
        )

    if redis_client is None:
        redis_client = wait_for_sync_redis()
    await refresh_verdicts(session, container.id, redis_client)

    await session.commit()
    await session.refresh(container, ["symbols", "nodes", "monitors"])
    return {
        "campaign_id": container.id,
        "theme": container.theme,
        "imported_count": added,
        "total_symbols": len(container.symbols),
        "source": str(sot.source_path),
    }


async def promote_campaign_to_executing(
    session: AsyncSession,
    campaign_id: int,
    *,
    symbol: str | None = None,
    human_confirmed: bool,
    redis_client: Any = None,
) -> dict[str, Any]:
    """规划区人工确认晋级执行：**把标的**从 planning 推进到 executing（advisory）。

    标的级漏斗：晋级作用于单只标的的 funnel_stage，而非整个 campaign。
    未指定 symbol 时晋级该容器下全部 planning/roadmap 标的（批量）。
    """
    if not human_confirmed:
        raise ValueError("human_confirmation_required")
    if redis_client is None:
        redis_client = wait_for_sync_redis()
    await refresh_falsify_verdicts(session, campaign_id, redis_client)

    promoted: list[str] = []
    if symbol:
        sym = symbol.zfill(6)[-6:]
        row = await set_stage(session, sym, "executing")
        if row is None:
            raise ValueError("symbol not found in funnel")
        promoted.append(sym)
    else:
        rows = await list_funnel_symbols(
            session, stages=("roadmap", "planning")
        )
        for r in rows:
            await set_stage(session, r.symbol, "executing")
            promoted.append(r.symbol)

    tasks = await list_falsify_tasks(session, campaign_id, symbol)
    readiness = compute_readiness(tasks)
    await session.flush()
    return {
        "campaign_id": campaign_id,
        "promoted_symbols": promoted,
        "funnel_stage": "executing",
        "readiness": readiness,
        "human_confirmation_required": True,
        "execute_mode": "advisory",
    }


async def list_nodes(session: AsyncSession, campaign_id: int) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(CampaignNode)
        .where(CampaignNode.campaign_id == campaign_id)
        .order_by(CampaignNode.seq)
    )
    return [
        {
            "id": n.id,
            "symbol": n.symbol,
            "seq": n.seq,
            "name": n.name,
            "trigger_condition": n.trigger_condition,
            "advice_action": n.advice_action,
            "execute_mode": n.execute_mode,
            "human_confirmation_required": n.human_confirmation_required,
            "status": n.status,
        }
        for n in rows
    ]


def _campaign_to_dict(
    c: Campaign,
    *,
    include_nodes: bool = False,
    include_monitors: bool = False,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": c.id,
        "theme": c.theme,
        "status": c.status,
        "horizon_to": c.horizon_to.isoformat() if c.horizon_to else None,
        "notes": c.notes,
        "symbols": [
            {
                "id": s.id,
                "symbol": s.symbol,
                "name": s.name,
                "graph_position": s.graph_position,
                "stage": s.stage,
                "is_executing_point": s.is_executing_point,
            }
            for s in (c.symbols or [])
        ],
    }
    if include_nodes:
        d["nodes"] = [
            {
                "id": n.id,
                "symbol": n.symbol,
                "name": n.name,
                "advice_action": n.advice_action,
                "execute_mode": n.execute_mode,
                "status": n.status,
            }
            for n in (c.nodes or [])
        ]
    if include_monitors:
        d["monitors"] = [
            {
                "id": m.id,
                "pillar": m.pillar,
                "symbol": m.symbol,
                "indicator": m.indicator,
                "verdict": m.verdict,
            }
            for m in (c.monitors or [])
        ]
    return d
