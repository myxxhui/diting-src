"""Z0 指标先行 API 路由扩展。

[Ref: 33_ §10.1]
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

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
    # v5.5: 生态位分析区域（写在 CVM 上方）
    from apps.copilot.modules.strategic.render import render_ecosystem_section
    ecosystem_html = render_ecosystem_section(detail)
    cvm_html = ""
    if sel:
        rows = await list_cvm_scorecards(session, sel)
        dispatch = await get_active_dispatch_for_phase(session, sel)
        cvm_html = render_cvm_matrix_table(sel, rows, dispatch=dispatch)
    return main + ecosystem_html, cvm_html


@router.post("/api/strategic/z0/collect/run", response_class=HTMLResponse)
async def api_z0_collect_run(
    job_id: str = Query("z0-bootstrap-all"),
    session: AsyncSession = Depends(get_db),
):
    """段 A 采集（UI 快速版）：M1 宏观 + M5 流动性 + WindScan合成。不跑LLM T1打分（由CronJob负责）。"""
    from apps.copilot.metrics.z0_runner import run_z0_m1, run_z0_m5
    from apps.copilot.modules.strategic.z0_workflow import run_wind_scan
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    redis = wait_for_sync_redis()
    if redis is None:
        scan = await run_wind_scan(session)
        await session.commit()
        return HTMLResponse(render_wind_scan_panel(scan))

    # v5.1 UI快速采集：M1+M5+WindScan，跳过 policy_ingest+T1（CronJob 负责LLM打分）
    await run_z0_m1(session, redis)
    await run_z0_m5(session, redis)
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


@router.post("/api/strategic/z0/investment-rescore", response_class=JSONResponse)
async def api_z0_investment_rescore(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """Z0+ 投资级重评分：仅重跑商业轨迹 + 资本引力 + 执行质量三个 LLM 维度。

    返回 { success, sector, z0_plus_breakdown, errors }.
    """
    from apps.copilot.db.models import WindScan
    from apps.common.ai_dispatcher import AIDispatcher
    import json as _json

    form = await request.form()
    sector = (form.get("sector") or "").strip()
    if not sector:
        return {"success": False, "error": "缺少 sector 参数"}

    # 找最近的 wind_scan 中该 sector
    ws_result = await session.execute(
        select(WindScan).order_by(WindScan.created_at.desc()).limit(1)
    )
    ws = ws_result.scalar_one_or_none()
    if not ws:
        return {"success": False, "error": "无 WindScan 记录"}

    candidates = ws.candidates_json or []
    target = None
    for c in candidates:
        if str(c.get("sector", "")).strip() == sector:
            target = c
            break
    if not target:
        return {"success": False, "error": f"未找到赛道 {sector}"}

    # 触发 LLM 重评分
    z0pb = target.get("z0_plus_breakdown") or {}
    policy_docs_text = z0pb.get("context_summary", f"对「{sector}」赛道进行投资级重评分")

    dispatcher = AIDispatcher.default()
    prompt = f"""你是资深投资分析师。为以下赛道重新评估三个投资维度：

赛道名：{sector}
背景：{policy_docs_text}

当前 z0_plus_breakdown：{_json.dumps(z0pb, ensure_ascii=False)}

