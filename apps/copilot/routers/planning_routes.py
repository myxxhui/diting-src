"""行情解析与规划工作台路由。

[Ref: 03_/00_维度零/.../step_12_行情解析与规划工作台.md]
"""
from __future__ import annotations

import asyncio
import json
import html as _html
import re
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.db.models import RegimeAssessment
from apps.copilot.services.redis_wait import wait_for_sync_redis
from apps.copilot.modules.planning.dossier import build_symbol_dossier
from apps.copilot.modules.execution.advisor import (
    generate_execution_advice,
    list_execution_advices,
)
from apps.copilot.modules.planning.falsify import (
    compute_readiness,
    create_falsify_task,
    ensure_default_falsify_tasks,
    get_cognitive_snapshot,
    list_falsify_tasks,
    refresh_falsify_verdicts,
)
from apps.copilot.modules.planning.monitor import list_monitors, refresh_verdicts
from apps.copilot.modules.planning.schema import CampaignCreate, RadarPromoteRequest, RadarScanCreate
from apps.copilot.modules.planning.funnel import (
    demote_symbol_one_stage,
    get_or_create_container,
    hide_symbol_ui,
)
from apps.copilot.modules.planning.workspace_registry import (
    ALLOWED_WORKBENCH_VIEWS,
    DEFAULT_WORKBENCH_VIEW,
    get_workspace,
    workspace_display_name,
    workbench_tab_items,
)
from apps.copilot.modules.planning.sandbox import (
    get_asset_sandbox,
    one_shot_global_deduction,
    one_shot_plan_probes,
    update_probe_result,
)
from apps.copilot.modules.planning.service import (
    create_campaign,
    get_campaign,
    import_portfolio_to_campaign,
    list_campaigns,
    list_nodes,
    list_radar_symbols,
    list_timeline_entries,
    list_workspace_symbols,
    promote_campaign_to_executing,
)
from apps.copilot.modules.radar.schema import DIMENSIONS, MARKET_PHASE_LABELS
from apps.copilot.modules.radar.display_layout import (
    LAYOUT_HEADER,
    layout_to_jsonable,
    load_saved_layout,
    reset_saved_layout,
    resolve_layout_for_request,
    save_saved_layout,
    default_layout,
    layout_schema_payload,
    ordered_display_metas,
    parse_layout_from_header,
)
from apps.copilot.modules.radar.audit_render import render_audit_page
from apps.copilot.modules.radar.chat import (
    DEFAULT_CHAT_MODEL,
    RADAR_CHAT_MODELS,
    chat_turn,
    new_session_id,
)
from apps.copilot.modules.radar.persistence import (
    db_retention_days,
    list_versions_merged,
    load_version_merged,
    symbol_data_status,
)
from apps.copilot.modules.radar.symbol_resolve import (
    RadarSymbolResolveError,
    display_name_for_symbol,
    resolve_radar_query,
    suggest_radar_symbols,
)
from apps.copilot.modules.radar.t0.symbol_list import (
    list_collect_symbol_rows,
    row_to_dict,
    set_collect_symbol_enabled,
)
from apps.copilot.db.models import AssetState, RadarCandidate, RadarScan
from apps.copilot.modules.radar.collect_progress import (
    COLLECT_STEP_ORDER,
    load as load_collect_job,
    new_job_id,
)
from apps.copilot.modules.radar.collect_progress import init_job as init_collect_job
from apps.copilot.modules.radar.scan_progress import (
    SCAN_STEP_ORDER,
    init_scan as init_scan_progress,
    load as load_scan_progress,
)
from apps.copilot.modules.radar.service import (
    collect_symbol_t0_only,
    create_symbol_scan,
    run_collect_job,
    run_scan_job,
    ensure_model_profiles,
    get_scan,
    list_candidate_artifacts,
    list_recent_candidates,
    promote_candidate,
)
from apps.copilot.modules.roadmap.regime import regime_to_dict
from apps.copilot.modules.roadmap.service import (
    add_timeline_entry,
    add_timeline_from_candidate,
    archive_campaign_rolling,
    assess_campaign_regime,
    list_campaign_timeline,
    list_pending_next_waves,
)

router = APIRouter()


def _tpl(request: Request):
    return request.app.state.templates


async def _strategic_roadmap_context(session: AsyncSession, request: Request) -> dict:
    """滚动路线图 Tab 战略板块上下文。

    [Ref: 33_ §4]
    """
    from apps.copilot.modules.strategic.render import (
        render_command_center_main,
        render_phase_panel,
    )
    from apps.copilot.modules.strategic.service import (
        get_board_detail,
        get_phase_detail,
        list_boards_summary,
    )
    from apps.copilot.modules.strategic.z0_render import (
        render_cvm_matrix_table,
        render_core_pool_panel,
        render_left_sidebar_z0,
        render_p0_regime_banner,
    )
    from apps.copilot.modules.strategic.z0_workflow import (
        get_active_dispatch_for_phase,
        get_confirmed_core_pool,
        get_latest_wind_scan,
        list_cvm_scorecards,
    )

    boards = await list_boards_summary(session)
    board_id_raw = request.query_params.get("board_id")
    phase_id_raw = request.query_params.get("phase_id")
    z0_mode_raw = request.query_params.get("z0_mode")
    board_id: int | None = None
    phase_id: int | None = None
    if board_id_raw and str(board_id_raw).isdigit():
        board_id = int(board_id_raw)
    elif boards and z0_mode_raw != "wind":
        board_id = boards[0]["id"]
    if phase_id_raw and str(phase_id_raw).isdigit():
        phase_id = int(phase_id_raw)

    z0_mode = z0_mode_raw or ("wind" if not boards else "board")
    if z0_mode == "wind":
        board_id = None

    wind_scan = await get_latest_wind_scan(session)
    detail = None
    phase_detail = None
    cvm_html = ""
    core_pool_html = ""
    if board_id:
        detail = await get_board_detail(session, board_id)
        pid = phase_id or (detail or {}).get("active_phase_id")
        if pid:
            phase_id = pid
            phase_detail = await get_phase_detail(session, pid)
            rows = await list_cvm_scorecards(session, pid)
            dispatch = await get_active_dispatch_for_phase(session, pid)
            cvm_html = render_cvm_matrix_table(pid, rows, dispatch=dispatch)
            pool = await get_confirmed_core_pool(session, pid)
            core_pool_html = render_core_pool_panel(pid, pool, dispatch=dispatch)

    p0 = (wind_scan or {}).get("p0_snapshot") or {}
    left_html = render_left_sidebar_z0(
        mode=z0_mode,
        boards=boards,
        selected_board_id=board_id,
        wind_scan=wind_scan,
    )

    return {
        "strategic_boards": boards,
        "strategic_board_id": board_id,
        "strategic_phase_id": phase_id,
        "z0_mode": z0_mode,
        "wind_scan": wind_scan,
        "scan": wind_scan,
        "strategic_left_sidebar_html": left_html,
        "strategic_p0_banner_html": render_p0_regime_banner(p0),
        "strategic_board_list_html": left_html,
        "strategic_main_html": render_command_center_main(
            detail, selected_phase_id=phase_id
        ),
        "strategic_panel_html": render_phase_panel(phase_detail) if phase_detail else "",
        "strategic_cvm_html": cvm_html,
        "strategic_core_pool_html": core_pool_html,
    }


def _sync_redis():
    """阻塞等待 Redis PONG（不降级跳过）。"""
    return wait_for_sync_redis()


def _render_probe_task_markdown(bp: dict[str, Any]) -> str:
    def g(k: str) -> str:
        return _esc(bp.get(k) or "—")

    alts = bp.get("alternative_sources") or []
    alt_html = "".join(f"<li>{_esc(x)}</li>" for x in alts) if alts else "<li>无</li>"
    return (
        "<div class='text-sm leading-6 text-gray-700 space-y-2'>"
        f"<p><b>维度：</b>{g('dimension')}</p>"
        f"<p><b>目标数据：</b>{g('target_data_desc')}</p>"
        f"<p><b>主数据源：</b>{g('primary_source_name')}</p>"
        f"<p><b>为何选它：</b>{g('why_this_source')}</p>"
        f"<p><b>采集建议：</b>{g('collection_guidance')}</p>"
        f"<p><b>证伪逻辑：</b>{g('falsification_logic')}</p>"
        "<div><b>备选来源：</b><ul class='list-disc pl-5'>"
        f"{alt_html}</ul></div>"
        "</div>"
    )


def _render_sandbox_panel(sandbox: dict[str, Any]) -> str:
    probes = sandbox.get("probes") or []
    symbol = _esc(sandbox.get("symbol_code") or "")
    planning_snapshot = sandbox.get("planning_snapshot") or {}
    deduction_snapshot = sandbox.get("deduction_snapshot") or {}

    top = (
        f"<details class='mb-3 rounded-lg border border-gray-100 bg-gray-50/70' open>"
        f"<summary class='cursor-pointer px-3 py-2 text-sm font-semibold text-gray-700'>"
        f"雷达初评快照（{symbol}）</summary>"
        f"<div class='px-3 pb-3 text-xs text-gray-600'>"
        f"<pre class='bg-white border border-gray-100 rounded p-2 overflow-x-auto'>"
        f"{_esc(json.dumps((sandbox.get('radar_initial_analysis') or {}), ensure_ascii=False, indent=2)[:2000])}"
        f"</pre></div></details>"
    )
    plan_meta = ""
    if planning_snapshot:
        plan_meta = (
            f"<p class='text-xs text-gray-500 mb-2'>"
            f"最近规划：{_esc(planning_snapshot.get('model'))} · "
            f"probe={planning_snapshot.get('probe_count', 0)} · "
            f"¥{float(planning_snapshot.get('cost_yuan_est') or 0):.4f}</p>"
        )
    plan_btn = (
        f"<form hx-post='/api/planning/sandbox/{symbol}/plan' "
        f"hx-target='#planning-sandbox-panel-{symbol}' hx-swap='outerHTML' class='mb-3'>"
        f"<button type='submit' class='px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold "
        f"hover:bg-indigo-700'>✨ 智能规划：一键生成全维度数据探针</button></form>"
    )

    rows: list[str] = []
    for p in probes:
        pid = _esc(p.get("id"))
        st = p.get("status")
        cls = "bg-red-50 text-red-700" if st == "pending_code" else "bg-green-50 text-green-700"
        st_label = "🔴 待开发接入" if st == "pending_code" else "🟢 数据可用"
        bp = p.get("probe_blueprint") or {}
        title = _esc(bp.get("target_data_desc") or bp.get("dimension") or "探针")
        dim = _esc(bp.get("dimension") or "—")
        row = [
            "<div class='border border-gray-100 rounded-lg p-3 mb-2'>",
            f"<div class='flex flex-wrap items-center gap-2 mb-1'>",
            f"<span class='font-semibold text-gray-900'>{title}</span>",
            f"<span class='text-xs px-2 py-0.5 rounded {cls}'>{st_label}</span>",
            f"<span class='text-xs text-gray-400'>{dim}</span></div>",
        ]
        if st == "pending_code":
            row.append(
                "<details class='mt-2 bg-gray-50 rounded border border-gray-100'>"
                "<summary class='cursor-pointer px-2 py-1.5 text-xs text-blue-700'>查看数据采集开发蓝图</summary>"
                f"<div class='p-2'>{_render_probe_task_markdown(bp)}</div></details>"
            )
        else:
            refined = p.get("refined_data") or {}
            row.append(
                "<div class='mt-2 grid grid-cols-1 lg:grid-cols-2 gap-2'>"
                "<div class='rounded border border-gray-100 bg-white p-2'>"
                "<p class='text-xs text-gray-500 mb-1'>数值趋势（Echarts 占位）</p>"
                "<div class='h-20 rounded bg-slate-50 border border-dashed border-slate-200 "
                "text-[11px] text-slate-500 flex items-center justify-center'>迷你趋势图（time-series）</div>"
                "</div>"
                "<div class='rounded border border-gray-100 bg-white p-2'>"
                "<p class='text-xs text-gray-500 mb-1'>提炼结论</p>"
                f"<pre class='text-xs text-gray-700 whitespace-pre-wrap'>{_esc(json.dumps(refined, ensure_ascii=False, indent=2)[:900])}</pre>"
                "</div></div>"
            )
        row.append(
            f"<form hx-post='/api/planning/sandbox/probes/{pid}/result' hx-target='#planning-sandbox-panel-{symbol}' "
            f"hx-swap='outerHTML' class='mt-2 flex gap-2 items-center'>"
            f"<input type='text' name='mock_result' placeholder='可粘贴 JSON（模拟数据就绪）' "
            f"class='flex-1 border border-gray-200 rounded px-2 py-1 text-xs'>"
            f"<button type='submit' class='text-xs px-2 py-1 rounded border border-gray-200 text-gray-600'>标记数据可用</button>"
            f"</form>"
        )
        row.append("</div>")
        rows.append("".join(row))
    board = (
        "<div class='rounded-lg border border-gray-100 bg-white p-3'>"
        "<h3 class='text-sm font-semibold text-gray-800 mb-2'>探针流水线看板</h3>"
        + ("".join(rows) if rows else "<p class='text-sm text-gray-400'>暂无探针，请先执行智能规划。</p>")
        + "</div>"
    )

    all_ready = bool(sandbox.get("all_data_ready"))
    gate_cls = "bg-green-600 hover:bg-green-700" if all_ready else "bg-gray-300"
    gate_text = "🚀 全局视野：执行最终逻辑深度推演" if all_ready else "🚀 全局视野：等待全部探针数据就绪"
    gate = (
        f"<div class='mt-3 rounded-lg border border-gray-100 bg-white p-3'>"
        f"<p class='text-xs text-gray-500 mb-2'>全局决断门：仅当全部探针为 🟢 数据可用时解锁</p>"
        f"<form hx-post='/api/planning/sandbox/{symbol}/deduce' "
        f"hx-target='#planning-sandbox-panel-{symbol}' hx-swap='outerHTML'>"
        f"<button type='submit' {'disabled' if not all_ready else ''} "
        f"class='w-full px-3 py-2 rounded-lg text-white text-sm font-semibold {gate_cls} "
        f"{'cursor-not-allowed' if not all_ready else ''}'>{gate_text}</button></form>"
        f"</div>"
    )

    verdict = ""
    if deduction_snapshot:
        falsified = bool(deduction_snapshot.get("falsified_flag"))
        lamp = "🔴 红灯（逻辑被证伪）" if falsified else "🟢 绿灯（逻辑未被证伪）"
        lamp_cls = "bg-red-50 text-red-700 border-red-100" if falsified else "bg-green-50 text-green-700 border-green-100"
        verdict = (
            f"<div class='mt-3 rounded-lg border p-3 {lamp_cls}'>"
            f"<p class='font-semibold mb-1'>{lamp}</p>"
            f"<p class='text-sm mb-1'>{_esc(deduction_snapshot.get('cross_validation_analysis') or '')}</p>"
            f"<p class='text-sm'><b>建议：</b>{_esc(deduction_snapshot.get('final_recommendation') or '')}</p>"
            f"</div>"
        )

    return (
        f"<div id='planning-sandbox-panel-{symbol}' class='mt-3 rounded-xl border border-indigo-100 bg-indigo-50/40 p-3'>"
        f"{top}{plan_meta}{plan_btn}{board}{gate}{verdict}</div>"
    )


