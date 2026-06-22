"""战略板块 HTML 渲染。

[Ref: 30_ §4 · §8 · 37_ v2.0]
"""
from __future__ import annotations

import html
from typing import Any, Optional

_BOARD_COLOR = {
    "indigo": ("border-indigo-500", "bg-indigo-600", "bg-indigo-50", "text-indigo-800"),
    "emerald": ("border-emerald-500", "bg-emerald-600", "bg-emerald-50", "text-emerald-800"),
    "amber": ("border-amber-500", "bg-amber-600", "bg-amber-50", "text-amber-800"),
    "violet": ("border-violet-500", "bg-violet-600", "bg-violet-50", "text-violet-800"),
}


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


# ── 赛道官方命名体系 ──
# 从 z0_policy_keywords.yaml 读取 display_name，确保全仓统一使用「人工智能产业」而非「AI算力」等
_SECTOR_DISPLAY_NAME_CACHE: dict[str, str] | None = None


def get_sector_display_name(sector_key: str) -> str:
    """根据 sector key 返回官方展示名（display_name）。

    数据源：z0_policy_keywords.yaml canonical_sectors.*.display_name
    参见 L3 规约：36_Z0-M2政策赛道T1-语义工程化方案.md §3.1.
    """
    global _SECTOR_DISPLAY_NAME_CACHE
    if _SECTOR_DISPLAY_NAME_CACHE is None:
        try:
            from pathlib import Path
            import yaml as _yaml
            cfg_path = (
                Path(__file__).resolve().parents[4]
                / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
            )
            with cfg_path.open(encoding="utf-8") as f:
                cfg = _yaml.safe_load(f) or {}
            cs_map: dict[str, dict] = cfg.get("canonical_sectors") or {}
            _SECTOR_DISPLAY_NAME_CACHE = {
                k: str(v.get("display_name") or k)
                for k, v in cs_map.items()
            }
        except Exception:
            _SECTOR_DISPLAY_NAME_CACHE = {}
    return _SECTOR_DISPLAY_NAME_CACHE.get(sector_key, sector_key)


def load_curated_bom(sector_key: str) -> list[dict]:
    """加载指定赛道的定制化 BOM 节点列表（从 z0_policy_keywords.yaml 读取）。

    数据源：canonical_sectors.*.curated_bom_nodes
    每个节点：{node_id, name, tier, layer}
    """
    try:
        from pathlib import Path
        import yaml as _yaml
        cfg_path = (
            Path(__file__).resolve().parents[4]
            / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
        )
        with cfg_path.open(encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}
        cs = (cfg.get("canonical_sectors") or {}).get(sector_key) or {}
        nodes = cs.get("curated_bom_nodes") or []
        return list(nodes)
    except Exception:
        return []


def load_curated_bom_as_proposal(sector_key: str) -> dict:
    """将定制化 BOM 包装为 LLM 提案格式（bom_proposal），供模板 Step 3 消费。

    返回格式：
        {"status": "ok", "bom_nodes": [...], "top_recommendations": [...],
         "industry_summary": "..."}
    """
    nodes = load_curated_bom(sector_key)
    if not nodes:
        return {
            "status": "ok",
            "bom_nodes": [],
            "top_recommendations": [],
            "industry_summary": "",
        }
    # 核心节点自动列为 TOP 推荐
    top_ids = [n["node_id"] for n in nodes if n.get("tier") == "核心"]
    return {
        "status": "ok",
        "bom_nodes": nodes,
        "top_recommendations": top_ids,
        "industry_summary": "以下为经人工筛选与深度评估的 AI 算力产业链关键节点，覆盖 L1-L5 全栈架构。",
    }


def _md(text: Optional[str]) -> str:
    if not text:
        return "<p class='text-sm text-gray-400'>暂无内容</p>"
    paras = [_esc(p.strip()) for p in text.split("\n\n") if p.strip()]
    return "".join(f"<p class='text-xs text-gray-600 mb-1'>{p}</p>" for p in paras)


def board_color_classes(token: str) -> tuple[str, str, str, str]:
    return _BOARD_COLOR.get(token) or _BOARD_COLOR["indigo"]


def render_alert_badges(counts: dict[str, int]) -> str:
    r = int(counts.get("red") or 0)
    y = int(counts.get("yellow") or 0)
    g = int(counts.get("green") or 0)
    p = int(counts.get("pending") or 0)
    parts = []
    if r:
        parts.append(f"<span class='text-xs'>🔴{r}</span>")
    if y:
        parts.append(f"<span class='text-xs'>🟡{y}</span>")
    if g:
        parts.append(f"<span class='text-xs'>🟢{g}</span>")
    if p and not (r or y or g):
        parts.append(f"<span class='text-xs text-gray-400'>⚪{p}</span>")
    return " ".join(parts) or "<span class='text-xs text-gray-400'>—</span>"


def render_board_list(boards, *, selected_id=None):
    if not boards:
        return (
            "<div class='p-4 text-center text-sm text-gray-500'>"
            "<p class='mb-3'>尚无战略板块</p>"
            "<button type='button' class='text-indigo-600 font-medium underline' "
            "hx-post='/api/strategic/boards/seed-ai' "
            "hx-target='#strategic-board-list' hx-swap='innerHTML'>"
            "加载 AI 产业生态样板</button>"
            "</div>"
        )
    rows = []
    for b in boards:
        bid = b["id"]
        sel = bid == selected_id
        border, bar, bg, text = board_color_classes(b.get("color_token") or "indigo")
        sel_cls = f"border-l-4 {border} {bg}" if sel else "border-l-4 border-transparent hover:bg-gray-50"
        is_tmpl = b.get("is_template", False)
        tmpl_badge = '<span class="text-[9px] px-1 py-0 rounded bg-amber-100 text-amber-700 shrink-0">模板</span>' if is_tmpl else ""
        rows.append(
            f"<div class='group flex items-center {sel_cls}'>"
            f"<div role='button' tabindex='0' "
            f"class='flex-1 block px-3 py-2.5 cursor-pointer min-w-0 strategic-board-item' "
            f"data-board-id='{bid}' "
            f"hx-get='/api/strategic/command-center?board_id={bid}' "
            f"hx-target='#strategic-command-main' hx-swap='innerHTML' "
            f"hx-push-url='/planning?view=roadmap&board_id={bid}'>"
            f"<div class='flex items-center gap-1.5'>"
            f"<span class='font-semibold text-gray-900 text-sm leading-snug truncate'>{_esc(b['name'])}</span>"
            f"{tmpl_badge}"
            f"</div>"
            f"<div class='text-xs text-gray-500 mt-0.5'>{b['horizon_start']}–{b['horizon_end']}</div>"
            f"<div class='text-xs text-gray-600 mt-1 truncate'>▶ {_esc(b.get('active_phase_name') or '—')}</div>"
            f"<div class='mt-1'>{render_alert_badges(b.get('alerts') or {})}</div>"
            f"</div>"
            f"<button type='button' "
            f"class='shrink-0 px-2 py-1 text-[10px] text-gray-400 hover:text-red-600 hover:bg-red-50 rounded opacity-0 group-hover:opacity-100 transition' "
            f"hx-delete='/api/strategic/boards/{bid}' "
            f"hx-target='#strategic-board-list' hx-swap='outerHTML' "
            f"hx-confirm=\"确认删除「{_esc(b['name'])}」？此操作不可撤销。\">"
            f"✕"
            f"</button>"
            f"</div>"
        )
    return "".join(rows)