输出严格 JSON（无 markdown）：
{{
    "commercial_trajectory": {{
        "score_d1_tier": "A"|"B"|"C",
        "reasoning": "40-80字中文",
        "evidence": [],
        "d1_keywords": []
    }},
    "capital_gravity": {{
        "score_d1_tier": "A"|"B"|"C",
        "reasoning": "40-80字中文",
        "evidence": [],
        "d1_keywords": []
    }},
    "implementation_quality": {{
        "score_d1_tier": "A"|"B"|"C",
        "reasoning": "40-80字中文",
        "evidence": [],
        "d1_keywords": []
    }}
}}
"""
    try:
        resp = dispatcher.call(
            scene="z0_t2_concept_analysis",
            messages=[
                {"role": "system", "content": "你是顶级投研分析师。用中文回答。只返回JSON，不含markdown。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
            model_override="claude-opus-4-6",
        )
        raw = resp.text if hasattr(resp, "text") else str(resp)
        llm_result = _parse_llm_json(raw)
    except Exception as exc:
        llm_result = {}
        logger.warning("[z0+ rescore] LLM 调用失败: %s", exc)

    # 合并回 z0_plus_breakdown
    for dim in ("commercial_trajectory", "capital_gravity", "implementation_quality"):
        if dim in llm_result:
            z0pb[dim] = llm_result[dim]

    # 更新 wind_scan
    for c in candidates:
        if str(c.get("sector", "")).strip() == sector:
            c["z0_plus_breakdown"] = z0pb
            break
    ws.candidates_json = candidates
    await session.commit()

    return {
        "success": True,
        "sector": sector,
        "z0_plus_breakdown": z0pb,
        "errors": [],
    }


@router.get("/api/strategic/genesis/sectors", response_class=HTMLResponse)
async def api_genesis_sectors(session: AsyncSession = Depends(get_db)):
    """v5.1: 返回全部候赛道列表（HTML 下拉选项片段）"""
    wind = await get_latest_wind_scan(session)
    candidates = (wind.get("candidates") or []) if wind else []
    opts = ""
    for c in candidates:
        dn = c.get("display_name", c.get("sector", "?"))
        z0 = c.get("z0_plus_score")
        d1 = c.get("d1_score")
        sc = c.get("sub_concepts") or []
        z0_str = f"Z0+={int(z0*100)}" if z0 is not None else ""
        d1_str = f"D1={int(d1*100)}" if d1 is not None else ""
        label = f"{dn} · {z0_str} · {len(sc)}概念"
        opts += f'<option value="{_esc(c.get("sector",""))}" data-display="{_esc(dn)}">{_esc(label)}</option>\n'
    return HTMLResponse(f'<option value="">-- 请选择赛道 --</option>\n{opts}')


@router.post("/api/strategic/genesis/concepts", response_class=HTMLResponse)
async def api_genesis_concepts(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """v5.1: 根据选中赛道返回概念列表（含证据摘要）"""
    form = await request.form()
    sector = (form.get("sector") or "").strip()
    if not sector:
        return HTMLResponse('<p class="text-red-500 text-xs">未选择赛道</p>')

    wind = await get_latest_wind_scan(session)
    candidates = (wind.get("candidates") or []) if wind else []
    sector_data = None
    for c in candidates:
        if c.get("sector") == sector:
            sector_data = c
            break

    if not sector_data:
        return HTMLResponse(f'<p class="text-red-500 text-xs">赛道 {_esc(sector)} 无数据</p>')

    sub_concepts = sector_data.get("sub_concepts") or []
    # 优先展示有文档命中的
    sub_concepts.sort(key=lambda x: x.get("doc_count", 0), reverse=True)

    z0p = sector_data.get("z0_plus_score")
    d1 = sector_data.get("d1_score")
    display_name = sector_data.get("display_name", sector)
    rows = ""
    for sc in sub_concepts:
        sn = sc.get("sub_name", "?")
        dc = sc.get("doc_count", 0)
        ac = sc.get("avg_composite", 0)
        evidence_html = ""
        for eq in (sc.get("evidence_quotes") or [])[:2]:
            ex = _esc((eq.get("excerpt") or "")[:100])
            evidence_html += f'<span class="text-gray-400 ml-2">「{ex}...」</span>'
        checked = "checked" if dc > 0 else ""
        dc_badge = f'{dc}篇 均分{ac:.0f}' if dc > 0 else '未命中'
        rows += f"""
        <label class="flex items-center gap-2 px-2 py-1.5 hover:bg-indigo-50 rounded cursor-pointer text-xs">
          <input type="checkbox" name="concept_{_esc(sn)}" value="{_esc(sn)}" {checked} class="rounded" />
          <span class="font-medium text-gray-800">{_esc(sn)}</span>
          <span class="text-gray-400">{dc_badge}</span>
          {evidence_html}
        </label>"""
    return HTMLResponse(f"""
    <div class="text-xs space-y-1">
      <p class="font-medium text-gray-700 mb-1">已选赛道：<span class="text-indigo-700">{_esc(display_name)}</span>
      {f'<span class="ml-2 text-emerald-600 font-bold">Z0+{int(z0p*100)}</span>' if z0p else ''}
      {f'<span class="ml-1 text-gray-400">D1={int(d1*100)}</span>' if d1 else ''}
      </p>
      <p class="text-gray-500 mb-2">勾选概念板块（已按文档命中数降序）</p>
      {rows}
    </div>
    """)


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
    """Genesis 建板分步处理（v3.0 · 四步）。"""
    form = await request.form()
    payload = {k: form.get(k) for k in form.keys()}

    selected_concepts: list[str] = []
    for k, v in payload.items():
        if k.startswith("concept_") and v:
            selected_concepts.append(v)

    if step == 2:
        # Step 1 → Step 2：显示概念选择 + 时间骨架（BOM 在 Step 3 以定制化方式展示）
        sector = (payload.get("sector") or "").strip()
        wind = await get_latest_wind_scan(session)
        candidates = (wind.get("candidates") or []) if wind else []
        sector_data = None
        for c in candidates:
            if c.get("sector") == sector:
                sector_data = c
                break
        preview = await genesis_preview(
            session,
            {
                "board_title": payload.get("board_title") or sector_data.get("display_name", sector) if sector_data else "新战略板块",
                "wind_scan_id": payload.get("wind_scan_id") or None,
                "horizon_years": payload.get("horizon_years") or 10,
                "start_year": payload.get("start_year") or 2026,
            },
        )
        return HTMLResponse(render_genesis_wizard(
            step=2, preview=preview,
            sector_data=sector_data,
            wind_scan=wind,
        ))

    if step == 3:
        # Step 2 → Step 3：加载定制化 BOM 节点（经人工筛选与深度评估），显示选择面板
        sector = (payload.get("sector") or "").strip()

        # 生成 preview（用于 Step 3 的预览信息）
        preview = await genesis_preview(
            session,
            {
                "board_title": payload.get("board_title"),
                "wind_scan_id": payload.get("wind_scan_id") or None,
                "horizon_years": payload.get("horizon_years") or 10,
                "start_year": payload.get("start_year") or 2026,
            },
        )

        # 从 YAML 加载定制化 BOM（替代原 LLM 动态生成）
        from apps.copilot.modules.strategic.render import load_curated_bom_as_proposal
        bom_result = load_curated_bom_as_proposal(sector)

        return HTMLResponse(render_genesis_wizard(
            step=3, preview=preview,
            selected_concepts=selected_concepts,
            sector=sector,
            bom_proposal=bom_result,
        ))

    # step == 4: Step 3 → Step 4：收集选中的 BOM 节点，显示确认页
    sector = (payload.get("sector") or "").strip()
    # 查找 display_name
    sector_display_name = sector
    wind = await get_latest_wind_scan(session)
    if wind:
        for c in (wind.get("candidates") or []):
            if c.get("sector") == sector:
                sector_display_name = c.get("display_name", sector)
                break

    preview = await genesis_preview(
        session,
        {
            "board_title": payload.get("board_title"),
            "wind_scan_id": payload.get("wind_scan_id") or None,
            "horizon_years": payload.get("horizon_years") or 10,
            "start_year": payload.get("start_year") or 2026,
        },
    )

    # 解析 bom_proposal_json → 获取节点完整信息
    import json
    bom_proposal = {}
    bom_proposal_raw = payload.get("bom_proposal_json")
    if bom_proposal_raw:
        try:
            bom_proposal = json.loads(bom_proposal_raw)
        except (json.JSONDecodeError, TypeError):
            bom_proposal = {}

    nodes_lookup = {n.get("node_id"): n for n in (bom_proposal.get("bom_nodes") or [])}

    # 收集选中的 BOM 节点（含 name / tier / layer）
    selected_bom_nodes: list[dict[str, str]] = []
    for k, v in payload.items():
        if k.startswith("bom_node_") and v:
            nid = v
            node_info = nodes_lookup.get(nid, {})
            selected_bom_nodes.append({
                "node_id": nid,
                "name": node_info.get("name", nid),
                "tier": node_info.get("tier", "配套"),
                "layer": node_info.get("layer", "") or "",
            })

    return HTMLResponse(render_genesis_wizard(
        step=4, preview=preview,
        selected_concepts=selected_concepts,
        sector=sector,
        sector_display_name=sector_display_name,
        selected_bom_nodes=selected_bom_nodes,
    ))


def _render_ecosystem_html(result: dict[str, Any]) -> str:
    """将生态位推断结果渲染为 HTML 片段（v2.0：BOM 节点 + 5因子 + 兼容 v1.0 concept_pools）。"""
    if result.get("status") != "ok":
        err = result.get("error", "未知错误")
        return f'<p class="text-red-500 text-xs">LLM 推断失败: {_esc(err)}</p>'

    # v2.0: bom_nodes 格式
    bom_nodes = result.get("bom_nodes") or []
    if result.get("version") == "2.0" and bom_nodes:
        return _render_ecosystem_html_v2(result, bom_nodes)

    # v1.0 fallback: concept_pools 格式
    return _render_ecosystem_html_v1(result)


def _render_ecosystem_html_v2(result: dict[str, Any], bom_nodes: list[dict]) -> str:
    """v2.0: BOM 节点分组渲染 + 5因子打分明细（可展开）。"""
    thesis = result.get("investment_thesis", "")
    disclaimer = result.get("disclaimer", "")
    excluded_stocks = result.get("excluded_stocks", [])

    node_html = ""
    total_stocks = 0
    for node in bom_nodes:
        nid = node.get("node_id", "?")
        name = node.get("name", "?")
        tier = node.get("tier", "核心")
        tier_color = "text-rose-700 bg-rose-50" if tier == "核心" else "text-amber-700 bg-amber-50" if tier == "重要" else "text-gray-600 bg-gray-50"
        rationale = node.get("rationale", "")
        stocks = node.get("stocks", [])
        total_stocks += len(stocks)
        stock_rows = ""
        for st in stocks:
            sym = st.get("symbol", "??????")
            sn = st.get("stock_name", "?")
            pos = st.get("ecosystem_position", "")
            sd = st.get("scoring_detail") or {}
            composite = sd.get("composite", 0)
            comp_color = "text-emerald-600" if composite >= 0.8 else "text-amber-600" if composite >= 0.6 else "text-rose-500"
            factor_detail = ""
            for fk, flabel in [("moat", "壁垒"), ("growth", "成长"), ("profit", "盈利"), ("localize", "国产替代"), ("policy_bond", "政策映射")]:
                fv = sd.get(fk) or {}
                fscore = fv.get("score", "—")
                fscore_txt = f"{fscore:.0%}" if isinstance(fscore, (int, float)) else str(fscore)
                fevidence = fv.get("evidence") or []
                if fk == "policy_bond":
                    matched = fv.get("matched_concepts", [])
                    note = fv.get("note", "")
                    fev_html = f"<p class='text-[10px] text-gray-600'>匹配概念：{', '.join(matched) if matched else '无'}{' · ' + _esc(note) if note else ''}</p>"
                else:
                    fev_html = "<ul class='list-disc pl-4 space-y-0.5'>" + "".join(
                        f"<li class='text-[10px] text-gray-600'>{_esc(ev)}</li>" for ev in fevidence
                    ) + "</ul>" if fevidence else "<span class='text-[10px] text-gray-400'>无证据</span>"
                factor_detail += f"<tr class='border-b border-gray-50'><td class='py-1.5 text-[11px] text-gray-700 font-medium w-20'>{flabel}</td><td class='py-1.5 text-[11px] font-mono w-14'>{fscore_txt}</td><td class='py-1.5'>{fev_html}</td></tr>"
            stock_rows += f"""<details class='border rounded-lg mb-1'>
  <summary class='flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-gray-50 text-xs'>
    <span class='font-mono font-medium'>{_esc(sym)}</span>
    <span class='font-medium'>{_esc(sn)}</span>
    <span class='text-[10px] text-gray-400 ml-1'>{_esc(pos)}</span>
    <span class='ml-auto font-bold {comp_color}'>{composite:.0%}</span>
  </summary>
  <div class='px-3 py-2 bg-gray-50/70'>
    <table class='w-full text-xs'>
      <thead><tr class='text-[10px] text-gray-400'><th class='text-left font-normal w-20'>因子</th><th class='text-left font-normal w-14'>得分</th><th class='text-left font-normal'>证据</th></tr></thead>
      <tbody>{factor_detail}</tbody>
    </table>
  </div>
