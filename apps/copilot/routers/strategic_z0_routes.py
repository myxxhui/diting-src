"""Z0 指标先行 API 路由扩展。

[Ref: 33_ §10.1]
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.modules.strategic.render import (
    render_board_list,
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
    render_genesis_wizard,
    render_p0_regime_banner,
    render_wind_scan_panel,
)
from apps.copilot.modules.strategic.z0_workflow import (
    confirm_cvm_pool,
    create_scan_dispatch,
    genesis_apply,
    genesis_preview,
    get_active_dispatch_for_phase,
    get_confirmed_core_pool,
    get_latest_wind_scan,
    list_cvm_scorecards,
    revoke_dispatch,
    run_cvm_for_phase,
    run_wind_scan,
)

router = APIRouter(tags=["strategic-z0"])


def _esc(v) -> str:
    import html

    return html.escape(str(v if v is not None else ""))


async def _phase_panel_bundle(session: AsyncSession, phase_id: int) -> str:
    phase = await get_phase_detail(session, phase_id)
    if not phase:
        return "<p class='text-xs text-red-600'>阶段不存在</p>"
    pool = await get_confirmed_core_pool(session, phase_id)
    dispatch = await get_active_dispatch_for_phase(session, phase_id)
    return (
        render_phase_panel(phase)
        + render_core_pool_panel(phase_id, pool, dispatch=dispatch)
    )


async def _command_main_bundle(
    session: AsyncSession,
    board_id: int,
    phase_id: Optional[int],
) -> tuple[str, str]:
    detail = await get_board_detail(session, board_id)
    if not detail:
        return ("<p class='text-sm text-gray-500'>板块不存在</p>", "")
    sel = phase_id or detail.get("active_phase_id")
    main = render_command_center_main(detail, selected_phase_id=sel)
    cvm_html = ""
    if sel:
        rows = await list_cvm_scorecards(session, sel)
        dispatch = await get_active_dispatch_for_phase(session, sel)
        cvm_html = render_cvm_matrix_table(sel, rows, dispatch=dispatch)
    return main, cvm_html


@router.post("/api/strategic/z0/collect/run", response_class=HTMLResponse)
async def api_z0_collect_run(
    job_id: str = Query("z0-bootstrap-all"),
    session: AsyncSession = Depends(get_db),
):
    """段 A 采集：有 ARQ 则入队；否则同进程直跑（本地/测试）。"""
    from apps.copilot.metrics.z0_runner import run_z0_job
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    redis = wait_for_sync_redis()
    if redis is not None:
        try:
            from apps.copilot.services.queue.enqueue import close_arq_pool, enqueue_z0_job

            arq_id = await enqueue_z0_job(job_id, source="ui")
            await close_arq_pool()
            scan = await get_latest_wind_scan(session)
            msg = f"已入队 {job_id} · arq={arq_id[:12] if arq_id else '—'}"
            return HTMLResponse(
                render_wind_scan_panel(scan)
                + f"<div class='text-xs text-sky-700 mt-2'>{_esc(msg)} · Worker 完成后点「刷新风向标」</div>"
            )
        except Exception:
            pass

    await run_z0_job(session, job_id, redis)
    scan = await run_wind_scan(session, redis_client=redis)
    await session.commit()
    return HTMLResponse(render_wind_scan_panel(scan))


@router.get("/api/strategic/z0/status")
async def api_z0_status_json(session: AsyncSession = Depends(get_db)):
    from apps.copilot.metrics.z0_status import build_z0_pipeline_status
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    redis = wait_for_sync_redis()
    return await build_z0_pipeline_status(session, redis)


@router.post("/api/strategic/wind-scan/run", response_class=HTMLResponse)
async def api_wind_scan_run(session: AsyncSession = Depends(get_db)):
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    scan = await run_wind_scan(session, redis_client=wait_for_sync_redis())
    await session.commit()
    return HTMLResponse(render_wind_scan_panel(scan))


@router.get("/api/strategic/wind-scan/latest", response_class=HTMLResponse)
async def api_wind_scan_latest(session: AsyncSession = Depends(get_db)):
    scan = await get_latest_wind_scan(session)
    return HTMLResponse(render_wind_scan_panel(scan))


@router.get("/api/strategic/genesis/wizard", response_class=HTMLResponse)
async def api_genesis_wizard(
    step: int = Query(1, ge=1, le=4),
    session: AsyncSession = Depends(get_db),
):
    wind = await get_latest_wind_scan(session)
    preview = None
    if step > 1:
        preview = await genesis_preview(session, {"board_title": "新战略板块"})
    return HTMLResponse(render_genesis_wizard(step=step, wind_scan=wind, preview=preview))


@router.post("/api/strategic/genesis/wizard", response_class=HTMLResponse)
async def api_genesis_wizard_step(
    request: Request,
    step: int = Query(2, ge=2, le=4),
    session: AsyncSession = Depends(get_db),
):
    form = await request.form()
    payload = {k: form.get(k) for k in form.keys()}
    if step == 2:
        preview = await genesis_preview(
            session,
            {
                "board_title": payload.get("board_title"),
                "wind_scan_id": payload.get("wind_scan_id") or None,
                "horizon_years": payload.get("horizon_years") or 10,
                "start_year": payload.get("start_year") or 2026,
            },
        )
        return HTMLResponse(render_genesis_wizard(step=2, preview=preview))
    if step == 3:
        preview = await genesis_preview(
            session,
            {
                "board_title": payload.get("board_title"),
                "wind_scan_id": payload.get("wind_scan_id") or None,
                "horizon_years": payload.get("horizon_years") or 10,
                "start_year": payload.get("start_year") or 2026,
            },
        )
        return HTMLResponse(render_genesis_wizard(step=3, preview=preview))
    preview = await genesis_preview(
        session,
        {
            "board_title": payload.get("board_title"),
            "wind_scan_id": payload.get("wind_scan_id") or None,
            "horizon_years": payload.get("horizon_years") or 10,
            "start_year": payload.get("start_year") or 2026,
        },
    )
    return HTMLResponse(render_genesis_wizard(step=4, preview=preview))


@router.post("/api/strategic/genesis/apply", response_class=HTMLResponse)
async def api_genesis_apply(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    form = await request.form()
    payload = {k: form.get(k) for k in form.keys()}
    if form.get("advisory_ack") not in ("1", "on", "true"):
        return HTMLResponse(
            render_genesis_wizard(step=4, error="须勾选 advisory 确认", preview=None),
            status_code=400,
        )
    board = await genesis_apply(
        session,
        {
            "board_title": payload.get("board_title"),
            "wind_scan_id": payload.get("wind_scan_id") or None,
            "horizon_years": payload.get("horizon_years") or 10,
            "start_year": payload.get("start_year") or 2026,
            "niche_default": payload.get("niche_default"),
        },
    )
    await session.commit()
    boards = await list_boards_summary(session)
    detail = await get_board_detail(session, board.id)
    active_pid = detail.get("active_phase_id") if detail else None
    main, cvm_html = await _command_main_bundle(session, board.id, active_pid)
    panel = ""
    if active_pid:
        panel = await _phase_panel_bundle(session, active_pid)
    from apps.copilot.modules.strategic.z0_render import render_left_sidebar_z0

    left = render_left_sidebar_z0(
        mode="board", boards=boards, selected_board_id=board.id
    )
    return HTMLResponse(
        f"<div id='genesis-wizard-root' hx-swap-oob='innerHTML'></div>"
        f"<div id='strategic-left-sidebar' hx-swap-oob='innerHTML'>{left}</div>"
        f"<div id='strategic-command-main' hx-swap-oob='innerHTML'>{main}{cvm_html}</div>"
        f"<div id='strategic-phase-panel' hx-swap-oob='innerHTML'>{panel}</div>"
        f"<div class='fixed bottom-4 right-4 bg-emerald-700 text-white text-xs px-3 py-2 rounded-lg z-50'>"
        f"✓ Genesis 已建板「{_esc(board.name)}」</div>"
    )


@router.post("/api/strategic/phases/{phase_id}/cvm/run", response_class=HTMLResponse)
async def api_cvm_run(phase_id: int, session: AsyncSession = Depends(get_db)):
    try:
        rows = await run_cvm_for_phase(session, phase_id)
        await session.commit()
    except ValueError as e:
        rows = await list_cvm_scorecards(session, phase_id)
        dispatch = await get_active_dispatch_for_phase(session, phase_id)
        return HTMLResponse(render_cvm_matrix_table(phase_id, rows, dispatch=dispatch, error=str(e)))
    dispatch = await get_active_dispatch_for_phase(session, phase_id)
    return HTMLResponse(render_cvm_matrix_table(phase_id, rows, dispatch=dispatch))


@router.get("/api/strategic/phases/{phase_id}/cvm/matrix", response_class=HTMLResponse)
async def api_cvm_matrix(phase_id: int, session: AsyncSession = Depends(get_db)):
    rows = await list_cvm_scorecards(session, phase_id)
    dispatch = await get_active_dispatch_for_phase(session, phase_id)
    return HTMLResponse(render_cvm_matrix_table(phase_id, rows, dispatch=dispatch))


@router.post("/api/strategic/phases/{phase_id}/cvm/confirm", response_class=HTMLResponse)
async def api_cvm_confirm(
    phase_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    form = await request.form()
    symbols = form.getlist("symbols")
    try:
        rows = await confirm_cvm_pool(session, phase_id, selected_symbols=symbols)
        await session.commit()
    except ValueError as e:
        rows = await list_cvm_scorecards(session, phase_id)
        dispatch = await get_active_dispatch_for_phase(session, phase_id)
        return HTMLResponse(render_cvm_matrix_table(phase_id, rows, dispatch=dispatch, error=str(e)))
    dispatch = await get_active_dispatch_for_phase(session, phase_id)
    panel_oob = (
        f"<div id='strategic-phase-panel' hx-swap-oob='innerHTML'>"
        f"{await _phase_panel_bundle(session, phase_id)}</div>"
    )
    return HTMLResponse(
        panel_oob + render_cvm_matrix_table(phase_id, rows, dispatch=dispatch)
    )


@router.post("/api/strategic/phases/{phase_id}/dispatch", response_class=HTMLResponse)
async def api_phase_dispatch(phase_id: int, session: AsyncSession = Depends(get_db)):
    try:
        disp = await create_scan_dispatch(session, phase_id)
        await session.commit()
    except ValueError as e:
        return HTMLResponse(f"<div class='text-xs text-red-600'>{_esc(e)}</div>", status_code=400)
    rows = await list_cvm_scorecards(session, phase_id)
    return HTMLResponse(
        f"<div id='strategic-phase-panel' hx-swap-oob='innerHTML'>"
        f"{await _phase_panel_bundle(session, phase_id)}</div>"
        f"<div id='cvm-matrix-panel' hx-swap-oob='outerHTML'>"
        f"{render_cvm_matrix_table(phase_id, rows, dispatch=disp)}</div>"
        f"<div class='text-xs text-emerald-700'>✓ 已派单 · { _esc(disp['theme']) }</div>"
    )


@router.post("/api/strategic/dispatches/{dispatch_id}/revoke", response_class=HTMLResponse)
async def api_dispatch_revoke(dispatch_id: int, session: AsyncSession = Depends(get_db)):
    disp = await revoke_dispatch(session, dispatch_id)
    await session.commit()
    panel = await _phase_panel_bundle(session, disp["phase_id"])
    rows = await list_cvm_scorecards(session, disp["phase_id"])
    return HTMLResponse(
        panel
        + f"<div id='cvm-matrix-panel' hx-swap-oob='outerHTML'>"
        f"{render_cvm_matrix_table(disp['phase_id'], rows)}</div>"
    )