def render_strategic_timeline(board, *, selected_phase_id=None):
    h0 = board["horizon_start"]
    h1 = board["horizon_end"]
    span = max(h1 - h0, 1)
    today = __import__("datetime").date.today()
    pin_pct = max(0, min(100, int((today.year - h0) * 100 / span)))

    blocks: list[str] = []
    wave_colors = ["bg-indigo-700", "bg-indigo-500", "bg-indigo-400", "bg-indigo-300"]
    for ph in board.get("phases") or []:
        left = max(0, (ph["start_year"] - h0) * 100 / span)
        width = max(4, (ph["end_year"] - ph["start_year"] + 1) * 100 / span)
        wno = int(ph.get("wave_no") or 1)
        color = wave_colors[min(wno - 1, len(wave_colors) - 1)]
        sel_ring = "ring-2 ring-offset-1 ring-indigo-400" if ph["id"] == selected_phase_id else ""
        blocks.append(
            f"<button type='button' title='{_esc(ph['name'])}' "
            f"class='absolute top-2 h-8 rounded-md {color} text-white text-[10px] px-1 truncate {sel_ring} "
            f"strategic-phase-bar' data-phase-id='{ph['id']}' "
            f"style='left:{left:.1f}%;width:{width:.1f}%;' "
            f"hx-get='/api/strategic/phases/{ph['id']}/panel' "
            f"hx-target='#strategic-phase-panel' hx-swap='innerHTML'>"
            f"🌊{wno}</button>"
        )

    cards: list[str] = []
    for ph in board.get("phases") or []:
        stats = ph.get("stats") or {}
        alerts = ph.get("alert_counts") or {}
        prog = ph.get("progress_pct") or 0
        sel_border = "ring-2 ring-indigo-400" if ph["id"] == selected_phase_id else "border-gray-100"
        cards.append(
            f"<div class='border rounded-xl p-4 {sel_border} bg-white shadow-sm'>"
            f"<div class='flex flex-wrap items-start justify-between gap-2 mb-2'>"
            f"<div>"
            f"<h4 class='font-semibold text-gray-900 text-sm'>🌊 {_esc(ph['name'])}</h4>"
            f"<p class='text-xs text-gray-500'>{ph['start_year']}–{ph['end_year']}</p>"
            f"</div>"
            f"<span class='text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600'>"
            f"进度 {prog}%</span></div>"
            f"<p class='text-xs text-gray-600 line-clamp-2 mb-2'>{_esc(ph.get('situation_md') or '')[:120]}</p>"
            f"<div class='text-xs text-gray-500 mb-2'>"
            f"猎物 {ph.get('watch_count', 0)} · "
            f"执行 {stats.get('executing', 0)} · "
            f"规划 {stats.get('planning', 0) + stats.get('roadmap', 0)} · "
            f"雷达 {stats.get('radar', 0)}</div>"
            f"<div class='mb-2'>{render_alert_badges(alerts)}</div>"
            f"<div class='h-1.5 bg-gray-100 rounded-full overflow-hidden mb-3'>"
            f"<div class='h-full bg-indigo-500 rounded-full' style='width:{prog}%'></div></div>"
            f"<div class='flex flex-wrap gap-2'>"
            f"<button type='button' class='text-xs px-2 py-1 rounded-lg bg-indigo-50 text-indigo-700 "
            f"hover:bg-indigo-100' "
            f"hx-get='/api/strategic/phases/{ph['id']}/panel' "
            f"hx-target='#strategic-phase-panel' hx-swap='innerHTML'>详情</button>"
            f"<button type='button' class='text-xs px-2 py-1 rounded-lg border border-gray-200 "
            f"text-gray-600 hover:bg-gray-50' "
            f"hx-get='/api/strategic/phases/{ph['id']}/expand' "
            f"hx-target='#strategic-phase-expand-{ph['id']}' hx-swap='innerHTML'>"
            f"展开战术层</button></div>"
            f"<div id='strategic-phase-expand-{ph['id']}' class='mt-3'></div>"
            f"</div>"
        )

    return (
        f"<div class='mb-6'>"
        f"<h3 class='text-sm font-semibold text-gray-800 mb-2'>10 年战略时间轴</h3>"
        f"<div class='relative h-12 bg-gray-50 border border-dashed border-gray-200 rounded-lg overflow-x-auto'>"
        f"<div class='relative min-w-[640px] h-full px-2'>"
        f"<div class='absolute bottom-0 left-0 right-0 flex justify-between text-[10px] text-gray-400 px-1'>"
        f"<span>{h0}</span><span>{h1}</span></div>"
        f"<div class='absolute top-0 bottom-4 w-px bg-rose-400 z-10' style='left:{pin_pct:.1f}%' "
        f"title='当前'></div>"
        f"{''.join(blocks)}"
        f"</div></div></div>"
        f"<div class='grid gap-3 sm:grid-cols-2'>{''.join(cards)}</div>"
    )


def render_phase_panel(phase: dict[str, Any]) -> str:
    probes = phase.get("probes") or []
    jl1 = [p for p in probes if p.get("layer") == "JL1"]
    jl2 = [p for p in probes if p.get("layer") == "JL2"]

    def probe_rows(items: list[dict]) -> str:
        if not items:
            return "<p class='text-xs text-gray-400'>未配置探针</p>"
        rows = []
        for p in items:
            st = p.get("status") or "pending"
            icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(st, "⚪")
            val = p.get("latest_value")
            val_txt = _esc(val) if val is not None else "pending"
            rows.append(
                f"<details class='border-b border-gray-50 py-2 last:border-0'>"
                f"<summary class='cursor-pointer text-xs flex items-center justify-between gap-2'>"
                f"<span>{icon} {_esc(p.get('label'))}</span>"
                f"<span class='font-mono text-gray-500'>{val_txt}</span></summary>"
                f"<div class='mt-1 pl-4 text-[11px] text-gray-500 space-y-0.5'>"
                f"<p>Key: <code>{_esc(p.get('probe_key'))}</code></p>"
                f"<p>频次: {_esc(p.get('cadence'))} · 源: {_esc(p.get('source_hint'))}</p>"
                f"<p>{_esc(p.get('blocker') or '')}</p></div></details>"
            )
        return "".join(rows)

    sym_rows = []
    for s in phase.get("symbols") or []:
        stage = s.get("funnel_stage")
        stage_chip = (
            f"<span class='text-[10px] px-1.5 py-0.5 rounded bg-gray-100'>{_esc(stage)}</span>"
            if stage
            else "<span class='text-[10px] text-gray-400'>未入漏斗</span>"
        )
        sym_rows.append(
            f"<li class='flex items-center justify-between gap-2 py-1.5 border-b border-gray-50 text-xs'>"
            f"<span><span class='font-mono font-medium'>{_esc(s['symbol'])}</span> "
            f"<span class='text-gray-500'>{_esc(s.get('role_tag') or '')}</span></span>"
            f"{stage_chip}</li>"
        )

    barbell = phase.get("cso_barbell_pct_json") or {}
    barbell_html = ""
    if barbell:
        parts = [f"{k} {v}%" for k, v in barbell.items() if v]
        barbell_html = (
            f"<div class='text-xs bg-slate-50 rounded-lg p-2 mb-3'>"
            f"<span class='font-medium text-slate-700'>CSO 杠铃 · </span>"
            f"{_esc(' · '.join(parts))}</div>"
        )

    traps = (phase.get("barbell_config_json") or {}).get("pseudo_tech_traps") or []
    traps_html = ""
    if traps:
        traps_html = (
            "<div class='mt-3 border border-rose-100 rounded-lg p-2 bg-rose-50/50'>"
            "<p class='text-xs font-medium text-rose-800 mb-1'>🛡️ 伪科技三死穴（advisory）</p>"
            "<ul class='text-[11px] text-rose-700 list-disc pl-4 space-y-0.5'>"
            + "".join(f"<li>{_esc(t)}</li>" for t in traps[:3])
            + "</ul></div>"
        )

    sym_list_html = "".join(sym_rows) if sym_rows else "<li class='text-xs text-gray-400'>暂无</li>"

    return (
        f"<div class='strategic-phase-panel'>"
        f"<h3 class='text-sm font-bold text-gray-900 mb-1'>{_esc(phase.get('name'))}</h3>"
        f"<p class='text-xs text-gray-500 mb-3'>{phase.get('start_year')}–{phase.get('end_year')} · "
        f"进度 {phase.get('progress_pct')}%</p>"
        f"<div class='prose prose-sm max-w-none text-gray-700 mb-3 text-xs'>"
        f"<p class='font-medium text-gray-800'>局势研判</p>{_md(phase.get('situation_md'))}"
        f"<p class='font-medium text-gray-800 mt-2'>操盘心法</p>{_md(phase.get('playbook_md'))}"
        f"</div>"
        f"{barbell_html}"
        f"<h4 class='text-xs font-semibold text-gray-700 mb-1'>JL1 宏观</h4>{probe_rows(jl1)}"
        f"<h4 class='text-xs font-semibold text-gray-700 mt-3 mb-1'>JL2 行业</h4>{probe_rows(jl2)}"
        f"<h4 class='text-xs font-semibold text-gray-700 mt-3 mb-2'>核心猎物池</h4>"
        f"<ul class='max-h-40 overflow-y-auto'>{sym_list_html}</ul>"
        f"{traps_html}"
        f"<form class='mt-4 pt-3 border-t border-gray-100' "
        f"hx-post='/api/strategic/phases/{phase['id']}/reviews' "
        f"hx-target='#strategic-review-toast-{phase['id']}' hx-swap='innerHTML'>"
        f"<label class='text-xs font-medium text-gray-700'>阶段复盘</label>"
        f"<textarea name='review_md' rows='2' required "
        f"class='mt-1 w-full text-xs border border-gray-200 rounded-lg p-2' "
        f"placeholder='记录战略调整理由…'></textarea>"
        f"<button type='submit' class='mt-2 text-xs px-3 py-1.5 rounded-lg bg-gray-800 text-white'>保存复盘</button>"
        f"<div id='strategic-review-toast-{phase['id']}' class='mt-1'></div>"
        f"</form>"
        f"</div>"
    )


