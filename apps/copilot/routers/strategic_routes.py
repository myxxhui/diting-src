"""战略板块 API 路由。

[Ref: 30_ §10]
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.modules.planning.funnel import get_or_create_container
from apps.copilot.modules.roadmap.service import list_campaign_timeline
from apps.copilot.modules.strategic.render import (
    render_board_list,
    render_command_center_main,
    render_phase_panel,
    render_promote_modal_radar,
    render_strategic_overview_drawer,
    render_tag_edit_modal,
)
from apps.copilot.modules.strategic.service import (
    add_phase_review,
    clear_primary_strategic_tag,
    create_board,
    get_board_detail,
    get_phase_detail,
    list_board_phase_options,
    list_boards_summary,
    seed_ai_ecosystem_board,
    suggest_tag_for_symbol,
    upsert_primary_strategic_tag,
)
from apps.copilot.routers.planning_routes import _render_roadmap_timeline_html

router = APIRouter(tags=["strategic"])


def _esc(v) -> str:
    import html

    return html.escape(str(v if v is not None else ""))


@router.get("/api/strategic/boards", response_class=HTMLResponse)
async def api_strategic_boards_list(
    request: Request,
    board_id: Optional[int] = None,
    session: AsyncSession = Depends(get_db),
):
    boards = await list_boards_summary(session)
    sel = board_id
    if sel is None and boards:
        sel = boards[0]["id"]
    return HTMLResponse(render_board_list(boards, selected_id=sel))


@router.post("/api/strategic/boards/seed-ai", response_class=HTMLResponse)
async def api_seed_ai_board(session: AsyncSession = Depends(get_db)):
    from apps.copilot.modules.strategic.z0_render import render_left_sidebar_z0
    from apps.copilot.routers.strategic_z0_routes import _command_main_bundle, _phase_panel_bundle

    board = await seed_ai_ecosystem_board(session)
    await session.commit()
    boards = await list_boards_summary(session)
    detail = await get_board_detail(session, board.id)
    active_pid = detail.get("active_phase_id") if detail else None
    main, cvm_html = await _command_main_bundle(session, board.id, active_pid)
    panel = await _phase_panel_bundle(session, active_pid) if active_pid else ""
    left = render_left_sidebar_z0(mode="board", boards=boards, selected_board_id=board.id)
    return HTMLResponse(
        f"<div id='strategic-left-sidebar' hx-swap-oob='innerHTML'>{left}</div>"
        f"<div id='strategic-command-main' hx-swap-oob='innerHTML'>{main}{cvm_html}</div>"
        f"<div id='strategic-phase-panel' hx-swap-oob='innerHTML'>{panel}</div>"
        f"<div class='p-2 text-xs text-emerald-700'>✓ 已加载 AI 产业生态样板</div>"
    )


@router.post("/api/strategic/boards", response_class=HTMLResponse)
async def api_create_board(
    session: AsyncSession = Depends(get_db),
    name: str = Form(...),
    horizon_start: int = Form(...),
    horizon_end: int = Form(...),
    qualitative_md: str = Form(""),
    load_template: str = Form(""),
):
    if load_template in ("1", "true", "on", "yes"):
        board = await seed_ai_ecosystem_board(session)
    else:
        if not name.strip():
            raise HTTPException(status_code=400, detail="板块名称不能为空")
        board = await create_board(
            session,
            name=name.strip(),
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            qualitative_md=qualitative_md.strip(),
        )
    await session.commit()
    boards = await list_boards_summary(session)
    detail = await get_board_detail(session, board.id)
    active_pid = detail.get("active_phase_id") if detail else None
    from apps.copilot.modules.strategic.z0_render import render_left_sidebar_z0
    from apps.copilot.routers.strategic_z0_routes import _command_main_bundle, _phase_panel_bundle

    main, cvm_html = await _command_main_bundle(session, board.id, active_pid)
    panel = await _phase_panel_bundle(session, active_pid) if active_pid else ""
    left = render_left_sidebar_z0(mode="board", boards=boards, selected_board_id=board.id)
    return HTMLResponse(
        f"<div id='strategic-left-sidebar' hx-swap-oob='innerHTML'>{left}</div>"
        f"<div id='strategic-command-main' hx-swap-oob='innerHTML'>{main}{cvm_html}</div>"
        f"<div id='strategic-phase-panel' hx-swap-oob='innerHTML'>{panel}</div>"
        f"<div class='p-2 text-xs text-emerald-700'>✓ 已创建「{_esc(board.name)}」</div>"
    )


@router.get("/api/strategic/command-center", response_class=HTMLResponse)
async def api_command_center(
    board_id: int,
    phase_id: Optional[int] = None,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.routers.strategic_z0_routes import _command_main_bundle, _phase_panel_bundle

    detail = await get_board_detail(session, board_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="板块不存在")
    sel = phase_id or detail.get("active_phase_id")
    main, cvm_html = await _command_main_bundle(session, board_id, sel)
    oob_panel = ""
    if sel:
        oob_panel = (
            f"<div id='strategic-phase-panel' hx-swap-oob='innerHTML'>"
            f"{await _phase_panel_bundle(session, sel)}</div>"
        )
    return HTMLResponse(oob_panel + main + cvm_html)


@router.get("/api/strategic/phases/{phase_id}/panel", response_class=HTMLResponse)
async def api_phase_panel(phase_id: int, session: AsyncSession = Depends(get_db)):
    from apps.copilot.routers.strategic_z0_routes import _phase_panel_bundle

    phase = await get_phase_detail(session, phase_id)
    if phase is None:
        raise HTTPException(status_code=404, detail="阶段不存在")
    return HTMLResponse(await _phase_panel_bundle(session, phase_id))


@router.get("/api/strategic/phases/{phase_id}/expand", response_class=HTMLResponse)
async def api_phase_expand_tactical(phase_id: int, session: AsyncSession = Depends(get_db)):
    """嵌入战术甘特（step_15 · 虚线战术层）。"""
    phase = await get_phase_detail(session, phase_id)
    if phase is None:
        raise HTTPException(status_code=404, detail="阶段不存在")
    container = await get_or_create_container(session)
    items = await list_campaign_timeline(session, container.id)
    phase_syms = {s["symbol"] for s in phase.get("symbols") or []}
    filtered = [e for e in items if (e.get("symbol") or "") in phase_syms]
    timeline_resp = _render_roadmap_timeline_html(filtered, container.id)
    timeline_html = timeline_resp.body.decode("utf-8")
    return HTMLResponse(
        f"<div class='border border-dashed border-gray-200 rounded-lg p-3 bg-gray-50/50'>"
        f"<p class='text-xs font-medium text-gray-600 mb-2'>⚙️ 战术甘特（Campaign 时间线 · 本阶段猎物）</p>"
        f"{timeline_html}"
        f"</div>"
    )


@router.post("/api/strategic/phases/{phase_id}/reviews", response_class=HTMLResponse)
async def api_phase_review(
    phase_id: int,
    review_md: str = Form(...),
    session: AsyncSession = Depends(get_db),
):
    if not review_md.strip():
        return HTMLResponse("<p class='text-xs text-red-600'>复盘内容不能为空</p>")
    await add_phase_review(session, phase_id, review_md.strip())
    await session.commit()
    return HTMLResponse("<p class='text-xs text-emerald-700'>✓ 复盘已保存</p>")


@router.get("/api/strategic/promote-modal/radar/{candidate_id}", response_class=HTMLResponse)
async def api_promote_modal_radar(
    candidate_id: int,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.db.models import RadarCandidate

    cand = await session.get(RadarCandidate, candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="候选不存在")
    options = await list_board_phase_options(session)
    suggested = await suggest_tag_for_symbol(session, cand.symbol or "")
    return HTMLResponse(
        render_promote_modal_radar(
            candidate_id=candidate_id,
            symbol=cand.symbol or "",
            name=cand.name or cand.symbol or "",
            options=options,
            suggested=suggested,
        )
    )


@router.get("/api/strategic/tags/edit", response_class=HTMLResponse)
async def api_tag_edit_modal(
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    from apps.copilot.modules.planning.funnel import normalize_symbol
    from apps.copilot.modules.strategic.service import get_primary_tags_map

    sym = normalize_symbol(symbol)
    options = await list_board_phase_options(session)
    tags = await get_primary_tags_map(session, [sym])
    current = tags.get(sym)
    name = sym
    from apps.copilot.modules.planning.funnel import get_funnel_symbol

    row = await get_funnel_symbol(session, sym)
    if row and row.name:
        name = row.name
    return HTMLResponse(
        render_tag_edit_modal(
            symbol=sym,
            name=name,
            options=options,
            current=current,
        )
    )


@router.post("/api/strategic/tags", response_class=HTMLResponse)
async def api_upsert_tag(
    session: AsyncSession = Depends(get_db),
    symbol: str = Form(...),
    board_id: int | None = Form(None),
    phase_id: int | None = Form(None),
    role_tag: str | None = Form(None),
    add_to_watchlist: str | None = Form(None),
    clear: str | None = Form(None),
):
    from apps.copilot.modules.planning.funnel import normalize_symbol
    from apps.copilot.modules.strategic.service import get_primary_tags_map

    sym = normalize_symbol(symbol)
    if clear in ("1", "true", "on", "yes"):
        await clear_primary_strategic_tag(session, sym)
        await session.commit()
        from apps.copilot.modules.planning.workspace_render import render_workspace_tag_oob

        return HTMLResponse(
            render_workspace_tag_oob(sym, None)
            + (
                f"<div id='strategic-tag-toast' hx-swap-oob='true' "
                f"class='fixed bottom-4 right-4 bg-gray-800 text-white text-xs px-3 py-2 rounded-lg'>"
                f"✓ 已清除 {sym} 战略标签</div>"
            )
        )
    if not board_id or not phase_id:
        return HTMLResponse(
            "<p class='text-xs text-red-600'>请选择板块与阶段</p>", status_code=400
        )
    await upsert_primary_strategic_tag(
        session,
        sym,
        board_id=int(board_id),
        phase_id=int(phase_id),
        role_tag=(role_tag or "").strip() or None,
        tagged_from="manual",
        add_to_watchlist=str(add_to_watchlist or "").lower() in ("1", "true", "on", "yes"),
    )
    await session.commit()
    tags = await get_primary_tags_map(session, [sym])
    from apps.copilot.modules.planning.workspace_render import render_workspace_tag_oob

    return HTMLResponse(
        render_workspace_tag_oob(sym, tags.get(sym))
        + (
            f"<div id='strategic-tag-toast' hx-swap-oob='true' "
            f"class='fixed bottom-4 right-4 bg-emerald-700 text-white text-xs px-3 py-2 rounded-lg'>"
            f"✓ 已更新 {sym} 战略标签</div>"
        )
    )


@router.get("/api/strategic/overview", response_class=HTMLResponse)
async def api_strategic_overview(session: AsyncSession = Depends(get_db)):
    boards = await list_boards_summary(session)
    return HTMLResponse(render_strategic_overview_drawer(boards))
