"""Planning 工作区：全局上下文感知动态探针沙盒（One-Shot Batching）。"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.common.ai_dispatcher import AIDispatcher
from apps.copilot.db.models import AssetState, ProbeResult, ProbeTask, RadarCandidate
from apps.copilot.modules.planning.sandbox_schema import (
    AssetSandboxOut,
    OneShotDeductionOutput,
    OneShotPlanningOutput,
)

PLANNING_SYSTEM_PROMPT = (
    "你是一名服务于顶尖游资的量化基本面架构师。我将提供一个标的的核心逻辑，以及上游雷达的初评结果。"
    "你必须进行全局视野统筹，一次性输出一个包含多条探针的【数据采集开发蓝图矩阵】。"
    "强制覆盖五个标准维度：宏观政策与产业周期、上游供给与成本约束、下游需求与资本开支、"
    "微观高频与财务印证、竞争格局与壁垒探测。每个维度至少一条探针，且不可冗余重复。"
    "只输出 JSON，不要 markdown 代码块。"
)

DEDUCTION_SYSTEM_PROMPT = (
    "你是一名首席量化策略分析师。我将提供一个标的最初的核心投资逻辑，以及五大官方维度探针提炼后的全量真实数据快照。"
    "请交叉验证并寻找矛盾点，研判最初逻辑是否被证伪，并输出结构化决策建议。"
    "只输出 JSON，不要 markdown 代码块。"
)

_DIM_RULES = {
    "macro_policy_cycle": ("宏观", "政策", "产业周期", "发改委", "招标"),
    "upstream_supply_cost": ("上游", "供给", "成本", "lme", "海关"),
    "downstream_demand_capex": ("下游", "需求", "capex", "云厂商", "资本开支"),
    "micro_highfreq_financial": ("微观", "高频", "财务", "月度营收", "出口额"),
    "competition_moat": ("竞争", "壁垒", "专利", "竞对", "扩产"),
}


def _extract_json(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        l, r = s.find("{"), s.rfind("}")
        if l >= 0 and r > l:
            return json.loads(s[l : r + 1])
        raise


def _default_core_logic(symbol: str, radar_initial_analysis: dict | None) -> str:
    base = (radar_initial_analysis or {}).get("overall", {}).get("conclusion")
    if base:
        return str(base)
    return f"{symbol} 的核心逻辑待补充：请基于雷达初评与官方数据验证产业逻辑闭环。"


async def _latest_radar_initial(session: AsyncSession, symbol: str) -> dict[str, Any]:
    row = await session.scalar(
        select(RadarCandidate)
        .where(RadarCandidate.symbol == symbol)
        .order_by(RadarCandidate.id.desc())
        .limit(1)
    )
    if row is None:
        return {}
    raw = row.raw_json or {}
    return {
        "name": row.name,
        "symbol": row.symbol,
        "industry": row.industry,
        "concept": row.concept,
        "confidence": row.confidence,
        "deep_analysis": raw.get("deep_analysis") or {},
    }


async def get_or_create_asset_state(
    session: AsyncSession,
    symbol: str,
    *,
    core_logic: str | None = None,
) -> AssetState:
    sym = symbol.zfill(6)[-6:]
    row = await session.scalar(
        select(AssetState)
        .where(AssetState.symbol_code == sym)
        .options(selectinload(AssetState.probes).selectinload(ProbeTask.result))
    )
    if row:
        if core_logic:
            row.core_logic = core_logic.strip()
        if not row.radar_initial_analysis:
            row.radar_initial_analysis = await _latest_radar_initial(session, sym)
        return row
    radar_initial = await _latest_radar_initial(session, sym)
    row = AssetState(
        id=str(uuid4()),
        symbol_code=sym,
        status="planning",
        core_logic=(core_logic or _default_core_logic(sym, radar_initial)).strip(),
        radar_initial_analysis=radar_initial,
    )
    session.add(row)
    await session.flush()
    return row


def _planning_user_payload(asset: AssetState) -> dict[str, Any]:
    return {
        "symbol_code": asset.symbol_code,
        "core_logic": asset.core_logic,
        "radar_initial_analysis": asset.radar_initial_analysis or {},
        "output_schema": {
            "probes": [
                {
                    "dimension": "维度 3：下游需求与资本开支",
                    "target_data_desc": "北美四大云厂商季报中的 Capex 资本开支指引",
                    "primary_source_name": "SEC EDGAR 数据库或各巨头 IR 官网",
                    "why_this_source": "全球产业链最终买单方，Capex绝对值是印钞机上限。",
                    "alternative_sources": ["北美投行 Earnings Call 纪要"],
                    "collection_guidance": "在 Request Header 中加合规 User-Agent 拉取 10-Q。",
                    "falsification_logic": "任意两家巨头下季度 Capex 增速放缓，证伪高增长逻辑。",
                }
            ]
        },
    }


async def one_shot_plan_probes(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """单次全局规划：1 次 Opus 输出全部探针蓝图并批量入库。"""
    asset = await get_or_create_asset_state(session, symbol)
    dispatcher = AIDispatcher.default()
    messages = [
        {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(_planning_user_payload(asset), ensure_ascii=False)},
    ]
    ai = dispatcher.call(
        "radar_assess",
        messages,
        max_tokens=3200,
        temperature=0.15,
        model_override="claude-opus-4-6",
    )
    parsed = OneShotPlanningOutput.model_validate(_extract_json(ai.text))
    if len(parsed.probes) < 5:
        raise ValueError("one-shot planning 返回探针不足 5 条")
    covered: set[str] = set()
    for probe in parsed.probes:
        d = (probe.dimension + " " + probe.target_data_desc).lower()
        for dim_key, kws in _DIM_RULES.items():
            if any(k.lower() in d for k in kws):
                covered.add(dim_key)
    if len(covered) < 5:
        raise ValueError(f"one-shot planning 维度覆盖不足，当前={sorted(covered)}")

    # 重建该标的探针任务（按一次规划快照覆盖）
    for p in list(asset.probes or []):
        await session.delete(p)
    await session.flush()

    for probe in parsed.probes:
        session.add(
            ProbeTask(
                id=str(uuid4()),
                asset_id=asset.id,
                probe_blueprint=probe.model_dump(mode="json"),
                status="pending_code",
            )
        )
    snapshot = {
        "model": ai.model,
        "tokens_in": ai.tokens_in,
        "tokens_out": ai.tokens_out,
        "cost_yuan_est": ai.cost_yuan_est,
        "probe_count": len(parsed.probes),
    }
    ria = dict(asset.radar_initial_analysis or {})
    ria["sandbox_planning_snapshot"] = snapshot
    asset.radar_initial_analysis = ria
    await session.flush()
    return snapshot


async def update_probe_result(
    session: AsyncSession,
    probe_task_id: str,
    refined_data: dict[str, Any],
) -> ProbeTask:
    task = await session.scalar(
        select(ProbeTask).where(ProbeTask.id == probe_task_id).options(selectinload(ProbeTask.result))
    )
    if task is None:
        raise ValueError("probe_task not found")
    if task.result is None:
        task.result = ProbeResult(
            id=str(uuid4()),
            probe_task_id=task.id,
            refined_data=refined_data or {},
        )
    else:
        task.result.refined_data = refined_data or {}
    task.status = "data_ready"
    await session.flush()
    return task


def _deduction_payload(asset: AssetState, probes: list[ProbeTask]) -> dict[str, Any]:
    return {
        "symbol_code": asset.symbol_code,
        "core_logic": asset.core_logic,
        "all_probe_snapshots": [
            {
                "probe_id": p.id,
                "blueprint": p.probe_blueprint,
                "refined_data": (p.result.refined_data if p.result else {}),
            }
            for p in probes
        ],
        "output_schema": {
            "cross_validation_analysis": "string",
            "falsified_flag": False,
            "final_recommendation": "string",
        },
    }


async def one_shot_global_deduction(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """单次全局推演：全部 probe data_ready 后，1 次 Opus 最终裁决。"""
    sym = symbol.zfill(6)[-6:]
    asset = await session.scalar(
        select(AssetState)
        .where(AssetState.symbol_code == sym)
        .options(selectinload(AssetState.probes).selectinload(ProbeTask.result))
    )
    if asset is None:
        raise ValueError("asset_state not found")
    probes = list(asset.probes or [])
    if not probes:
        raise ValueError("no probes for asset")
    if any(p.status != "data_ready" for p in probes):
        raise ValueError("not all probes are data_ready")

    dispatcher = AIDispatcher.default()
    messages = [
        {"role": "system", "content": DEDUCTION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(_deduction_payload(asset, probes), ensure_ascii=False)},
    ]
    ai = dispatcher.call(
        "radar_assess",
        messages,
        max_tokens=2200,
        temperature=0.1,
        model_override="claude-opus-4-6",
    )
    parsed = OneShotDeductionOutput.model_validate(_extract_json(ai.text))
    snapshot = {
        "model": ai.model,
        "tokens_in": ai.tokens_in,
        "tokens_out": ai.tokens_out,
        "cost_yuan_est": ai.cost_yuan_est,
        **parsed.model_dump(mode="json"),
    }
    ria = dict(asset.radar_initial_analysis or {})
    ria["sandbox_deduction_snapshot"] = snapshot
    asset.radar_initial_analysis = ria
    asset.status = "discarded" if parsed.falsified_flag else "executing"
    await session.flush()
    return snapshot


async def get_asset_sandbox(session: AsyncSession, symbol: str) -> AssetSandboxOut:
    asset = await get_or_create_asset_state(session, symbol)
    await session.refresh(asset, ["probes"])
    probes = await session.scalars(
        select(ProbeTask)
        .where(ProbeTask.asset_id == asset.id)
        .options(selectinload(ProbeTask.result))
        .order_by(ProbeTask.created_at.asc())
    )
    probe_rows = list(probes)
    ria = asset.radar_initial_analysis or {}
    return AssetSandboxOut(
        asset_id=asset.id,
        symbol_code=asset.symbol_code,
        status=asset.status,  # type: ignore[arg-type]
        core_logic=asset.core_logic or "",
        radar_initial_analysis=ria,
        planning_snapshot=ria.get("sandbox_planning_snapshot"),
        deduction_snapshot=ria.get("sandbox_deduction_snapshot"),
        probes=[
            {
                "id": p.id,
                "asset_id": p.asset_id,
                "status": p.status,  # type: ignore[arg-type]
                "probe_blueprint": p.probe_blueprint or {},
                "refined_data": p.result.refined_data if p.result else None,
            }
            for p in probe_rows
        ],
        all_data_ready=bool(probe_rows) and all(p.status == "data_ready" for p in probe_rows),
    )
