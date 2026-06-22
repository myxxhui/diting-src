"""Z0 指标先行 API 路由扩展。

[Ref: 33_ §10.1]
"""
from __future__ import annotations

from typing import Any, Optional

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
    render_sector_detail_body,
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
    candidates = (wind.get("candidates") or []) if wind else []
    boards = await list_boards_summary(session)
    preview = None
    if step > 1:
        preview = await genesis_preview(session, {"board_title": "新战略板块"})
    return HTMLResponse(render_genesis_wizard(
        step=step, wind_scan=wind, preview=preview,
        candidates=candidates, boards=boards,
    ))


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


@router.get("/api/strategic/z0/sector-detail", response_class=HTMLResponse)
async def api_sector_detail(sector: str = Query(...)):
    """赛道详情：T2 结论 + 原文证据 + 政策风向标（v5.0 Pure Policy HTMX partial）。"""
    from apps.copilot.services.deepsea.policy_reader import read_sector_detail

    detail = read_sector_detail(sector)

    # 附上 wind_scan 政策风向标（从 PG wind_scans 最新快照读取）
    d1_info: dict[str, Any] = {"d1_score": None, "d1_tier": None, "needs_review": False, "review_status": None, "high_value_flag": False}
    try:
        from apps.copilot.db.database import AsyncSessionLocal
        from apps.copilot.db.models import WindScan
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(WindScan).order_by(WindScan.created_at.desc()).limit(1)
            )
            ws = result.scalar_one_or_none()
            if ws and ws.candidates_json:
                for c in ws.candidates_json:
                    if str(c.get("sector", "")).strip() == sector:
                        d1_info = {
                            "d1_score": c.get("d1_score"),
                            "d1_tier": c.get("d1_tier"),
                            "z0_plus_score": c.get("z0_plus_score"),  # v3.0
                            "z0_plus_breakdown": c.get("z0_plus_breakdown"),  # v3.0
                            "needs_review": bool(c.get("needs_review")),
                            "review_status": c.get("review_status"),
                            "high_value_flag": bool(c.get("high_value_flag")),
                            "d1_detail": c.get("d1_detail"),
                            "sub_concepts": c.get("sub_concepts") or [],  # v2.0
                        }
                        if d1_info["high_value_flag"]:
                            detail["high_value_flag"] = True
                        break
    except Exception:
        pass

    detail["wind_info"] = d1_info
    # 附丰富标签解释（供前端面板渲染）
    from apps.copilot.metrics.synthesizer.wind_scan import get_tier_specs
    specs = get_tier_specs()
    detail["rich_tier_explanations"] = specs.get("rich_tier_explanations", {})
    detail["review_threshold"] = specs.get("review_threshold", 0.60)
    return HTMLResponse(render_sector_detail_body(detail))


@router.get("/api/z0/policy/admin/concepts", response_class=HTMLResponse)
async def api_concept_options(sector: str = Query("")):
    """根据赛道动态返回 AI概念下拉选项（Partial HTML <select>）。"""
    from apps.copilot.services.deepsea.policy_reader import load_policy_keywords
    kws = load_policy_keywords()
    concept_options: list[str] = []
    if sector:
        cs = (kws.get("canonical_sectors") or {}).get(sector) or {}
        for cc in cs.get("child_concepts") or []:
            concept_options.append(str(cc["name"]))
    # 返回 <select> 标签（替换原有的概念下拉）
    opts_html = '<select name="concept" class="text-xs border border-gray-200 rounded px-2 py-1">'
    opts_html += '<option value="">全部</option>'
    for cc in concept_options:
        opts_html += f'<option value="{cc}">{cc}</option>'
    opts_html += '</select>'
    return HTMLResponse(opts_html)


@router.post("/api/strategic/z0/concept-analysis", response_class=HTMLResponse)
async def api_concept_analysis(
    concept: str = Query(...),
    parent: str = Query(""),
):
    """T2 深度分析：对单个A股概念板，基于其政第原文引用进行LLM深度解读。"""
    from apps.copilot.services.deepsea.policy_reader import read_sector_detail
    from apps.copilot.services.deepsea.policy_t1_llm_scorer import _call_llm

    detail = read_sector_detail(parent)
    # 收集该概念下所有证据引用
    sub_concepts = []
    try:
        from apps.copilot.db.database import AsyncSessionLocal
        from apps.copilot.db.models import WindScan
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(WindScan).order_by(WindScan.created_at.desc()).limit(1)
            )
            ws = result.scalar_one_or_none()
            if ws and ws.candidates_json:
                for c in ws.candidates_json:
                    if str(c.get("sector", "")).strip() == parent:
                        sub_concepts = c.get("sub_concepts") or []
                        break
    except Exception:
        pass

    target = None
    for sc in sub_concepts:
        if sc.get("sub_name", "") == concept:
            target = sc
            break
    if not target:
        return HTMLResponse(f'<div class="mt-2 p-2 text-[10px] text-red-500">未找到概念 "{concept}" 的证据数据</div>')

    quotes = target.get("evidence_quotes") or []
    doc_count = target.get("doc_count", 0)
    avg_score = target.get("avg_composite", 0)

    if not quotes:
        return HTMLResponse(f'<div class="mt-2 p-2 text-[10px] text-gray-500">该概念暂无原文引用数据（doc_count={doc_count}）</div>')

    # 拼接引用给LLM做深度分析（兼容字符串和字典两种格式）
    def _fmt_quote(q) -> str:
        if isinstance(q, dict):
            return f"[{q.get('direction','')}·score={q.get('impact_score','')}] {q.get('quote','')[:500]}"
        else:
            return f"[quote] {str(q)[:500]}"
    quote_text = "\n".join(
        f"[{i+1}] {_fmt_quote(q)}"
        for i, q in enumerate(quotes[:10])
    )

    prompt = f"""你是政策分析专家。以下是与「{concept}」概念相关的 {doc_count} 篇政策文档中的关键原文引用（共 {len(quotes)} 条）：

{quote_text}

请从以下维度进行深度解读（200-300字，bullet points）：
1. **国家战略意图**：这些政策表达背后，国家对该行业的真实意图是什么？是核心战略还是配套措施？
2. **政策分量评估**：从措施强度（拨款/立法/标准/鼓励）、发文主体级别、时效性综合判断，该概念的实际政策分量有多大？
3. **落地方向**：利好集中在哪些具体子领域？是否有明确的量化目标或时间节点？
4. **风险与不足**：是否存在负面表述、监管重、或政策扶持停留在纸面的风险？
5. **对「{parent}」赛道的贡献度**：该概念在上级赛道中的权重和支撑作用如何？

用中文回答，每点1-2句话，不要过度展开。"""

    try:
        llm_resp = _call_llm(prompt, model="deepseek-chat", max_tokens=600)
        analysis = llm_resp.strip() if llm_resp else "T2分析暂不可用（LLM未返回）"
    except Exception as e:
        analysis = f"T2分析失败：{str(e)[:100]}"

    return HTMLResponse(f"""
<div class="mt-2 p-3 rounded border border-amber-200 bg-amber-50/80">
  <div class="flex items-center gap-2 mb-2">
    <span class="text-xs font-medium text-amber-800">T2 深度分析 · {concept}</span>
    <span class="text-[9px] text-amber-600">基于 {doc_count} 篇文档 · {len(quotes)} 条引用</span>
  </div>
  <div class="text-[11px] text-gray-700 leading-relaxed whitespace-pre-line space-y-1">
{analysis}
  </div>
</div>
""")
