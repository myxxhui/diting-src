"""战略板块 HTML 渲染。

[Ref: 30_ §4 · §8]
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


def render_board_list(
    boards: list[dict[str, Any]],
    *,
    selected_id: Optional[int] = None,
) -> str:
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

    rows: list[str] = []
    for b in boards:
        bid = b["id"]
        sel = bid == selected_id
        border, bar, bg, text = board_color_classes(b.get("color_token") or "indigo")
        sel_cls = f"border-l-4 {border} {bg}" if sel else "border-l-4 border-transparent hover:bg-gray-50"
        rows.append(
            f"<div role='button' tabindex='0' "
            f"class='block px-3 py-3 cursor-pointer {sel_cls} strategic-board-item' "
            f"data-board-id='{bid}' "
            f"hx-get='/api/strategic/command-center?board_id={bid}' "
            f"hx-target='#strategic-command-main' hx-swap='innerHTML' "
            f"hx-push-url='/planning?view=roadmap&board_id={bid}'>"
            f"<div class='font-semibold text-gray-900 text-sm leading-snug'>{_esc(b['name'])}</div>"
            f"<div class='text-xs text-gray-500 mt-0.5'>"
            f"{b['horizon_start']}–{b['horizon_end']}</div>"
            f"<div class='text-xs text-gray-600 mt-1 truncate'>"
            f"▶ {_esc(b.get('active_phase_name') or '—')}</div>"
            f"<div class='mt-1'>{render_alert_badges(b.get('alerts') or {})}</div>"
            f"</div>"
        )
    return "".join(rows)


def render_strategic_timeline(board: dict[str, Any], *, selected_phase_id: Optional[int] = None) -> str:
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
        f"<h4 class='text-xs font-semibold text-gray-700 mb-1'>JL1 宏观</h4>"
        f"{probe_rows(jl1)}"
        f"<h4 class='text-xs font-semibold text-gray-700 mt-3 mb-1'>JL2 行业</h4>"
        f"{probe_rows(jl2)}"
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
        f"<button type='submit' class='mt-2 text-xs px-3 py-1.5 rounded-lg bg-gray-800 text-white'>"
        f"保存复盘</button>"
        f"<div id='strategic-review-toast-{phase['id']}' class='mt-1'></div>"
        f"</form>"
        f"</div>"
    )


def render_command_center_main(
    board: Optional[dict[str, Any]],
    *,
    selected_phase_id: Optional[int] = None,
) -> str:
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
    return (
        f"<div>"
        f"<div class='flex flex-wrap items-center justify-between gap-2 mb-3'>"
        f"<h2 class='text-base font-bold text-gray-900'>{_esc(board['name'])}</h2>"
        f"<span class='text-xs text-gray-500'>{board['horizon_start']}–{board['horizon_end']}</span>"
        f"</div>"
        f"{qualitative}"
        f"{render_strategic_timeline(board, selected_phase_id=selected_phase_id)}"
        f"</div>"
    )


def render_strategic_chip(
    tag: Optional[dict[str, Any]],
    *,
    symbol: str,
    editable: bool = False,
) -> str:
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


def render_strategic_context_bar(
    tag: Optional[dict[str, Any]],
    jl_summary: str,
) -> str:
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


def _render_board_phase_selects(
    options: list[dict[str, Any]],
    suggested: Optional[dict[str, Any]],
    *,
    field_prefix: str = "",
) -> str:
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


def render_promote_modal_radar(
    *,
    candidate_id: int,
    symbol: str,
    name: str,
    options: list[dict[str, Any]],
    suggested: Optional[dict[str, Any]],
) -> str:
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


def render_tag_edit_modal(
    *,
    symbol: str,
    name: str,
    options: list[dict[str, Any]],
    current: Optional[dict[str, Any]],
) -> str:
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


def render_strategic_overview_drawer(boards: list[dict[str, Any]]) -> str:
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