def render_command_center_main(board, *, selected_phase_id=None):
    if board is None:
        return (
            "<div class='p-8 text-center text-gray-500 text-sm'>"
            "请从左侧选择战略板块，或加载样板</div>"
        )
    qualitative = ""
    if board.get("qualitative_md"):
        qualitative = (
            f"<div class='mb-4 p-3 rounded-lg bg-gradient-to-r from-indigo-50 to-white "
            f"border border-indigo-100 text-xs text-gray-700'>{_esc(board['qualitative_md'][:300])}</div>"
        )
    barbell = board.get("barbell_config_json") or {}
    sector = barbell.get("genesis_sector") or ""
    sector_display = barbell.get("genesis_sector_display_name") or get_sector_display_name(sector)
    concept_names = barbell.get("genesis_concepts") or []
    concepts_preview = ", ".join(concept_names[:3])
    if len(concept_names) > 3:
        concepts_preview += f"⋯ +{len(concept_names)-3}"

    edit_btn = (
        f"<button type='button' "
        f"class='shrink-0 text-[10px] px-2 py-1 rounded border border-gray-200 text-gray-500 "
        f"hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 transition' "
        f"hx-get='/api/strategic/boards/{board['id']}/edit-modal' "
        f"hx-target='#strategic-edit-modal-root' hx-swap='innerHTML'>"
        f"⚙ 编辑</button>"
    )
    return (
        f"<div>"
        f"<div class='flex flex-wrap items-center justify-between gap-2 mb-2'>"
        f"<div class='flex flex-wrap items-center gap-2'>"
        f"<h2 class='text-base font-bold text-gray-900'>{_esc(board['name'])}</h2>"
        f"<span class='text-xs text-gray-500'>{board['horizon_start']}–{board['horizon_end']}</span>"
        f"</div>"
        f"<div class='flex items-center gap-2'>{edit_btn}</div>"
        f"</div>"
        + (f"<div class='text-[10px] text-gray-400 mb-2'>赛道：{_esc(sector_display)} · 概念：{_esc(concepts_preview)}</div>" if sector else "")
        + f"{qualitative}"
        f"{render_strategic_timeline(board, selected_phase_id=selected_phase_id)}"
        f"<div id='strategic-edit-modal-root'></div>"
        f"</div>"
    )


def render_strategic_chip(tag, *, symbol: str, editable: bool = False):
    sym = _esc(symbol)
    if not tag:
        edit = ""
        if editable:
            edit = (
                f"<button type='button' class='ml-1 text-[10px] text-indigo-600 underline' "
                f"hx-get='/api/strategic/tags/edit?symbol={sym}' "
                f"hx-target='#strategic-promote-modal-root' hx-swap='innerHTML'>打标签</button>"
            )
        return (
            f"<span class='inline-flex items-center text-[10px] px-2 py-0.5 rounded-full "
            f"border border-dashed border-gray-300 text-gray-500 bg-gray-50'>"
            f"未归属战略{edit}</span>"
        )
    _, _, bg, text = board_color_classes(tag.get("color_token") or "indigo")
    role = tag.get("role_tag")
    role_txt = f" · {_esc(role)}" if role else ""
    wave = tag.get("wave_no")
    wave_txt = f"第{wave}波 · " if wave else ""
    edit_btn = ""
    if editable:
        edit_btn = (
            f"<button type='button' class='ml-1 text-[10px] opacity-80 underline' "
            f"hx-get='/api/strategic/tags/edit?symbol={sym}' "
            f"hx-target='#strategic-promote-modal-root' hx-swap='innerHTML'>改</button>"
        )
    return (
        f"<span class='inline-flex items-center text-[10px] px-2 py-0.5 rounded-full border "
        f"{bg} {text} font-medium' title='战略归属'>"
        f"🏷 {_esc(tag.get('board_name', '')[:8])} · {wave_txt}"
        f"{_esc(tag.get('phase_name', '')[:12])}{role_txt}{edit_btn}</span>"
    )


def render_strategic_context_bar(tag, jl_summary: str):
    if not tag:
        return ""
    pid = tag.get("phase_id")
    board = _esc(tag.get("board_name", ""))
    phase = _esc(tag.get("phase_name", ""))
    jl = _esc(jl_summary or "⚪ pending")
    return (
        f"<div class='px-4 py-2.5 text-xs text-indigo-900 bg-indigo-50/50'>"
        f"<span class='font-medium text-indigo-800'>战略上下文</span>"
        f"<span class='text-indigo-700/90 ml-2'>🏷 {board} · {phase} · JL1/JL2：{jl}</span>"
        f"<a class='text-indigo-700 underline ml-2 whitespace-nowrap' "
        f"href='/planning?view=roadmap&amp;board_id={tag.get('board_id')}"
        f"&amp;phase_id={pid}'>板块详情 →</a>"
        f"</div>"
    )


def _render_board_phase_selects(options, suggested, *, field_prefix=""):
    if not options:
        return (
            "<p class='text-xs text-gray-500 mb-2'>尚无战略板块 · "
            "<a href='/planning?view=roadmap' class='text-indigo-600 underline'>去路线图创建</a></p>"
        )
    sb = suggested or {}
    board_opts = []
    for b in options:
        sel = " selected" if b["board_id"] == sb.get("board_id") else ""
        board_opts.append(
            f"<option value='{b['board_id']}'{sel}>{_esc(b['board_name'])}</option>"
        )
    phase_opts: list[str] = []
    role_opts = ["<option value=''>—</option>"]
    default_board = sb.get("board_id") or options[0]["board_id"]
    for b in options:
        if b["board_id"] != default_board:
            continue
        for ph in b.get("phases") or []:
            sel = " selected" if ph["phase_id"] == sb.get("phase_id") else ""
            phase_opts.append(
                f"<option value='{ph['phase_id']}' data-board='{b['board_id']}'{sel}>"
                f"{_esc(ph['label'])}</option>"
            )
            if ph["phase_id"] == sb.get("phase_id"):
                for r in ph.get("roles") or []:
                    rsel = " selected" if r == sb.get("role_tag") else ""
                    role_opts.append(f"<option value='{_esc(r)}'{rsel}>{_esc(r)}</option>")
    suggest_html = ""
    if sb.get("reason"):
        suggest_html = (
            f"<p class='text-xs text-violet-700 bg-violet-50 rounded px-2 py-1 mb-2'>"
            f"💡 建议：{_esc(sb['reason'])}</p>"
        )
    phase_select_inner = "".join(phase_opts) if phase_opts else "<option value=''>—</option>"
    return (
        f"{suggest_html}"
        f"<div class='grid grid-cols-1 sm:grid-cols-2 gap-2 mb-2'>"
        f"<div><label class='text-xs text-gray-600'>战略板块</label>"
        f"<select name='board_id' class='w-full text-xs border rounded-lg px-2 py-1.5 mt-0.5 "
        f"strategic-board-select' data-prefix='{field_prefix}'>{''.join(board_opts)}</select></div>"
        f"<div><label class='text-xs text-gray-600'>阶段</label>"
        f"<select name='phase_id' class='w-full text-xs border rounded-lg px-2 py-1.5 mt-0.5 "
        f"strategic-phase-select'>{phase_select_inner}</select></div>"
        f"</div>"
        f"<div class='mb-2'><label class='text-xs text-gray-600'>角色</label>"
        f"<select name='role_tag' class='w-full text-xs border rounded-lg px-2 py-1.5 mt-0.5'>"
        f"{''.join(role_opts)}</select></div>"
        f"<label class='flex items-center gap-2 text-xs text-gray-600 mb-2'>"
        f"<input type='checkbox' name='add_to_watchlist' value='1' checked />"
        f"同步加入该阶段核心猎物池</label>"
    )