async def _audit_page_context(
    request: Request,
    session: AsyncSession,
) -> dict[str, Any]:
    """数据审计页上下文（顶栏「审计」）。"""
    sym_q = (request.query_params.get("symbol") or "").strip()
    ver_q = (request.query_params.get("version") or "").strip()
    symbol = sym_q
    name = sym_q
    if sym_q:
        try:
            symbol, name = resolve_radar_query(sym_q)
        except RadarSymbolResolveError:
            symbol = sym_q.zfill(6)[-6:] if sym_q.isdigit() else sym_q
    versions = await list_versions_merged(session, symbol) if symbol else []
    bundle = None
    vid = ver_q or (versions[0]["version_id"] if versions else "")
    if symbol and vid:
        bundle = await load_version_merged(session, symbol, vid)
    t2_id = (request.query_params.get("t2_id") or "").strip()
    return {
        "audit_symbol": symbol,
        "audit_name": name,
        "audit_versions": versions,
        "audit_version_id": vid,
        "t2_id": t2_id,
        "audit_html": render_audit_page(
            symbol=symbol or "—",
            name=name or "—",
            versions=versions,
            selected_version_id=vid or None,
            bundle=bundle,
        )
        if symbol
        else (
            "<p class='text-sm text-gray-500 py-6 text-center'>"
            "输入标的代码或简称，查询 T0 / T1 / T2 版本与 bundle</p>"
        ),
    }


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    ctx = await _audit_page_context(request, session)
    return _tpl(request).TemplateResponse(request, "audit/data.html", ctx)


@router.get("/opus", response_class=HTMLResponse)
async def opus_chat_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.modules.executing.t2_analyst import DEFAULT_JL13_DATA_TEMPLATE
    from apps.copilot.modules.planning.service import list_workspace_symbols

    symbols: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in await list_workspace_symbols(session, view="executing"):
        sym = str(item.get("symbol") or "").strip()
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append({"symbol": sym, "name": item.get("name") or item.get("stock_name") or ""})

    return _tpl(request).TemplateResponse(
        request,
        "audit/opus.html",
        {
            "chat_models": RADAR_CHAT_MODELS,
            "default_model": DEFAULT_CHAT_MODEL,
            "default_jl13_data_template": DEFAULT_JL13_DATA_TEMPLATE,
            "workspace_symbols": symbols,
        },
    )


@router.get("/ledger")
async def ledger_entry(request: Request):
    """Z4 横切入口 · [Ref: 33_ §3.1] → 投资工作台决策复盘 Tab。"""
    from urllib.parse import urlencode

    from fastapi.responses import RedirectResponse

    q: dict[str, str] = {"view": "ledger"}
    for key in ("symbol", "user_id"):
        val = request.query_params.get(key)
        if val:
            q[key] = val
    return RedirectResponse(url="/planning?" + urlencode(q), status_code=302)


