"""规划/执行工作区标的卡片 HTML。

[Ref: 24_行情解析与规划工作台_需求实现表.md]
[Ref: 32_五区漏斗工作流与数据工程标准化规约.md §1.4]
"""
from __future__ import annotations

import html as _html
from typing import Any, Callable, Optional

from apps.copilot.modules.planning.workspace_registry import workspace_list_label, workspace_tab_label

_PHASE_LABEL = {
    "concept":     ("炒概念",   "bg-sky-50 text-sky-700 border-sky-100"),
    "expectation": ("炒预期",   "bg-blue-50 text-blue-700 border-blue-100"),
    "realization": ("炒业绩",   "bg-amber-50 text-amber-800 border-amber-100"),
    "exhaustion":  ("利好出尽", "bg-gray-50 text-gray-600 border-gray-200"),
}


def _esc(v: Any) -> str:
    return _html.escape(str(v)) if v is not None else ""


def render_phase_chip(phase: str | None) -> str:
    if not phase:
        return (
            "<span class='text-[10px] px-1.5 py-0.5 rounded border border-gray-200 "
            "bg-gray-50 text-gray-400'>阶段 pending</span>"
        )
    label, cls = _PHASE_LABEL.get(phase, (phase, "bg-gray-50 text-gray-600 border-gray-200"))
    return f"<span class='text-[10px] px-1.5 py-0.5 rounded border {cls}'>{label}</span>"


def render_strategic_tag_summary_hint(tag: Optional[dict[str, Any]]) -> str:
    """折叠摘要行 · 只读战略归属提示。"""
    if not tag:
        return (
            "<span class='text-[11px] text-gray-400'>战略 · "
            "<span class='text-indigo-600'>未归属</span></span>"
        )
    board = _esc((tag.get("board_name") or "")[:10])
    phase = _esc((tag.get("phase_name") or "")[:12])
    return f"<span class='text-[11px] text-indigo-700'>🏷 {board} · {phase}</span>"


def wrap_workspace_tag_chip(symbol: str, chip_html: str) -> str:
    return f"<span id='workspace-tag-{_esc(symbol)}' class='inline-flex items-center'>{chip_html}</span>"


def wrap_workspace_tag_hint(symbol: str, hint_html: str) -> str:
    return f"<span id='workspace-tag-hint-{_esc(symbol)}'>{hint_html}</span>"


def render_strategic_tag_panel(
    symbol: str,
    tag: Optional[dict[str, Any]],
    *,
    render_strategic_chip: Callable[..., str],
) -> str:
    """展开区 · 战略归属（弹窗编辑）。"""
    sym = _esc(symbol)
    chip = wrap_workspace_tag_chip(symbol, render_strategic_chip(tag, symbol=symbol, editable=True))
    modal_btn = (
        f"<button type='button' class='text-[11px] px-2.5 py-1 rounded-md border border-indigo-200 "
        f"bg-indigo-50 text-indigo-700 hover:bg-indigo-100 font-medium' "
        f"hx-get='/api/strategic/tags/edit?symbol={sym}' "
        f"hx-target='#strategic-promote-modal-root' hx-swap='innerHTML'>"
        f"设置战略归属…</button>"
    )
    roadmap = ""
    if tag and tag.get("phase_id"):
        roadmap = (
            f"<a class='text-[11px] text-indigo-600 underline ml-auto' "
            f"href='/planning?view=roadmap&amp;board_id={tag.get('board_id')}"
            f"&amp;phase_id={tag.get('phase_id')}'>板块监控 →</a>"
        )
    return (
        f"<section class='bg-white border-b border-gray-200'>"
        f"{_section_title('① 战略归属', accent='indigo')}"
        f"<div class='px-4 py-3 flex flex-wrap items-center gap-2'>"
        f"{chip}{modal_btn}{roadmap}"
        f"<p class='text-[11px] text-gray-400 w-full mt-1 mb-0'>"
        f"弹窗选择板块 / 阶段 / 角色 · 与漏斗晋级独立</p></div></section>"
    )