def render_promote_modal_radar(*, candidate_id, symbol, name, options, suggested):
    sym = _esc(symbol)
    display = _esc(name or symbol)
    return (
        f"<div class='fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/40' "
        f"id='strategic-promote-modal' onclick=\"if(event.target===this) this.remove()\">"
        f"<div class='bg-white rounded-xl shadow-xl max-w-md w-full p-5' onclick='event.stopPropagation()'>"
        f"<div class='flex justify-between items-start mb-3'>"
        f"<h3 class='font-bold text-gray-900'>晋级到规划区</h3>"
        f"<button type='button' class='text-gray-400 text-xl' "
        f"onclick=\"this.closest('#strategic-promote-modal').remove()\">×</button></div>"
        f"<p class='text-sm text-gray-600 mb-3'>{display} <span class='font-mono text-xs'>({sym})</span></p>"
        f"<form hx-post='/api/radar/candidates/{int(candidate_id)}/promote' "
        f"hx-target='#radar-candidates-list' hx-swap='innerHTML' "
        f"hx-on::after-request=\"this.closest('#strategic-promote-modal')?.remove()\">"
        f"<fieldset class='border border-gray-100 rounded-lg p-3 mb-3'>"
        f"<legend class='text-xs font-medium text-gray-700 px-1'>战略归属（可选）</legend>"
        f"{_render_board_phase_selects(options, suggested)}"
        f"</fieldset>"
        f"<div class='flex flex-wrap gap-2 justify-end'>"
        f"<button type='button' class='text-sm px-3 py-1.5 rounded-lg border border-gray-200' "
        f"onclick=\"this.closest('#strategic-promote-modal').remove()\">取消</button>"
        f"<button type='submit' name='skip_tags' value='1' "
        f"class='text-sm px-3 py-1.5 rounded-lg border border-amber-200 text-amber-800' "
        f"onclick='return confirm(\"该标的将不纳入任何战略板块监控聚合，确定跳过？\")'>"
        f"跳过标签</button>"
        f"<button type='submit' class='text-sm px-3 py-1.5 rounded-lg bg-blue-600 text-white'>"
        f"确认晋级</button></div></form></div></div>"
    )


def render_tag_edit_modal(*, symbol, name, options, current):
    sym = _esc(symbol)
    suggested = current or {}
    return (
        f"<div class='fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/40' "
        f"id='strategic-promote-modal' onclick=\"if(event.target===this) this.remove()\">"
        f"<div class='bg-white rounded-xl shadow-xl max-w-md w-full p-5' onclick='event.stopPropagation()'>"
        f"<div class='flex justify-between mb-3'><h3 class='font-bold'>战略标签 · {_esc(name)}</h3>"
        f"<button type='button' class='text-gray-400 text-xl' "
        f"onclick=\"this.closest('#strategic-promote-modal').remove()\">×</button></div>"
        f"<form hx-post='/api/strategic/tags' hx-target='body' hx-swap='beforeend' "
        f"hx-on::after-request=\"this.closest('#strategic-promote-modal')?.remove()\">"
        f"<input type='hidden' name='symbol' value='{sym}' />"
        f"{_render_board_phase_selects(options, suggested)}"
        f"<div class='flex gap-2 justify-end mt-3'>"
        f"<button type='submit' name='clear' value='1' class='text-xs px-3 py-1.5 border rounded-lg'>"
        f"清除标签</button>"
        f"<button type='submit' class='text-xs px-3 py-1.5 bg-indigo-600 text-white rounded-lg'>"
        f"保存</button></div></form></div></div>"
    )


def render_strategic_overview_drawer(boards):
    if not boards:
        return "<p class='text-sm text-gray-500 p-4'>暂无战略板块</p>"
    rows = []
    for b in boards:
        bid = b["id"]
        rows.append(
            f"<a href='/planning?view=roadmap&board_id={bid}' "
            f"class='block p-3 border-b border-gray-100 hover:bg-gray-50 no-underline'>"
            f"<div class='font-medium text-sm text-gray-900'>{_esc(b['name'])}</div>"
            f"<div class='text-xs text-gray-500 mt-0.5'>{b['horizon_start']}–{b['horizon_end']} · "
            f"{_esc(b.get('active_phase_name') or '—')}</div>"
            f"<div class='mt-1'>{render_alert_badges(b.get('alerts') or {})}</div></a>"
        )
    return f"<div class='divide-y divide-gray-50'>{''.join(rows)}</div>"


# ════════════════════════════════════════════════════════════════
#  生态位分析区域（v2.0 · BOM 节点分组 + 5 因子打分明细）
# ════════════════════════════════════════════════════════════════

def render_ecosystem_section(board: dict[str, Any]) -> str:
    """生态位分析区域：已完成 → 展示 v2.0 BOM 标的池；进行中 → 进度+JS轮询；未开始 → 触发按钮。"""
    board_id = board["id"]
    stock_pool = board.get("stock_pool_json")

    # 已完成
    if stock_pool and stock_pool.get("status") == "ok":
        return _render_ecosystem_result(board_id, stock_pool)

    # 进行中
    if stock_pool and stock_pool.get("status") == "pending":
        task_id = stock_pool.get("task_id", "")
        return _render_ecosystem_pending(board_id, task_id)

    # 未开始
    barbell = board.get("barbell_config_json") or {}
    sector = barbell.get("genesis_sector") or ""
    sector_display = barbell.get("genesis_sector_display_name") or get_sector_display_name(sector)
    concepts = barbell.get("genesis_concepts") or []

    if not sector or not concepts:
        return (
            "<div id='ecosystem-section' class='mt-6 border border-dashed border-gray-200 rounded-lg p-4 bg-gray-50/50'>"
            "<p class='text-xs text-gray-400 text-center'>尚未选择赛道与概念，无法触发生态位分析。请通过智能建板创建。</p>"
            "</div>"
        )

    concept_badges = "".join(
        f'<span class="text-xs px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700">{_esc(c)}</span>'
        for c in concepts[:5]
    )
    return f"""<div id='ecosystem-section' class='mt-6 border border-dashed border-indigo-200 rounded-lg p-4 bg-indigo-50/30'>
  <div class='flex flex-wrap items-center justify-between gap-3 mb-2'>
    <div>
      <h3 class='text-sm font-semibold text-gray-800'>🔬 产业生态位分析</h3>
      <p class='text-xs text-gray-500 mt-0.5'>赛道：{_esc(sector_display)} · 概念：{concept_badges}</p>
    </div>
    <button type='button' id='eco-trigger-btn'
            class='text-xs px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition font-medium'
            hx-post='/api/strategic/boards/{board_id}/ecosystem/infer'
            hx-target='#ecosystem-section' hx-swap='outerHTML'>
      调用高级模型深度分析产业生态 + 生成标的池
    </button>
  </div>
  <p class='text-[10px] text-gray-400 mt-1'>分析将包括：BOM 产业链拆解 × 5 因子打分 × 证据链 · 预计 60-90s</p>
</div>"""