@router.get("/planning", response_class=HTMLResponse)
async def planning_page(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from urllib.parse import urlencode

    from fastapi.responses import RedirectResponse

    view = request.query_params.get("view", DEFAULT_WORKBENCH_VIEW)
    audit_tab = (request.query_params.get("audit_tab") or "data").strip()
    # 旧工作台链接 → 顶栏一级页面
    if view == "radar_chat" or (view in ("audit", "radar_audit") and audit_tab == "chat"):
        return RedirectResponse(url="/opus", status_code=302)
    if view in ("audit", "radar_audit", "radar_data"):
        q = {k: v for k, v in request.query_params.items() if k not in ("view", "audit_tab")}
        return RedirectResponse(url="/audit?" + urlencode(q), status_code=302)
    if view in ("radar_settings",):
        return RedirectResponse(url="/settings#radar-prefs", status_code=302)
    allowed = tuple(ALLOWED_WORKBENCH_VIEWS)
    if view not in allowed:
        view = DEFAULT_WORKBENCH_VIEW
    from apps.copilot.modules.radar.workbench_prefs import load_prefs

    ctx: dict = {
        "view": view,
        "workbench_prefs": load_prefs(),
        "radar_chat_models": RADAR_CHAT_MODELS,
        "radar_default_model": DEFAULT_CHAT_MODEL,
        **_workbench_template_context(view),
    }
    if view == "roadmap":
        ctx.update(await _strategic_roadmap_context(session, request))
    if view in ("planning", "executing"):
        ctx["workspace_symbols_html"] = await build_workspace_symbols_html(session, view=view)
    if view == "ledger":
        ctx.update(await _load_ledger_page_context(session, request))
    return _tpl(request).TemplateResponse(request, "planning/workbench.html", ctx)


@router.get("/planning/panel", response_class=HTMLResponse)
async def planning_panel(
    request: Request,
    view: str = DEFAULT_WORKBENCH_VIEW,
    session: AsyncSession = Depends(get_db),
):
    """工作台内容区片段（HTMX 切换 Tab · 避免整页刷新）。"""
    allowed = tuple(ALLOWED_WORKBENCH_VIEWS)
    if view not in allowed:
        view = DEFAULT_WORKBENCH_VIEW
    from apps.copilot.modules.radar.workbench_prefs import load_prefs

    ctx: dict = {
        "view": view,
        "workbench_prefs": load_prefs(),
        "radar_chat_models": RADAR_CHAT_MODELS,
        "radar_default_model": DEFAULT_CHAT_MODEL,
        **_workbench_template_context(view),
    }
    if view == "roadmap":
        ctx.update(await _strategic_roadmap_context(session, request))
    if view in ("planning", "executing"):
        ctx["workspace_symbols_html"] = await build_workspace_symbols_html(session, view=view)
    if view == "ledger":
        ctx.update(await _load_ledger_page_context(session, request))
    return _tpl(request).TemplateResponse(
        request,
        "planning/_workbench_panel.html",
        ctx,
    )


@router.get("/portfolio-guard", response_class=HTMLResponse)
async def guard_page(request: Request):
    """兼容旧入口 · Z3 持仓监护室在投资工作台内。"""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/planning?view=executing", status_code=302)


@router.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    center = request.query_params.get("center", "").strip()
    if center:
        center = center.zfill(6)[-6:]
    return _tpl(request).TemplateResponse(
        request, "graph/placeholder.html", {"center": center or None}
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    from apps.copilot.modules.radar.workbench_prefs import load_prefs

    return _tpl(request).TemplateResponse(
        request,
        "settings/index.html",
        {"workbench_prefs": load_prefs()},
    )


@router.get("/system", response_class=HTMLResponse)
async def system_page(request: Request):
    """兼容旧链接 /system → /settings。"""
    from fastapi.responses import RedirectResponse

    if request.url.query:
        return RedirectResponse(url=f"/settings?{request.url.query}#radar-prefs", status_code=302)
    return RedirectResponse(url="/settings#radar-prefs", status_code=302)


async def _load_ledger_page_context(
    session: AsyncSession,
    request: Request,
    *,
    user_id: str = "default",
) -> dict[str, Any]:
    """决策复盘库（Z4）：价值指标 + 归档标的 SSR。"""
    from datetime import date, datetime, timezone

    symbols = await list_workspace_symbols(session, view="ledger")
    await session.commit()
    from apps.copilot.modules.planning.workspace_render import render_archived_symbol_list

    ledger_symbols_html = render_archived_symbol_list(symbols)

    today = date.today()
    start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    end_year, end_month = (
        (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    )
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)

    scs = type(
        "SCS",
        (),
        {"score": 0, "base": 0, "contribution_sum": 0, "lag_penalty": 0, "sample_count": 0},
    )()
    ev = type(
        "EV",
        (),
        {"total": 0, "hedge_value": 0, "gain_value": 0, "cost_value": 0},
    )()
    breaker = type(
        "Breaker",
        (),
        {"paused": False, "reason": "", "last_window_size": 0, "last_bh_ratio": 0.0},
    )()

    ledger = getattr(request.app.state, "ledger", None)
    if ledger:
        try:
            scs_co = await ledger["scs"].calculate(user_id=user_id, start=start, end=end)
            ev_co = await ledger["ev"].calculate(user_id=user_id, start=start, end=end)
            breaker_state = await ledger["breaker"].evaluate(user_id)
            scs = scs_co
            ev = ev_co
            breaker = breaker_state
        except Exception:
            pass  # 复盘指标不可用时仍展示归档区

    return {
        "user_id": user_id,
        "scs": scs,
        "ev": ev,
        "breaker": breaker,
        "year": today.year,
        "month": today.month,
        "ledger_symbols_html": ledger_symbols_html,
    }


def _workbench_template_context(view: str) -> dict[str, Any]:
    w = get_workspace(view)
    return {
        "workspace_tabs": workbench_tab_items(),
        "workspace_display_name": w.display_name,
        "workspace_tagline": w.tagline,
        "workspace_zone": w.zone_code,
    }


async def _load_workspace_symbols_bundle(
    session: AsyncSession,
    *,
    view: str,
) -> tuple[list, int, dict, dict, list, dict, dict]:
    """规划/执行区标的卡数据包（SSR 与 /api/campaigns 共用）。"""
    symbols = await list_workspace_symbols(session, view=view)
    container = await get_or_create_container(session)
    t2_summaries: dict = {}
    sym_list = [s.get("symbol", "") for s in symbols if s.get("symbol")]
    from apps.copilot.modules.strategic.service import (
        get_primary_tags_map,
        jl_summary_for_phase,
        list_board_phase_options,
        suggest_tag_for_symbol,
    )

    tags_map = await get_primary_tags_map(session, sym_list)
    tag_options = await list_board_phase_options(session)
    tag_suggested: dict[str, dict | None] = {}
    jl_summaries: dict[str, str] = {}
    for sym in sym_list:
        tag_suggested[sym] = await suggest_tag_for_symbol(session, sym)
        t = tags_map.get(sym)
        if t and t.get("phase_id"):
            jl_summaries[sym] = await jl_summary_for_phase(session, t["phase_id"])
    if view == "executing":
        from apps.copilot.modules.executing.t2_advice_summary import (
            load_executing_t2_summaries_for_symbols,
        )

        t2_summaries = await load_executing_t2_summaries_for_symbols(session, sym_list)
    await session.commit()
    return (
        symbols,
        container.id,
        t2_summaries,
        tags_map,
        tag_options,
        tag_suggested,
        jl_summaries,
    )


async def build_workspace_symbols_html(session: AsyncSession, *, view: str) -> str:
    """工作台规划/执行/复盘区首屏 SSR · 与 /api/campaigns HTML 同构。"""
    if view == "ledger":
        symbols = await list_workspace_symbols(session, view="ledger")
        from apps.copilot.modules.planning.workspace_render import render_archived_symbol_list

        return render_archived_symbol_list(symbols)
    if view not in ("planning", "executing"):
        return ""
    (
        symbols,
        container_id,
        t2_summaries,
        tags_map,
        tag_options,
        tag_suggested,
        jl_summaries,
    ) = await _load_workspace_symbols_bundle(session, view=view)
    resp = _render_workspace_symbols_html(
        symbols,
        view=view,
        container_id=container_id,
        t2_summaries=t2_summaries,
        tags_map=tags_map,
        tag_options=tag_options,
        tag_suggested=tag_suggested,
        jl_summaries=jl_summaries,
    )
    return resp.body.decode("utf-8")


@router.get("/api/campaigns")
async def api_list_campaigns(
    request: Request,
    session: AsyncSession = Depends(get_db),
    view: str | None = None,
):
    accept = request.headers.get("accept", "")
    want_html = "text/html" in accept or request.headers.get("hx-request")
    # 标的级漏斗：planning/executing/ledger 视图按 funnel_stage 渲染
    if view in ("planning", "executing", "ledger"):
        if view == "ledger":
            symbols = await list_workspace_symbols(session, view="ledger")
            if want_html:
                from apps.copilot.modules.planning.workspace_render import (
                    render_archived_symbol_list,
                )

                return HTMLResponse(render_archived_symbol_list(symbols))
            return symbols
        (
            symbols,
            container_id,
            t2_summaries,
            tags_map,
            tag_options,
            tag_suggested,
            jl_summaries,
        ) = await _load_workspace_symbols_bundle(session, view=view)
        if want_html:
            return _render_workspace_symbols_html(
                symbols,
                view=view,
                container_id=container_id,
                t2_summaries=t2_summaries,
                tags_map=tags_map,
                tag_options=tag_options,
                tag_suggested=tag_suggested,
                jl_summaries=jl_summaries,
            )
        return symbols
    items = await list_campaigns(session, view=view)
    if want_html:
        return _render_campaigns_html(items, view=view)
    return items


@router.get("/api/timeline")
async def api_timeline(
    request: Request,
    session: AsyncSession = Depends(get_db),
    campaign_id: int | None = None,
):
    items = await list_timeline_entries(session, campaign_id=campaign_id)
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return _render_timeline_html(items)
    return items


async def _radar_candidates_html_response(
    session: AsyncSession,
    *,
    flash: str = "",
) -> HTMLResponse:
    from apps.copilot.modules.strategic.service import get_primary_tags_map

    items = await list_recent_candidates(session)
    syms = [c.get("symbol", "") for c in items if c.get("symbol")]
    tags_map = await get_primary_tags_map(session, syms)
    return _render_radar_candidates_html(items, flash=flash, tags_map=tags_map)


@router.get("/api/radar/symbols")
async def api_radar_symbols(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """雷达区 = 扫描工作台：最近扫描候选（待晋级），不再混入持仓列表。"""
    items = await list_recent_candidates(session)
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        from apps.copilot.modules.strategic.service import get_primary_tags_map

        syms = [c.get("symbol", "") for c in items if c.get("symbol")]
        tags_map = await get_primary_tags_map(session, syms)
        return _render_radar_candidates_html(items, tags_map=tags_map)
    return items


def _form_bool_on(vals: list[str], *, default: bool = False) -> bool:
    if not vals:
        return default
    return any(v.lower() in ("1", "true", "yes", "on") for v in vals)


def _parse_radar_scan_stages(form: Any) -> tuple[bool, bool, bool, str, str | None]:
    from apps.copilot.modules.radar.stage_presets import validate_radar_stage_combo

    t0_on = _form_bool_on(form.getlist("enable_t0"), default=False)
    t1_on = _form_bool_on(form.getlist("enable_t1"), default=False)
    t2_on = _form_bool_on(form.getlist("enable_t2"), default=False)
    t1_mode = (form.get("t1_mode") or "rule").strip().lower()
    if t1_mode not in ("rule", "deepseek"):
        t1_mode = "rule"
    t2_model = (form.get("t2_model") or "").strip() or None
    validate_radar_stage_combo(t0_on, t1_on, t2_on)
    return t0_on, t1_on, t2_on, t1_mode, t2_model


@router.post("/api/radar/scans", status_code=201)
async def api_create_radar_scan(
    request: Request,
    session: AsyncSession = Depends(get_db),
    query_text: str = Form(""),
    input_type: str = Form("symbol"),
):
    q = (query_text or "").strip()
    if not q:
        msg = "请输入股票代码或简称"
        if request.headers.get("hx-request") or "text/html" in request.headers.get(
            "accept", ""
        ):
            return HTMLResponse(_render_radar_resolve_error_html(msg))
        raise HTTPException(status_code=400, detail=msg)
    query_text = q
    if input_type != "symbol":
        raise HTTPException(
            status_code=501,
            detail="启动期仅支持模式 C（symbol）；A/B 见 step_14 扩展项",
        )
    form = await request.form()
    try:
        t0_on, t1_on, t2_on, t1_mode, t2_model = _parse_radar_scan_stages(form)
    except ValueError as exc:
        if request.headers.get("hx-request") or "text/html" in request.headers.get(
            "accept", ""
        ):
            return HTMLResponse(_render_radar_resolve_error_html(str(exc)))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scan_origin = (form.get("scan_origin") or "workbench").strip() or "workbench"
    fr_vals = form.getlist("force_refresh")
    # 工作台「分析」默认 live 重新推演；历史缓存单独在 cached-report 区展示
    force_refresh = _form_bool_on(fr_vals, default=True)
    await ensure_model_profiles(session)
    redis_client = _sync_redis()
    import asyncio

    try:
        sym, name = await asyncio.to_thread(resolve_radar_query, query_text)
    except RadarSymbolResolveError as exc:
        if request.headers.get("hx-request") or "text/html" in request.headers.get(
            "accept", ""
        ):
            return HTMLResponse(_render_radar_resolve_error_html(str(exc)))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan = RadarScan(input_type="symbol", query_text=sym, status="running")
    session.add(scan)
    await session.flush()
    session.add(RadarCandidate(scan_id=scan.id, symbol=sym, name=name))
    await session.flush()
    scan_id = scan.id
    await session.commit()

    init_scan_progress(
        redis_client,
        scan_id,
        symbol=sym,
        name=name,
        enable_t0=t0_on,
        enable_t1=t1_on,
        enable_t2=t2_on,
        t1_mode=t1_mode,
        t2_model=t2_model,
    )
    asyncio.create_task(
        run_scan_job(
            scan_id,
            query_text,
            enable_t0=t0_on,
            enable_t1=t1_on,
            enable_t2=t2_on,
            t1_mode=t1_mode,
            t2_model=t2_model,
            force_refresh=force_refresh,
            scan_origin=scan_origin,
            redis_client=redis_client,
        )
    )

    if request.headers.get("hx-request"):
        state = load_scan_progress(redis_client, scan_id) or {
            "scan_id": scan_id,
            "status": "running",
            "symbol": sym,
            "name": name,
            "pct": 0,
            "step_label": "已提交分析任务…",
        }
        return HTMLResponse(_render_scan_progress_panel(state))
    return {"id": scan_id, "status": "running", "symbol": sym}


@router.get("/api/radar/display-layout/schema")
async def api_radar_display_layout_schema():
    """内置 9 维 + 默认布局 + 自定义模块提示词编写指南。"""
    return layout_schema_payload()


@router.get("/api/radar/display-layout")
async def api_get_radar_display_layout():
    """已持久化的九维展示顺序（PVC display_layout.json）。"""
    saved = load_saved_layout()
    if saved:
        return layout_to_jsonable(saved)
    return layout_to_jsonable(default_layout())


@router.put("/api/radar/display-layout")
async def api_put_radar_display_layout(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.modules.radar.display_layout import save_saved_layout_async

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="需要 JSON 请求体") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="无效 JSON")
    result = await save_saved_layout_async(session, body)
    await session.commit()
    return result


@router.delete("/api/radar/display-layout")
async def api_delete_radar_display_layout(session: AsyncSession = Depends(get_db)):
    from apps.copilot.modules.radar.display_layout import reset_saved_layout_async

    result = await reset_saved_layout_async(session)
    await session.commit()
    return layout_to_jsonable(result)


@router.get("/api/radar/workbench-prefs")
async def api_get_radar_workbench_prefs():
    """扫描台默认选项 + 缓存策略（服务端 JSON 热加载）。"""
    from apps.copilot.modules.radar.workbench_prefs import load_prefs

    return load_prefs()


@router.put("/api/radar/workbench-prefs")
async def api_put_radar_workbench_prefs(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.modules.radar.workbench_prefs import save_prefs_async

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="需要 JSON 请求体") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="无效 JSON")
    result = await save_prefs_async(session, body)
    await session.commit()
    return result


@router.delete("/api/radar/workbench-prefs")
async def api_delete_radar_workbench_prefs(session: AsyncSession = Depends(get_db)):
    from apps.copilot.modules.radar.workbench_prefs import reset_prefs_async

    result = await reset_prefs_async(session)
    await session.commit()
    return result


def _layout_from_request(request: Request) -> dict[str, Any]:
    raw = request.headers.get(LAYOUT_HEADER) or request.headers.get("X-Radar-Display-Layout")
    return resolve_layout_for_request(raw)


@router.get("/api/radar/scans/{scan_id}/progress")
async def api_radar_scan_progress(
    scan_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """轻量进度轮询（仅 Redis · 不 hydrate T2 / 不扫 DB 候选）。"""
    from apps.copilot.modules.radar.scan_progress import load as load_scan_progress

    redis_client = _sync_redis()
    state = load_scan_progress(redis_client, scan_id)
    if not state:
        scan_row = await session.get(RadarScan, scan_id)
        if scan_row is None:
            raise HTTPException(status_code=404, detail="scan not found")
        db_status, query_text = scan_row.status, scan_row.query_text
        if db_status == "done":
            return await api_get_radar_scan(scan_id, request, session)
        if db_status == "error":
            return await api_get_radar_scan(scan_id, request, session)
        state = {
            "scan_id": scan_id,
            "status": "running",
            "symbol": query_text or "",
            "name": "",
            "pct": 5,
            "step_label": "任务排队中…",
        }
    status = state.get("status") or "running"
    if status == "done":
        return await api_get_radar_scan(scan_id, request, session)
    if status == "error":
        return HTMLResponse(_render_scan_progress_panel(state))
    return HTMLResponse(_render_scan_progress_panel(state))


@router.get("/api/radar/scans/{scan_id}")
async def api_get_radar_scan(
    scan_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.modules.radar.scan_progress import load as load_scan_progress

    redis_client = _sync_redis()
    try:
        result = await get_scan(session, scan_id, hydrate_t2=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.get("status") == "running":
        state = load_scan_progress(redis_client, scan_id) or {
            "scan_id": scan_id,
            "status": "running",
            "symbol": result.get("query_text") or "",
            "name": "",
            "pct": 5,
            "step_label": "任务排队中…",
        }
        if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
            return HTMLResponse(_render_scan_progress_panel(state))
        return {**result, "progress": state}
    if result.get("status") == "done":
        result = await get_scan(session, scan_id, hydrate_t2=True)
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        view_cached = (
            request.headers.get("x-radar-view-mode", "").strip().lower() == "cached"
        )
        return _render_scan_html(
            result,
            layout=_layout_from_request(request),
            redis_client=redis_client,
            view_cached=view_cached,
        )
    return result


@router.get("/api/radar/candidates/{candidate_id}/artifacts")
async def api_candidate_artifacts(
    candidate_id: int,
    session: AsyncSession = Depends(get_db),
):
    return await list_candidate_artifacts(session, candidate_id)


@router.get("/api/radar/audit/{symbol}/versions")
async def api_radar_audit_versions(
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    """近 N 天版本列表（DB + 24h 文件缓存，最多 7 版/标的）。"""
    try:
        sym, _ = resolve_radar_query(symbol)
    except RadarSymbolResolveError:
        sym = symbol.zfill(6)[-6:] if symbol.isdigit() else symbol
    return {
        "symbol": sym,
        "file_retention_hours": file_retention_hours(),
        "db_retention_days": db_retention_days(),
        "versions": await list_versions_merged(session, sym),
    }


@router.get("/api/radar/data/{symbol}")
async def api_radar_data_status(
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    try:
        sym, _ = resolve_radar_query(symbol)
    except RadarSymbolResolveError:
        sym = symbol.zfill(6)[-6:] if symbol.isdigit() else symbol
    return await symbol_data_status(session, sym)


def _start_radar_collect(query_text: str, redis_client: Any) -> tuple[str, dict]:
    """解析输入并启动后台采集，返回 (job_id, progress_state)。"""
    sym, name = resolve_radar_query(query_text)
    job_id = new_job_id()
    state = init_collect_job(redis_client, job_id, symbol=sym, name=name)
    asyncio.create_task(run_collect_job(job_id, query_text.strip(), redis_client))
    return job_id, state


@router.get("/api/radar/cached-report")
async def api_radar_cached_report(
    request: Request,
    q: str = "",
    session: AsyncSession = Depends(get_db),
):
    """标的已有历史 ok T2 研报时，在分析区下方展示（非 live 重推）。"""
    import asyncio

    from apps.copilot.modules.radar.symbol_resolve import display_name_for_symbol, resolve_radar_query
    from apps.copilot.modules.radar.t2_resolve import hydrate_candidate_t2, resolve_ok_t2_verdict

    raw = (q or "").strip()
    if not raw:
        return HTMLResponse("")
    try:
        sym, name = await asyncio.to_thread(resolve_radar_query, raw)
    except RadarSymbolResolveError:
        sym = raw.zfill(6)[-6:] if raw.isdigit() else raw
        name = display_name_for_symbol(sym, allow_network=False)

    t2 = await resolve_ok_t2_verdict(session, sym)
    if not t2 or t2.get("status") != "ok":
        return HTMLResponse(
            "<p class='text-xs text-gray-400 py-2'>暂无历史研报缓存</p>"
        )
    c = hydrate_candidate_t2(
        {"symbol": sym, "name": name, "cost": {}},
        t2,
        note="历史缓存",
    )
    block = _render_candidate_report(
        c,
        layout=_layout_from_request(request),
        view_cached=True,
    )
    return HTMLResponse(
        f"<div class='mt-2'><p class='text-xs font-medium text-gray-500 mb-2'>"
        f"📋 历史研报缓存（点击「分析」将 live 重新推演）</p>{block}</div>"
    )


@router.get("/api/radar/symbols/suggest")
async def api_radar_symbol_suggest(q: str = "", limit: int = 8):
    """搜索栏模糊建议（JSON）· 线程池执行，避免阻塞事件循环。"""
    import asyncio

    from apps.copilot.modules.radar.symbol_resolve import market_name_index_ready

    lim = min(12, max(1, limit))
    try:
        items = await asyncio.wait_for(
            asyncio.to_thread(suggest_radar_symbols, q, limit=lim),
            timeout=2.5,
        )
    except asyncio.TimeoutError:
        import re

        from apps.copilot.modules.radar.symbol_resolve import _name_from_cache_or_sot

        digits = re.sub(r"\D", "", q or "")
        if len(digits) >= 6:
            sym = digits[-6:]
            items = [{"symbol": sym, "name": _name_from_cache_or_sot(sym), "score": 1.0}]
        else:
            items = []
    return {
        "query": q,
        "items": items,
        "index_ready": market_name_index_ready(),
    }


@router.post("/api/radar/collect")
async def api_radar_collect_by_query(
    request: Request,
    query_text: str = Form(...),
):
    """启动后台 T0+T1 采集（表单 query_text · 避免路径编码问题）。"""
    try:
        redis_client = _sync_redis()
        _job_id, state = _start_radar_collect(query_text, redis_client)
    except RadarSymbolResolveError as exc:
        if request.headers.get("hx-request") or "text/html" in request.headers.get(
            "accept", ""
        ):
            return HTMLResponse(_render_radar_resolve_error_html(str(exc)))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_collect_progress_panel(state))
    return {"job_id": state["job_id"], "status": "running"}


@router.post("/api/radar/data/{symbol}/collect")
async def api_radar_collect_t0(
    symbol: str,
    request: Request,
):
    """启动后台 T0+T1 采集；立即返回进度面板（兼容旧路径）。"""
    try:
        redis_client = _sync_redis()
        _job_id, state = _start_radar_collect(symbol, redis_client)
    except RadarSymbolResolveError as exc:
        if request.headers.get("hx-request") or "text/html" in request.headers.get(
            "accept", ""
        ):
            return HTMLResponse(_render_radar_resolve_error_html(str(exc)))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_collect_progress_panel(state))
    return {"job_id": state["job_id"], "status": "running"}


@router.get("/api/radar/collect/jobs/{job_id}")
async def api_radar_collect_job_status(
    job_id: str,
    request: Request,
):
    """采集任务进度（HTML 片段 · 未完成时每 1s 由 HTMX 轮询）。"""
    redis_client = _sync_redis()
    state = load_collect_job(redis_client, job_id)
    if not state:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_collect_progress_panel(state))
    return state


@router.get("/api/radar/collect-symbols")
async def api_radar_collect_symbols(
    session: AsyncSession = Depends(get_db),
    enabled_only: bool = False,
):
    """基础数据采集标的列表（T0 universe SoT）。"""
    rows = await list_collect_symbol_rows(session, enabled_only=enabled_only)
    return {"items": [row_to_dict(r) for r in rows], "count": len(rows)}


@router.patch("/api/radar/collect-symbols/{symbol}")
async def api_radar_collect_symbol_patch(
    symbol: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """启用/停用采集列表中的标的。"""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="需要 JSON body") from exc
    if "enabled" not in body:
        raise HTTPException(status_code=400, detail="缺少 enabled 字段")
    row = await set_collect_symbol_enabled(session, symbol, enabled=bool(body["enabled"]))
    if row is None:
        raise HTTPException(status_code=404, detail="标的不在采集列表中")
    await session.commit()
    return row_to_dict(row)


@router.delete("/api/radar/collect-symbols/{symbol}")
async def api_radar_collect_symbol_delete(
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    """软删：enabled=false（保留历史采集记录）。"""
    row = await set_collect_symbol_enabled(session, symbol, enabled=False)
    if row is None:
        raise HTTPException(status_code=404, detail="标的不在采集列表中")
    await session.commit()
    return row_to_dict(row)


@router.post("/api/funnel/symbols/{symbol}/demote")
async def api_funnel_demote(
    symbol: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    row = await demote_symbol_one_stage(session, symbol)
    if row is None:
        raise HTTPException(status_code=404, detail="标的未在漏斗中")
    await session.commit()
    if request.headers.get("hx-request"):
        return await _radar_candidates_html_response(
            session,
            flash=f"已降级 {display_name_for_symbol(row.symbol, row.name, allow_network=False)} · 当前阶段 {row.funnel_stage}",
        )
    return {"symbol": row.symbol, "funnel_stage": row.funnel_stage}


@router.post("/api/funnel/symbols/{symbol}/remove")
async def api_funnel_remove_ui(
    symbol: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    row = await hide_symbol_ui(session, symbol)
    if row is None:
        raise HTTPException(status_code=404, detail="标的未在漏斗中")
    await session.commit()
    if request.headers.get("hx-request"):
        return await _radar_candidates_html_response(
            session,
            flash=f"已从候选区移除 {display_name_for_symbol(row.symbol, row.name, allow_network=False)}",
        )
    return {"symbol": row.symbol, "ui_removed_at": row.ui_removed_at.isoformat()}


async def _latest_scan_context(session: AsyncSession, symbol: str) -> dict | None:
    sym = symbol.zfill(6)[-6:]
    row = await session.scalar(
        select(RadarCandidate)
        .where(RadarCandidate.symbol == sym)
        .order_by(RadarCandidate.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    raw = row.raw_json or {}
    return {
        "name": row.name,
        "symbol": row.symbol,
        "deep_analysis": raw.get("deep_analysis") or {},
    }


@router.post("/api/radar/chat")
async def api_radar_chat(
    request: Request,
    session: AsyncSession = Depends(get_db),
    message: str = Form(...),
    session_id: str = Form(""),
    symbol: str = Form(""),
    model_id: str = Form(""),
    jl13_data_prompt: str = Form(""),
    force_base: str = Form(""),
    force_jl13: str = Form(""),
    force_jl4: str = Form(""),
    force_9d: str = Form(""),
):
    """Opus 多轮日常对话（HTMX 返回聊天气泡 HTML）。
    首轮自动携带 JL/JL4 全量数据；后续轮仅轻量 system 省 token。
    勾选「基础/JL1-3/JL4/9维」可在任意轮次强制重取对应数据。
    """
    import logging

    log = logging.getLogger(__name__)

    redis_client = _sync_redis()
    sym: str | None = (symbol or "").strip() or None
    if sym:
        try:
            sym, _ = resolve_radar_query(sym)
        except RadarSymbolResolveError:
            sym = sym.zfill(6)[-6:] if sym.isdigit() else None

    force_flags = {
        "base": bool((force_base or "").strip() == "1"),
        "jl13": bool((force_jl13 or "").strip() == "1"),
        "jl4": bool((force_jl4 or "").strip() == "1"),
        "9d": bool((force_9d or "").strip() == "1"),
    }
    log.info("radar_chat sym=%s force=%s", sym, force_flags)

    try:
        result = await chat_turn(
            redis_client,
            session_id=session_id,
            user_message=message,
            symbol=sym,
            jl13_data_prompt=jl13_data_prompt,
            model_id=model_id or None,
            db_session=session,
            force_refresh=force_flags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_chat_panel(result))
    return result


@router.post("/api/radar/chat/new")
async def api_radar_chat_new(
    request: Request,
    session_id: str = Form(""),
    session: AsyncSession = Depends(get_db),
):
    """清空当前会话，开始新对话。"""
    from apps.copilot.modules.radar.chat import clear_session_async

    await clear_session_async(session_id, redis_client=_sync_redis(), db_session=session)
    await session.commit()
    payload = {"session_id": new_session_id(), "messages": [], "status": "new"}
    if request.headers.get("hx-request"):
        return HTMLResponse(_render_chat_panel(payload))
    return payload


@router.post("/api/radar/chat/edit")
async def api_radar_chat_edit(
    request: Request,
    session: AsyncSession = Depends(get_db),
    session_id: str = Form(""),
    message_idx: str = Form("0"),
    new_text: str = Form(""),
    symbol: str = Form(""),
    force_base: str = Form(""),
    force_jl13: str = Form(""),
    force_jl4: str = Form(""),
    force_9d: str = Form(""),
):
    """编辑已发送消息并重新生成回复。截断指定消息后的内容，替换为新文本+可选标的+数据开关后重发 AI。"""
    import logging
    from apps.copilot.modules.radar.chat import (
        chat_turn,
        load_messages_async,
        save_messages_async,
    )

    log = logging.getLogger(__name__)
    redis_client = _sync_redis()
    sid = (session_id or "").strip()
    idx = int(message_idx) if message_idx.isdigit() else 0
    text = (new_text or "").strip()
    sym = (symbol or "").strip() or None
    if not sid or not text:
        raise HTTPException(status_code=400, detail="缺少 session_id 或 new_text")

    existing = await load_messages_async(sid, redis_client=redis_client, db_session=session)
    # 截断 idx 及之后的消息（不提前 save，chat_turn 成功后自己会存）
    truncated = existing[:idx]
    # 注入内存缓存让 chat_turn 读到截断后的历史（防 race）
    from apps.copilot.modules.radar import chat as radar_chat_mod
    radar_chat_mod._memory_sessions[sid] = truncated

    force_refresh: dict[str, bool] = {}
    for k, v in {"base": force_base, "jl13": force_jl13, "jl4": force_jl4, "9d": force_9d}.items():
        if v and v.lower() in ("on", "true", "1", "yes"):
            force_refresh[k] = True

    try:
        result = await chat_turn(
            redis_client,
            session_id=sid,
            user_message=text,
            symbol=sym,
            model_id=None,
            db_session=session,
            force_refresh=force_refresh if force_refresh else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_chat_panel(result))
    return result


@router.post("/api/radar/chat/delete")
async def api_radar_chat_delete(
    session_id: str = Form(""),
    session: AsyncSession = Depends(get_db),
):
    """删除一个聊天会话（Redis + PG）。"""
    from apps.copilot.modules.radar.chat import clear_session_async

    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    await clear_session_async(sid, redis_client=_sync_redis(), db_session=session)
    await session.commit()
    return {"deleted": sid}

    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_chat_panel(result))
    return result


@router.get("/api/radar/chat/sessions")
async def api_radar_chat_sessions(
    session: AsyncSession = Depends(get_db),
    limit: int = 40,
):
    from apps.copilot.modules.radar.chat import list_radar_chat_sessions

    return {"sessions": await list_radar_chat_sessions(session, limit=limit)}


@router.get("/api/radar/query-history")
async def api_radar_query_history_get(session: AsyncSession = Depends(get_db)):
    from apps.copilot.modules.copilot_ui_settings import load_query_history

    return await load_query_history(session)


@router.post("/api/radar/query-history")
async def api_radar_query_history_post(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.modules.copilot_ui_settings import remember_query

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="需要 JSON 请求体") from exc
    q = (body.get("query") if isinstance(body, dict) else "") or ""
    result = await remember_query(session, q)
    await session.commit()
    return result


@router.get("/api/radar/chat/{session_id}")
async def api_radar_chat_history(
    session_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """拉取会话历史（HTML 片段）。"""
    from apps.copilot.modules.radar.chat import load_messages_async

    messages = await load_messages_async(
        session_id, redis_client=_sync_redis(), db_session=session
    )
    payload = {"session_id": session_id, "messages": messages, "status": "ok"}
    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_chat_panel(payload))
    return payload


@router.get("/api/radar/audit/{symbol}/{version_id}")
async def api_radar_audit_bundle(
    symbol: str,
    version_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """指定版本的 T0/T1/T2 bundle。"""
    try:
        sym, name = resolve_radar_query(symbol)
    except RadarSymbolResolveError:
        sym = symbol.zfill(6)[-6:] if symbol.isdigit() else symbol
        name = sym
    bundle = await load_version_merged(session, sym, version_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="版本不存在或已超出保留期")
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        html_body = render_audit_page(
            symbol=sym,
            name=str(bundle.get("name") or name),
            versions=list_versions(sym),
            selected_version_id=version_id,
            bundle=bundle,
        )
        return HTMLResponse(html_body)
    return bundle


@router.post("/api/radar/candidates/{candidate_id}/promote")
async def api_promote_candidate(
    request: Request,
    candidate_id: int,
    session: AsyncSession = Depends(get_db),
    new_theme: str | None = Form(None),
    campaign_id: int | None = Form(None),
    board_id: int | None = Form(None),
    phase_id: int | None = Form(None),
    role_tag: str | None = Form(None),
    add_to_watchlist: str | None = Form(None),
    skip_tags: str | None = Form(None),
):
    from apps.copilot.modules.strategic.service import upsert_primary_strategic_tag

    redis_client = _sync_redis()
    try:
        result = await promote_candidate(
            session,
            candidate_id,
            new_theme=new_theme,
            campaign_id=campaign_id,
            redis_client=redis_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sym = result.get("symbol", "")
    skip = str(skip_tags or "").lower() in ("1", "true", "on", "yes")
    if not skip and board_id and phase_id:
        await upsert_primary_strategic_tag(
            session,
            sym,
            board_id=int(board_id),
            phase_id=int(phase_id),
            role_tag=(role_tag or "").strip() or None,
            tagged_from="radar",
            add_to_watchlist=str(add_to_watchlist or "").lower() in ("1", "true", "on", "yes"),
        )
    await session.commit()
    if request.headers.get("hx-request"):
        sym = result.get("symbol", "")
        return await _radar_candidates_html_response(
            session,
            flash=(
                f"✓ {display_name_for_symbol(sym, result.get('name'), allow_network=False)} "
                f"({sym}) 已晋级到「{workspace_display_name('planning')}」· "
                f"可切到 📝 {get_workspace('planning').tab_label} Tab"
            ),
        )
    return result


def _render_campaigns_html(items: list, *, view: str | None = None) -> HTMLResponse:
    if not items:
        hint = {
            "planning": "暂无规划中 Campaign",
            "executing": "暂无执行中 Campaign（节点触发后将自动归入）",
        }.get(view or "", "暂无 Campaign · 运行 make copilot-step12-campaign 导入持仓")
        return HTMLResponse(
            f"<p class='text-sm text-gray-500 py-4 text-center'>{hint}</p>"
        )

    blocks: list[str] = []
    for c in items:
        syms_html = "".join(
            f'<a href="/api/campaigns/{c["id"]}/symbols/{s["symbol"]}"'
            f' class="inline-flex items-center gap-1 text-sm font-semibold text-gray-800'
            f' hover:text-blue-600 transition-colors">'
            f'{s["name"]}'
            f'<span class="text-gray-400 font-normal text-xs">{s["symbol"]}</span>'
            f'</a>'
            for s in c.get("symbols", [])
            if s.get("symbol")
        )
        nodes = c.get("nodes") or []
        node_lines = "".join(
            f"<li class='flex items-start gap-2 text-sm text-gray-600'>"
            f"<span class='inline-block mt-0.5 px-1.5 py-0.5 rounded text-xs font-mono"
            f" bg-gray-100 text-gray-500'>{n['status']}</span>"
            f"<span>{n['name']} — {n.get('advice_action', '')[:60]}</span></li>"
            for n in nodes
        )
        node_ul = ""
        if node_lines:
            node_ul = (
                '<ul class="mt-3 space-y-1 border-l-2 border-gray-100 pl-3">'
                + node_lines
                + "</ul>"
            )
        status_color = "bg-blue-50 text-blue-600" if c["status"] == "planning" else "bg-green-50 text-green-600"
        syms_display = syms_html if syms_html else "<span class='text-gray-400'>无</span>"
        blocks.append(
            f"<div class='border border-gray-100 rounded-lg p-4 mb-3 hover:shadow-sm transition-shadow'>"
            f"<div class='flex items-center gap-2 mb-2'>"
            f"<span class='font-semibold text-gray-900'>{c['theme']}</span>"
            f"<span class='text-xs px-2 py-0.5 rounded-full font-medium {status_color}'>{c['status']}</span>"
            f"</div>"
            f"<div class='flex flex-wrap gap-2 text-sm'>标的：{syms_display}</div>"
            f"{node_ul}"
            f"<div class='mt-3 flex flex-wrap gap-2'>"
            f"<a href='/api/campaigns/{c['id']}/planning-panel' "
            f"class='text-sm text-blue-600 hover:underline'>证伪监控面板</a>"
            f"</div>"
            f"</div>"
        )
    return HTMLResponse("\n".join(blocks))


def _render_timeline_html(items: list) -> HTMLResponse:
    if not items:
        return HTMLResponse(
            "<p class='text-sm text-gray-500 py-4 text-center'>暂无时间轴节点 · 导入持仓后会生成默认复盘节点</p>"
        )
    rows = [
        f"<li class='flex items-baseline gap-3 py-2 border-b border-gray-50 last:border-0'>"
        f"<span class='font-mono text-sm font-semibold text-gray-700 shrink-0'>{e['anchor_date']}</span>"
        f"<span class='text-gray-800'>{e['title']}</span>"
        f"<span class='text-xs text-gray-400 ml-auto shrink-0'>{e['campaign_theme']} · {e['status']}</span>"
        f"</li>"
        for e in items
    ]
    return HTMLResponse('<ul class="divide-y divide-gray-50">' + "".join(rows) + "</ul>")


_HORIZON_CHIP = {
    "single": ("单次", "bg-gray-100 text-gray-600"),
    "short": ("短期", "bg-blue-50 text-blue-700"),
    "mid": ("中期", "bg-amber-50 text-amber-800"),
    "long_multiwave": ("长期多波", "bg-purple-50 text-purple-800"),
}


def _render_roadmap_timeline_html(items: list, campaign_id: int) -> HTMLResponse:
    if not items:
        return HTMLResponse(
            f"<p class='text-sm text-gray-500 py-4'>Campaign #{campaign_id} 暂无时间线节点 · "
            f"从雷达候选 POST timeline 或 make copilot-step15-timeline</p>"
        )
    blocks: list[str] = []
    for e in items:
        flags = e.get("feasibility_flags") or []
        flag_html = "".join(
            f"<span class='text-xs px-2 py-0.5 rounded-full mr-1 "
            f"{'bg-red-50 text-red-700' if f else 'bg-yellow-50 text-yellow-800'}'>"
            f"{f}</span>"
            for f in flags
        )
        adv = e.get("advisories") or []
        adv_html = (
            "<ul class='mt-2 text-xs text-amber-700 list-disc pl-4'>"
            + "".join(f"<li>{a}</li>" for a in adv[:3])
            + "</ul>"
            if adv
            else ""
        )
        sym = e.get("symbol") or "—"
        ok_span = '<span class="text-xs text-green-600">✓ 合理性 OK</span>'
        flag_row = flag_html or ok_span
        border_cls = "border-red-200 bg-red-50/30" if flags else "bg-white"
        blocks.append(
            f"<div class='border border-gray-100 rounded-lg p-3 mb-2 {border_cls}'>"
            f"<div class='flex flex-wrap items-center gap-2 mb-1'>"
            f"<span class='text-xs font-mono bg-gray-100 px-2 py-0.5 rounded'>#{e.get('sequence_no', '—')}</span>"
            f"<span class='font-semibold text-gray-900'>{e['title']}</span>"
            f"<span class='text-gray-400 text-sm'>{sym}</span>"
            f"</div>"
            f"<div class='text-xs text-gray-500 mb-1'>"
            f"窗口 {e.get('window_start', '?')} → {e.get('window_end', '?')} · "
            f"爆发 {e['anchor_date']} · 建仓门槛 {e.get('build_lead_days', 15)} 交易日"
            f"</div>"
            f"<div class='flex flex-wrap gap-1'>{flag_row}</div>"
            f"{adv_html}"
            f"</div>"
        )
    return HTMLResponse("".join(blocks))


_PHASE_LABEL = {
    "concept": ("🌱 炒概念", "bg-emerald-50 text-emerald-700"),
    "expectation": ("📈 炒预期", "bg-blue-50 text-blue-700"),
    "realization": ("💰 炒业绩", "bg-amber-50 text-amber-800"),
    "exhaustion": ("🍂 利好出尽", "bg-gray-100 text-gray-600"),
}


def _phase_chip(phase: str | None) -> str:
    from apps.copilot.modules.planning.workspace_render import render_phase_chip

    return render_phase_chip(phase)


def _render_collect_progress_panel(state: dict) -> str:
    """T0 采集进度条 + 分步清单（运行中可 HTMX 轮询）。"""
    job_id = _esc(state.get("job_id") or "")
    status = state.get("status") or "running"
    sym = _esc(state.get("symbol") or "")
    name = _esc(state.get("name") or "")
    pct = int(state.get("pct") or 0)
    step_label = _esc(state.get("step_label") or "采集中…")
    detail = _esc(state.get("detail") or "")
    steps_done = set(state.get("steps_done") or [])

    step_rows: list[str] = []
    for sid, label, _bound in COLLECT_STEP_ORDER:
        if sid == "done":
            continue
        if status == "done" or sid in steps_done:
            icon = "✅"
            cls = "text-emerald-700"
        elif state.get("step") == sid and status == "running":
            icon = "⏳"
            cls = "text-blue-700 font-medium"
        else:
            icon = "○"
            cls = "text-gray-400"
        step_rows.append(
            f"<li class='flex items-center gap-2 text-xs {cls}'>"
            f"<span class='w-4 text-center'>{icon}</span><span>{_esc(label)}</span></li>"
        )

    poll_attrs = ""
    if status == "running":
        poll_attrs = (
            f" id='radar-collect-progress' data-job-id='{job_id}' data-running='1'"
            f" hx-get='/api/radar/collect/jobs/{job_id}'"
            f" hx-trigger='every 1s'"
            f" hx-swap='outerHTML'"
        )
    elif status == "error":
        poll_attrs = f" id='radar-collect-progress' data-job-id='{job_id}' data-done='1' data-error='1'"
    else:
        poll_attrs = f" id='radar-collect-progress' data-job-id='{job_id}' data-done='1'"

    bar_color = "bg-emerald-500" if status == "done" else "bg-blue-500"
    if status == "error":
        bar_color = "bg-red-400"

    header = (
        f"<div class='flex flex-wrap items-center justify-between gap-2 mb-2'>"
        f"<span class='text-sm font-semibold text-gray-800'>"
        f"📦 T0 采集 · {name} <span class='font-mono text-gray-500'>{sym}</span></span>"
        f"<span class='text-xs text-gray-500'>{pct}%</span></div>"
    )
    bar = (
        f"<div class='h-2 rounded-full bg-gray-100 overflow-hidden mb-2'>"
        f"<div class='h-full {bar_color} transition-all duration-500' "
        f"style='width:{pct}%'></div></div>"
    )
    detail_html = f' <span class="text-gray-400">— {detail}</span>' if detail else ""
    current = f"<p class='text-sm text-gray-700 mb-2'>{step_label}{detail_html}</p>"
    steps_ul = f"<ul class='space-y-1 mb-3 border-t border-gray-100 pt-2'>{''.join(step_rows)}</ul>"

    footer = ""
    if status == "done":
        res = state.get("result") or {}
        vid = _esc(res.get("version_id") or "")
        ok = res.get("t0_ok_parts", "?")
        enrolled = res.get("enrolled_in_collect_list")
        enrolled_note = " · 已纳入基础数据采集列表" if enrolled else ""
        footer = (
            f"<div class='text-sm text-green-800 bg-green-50 rounded-lg px-3 py-2'>"
            f"✓ 采集完成 · 版本 <span class='font-mono'>{vid}</span> · "
            f"T0 就绪 {ok}/4{enrolled_note} · "
            f"<a class='text-blue-600 underline' href='/audit?symbol={sym}'>"
            f"数据审计</a></div>"
        )
    elif status == "error":
        err = _esc(state.get("error") or "未知错误")
        footer = (
            f"<div class='text-sm text-red-800 bg-red-50 rounded-lg px-3 py-2'>"
            f"⚠️ 采集失败：{err}</div>"
        )
    elif status == "running":
        footer = (
            "<p class='text-[11px] text-gray-400 flex items-center gap-2'>"
            "<svg class='animate-spin h-3 w-3' fill='none' viewBox='0 0 24 24'>"
            "<circle class='opacity-25' cx='12' cy='12' r='10' stroke='currentColor' stroke-width='4'/>"
            "<path class='opacity-75' fill='currentColor' d='M4 12a8 8 0 018-8v8H4z'/></svg>"
            "自动刷新进度（约 30～120 秒，视网络而定）</p>"
        )

    return (
        f"<div class='rounded-xl border border-emerald-100 bg-emerald-50/40 p-4'{poll_attrs}>"
        f"{header}{bar}{current}{steps_ul}{footer}</div>"
    )


def _render_context_meta_banner(payload: dict) -> str:
    cm = payload.get("context_meta") or {}
    if not cm:
        return ""
    mode = cm.get("context_mode") or "none"
    if mode == "none":
        return ""
    sym = _esc(cm.get("symbol") or "—")
    lines: list[str]
    tone: str
    if mode == "cached_context":
        lines = [f"上下文 · {sym} · 沿用首轮缓存", _esc(cm.get("note") or "")]
        tone = "border-blue-200 bg-blue-50 text-blue-800"
    elif mode == "t1_envelope":
        lines = [
            f"上下文 · {sym} · 模式 t1_envelope",
            f"JL4 指标 {cm.get('jl4_indicator_count', 0)} 个 · "
            f"system {cm.get('system_prompt_chars', 0)} 字",
        ]
        tone = "border-emerald-200 bg-emerald-50 text-emerald-800"
    elif mode in ("radar_scan_fallback", "symbol_only"):
        lines = [f"上下文 · {sym} · 模式 {mode}", _esc(cm.get("note") or "")]
        tone = "border-amber-200 bg-amber-50 text-amber-900"
    else:
        lines = [f"上下文 · {sym} · 模式 {mode}", _esc(cm.get("note") or "")]
        tone = "border-gray-200 bg-gray-50 text-gray-700"
    body = " · ".join(lines)
    return (
        f"<div class='mx-2 mb-2 rounded-lg border px-3 py-1.5 text-[10px] {tone}'>"
        f"{body}</div>"
    )


def _render_chat_panel(payload: dict) -> str:
    """Opus 风格对话区 HTML · Markdown 渲染 + 消息编辑 + cost 信息集成。"""
    sid = _esc(payload.get("session_id") or new_session_id())
    messages = payload.get("messages") or []
    err = payload.get("error")
    status = payload.get("status")

    bubbles: list[str] = []
    if not messages and status in ("new", None):
        bubbles.append(
            "<div class='flex flex-col items-center justify-center py-16 text-center'>"
            "<div class='w-12 h-12 rounded-full bg-violet-100 flex items-center justify-center mb-4'>"
            "<span class='text-2xl'>💬</span></div>"
            "<p class='text-sm font-medium text-gray-700 mb-1'>开始与 Opus 对话</p>"
            "<p class='text-xs text-gray-400 max-w-[280px] leading-relaxed'>"
            "可问产业逻辑、财报解读、估值框架、风险识别等；"
            "可选填标的代码以附带最近扫描结论</p></div>"
        )

    prev_role = None
    for i, m in enumerate(messages):
        role = m.get("role")
        content = _esc(m.get("content") or "")
        is_consecutive = role == prev_role
        prev_role = role

        if role == "user":
            msg_id = f"radar-msg-{i}"
            gap = "mt-1" if is_consecutive else "mt-4 first:mt-0"
            bubbles.append(
                f"<div class='flex justify-end group/msg {gap}' id='{msg_id}' data-msg-idx='{i}'>"
                f"<div class='opus-user-bubble max-w-[82%] rounded-2xl rounded-tr-md "
                f"bg-gradient-to-br from-violet-600 to-purple-700 text-white px-4 py-2.5 text-sm "
                f"leading-relaxed shadow-[0_2px_8px_rgba(124,58,237,0.18)] relative'>"
                f"<span class='msg-text'>{content}</span>"
                f"<button type='button' class='msg-edit-btn absolute -top-2 -right-2 opacity-0 group-hover/msg:opacity-100 "
                f"w-6 h-6 rounded-full bg-white text-violet-600 hover:bg-violet-50 shadow text-[13px] "
                f"flex items-center justify-center transition-opacity' "
                f"title='编辑' aria-label='编辑消息'>✎</button>"
                f"</div></div>"
            )
        elif role == "assistant":
            meta = m.get("meta") or {}
            cost_line = ""
            if meta.get("cost_yuan") is not None:
                cost_line = (
                    f"<span class='opus-cost-pill'>"
                    f"¥{float(meta['cost_yuan']):.4f}"
                    f"<span class='opus-cost-model'>{_esc(meta.get('model') or '')}</span>"
                    f"</span>"
                )
            gap = "mt-1.5" if is_consecutive else "mt-4 first:mt-0"
            bubbles.append(
                f"<div class='flex justify-start msg-md-block {gap}'>"
                f"<div class='opus-assistant-bubble max-w-[90%] rounded-2xl rounded-tl-md "
                f"bg-white border border-gray-100 px-5 py-3 text-sm text-gray-800 leading-relaxed "
                f"shadow-[0_1px_3px_rgba(0,0,0,0.04)] msg-md-content prose prose-sm max-w-none'>"
                f"{content}</div>"
                f"<script type='md-tail'>{cost_line}</script>"
                f"</div>"
            )

    err_html = ""
    if err:
        err_html = (
            f"<div class='mx-3 mb-3 rounded-xl border border-red-100 bg-red-50 px-4 py-3 "
            f"text-sm text-red-700 flex items-start gap-2'>"
            f"<span class='text-base shrink-0 mt-0.5'>⚠️</span>"
            f"<span>{_esc(err)}</span></div>"
        )

    meta_html = ""
    if payload.get("cost_yuan") is not None and status == "ok":
        meta_html = (
            f"<div class='flex justify-center mt-3'>"
            f"<span class='opus-cost-pill'>¥{float(payload['cost_yuan']):.4f}"
            f"<span class='opus-cost-model'>{_esc(payload.get('model') or '')}</span></span>"
            f"</div>"
        )

    return (
        f"<div id='radar-chat-inner' data-session-id='{sid}'>"
        f"<input type='hidden' name='session_id' id='radar-chat-session-id' value='{sid}'>"
        f"{err_html}"
        f"{_render_context_meta_banner(payload)}"
        f"<div class='px-2 py-3 min-h-[160px] flex flex-col'>{''.join(bubbles)}</div>"
        f"{meta_html}"
        f"<script>window.opusRenderMarkdown();window.opusBindMsgEdit();</script>"
        f"</div>"
    )


def _render_radar_candidates_html(
    items: list, *, flash: str = "", tags_map: dict | None = None
) -> HTMLResponse:
    """雷达扫描候选卡（待晋级 → planning）；片段 HTML，由 #radar-candidates-list 容器 hx-swap 注入。"""
    from apps.copilot.modules.strategic.render import render_strategic_chip

    tags_map = tags_map or {}
    flash_html = ""
    if flash:
        flash_html = (
            f"<div class='mb-2 text-sm text-green-800 bg-green-50 border border-green-100 "
            f"rounded-lg px-3 py-2'>{_esc(flash)}</div>"
        )
    if not items:
        return HTMLResponse(
            f"{flash_html}"
            "<p class='text-sm text-gray-500 py-4 text-center'>"
            "暂无近 7 日分析候选 · 上方输入标的启动扫描</p>"
        )
    cards: list[str] = []
    for c in items:
        sym = c.get("symbol", "")
        scan_id = c.get("scan_id")
        sym_esc = _esc(sym)
        display = _esc(display_name_for_symbol(sym, c.get("name"), allow_network=False))
        promoted = c.get("already_promoted")
        conf = c.get("confidence")
        conf_txt = f"{conf:.0%}" if conf is not None else "—"
        title_inner = (
            f"<span class='block font-semibold text-gray-900 leading-tight'>{display}</span>"
            f"<span class='block text-xs text-gray-400 font-mono mt-0.5'>{sym_esc}</span>"
        )
        if scan_id:
            title = (
                f"<button type='button' "
                f"class='radar-candidate-load hover:text-blue-700 hover:underline cursor-pointer text-left "
                f"bg-transparent border-0 p-0' "
                f"title='加载深度分析报告' "
                f"data-scan-id='{int(scan_id)}' "
                f"hx-get='/api/radar/scans/{int(scan_id)}' "
                f"hx-target='#radar-scan-result' hx-swap='innerHTML' "
                f"hx-indicator='#radar-scan-loading' "
                f"hx-headers='{{\"Accept\":\"text/html\",\"HX-Request\":\"true\","
                f"\"X-Radar-View-Mode\":\"cached\"}}'>"
                f"{title_inner}</button>"
            )
        else:
            title = f"<div>{title_inner}</div>"
        cid = c.get("id")
        sym_raw = sym
        promote_btn = ""
        if not promoted and cid:
            promote_btn = (
                f"<button type='button' "
                f"hx-get='/api/strategic/promote-modal/radar/{int(cid)}' "
                f"hx-target='#strategic-promote-modal-root' hx-swap='innerHTML' "
                f"class='text-sm px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700'>"
                f"➕ 晋级规划</button>"
            )
        elif promoted:
            promote_btn = (
                "<span class='text-xs px-2 py-1 rounded bg-green-50 text-green-700'>"
                "✓ 已在规划区</span>"
            )
        demote_btn = (
            f"<form hx-post='/api/funnel/symbols/{sym_raw}/demote' "
            f"hx-target='#radar-candidates-list' hx-swap='innerHTML' class='inline'>"
            f"<button type='submit' class='text-xs px-2 py-1 rounded border border-amber-200 "
            f"text-amber-800 hover:bg-amber-50'>降级</button></form>"
        )
        remove_btn = (
            f"<form hx-post='/api/funnel/symbols/{sym_raw}/remove' "
            f"hx-target='#radar-candidates-list' hx-swap='innerHTML' class='inline'>"
            f"<button type='submit' class='text-xs px-2 py-1 rounded border border-gray-200 "
            f"text-gray-600 hover:bg-gray-100'>移除</button></form>"
        )
        action = (
            f"<div class='flex flex-wrap gap-2 justify-end'>"
            f"{promote_btn}{demote_btn}{remove_btn}</div>"
        )
        chip = render_strategic_chip(tags_map.get(sym_raw), symbol=sym_raw, editable=False)
        cards.append(
            f"<div class='flex items-center justify-between p-3 mb-2 rounded-lg"
            f" bg-gray-50 border border-gray-100'>"
            f"<div class='flex items-center gap-3 flex-wrap'>"
            f"{title}"
            f"{chip}"
            f"{_phase_chip(c.get('market_phase'))}"
            f"<span class='text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700'>置信 {conf_txt}</span>"
            f"</div>"
            f"<div class='shrink-0 ml-4'>{action}</div>"
            f"</div>"
        )
    return HTMLResponse(f"{flash_html}{''.join(cards)}")


def _render_workspace_symbols_html(
    items: list,
    *,
    view: str,
    container_id: int,
    t2_summaries: dict | None = None,
    tags_map: dict | None = None,
    tag_options: list | None = None,
    tag_suggested: dict | None = None,
    jl_summaries: dict | None = None,
) -> HTMLResponse:
    """规划/执行区标的卡（标的级漏斗联动渲染）。"""
    from apps.copilot.modules.planning.workspace_render import (
        render_executing_symbol_card,
        render_planning_symbol_card,
        render_workspace_symbol_list,
    )
    from apps.copilot.modules.strategic.render import render_strategic_chip

    t2_summaries = t2_summaries or {}
    tags_map = tags_map or {}
    tag_options = tag_options or []
    tag_suggested = tag_suggested or {}
    jl_summaries = jl_summaries or {}
    if not items:
        hint = {
            "planning": f"{workspace_display_name('planning')}暂无标的 · 从机会雷达晋级，或导入持仓",
            "executing": f"{workspace_display_name('executing')}暂无标的 · 在买入论证台人工确认晋级",
            "ledger": f"{workspace_display_name('ledger')}暂无归档标的",
        }.get(view, "暂无标的")
        return HTMLResponse(f"<p class='text-sm text-gray-500 py-6 text-center'>{hint}</p>")

    cards: list[str] = []
    if view == "planning":
        for s in items:
            sym = s.get("symbol", "")
            cards.append(
                render_planning_symbol_card(
                    s,
                    container_id=container_id,
                    tags_map=tags_map,
                    render_strategic_chip=render_strategic_chip,
                )
            )
    else:
        from apps.copilot.modules.executing.t2_advice_summary import render_executing_t2_banner

        for s in items:
            sym = s.get("symbol", "")
            cards.append(
                render_executing_symbol_card(
                    s,
                    container_id=container_id,
                    t2_summaries=t2_summaries,
                    tags_map=tags_map,
                    render_strategic_chip=render_strategic_chip,
                    render_executing_t2_banner=render_executing_t2_banner,
                )
            )

    html = render_workspace_symbol_list(cards, view=view, count=len(items))
    wrap_cls = "executing-workspace-list" if view == "executing" else "planning-workspace-list"
    return HTMLResponse(f'<div class="{wrap_cls}">{html}</div>')


def _render_radar_html(items: list) -> HTMLResponse:
    if not items:
        return HTMLResponse(
            "<p class='text-sm text-gray-500 py-4 text-center'>暂无监控标的</p>"
        )
    cards = []
    for s in items:
        cid, sym = s["campaign_id"], s["symbol"]
        cards.append(
            f"<div class='flex items-center justify-between p-3 mb-2 rounded-lg"
            f" bg-gray-50 hover:bg-blue-50 border border-gray-100 hover:border-blue-200"
            f" transition-all group'>"
            f"<div>"
            f"<span class='font-semibold text-gray-900 group-hover:text-blue-700'>{s['name']}</span>"
            f"<span class='text-gray-400 text-sm ml-2'>{sym}</span>"
            f"<span class='ml-3 text-xs text-gray-500'>{s['campaign_theme']}</span>"
            f"</div>"
            f"<a href='/api/campaigns/{cid}/symbols/{sym}'"
            f" class='text-blue-500 text-sm hover:text-blue-700 hover:underline cursor-pointer shrink-0 ml-4'>"
            f"6 维档案 JSON</a>"
            f"</div>"
        )
    return HTMLResponse("".join(cards))


def _render_promote_executing_form(
    campaign_id: int,
    symbol: str,
    *,
    compact: bool = False,
    tag_options: list | None = None,
    tag_suggested: dict | None = None,
    current_tag: dict | None = None,
) -> str:
    from apps.copilot.modules.planning.workspace_render import render_promote_executing_form

    _ = (tag_options, tag_suggested, current_tag)  # 战略归属改由弹窗设置
    return render_promote_executing_form(campaign_id, symbol, compact=compact)


def _esc(v) -> str:
    return _html.escape(str(v)) if v is not None else ""


def _conf_bar(conf) -> str:
    try:
        pct = max(0, min(100, int(round(float(conf) * 100))))
    except (TypeError, ValueError):
        pct = 0
    color = "bg-emerald-500" if pct >= 70 else ("bg-amber-500" if pct >= 40 else "bg-gray-400")
    return (
        f"<div class='flex items-center gap-1.5 mt-1'>"
        f"<div class='flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden'>"
        f"<div class='h-full {color}' style='width:{pct}%'></div></div>"
        f"<span class='text-[11px] text-gray-400'>{pct}%</span></div>"
    )


def _verdict_badge(text: str) -> str:
    return (
        f"<span class='text-xs font-semibold px-2 py-0.5 rounded-full "
        f"bg-indigo-50 text-indigo-700 border border-indigo-100'>{_esc(text)}</span>"
    )


def _parse_reasoning_blocks(text: str) -> list[tuple[str | None, str, str | None]]:
    """将推理文本拆为 (序号, 小标题, 正文) 列表；序号为 None 表示引言段。"""
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return []

    # 仅识别中文序号 1）2）、1、2、，避免把小数 3.86 误判为列表
    segments = [
        s.strip()
        for s in re.split(r"(?:(?<=[；。!！?？\n])|^)\s*(?=\d{1,2}[、）)）]\s*)", raw)
        if s.strip()
    ]
    blocks: list[tuple[str | None, str, str | None]] = []

    for seg in segments:
        m = re.match(r"^(\d{1,2})(?:[、）)）])\s*(.+)$", seg, re.DOTALL)
        if not m:
            body = seg.rstrip("；;")
            if body:
                blocks.append((None, "", body))
            continue
        num, body = m.group(1), m.group(2).strip().rstrip("；;")
        subtitle = ""
        for sep in ("：", ":"):
            if sep in body[:48]:
                head, _, tail = body.partition(sep)
                if 0 < len(head) <= 28:
                    subtitle = head.strip()
                    body = tail.strip().rstrip("；;")
                break
        blocks.append((num, subtitle, body))

    if len(blocks) == 1 and blocks[0][0] is None:
        intro = blocks[0][2] or ""
        clauses = [c.strip().rstrip("；;") for c in re.split(r"[；;]\s*", intro) if c.strip()]
        if len(clauses) >= 3 and all(len(c) > 12 for c in clauses):
            return [(None, "", c) for c in clauses]

    return blocks


def _render_reasoning_html(reasoning: str) -> str:
    """推理过程：编号列表 / 分条展示，避免整段混排。"""
    blocks = _parse_reasoning_blocks(reasoning)
    if not blocks:
        return ""

    numbered = [b for b in blocks if b[0] is not None]
    intros = [b for b in blocks if b[0] is None]

    inner: list[str] = []
    for _, _, body in intros:
        inner.append(
            f"<p class='text-[13px] text-gray-700 leading-relaxed'>{_esc(body)}</p>"
        )

    if numbered:
        items: list[str] = []
        for num, subtitle, body in numbered:
            title_row = ""
            if subtitle:
                title_row = (
                    f"<p class='text-[13px] font-semibold text-gray-800 mb-0.5'>"
                    f"{_esc(subtitle)}</p>"
                )
            items.append(
                f"<li class='flex gap-2.5 items-start py-2 border-b border-slate-100 "
                f"last:border-0'>"
                f"<span class='shrink-0 w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 "
                f"text-[11px] font-bold flex items-center justify-center mt-0.5'>"
                f"{_esc(num)}</span>"
                f"<div class='min-w-0 flex-1'>{title_row}"
                f"<p class='text-[13px] text-gray-600 leading-relaxed'>{_esc(body)}</p>"
                f"</div></li>"
            )
        inner.append(
            f"<ol class='list-none m-0 p-0 space-y-0'>{''.join(items)}</ol>"
        )
    elif len(intros) > 1:
        inner = [
            f"<ul class='list-disc pl-4 space-y-2 m-0'>"
            + "".join(
                f"<li class='text-[13px] text-gray-600 leading-relaxed'>{_esc(b[2])}</li>"
                for b in intros
            )
            + "</ul>"
        ]

    body_html = "".join(inner)
    return (
        f"<div class='rounded-md bg-slate-50/80 border border-slate-100 px-2.5 py-2'>"
        f"<p class='text-[11px] font-medium text-slate-500 mb-2'>推理过程</p>"
        f"<div class='space-y-2'>{body_html}</div></div>"
    )


def _render_dimension_detail_body(meta: dict, dim: dict) -> str:
    """9 维折叠区：推理过程、证据链、维度扩展字段（默认隐藏，点击标题展开）。"""
    key = meta["key"]
    parts: list[str] = []

    reasoning = (dim.get("reasoning") or "").strip()
    if reasoning:
        parts.append(_render_reasoning_html(reasoning))

    if key == "valuation":
        dd = dim.get("davis_double")
        pep = dim.get("pe_percentile")
        chips = []
        if dd and dd != "—":
            chips.append(f"戴维斯：{_esc(dd)}")
        if pep is not None:
            chips.append(f"PE 历史分位 {_esc(pep)}%")
        if chips:
            parts.append(
                "<p class='text-[12px] text-gray-600'>" + " · ".join(chips) + "</p>"
            )

    if key == "catalyst_timeline":
        items = dim.get("items") or []
        if items:
            lis = "".join(
                f"<li class='flex flex-wrap gap-x-1.5 gap-y-0.5 py-1 border-b border-gray-50 last:border-0'>"
                f"<span class='text-indigo-600 font-medium shrink-0'>{_esc(it.get('window'))}</span>"
                f"<span class='text-gray-800'>{_esc(it.get('event'))}</span>"
                f"<span class='text-gray-400 text-[11px]'>概率 {_esc(it.get('probability'))}</span></li>"
                for it in items
                if isinstance(it, dict)
            )
            parts.append(
                f"<div><p class='text-[11px] font-medium text-slate-500 mb-1'>催化时间线</p>"
                f"<ul class='text-[12px]'>{lis}</ul></div>"
            )

    evidence = dim.get("evidence") or []
    if evidence:
        ev_items = "".join(
            f"<li class='text-[12px] text-gray-600 py-0.5 pl-2 border-l-2 border-indigo-200'>"
            f"{_esc(e)}</li>"
            for e in evidence[:8]
        )
        parts.append(
            f"<div><p class='text-[11px] font-medium text-slate-500 mb-1'>事实证据</p>"
            f"<ul class='space-y-1'>{ev_items}</ul></div>"
        )

    if not parts:
        return (
            "<p class='text-[12px] text-gray-400 italic py-1'>暂无详细推理描述</p>"
        )
    return "<div class='space-y-2.5'>" + "".join(parts) + "</div>"


def _render_dimension_card(meta: dict, dim: dict) -> str:
    key = meta["key"]
    verdict = dim.get("verdict") or "—"
    if key == "market_phase" and verdict in MARKET_PHASE_LABELS:
        verdict = f"{MARKET_PHASE_LABELS[verdict]}（{verdict}）"

    missing = dim.get("status") == "missing"
    custom_tag = (
        "<span class='text-[10px] text-violet-600'>· 自定义维</span>"
        if meta.get("custom") == "true"
        else ""
    )
    note = (
        (f"<span class='text-[11px] text-amber-600'>· 模型未给出该维</span>" if missing else "")
        + custom_tag
    )
    detail_body = _render_dimension_detail_body(meta, dim)
    dim_id = _esc(key)

    return (
        f"<details class='radar-dim-details group border border-gray-100 rounded-lg bg-white "
        f"overflow-hidden min-h-[7.5rem] h-full' data-dim-key='{dim_id}'>"
        f"<summary class='cursor-pointer list-none p-3 hover:bg-gray-50/80 transition-colors "
        f"[&::-webkit-details-marker]:hidden'>"
        f"<div class='flex items-center justify-between gap-2'>"
        f"<span class='text-sm font-semibold text-gray-800 flex items-center gap-1.5 min-w-0'>"
        f"<span class='radar-dim-grip shrink-0 text-gray-300 text-xs select-none px-0.5' "
        f"aria-hidden='true' title='按住本卡任意处拖动排序'>⠿</span>"
        f"<span class='text-gray-400 text-[10px] group-open:rotate-90 transition-transform "
        f"inline-block shrink-0'>▸</span>"
        f"{meta['emoji']} {meta['label']}</span>"
        f"{_verdict_badge(verdict)}</div>"
        f"<div class='text-[11px] text-gray-400 mt-1 ml-4'>{_esc(meta['hint'])} {note}</div>"
        f"<div class='ml-4'>{_conf_bar(dim.get('confidence'))}</div>"
        f"<p class='text-[10px] text-blue-500/80 mt-1.5 ml-4 group-open:hidden'>"
        f"点击标题展开 · 推理过程与证据</p>"
        f"<p class='text-[10px] text-gray-400 mt-1.5 ml-4 hidden group-open:block'>"
        f"按住卡片拖动排序 · 点击标题收起</p>"
        f"</summary>"
        f"<div class='radar-dim-detail-body px-3 pb-3 pt-0 ml-4 mr-1 border-t border-gray-100 "
        f"bg-gray-50/40 rounded-b-md'>{detail_body}</div>"
        f"</details>"
    )


def _cost_badge(cost: dict) -> str:
    if not cost:
        return ""
    cy = cost.get("cost_yuan")
    ti = cost.get("tokens_in") or 0
    to = cost.get("tokens_out") or 0
    model = cost.get("model") or "—"
    cy_txt = f"¥{float(cy):.4f}" if cy is not None else "¥—"
    return (
        f"<span class='text-[11px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 "
        f"border border-amber-100' title='{_esc(model)}'>"
        f"💸 {cy_txt} · 入{ti}/出{to} tok</span>"
    )


def _audit_link(symbol: str, version_id: str | None = None) -> str:
    sym = _esc(symbol)
    qs = f"/audit?symbol={sym}"
    if version_id:
        qs += f"&amp;version={_esc(version_id)}"
    return (
        f"<a href='{qs}' class='text-blue-600 text-xs hover:underline no-underline'>"
        f"📋 数据审计（近 7 天 · T0/T1/T2）</a>"
    )


def _render_candidate_report(
    c: dict,
    *,
    cache_version_id: str | None = None,
    layout: dict[str, Any] | None = None,
    view_cached: bool = False,
) -> str:
    deep = c.get("deep_analysis") or {}
    overall = deep.get("overall") or {}
    dims = deep.get("dimensions") or {}
    t2_status = c.get("t2_status")
    cost = c.get("cost") or {}

    conf = overall.get("confidence", c.get("confidence"))
    conf_txt = f"{float(conf):.0%}" if conf is not None else "—"
    sym = c.get("symbol") or ""
    display = _esc(display_name_for_symbol(sym, c.get("name"), allow_network=False))
    sym_esc = _esc(sym)

    header = (
        f"<div class='flex flex-wrap items-start justify-between gap-3 mb-2'>"
        f"<div class='flex flex-wrap items-center gap-2 min-w-0'>"
        f"<span class='font-bold text-gray-900 text-base'>{display}</span>"
        f"<span class='text-gray-400 text-sm font-mono'>{sym_esc}</span>"
        + (f"<span class='text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600'>"
           f"{_esc(c.get('industry'))}</span>"
           if c.get("industry") else "")
        + f"<span class='text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700'>"
        f"总置信 {conf_txt}</span>"
        + _cost_badge(cost)
        + f"</div></div>"
    )

    layout = layout or resolve_layout_for_request(None)
    display_metas = ordered_display_metas(layout)
    dim_count = len(display_metas)

    stale_note = ""
    if view_cached:
        stale_note = (
            "<div class='rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 mb-2 "
            "text-xs text-blue-800'>📋 历史研报缓存；"
            "点击上方「分析」将 live 重新推演。</div>"
        )
    elif c.get("t2_from_stale_cache"):
        stale_note = (
            f"<div class='rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-2 "
            f"text-xs text-amber-800'>📦 本次 live Opus 未成功，已展示历史预拉缓存"
            f"（非编造 · 可 diting-infra make radar-t0-sync 更新）</div>"
        )

    # 硬失败 / 未开启 / 用户跳过：显式说明，不伪造
    if t2_status != "ok" or not dims:
        detail = c.get("t2_detail") or "深度分析未生成"
        if t2_status == "skipped":
            banner_color = "gray"
            title = "快速扫描（仅 T0+T1）"
        elif t2_status == "disabled":
            banner_color = "amber"
            title = "Opus 深度研报未就绪"
        else:
            banner_color = "red"
            title = "Opus 深度研报失败"
        body = (
            f"{stale_note}"
            f"<div class='rounded-lg border border-{banner_color}-200 bg-{banner_color}-50 p-3 text-sm "
            f"text-{banner_color}-700'>⚠️ {title}：{_esc(detail)}"
            f"<div class='text-[11px] text-{banner_color}-600 mt-1'>"
            f"（恪守 no-mock：不以占位/编造数据冒充分析结果）</div></div>"
        )
        return (
            f"<div class='border border-gray-100 rounded-xl p-4 mb-3 bg-gray-50'>{header}{body}</div>"
        )

    conclusion_txt = _esc(overall.get("conclusion") or "—")
    advisory_txt = _esc(overall.get("action_advisory") or "—")
    summary_strip = ""
    if layout.get("show_summary", True):
        summary_strip = (
            f"<div id='radar-scan-summary-strip' "
            f"class='rounded-lg bg-indigo-50/50 border border-indigo-100 px-3 py-2 mb-2'>"
            f"<p class='text-sm text-gray-800'><span class='font-semibold'>结论摘要：</span>"
            f"{conclusion_txt}</p>"
            f"<p class='text-xs text-gray-600 mt-1'><span class='font-semibold'>advisory：</span>"
            f"{advisory_txt}"
            f"<span class='text-[11px] text-gray-400'>（人工确认 · 非交易指令）</span></p>"
            f"<p class='text-[10px] text-gray-400 mt-1'>"
            f"维度详细推理默认收起；需要时点击「打开行情推理」</p>"
            f"</div>"
        )

    cards = "".join(
        _render_dimension_card(meta, dims.get(meta["key"]) or {})
        for meta in display_metas
    )
    grid = (
        f"<div id='radar-dim-grid' class='grid grid-cols-2 gap-2 items-stretch'>{cards}</div>"
        if cards
        else "<p class='text-sm text-gray-500'>当前未启用展示模块 · 点击 ⋯ 配置维度</p>"
    )

    detail_panel = (
        f"<details id='radar-scan-detail-panel' class='radar-scan-detail-panel mb-3 group'>"
        f"<summary class='cursor-pointer list-none flex flex-wrap items-center justify-between "
        f"gap-2 py-2.5 px-3 rounded-lg bg-gray-50 border border-gray-200 "
        f"hover:bg-gray-100/80 [&::-webkit-details-marker]:hidden'>"
        f"<span class='text-sm font-semibold text-gray-800 flex items-center gap-1.5 min-w-0'>"
        f"<span class='text-gray-400 text-[10px] group-open:rotate-90 transition-transform shrink-0'>"
        f"▸</span>📊 维度详细推理"
        f"<span class='text-[11px] font-normal text-gray-400'>（{dim_count} 项 · 拖动 ⠿ 排序）</span></span>"
        f"<span class='flex items-center gap-1.5 shrink-0 z-10'>"
        f"<button type='button' id='radar-scan-toggle-btn' "
        f"class='text-xs px-2.5 py-1 rounded-lg border border-indigo-200 bg-indigo-50 "
        f"text-indigo-800 hover:bg-indigo-100' "
        f"onclick='window.radarScanToggleDetail(event)'>打开行情推理</button>"
        f"<button type='button' id='radar-dim-menu-btn' "
        f"class='text-xs w-8 h-7 rounded-lg border border-gray-200 bg-white text-gray-600 "
        f"hover:bg-gray-50 leading-none' title='维度展示设置' "
        f"onclick='window.radarDimMenuToggle(event)'>⋯</button>"
        f"</span></summary>"
        f"<div class='border border-t-0 border-gray-200 rounded-b-lg p-3 bg-white mt-0'>"
        f"{grid}</div></details>"
    )

    footer = (
        f"<div class='border-t border-gray-100 pt-3 mt-1 flex justify-end'>"
        f"<form hx-post='/api/radar/candidates/{c['id']}/promote' "
        f"hx-target='#radar-candidates-list' hx-swap='innerHTML'>"
        f"<input type='hidden' name='new_theme' value='雷达晋级 · {_esc(c.get('name') or sym)}'>"
        f"<button type='submit' class='text-sm px-3 py-1.5 rounded bg-blue-600 text-white "
        f"hover:bg-blue-700'>➕ 晋级规划</button></form>"
        f"</div>"
    )

    return (
        f"<div id='radar-scan-report' class='radar-scan-report' data-symbol='{sym_esc}'>"
        f"<div class='border border-gray-100 rounded-xl p-4 mb-3 bg-white shadow-sm'>"
        f"{header}{stale_note}{summary_strip}{detail_panel}{footer}</div></div>"
    )


def _render_radar_resolve_error_html(message: str) -> str:
    """标的解析失败（HTMX 须返回 HTML，否则仅转圈无提示）。"""
    return (
        "<div class='rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-800'>"
        "<p class='font-medium'>无法识别标的</p>"
        f"<p class='mt-1'>{_esc(message)}</p>"
        "<p class='mt-2 text-xs text-red-600'>请等待下拉建议出现并点选，或输入 6 位代码后再按回车。</p>"
        "</div>"
    )


def _render_scan_progress_panel(state: dict) -> str:
    """深度扫描进度（运行中由 HTMX 轮询 GET /api/radar/scans/{id}）。"""
    from apps.copilot.modules.radar.scan_progress import _steps_from_state

    scan_id = int(state.get("scan_id") or 0)
    status = state.get("status") or "running"
    sym = _esc(state.get("symbol") or "")
    name = _esc(state.get("name") or "")
    pct = int(state.get("pct") or 0)
    step_label = _esc(state.get("step_label") or "分析进行中…")
    detail = _esc(state.get("detail") or "")
    steps_done = set(state.get("steps_done") or [])
    combo = _esc(state.get("combo") or "")
    workflow = _esc(
        state.get("workflow_summary")
        or "流程：按所选阶段执行；完成后自动展示研报。"
    )
    title_combo = f"{combo} · " if combo else ""

    step_rows: list[str] = []
    for s in _steps_from_state(state):
        sid = str(s.get("id") or "")
        label = str(s.get("label") or sid)
        if sid == "done":
            continue
        if status == "done" or sid in steps_done:
            icon, cls = "✅", "text-emerald-700"
        elif state.get("step") == sid and status == "running":
            icon, cls = "⏳", "text-blue-700 font-medium"
        else:
            icon, cls = "○", "text-gray-400"
        step_rows.append(
            f"<li class='flex items-center gap-2 text-xs {cls}'>"
            f"<span class='w-4 text-center'>{icon}</span><span>{_esc(label)}</span></li>"
        )

    poll_attrs = ""
    if status == "running" and scan_id:
        poll_attrs = (
            f" id='radar-scan-progress' data-scan-id='{scan_id}' data-running='1'"
            f" hx-get='/api/radar/scans/{scan_id}/progress'"
            f" hx-trigger='every 3s'"
            f" hx-target='#radar-scan-result'"
            f" hx-swap='innerHTML'"
            f" hx-indicator='#radar-scan-loading'"
        )
    elif status == "error":
        poll_attrs = f" id='radar-scan-progress' data-scan-id='{scan_id}' data-error='1'"
    else:
        poll_attrs = f" id='radar-scan-progress' data-scan-id='{scan_id}' data-done='1'"

    bar_color = "bg-blue-500"
    if status == "done":
        bar_color = "bg-emerald-500"
    elif status == "error":
        bar_color = "bg-red-400"

    detail_html = f' <span class="text-gray-400">— {detail}</span>' if detail else ""
    footer = ""
    if status == "error":
        err = _esc(state.get("error") or "未知错误")
        footer = (
            f"<div class='rounded-lg border border-red-200 bg-red-50 px-3 py-2 mt-2'>"
            f"<p class='text-sm font-semibold text-red-900'>扫描未完成</p>"
            f"<p class='text-sm text-red-800 mt-1'>{err}</p></div>"
        )

    return (
        f"<div class='rounded-xl border border-blue-100 bg-blue-50/40 p-4'{poll_attrs}>"
        f"<div class='flex flex-wrap items-center justify-between gap-2 mb-2'>"
        f"<span class='text-sm font-semibold text-gray-800'>"
        f"🔭 {title_combo}{name} <span class='font-mono text-gray-500'>{sym}</span></span>"
        f"<span class='inline-flex items-center gap-2 text-xs text-blue-700'>"
        f"<svg class='animate-spin h-4 w-4' fill='none' viewBox='0 0 24 24'>"
        f"<circle class='opacity-25' cx='12' cy='12' r='10' stroke='currentColor' stroke-width='4'></circle>"
        f"<path class='opacity-75' fill='currentColor' d='M4 12a8 8 0 018-8v8H4z'></path></svg>"
        f"{pct}%</span></div>"
        f"<div class='h-2 rounded-full bg-gray-100 overflow-hidden mb-2'>"
        f"<div class='h-full {bar_color} transition-all duration-500' style='width:{pct}%'></div></div>"
        f"<p class='text-sm text-gray-700 mb-2'>{step_label}{detail_html}</p>"
        f"<p class='text-[11px] text-gray-500 mb-2'>{workflow}</p>"
        f"<ul class='space-y-1 border-t border-gray-100 pt-2'>{''.join(step_rows)}</ul>"
        f"{footer}</div>"
    )


def _render_scan_html(
    scan: dict,
    *,
    layout: dict[str, Any] | None = None,
    redis_client: Any = None,
    view_cached: bool = False,
) -> HTMLResponse:
    """雷达扫描结果 HTMX 片段：人类可读 9 维深度研报卡 + 成本 + 溯源。"""
    status = scan.get("status")
    scan_id = scan.get("id")
    if status == "running":
        state = load_scan_progress(redis_client, int(scan_id)) if redis_client and scan_id else None
        if not state:
            state = {
                "scan_id": scan_id,
                "status": "running",
                "symbol": scan.get("query_text") or "",
                "name": "",
                "pct": 5,
                "step_label": "任务排队中…",
            }
        return HTMLResponse(_render_scan_progress_panel(state))
    if status == "error":
        summary = scan.get("summary_json") or {}
        err = _esc(summary.get("error") or "分析失败")
        hint = ""
        if summary.get("error_code"):
            hint = (
                f"<p class='text-[10px] text-red-500/80 mt-1'>"
                f"技术标识：{_esc(summary.get('error_code'))}</p>"
            )
        return HTMLResponse(
            f"<div class='rounded-lg border border-red-200 bg-red-50 px-4 py-3 mb-2'>"
            f"<p class='text-sm font-semibold text-red-900 mb-1'>扫描未完成</p>"
            f"<p class='text-sm text-red-800'>{err}</p>{hint}</div>"
        )
    if status != "done":
        return HTMLResponse(_render_scan_progress_panel({
            "scan_id": scan_id,
            "status": "running",
            "step_label": "扫描进行中…",
            "pct": 10,
            "symbol": scan.get("query_text") or "",
        }))
    summary = scan.get("summary_json") or {}
    vid = summary.get("cache_version_id")
    blocks = [
        _render_candidate_report(
            c, cache_version_id=vid, layout=layout, view_cached=view_cached
        )
        for c in (scan.get("candidates") or [])
    ]
    if not blocks:
        return HTMLResponse("<p class='text-sm text-gray-500'>无候选结果</p>")
    return HTMLResponse("".join(blocks))


@router.post("/api/campaigns", status_code=201)
async def api_create_campaign(
    payload: CampaignCreate,
    session: AsyncSession = Depends(get_db),
):
    c = await create_campaign(session, payload)
    await session.commit()
    return c


@router.post("/api/campaigns/import-portfolio")
async def api_import_portfolio(session: AsyncSession = Depends(get_db)):
    result = await import_portfolio_to_campaign(session, redis_client=_sync_redis())
    return result


@router.get("/api/campaigns/{campaign_id}")
async def api_get_campaign(campaign_id: int, session: AsyncSession = Depends(get_db)):
    c = await get_campaign(session, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Campaign 不存在")
    return c


@router.get("/api/campaigns/{campaign_id}/symbols/{symbol}")
async def api_symbol_dossier(
    campaign_id: int,
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    redis_client = _sync_redis()
    dossier = await build_symbol_dossier(
        session, campaign_id, symbol, redis_client=redis_client
    )
    await session.commit()
    return dossier


@router.get("/api/campaigns/{campaign_id}/monitors")
async def api_campaign_monitors(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
):
    redis_client = _sync_redis()
    await refresh_verdicts(session, campaign_id, redis_client)
    await session.commit()
    return await list_monitors(session, campaign_id)


@router.get("/api/campaigns/{campaign_id}/timeline")
async def api_campaign_timeline(
    campaign_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    items = await list_campaign_timeline(session, campaign_id)
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return _render_roadmap_timeline_html(items, campaign_id)
    return items


@router.post("/api/campaigns/{campaign_id}/timeline", status_code=201)
async def api_add_campaign_timeline(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    candidate_id: int | None = Form(None),
    symbol: str | None = Form(None),
    anchor_date: str | None = Form(None),
    title: str | None = Form(None),
    sequence_no: int | None = Form(None),
    target_weight_pct: float = Form(50.0),
):
    from datetime import date as date_cls

    try:
        if candidate_id is not None:
            result = await add_timeline_from_candidate(
                session,
                campaign_id,
                candidate_id,
                sequence_no=sequence_no,
                target_weight_pct=target_weight_pct,
            )
        elif symbol and anchor_date and title:
            result = await add_timeline_entry(
                session,
                campaign_id,
                symbol=symbol,
                anchor_date=date_cls.fromisoformat(anchor_date[:10]),
                title=title,
                sequence_no=sequence_no,
                target_weight_pct=target_weight_pct,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="需提供 candidate_id 或 symbol+anchor_date+title",
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return result


@router.get("/api/campaigns/{campaign_id}/regime")
async def api_campaign_regime(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
):
    rows = await session.scalars(
        select(RegimeAssessment).where(RegimeAssessment.campaign_id == campaign_id)
    )
    return [regime_to_dict(r) for r in rows]


@router.post("/api/campaigns/{campaign_id}/regime/assess")
async def api_assess_campaign_regime(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
):
    redis_client = _sync_redis()
    result = await assess_campaign_regime(
        session, campaign_id, redis_client=redis_client
    )
    await session.commit()
    return result


@router.post("/api/campaigns/{campaign_id}/archive")
async def api_archive_campaign(
    request: Request,
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    symbol: str | None = Form(None),
):
    try:
        result = await archive_campaign_rolling(session, campaign_id, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    if request.headers.get("hx-request"):
        arch = ", ".join(result.get("archived_symbols") or []) or "—"
        rolled = ", ".join(result.get("rolled_back_symbols") or []) or "—"
        return HTMLResponse(
            f"<div class='p-3 rounded-lg bg-gray-50 text-gray-700 text-sm'>"
            f"✓ 已归档：{arch}；长周期回流路线图：{rolled}。切到 🗓️ 路线图查看下一波。</div>"
        )
    return result


@router.get("/api/roadmap/next-waves")
async def api_next_waves(session: AsyncSession = Depends(get_db)):
    return await list_pending_next_waves(session)


@router.get("/api/campaigns/{campaign_id}/nodes")
async def api_campaign_nodes(campaign_id: int, session: AsyncSession = Depends(get_db)):
    return await list_nodes(session, campaign_id)


# ─── M11 执行区仓位指导 ────────────────────────────────────────────────────────

_ADVICE_CHIP = {
    "维持持仓": ("持有", "bg-gray-100 text-gray-700"),
    "建议分批建仓": ("建仓", "bg-blue-50 text-blue-700"),
    "可考虑加仓": ("加仓", "bg-green-50 text-green-700"),
    "建议浮盈分批减仓": ("减仓", "bg-yellow-50 text-yellow-800"),
    "逻辑被证伪/破坏，建议评估止损": ("⚠️止损", "bg-orange-50 text-orange-800"),
    "重大风险，建议评估清仓": ("🚨清仓提示", "bg-red-50 text-red-700"),
    "风险未排除，暂缓加仓（advisory）": ("暂缓加仓", "bg-amber-50 text-amber-800"),
}


def _render_execution_html(items: list, campaign_id: int) -> HTMLResponse:
    if not items:
        return HTMLResponse(
            "<p class='text-sm text-gray-500 py-4 text-center'>"
            "暂无执行建议 · POST /api/campaigns/{id}/execution/advise</p>"
        )
    cards: list[str] = []
    for a in items:
        act = a.get("advice_action", "持有")
        chip_label, chip_cls = next(
            ((lbl, cls) for k, (lbl, cls) in _ADVICE_CHIP.items() if k in act),
            (act[:6], "bg-gray-100 text-gray-600"),
        )
        sym = a.get("symbol", "")
        price = a.get("current_price")
        cost = a.get("cost_price")
        pnl = a.get("unrealized_pnl_pct")
        stale = a.get("price_stale", False)
        safety = a.get("safety_status", "pending")
        safety_icon = "🔴" if safety == "fraud" else ("🟡" if safety == "pending" else "🟢")
        price_str = f"¥{price:.2f}{'⚠️stale' if stale else ''}" if price else "—"
        cost_str = f"¥{cost:.2f}" if cost else "—"
        pnl_str = f"{pnl:+.1f}%" if pnl is not None else "—"
        pnl_cls = "text-green-600" if (pnl or 0) > 0 else ("text-red-600" if (pnl or 0) < 0 else "text-gray-500")
        cards.append(
            f"<div class='border border-gray-100 rounded-lg p-4 mb-3'>"
            f"<div class='flex flex-wrap items-center gap-2 mb-2'>"
            f"<span class='font-semibold text-gray-900'>{a.get('name', sym)}</span>"
            f"<span class='text-gray-400 text-sm'>{sym}</span>"
            f"<span class='text-xs px-2 py-0.5 rounded-full {chip_cls}'>{chip_label}</span>"
            f"<span class='text-xs text-gray-400 ml-auto'>{safety_icon} 安全扫描 {safety}</span>"
            f"</div>"
            f"<div class='grid grid-cols-3 gap-2 text-sm mb-2'>"
            f"<div><span class='text-gray-400 text-xs'>实时价</span><p class='font-mono'>{price_str}</p></div>"
            f"<div><span class='text-gray-400 text-xs'>成本价</span><p class='font-mono'>{cost_str}</p></div>"
            f"<div><span class='text-gray-400 text-xs'>浮盈亏</span><p class='font-mono {pnl_cls}'>{pnl_str}</p></div>"
            f"</div>"
            f"<p class='text-sm text-gray-700 mb-1'>{a.get('rationale', '')[:120]}</p>"
            f"<p class='text-xs text-gray-400'>更新 {a.get('as_of', '')[:16]}</p>"
            f"</div>"
        )
    # 归档按钮（无下单语义）
    archive_btn = (
        f"<form hx-post='/api/campaigns/{campaign_id}/archive' hx-swap='none' class='mt-3'>"
        f"<button type='submit' "
        f"class='px-4 py-2 rounded-lg bg-gray-200 text-gray-800 text-sm hover:bg-gray-300'>"
        f"标记本波完成 · 归档（advisory）</button>"
        f"<span class='text-xs text-gray-400 ml-2'>仅归档记录，不含任何交易操作</span>"
        f"</form>"
    )
    return HTMLResponse("".join(cards) + archive_btn)


@router.get("/api/campaigns/{campaign_id}/execution")
async def api_execution_list(
    campaign_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    symbol: str | None = None,
):
    items = await list_execution_advices(session, campaign_id, symbol)
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return _render_execution_html(items, campaign_id)
    return items


@router.post("/api/campaigns/{campaign_id}/execution/advise")
async def api_execution_advise(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    symbol: str = Form(...),
):
    redis_client = _sync_redis()
    result = await generate_execution_advice(session, campaign_id, symbol, redis_client=redis_client)
    await session.commit()
    return result


_VERDICT_CHIP = {
    "ok": ("成立", "bg-green-50 text-green-700"),
    "warn": ("预警", "bg-yellow-50 text-yellow-800"),
    "alert": ("被证伪", "bg-red-50 text-red-700"),
    "pending": ("待数据", "bg-gray-100 text-gray-600"),
}

_FALSIFY_LABEL = {
    "moat": "🧱 物理壁垒",
    "niche": "🕸️ 生态位",
    "catalyst": "📈 利好追踪",
    "risk": "⚠️ 关键风险",
}


def _render_falsify_html(
    campaign_id: int,
    tasks: list,
    readiness: dict,
    snapshot: dict,
    symbol: str,
) -> HTMLResponse:
    snap_status = snapshot.get("status", "empty")
    if snap_status == "ok":
        assess = (snapshot.get("analysis_snapshot") or {}).get("assessment") or snapshot.get(
            "analysis_snapshot"
        )
        snap_html = (
            f"<pre class='text-xs bg-gray-50 p-3 rounded overflow-x-auto max-h-48'>"
            f"{assess}</pre>"
        )
        refs = snapshot.get("artifact_refs") or []
        if refs:
            ref_links = " · ".join(
                f"<a class='text-blue-500 text-xs' href='/api/radar/candidates/"
                f"{snapshot.get('promoted_from_candidate_id')}/artifacts'>"
                f"artifact #{r['id']} {r['stage']}</a>"
                for r in refs[:3]
            )
            snap_html += f"<p class='text-xs text-gray-500 mt-1'>溯源：{ref_links}</p>"
    else:
        snap_html = (
            f"<p class='text-sm text-amber-700'>{snapshot.get('message', '无认知快照')}</p>"
        )

    cards: list[str] = []
    for t in tasks:
        v = t.get("verdict", "pending")
        label, cls = _VERDICT_CHIP.get(v, ("?", "bg-gray-100"))
        ft = t.get("falsify_type", "")
        ft_label = _FALSIFY_LABEL.get(ft, ft)
        cards.append(
            f"<div class='border border-gray-100 rounded-lg p-3 mb-2'>"
            f"<div class='flex flex-wrap items-center gap-2 mb-1'>"
            f"<span class='font-medium text-gray-900'>{ft_label}</span>"
            f"<span class='text-xs px-2 py-0.5 rounded-full {cls}'>{label}</span>"
            f"<span class='text-xs text-gray-400'>{t.get('symbol')}</span>"
            f"</div>"
            f"<p class='text-sm text-gray-600 mb-1'>{t.get('hypothesis') or '—'}</p>"
            f"<p class='text-xs text-gray-400'>"
            f"源 {t.get('source', '—')[:40]} · "
            f"最近 {t.get('last_checked_at') or '未判定'}"
            f"</p></div>"
        )
    if not cards:
        cards.append("<p class='text-sm text-gray-500'>暂无证伪任务 · POST /falsify 或雷达晋级</p>")

    ready_cls = (
        "text-green-700 bg-green-50"
        if readiness.get("ready_for_executing")
        else "text-amber-800 bg-amber-50"
    )
    promote_btn = ""
    if snapshot.get("status") != "missing":
        promote_btn = (
            f"<div class='mt-3'>"
            f"{_render_promote_executing_form(campaign_id, symbol, compact=False)}"
            f"</div>"
        )

    body = (
        f"<div class='space-y-4' data-falsify-panel-content='1'>"
        f"<div class='flex justify-end'>"
        f"<button type='button' class='text-xs text-gray-500 hover:text-gray-800 "
        f"falsify-panel-collapse' data-symbol='{symbol}'>收起面板 ▴</button></div>"
        f"<div><h3 class='text-sm font-semibold text-gray-800 mb-2'>"
        f"认知快照 · {symbol}</h3>{snap_html}</div>"
        f"<div class='px-3 py-2 rounded-lg text-sm {ready_cls}'>"
        f"就绪度 {readiness.get('ok_rate', 0):.0%} · "
        f"被证伪 {readiness.get('falsified', 0)} · pending {readiness.get('pending', 0)} · "
        f"{readiness.get('advice', '')}</div>"
        f"<div><h3 class='text-sm font-semibold text-gray-800 mb-2'>4 类证伪任务</h3>"
        f"{''.join(cards)}</div>"
        f"<form hx-post='/api/campaigns/{campaign_id}/falsify' hx-swap='none' "
        f"class='flex flex-wrap gap-2 items-end border-t pt-3'>"
        f"<input type='hidden' name='symbol' value='{symbol}'>"
        f"<div><label class='text-xs text-gray-500'>类型</label>"
        f"<select name='falsify_type' class='border rounded px-2 py-1 text-sm block'>"
        f"<option value='moat'>moat</option><option value='niche'>niche</option>"
        f"<option value='catalyst'>catalyst</option><option value='risk'>risk</option>"
        f"</select></div>"
        f"<div class='flex-1 min-w-[200px]'><label class='text-xs text-gray-500'>论点</label>"
        f"<input name='hypothesis' class='border rounded px-2 py-1 text-sm w-full' "
        f"placeholder='待证伪论点'></div>"
        f"<button type='submit' class='px-3 py-1.5 bg-gray-800 text-white text-sm rounded'>"
        f"设监控</button></form>"
        f"{promote_btn}"
        f"</div>"
    )
    return HTMLResponse(body)


@router.get("/api/campaigns/{campaign_id}/cognitive/{symbol}")
async def api_cognitive_snapshot(
    campaign_id: int,
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    return await get_cognitive_snapshot(session, campaign_id, symbol)


@router.get("/api/campaigns/{campaign_id}/falsify")
async def api_list_falsify(
    campaign_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    symbol: str | None = None,
):
    redis_client = _sync_redis()
    await refresh_falsify_verdicts(session, campaign_id, redis_client)
    await session.commit()
    tasks = await list_falsify_tasks(session, campaign_id, symbol)
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        readiness = compute_readiness(tasks)
        sym = symbol or (tasks[0]["symbol"] if tasks else "601138")
        snapshot = await get_cognitive_snapshot(session, campaign_id, sym)
        return _render_falsify_html(campaign_id, tasks, readiness, snapshot, sym)
    return tasks


@router.post("/api/campaigns/{campaign_id}/falsify", status_code=201)
async def api_create_falsify(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    symbol: str = Form(...),
    falsify_type: str = Form(...),
    hypothesis: str | None = Form(None),
    frequency: str | None = Form(None),
):
    try:
        sub = await create_falsify_task(
            session,
            campaign_id,
            symbol,
            falsify_type,
            hypothesis=hypothesis,
            frequency=frequency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": sub.id,
        "falsify_type": sub.falsify_type,
        "symbol": sub.symbol,
        "verdict": sub.verdict,
    }


@router.post("/api/campaigns/{campaign_id}/falsify/ensure-default")
async def api_ensure_default_falsify(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    symbol: str = Form(...),
):
    subs = await ensure_default_falsify_tasks(session, campaign_id, symbol)
    await session.commit()
    return {"created": len(subs), "symbol": symbol.zfill(6)[-6:]}


@router.get("/api/campaigns/{campaign_id}/readiness")
async def api_campaign_readiness(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    symbol: str | None = None,
):
    redis_client = _sync_redis()
    await refresh_falsify_verdicts(session, campaign_id, redis_client)
    await session.commit()
    tasks = await list_falsify_tasks(session, campaign_id, symbol)
    return compute_readiness(tasks)


@router.post("/api/campaigns/{campaign_id}/promote-executing")
async def api_promote_executing(
    request: Request,
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    human_confirmed: str | None = Form(None),
    symbol: str | None = Form(None),
    lifecycle_mode: str | None = Form(None),
    opened_at: str | None = Form(None),
    cost_price: float | None = Form(None),
    quantity: float | None = Form(None),
    position_pct: float | None = Form(None),
    board_id: int | None = Form(None),
    phase_id: int | None = Form(None),
    role_tag: str | None = Form(None),
    add_to_watchlist: str | None = Form(None),
):
    from apps.copilot.modules.executing.position_lifecycle import (
        LIFECYCLE_HOLDING,
        normalize_lifecycle_mode,
    )
    from apps.copilot.modules.strategic.service import upsert_primary_strategic_tag

    confirmed = str(human_confirmed or "").lower() in ("1", "true", "yes", "on")
    redis_client = _sync_redis()
    try:
        result = await promote_campaign_to_executing(
            session,
            campaign_id,
            symbol=symbol,
            human_confirmed=confirmed,
            redis_client=redis_client,
            lifecycle_mode=lifecycle_mode,
            opened_at=opened_at or None,
            cost_price=cost_price,
            quantity=quantity,
            position_pct=position_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if board_id and phase_id and symbol:
        await upsert_primary_strategic_tag(
            session,
            symbol,
            board_id=int(board_id),
            phase_id=int(phase_id),
            role_tag=(role_tag or "").strip() or None,
            tagged_from="planning",
            add_to_watchlist=str(add_to_watchlist or "").lower() in ("1", "true", "on", "yes"),
        )
    await session.commit()
    if request.headers.get("hx-request"):
        syms = ", ".join(result.get("promoted_symbols") or []) or "—"
        mode = normalize_lifecycle_mode(result.get("lifecycle_mode"))
        mode_label = "已建仓" if mode == LIFECYCLE_HOLDING else "待建仓"
        return HTMLResponse(
            f"<div class='p-3 rounded-lg bg-green-50 text-green-700 text-sm'>"
            f"✓ 已人工确认晋级执行：{syms}（{mode_label}）。"
            f"切到 🚀 {get_workspace('executing').tab_label} Tab 查看仓位指导。</div>"
        )
    return result


@router.get("/api/campaigns/{campaign_id}/planning-panel")
async def api_planning_panel(
    campaign_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    symbol: str | None = None,
):
    camp = await get_campaign(session, campaign_id)
    if camp is None:
        raise HTTPException(status_code=404, detail="Campaign 不存在")
    sym = symbol
    if not sym and camp.get("symbols"):
        sym = camp["symbols"][0]["symbol"]
    sym = (sym or "601138").zfill(6)[-6:]
    redis_client = _sync_redis()
    await refresh_falsify_verdicts(session, campaign_id, redis_client)
    tasks = await list_falsify_tasks(session, campaign_id, sym)
    readiness = compute_readiness(tasks)
    snapshot = await get_cognitive_snapshot(session, campaign_id, sym)
    await session.commit()
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return _render_falsify_html(campaign_id, tasks, readiness, snapshot, sym)
    return {"snapshot": snapshot, "falsify_tasks": tasks, "readiness": readiness}


@router.get("/api/planning/sandbox/{symbol}")
async def api_planning_sandbox(
    symbol: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    sb = (await get_asset_sandbox(session, symbol)).model_dump(mode="json")
    await session.commit()
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return HTMLResponse(_render_sandbox_panel(sb))
    return sb


@router.post("/api/planning/sandbox/{symbol}/plan")
async def api_planning_sandbox_plan(
    symbol: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    await one_shot_plan_probes(session, symbol)
    sb = (await get_asset_sandbox(session, symbol)).model_dump(mode="json")
    await session.commit()
    if request.headers.get("hx-request"):
        return HTMLResponse(_render_sandbox_panel(sb))
    return sb


@router.post("/api/planning/sandbox/probes/{probe_task_id}/result")
async def api_planning_sandbox_probe_result(
    probe_task_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    mock_result: str = Form(""),
):
    payload: dict[str, Any]
    try:
        payload = json.loads(mock_result) if mock_result.strip() else {"note": "manual_ready"}
    except Exception:  # noqa: BLE001
        payload = {"note": mock_result.strip()[:240] or "manual_ready"}
    task = await update_probe_result(session, probe_task_id, payload)
    asset = await session.scalar(select(AssetState).where(AssetState.id == task.asset_id))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset_state not found")
    sb = (await get_asset_sandbox(session, asset.symbol_code)).model_dump(mode="json")
    await session.commit()
    if request.headers.get("hx-request"):
        return HTMLResponse(_render_sandbox_panel(sb))
    return sb


@router.post("/api/planning/sandbox/{symbol}/deduce")
async def api_planning_sandbox_deduce(
    symbol: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    try:
        await one_shot_global_deduction(session, symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sb = (await get_asset_sandbox(session, symbol)).model_dump(mode="json")
    await session.commit()
    if request.headers.get("hx-request"):
        return HTMLResponse(_render_sandbox_panel(sb))
    return sb
