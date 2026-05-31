"""行情解析与规划工作台路由。

[Ref: 03_/00_维度零/.../step_12_行情解析与规划工作台.md]
"""
from __future__ import annotations

import html as _html

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
from apps.copilot.modules.planning.funnel import get_or_create_container
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
from apps.copilot.modules.radar.service import (
    create_symbol_scan,
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


def _sync_redis():
    """阻塞等待 Redis PONG（不降级跳过）。"""
    return wait_for_sync_redis()


@router.get("/planning", response_class=HTMLResponse)
async def planning_page(request: Request):
    view = request.query_params.get("view", "radar")
    if view not in ("radar", "planning", "executing", "roadmap"):
        view = "radar"
    return _tpl(request).TemplateResponse(
        request, "planning/workbench.html", {"view": view}
    )


@router.get("/portfolio-guard", response_class=HTMLResponse)
async def guard_page(request: Request):
    return _tpl(request).TemplateResponse(request, "guard/workbench.html", {})


@router.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    center = request.query_params.get("center", "").strip()
    if center:
        center = center.zfill(6)[-6:]
    return _tpl(request).TemplateResponse(
        request, "graph/placeholder.html", {"center": center or None}
    )


@router.get("/system", response_class=HTMLResponse)
async def system_page(request: Request):
    return _tpl(request).TemplateResponse(request, "system/index.html", {})


@router.get("/api/campaigns")
async def api_list_campaigns(
    request: Request,
    session: AsyncSession = Depends(get_db),
    view: str | None = None,
):
    accept = request.headers.get("accept", "")
    want_html = "text/html" in accept or request.headers.get("hx-request")
    # 标的级漏斗：planning/executing 视图按 funnel_stage 渲染标的卡（四区联动）
    if view in ("planning", "executing"):
        symbols = await list_workspace_symbols(session, view=view)
        container = await get_or_create_container(session)
        await session.commit()
        if want_html:
            return _render_workspace_symbols_html(symbols, view=view, container_id=container.id)
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


@router.get("/api/radar/symbols")
async def api_radar_symbols(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """雷达区 = 扫描工作台：最近扫描候选（待晋级），不再混入持仓列表。"""
    items = await list_recent_candidates(session)
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return _render_radar_candidates_html(items)
    return items


@router.post("/api/radar/scans", status_code=201)
async def api_create_radar_scan(
    request: Request,
    session: AsyncSession = Depends(get_db),
    query_text: str = Form(...),
    input_type: str = Form("symbol"),
):
    if input_type != "symbol":
        raise HTTPException(
            status_code=501,
            detail="启动期仅支持模式 C（symbol）；A/B 见 step_14 扩展项",
        )
    t2_vals = (await request.form()).getlist("enable_t2")
    t2_on = any(v.lower() in ("1", "true", "yes", "on") for v in t2_vals) if t2_vals else True
    await ensure_model_profiles(session)
    redis_client = _sync_redis()
    result = await create_symbol_scan(
        session,
        query_text=query_text,
        redis_client=redis_client,
        enable_t2=t2_on,
    )
    await session.commit()
    if request.headers.get("hx-request"):
        return _render_scan_html(result)
    return result


@router.get("/api/radar/scans/{scan_id}")
async def api_get_radar_scan(
    scan_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    try:
        result = await get_scan(session, scan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return _render_scan_html(result)
    return result


@router.get("/api/radar/candidates/{candidate_id}/artifacts")
async def api_candidate_artifacts(
    candidate_id: int,
    session: AsyncSession = Depends(get_db),
):
    return await list_candidate_artifacts(session, candidate_id)


@router.post("/api/radar/candidates/{candidate_id}/promote")
async def api_promote_candidate(
    request: Request,
    candidate_id: int,
    session: AsyncSession = Depends(get_db),
    new_theme: str | None = Form(None),
    campaign_id: int | None = Form(None),
):
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
    await session.commit()
    if request.headers.get("hx-request"):
        return HTMLResponse(
            f"<div class='p-3 rounded-lg bg-green-50 text-green-700 text-sm'>"
            f"✓ 标的 {result['symbol']} 已晋级到「规划中」区（funnel_stage="
            f"{result.get('funnel_stage', 'planning')}）。切到 📝 规划中 Tab 继续证伪监控。</div>"
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
    if not phase:
        return "<span class='text-xs px-2 py-0.5 rounded bg-gray-50 text-gray-400'>阶段 pending</span>"
    label, cls = _PHASE_LABEL.get(phase, (phase, "bg-gray-100 text-gray-600"))
    return f"<span class='text-xs px-2 py-0.5 rounded {cls}'>{label}</span>"


def _render_radar_candidates_html(items: list) -> HTMLResponse:
    """雷达扫描候选卡（待晋级 → planning）。"""
    if not items:
        return HTMLResponse(
            "<p class='text-sm text-gray-500 py-4 text-center'>"
            "暂无扫描候选 · 上方输入标的代码启动扫描</p>"
        )
    cards: list[str] = []
    for c in items:
        sym = c.get("symbol", "")
        promoted = c.get("already_promoted")
        conf = c.get("confidence")
        conf_txt = f"{conf:.0%}" if conf is not None else "—"
        action = (
            "<span class='text-xs px-3 py-1 rounded bg-green-50 text-green-700'>✓ 已在规划区</span>"
            if promoted
            else (
                f"<form hx-post='/api/radar/candidates/{c['id']}/promote' "
                f"hx-target='#radar-scan-result' hx-swap='innerHTML' class='inline'>"
                f"<button type='submit' "
                f"class='text-sm px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700'>"
                f"➕ 晋级到规划区</button></form>"
            )
        )
        cards.append(
            f"<div class='flex items-center justify-between p-3 mb-2 rounded-lg"
            f" bg-gray-50 border border-gray-100'>"
            f"<div class='flex items-center gap-2 flex-wrap'>"
            f"<span class='font-semibold text-gray-900'>{c.get('name', sym)}</span>"
            f"<span class='text-gray-400 text-sm'>{sym}</span>"
            f"{_phase_chip(c.get('market_phase'))}"
            f"<span class='text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700'>置信 {conf_txt}</span>"
            f"</div>"
            f"<div class='shrink-0 ml-4'>{action}</div>"
            f"</div>"
        )
    return HTMLResponse("".join(cards))


def _render_workspace_symbols_html(
    items: list, *, view: str, container_id: int
) -> HTMLResponse:
    """规划/执行区标的卡（标的级漏斗联动渲染）。"""
    if not items:
        hint = {
            "planning": "规划区暂无标的 · 从行情雷达晋级，或导入持仓",
            "executing": "执行区暂无标的 · 在规划区人工确认晋级执行",
        }.get(view, "暂无标的")
        return HTMLResponse(f"<p class='text-sm text-gray-500 py-4 text-center'>{hint}</p>")

    cards: list[str] = []
    for s in items:
        sym = s.get("symbol", "")
        name = s.get("name", sym)
        phase = _phase_chip(s.get("market_phase"))
        if view == "planning":
            cards.append(
                f"<div class='border border-gray-100 rounded-lg p-4 mb-3'>"
                f"<div class='flex flex-wrap items-center gap-2 mb-2'>"
                f"<span class='font-semibold text-gray-900'>{name}</span>"
                f"<span class='text-gray-400 text-sm'>{sym}</span>"
                f"{phase}"
                f"<span class='text-xs px-2 py-0.5 rounded bg-indigo-50 text-indigo-700'>规划中</span>"
                f"</div>"
                f"<div class='flex flex-wrap gap-2 items-center'>"
                f"<button class='text-sm text-blue-600 hover:underline' "
                f"hx-get='/api/campaigns/{container_id}/planning-panel?symbol={sym}' "
                f"hx-target='#panel-{sym}' hx-swap='innerHTML' "
                f"hx-headers='{{\"Accept\":\"text/html\"}}'>展开证伪监控面板 ▾</button>"
                f"<a href='/api/campaigns/{container_id}/symbols/{sym}' "
                f"class='text-sm text-gray-500 hover:underline'>6 维档案 JSON</a>"
                f"<form hx-post='/api/campaigns/{container_id}/promote-executing' "
                f"hx-swap='none' class='inline ml-auto'>"
                f"<input type='hidden' name='symbol' value='{sym}'>"
                f"<input type='hidden' name='human_confirmed' value='true'>"
                f"<button type='submit' "
                f"class='text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700'>"
                f"人工确认 · 晋级执行</button></form>"
                f"</div>"
                f"<div id='panel-{sym}' class='mt-3'></div>"
                f"</div>"
            )
        else:  # executing
            cards.append(
                f"<div class='border border-gray-100 rounded-lg p-4 mb-3'>"
                f"<div class='flex flex-wrap items-center gap-2 mb-2'>"
                f"<span class='font-semibold text-gray-900'>{name}</span>"
                f"<span class='text-gray-400 text-sm'>{sym}</span>"
                f"{phase}"
                f"<span class='text-xs px-2 py-0.5 rounded bg-green-50 text-green-700'>执行中</span>"
                f"</div>"
                f"<div class='flex flex-wrap gap-2 items-center'>"
                f"<form hx-post='/api/campaigns/{container_id}/execution/advise' "
                f"hx-target='#exec-{sym}' hx-swap='innerHTML' class='inline'>"
                f"<input type='hidden' name='symbol' value='{sym}'>"
                f"<button type='submit' "
                f"class='text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700'>"
                f"生成仓位建议</button></form>"
                f"<form hx-post='/api/campaigns/{container_id}/archive' hx-swap='none' "
                f"class='inline ml-auto'>"
                f"<input type='hidden' name='symbol' value='{sym}'>"
                f"<button type='submit' "
                f"class='text-sm px-3 py-1.5 rounded bg-gray-200 text-gray-800 hover:bg-gray-300'>"
                f"本波完成 · 归档</button></form>"
                f"</div>"
                f"<div id='exec-{sym}' class='mt-3'></div>"
                f"</div>"
            )
    return HTMLResponse("".join(cards))


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


def _render_dimension_card(meta: dict, dim: dict) -> str:
    key = meta["key"]
    verdict = dim.get("verdict") or "—"
    if key == "market_phase" and verdict in MARKET_PHASE_LABELS:
        verdict = f"{MARKET_PHASE_LABELS[verdict]}（{verdict}）"

    extra = ""
    if key == "valuation":
        dd = dim.get("davis_double")
        pep = dim.get("pe_percentile")
        chips = []
        if dd and dd != "—":
            chips.append(f"戴维斯：{_esc(dd)}")
        if pep is not None:
            chips.append(f"PE 历史分位 {_esc(pep)}%")
        if chips:
            extra += "<div class='text-[11px] text-gray-500 mt-1'>" + " · ".join(chips) + "</div>"
    if key == "catalyst_timeline":
        items = dim.get("items") or []
        if items:
            lis = "".join(
                f"<li class='flex gap-1.5'><span class='text-gray-400'>{_esc(it.get('window'))}</span>"
                f"<span>{_esc(it.get('event'))}</span>"
                f"<span class='text-gray-400'>·{_esc(it.get('probability'))}</span></li>"
                for it in items if isinstance(it, dict)
            )
            extra += f"<ul class='text-[12px] text-gray-600 mt-1 space-y-0.5'>{lis}</ul>"

    reasoning = dim.get("reasoning") or ""
    evidence = dim.get("evidence") or []
    ev_html = ""
    if evidence:
        ev_items = "".join(
            f"<li class='text-[11px] text-gray-500 pl-2 border-l-2 border-gray-200'>{_esc(e)}</li>"
            for e in evidence[:5]
        )
        ev_html = f"<ul class='mt-1.5 space-y-1'>{ev_items}</ul>"

    missing = dim.get("status") == "missing"
    note = "<span class='text-[11px] text-amber-600'>· 模型未给出该维</span>" if missing else ""

    return (
        f"<div class='border border-gray-100 rounded-lg p-3 bg-white'>"
        f"<div class='flex items-center justify-between gap-2 mb-1'>"
        f"<span class='text-sm font-semibold text-gray-800'>{meta['emoji']} {meta['label']}</span>"
        f"{_verdict_badge(verdict)}</div>"
        f"<div class='text-[11px] text-gray-400 mb-1'>{_esc(meta['hint'])} {note}</div>"
        f"{_conf_bar(dim.get('confidence'))}"
        f"<p class='text-[13px] text-gray-700 leading-relaxed mt-2'>{_esc(reasoning)}</p>"
        f"{extra}{ev_html}</div>"
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


def _render_candidate_report(c: dict) -> str:
    deep = c.get("deep_analysis") or {}
    overall = deep.get("overall") or {}
    dims = deep.get("dimensions") or {}
    t2_status = c.get("t2_status")
    cost = c.get("cost") or {}

    conf = overall.get("confidence", c.get("confidence"))
    conf_txt = f"{float(conf):.0%}" if conf is not None else "—"

    header = (
        f"<div class='flex flex-wrap items-center gap-2 mb-2'>"
        f"<span class='font-bold text-gray-900 text-base'>{_esc(c['name'])}</span>"
        f"<span class='text-gray-400 text-sm'>{_esc(c['symbol'])}</span>"
        + (f"<span class='text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600'>{_esc(c.get('industry'))}</span>"
           if c.get("industry") else "")
        + f"<span class='text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700'>总置信 {conf_txt}</span>"
        + _cost_badge(cost)
        + "</div>"
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
            f"<div class='rounded-lg border border-{banner_color}-200 bg-{banner_color}-50 p-3 text-sm "
            f"text-{banner_color}-700'>⚠️ {title}：{_esc(detail)}"
            f"<div class='text-[11px] text-{banner_color}-600 mt-1'>"
            f"（恪守 no-mock：不以占位/编造数据冒充分析结果）</div></div>"
        )
        return (
            f"<div class='border border-gray-100 rounded-xl p-4 mb-3 bg-gray-50'>{header}{body}"
            f"<div class='mt-2'><a href='/api/radar/candidates/{c['id']}/artifacts' "
            f"class='text-blue-500 text-xs hover:underline'>查看三段 artifact 溯源</a></div></div>"
        )

    overall_block = (
        f"<div class='rounded-lg bg-indigo-50/60 border border-indigo-100 p-3 mb-3'>"
        f"<p class='text-sm text-gray-800'><span class='font-semibold'>结论：</span>"
        f"{_esc(overall.get('conclusion'))}</p>"
        f"<p class='text-[13px] text-gray-600 mt-1'><span class='font-semibold'>研究 advisory：</span>"
        f"{_esc(overall.get('action_advisory'))} "
        f"<span class='text-[11px] text-gray-400'>（全程人工确认 · 非交易指令）</span></p></div>"
    )

    cards = "".join(
        _render_dimension_card(meta, dims.get(meta["key"]) or {})
        for meta in DIMENSIONS
    )
    grid = f"<div class='grid grid-cols-1 md:grid-cols-2 gap-2 mb-3'>{cards}</div>"

    footer = (
        f"<details class='mb-2'><summary class='text-xs text-gray-500 cursor-pointer "
        f"hover:text-gray-700'>三段流水线溯源（T0 akshare → T1 矩阵 → T2 Opus）</summary>"
        f"<a href='/api/radar/candidates/{c['id']}/artifacts' "
        f"class='text-blue-500 text-xs hover:underline'>artifact JSON</a></details>"
        f"<form hx-post='/api/radar/candidates/{c['id']}/promote' hx-swap='none' class='inline'>"
        f"<input type='hidden' name='new_theme' value='雷达晋级 · {_esc(c['name'])}'>"
        f"<button type='submit' class='text-sm px-3 py-1.5 rounded bg-blue-600 text-white "
        f"hover:bg-blue-700'>➕ 晋级规划区</button></form>"
    )

    return (
        f"<div class='border border-gray-100 rounded-xl p-4 mb-3 bg-white shadow-sm'>"
        f"{header}{overall_block}{grid}{footer}</div>"
    )


def _render_scan_html(scan: dict) -> HTMLResponse:
    """雷达扫描结果 HTMX 片段：人类可读 9 维深度研报卡 + 成本 + 溯源。"""
    if scan.get("status") != "done":
        return HTMLResponse("<p class='text-sm text-gray-500 py-2'>扫描进行中…</p>")
    blocks = [_render_candidate_report(c) for c in (scan.get("candidates") or [])]
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
            f"<form hx-post='/api/campaigns/{campaign_id}/promote-executing' "
            f"hx-swap='none' class='mt-3'>"
            f"<input type='hidden' name='human_confirmed' value='true'>"
            f"<input type='hidden' name='symbol' value='{symbol}'>"
            f"<button type='submit' "
            f"class='px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold "
            f"hover:bg-blue-700'>人工确认 · 晋级执行（{symbol}）</button>"
            f"<span class='text-xs text-gray-400 ml-2'>advisory · 须人工确认</span>"
            f"</form>"
        )

    body = (
        f"<div class='space-y-4'>"
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
):
    confirmed = str(human_confirmed or "").lower() in ("1", "true", "yes", "on")
    redis_client = _sync_redis()
    try:
        result = await promote_campaign_to_executing(
            session,
            campaign_id,
            symbol=symbol,
            human_confirmed=confirmed,
            redis_client=redis_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    if request.headers.get("hx-request"):
        syms = ", ".join(result.get("promoted_symbols") or []) or "—"
        return HTMLResponse(
            f"<div class='p-3 rounded-lg bg-green-50 text-green-700 text-sm'>"
            f"✓ 已人工确认晋级执行：{syms}。切到 🚀 执行中 Tab 查看仓位指导。</div>"
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