def _render_ecosystem_pending(board_id: int, task_id: str) -> str:
    """渲染进行中的进度 UI（原生 JS 轮询）。"""
    return f"""<div id='ecosystem-section' class='mt-6 border border-dashed border-indigo-200 rounded-lg p-4 bg-indigo-50/30'>
  <div class="flex items-center justify-between mb-3">
    <span class="text-sm font-medium text-gray-700">🔬 产业生态位分析</span>
    <div class="flex items-center gap-2">
      <span class="text-xs text-gray-500 tabular-nums" id="eco-timer">0s</span>
      <button type="button" id="eco-cancel-btn"
              class="text-[10px] px-2 py-1 rounded border border-gray-300 text-gray-500 hover:bg-red-50 hover:text-red-600 hover:border-red-300 transition">
        中断分析
      </button>
    </div>
  </div>
  <div class="w-full bg-gray-200 rounded-full h-2.5 mb-1 overflow-hidden">
    <div id="eco-progress" class="bg-indigo-600 h-2.5 rounded-full transition-all duration-700 ease-out" style="width:0%"></div>
  </div>
  <p class="text-xs text-gray-600 mt-3 flex items-center gap-2">
    <span class="animate-spin inline-block w-3.5 h-3.5 border-2 border-gray-300 border-t-indigo-600 rounded-full"></span>
    <span id="eco-hint">正在启动大模型分析...</span>
  </p>
  <p class="text-[10px] text-gray-400 mt-1">预计 60-90s · 请勿关闭页面</p>
  <script>(function(){{
    const BOARD_ID = {board_id};
    const TASK_ID = '{task_id}';
    let _poll_count = 0;
    let _interval = null;

    const _statusUrl = () => '/api/strategic/boards/' + BOARD_ID + '/ecosystem/status/' + TASK_ID + '?poll_count=' + (_poll_count + 1);
    const _cancelUrl = () => '/api/strategic/boards/' + BOARD_ID + '/ecosystem/cancel/' + TASK_ID;

    function _stop() {{ if (_interval) {{ clearInterval(_interval); _interval = null; }} }}

    async function _poll() {{
      _poll_count++;
      try {{
        const r = await fetch(_statusUrl());
        if (!r.ok) return;
        const d = await r.json();
        if (d.status === 'done') {{
          _stop();
          const sec = document.getElementById('ecosystem-section');
          if (sec && d.html) sec.outerHTML = d.html;
          if (window.htmx) htmx.process(sec);
        }} else if (d.status === 'expired') {{
          _stop();
          const sec = document.getElementById('ecosystem-section');
          if (sec) {{
            sec.innerHTML = '<div class=\"flex items-center justify-between\"><span class=\"text-sm font-medium text-amber-700\">⚠️ 分析任务已过期</span><button type=\"button\" class=\"text-xs px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 transition\" onclick=\"_eco_retry()\">🔄 重新分析</button></div><p class=\"text-xs text-amber-600 mt-2\">任务已过期（超过 10 分钟），请重新触发分析。</p>';
            sec.className = 'mt-6 border border-dashed border-amber-200 rounded-lg p-4 bg-amber-50/30';
          }}
        }} else if (d.status === 'processing') {{
          const bar = document.getElementById('eco-progress');
          if (bar) bar.style.width = (d.pct || 0) + '%';
          const timer = document.getElementById('eco-timer');
          if (timer) timer.textContent = (d.elapsed || 0) + 's';
          const hint = document.getElementById('eco-hint');
          if (hint && d.hint) hint.textContent = d.hint;
        }}
      }} catch(e) {{}}
    }}

    window._eco_retry = function() {{
      if (window.htmx) {{
        htmx.ajax('POST', '/api/strategic/boards/' + BOARD_ID + '/ecosystem/infer', {{ target: '#ecosystem-section', swap: 'outerHTML' }});
      }}
    }};

    async function _cancel() {{
      _stop();
      try {{
        const btn = document.getElementById('eco-cancel-btn');
        if (btn) {{ btn.textContent = '正在中断...'; btn.disabled = true; }}
        const r = await fetch(_cancelUrl(), {{ method: 'POST' }});
        if (r.ok) {{
          const sec = document.getElementById('ecosystem-section');
          if (sec) sec.outerHTML = await r.text();
        }}
      }} catch(e) {{
        const sec = document.getElementById('ecosystem-section');
        if (sec) {{
          sec.innerHTML = '<div class=\"flex items-center justify-between\"><span class=\"text-sm font-medium text-red-700\">❌ 中断失败</span><button type=\"button\" class=\"text-xs px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 transition\" onclick=\"_eco_retry()\">🔄 重新分析</button></div><p class=\"text-xs text-red-600 mt-2\">中断操作失败，请重试。</p>';
          sec.className = 'mt-6 border border-dashed border-red-200 rounded-lg p-4 bg-red-50/30';
        }}
      }}
    }}

    function _init() {{
      const cancelBtn = document.getElementById('eco-cancel-btn');
      if (cancelBtn) cancelBtn.addEventListener('click', _cancel);
      _poll();
      _interval = setInterval(_poll, 2000);
    }}

    if (document.readyState === 'loading') {{
      document.addEventListener('DOMContentLoaded', _init);
    }} else {{
      _init();
    }}
  }})();</script>
</div>"""


def _render_ecosystem_result(board_id: int, stock_pool: dict[str, Any]) -> str:
    """渲染生态位分析结果（v2.0：BOM 节点分组 + 5因子打分明细）。"""
    version = stock_pool.get("version", "1.0")

    # v2.0 → BOM 节点分组渲染
    bom_nodes = stock_pool.get("bom_nodes") or []
    if version == "2.0" and bom_nodes:
        return _render_bom_stock_pool(board_id, stock_pool, bom_nodes)

    # v1.0 fallback → concept_pools 渲染（兼容旧数据）
    return _render_concept_pools_result(board_id, stock_pool)


