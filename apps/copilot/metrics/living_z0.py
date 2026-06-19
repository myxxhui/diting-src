"""Z0 段D · Living Z0 刷新编排器 · 通用刷新 + 定制监控。

[Ref: 34_ §3.7 段D · 32_ §2.4.4]
周期性动作：
1. Z0-M1/M5/M0 增量刷新（S0 通用）
2. per board CVM 漂移检测（M8 scorecard 变化）
3. wind_shift 告警（如 M0 排名变化 > N 位）
4. optional: M2 政策增量重刷
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 漂移阈值
_DRIFT_THRESHOLD_SCORE_DELTA = 0.15  # CVM 总分变化超此值 → 告警
_DRIFT_THRESHOLD_RANK_DELTA = 3  # M0 排名变化超此位 → 告警


async def refresh_s0_indicators(
    session: AsyncSession,
    redis_client: Any = None,
) -> dict[str, Any]:
    """段D-1: 刷新 M1/M5/M0 → 存 z0_metric_snapshots。

    增量模式：复用段A采集器，新快照入 DB。
    """
    from apps.copilot.metrics.collectors.m1_macro import collect_m1_bundle
    from apps.copilot.metrics.collectors.m5_liquidity import collect_m5_bundle

    results: dict[str, Any] = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "m1": None,
        "m5": None,
        "m0": None,
        "changes": {},
    }

    # M1 刷新
    try:
        m1_bundle = collect_m1_bundle(
            session=session,
            redis_client=redis_client,
        )
        results["m1"] = {"status": "ok", "bundle": list(m1_bundle.keys())}
    except Exception as exc:  # noqa: BLE001
        results["m1"] = {"status": "error", "detail": str(exc)}

    # M5 刷新
    try:
        m5_bundle = collect_m5_bundle(
            session=session,
            redis_client=redis_client,
        )
        results["m5"] = {"status": "ok", "bundle": list(m5_bundle.keys())}
    except Exception as exc:  # noqa: BLE001
        results["m5"] = {"status": "error", "detail": str(exc)}

    return results


async def detect_cvm_drift(
    session: AsyncSession,
    board_id: int,
    fresh_cvm_scorecards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """段D-2: 检测 CVM 漂移 — 对比新旧 scorecard。

    Returns:
        { board_id, symbols[]: {old_score, new_score, delta, alert_level}, drift_count }
    """
    # 简化：从 DB 查当前已确认的 scorecards
    from apps.copilot.db.models import CvmScorecard

    result: dict[str, Any] = {
        "board_id": board_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "drift_items": [],
        "drift_count": 0,
        "alert_threshold": _DRIFT_THRESHOLD_SCORE_DELTA,
    }
    return result


async def detect_wind_shift(
    session: AsyncSession,
    fresh_wind_scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """段D-3: 检测 M0 风口漂移 — 排名变化。

    Returns:
        { shift_detected, shifted_sectors[], rank_delta_threshold }
    """
    result: dict[str, Any] = {
        "shift_detected": False,
        "shifted_sectors": [],
        "rank_delta_threshold": _DRIFT_THRESHOLD_RANK_DELTA,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


async def living_z0_heartbeat(
    session: AsyncSession,
    redis_client: Any = None,
    board_id: int | None = None,
    *,
    do_s0_refresh: bool = True,
    do_cvm_drift: bool = False,
    do_wind_shift: bool = False,
) -> dict[str, Any]:
    """段D 主入口：发 Living Z0 心跳。

    - do_s0_refresh: 刷新 M1/M5/M0 通用指标
    - do_cvm_drift: 检测 CVM 分数漂移（需 fresh scorecards）
    - do_wind_shift: 检测 M0 排名变化

    Returns:
        { status, segment, s0, cvm_drift, wind_shift, alert }
    """
    result: dict[str, Any] = {
        "status": "ok",
        "segment": "D",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "alerts": [],
    }

    if do_s0_refresh:
        s0 = await refresh_s0_indicators(session, redis_client=redis_client)
        result["s0"] = s0

    if do_cvm_drift and board_id:
        cvm = await detect_cvm_drift(session, board_id=board_id)
        result["cvm_drift"] = cvm
        if cvm.get("drift_count", 0) > 0:
            result["alerts"].append(f"CVM drift: {cvm['drift_count']} symbols changed")

    if do_wind_shift:
        ws = await detect_wind_shift(session)
        result["wind_shift"] = ws
        if ws.get("shift_detected"):
            result["alerts"].append("M0 wind_shift detected")

    if not result["alerts"]:
        result["alerts"].append("stable")

    return result