def render_workspace_tag_oob(symbol: str, tag: Optional[dict[str, Any]]) -> str:
    """保存标签后 HTMX OOB 刷新 chip 与摘要。"""
    from apps.copilot.modules.strategic.render import render_strategic_chip

    sym = _esc(symbol)
    chip = render_strategic_chip(tag, symbol=symbol, editable=True)
    hint = render_strategic_tag_summary_hint(tag)
    return (
        f"<span id='workspace-tag-{sym}' hx-swap-oob='true' class='inline-flex items-center'>"
        f"{chip}</span>"
        f"<span id='workspace-tag-hint-{sym}' hx-swap-oob='true'>{hint}</span>"
    )


def render_promote_executing_form(
    campaign_id: int,
    symbol: str,
    *,
    compact: bool = False,
) -> str:
    """晋级执行表单：待建仓/已建仓 · 战略归属请用弹窗单独设置。"""
    sym = _esc(symbol)
    cid = int(campaign_id)
    holding_fields = f"""
    <div class="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs holding-promote-fields" data-symbol="{sym}">
      <label class="flex flex-col gap-0.5 text-gray-600">建仓日
        <input name="opened_at" type="date" class="border border-gray-200 rounded px-1.5 py-1">
      </label>
      <label class="flex flex-col gap-0.5 text-gray-600">成本价
        <input name="cost_price" type="number" step="0.0001" min="0" class="border border-gray-200 rounded px-1.5 py-1">
      </label>
      <label class="flex flex-col gap-0.5 text-gray-600">股数
        <input name="quantity" type="number" step="any" min="0" class="border border-gray-200 rounded px-1.5 py-1">
      </label>
      <label class="flex flex-col gap-0.5 text-gray-600">仓位%
        <input name="position_pct" type="number" step="0.01" min="0" max="100" class="border border-gray-200 rounded px-1.5 py-1">
      </label>
    </div>
    """
    mode_row = f"""
    <div class="flex flex-wrap items-center gap-3 text-xs text-gray-600 mt-2">
      <span class="font-medium text-gray-700">晋级为</span>
      <label class="inline-flex items-center gap-1 cursor-pointer">
        <input type="radio" name="lifecycle_mode" value="pending_build" checked class="accent-blue-600">
        待建仓
      </label>
      <label class="inline-flex items-center gap-1 cursor-pointer">
        <input type="radio" name="lifecycle_mode" value="holding" class="accent-blue-600">
        已建仓
      </label>
    </div>
    {holding_fields}
    """
    btn_cls = (
        "text-sm px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 font-medium"
        if compact
        else "px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700"
    )
    btn_label = "人工确认 · 晋级执行" if compact else f"人工确认 · 晋级执行（{sym}）"
    return (
        f"<form hx-post='/api/campaigns/{cid}/promote-executing' "
        f"hx-swap='none' class='promote-executing-form' data-symbol='{sym}'>"
        f"<input type='hidden' name='human_confirmed' value='true'>"
        f"<input type='hidden' name='symbol' value='{sym}'>"
        f"{mode_row}"
        f"<div class='mt-3 flex flex-wrap items-center gap-2'>"
        f"<button type='submit' class='{btn_cls}'>{btn_label}</button>"
        f"<span class='text-[11px] text-gray-400'>须人工确认 · advisory only</span>"
        f"</div></form>"
    )


def _summary_chevron() -> str:
    return (
        "<span class='workspace-card-chevron text-gray-400 text-xs shrink-0 "
        "group-open:rotate-90 transition-transform duration-150'>▸</span>"
    )


def _section_title(label: str, *, accent: str = "gray") -> str:
    borders = {
        "blue": "border-blue-200 text-blue-800 bg-blue-50/50",
        "indigo": "border-indigo-200 text-indigo-800 bg-indigo-50/50",
        "emerald": "border-emerald-200 text-emerald-800 bg-emerald-50/50",
        "gray": "border-gray-200 text-gray-700 bg-gray-50/80",
    }
    cls = borders.get(accent, borders["gray"])
    return (
        f"<div class='text-[11px] font-semibold uppercase tracking-wide px-3 py-1.5 "
        f"border-b {cls}'>{label}</div>"
    )