def _render_bom_stock_pool(board_id: int, stock_pool: dict[str, Any], bom_nodes: list[dict]) -> str:
    """v2.0：BOM 节点分组渲染标的池，每只标的含 5 因子打分明细（可展开）。"""
    topo = stock_pool.get("ecosystem_topology", {})
    thesis = stock_pool.get("investment_thesis", "")
    suggested_additions = stock_pool.get("suggested_additions", [])
    excluded_stocks = stock_pool.get("excluded_stocks", [])
    disclaimer = stock_pool.get("disclaimer", "")
    bom_version = stock_pool.get("bom_whitelist_version", "1.0.0")

    # 生态位拓扑
    topo_rows = ""
    layers = [
        ("upstream", "🔺 上游", "原材料/核心技术/基础设施"),
        ("midstream", "⏺ 中游", "核心制造/平台/系统集成"),
        ("downstream", "🔻 下游", "终端产品/应用/服务"),
        ("service_layer", "⚙ 服务层", "配套服务/软件/数据/渠道"),
    ]
    for key, label, hint in layers:
        layer = topo.get(key, {})
        if not layer:
            continue
        role = layer.get("role", "")
        segments = layer.get("key_segments", [])
        seg_badges = "".join(
            f'<span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{_esc(s)}</span>'
            for s in segments
        ) if segments else ""
        topo_rows += (
            f"<div class='py-2 border-b border-gray-100 last:border-0'>"
            f"<span class='text-xs font-medium'>{label}</span>"
            f"<span class='text-[10px] text-gray-400 ml-1'>({hint})</span>"
            f"<p class='text-xs text-gray-600 mt-0.5'>{_esc(role)}</p>"
            + (f'<div class="flex flex-wrap gap-1 mt-1">{seg_badges}</div>' if seg_badges else '')
            + "</div>"
        )

    # BOM 节点 × 标的池
    node_html = ""
    total_stocks = 0
    for node in bom_nodes:
        nid = node.get("node_id", "?")
        name = node.get("name", "?")
        tier = node.get("tier", "核心")
        tier_color = "text-rose-700 bg-rose-50" if tier == "核心" else "text-amber-700 bg-amber-50" if tier == "重要" else "text-gray-600 bg-gray-50"
        rationale = node.get("rationale", "")
        layer_label = node.get("ecosystem_layer", "")
        stocks = node.get("stocks", [])
        total_stocks += len(stocks)

        stock_rows = ""
        for st in stocks:
            sym = st.get("symbol", "??????")
            name_stock = st.get("stock_name", "?")
            pos = st.get("ecosystem_position", "")
            sd = st.get("scoring_detail") or {}
            ec = st.get("exclusion_check") or {}
            composite = sd.get("composite", 0)

            # 排除检查状态
            ec_ok = ec.get("passed", False)
            ec_badge = (
                '<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">排除通过</span>'
                if ec_ok else
                '<span class="text-[10px] px-1.5 py-0.5 rounded bg-rose-100 text-rose-700">排除未通过</span>'
            )

            # composite 颜色
            comp_color = "text-emerald-600" if composite >= 0.8 else "text-amber-600" if composite >= 0.6 else "text-rose-500"

            # 5 因子明细
            factor_detail = ""
            for fk, flabel in [("moat", "壁垒"), ("growth", "成长"), ("profit", "盈利"), ("localize", "国产替代"), ("policy_bond", "政策映射")]:
                fv = sd.get(fk) or {}
                fscore = fv.get("score", "—")
                fscore_txt = f"{fscore:.0%}" if isinstance(fscore, (int, float)) else str(fscore)
                fevidence = fv.get("evidence") or []
                fev_html = ""
                if fevidence:
                    fev_html = "<ul class='list-disc pl-4 space-y-0.5'>" + "".join(
                        f"<li class='text-[10px] text-gray-600'>{_esc(ev)}</li>" for ev in fevidence
                    ) + "</ul>"
                # policy_bond 特殊处理
                if fk == "policy_bond":
                    matched = fv.get("matched_concepts", [])
                    note = fv.get("note", "")
                    fev_html = (
                        f"<p class='text-[10px] text-gray-600'>"
                        f"匹配概念：{', '.join(matched) if matched else '无'}"
                        + (f" · {_esc(note)}" if note else "")
                        + "</p>"
                    )
                factor_detail += (
                    f"<tr class='border-b border-gray-50'>"
                    f"<td class='py-1.5 text-[11px] text-gray-700 font-medium w-20'>{flabel}</td>"
                    f"<td class='py-1.5 text-[11px] font-mono w-14'>{fscore_txt}</td>"
                    f"<td class='py-1.5'>{fev_html}</td>"
                    f"</tr>"
                )

            stock_rows += (
                f"<details class='border rounded-lg mb-0.5'>"
                f"<summary class='flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-gray-50 text-xs'>"
                f"<span class='font-mono font-medium'>{_esc(sym)}</span>"
                f"<span class='font-medium'>{_esc(name_stock)}</span>"
                f"<span class='text-[10px] text-gray-400 ml-1'>{_esc(pos)}</span>"
                f"<span class='ml-auto font-bold {comp_color}'>{composite:.0%}</span>"
                f"{ec_badge}"
                f"</summary>"
                f"<div class='px-3 py-2 bg-gray-50/70'>"
                f"<table class='w-full text-xs'>"
                f"<thead><tr class='text-[10px] text-gray-400'><th class='text-left font-normal w-20'>因子</th><th class='text-left font-normal w-14'>得分</th><th class='text-left font-normal'>证据</th></tr></thead>"
                f"<tbody>{factor_detail}</tbody>"
                f"</table>"
                f"</div>"
                f"</details>"
            )

        if not stock_rows:
            stock_rows = '<p class="text-xs text-gray-400 py-2 text-center">该节点未生成标的</p>'

        node_html += (
            f"<div class='mb-3 border rounded-lg p-3 bg-white'>"
            f"<div class='flex items-center gap-2 mb-2'>"
            f"<span class='text-xs font-semibold text-gray-800'>{_esc(name)}</span>"
            f"<span class='text-[10px] px-1.5 py-0.5 rounded {tier_color}'>{tier}</span>"
            f"<span class='text-[10px] text-gray-400'>({_esc(layer_label)} | node: {_esc(nid)})</span>"
            f"</div>"
            + (f'<p class="text-[10px] text-gray-500 mb-2">{_esc(rationale)}</p>' if rationale else '')
            + f"<div class='space-y-0.5'>{stock_rows}</div>"
            + "</div>"
        )

    # Suggested additions
    additions_html = ""
    if suggested_additions:
        addition_rows = "".join(
            f"<li class='text-xs text-gray-600 flex items-center gap-2'>"
            f"<span class='font-medium'>{_esc(a.get('node_name', '?'))}</span>"
            f"<span class='text-[10px] text-gray-400'>{_esc(a.get('rationale', ''))}</span>"
            f"<span class='text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700'>{a.get('status', 'pending_approval')}</span>"
            f"</li>"
            for a in suggested_additions
        )
        additions_html = (
            f"<div class='mt-3 border border-amber-200 rounded-lg p-3 bg-amber-50/30'>"
            f"<p class='text-xs font-medium text-amber-800 mb-2'>💡 LLM 建议新增节点（需架构师审批）</p>"
            f"<ul class='space-y-1'>{addition_rows}</ul>"
            f"</div>"
        )

    # Excluded stocks
    excluded_html = ""
    if excluded_stocks:
        ex_rows = "".join(
            f"<li class='text-xs text-rose-600 flex items-center gap-2'>"
            f"<span class='font-mono'>{_esc(e.get('symbol', '?'))}</span>"
            f"<span>{_esc(e.get('stock_name', '?'))}</span>"
            f"<span class='text-[10px] px-1.5 py-0.5 rounded bg-rose-100'>{_esc(e.get('exclusion_rule', ''))}</span>"
            f"<span class='text-[10px] text-rose-500'>{_esc(e.get('reason', ''))}</span>"
            f"</li>"
            for e in excluded_stocks
        )
        excluded_html = (
            f"<div class='mt-3 border border-rose-200 rounded-lg p-3 bg-rose-50/30'>"
            f"<p class='text-xs font-medium text-rose-800 mb-2'>🚫 排除标的（{len(excluded_stocks)} 只）</p>"
            f"<ul class='space-y-0.5'>{ex_rows}</ul></div>"
        )

    # 刷新按钮
    refresh_btn = f"""<button type='button'
    class='text-[10px] px-2 py-1 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 mt-2'
    hx-post='/api/strategic/boards/{board_id}/ecosystem/infer'
    hx-target='#ecosystem-section' hx-swap='outerHTML'>🔄 重新分析</button>"""

    if not topo_rows:
        topo_rows = '<p class="text-xs text-gray-400 py-4 text-center">暂无生态位拓扑数据</p>'
    if not node_html:
        node_html = '<p class="text-xs text-gray-400 py-4 text-center">暂未生成标的池</p>'

    return f"""<div id='ecosystem-section' class='mt-6 border border-emerald-200 rounded-lg p-4 bg-emerald-50/30'>
  <div class='flex items-center justify-between mb-3'>
    <h3 class='text-sm font-semibold text-gray-800'>
      🔬 产业生态位分析 <span class='text-[10px] text-emerald-600 font-normal ml-1'>✓ 已完成</span>
      <span class='text-[10px] text-gray-400 font-normal ml-2'>BOM v{bom_version} · 5因子打分 · {total_stocks} 只标的</span>
    </h3>
    {refresh_btn}
  </div>
  {f'<div class="bg-white border border-emerald-100 rounded-lg p-3 mb-3 text-xs text-gray-700">💡 {_esc(thesis)}</div>' if thesis else ''}
  <div class='grid grid-cols-1 md:grid-cols-3 gap-3 mb-3'>
    <div class='bg-white border rounded-lg p-3'>
      <p class='text-xs font-medium text-gray-700 mb-2'>🏗 产业生态位拓扑</p>
      {topo_rows}
    </div>
    <div class='md:col-span-2'>
      {node_html}
      {additions_html}
      {excluded_html}
    </div>
  </div>
  {f'<p class="text-[10px] text-gray-400 italic mt-2">{_esc(disclaimer)}</p>' if disclaimer else ''}
</div>"""


# ── v1.0 兼容（旧 concept_pools 数据） ──

# ════════════════════════════════════════════════════════════════
#  板块编辑模态框
# ════════════════════════════════════════════════════════════════