</details>"""
        if not stock_rows:
            stock_rows = '<p class="text-xs text-gray-400 py-2 text-center">该节点未生成标的</p>'
        node_html += f"""<div class='mb-3 border rounded-lg p-3 bg-white'>
  <div class='flex items-center gap-2 mb-2'>
    <span class='text-xs font-semibold text-gray-800'>{_esc(name)}</span>
    <span class='text-[10px] px-1.5 py-0.5 rounded {tier_color}'>{tier}</span>
    <span class='text-[10px] text-gray-400'>(node: {_esc(nid)})</span>
  </div>
  {f'<p class="text-[10px] text-gray-500 mb-2">{_esc(rationale)}</p>' if rationale else ''}
  {stock_rows}
</div>"""

    excluded_html = ""
    if excluded_stocks:
        ex_rows = "".join(
            f"<li class='text-xs text-rose-600 flex items-center gap-2'><span class='font-mono'>{_esc(e.get('symbol', '?'))}</span><span>{_esc(e.get('stock_name', '?'))}</span><span class='text-[10px] px-1.5 py-0.5 rounded bg-rose-100'>{_esc(e.get('exclusion_rule', ''))}</span></li>"
            for e in excluded_stocks
        )
        excluded_html = f"<div class='mt-2 border border-rose-200 rounded-lg p-2 bg-rose-50/30'><p class='text-xs font-medium text-rose-800 mb-1'>🚫 排除标的（{len(excluded_stocks)} 只）</p><ul class='space-y-0.5'>{ex_rows}</ul></div>"

    return f"""<div class='space-y-3'>
  {f'<div class="bg-emerald-50 border border-emerald-100 rounded-lg p-2 text-xs text-emerald-800">💡 {_esc(thesis)}</div>' if thesis else ''}
  <p class='text-xs font-medium text-gray-700'>📊 BOM 节点标的池 ({len(bom_nodes)} 个节点 · 共 {total_stocks} 只)</p>
  {node_html}
  {excluded_html}
  {f'<p class="text-[10px] text-gray-400 italic">{_esc(disclaimer)}</p>' if disclaimer else ''}
</div>"""


def _render_ecosystem_html_v1(result: dict[str, Any]) -> str:
    """v1.0 兼容：concept_pools 格式渲染。"""
    topo = result.get("ecosystem_topology", {})
    thesis = result.get("investment_thesis", "")
    pools = result.get("concept_pools", [])
    disclaimer = result.get("disclaimer", "")

    topo_html = ""
    for layer, label in [("upstream", "🔼 上游"), ("midstream", "➡️ 中游"), ("downstream", "🔽 下游"), ("service_layer", "⚙️ 服务层")]:
        ld = topo.get(layer, {})
        role = ld.get("role", "")
        segs = ld.get("key_segments", [])
        if role or segs:
            topo_html += f"""
            <div class="flex items-start gap-2 text-xs">
              <span class="font-medium text-gray-700 w-16 shrink-0">{label}</span>
              <div>
                <span class="text-gray-600">{_esc(role)}</span>
                <div class="flex flex-wrap gap-1 mt-0.5">{''.join(f'<span class="px-1 py-0 rounded bg-indigo-50 text-indigo-700 text-[10px]">{_esc(s)}</span>' for s in segs)}</div>
              </div>
            </div>"""

    pool_html = ""
    for pool in pools:
        cn = pool.get("concept_name", "?")
        layer_label = pool.get("ecosystem_layer", "?")
        rationale = pool.get("rationale", "")
        stocks = pool.get("stocks", [])
        stock_rows = ""
        for i, st in enumerate(stocks):
            conf = st.get("confidence", 0)
            conf_color = "text-emerald-600" if conf >= 0.7 else "text-amber-500"
            stock_rows += f"""
            <div class="flex items-start gap-2 text-xs py-1 border-b border-gray-50 last:border-0">
              <span class="text-gray-400 w-5">{i+1}</span>
              <span class="font-medium text-gray-800 w-16">{_esc(st.get('symbol','?'))}</span>
              <span class="text-gray-700 w-20">{_esc(st.get('stock_name','?'))}</span>
              <span class="text-gray-400 flex-1">{_esc(st.get('ecosystem_position',''))}</span>
              <span class="{conf_color} w-8 text-right">{conf:.0%}</span>
            </div>"""
            stock_rows += f'<div class="text-[10px] text-gray-400 pl-8 pb-1">{_esc(st.get("growth_rationale",""))}</div>'

        pool_html += f"""
        <div class="border border-gray-200 rounded-lg overflow-hidden mb-2">
          <div class="bg-gray-50 px-3 py-1.5 flex items-center justify-between text-xs">
            <span class="font-semibold text-gray-800">{_esc(cn)}</span>
            <span class="text-gray-400">{_esc(layer_label)}</span>
          </div>
          <div class="text-[10px] text-gray-500 px-3 py-1 bg-white border-b border-gray-100">{_esc(rationale)}</div>
          <div class="px-1 py-0.5">
            <div class="flex items-center gap-2 text-[10px] text-gray-400 px-2 py-0.5">
              <span class="w-5">#</span><span class="w-16">代码</span><span class="w-20">名称</span><span class="flex-1">生态位定位</span><span class="w-8 text-right">置信</span>
            </div>
            {stock_rows}
          </div>
        </div>"""

    return f"""
    <div class="space-y-3">
      {f'<div class="bg-emerald-50 border border-emerald-100 rounded-lg p-2 text-xs text-emerald-800">💡 {_esc(thesis)}</div>' if thesis else ''}
      {f'<div class="border border-gray-200 rounded-lg p-2 space-y-1.5"><p class="text-xs font-medium text-gray-700 mb-1">🏗 产业生态位拓扑</p>{topo_html}</div>' if topo_html else ''}
      <p class="text-xs font-medium text-gray-700">📊 概念标的池 ({len(pools) if pools else 0} 个概念)</p>
      {pool_html or '<p class="text-xs text-gray-400">LLM 未返回概念池</p>'}
      {f'<p class="text-[10px] text-gray-400 italic">{_esc(disclaimer)}</p>' if disclaimer else ''}
    </div>
    """


@router.post("/api/strategic/genesis/infer", response_class=HTMLResponse)
async def api_genesis_infer(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """v5.2: 异步后台模式——启动 LLM 推断任务后立即返回轮询 HTML。
    LLM 调用需 30-60s，避免浏览器/代理超时导致 'TypeError: Failed to fetch'。
    """
    from apps.copilot.services.genesis.ecosystem_inferrer import start_ecosystem_inference

    form = await request.form()
    sector = (form.get("sector") or "").strip()
    selected_concept_names: list[str] = []
    for k, v in {k: form.get(k) for k in form.keys()}.items():
        if k.startswith("concept_") and v:
            selected_concept_names.append(v)

    if not sector or not selected_concept_names:
        return HTMLResponse('<p class="text-red-500 text-xs">缺少赛道或概念参数</p>')

    wind = await get_latest_wind_scan(session)
    candidates = (wind.get("candidates") or []) if wind else []
    sector_data = None
    for c in candidates:
        if c.get("sector") == sector:
            sector_data = c
            break

    if not sector_data:
        return HTMLResponse(f'<p class="text-red-500 text-xs">赛道 {_esc(sector)} 无数据</p>')

    display_name = sector_data.get("display_name", sector)
    z0_bd = sector_data.get("z0_plus_breakdown", {})
    all_sub_concepts = sector_data.get("sub_concepts") or []
    concept_map = {sc.get("sub_name", ""): sc for sc in all_sub_concepts}
    selected_data = [concept_map[n] for n in selected_concept_names if n in concept_map]

    if not selected_data:
        return HTMLResponse('<p class="text-red-500 text-xs">选定概念无数据</p>')

    task_id = await start_ecosystem_inference(
        sector=sector,
        display_name=display_name,
        z0_plus_breakdown=z0_bd,
        selected_concepts=selected_data,
    )

    return HTMLResponse(f"""
    <div id="ecosystem-infer-result" class="border border-dashed border-gray-200 rounded-lg p-4 min-h-[60px]">
      <div class="flex items-center gap-2 text-xs text-gray-400"
           hx-get="/api/strategic/genesis/infer/status/{task_id}"
           hx-trigger="every 2s"
           hx-swap="outerHTML">
        <span class="animate-spin inline-block w-4 h-4 border-2 border-gray-300 border-t-indigo-600 rounded-full"></span>
        <span>正在调用深度模型分析产业生态位...</span>
      </div>
    </div>
    """)


@router.get("/api/strategic/genesis/infer/status/{task_id}", response_class=HTMLResponse)
async def api_genesis_infer_status(
    task_id: str,
):
    """v5.2: 轮询 LLM 推断任务状态。返回处理中动画或完成后的结果 HTML。"""
    from apps.copilot.services.genesis.ecosystem_inferrer import get_inference_task

    task = await get_inference_task(task_id)

    if task is None:
        return HTMLResponse('<p class="text-red-500 text-xs">任务已过期或不存在，请重新触发分析。</p>')

    if task["status"] == "processing":
        return HTMLResponse("""
        <div class="flex items-center gap-2 text-xs text-gray-400"
             hx-get="/api/strategic/genesis/infer/status/""" + task_id + """"
             hx-trigger="every 2s"
             hx-swap="outerHTML">
          <span class="animate-spin inline-block w-4 h-4 border-2 border-gray-300 border-t-indigo-600 rounded-full"></span>
          <span>正在调用深度模型分析产业生态位...</span>
        </div>
        """)

    # 任务完成，渲染结果 HTML
    result = task.get("result", {})
    html = _render_ecosystem_html(result)
    # 结果容器外层包一个 div，保留 id 以便前端 JS 可找到
    return HTMLResponse(f'<div id="ecosystem-infer-result">{html}</div>')