def _t2_summary_line(advice: dict[str, Any] | None) -> str:
    if not advice:
        return "<span class='text-[11px] text-gray-400'>T2 · 待分析</span>"
    action = _esc(advice.get("action_label") or advice.get("action") or "—")
    summary = _esc((advice.get("summary") or advice.get("core_eval") or "")[:48])
    pinned = (advice.get("source") or "") == "pinned" or advice.get("pinned")
    pin = " 📌" if pinned else ""
    return (
        f"<span class='text-[11px] text-indigo-700 truncate max-w-[14rem] inline-block' "
        f"title='T2 摘要'>T2 · <strong>{action}</strong>{pin} · {summary or '—'}</span>"
    )


def render_planning_symbol_card(
    s: dict[str, Any],
    *,
    container_id: int,
    tags_map: dict,
    render_strategic_chip: Callable[..., str],
) -> str:
    sym = s.get("symbol", "")
    name = _esc(s.get("name", sym))
    sym_esc = _esc(sym)
    tag = tags_map.get(sym)
    phase = render_phase_chip(s.get("market_phase"))
    tag_hint = wrap_workspace_tag_hint(sym, render_strategic_tag_summary_hint(tag))
    tag_panel = render_strategic_tag_panel(sym, tag, render_strategic_chip=render_strategic_chip)
    promote = render_promote_executing_form(container_id, sym, compact=True)
    return (
        f"<div class='planning-symbol-card-wrap workspace-symbol-card-wrap' data-symbol='{sym_esc}'>"
        f"<details class='planning-symbol-card workspace-symbol-card group bg-white border border-gray-200 "
        f"rounded-xl shadow-sm overflow-hidden'>"
        f"<summary class='workspace-card-summary cursor-pointer list-none px-4 py-3 hover:bg-gray-50/80 "
        f"[&::-webkit-details-marker]:hidden'>"
        f"<div class='flex items-start gap-2'>"
        f"{_summary_chevron()}"
        f"<div class='flex-1 min-w-0'>"
        f"<div class='flex flex-wrap items-center gap-x-2 gap-y-1'>"
        f"<span class='font-semibold text-gray-900'>{name}</span>"
        f"<span class='text-gray-400 text-xs font-mono'>{sym_esc}</span>"
        f"<span class='text-[10px] px-1.5 py-0.5 rounded border border-indigo-200 "
        f"bg-indigo-50 text-indigo-700 font-medium'>{_esc(workspace_tab_label('planning'))}</span>"
        f"</div>"
        f"<div class='flex flex-wrap items-center gap-2 mt-1.5'>{phase}{tag_hint}</div>"
        f"<p class='text-[11px] text-gray-400 mt-1'>展开 · 战略归属 · 晋级 · 证伪 · 沙盒</p>"
        f"</div></div></summary>"
        f"<div class='workspace-card-body border-t border-gray-200 bg-gray-50/40'>"
        f"{tag_panel}"
        f"<section class='bg-white border-b border-gray-200'>"
        f"{_section_title('② 晋级执行', accent='blue')}"
        f"<div class='p-4'>{promote}</div></section>"
        f"<details class='planning-sub-panel border-b border-gray-200 bg-white'>"
        f"<summary class='cursor-pointer list-none px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 "
        f"flex items-center gap-2 [&::-webkit-details-marker]:hidden'>"
        f"<span class='text-gray-400 text-xs group-open/sub:rotate-90'>▸</span>"
        f"<span class='font-medium'>③ 证伪监控</span>"
        f"<span class='text-[11px] text-gray-400 ml-auto'>按需加载</span></summary>"
        f"<div class='px-4 pb-4 pt-1 border-t border-gray-100'>"
        f"<div id='panel-{sym_esc}' class='planning-falsify-slot' "
        f"hx-get='/api/campaigns/{container_id}/planning-panel?symbol={sym_esc}' "
        f"hx-trigger='revealed once' hx-swap='innerHTML'>"
        f"<p class='text-xs text-gray-400 py-2'>展开后加载证伪面板…</p></div></div></details>"
        f"<details class='planning-sub-panel border-b border-gray-200 bg-white'>"
        f"<summary class='cursor-pointer list-none px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 "
        f"flex items-center gap-2 [&::-webkit-details-marker]:hidden'>"
        f"<span class='text-gray-400 text-xs'>▸</span>"
        f"<span class='font-medium'>④ Context-Aware Sandbox</span>"
        f"<span class='text-[11px] text-gray-400 ml-auto'>按需加载</span></summary>"
        f"<div class='px-4 pb-4 pt-1 border-t border-gray-100'>"
        f"<div id='sandbox-{sym_esc}' "
        f"hx-get='/api/planning/sandbox/{sym_esc}' "
        f"hx-trigger='revealed once' hx-swap='innerHTML'>"
        f"<p class='text-xs text-gray-400 py-2'>展开后加载沙盒…</p></div></div></details>"
        f"<div class='px-4 py-2.5 flex flex-wrap items-center gap-2 bg-white text-xs'>"
        f"<a href='/api/campaigns/{container_id}/symbols/{sym_esc}' "
        f"class='text-gray-500 hover:text-blue-600 hover:underline'>6 维档案</a>"
        f"<span class='text-gray-300'>|</span>"
        f"<form hx-post='/api/funnel/symbols/{sym_esc}/demote' hx-swap='none' class='inline'>"
        f"<button type='submit' class='text-amber-700 hover:underline'>降级到候选</button></form>"
        f"<form hx-post='/api/funnel/symbols/{sym_esc}/remove' hx-swap='none' class='inline ml-auto'>"
        f"<button type='submit' class='text-gray-500 hover:underline'>移除</button></form>"
        f"</div></div></details></div>"
    )