def _render_bom_node_list(
    bom_nodes: Optional[list[Any]] = None,
    *,
    selected_ids: set[str] | None = None,
) -> str:
    """渲染 BOM 节点列表（可勾选）。支持多种输入格式：
    - (nid, name, tier) 元组
    - (nid, name, tier, layer) 4元组
    - dict 格式 {node_id, name, tier, layer?}
    """
    if not bom_nodes:
        return '<p class="text-[10px] text-gray-400 py-1">当前赛道暂无 BOM 节点定义</p>'
    if selected_ids is None:
        selected_ids = set()

    # 归一化为规范 dict 列表
    normalized: list[dict[str, Any]] = []
    for n in bom_nodes:
        if isinstance(n, dict):
            normalized.append(n)
        elif isinstance(n, (list, tuple)) and len(n) >= 3:
            normalized.append({
                "node_id": str(n[0]),
                "name": str(n[1]),
                "tier": str(n[2]),
                "layer": str(n[3]) if len(n) >= 4 and n[3] else None,
            })
        else:
            continue

    rows = ""
    for n in normalized:
        nid = n.get("node_id", "")
        name = n.get("name", "")
        tier = n.get("tier", "配套")
        layer = n.get("layer") or None

        if tier == "核心":
            dot = "bg-rose-500"
            badge = "text-rose-700 bg-rose-50"
        elif tier == "重要":
            dot = "bg-amber-500"
            badge = "text-amber-700 bg-amber-50"
        else:
            dot = "bg-gray-400"
            badge = "text-gray-600 bg-gray-100"

        # layer 标签（仅在有值时显示）
        layer_badge = ""
        if layer and layer.startswith("L"):
            layer_colors = {
                "L1": "bg-purple-100 text-purple-700",
                "L2": "bg-blue-100 text-blue-700",
                "L3": "bg-cyan-100 text-cyan-700",
                "L4": "bg-teal-100 text-teal-700",
                "L5": "bg-green-100 text-green-700",
            }
            lc = layer_colors.get(layer, "bg-gray-100 text-gray-600")
            layer_badge = f'<span class="text-[9px] px-1 py-0.5 rounded {lc} font-medium">{_esc(layer)}</span>'

        checked = "checked" if nid in selected_ids else ""
        rows += (
            f'<label class="flex items-center gap-2 px-2 py-1 text-xs cursor-pointer hover:bg-gray-50 rounded">'
            f'<input type="checkbox" name="bom_node_{_esc(nid)}" value="{_esc(nid)}" {checked} class="rounded" />'
            f'<span class="w-2 h-2 rounded-full {dot} shrink-0"></span>'
            f'<span class="font-medium text-gray-800">{_esc(name)}</span>'
            f'<span class="text-[10px] px-1.5 py-0.5 rounded {badge}">{_esc(tier)}</span>'
            f'{layer_badge}'
            f'<span class="text-[9px] text-gray-400">({_esc(nid)})</span>'
            f'</label>'
        )
    if not rows:
        return '<p class="text-[10px] text-gray-400 py-1">当前赛道暂无 BOM 节点定义</p>'
    return f'<div class="max-h-48 overflow-y-auto space-y-0.5 bg-white rounded-lg border border-emerald-100 p-2">{rows}</div>'

def render_board_edit_modal(
    *,
    board: dict[str, Any],
    candidates: list[dict[str, Any]],
    bom_nodes: Optional[list[tuple[str, str, str]]] = None,
) -> str:
    """渲染板块编辑模态框（赛道/概念/BOM/时间/名称均可改）。"""
    barbell = board.get("barbell_config_json") or {}
    current_sector = barbell.get("genesis_sector") or ""
    current_concepts = barbell.get("genesis_concepts") or []

    # 找到当前赛道信息（用于渲染概念勾选列表）
    current_sector_data = None
    for c in candidates:
        if c.get("sector") == current_sector:
            current_sector_data = c
            break

    # 预览用
    has_eco = board.get("stock_pool_json") and board.get("stock_pool_json").get("status") == "ok"

    # 已选的 BOM 节点（从 barbell_config_json 读取）
    existing_bom_nodes = barbell.get("genesis_bom_nodes") or []
    existing_bom_ids = {n.get("node_id") for n in existing_bom_nodes if n.get("node_id")}

    # 赛道下拉选项
    sector_opts = ""
    for c in candidates:
        dn = c.get("display_name", c.get("sector", "?"))
        z0 = c.get("z0_plus_score")
        d1 = c.get("d1_score")
        sc_count = len(c.get("sub_concepts") or [])
        z0_str = f"Z0+={int(z0*100)}" if z0 is not None else ""
        label = f"{dn} · {z0_str} · {sc_count}概念"
        sel = " selected" if c.get("sector") == current_sector else ""
        sector_opts += f'<option value="{_esc(c.get("sector",""))}" data-display="{_esc(dn)}"{sel}>{_esc(label)}</option>\n'

    # 概念勾选列表
    concept_rows = ""
    if current_sector_data:
        sub_concepts = current_sector_data.get("sub_concepts") or []
        sub_concepts.sort(key=lambda x: x.get("doc_count", 0), reverse=True)
        for sc in sub_concepts:
            sn = sc.get("sub_name", "?")
            dc = sc.get("doc_count", 0)
            ac = sc.get("avg_composite", 0)
            checked = "checked" if sn in current_concepts else ""
            dc_badge = f'{dc}篇 均分{ac:.0f}' if dc > 0 else '未命中'
            concept_rows += (
                f'<label class="flex items-center gap-2 px-2 py-1.5 hover:bg-indigo-50 rounded cursor-pointer text-xs">'
                f'<input type="checkbox" name="concept_{_esc(sn)}" value="{_esc(sn)}" {checked} class="rounded" />'
                f'<span class="font-medium text-gray-800">{_esc(sn)}</span>'
                f'<span class="text-gray-400">{dc_badge}</span>'
                f'</label>'
            )

    warning = ""
    if has_eco:
        warning = (
            '<div class="bg-amber-50 border border-amber-100 rounded-lg p-2 text-[10px] text-amber-700 mb-3">'
            '⚠️ 修改赛道或概念将清除现有生态位分析结果，需重新触发生成。</div>'
        )

    return f"""<div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
     id="board-edit-modal" onclick="if(event.target===this) this.remove()">
  <div class="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto p-5" onclick="event.stopPropagation()">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-base font-bold text-gray-900">⚙ 编辑板块配置</h3>
      <button type="button" class="text-gray-400 hover:text-gray-600 text-xl"
              onclick="this.closest('#board-edit-modal').remove()">×</button>
    </div>

    <form hx-post="/api/strategic/boards/{board['id']}/edit"
          hx-swap="none"
          class="space-y-4 text-sm">
      <input type="hidden" name="board_id" value="{board['id']}" />

      {warning}

      <!-- 板块名称 -->
      <div>
        <label class="block text-xs font-medium text-gray-700 mb-1">板块名称</label>
        <input name="board_title" type="text" required value="{_esc(board['name'])}"
               class="w-full border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none" />
      </div>

      <!-- 赛道选择 -->
      <div>
        <label class="block text-xs font-medium text-gray-700 mb-1">选择赛道</label>
        <select name="sector" required id="edit-sector-select"
                class="w-full border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none"
                hx-post="/api/strategic/genesis/concepts-json"
                hx-trigger="change"
                hx-target="#edit-concept-list"
                hx-swap="innerHTML">
          <option value="">-- 请选择赛道 --</option>
          {sector_opts}
        </select>
      </div>

      <!-- BOM 产业链节点选择 -->
      <div>
        <label class="block text-xs font-medium text-gray-700 mb-1">
          产业链 BOM 节点（可勾选）
          <span id="edit-bom-count" class="text-gray-400 font-normal ml-1">— 已选 {len(existing_bom_ids)} 个</span>
        </label>
        <p class="text-[10px] text-gray-400 mb-1">
          基于 AI 算力产业链经人工筛选与深度评估的 25 个关键节点。未勾选的节点将不被纳入分析。</p>
        <div id="edit-bom-list"
             class="bg-emerald-50 border border-emerald-200 rounded-lg p-2">
          {_render_bom_node_list(bom_nodes or existing_bom_nodes, selected_ids=existing_bom_ids)}
        </div>
      </div>

      <!-- 概念勾选 -->
      <div>
        <label class="block text-xs font-medium text-gray-700 mb-1">
          勾选 A 股概念板块
          <span class="text-gray-400 font-normal">（仅用于 policy_bond 加分）</span>
        </label>
        <div id="edit-concept-list"
             class="max-h-40 overflow-y-auto space-y-0.5 bg-white rounded-lg border border-gray-200 p-2">
          {concept_rows if concept_rows else '<p class="text-xs text-gray-400 py-2 text-center">请先选择赛道</p>'}
        </div>
      </div>

      <!-- 时间骨架 -->
      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="block text-xs font-medium mb-1">战略跨度（年）</label>
          <select name="horizon_years" class="w-full border rounded-lg px-3 py-2">
            <option value="5" {"selected" if board['horizon_end'] - board['horizon_start'] + 1 == 5 else ""}>5 年</option>
            <option value="10" {"selected" if board['horizon_end'] - board['horizon_start'] + 1 == 10 else ""} selected>10 年</option>
            <option value="15" {"selected" if board['horizon_end'] - board['horizon_start'] + 1 == 15 else ""}>15 年</option>
          </select>
        </div>
        <div>
          <label class="block text-xs font-medium mb-1">起始年</label>
          <input name="start_year" type="number" value="{board['horizon_start']}"
                 class="w-full border rounded-lg px-3 py-2" />
        </div>
      </div>

      <div class="flex gap-2 justify-end pt-2 border-t border-gray-100">
        <button type="button"
                class="text-sm px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                onclick="this.closest('#board-edit-modal').remove()">取消</button>
        <button type="submit"
                class="text-sm px-4 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition font-medium">
          保存修改</button>
      </div>
    </form>
  </div>
</div>
<script>
  // 模态框打开后：拦截 form submit，用 fetch 提交，HTML 回填替换
  document.addEventListener('DOMContentLoaded', function() {{
    const form = document.querySelector('#board-edit-modal form');
    if (form) {{
      form.addEventListener('htmx:beforeSend', function(evt) {{
        // 让 HTMX 正常 submit → 后端返回多个 hx-swap-oob 更新
      }});
    }}
  }});
</script>"""


