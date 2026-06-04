"""T0→T1→T2 三段流水线 + StageArtifact / WorkspaceArtifact 落库。

[Ref: step_14 · 25_ §2/§3]
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import StageArtifact, WorkspaceArtifact
from apps.copilot.modules.radar.context_matrix import build_context_matrix
from apps.copilot.modules.radar.model_router import radar_t2_enabled, resolve_model
from apps.copilot.modules.radar.scanner import collect_t0_raw
from apps.copilot.modules.radar.persistence import load_latest_bundle_db
from apps.copilot.modules.radar.t0_cache import cached_t2_verdict, load_cached
from apps.copilot.modules.radar.t2_resolve import (
    find_ok_t2_verdict,
    find_ok_t2_verdict_db,
)
from apps.copilot.modules.radar.schema import (
    build_opus_messages,
    estimate_cost_yuan,
    parse_opus_verdict,
)

logger = logging.getLogger(__name__)


async def run_radar_pipeline(
    session: AsyncSession,
    *,
    symbol: str,
    name: str = "",
    scan_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
    redis_client: Any = None,
    enable_t2: bool = True,
    force_refresh_t0: bool = False,
    force_refresh_t2: bool = False,
) -> dict[str, Any]:
    """跑完整三段流水线并落库；enable_t2=False 时仅 T0+T1（快速扫描）。"""
    t0_start = time.perf_counter()
    t0_raw = await collect_t0_raw(
        symbol,
        name=name,
        redis_client=redis_client,
        force_refresh=force_refresh_t0,
    )
    t0_art = await _save_artifact(
        session,
        stage="T0_raw",
        model_id="code:t0_collect",
        payload=t0_raw,
        symbol=symbol,
        scan_id=scan_id,
        candidate_id=candidate_id,
        latency_ms=int((time.perf_counter() - t0_start) * 1000),
    )

    t1_start = time.perf_counter()
    t1_profile = resolve_model("radar", "t1_distill")
    cached_t1 = t0_raw.get("t1_distilled") if t0_raw.get("cache_hit") else None
    if isinstance(cached_t1, dict) and cached_t1.get("matrix"):
        t1_payload = cached_t1
    else:
        t1_payload = build_context_matrix(t0_raw)
    t1_art = await _save_artifact(
        session,
        stage="T1_distilled",
        model_id=t1_profile["model_id"],
        payload=t1_payload,
        symbol=symbol,
        scan_id=scan_id,
        candidate_id=candidate_id,
        input_refs=[t0_art.id],
        latency_ms=int((time.perf_counter() - t1_start) * 1000),
    )

    t2_start = time.perf_counter()
    t2_profile = resolve_model("radar", "t2_assess")
    t2_from_cache = False
    if not enable_t2:
        t2_payload = _t2_result(
            status="skipped",
            model_id=str(t2_profile.get("model_id")),
            route="none",
            detail="已关闭深度推理（仅 T0+T1 事实矩阵）",
        )
    else:
        t2_cached = None
        if not force_refresh_t2:
            t2_cached = cached_t2_verdict(t0_raw)
            if not t2_cached:
                t2_cached = cached_t2_verdict(load_cached(symbol, require_fresh=True))
            if not t2_cached:
                t2_cached = cached_t2_verdict(load_cached(symbol, require_fresh=False))
            if not t2_cached:
                db_bundle = await load_latest_bundle_db(session, symbol)
                t2_cached = cached_t2_verdict(db_bundle)
        if t2_cached:
            t2_payload = t2_cached
            logger.info("T2 cache hit symbol=%s model=%s", symbol, t2_payload.get("model_id"))
        else:
            t2_payload = await run_t2_live(t1_payload, t0_raw, profile=t2_profile)
            if t2_payload.get("status") != "ok":
                fb = find_ok_t2_verdict(symbol)
                if not fb:
                    fb = await find_ok_t2_verdict_db(session, symbol)
                if fb:
                    logger.info(
                        "T2 live 失败，回退历史 ok 缓存 symbol=%s detail=%s",
                        symbol,
                        (t2_payload.get("detail") or "")[:80],
                    )
                    t2_payload = {
                        **fb,
                        "detail": (
                            f"{t2_payload.get('detail') or 'live 失败'} · "
                            "已展示历史 Opus 缓存（非编造）"
                        ),
                    }
    t2_from_cache = bool(
        enable_t2
        and t2_payload.get("status") == "ok"
        and (
            t2_payload.get("cache_hit")
            or t2_payload.get("route") == "cache"
            or t2_payload.get("stale_fallback")
        )
    )
    t2_art = await _save_artifact(
        session,
        stage="T2_verdict",
        model_id=t2_payload.get("model_id", t2_profile["model_id"]),
        payload=t2_payload,
        symbol=symbol,
        scan_id=scan_id,
        candidate_id=candidate_id,
        input_refs=[t1_art.id],
        latency_ms=int((time.perf_counter() - t2_start) * 1000),
        token_cost=float(t2_payload.get("token_cost") or 0.0),
    )

    wa = WorkspaceArtifact(
        scan_id=scan_id,
        candidate_id=candidate_id,
        symbol=symbol,
        workspace="radar",
        key_facts={"matrix": t1_payload.get("matrix"), "unavailable": t1_payload.get("unavailable")},
        verdict=t2_payload.get("deep_analysis") or {"status": t2_payload.get("status")},
        confidence=float(t2_payload.get("confidence") or 0.0),
        upstream_refs=[t2_art.id],
        t2_artifact_id=t2_art.id,
    )
    session.add(wa)
    await session.flush()

    return {
        "t0_id": t0_art.id,
        "t1_id": t1_art.id,
        "t2_id": t2_art.id,
        "wa_id": wa.id,
        "t0_raw": t0_raw,
        "t1_distilled": t1_payload,
        "t2_verdict": t2_payload,
        "t0_cache_hit": bool(t0_raw.get("cache_hit")),
        "t2_from_cache": t2_from_cache,
        "force_refresh_t0": force_refresh_t0,
        "force_refresh_t2": force_refresh_t2,
    }


async def _save_artifact(
    session: AsyncSession,
    *,
    stage: str,
    model_id: str,
    payload: dict,
    symbol: str,
    scan_id: Optional[int],
    candidate_id: Optional[int],
    input_refs: Optional[list[int]] = None,
    latency_ms: int = 0,
    token_cost: float = 0.0,
) -> StageArtifact:
    art = StageArtifact(
        symbol=symbol,
        scan_id=scan_id,
        candidate_id=candidate_id,
        workspace="radar",
        stage=stage,
        model_id=model_id,
        input_refs=input_refs or [],
        payload_json=payload,
        latency_ms=latency_ms,
        token_cost=token_cost,
    )
    session.add(art)
    await session.flush()
    return art


def _t2_result(
    *,
    status: str,
    model_id: str,
    route: str,
    deep_analysis: Optional[dict] = None,
    detail: str = "",
    confidence: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_yuan: float = 0.0,
) -> dict[str, Any]:
    return {
        "status": status,
        "model_id": model_id,
        "route": route,
        "detail": detail,
        "deep_analysis": deep_analysis or {},
        "confidence": confidence,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_yuan": cost_yuan,
        "token_cost": cost_yuan,
    }


async def run_t2_live(
    t1: dict[str, Any],
    t0: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """本机预拉 --with-t2 与生产 live Opus 共用入口。"""
    if profile is None:
        profile = resolve_model("radar", "t2_assess")
    return await _run_t2(t1, t0, profile=profile)


async def _run_t2(
    t1: dict[str, Any],
    t0: dict[str, Any],
    *,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """T2 必开 Opus：输出 9 维结构化 deep_analysis + 真实 token 成本。

    no-mock：Opus 不可达（降级 mock）/ 解析失败 / 预算超限 → status=error+detail，
    绝不伪造内容；前端据此显示明确错误而非假数据。
    """
    if not radar_t2_enabled():
        return _t2_result(
            status="disabled",
            model_id=str(profile.get("model_id")),
            route="none",
            detail="RADAR_T2_ENABLED=false：未开启 Opus 深度推理",
        )

    symbol = t0.get("symbol") or ""
    name = t0.get("name") or symbol

    def _blocking_call() -> Any:
        from apps.common.ai_dispatcher import AIDispatcher, BudgetExceededError

        dispatcher = AIDispatcher.default()
        try:
            return dispatcher.call(
                "radar_assess",
                messages=build_opus_messages(symbol, name, t1),
                max_tokens=4096,
                temperature=0.2,
            )
        except BudgetExceededError as exc:
            raise RuntimeError(f"预算超限：{exc}") from exc

    try:
        import asyncio

        resp = await asyncio.to_thread(_blocking_call)
    except Exception as exc:  # noqa: BLE001
        logger.warning("T2 Opus 调用失败: %s", exc)
        return _t2_result(
            status="error",
            model_id="anthropic:opus",
            route="remote",
            detail=f"Opus 调用失败：{str(exc)[:200]}",
        )

    # 检测 AIDispatcher 静默降级到 mock（旧路径兜底）→ no-mock 显式报错
    if resp.model == "mock" or (resp.raw or {}).get("_dispatcher_mock"):
        return _t2_result(
            status="error",
            model_id=resp.model,
            route=resp.route,
            detail=(
                "Opus 不可达（香港 ECS 地域限制或未配置 HTTPS_PROXY）；"
                "持仓/已预拉标的：本机 make radar-t0-prefetch-with-t2 后 diting-infra make radar-t0-sync；"
                "新标的 live 推理需配置出口代理"
            ),
        )

    try:
        deep = parse_opus_verdict(resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("T2 Opus 输出解析失败: %s", exc)
        return _t2_result(
            status="error",
            model_id=resp.model,
            route=resp.route,
            detail=f"Opus 输出非预期 JSON：{str(exc)[:160]}",
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost_yuan=estimate_cost_yuan(resp.tokens_in, resp.tokens_out),
        )

    cost = estimate_cost_yuan(resp.tokens_in, resp.tokens_out)
    return _t2_result(
        status="ok",
        model_id=resp.model,
        route=resp.route,
        deep_analysis=deep,
        confidence=float((deep.get("overall") or {}).get("confidence") or 0.0),
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
        cost_yuan=cost,
    )