def render_executing_symbol_card(
    s: dict[str, Any],
    *,
    container_id: int,
    t2_summaries: dict,
    tags_map: dict,
    render_strategic_chip: Callable[..., str],
    render_executing_t2_banner: Callable[..., str],
) -> str:
    from apps.copilot.modules.executing.position_lifecycle import (
        LIFECYCLE_HOLDING,
        resolve_lifecycle_status,
    )

    sym = s.get("symbol", "")
    name = _esc(s.get("name", sym))
    sym_esc = _esc(sym)
    tag = tags_map.get(sym)
    phase = render_phase_chip(s.get("market_phase"))
    tag_hint = wrap_workspace_tag_hint(sym, render_strategic_tag_summary_hint(tag))
    tag_panel = render_strategic_tag_panel(sym, tag, render_strategic_chip=render_strategic_chip)
    pct = s.get("position_pct")
    opened = s.get("opened_at") or "—"
    if opened and "T" in str(opened):
        opened = str(opened)[:10]
    qty = s.get("quantity")
    cost = s.get("cost_price")
    lifecycle = resolve_lifecycle_status(
        {"opened_at": s.get("opened_at"), "cost_price": cost, "quantity": qty}
    )
    lifecycle_chip = (
        "<span class='text-[10px] px-1.5 py-0.5 rounded border border-emerald-200 "
        "bg-emerald-50 text-emerald-700 font-medium'>持仓中</span>"
        if lifecycle == LIFECYCLE_HOLDING
        else "<span class='text-[10px] px-1.5 py-0.5 rounded border border-sky-200 "
        "bg-sky-50 text-sky-700 font-medium'>待建仓</span>"
    )
    pct_txt = f"{pct:.1f}%" if isinstance(pct, (int, float)) else "—"
    metrics = (
        f"<span class='text-[11px] text-gray-500 font-mono'>"
        f"仓位 {pct_txt} · 股 {qty or '—'} · 成本 {cost or '—'} · 建仓 {opened}</span>"
    )
    advice = t2_summaries.get(sym)
    t2_line = _t2_summary_line(advice)
    t2_banner = render_executing_t2_banner(sym, advice, embedded=True)
    return (
        f"<div class='executing-symbol-card-wrap workspace-symbol-card-wrap mb-3' data-symbol='{sym_esc}'>"
        f"<details class='executing-symbol-card workspace-symbol-card group bg-white border border-gray-200 "
        f"rounded-xl shadow-sm overflow-hidden' data-symbol='{sym_esc}'>"
        f"<summary class='workspace-card-summary cursor-pointer list-none px-4 py-3 hover:bg-gray-50/80 "
        f"[&::-webkit-details-marker]:hidden'>"
        f"<div class='flex items-start gap-2'>"
        f"{_summary_chevron()}"
        f"<div class='flex-1 min-w-0 space-y-1.5'>"
        f"<div class='flex flex-wrap items-center gap-x-2 gap-y-1'>"
        f"<span class='font-semibold text-gray-900'>{name}</span>"
        f"<span class='text-gray-400 text-xs font-mono'>{sym_esc}</span>"
        f"{lifecycle_chip}"
        f"</div>"
        f"<div class='flex flex-wrap items-center gap-2'>{phase}{tag_hint}</div>"
        f"<div class='flex flex-wrap items-center gap-2'>{metrics}{t2_line}</div>"
        f"</div></div></summary>"
        f"<div class='workspace-card-body border-t border-gray-200'>"
        f"{tag_panel}"
        f"<details class='executing-t2-panel group/t2 border-b border-gray-200 bg-white'>"
        f"<summary class='executing-fold-summary cursor-pointer list-none block select-none px-4 py-2.5 flex items-center justify-between gap-2 "
        f"hover:bg-indigo-50/50 [&::-webkit-details-marker]:hidden' "
        f"onclick='event.stopPropagation()' onmousedown='event.stopPropagation()'>"
        f"<span class='text-sm font-semibold text-indigo-900'>② T2 持仓分析</span>"
        f"<span class='text-[10px] text-gray-400 shrink-0 group-open/t2:hidden'>展开 ▾</span>"
        f"<span class='text-[10px] text-gray-400 shrink-0 hidden group-open/t2:inline'>收起 ▴</span>"
        f"</summary>"
        f"<div class='border-t border-gray-100'>{t2_banner}</div></details>"
        f"<section class='bg-gray-50/60 border-b border-gray-200'>"
        f"{_section_title('③ 操作', accent='gray')}"
        f"<div class='px-4 py-3 flex flex-wrap gap-2 items-center'>"
        f"<form hx-post='/api/campaigns/{container_id}/execution/advise' "
        f"hx-target='#exec-{sym_esc}' hx-swap='innerHTML' class='inline'>"
        f"<input type='hidden' name='symbol' value='{sym_esc}'>"
        f"<button type='submit' class='text-sm px-3 py-1.5 rounded-lg bg-blue-600 text-white "
        f"hover:bg-blue-700 font-medium'>生成仓位建议</button></form>"
        f"<form hx-post='/api/campaigns/{container_id}/archive' hx-swap='none' class='inline'>"
        f"<input type='hidden' name='symbol' value='{sym_esc}'>"
        f"<button type='submit' class='text-sm px-3 py-1.5 rounded-lg border border-gray-300 "
        f"bg-white text-gray-700 hover:bg-gray-50'>本波归档</button></form>"
        f"<form hx-post='/api/funnel/symbols/{sym_esc}/demote' hx-swap='none' class='inline'>"
        f"<button type='submit' class='text-xs px-2 py-1 rounded border border-amber-200 "
        f"text-amber-800 bg-white'>降级到规划</button></form>"
        f"<form hx-post='/api/funnel/symbols/{sym_esc}/remove' hx-swap='none' class='inline ml-auto'>"
        f"<button type='submit' class='text-xs text-gray-500 hover:underline'>移除</button></form>"
        f"</div></section>"
        f"<div id='exec-{sym_esc}' class='px-4'></div>"
        f"<section class='px-4 pb-4 border-t border-gray-100'>"
        f"{_section_title('④ JL 指标监控', accent='emerald')}"
        f"<div class='pt-2'>"
        f"<div id='executing-detail-{sym_esc}' "
        f"data-detail-url='/api/executing/{sym_esc}/detail' "
        f"class='executing-detail-slot' data-symbol='{sym_esc}'>"
        f"<div id='executing-detail-body-{sym_esc}' class='executing-detail-body' "
        f"data-detail-state='loading' data-symbol='{sym_esc}'>"
        f"<p class='text-xs text-gray-400 py-4 flex items-center gap-2'>"
        f"<svg class='animate-spin h-3.5 w-3.5' fill='none' viewBox='0 0 24 24'>"
        f"<circle class='opacity-25' cx='12' cy='12' r='10' stroke='currentColor' "
        f"stroke-width='4'></circle>"
        f"<path class='opacity-75' fill='currentColor' "
        f"d='M4 12a8 8 0 018-8v8H4z'></path></svg>"
        f"加载 JL 指标与持仓面板…</p></div></div></div></section></div></details></div>"
    )