def _render_concept_pools_result(board_id: int, stock_pool: dict[str, Any]) -> str:
    """v1.0 兼容渲染（旧 format 含 concept_pools 字段）。"""
    topo = stock_pool.get("ecosystem_topology", {})
    thesis = stock_pool.get("investment_thesis", "")
    pools = stock_pool.get("concept_pools", [])
    disclaimer = stock_pool.get("disclaimer", "")

    topo_rows = ""
    layers = [
        ("upstream", "🔺 上游", "原材料/核心技术/基础设施"),
        ("midstream", "⏺ 中游", "核心制造/平台/系统集成"),
        ("downstream", "🔻 下游", "终端产品/应用/服务"),
        ("service_layer", "⚙ 服务层", "配套服务/软件/数据/渠道"),
    ]
    for key, label, hint in layers:
        layer = topo.get(key, {})
        if not layer:
            continue
        role = layer.get("role", "")
        segments = layer.get("key_segments", [])
        seg_badges = "".join(
            f'<span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{_esc(s)}</span>'
            for s in segments
        ) if segments else ""
        topo_rows += (
            f"<div class='py-2 border-b border-gray-100 last:border-0'>"
            f"<span class='text-xs font-medium'>{label}</span>"
            f"<span class='text-[10px] text-gray-400 ml-1'>({hint})</span>"
            f"<p class='text-xs text-gray-600 mt-0.5'>{_esc(role)}</p>"
            + (f'<div class="flex flex-wrap gap-1 mt-1">{seg_badges}</div>' if seg_badges else '')
            + "</div>"
        )

    pool_html = ""
    for pool in pools:
        cn = pool.get("concept_name", "未知概念")
        rationale = pool.get("rationale", "")
        stocks = pool.get("stocks", [])
        layer_label = pool.get("ecosystem_layer", "")
        stock_rows = ""
        for st in stocks[:8]:
            sym = st.get("symbol", "??????")
            name = st.get("stock_name", "?")
            pos = st.get("ecosystem_position", "")
            gr = st.get("growth_rationale", "")
            conf = st.get("confidence", 0.5)
            conf_color = "text-emerald-600" if conf >= 0.8 else "text-amber-600" if conf >= 0.6 else "text-rose-500"
            stock_rows += (
                f"<tr class='text-xs border-b border-gray-50'>"
                f"<td class='py-1 pr-2 font-mono font-medium'>{_esc(sym)}</td>"
                f"<td class='py-1 pr-2'>{_esc(name)}</td>"
                f"<td class='py-1 pr-2 text-[10px] text-gray-500 max-w-[120px] truncate'>{_esc(pos)}</td>"
                f"<td class='py-1 pr-2 text-[10px] text-gray-600 max-w-[200px] truncate'>{_esc(gr)}</td>"
                f"<td class='py-1 text-[10px] {conf_color} font-medium'>{conf:.0%}</td>"
                f"</tr>"
            )
        pool_html += (
            f"<div class='mb-3 last:mb-0'>"
            f"<div class='flex flex-wrap items-center gap-2 mb-1'>"
            f"<span class='text-xs font-semibold text-gray-800'>{_esc(cn)}</span>"
            f"<span class='text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500'>{_esc(layer_label)}</span>"
            f"</div>"
            + (f'<p class="text-[10px] text-gray-500 mb-1">{_esc(rationale)}</p>' if rationale else '')
            + f"<table class='w-full'><thead><tr class='text-[10px] text-gray-400'>"
            + "<th class='text-left font-normal py-1'>代码</th><th class='text-left font-normal'>名称</th>"
            + "<th class='text-left font-normal'>生态位</th><th class='text-left font-normal'>成长逻辑</th><th class='text-right font-normal'>置信度</th>"
            + f"</tr></thead><tbody>{stock_rows}</tbody></table></div>"
        )

    refresh_btn = f"""<button type='button'
    class='text-[10px] px-2 py-1 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 mt-2'
    hx-post='/api/strategic/boards/{board_id}/ecosystem/infer'
    hx-target='#ecosystem-section' hx-swap='outerHTML'>🔄 重新分析</button>"""

    if not topo_rows:
        topo_rows = '<p class="text-xs text-gray-400 py-4 text-center">暂无生态位拓扑数据</p>'
    total_stocks = sum(len(p.get('stocks', [])) for p in pools)
    if not pool_html:
        pool_html = '<p class="text-xs text-gray-400 py-4 text-center">暂未生成标的池</p>'

    return f"""<div id='ecosystem-section' class='mt-6 border border-emerald-200 rounded-lg p-4 bg-emerald-50/30'>
  <div class='flex items-center justify-between mb-3'>
    <h3 class='text-sm font-semibold text-gray-800'>🔬 产业生态位分析 <span class='text-[10px] text-emerald-600 font-normal ml-1'>✓ 已完成</span></h3>
    {refresh_btn}
  </div>
  {f'<div class="bg-white border border-emerald-100 rounded-lg p-3 mb-3 text-xs text-gray-700">💡 {_esc(thesis)}</div>' if thesis else ''}
  <div class='grid grid-cols-1 md:grid-cols-2 gap-3 mb-3'>
    <div class='bg-white border rounded-lg p-3'>
      <p class='text-xs font-medium text-gray-700 mb-2'>🏗 产业生态位拓扑</p>
      {topo_rows}
    </div>
  </div>
  <div class='bg-white border rounded-lg p-3'>
    <p class='text-xs font-medium text-gray-700 mb-2'>📊 概念标的池 ({len(pools)} 个概念 · 共 {total_stocks} 只)</p>
    {pool_html}
  </div>
  {f'<p class="text-[10px] text-gray-400 italic mt-2">{_esc(disclaimer)}</p>' if disclaimer else ''}
</div>"""