# ═══════════════════════════════════════════════════
# v5.6 标的操作：加入猎物池 / 排除 / 批量晋级 / 推送 CVM
# ═══════════════════════════════════════════════════

def _calc_board_stock_pool(board: Any) -> tuple[list[dict], list[dict]]:
    """解析 board 的 stock_pool_json 中的标的列表，返回 (可操作标的, 排除标的)。"""
    spj = board.stock_pool_json or {}
    bom_nodes = spj.get("bom_nodes") or []
    stocks = [s for n in bom_nodes for s in (n.get("stocks") or [])]
    excluded = spj.get("excluded_stocks") or []
    return stocks, excluded


@router.post("/api/strategic/boards/{board_id}/stock/{symbol}/accept", response_class=HTMLResponse)
async def api_board_stock_accept(
    board_id: int,
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    """将某只标的加入板块的猎物池（hunt_pool），返回已接受标记。"""
    board = await session.get(StrategicBoard, board_id)
    if not board:
        return HTMLResponse('<span class="text-[10px] text-red-500">板块不存在</span>', status_code=404)

    bcj = board.barbell_config_json or {}
    hunt_pool: list[dict] = bcj.get("hunt_pool") or []
    # 防止重复加入
    existing = {s.get("symbol") for s in hunt_pool}
    if symbol not in existing:
        stocks, _ = _calc_board_stock_pool(board)
        for st in stocks:
            if st.get("symbol") == symbol:
                hunt_pool.append({
                    "symbol": symbol,
                    "stock_name": st.get("stock_name", ""),
                    "composite": st.get("scoring_detail", {}).get("composite", 0),
                    "stock_source": st.get("stock_source", "llm"),
                    "accepted_at": datetime.utcnow().isoformat(),
                })
                break
        bcj["hunt_pool"] = hunt_pool
        board.barbell_config_json = bcj
        await session.commit()

    return HTMLResponse(f'<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">✅ 已加入猎物池</span>')


@router.post("/api/strategic/boards/{board_id}/stock/{symbol}/reject", response_class=HTMLResponse)
async def api_board_stock_reject(
    board_id: int,
    symbol: str,
    session: AsyncSession = Depends(get_db),
):
    """排除某只标的，从视图中移除该行。"""
    board = await session.get(StrategicBoard, board_id)
    if not board:
        return HTMLResponse('', status_code=404)

    spj = board.stock_pool_json or {}
    rejected: list[dict] = spj.get("rejected_stocks") or []
    # 记录排除
    stocks, _ = _calc_board_stock_pool(board)
    for st in stocks:
        if st.get("symbol") == symbol:
            rejected.append({
                "symbol": symbol,
                "stock_name": st.get("stock_name", ""),
                "reason": "人工排除",
                "rejected_at": datetime.utcnow().isoformat(),
            })
            break
    spj["rejected_stocks"] = rejected
    board.stock_pool_json = spj
    await session.commit()

    return HTMLResponse('')  # 返回空，前端用 hx-swap="outerHTML" 移除该行


@router.post("/api/strategic/boards/{board_id}/stock/batch-accept", response_class=HTMLResponse)
async def api_board_stock_batch_accept(
    board_id: int,
    session: AsyncSession = Depends(get_db),
):
    """一键晋级：将当前所有未排除的标的批量加入猎物池。"""
    from apps.copilot.modules.strategic.render import _render_bom_stock_pool

    board = await session.get(StrategicBoard, board_id)
    if not board:
        return HTMLResponse('<div class="text-xs text-red-500">板块不存在</div>', status_code=404)

    bcj = board.barbell_config_json or {}
    spj = board.stock_pool_json or {}
    hunt_pool: list[dict] = bcj.get("hunt_pool") or []
    existing_symbols = {s.get("symbol") for s in hunt_pool}
    bom_nodes = spj.get("bom_nodes") or []
    rejected_symbols = {s.get("symbol") for s in (spj.get("rejected_stocks") or [])}

    batch_added = 0
    for node in bom_nodes:
        for st in (node.get("stocks") or []):
            sym = st.get("symbol", "")
            if sym not in existing_symbols and sym not in rejected_symbols:
                hunt_pool.append({
                    "symbol": sym,
                    "stock_name": st.get("stock_name", ""),
                    "composite": st.get("scoring_detail", {}).get("composite", 0),
                    "stock_source": st.get("stock_source", "llm"),
                    "accepted_at": datetime.utcnow().isoformat(),
                })
                batch_added += 1

    bcj["hunt_pool"] = hunt_pool
    board.barbell_config_json = bcj
    await session.commit()

    # 重新渲染生态位部分
    bom_nodes = spj.get("bom_nodes") or []
    html = _render_bom_stock_pool(board_id, spj, bom_nodes)
    return HTMLResponse(html)


@router.post("/api/strategic/boards/{board_id}/stock/preview-accepted", response_class=HTMLResponse)
async def api_board_stock_preview_accepted(
    board_id: int,
    session: AsyncSession = Depends(get_db),
):
    """预览当前已接受的标的列表。"""
    board = await session.get(StrategicBoard, board_id)
    if not board:
        return HTMLResponse('')

    bcj = board.barbell_config_json or {}
    hunt_pool: list[dict] = bcj.get("hunt_pool") or []
    if not hunt_pool:
        return HTMLResponse('<p class="text-[10px] text-gray-400">暂无已选标的</p>')

    rows = "".join(
        f'<li class="text-[10px] text-gray-700 flex items-center gap-1">'
        f'<span class="font-mono">{_esc(s.get("symbol", ""))}</span>'
        f'<span>{_esc(s.get("stock_name", ""))}</span>'
        f'<span class="text-[10px] px-1 rounded bg-gray-100">{s.get("stock_source", "llm")}</span>'
        f'<span class="ml-auto font-mono">{s.get("composite", 0):.0%}</span>'
        f'</li>'
        for s in hunt_pool
    )
    return HTMLResponse(
        f'<div class="mt-2 border border-emerald-200 rounded p-2 bg-white">'
        f'<p class="text-[10px] font-medium text-emerald-800 mb-1">已选标的 ({len(hunt_pool)} 只)</p>'
        f'<ul class="space-y-0.5 max-h-40 overflow-y-auto">{rows}</ul>'
        f'</div>'
    )


@router.post("/api/strategic/boards/{board_id}/stock/push-to-cvm", response_class=HTMLResponse)
async def api_board_stock_push_to_cvm_ready(
    board_id: int,
    session: AsyncSession = Depends(get_db),
):
    """将猎物池标的推送到 CVM 矩阵——当前为标记就绪状态，Z1 阶段实现实际落库。"""
    board = await session.get(StrategicBoard, board_id)
    if not board:
        return HTMLResponse('<div class="text-[10px] text-red-500">板块不存在</div>', status_code=404)

    bcj = board.barbell_config_json or {}
    hunt_pool: list[dict] = bcj.get("hunt_pool") or []
    if not hunt_pool:
        return HTMLResponse('<div class="text-[10px] text-amber-600">暂无已选标的，请先加入猎物池。</div>')

    # 标记 push 状态
    bcj["cvm_push_ready"] = True
    bcj["cvm_push_at"] = datetime.utcnow().isoformat()
    bcj["cvm_pool"] = hunt_pool.copy()
    board.barbell_config_json = bcj
    await session.commit()

    names = ", ".join(s.get("stock_name", "") for s in hunt_pool[:5])
    suffix = f"等 {len(hunt_pool)} 只" if len(hunt_pool) > 5 else ""
    return HTMLResponse(
        f'<div class="mt-2 text-[10px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-2">'
        f'✅ 已标记就绪：{names}{suffix}，等待 Z1 Gate-A 财务交叉验证。'
        f'</div>'
    )


# ═══════════════════════════════════════════════════
# v5.5 版块级生态位分析（从战略板块命令中心触发）
# ═══════════════════════════════════════════════════

@router.post("/api/strategic/boards/{board_id}/ecosystem/infer", response_class=HTMLResponse)
async def api_board_ecosystem_infer(
    board_id: int,
    session: AsyncSession = Depends(get_db),
):
    """从命令中心触发 LLM 生态位分析。返回 JS 轮询 HTML（含进度条+取消按钮+自动恢复）。"""
    from apps.copilot.modules.strategic.service import get_board_detail
    from apps.copilot.services.genesis.ecosystem_inferrer import start_ecosystem_inference, get_inference_task
    from apps.copilot.modules.strategic.render import _render_ecosystem_pending
    from apps.copilot.db.models import StrategicBoard

    detail = await get_board_detail(session, board_id)
    if not detail:
        return HTMLResponse('<p class="text-red-500 text-xs">板块不存在</p>')

    barbell = detail.get("barbell_config_json") or {}
    sector = barbell.get("genesis_sector") or ""
    concept_names = barbell.get("genesis_concepts") or []

    if not sector or not concept_names:
        return HTMLResponse(
            '<div id="ecosystem-section" class="mt-6 border border-dashed border-gray-200 rounded-lg p-4">'
            '<p class="text-red-500 text-xs">板块缺少赛道或概念信息，请通过智能建板流程重新创建。</p>'
            '</div>'
        )

    # ── 防重复 / 过期处理 ──
    board = await session.get(StrategicBoard, board_id)
    if board and board.stock_pool_json and board.stock_pool_json.get("status") == "pending":
        existing_task_id = board.stock_pool_json.get("task_id", "")
        task = await get_inference_task(existing_task_id) if existing_task_id else None
        if task is not None:
            # 任务仍在运行：返回进度 UI
            return HTMLResponse(_render_ecosystem_pending(board_id, existing_task_id))
        # 任务已过期：清除 DB pending 标记，继续创建新任务
        board.stock_pool_json = None
        await session.commit()

    # 从 wind scan 获取 sector 的 Z0+ 评分与概念详情
    wind = await get_latest_wind_scan(session)
    candidates = (wind.get("candidates") or []) if wind else []
    sector_data = None
    for c in candidates:
        if c.get("sector") == sector:
            sector_data = c
            break

    if not sector_data:
        return HTMLResponse(
            '<div id="ecosystem-section" class="mt-6 border border-dashed border-gray-200 rounded-lg p-4">'
            f'<p class="text-red-500 text-xs">赛道 {_esc(sector)} 在 Wind Scan 中无数据，请先运行风向标。</p>'
            '</div>'
        )

    display_name = sector_data.get("display_name", sector)
    z0_bd = sector_data.get("z0_plus_breakdown", {})
    all_sub = sector_data.get("sub_concepts") or []
    concept_map = {sc.get("sub_name", ""): sc for sc in all_sub}
    selected_data = [concept_map[n] for n in concept_names if n in concept_map]

    if not selected_data:
        return HTMLResponse(
            '<div id="ecosystem-section" class="mt-6 border border-dashed border-gray-200 rounded-lg p-4">'
            '<p class="text-red-500 text-xs">选定概念无 Wind Scan 数据</p>'
            '</div>'
        )

    # 解析用户选定的 BOM 节点（从 barbell_config_json，保留代表标的）
    bom_node_defs = barbell.get("genesis_bom_nodes") or []
    bom_nodes_for_infer: list[dict] = [
        {
            "node_id": n.get("node_id", ""),
            "name": n.get("name", ""),
            "tier": n.get("tier", "配套"),
            "representative_stocks": n.get("representative_stocks") or [],
        }
        for n in bom_node_defs
        if n.get("node_id")
    ]

    # 启动后台推断
    task_id = await start_ecosystem_inference(
        sector=sector,
        display_name=display_name,
        z0_plus_breakdown=z0_bd,
        selected_concepts=selected_data,
        bom_nodes=bom_nodes_for_infer if bom_nodes_for_infer else None,
    )

    # 写入 DB 标记 pending（刷新页面恢复用）
    if board:
        board.stock_pool_json = {"status": "pending", "task_id": task_id}
        await session.commit()

    return HTMLResponse(_render_ecosystem_pending(board_id, task_id))


@router.get("/api/strategic/boards/{board_id}/ecosystem/status/{task_id}")
async def api_board_ecosystem_status(
    board_id: int,
    task_id: str,
    session: AsyncSession = Depends(get_db),
    poll_count: int = 0,
):
    """轮询任务状态（JSON 响应 · 由前端 JS setInterval 调用）。
    返回: {status: 'processing'|'done'|'expired', ...}
    """
    from apps.copilot.services.genesis.ecosystem_inferrer import get_inference_task
    from apps.copilot.modules.strategic.render import _render_ecosystem_result
    from apps.copilot.db.models import StrategicBoard

    task = await get_inference_task(task_id)

    if task is None:
        return JSONResponse({"status": "expired"})

    if task["status"] == "processing":
        elapsed = poll_count * 2
        pct = min(elapsed * 100 // 50, 95)
        if elapsed < 10:
            hint = "正在调用大模型 · 解析产业政策信号…"
        elif elapsed < 25:
            hint = "正在推断产业生态位拓扑 · 识别上下游关键环节…"
        elif elapsed < 40:
            hint = "正在扫描每个概念的潜在标的 · 评估成长逻辑…"
        else:
            hint = "正在汇总分析结果 · 即将完成…"
        return JSONResponse({"status": "processing", "elapsed": elapsed, "pct": pct, "hint": hint})

    # 任务完成：落库 + 双闸 T2 增强 + 返回结果 HTML
    result = task.get("result", {})
    if result.get("status") == "ok":
        from apps.copilot.modules.strategic.duan_dual_gate import compute_duan_dual_gates_async

        board = await session.get(StrategicBoard, board_id)
        if board:
            barbell = (board.barbell_config_json or {}) if hasattr(board, "barbell_config_json") else {}
            sector = barbell.get("genesis_sector_display_name") or barbell.get("genesis_sector") or ""
            duan_node, stock_duan, enriched_pool = await compute_duan_dual_gates_async(
                session,
                result,
                run_node_t2=True,
                run_stock_t2=True,
                persist_to_pool=True,
                sector_context=str(sector),
            )
            board.stock_pool_json = enriched_pool
            await session.commit()
            html = _render_ecosystem_result(
                board_id, enriched_pool,
                duan_node_scores=duan_node,
                stock_duan_scores=stock_duan,
            )
        else:
            duan_node, stock_duan, enriched_pool = await compute_duan_dual_gates_async(
                session, result, run_node_t2=True, run_stock_t2=True, persist_to_pool=True,
            )
            html = _render_ecosystem_result(
                board_id, enriched_pool,
                duan_node_scores=duan_node,
                stock_duan_scores=stock_duan,
            )
        return JSONResponse({"status": "done", "html": html})
    else:
        error_msg = result.get("error", "未知错误")
        raw = result.get("raw_preview", "")
        html = (
            f'<div id="ecosystem-section" class="mt-6 border border-dashed border-red-200 rounded-lg p-4 bg-red-50/30">'
            f'<div class="flex items-center gap-2 mb-2"><span class="text-base">❌</span><span class="text-sm font-medium text-red-700">分析失败</span></div>'
            f'<p class="text-xs text-red-600 mb-1">{_esc(error_msg[:200])}</p>'
            + (f'<details class="mt-1"><summary class="text-[10px] text-gray-400 cursor-pointer">LLM 原始输出</summary><pre class="text-[10px] text-gray-500 mt-1 max-h-32 overflow-auto">{_esc(raw[:500])}</pre></details>' if raw else '')
            + f'<button class="text-xs mt-3 px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 transition" '
            f"hx-post=\"/api/strategic/boards/{board_id}/ecosystem/infer\" "
            f'hx-target="#ecosystem-section" hx-swap="outerHTML">🔄 重新分析</button>'
            f'</div>'
        )
        return JSONResponse({"status": "done", "html": html})


@router.post("/api/strategic/boards/{board_id}/ecosystem/cancel/{task_id}", response_class=HTMLResponse)
async def api_board_ecosystem_cancel(
    board_id: int,
    task_id: str,
    session: AsyncSession = Depends(get_db),
):
    """中断正在进行的生态位分析。清除 DB pending 状态，返回触发按钮。"""
    from apps.copilot.services.genesis.ecosystem_inferrer import cancel_inference_task
    from apps.copilot.modules.strategic.render import render_ecosystem_section
    from apps.copilot.modules.strategic.service import get_board_detail
    from apps.copilot.db.models import StrategicBoard

    await cancel_inference_task(task_id)

    # 清除 DB pending 标记
    board = await session.get(StrategicBoard, board_id)
    if board and board.stock_pool_json and board.stock_pool_json.get("status") == "pending":
        board.stock_pool_json = None
        await session.commit()

    detail = await get_board_detail(session, board_id)
    if detail:
        return HTMLResponse(render_ecosystem_section(detail))
    return HTMLResponse(
        '<div id="ecosystem-section" class="mt-6 border border-dashed border-gray-200 rounded-lg p-4">'
        '<p class="text-red-500 text-xs">板块不存在</p></div>'
    )


# ═══════════════════════════════════════════════════
#  生态位排序接口
# ═══════════════════════════════════════════════════

@router.get("/api/strategic/boards/{board_id}/ecosystem/sorted", response_class=HTMLResponse)
async def api_board_ecosystem_sorted(
    board_id: int,
    node_sort: str = Query("tier_core_first"),
    stock_sort: str = Query("composite_desc"),
    view_mode: str = Query("grouped"),
    session: AsyncSession = Depends(get_db),
):
    """按指定排序参数重新渲染生态位标的池，返回完整 ecosystem-section HTML。"""
    from apps.copilot.modules.strategic.render import _render_ecosystem_result, render_ecosystem_section
    from apps.copilot.modules.strategic.service import get_board_detail
    from apps.copilot.modules.strategic.duan_dual_gate import compute_duan_dual_gates_async

    detail = await get_board_detail(session, board_id)
    if not detail:
        return HTMLResponse(
            '<div id="ecosystem-section" class="mt-6 border border-dashed border-gray-200 rounded-lg p-4">'
            '<p class="text-red-500 text-xs">板块不存在</p></div>'
        )
    stock_pool = detail.get("stock_pool_json")
    if not stock_pool or stock_pool.get("status") != "ok":
        return HTMLResponse(render_ecosystem_section(detail))

    # ── Z0 段永平双闸（v4.2 完整版 · duan_dual_gate 统一入口）──
    duan_node_scores, stock_duan_scores, _ = await compute_duan_dual_gates_async(
        session,
        stock_pool,
        run_node_t2=False,
        run_stock_t2=False,
        persist_to_pool=False,
    )

    html = _render_ecosystem_result(
        board_id, stock_pool, node_sort, stock_sort, view_mode,
        duan_node_scores=duan_node_scores,
        stock_duan_scores=stock_duan_scores,
    )
    return HTMLResponse(html)


@router.post("/api/strategic/boards/{board_id}/ecosystem/duan-enrich", response_class=HTMLResponse)
async def api_board_ecosystem_duan_enrich(
    board_id: int,
    session: AsyncSession = Depends(get_db),
):
    """重新跑节点 T2 + 标的轻 T2，落库 node_duan_pack / stock_duan_anchor 并刷新 UI。"""
    from apps.copilot.db.models import StrategicBoard
    from apps.copilot.modules.strategic.duan_dual_gate import compute_duan_dual_gates_async
    from apps.copilot.modules.strategic.render import _render_ecosystem_result, render_ecosystem_section
    from apps.copilot.modules.strategic.service import get_board_detail

    detail = await get_board_detail(session, board_id)
    if not detail:
        return HTMLResponse(
            '<div id="ecosystem-section" class="mt-6 p-4"><p class="text-red-500 text-xs">板块不存在</p></div>'
        )
    stock_pool = detail.get("stock_pool_json")
    if not stock_pool or stock_pool.get("status") != "ok":
        return HTMLResponse(render_ecosystem_section(detail))

    barbell = detail.get("barbell_config_json") or {}
    sector = barbell.get("genesis_sector_display_name") or barbell.get("genesis_sector") or ""
    duan_node, stock_duan, enriched = await compute_duan_dual_gates_async(
        session,
        stock_pool,
        run_node_t2=True,
        run_stock_t2=True,
        persist_to_pool=True,
        sector_context=str(sector),
    )
    board = await session.get(StrategicBoard, board_id)
    if board:
        board.stock_pool_json = enriched
        await session.commit()

    html = _render_ecosystem_result(
        board_id, enriched,
        duan_node_scores=duan_node,
        stock_duan_scores=stock_duan,
    )
    return HTMLResponse(html)


# ═══════════════════════════════════════════════════
#  板块编辑（添加/修改赛道/概念/时间）
# ═══════════════════════════════════════════════════

@router.get("/api/strategic/boards/{board_id}/edit-modal", response_class=HTMLResponse)
async def api_board_edit_modal(
    board_id: int,
    session: AsyncSession = Depends(get_db),
):
    """返回板块编辑模态框 HTML（预填充当前配置 + board 自身 BOM 节点）。"""
    from apps.copilot.modules.strategic.render import render_board_edit_modal
    from apps.copilot.modules.strategic.service import get_board_detail
    from apps.copilot.modules.strategic.z0_workflow import get_latest_wind_scan

    detail = await get_board_detail(session, board_id)
    if not detail:
        return HTMLResponse('<p class="text-red-500 text-xs">板块不存在</p>')

    wind = await get_latest_wind_scan(session)
    candidates = (wind.get("candidates") or []) if wind else []

    # 定制化 BOM：优先使用 board 自身保存的节点，无则从 YAML 加载该赛道的定制 BOM
    from apps.copilot.modules.strategic.render import load_curated_bom
    barbell = detail.get("barbell_config_json") or {}
    board_bom = barbell.get("genesis_bom_nodes") or load_curated_bom(barbell.get("genesis_sector", ""))

    html = render_board_edit_modal(board=detail, candidates=candidates, bom_nodes=board_bom)
    return HTMLResponse(html)


@router.post("/api/strategic/genesis/concepts-json", response_class=HTMLResponse)
async def api_genesis_concepts_json(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """根据选中赛道返回概念勾选列表 HTML（用于编辑模态框）。"""
    form = await request.form()
    sector = (form.get("sector") or "").strip()
    if not sector:
        return HTMLResponse('<p class="text-xs text-gray-400 py-2 text-center">请先选择赛道</p>')

    wind = await get_latest_wind_scan(session)
    candidates = (wind.get("candidates") or []) if wind else []
    sector_data = None
    for c in candidates:
        if c.get("sector") == sector:
            sector_data = c
            break
    if not sector_data:
        return HTMLResponse(f'<p class="text-xs text-gray-400 py-2">赛道 {_esc(sector)} 无数据</p>')

    sub_concepts = sector_data.get("sub_concepts") or []
    sub_concepts.sort(key=lambda x: x.get("doc_count", 0), reverse=True)
    rows = ""
    for sc in sub_concepts:
        sn = sc.get("sub_name", "?")
        dc = sc.get("doc_count", 0)
        ac = sc.get("avg_composite", 0)
        dc_badge = f'{dc}篇 均分{ac:.0f}' if dc > 0 else '未命中'
        rows += (
            f'<label class="flex items-center gap-2 px-2 py-1.5 hover:bg-indigo-50 rounded cursor-pointer text-xs">'
            f'<input type="checkbox" name="concept_{_esc(sn)}" value="{_esc(sn)}" checked class="rounded" />'
            f'<span class="font-medium text-gray-800">{_esc(sn)}</span>'
            f'<span class="text-gray-400">{dc_badge}</span>'
            f'</label>'
        )
    return HTMLResponse(rows if rows else '<p class="text-xs text-gray-400 py-2 text-center">该赛道无概念数据</p>')


@router.post("/api/strategic/boards/{board_id}/edit", response_class=HTMLResponse)
async def api_board_edit(
    board_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """提交板块编辑：更新名称/赛道/概念/时间骨架，清除旧生态位分析结果。"""
    from apps.copilot.modules.strategic.render import render_command_center_main, render_ecosystem_section
    from apps.copilot.modules.strategic.service import get_board_detail, list_boards_summary
    from apps.copilot.db.models import StrategicBoard

    form = await request.form()
    payload = {k: form.get(k) for k in form.keys()}

    name = (payload.get("board_title") or "").strip()
    sector = (payload.get("sector") or "").strip()
    horizon_years = int(payload.get("horizon_years") or 10)
    start_year = int(payload.get("start_year") or 2026)
    end_year = start_year + horizon_years

    selected_concepts: list[str] = []
    for k, v in payload.items():
        if k.startswith("concept_") and v:
            selected_concepts.append(v)

    # 收集选中的 BOM 节点（从 edit modal 的复选框）
    selected_bom_node_ids: list[str] = []
    for k, v in payload.items():
        if k.startswith("bom_node_") and v:
            selected_bom_node_ids.append(v)

    if not name or not sector:
        return HTMLResponse(
            '<div class="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg p-2">缺少板块名称或赛道</div>',
            status_code=400,
        )

    # v4.1: 从 board 现有 barbell 读取 BOM 节点元数据（tier/layer），回退静态白名单
    from apps.copilot.modules.strategic.service import get_board_detail as _get_board_detail
    _detail = await _get_board_detail(session, board_id)
    _barbell = (_detail.get("barbell_config_json") or {}) if _detail else {}
    _existing_bom = _barbell.get("genesis_bom_nodes") or []

    # 构建动态 BOM 查找表，保留 name/tier/layer
    _bom_lookup: dict[str, dict] = {n.get("node_id", ""): n for n in _existing_bom if n.get("node_id")}

    # 直接操作 board 记录，更新全部字段 + 动态 BOM 节点
    _board = await session.get(StrategicBoard, board_id)
    if not _board:
        return HTMLResponse(
            '<div class="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg p-2">板块不存在</div>',
            status_code=404,
        )
    _board.name = name.strip()
    _board.horizon_start = start_year
    _board.horizon_end = end_year
    _bcj = dict(_board.barbell_config_json or {})
    _bcj["genesis_sector"] = sector
    # 查找官方展示名（AI算力 → 人工智能产业）
    _dname = sector
    try:
        from pathlib import Path
        import yaml as _yaml
        _p = Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
        with _p.open(encoding="utf-8") as _f:
            _cfg = _yaml.safe_load(_f) or {}
        _cs = (_cfg.get("canonical_sectors") or {}).get(sector) or {}
        _dname = str(_cs.get("display_name") or sector)
    except Exception:
        pass
    _bcj["genesis_sector_display_name"] = _dname
    _bcj["genesis_concepts"] = selected_concepts
    # 保留已选节点的元数据（动态 BOM 的 name/tier/layer/representative_stocks）
    _bcj["genesis_bom_nodes"] = [
        {
            "node_id": nid,
            "name": _bom_lookup.get(nid, {}).get("name", nid),
            "tier": _bom_lookup.get(nid, {}).get("tier", "配套"),
            "layer": _bom_lookup.get(nid, {}).get("layer") or None,
            "representative_stocks": _bom_lookup.get(nid, {}).get("representative_stocks") or [],
        }
        for nid in selected_bom_node_ids
    ] if selected_bom_node_ids else []
    _board.barbell_config_json = _bcj
    _board.stock_pool_json = None  # 清除旧分析结果
    await session.commit()

    # 返回多 OOB 更新：左侧列表 + 命令中心 + 生态位区域
    boards = await list_boards_summary(session)
    detail = await get_board_detail(session, board_id)
    if not detail:
        return HTMLResponse('<div>板块不存在</div>', status_code=404)

    from apps.copilot.modules.strategic.z0_render import render_left_sidebar_z0
    left = render_left_sidebar_z0(mode="board", boards=boards, selected_board_id=board_id)

    main = render_command_center_main(detail, selected_phase_id=detail.get("active_phase_id"))
    ecosystem_html = render_ecosystem_section(detail)

    return HTMLResponse(
        f"<div id='strategic-left-sidebar' hx-swap-oob='innerHTML'>{left}</div>"
        f"<div id='strategic-command-main' hx-swap-oob='innerHTML'>{main}{ecosystem_html}</div>"
        f"<div id='strategic-edit-modal-root' hx-swap-oob='innerHTML'></div>"
        f"<div id='genesis-toast' hx-swap-oob='innerHTML'>"
        f"<div class='fixed bottom-4 right-4 bg-indigo-700 text-white text-xs px-3 py-2 rounded-lg z-50'>"
        f"✓ 板块「{_esc(name)}」已更新</div></div>"
    )


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
    # 从 form 中提取 concept_* 字段
    selected_concepts: list[str] = []
    for k, v in payload.items():
        if k.startswith("concept_") and v:
            selected_concepts.append(v)

    # 从 form 中提取 bom_selected_* 字段（用户选定的 BOM 节点）
    selected_bom_nodes: list[dict[str, str]] = []
    bom_id_map: dict[int, str] = {}
    for k, v in payload.items():
        if k.startswith("bom_selected_id_") and v:
            idx = k.replace("bom_selected_id_", "")
            try:
                idx_int = int(idx)
                bom_id_map[idx_int] = v
            except ValueError:
                pass
    for idx_int, nid in bom_id_map.items():
        name = payload.get(f"bom_selected_name_{idx_int}", nid)
        tier = payload.get(f"bom_selected_tier_{idx_int}", "配套")
        layer = payload.get(f"bom_selected_layer_{idx_int}", "")
        selected_bom_nodes.append({
            "node_id": nid,
            "name": name,
            "tier": tier,
            "layer": layer or None,
        })

    board = await genesis_apply(
        session,
        {
            "board_title": payload.get("board_title"),
            "wind_scan_id": payload.get("wind_scan_id") or None,
            "horizon_years": payload.get("horizon_years") or 10,
            "start_year": payload.get("start_year") or 2026,
            "niche_default": payload.get("niche_default"),
            "selected_concepts": selected_concepts,
            "selected_bom_nodes": selected_bom_nodes,
            "sector": payload.get("sector") or "",
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
        f"<div id='genesis-toast' hx-swap-oob='innerHTML'>"
        f"<div class='fixed bottom-4 right-4 bg-emerald-700 text-white text-xs px-3 py-2 rounded-lg z-50'>"
        f"✓ 智能建板「{_esc(board.name)}」已创建</div>"
        f"</div>"
    )


@router.delete("/api/strategic/boards/{board_id}", response_class=HTMLResponse)
async def api_delete_board(
    board_id: int,
    session: AsyncSession = Depends(get_db),
):
    """删除战略板块（v5.4 含级联删除 phases/symbols/probes/cvm）。"""
    from apps.copilot.modules.strategic.service import delete_board, count_boards

    ok = await delete_board(session, board_id)
    if not ok:
        return HTMLResponse('<p class="text-red-500 text-xs">板块不存在</p>', status_code=404)
    await session.commit()

    boards = await list_boards_summary(session)
    left = render_left_sidebar_z0(
        mode="board", boards=boards, selected_board_id=None
    )
    return HTMLResponse(
        f"<div id='strategic-left-sidebar' hx-swap-oob='innerHTML'>{left}</div>"
        f"<div id='strategic-board-list' hx-swap-oob='innerHTML'>{left}</div>"
        f"<div id='strategic-command-main' hx-swap-oob='innerHTML'><div class='p-6 text-sm text-gray-500'>板块已删除 · 请从左侧选择</div></div>"
        f"<div id='strategic-phase-panel' hx-swap-oob='innerHTML'></div>"
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


@router.post("/api/strategic/phases/{phase_id}/cvm/enrich-t2", response_class=HTMLResponse)
async def api_cvm_enrich_t2(
    phase_id: int,
    session: AsyncSession = Depends(get_db),
):
    """T2 语义增强：对已跑 L1 评分的 CVM 行执行 C2/C5/C6 语义分析。"""
    from apps.copilot.metrics.cvm_t2_semantic import score_peer_set_t2
    from apps.copilot.db.models import CvmScorecard

    try:
        rows = await run_cvm_for_phase(session, phase_id)
    except ValueError as e:
        return HTMLResponse(
            f'<div class="text-xs text-red-700 bg-red-50 rounded-lg px-3 py-2">{_esc(str(e))}</div>'
        )
    # T2 语义增强（在 run_cvm_for_phase 的 DB 写入基础上更新）
    t2_rows = score_peer_set_t2(rows, scene="z0_t2_concept_analysis", model_override="claude-opus-4-6")
    # 回写 DB
    for row in t2_rows:
        sym = row.get("symbol", "")
        if not sym:
            continue
        await session.execute(
            CvmScorecard.__table__.update()
            .where(CvmScorecard.phase_id == phase_id)
            .where(CvmScorecard.symbol == sym)
            .values(
                scores_json=row.get("scores", {}),
                provisional=row.get("provisional", False),
            )
        )
    await session.commit()
    dispatch = await get_active_dispatch_for_phase(session, phase_id)
    return HTMLResponse(render_cvm_matrix_table(phase_id, t2_rows, dispatch=dispatch))


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


@router.post("/api/strategic/z0/concept-analysis")
async def api_concept_analysis(
    concept: str = Query(...),
    parent: str = Query(""),
):
    """T2 深度分析 v5.3：对单个A股概念板，基于其政第原文引用进行 Claude Opus 深度解读。
    
    Returns JSON with fields: summary, relevance_level, policy_phase, revenue_transmission, investment_implication.
    """
    from apps.common.ai_dispatcher import AIDispatcher
    from apps.copilot.db.database import AsyncSessionLocal
    from apps.copilot.db.models import WindScan
    from sqlalchemy import select
    from fastapi.responses import JSONResponse

    sub_concepts = []
    try:
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
        return JSONResponse(
            {"error": f'未找到概念 "{concept}" 的证据数据', "summary": "无数据", "relevance_level": "N/A", "policy_phase": "N/A", "revenue_transmission": "N/A", "investment_implication": "无"},
            status_code=404
        )

    quotes = target.get("evidence_quotes") or []
    doc_count = target.get("doc_count", 0)

    if not quotes:
        return JSONResponse(
            {"error": "无原文引用", "summary": "该概念暂无原文引用数据", "relevance_level": "N/A", "policy_phase": "N/A", "revenue_transmission": "N/A", "investment_implication": f"关联文档数={doc_count}"},
            status_code=200
        )

    def _fmt_quote(q) -> str:
        if isinstance(q, dict):
            d = q.get("direction", "")
            s = q.get("impact_score", "")
            txt = q.get("quote", "")[:500]
            return f"[{d}·score={s}] {txt}"
        return f"[quote] {str(q)[:500]}"

    quote_text = "\n".join(
        f"[{i+1}] {_fmt_quote(q)}"
        for i, q in enumerate(quotes[:10])
    )

    prompt = f"""你是A股投研政策分析专家。以下是与「{concept}」概念相关的 {doc_count} 篇政策文档中的关键原文引用：

{quote_text}

请基于上述原文证据，从以下维度进行深度解读，并以纯净JSON格式返回（不含markdown代码块标记）：

{{
  "summary": "1-3句话总结国家对该概念的战略意图和政策分量",
  "relevance_level": "强关联/显著关联/间接关联/弱关联",
  "policy_phase": "概念期/试点期/加速期/成熟期/调整期",
  "revenue_transmission": "直接营收(订单/补贴/税收)→公司利润/间接收益(产业生态)→估值抬升/政策情绪→短期波动",
  "investment_implication": "1-2句话投资含义总结（该概念在A股的投资价值判断）"
}}

判断标准：
- summary: 综合所有引用，提炼国家战略意图
- relevance_level: 强关联=政策专指该概念·号令式表述 / 显著=明确提及·扶持措施具体 / 间接=泛化表述/被包含在其他战略中 / 弱=仅名义提及
- policy_phase: 根据政策内容判断该概念所处发展阶段
- revenue_transmission: 政策利好如何传导至上市公司基本面
- investment_implication: 站在A股投资者角度的价值判断和建议

只返回JSON，不要多余文字。"""

    try:
        dispatcher = AIDispatcher.default()
        result = dispatcher.call(
            scene="z0_t2_concept_analysis",
            messages=[
                {"role": "system", "content": "你是顶级投研分析师。用中文回答。只返回JSON，不含markdown标记。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=800,
            model_override="claude-opus-4-6",
            force_route="remote",
        )
        raw = (result.text or "").strip()
        # 清理可能的 markdown 代码块
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        parsed = __import__("json").loads(raw)
    except Exception as e:
        logger.warning(f"T2 concept analysis failed for {concept}: {e}")
        return JSONResponse({
            "summary": f"T2深度分析暂时不可用: {str(e)[:100]}",
            "relevance_level": "待重试",
            "policy_phase": "待重试",
            "revenue_transmission": "待重试",
            "investment_implication": "LLM调用失败，请稍后重试",
        })

    return JSONResponse({
        "summary": str(parsed.get("summary", "")),
        "relevance_level": str(parsed.get("relevance_level", "")),
        "policy_phase": str(parsed.get("policy_phase", "")),
        "revenue_transmission": str(parsed.get("revenue_transmission", "")),
        "investment_implication": str(parsed.get("investment_implication", "")),
    })


@router.get("/api/strategic/z0/living-status", response_class=HTMLResponse)
async def api_z0_living_status(
    board_id: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
):
    """Living Z0 监控面板：显示 D 段活跃状态 + 支持触发心跳。"""
    from apps.copilot.metrics.living_z0 import living_z0_heartbeat

    result = await living_z0_heartbeat(
        session,
        board_id=board_id,
        do_s0_refresh=True,
    )

    alerts = result.get("alerts", ["—"])
    s0 = result.get("s0", {})
    m1 = s0.get("m1", {})
    m5 = s0.get("m5", {})

    alert_html = ""
    for a in alerts:
        icon = "🟡" if a != "stable" else "🟢"
        cls = "text-amber-700 bg-amber-50" if a != "stable" else "text-emerald-700 bg-emerald-50"
        alert_html += f'<span class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded {cls}">{icon} {_esc(a)}</span> '

    html = f"""<div class="rounded-lg border border-gray-200 bg-white px-3 py-2 space-y-2">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium text-gray-700">
          🫀 Living Z0 段D · {_esc(result.get("as_of", "")[:19])}
        </span>
        <button type="button"
                class="text-[9px] px-2 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400 transition-all"
                hx-get="/api/strategic/z0/living-status{'?board_id=' + str(board_id) if board_id else ''}"
                hx-target="#living-z0-panel"
                hx-swap="outerHTML">
          ♻ 刷新心跳
        </button>
      </div>
      <div class="flex flex-wrap gap-1.5">""" + alert_html + """</div>
      <div class="grid grid-cols-2 gap-2 text-[10px] text-gray-500">
        <div class="rounded bg-gray-50 px-2 py-1">
          <span class="text-gray-400">M1 宏观</span>
          <br><span class="font-medium text-gray-700">{m1.get("status", "—")}</span>
        </div>
        <div class="rounded bg-gray-50 px-2 py-1">
          <span class="text-gray-400">M5 流动性</span>
          <br><span class="font-medium text-gray-700">{m5.get("status", "—")}</span>
        </div>
      </div>
    </div>"""
    return HTMLResponse(html)


def _parse_llm_json(raw: str) -> dict:
    """鲁棒解析 LLM 返回的 JSON 字符串。"""
    import json as _json

    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return _json.loads(text[start : end + 1])
        except _json.JSONDecodeError:
            pass
    return {}
