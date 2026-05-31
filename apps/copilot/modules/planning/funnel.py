"""标的级漏斗中枢（四区联动单一真相）。

核心不变量：**一个标的 = 一条 CampaignSymbol 记录**（symbol 全局唯一），
其 `funnel_stage` 是贯穿四区的唯一状态机：

    radar_intake → roadmap → planning → executing → archived

- 所有 funnel 标的挂在唯一容器 Campaign（theme=CONTAINER_THEME）下。
- promote / 晋级 = 推进同一条记录的 funnel_stage（**前向单向**），绝不新建 campaign。
- 四区 Tab 按 funnel_stage 过滤这同一批标的，杜绝重复与视图重叠。

[Ref: 25_四区漏斗_三段流水线_架构脊柱_设计.md · 标的级漏斗重构]
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import Campaign, CampaignSymbol

CONTAINER_THEME = "行情解析漏斗"

FUNNEL_STAGES = ["radar_intake", "roadmap", "planning", "executing", "archived"]
_STAGE_ORDER = {s: i for i, s in enumerate(FUNNEL_STAGES)}

# Tab → 该区展示的 funnel_stage 集合
VIEW_STAGES: dict[str, tuple[str, ...]] = {
    "radar": ("radar_intake",),
    "planning": ("roadmap", "planning"),
    "executing": ("executing",),
    "archived": ("archived",),
}


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().zfill(6)[-6:]


async def get_or_create_container(session: AsyncSession) -> Campaign:
    """唯一漏斗容器 Campaign（所有 funnel 标的的归属）。"""
    camp = await session.scalar(
        select(Campaign).where(Campaign.theme == CONTAINER_THEME).limit(1)
    )
    if camp is None:
        camp = Campaign(
            theme=CONTAINER_THEME,
            status="active",
            funnel_stage="container",
            notes="标的级漏斗唯一容器（四区联动单一真相）",
        )
        session.add(camp)
        await session.flush()
    return camp


async def get_funnel_symbol(
    session: AsyncSession, symbol: str
) -> Optional[CampaignSymbol]:
    sym = normalize_symbol(symbol)
    return await session.scalar(
        select(CampaignSymbol).where(CampaignSymbol.symbol == sym).limit(1)
    )


async def upsert_funnel_symbol(
    session: AsyncSession,
    symbol: str,
    name: str,
    *,
    stage: str = "planning",
    analysis_snapshot: Optional[dict] = None,
    promoted_from_candidate_id: Optional[int] = None,
    is_executing_point: Optional[bool] = None,
) -> CampaignSymbol:
    """按 symbol 全局 find-or-create；存在则更新元数据并**前向推进** stage。

    返回该标的唯一的 funnel 记录。stage 只会前进（不回退），
    除非显式调用 set_stage(allow_backward=True)。
    """
    sym = normalize_symbol(symbol)
    container = await get_or_create_container(session)
    row = await get_funnel_symbol(session, sym)

    if row is None:
        row = CampaignSymbol(
            campaign_id=container.id,
            symbol=sym,
            name=name or sym,
            funnel_stage=stage if stage in _STAGE_ORDER else "planning",
            analysis_snapshot=analysis_snapshot,
            promoted_from_candidate_id=promoted_from_candidate_id,
            is_executing_point=bool(is_executing_point),
        )
        session.add(row)
        await session.flush()
        return row

    # 已存在：更新元数据 + 前向推进 stage
    if name:
        row.name = name
    if analysis_snapshot is not None:
        row.analysis_snapshot = analysis_snapshot
    if promoted_from_candidate_id is not None:
        row.promoted_from_candidate_id = promoted_from_candidate_id
    if is_executing_point is not None:
        row.is_executing_point = is_executing_point
    _advance(row, stage)
    await session.flush()
    return row


def _advance(row: CampaignSymbol, target_stage: str) -> bool:
    """前向单向推进；目标 stage 序号 > 当前才更新。返回是否推进。"""
    if target_stage not in _STAGE_ORDER:
        return False
    cur = _STAGE_ORDER.get(row.funnel_stage or "planning", 0)
    nxt = _STAGE_ORDER[target_stage]
    if nxt > cur:
        row.funnel_stage = target_stage
        return True
    return False


async def set_stage(
    session: AsyncSession,
    symbol: str,
    target_stage: str,
    *,
    allow_backward: bool = False,
) -> Optional[CampaignSymbol]:
    """推进/设置标的 stage。allow_backward 时可回退（如归档后回流路线图）。"""
    if target_stage not in _STAGE_ORDER:
        raise ValueError(f"invalid funnel_stage: {target_stage}")
    row = await get_funnel_symbol(session, symbol)
    if row is None:
        return None
    if allow_backward:
        row.funnel_stage = target_stage
    else:
        _advance(row, target_stage)
    await session.flush()
    return row


async def list_funnel_symbols(
    session: AsyncSession,
    *,
    stages: Optional[tuple[str, ...]] = None,
) -> list[CampaignSymbol]:
    q = select(CampaignSymbol).order_by(CampaignSymbol.symbol)
    if stages:
        q = q.where(CampaignSymbol.funnel_stage.in_(stages))
    rows = await session.scalars(q)
    return list(rows)


def funnel_symbol_to_dict(s: CampaignSymbol) -> dict[str, Any]:
    snap = s.analysis_snapshot or {}
    assessment = snap.get("assessment") if isinstance(snap, dict) else None
    return {
        "id": s.id,
        "campaign_id": s.campaign_id,
        "symbol": s.symbol,
        "name": s.name,
        "funnel_stage": s.funnel_stage,
        "stage": s.stage,
        "is_executing_point": s.is_executing_point,
        "has_snapshot": bool(snap),
        "market_phase": (assessment or {}).get("market_phase") if assessment else None,
        "promoted_from_candidate_id": s.promoted_from_candidate_id,
    }