def render_workspace_symbol_list(
    cards: list[str],
    *,
    view: str,
    count: int,
) -> str:
    label = workspace_list_label(view)
    count_cls = (
        "text-indigo-700"
        if view == "planning"
        else "text-emerald-700"
        if view == "executing"
        else "text-violet-700"
    )
    header = (
        f"<div class='flex items-center justify-between gap-2 mb-3 px-1'>"
        f"<span class='text-xs font-medium {count_cls}'>{label} · {count} 只标的</span>"
        f"<span class='text-[11px] text-gray-400'>点击卡片展开 · 默认折叠</span></div>"
    )
    body = "".join(cards)
    return f"<div class='workspace-symbol-list space-y-0' onclick='event.stopPropagation()'>{header}{body}</div>"


def render_archived_symbol_card(s: dict[str, Any]) -> str:
    sym = s.get("symbol", "")
    name = _esc(s.get("name", sym))
    sym_esc = _esc(sym)
    return (
        f"<div class='archived-symbol-card border border-gray-200 rounded-xl bg-white px-4 py-3 mb-2 "
        f"flex flex-wrap items-center justify-between gap-2'>"
        f"<div>"
        f"<span class='font-semibold text-gray-900'>{name}</span>"
        f"<span class='text-gray-400 text-xs font-mono ml-2'>{sym_esc}</span>"
        f"<span class='text-[10px] ml-2 px-1.5 py-0.5 rounded border border-violet-200 "
        f"bg-violet-50 text-violet-700'>已归档</span>"
        f"</div>"
        f"<form hx-post='/api/funnel/symbols/{sym_esc}/demote' hx-swap='none' class='inline'>"
        f"<button type='submit' class='text-xs text-indigo-600 hover:underline'>"
        f"恢复到持仓监护</button></form>"
        f"</div>"
    )


def render_archived_symbol_list(symbols: list[dict[str, Any]]) -> str:
    if not symbols:
        return (
            "<p class='text-sm text-gray-500 py-6 text-center'>"
            "暂无归档标的 · 执行波次完成后可从路线图归档，或在本波结束时标记归档</p>"
        )
    cards = [render_archived_symbol_card(s) for s in symbols]
    header = (
        f"<div class='flex items-center justify-between gap-2 mb-3 px-1'>"
        f"<span class='text-xs font-medium text-violet-700'>"
        f"{workspace_list_label('ledger')} · {len(symbols)} 只标的</span>"
        f"<span class='text-[11px] text-gray-400'>归档后可在此复盘 · 可恢复至监护</span></div>"
    )
    return f"<div class='archived-symbol-list'>{header}{''.join(cards)}</div>"
