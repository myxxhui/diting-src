"""T0→T1→T2 三段流水线 + StageArtifact / WorkspaceArtifact 落库。

[Ref: step_14 · 25_ §2/§3]
工作台扫描：未勾选「刷新」时优先读 T0/T2 缓存；live 失败时回退历史 ok 研报。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import StageArtifact, WorkspaceArtifact
from apps.copilot.modules.radar.bg_tasks import BackgroundArtifactSink
from apps.copilot.modules.radar.display_layout import default_layout, load_saved_layout
from apps.copilot.modules.radar.model_router import t1_step_label
from apps.copilot.modules.radar.t1_distill import build_t1_payload
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
    build_opus_messages_freeform,
    build_opus_messages_from_t0,
    dimension_keys_from_layout,
    estimate_cost_yuan,
    parse_opus_verdict,
)
from apps.copilot.modules.radar.stage_presets import validate_radar_stage_combo

logger = logging.getLogger(__name__)


def _resolve_layout(layout: dict[str, Any] | None) -> dict[str, Any]:
    return layout or load_saved_layout() or default_layout()


def _minimal_t0(symbol: str, name: str) -> dict[str, Any]:
    return {"symbol": symbol, "name": name or symbol, "source": "resolve_only"}


async def run_radar_pipeline(
    session: AsyncSession,
    *,
    symbol: str,
    name: str = "",
    scan_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
    redis_client: Any = None,
    enable_t0: bool = True,
    enable_t1: bool = True,
    enable_t2: bool = False,
    t1_mode: str | None = None,
    t2_model: str | None = None,
    force_refresh_t0: bool = False,
    force_refresh_t2: bool = False,
    scan_origin: str = "internal",
    layout: dict[str, Any] | None = None,
    progress_cb: Any = None,
) -> dict[str, Any]:
    """三种组合：仅 T2 / T0+T2 / T0+T1+T2。

    工作台未勾选「刷新」时允许 T0/T2 读缓存；live 失败时回退历史 ok 研报（非编造）。
    """
    validate_radar_stage_combo(enable_t0, enable_t1, enable_t2)

    layout = _resolve_layout(layout)
    dim_keys = dimension_keys_from_layout(layout)
    t0_refresh = force_refresh_t0
    t2_refresh = force_refresh_t2

    t0_only = enable_t2 and not enable_t0 and not enable_t1
    t0_t2 = enable_t0 and enable_t2 and not enable_t1
    full_chain = enable_t0 and enable_t1 and enable_t2

    bg_sink = BackgroundArtifactSink()
    if enable_t0:
        if progress_cb is not None:
            progress_cb("t0", "T0 采集行情与公司资料", 20, symbol)
        t0_start = time.perf_counter()
        t0_raw = await collect_t0_raw(
            symbol,
            name=name,
            redis_client=redis_client,
            force_refresh=t0_refresh,
        )
        bg_sink.fire(
            stage="T0_raw",
            model_id="code:t0_collect",
            payload=t0_raw,
            symbol=symbol,
            scan_id=scan_id,
            candidate_id=candidate_id,
            latency_ms=int((time.perf_counter() - t0_start) * 1000),
        )
    elif t0_only:
        if progress_cb is not None:
            progress_cb("resolve", f"已解析 {symbol} · {name or symbol}", 12, "")
        t0_raw = _minimal_t0(symbol, name)
    else:
        raise ValueError("当前阶段组合需要勾选 T0 或仅 T2")

    if enable_t1:
        if progress_cb is not None:
            hit = "（缓存命中）" if t0_raw.get("cache_hit") and not t0_refresh else ""
            progress_cb("t1", f"{t1_step_label(t1_mode=t1_mode)}{hit}", 45, "")
        t1_start = time.perf_counter()
        t1_profile = resolve_model("radar", "t1_distill", t1_mode=t1_mode)
        cached_t1 = None
        if not t0_refresh and t0_raw.get("cache_hit"):
            cached_t1 = t0_raw.get("t1_distilled")
        if isinstance(cached_t1, dict) and cached_t1.get("matrix"):
            from apps.copilot.modules.radar.t1.fact_matrix_builder import enrich_t1_payload

            t1_payload = (
                cached_t1
                if cached_t1.get("fact_matrix")
                else enrich_t1_payload(t0_raw, dict(cached_t1))
            )
        else:
            t1_payload = await build_t1_payload(t0_raw, t1_mode=t1_mode)
        bg_sink.fire(
            stage="T1_distilled",
            model_id=t1_profile["model_id"],
            payload=t1_payload,
            symbol=symbol,
            scan_id=scan_id,
            candidate_id=candidate_id,
            latency_ms=int((time.perf_counter() - t1_start) * 1000),
        )
    else:
        t1_payload = {"matrix": {}, "unavailable": [], "skipped": True, "status": "skipped"}
        if progress_cb is not None:
            if t0_t2:
                progress_cb("t1", "T1 已跳过（T0 原始数据直供 T2）", 40, "")
            elif t0_only:
                progress_cb("t1", "T1 已跳过", 40, "")
            else:
                progress_cb("t1", "T1 已跳过", 45, "")

    if progress_cb is not None:
        if enable_t2:
            lbl = (t2_model or "Opus").strip()
            progress_cb("t2", f"T2 深度研报（{lbl}）", 58, "")
        else:
            progress_cb("t2", "T2 已跳过", 58, "")

    t2_start = time.perf_counter()
    t2_profile = resolve_model("radar", "t2_assess")
    if not enable_t2:
        t2_payload = _t2_result(
            status="skipped",
            model_id=str(t2_profile.get("model_id")),
            route="none",
            detail="未勾选 T2",
        )
    else:
        t2_payload = await _run_t2_for_combo(
            session,
            symbol=symbol,
            name=name or t0_raw.get("name") or symbol,
            t0_raw=t0_raw,
            t1_payload=t1_payload,
            layout=layout,
            dim_keys=dim_keys,
            t0_only=t0_only,
            t0_t2=t0_t2,
            full_chain=full_chain,
            t2_refresh=t2_refresh,
            profile=t2_profile,
            model_override=t2_model,
            progress_cb=progress_cb,
        )

    t2_from_cache = bool(
        enable_t2
        and t2_payload.get("status") == "ok"
        and (
            t2_payload.get("cache_hit")
            or t2_payload.get("route") == "cache"
            or t2_payload.get("stale_fallback")
            or (not t2_refresh and t2_payload.get("status") == "ok")
        )
    )
    if enable_t2:
        bg_sink.fire(
            stage="T2_verdict",
            model_id=t2_payload.get("model_id", t2_profile["model_id"]),
            payload=t2_payload,
            symbol=symbol,
            scan_id=scan_id,
            candidate_id=candidate_id,
            latency_ms=int((time.perf_counter() - t2_start) * 1000),
            token_cost=float(t2_payload.get("token_cost") or 0.0),
        )

    wa_id: int | None = None
    if enable_t1 or enable_t2:
        wa = WorkspaceArtifact(
            scan_id=scan_id,
            candidate_id=candidate_id,
            symbol=symbol,
            workspace="radar",
            key_facts={
                "matrix": t1_payload.get("matrix"),
                "unavailable": t1_payload.get("unavailable"),
                "fact_matrix": t1_payload.get("fact_matrix"),
                "unavailable_data": t1_payload.get("unavailable_data"),
            },
            verdict=t2_payload.get("deep_analysis") or {"status": t2_payload.get("status")},
            confidence=float(t2_payload.get("confidence") or 0.0),
            upstream_refs=[],
            t2_artifact_id=None,
        )
        session.add(wa)
        await session.flush()
        wa_id = wa.id

    stage_status = _build_stage_status(
        enable_t0=enable_t0,
        enable_t1=enable_t1,
        enable_t2=enable_t2,
        t0_raw=t0_raw,
        t1_payload=t1_payload,
        t2_payload=t2_payload,
    )

    return {
        "t0_id": None,
        "t1_id": None,
        "t2_id": None,
        "wa_id": wa_id,
        "t0_raw": t0_raw,
        "t1_distilled": t1_payload,
        "t2_verdict": t2_payload,
        "t0_cache_hit": bool(t0_raw.get("cache_hit")),
        "t2_from_cache": t2_from_cache,
        "force_refresh_t0": t0_refresh,
        "force_refresh_t2": t2_refresh,
        "scan_origin": scan_origin,
        "enable_t0": enable_t0,
        "enable_t1": enable_t1,
        "enable_t2": enable_t2,
        "stage_status": stage_status,
        "_bg_sink": bg_sink,
    }


async def _load_t2_cached(
    session: AsyncSession,
    symbol: str,
    t0_raw: dict[str, Any],
) -> dict[str, Any] | None:
    t2_cached = cached_t2_verdict(t0_raw)
    if not t2_cached:
        t2_cached = cached_t2_verdict(load_cached(symbol, require_fresh=True))
    if not t2_cached:
        t2_cached = cached_t2_verdict(load_cached(symbol, require_fresh=False))
    if not t2_cached:
        db_bundle = await load_latest_bundle_db(session, symbol)
        t2_cached = cached_t2_verdict(db_bundle)
    if not t2_cached:
        fb = find_ok_t2_verdict(symbol)
        if not fb:
            fb = await find_ok_t2_verdict_db(session, symbol)
        t2_cached = fb
    return t2_cached


async def _apply_t2_stale_fallback(
    session: AsyncSession,
    symbol: str,
    t2_payload: dict[str, Any],
) -> dict[str, Any]:
    if t2_payload.get("status") == "ok":
        return t2_payload
    fb = find_ok_t2_verdict(symbol)
    if not fb:
        fb = await find_ok_t2_verdict_db(session, symbol)
    if not fb:
        return t2_payload
    logger.info("T2 live 失败，回退历史 ok 缓存 symbol=%s", symbol)
    detail = t2_payload.get("detail") or "live 失败"
    if "invalid x-api-key" in str(detail).lower() or "authentication_error" in str(detail).lower():
        detail = (
            "Opus API 密钥无效或已过期（请更新 diting-src/.env 的 ANTHROPIC_API_KEY 后部署）"
        )
    return {
        **fb,
        "detail": f"{detail} · 已展示历史 Opus 缓存（非编造）",
        "stale_fallback": True,
    }


async def _run_t2_for_combo(
    session: AsyncSession,
    *,
    symbol: str,
    name: str,
    t0_raw: dict[str, Any],
    t1_payload: dict[str, Any],
    layout: dict[str, Any],
    dim_keys: list[str],
    t0_only: bool,
    t0_t2: bool,
    full_chain: bool,
    t2_refresh: bool,
    profile: dict[str, Any],
    model_override: str | None,
    progress_cb: Any,
) -> dict[str, Any]:
    if full_chain:
        if not (t1_payload.get("matrix")):
            raise ValueError("T0+T1+T2 需要 T1 事实矩阵；请检查 T1 步骤是否成功")
        messages = build_opus_messages(symbol, name, t1_payload)
        parse_keys = None
        if progress_cb is not None:
            progress_cb(
                "t2",
                "T2 基于 T1 事实矩阵推演（Opus + 维度 schema）",
                65,
                "",
            )
    elif t0_t2:
        messages = build_opus_messages_from_t0(symbol, name, t0_raw, layout)
        parse_keys = dim_keys
        if progress_cb is not None:
            progress_cb("t2", "T2 基于 T0 原始采集数据推演", 65, "")
    elif t0_only:
        messages = build_opus_messages_freeform(symbol, name, layout)
        parse_keys = dim_keys
        if progress_cb is not None:
            progress_cb("t2", "T2 按布局维度主题自主推演（不读 T0/T1 缓存）", 65, "")
    else:
        raise ValueError("未识别的 T2 阶段组合")

    if not t2_refresh:
        t2_cached = await _load_t2_cached(session, symbol, t0_raw)
        if t2_cached:
            logger.info("T2 cache hit symbol=%s", symbol)
            if progress_cb is not None:
                progress_cb("t2", "T2 使用历史 Opus 缓存", 72, "")
            return t2_cached

    if progress_cb is not None:
        progress_cb("t2", "T2 调用 Opus 深度推演", 65, "")
    t2_payload = await run_t2_live_messages(
        messages,
        t0_raw,
        dim_keys=parse_keys,
        profile=profile,
        model_override=model_override,
    )
    return await _apply_t2_stale_fallback(session, symbol, t2_payload)


def _build_stage_status(
    *,
    enable_t0: bool,
    enable_t1: bool,
    enable_t2: bool,
    t0_raw: dict[str, Any],
    t1_payload: dict[str, Any],
    t2_payload: dict[str, Any],
) -> dict[str, str]:
    """HTMX / summary_json 段状态：running|ok|skipped|error。"""

    def _t0() -> str:
        if not enable_t0:
            return "skipped"
        if t0_raw.get("source") == "resolve_only":
            return "ok"
        ok = sum(
            1
            for k in ("quote", "profile", "financials", "valuation")
            if (t0_raw.get(k) or {}).get("status") == "ok"
        )
        return "ok" if ok else "error"

    def _t1() -> str:
        if not enable_t1:
            return "skipped"
        if t1_payload.get("skipped"):
            return "skipped"
        if t1_payload.get("fact_matrix") or t1_payload.get("matrix"):
            return "ok"
        return "error"

    def _t2() -> str:
        if not enable_t2:
            return "skipped"
        st = str(t2_payload.get("status") or "error")
        if st in ("ok", "skipped", "disabled"):
            return st if st != "disabled" else "skipped"
        return "error"

    return {"t0": _t0(), "t1": _t1(), "t2": _t2()}


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
    model_override: str | None = None,
) -> dict[str, Any]:
    """本机预拉 --with-t2 与生产 live Opus 共用入口（T1 矩阵路径）。"""
    if profile is None:
        profile = resolve_model("radar", "t2_assess")
    symbol = t0.get("symbol") or ""
    name = t0.get("name") or symbol
    messages = build_opus_messages(symbol, name, t1)
    return await run_t2_live_messages(
        messages, t0, profile=profile, model_override=model_override
    )


async def run_t2_live_messages(
    messages: list[dict[str, str]],
    t0: dict[str, Any],
    *,
    dim_keys: list[str] | None = None,
    profile: dict[str, Any] | None = None,
    model_override: str | None = None,
) -> dict[str, Any]:
    """按已构建 messages 调用 Opus；dim_keys 为布局维度（None 则用内置 9 维解析）。"""
    if profile is None:
        profile = resolve_model("radar", "t2_assess")
    return await _run_t2_messages(
        messages,
        t0,
        dim_keys=dim_keys,
        profile=profile,
        model_override=model_override,
    )


async def _run_t2_messages(
    messages: list[dict[str, str]],
    t0: dict[str, Any],
    *,
    dim_keys: list[str] | None,
    profile: dict[str, Any],
    model_override: str | None = None,
) -> dict[str, Any]:
    if not radar_t2_enabled():
        return _t2_result(
            status="disabled",
            model_id=str(profile.get("model_id")),
            route="none",
            detail="RADAR_T2_ENABLED=false：未开启 Opus 深度推理",
        )

    from apps.copilot.modules.radar.chat import resolve_opus_model

    resolved_model = resolve_opus_model(model_override)

    def _blocking_call() -> Any:
        from apps.common.ai_dispatcher import AIDispatcher, BudgetExceededError

        dispatcher = AIDispatcher.default()
        try:
            return dispatcher.call(
                "radar_assess",
                messages=messages,
                max_tokens=4096,
                temperature=0.2,
                model_override=resolved_model,
            )
        except BudgetExceededError as exc:
            raise RuntimeError(f"预算超限：{exc}") from exc

    try:
        import asyncio

        resp = await asyncio.to_thread(_blocking_call)
    except Exception as exc:  # noqa: BLE001
        logger.warning("T2 Opus 调用失败: %s", exc)
        err = str(exc)
        if "invalid x-api-key" in err.lower() or "authentication_error" in err.lower():
            detail = (
                "Opus API 密钥无效或已过期；请更新 diting-src/.env 的 ANTHROPIC_API_KEY "
                "后执行 diting-infra make copilot-deploy-fast"
            )
        elif "not_found_error" in err or "model:" in err.lower():
            detail = (
                f"Opus 型号不可用（{resolved_model}）；"
                "请在 T2 下拉改选「Opus 4.6（推荐）」后重新点「分析」"
            )
        else:
            detail = f"Opus 调用失败：{err[:200]}"
        return _t2_result(
            status="error",
            model_id="anthropic:opus",
            route="remote",
            detail=detail,
        )

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
        deep = parse_opus_verdict(resp.text, dim_keys)
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
