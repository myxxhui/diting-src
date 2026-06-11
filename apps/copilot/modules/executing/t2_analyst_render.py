"""T2 持仓分析 · 对话区结构化 HTML 渲染。

[Ref: 28_ §5]
"""
from __future__ import annotations

import html
import json
import re
from typing import Any

from apps.copilot.modules.executing.t2_advice_summary import structured_audit_from_payload
from apps.copilot.modules.radar.schema import DIM_META, MARKET_PHASE_LABELS


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


_ACTION_LABELS: dict[str, str] = {
    "hold": "持有",
    "trim": "减持",
    "trim_30_pct": "减持 30%",
    "dump": "清仓",
    "dump_all": "全部清仓",
    "rotate": "换股",
    "watch": "观察",
}

_ACTION_BADGE: dict[str, str] = {
    "hold": "bg-emerald-100 text-emerald-800",
    "trim": "bg-amber-100 text-amber-800",
    "trim_30_pct": "bg-amber-100 text-amber-800",
    "dump": "bg-rose-100 text-rose-800",
    "dump_all": "bg-rose-100 text-rose-800",
    "rotate": "bg-indigo-100 text-indigo-800",
    "watch": "bg-slate-100 text-slate-700",
}


def _action_label(code: str | None) -> str:
    c = (code or "").strip().lower()
    return _ACTION_LABELS.get(c, c or "—")


def _action_badge(code: str | None) -> str:
    c = (code or "").strip().lower()
    return _ACTION_BADGE.get(c, "bg-gray-100 text-gray-700")


def _dim_display(key: str) -> str:
    meta = DIM_META.get(key) or {}
    emoji = meta.get("emoji") or ""
    label = meta.get("label") or key
    return f"{emoji} {label}".strip()


def _para(text: str | None, *, label: str = "", cls: str = "text-xs text-gray-700 leading-relaxed") -> str:
    t = (text or "").strip()
    if not t:
        return ""
    lbl = f"<span class='text-gray-400'>{_esc(label)}</span>" if label else ""
    return f"<p class='{cls} mt-1.5'>{lbl}{_esc(t)}</p>"


def _t1_context(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    t1: dict[str, Any] = {}
    env = payload.get("envelope") or {}
    t1 = (env.get("user_payload") or {}).get("t1") or env.get("t1") or {}
    if not t1:
        try:
            msgs = payload.get("opus_messages") or []
            if len(msgs) > 1:
                body = json.loads(msgs[1].get("content") or "{}")
                t1 = body.get("t1") or {}
        except (json.JSONDecodeError, TypeError):
            pass
    out: dict[str, dict[str, Any]] = {}
    for sym, sig in (t1.get("portfolio_signals") or {}).items():
        pos = sig.get("position_context") or {}
        out[sym] = {
            "name": sig.get("stock_name") or sym,
            "position_pct": pos.get("position_pct"),
            "current_price": pos.get("current_price"),
            "holding_volume": pos.get("holding_volume"),
            "unrealized_profit_pct": pos.get("unrealized_profit_pct"),
        }
    return out


def _pnl_badge(pnl: str | None) -> str:
    """T1 持仓浮盈/浮亏徽章（组合区权威口径，非 Opus 口述）。"""
    if not pnl:
        return "<span class='text-[10px] text-gray-400'>浮盈/浮亏 —</span>"
    raw = str(pnl).strip()
    neg = raw.startswith("-")
    cls = "text-rose-700 bg-rose-50" if neg else "text-emerald-700 bg-emerald-50"
    label = "浮亏" if neg else "浮盈"
    return (
        f"<span class='text-[10px] font-medium px-1.5 py-0.5 rounded {cls}'>"
        f"T1 {label} {_esc(raw)}</span>"
    )


def _split_prose_by_symbol_names(
    text: str | None, ctx_map: dict[str, dict[str, Any]]
) -> list[tuple[str, str, str]]:
    """按标的简称切分 L3/L4 长段落 → [(symbol, name, segment_text)]。"""
    t = (text or "").strip()
    if not t or not ctx_map:
        return []

    names: list[tuple[str, str, str]] = []
    for sym, ctx in ctx_map.items():
        name = (ctx.get("name") or "").strip()
        if name:
            names.append((name, sym, name))
        code = sym.split(".")[0] if "." in sym else sym[-6:]
        if code:
            names.append((code, sym, name or sym))
    names.sort(key=lambda x: len(x[0]), reverse=True)

    hits: list[tuple[int, str, str, str]] = []
    for alias, sym, display_name in names:
        for sep in ("：", ":"):
            needle = f"{alias}{sep}"
            pos = t.find(needle)
            if pos >= 0:
                hits.append((pos, sym, display_name or alias, needle))
                break

    if not hits:
        return []

    hits.sort(key=lambda x: x[0])
    # 去重：同一位置只保留最长别名
    deduped: list[tuple[int, str, str, str]] = []
    seen_pos: set[int] = set()
    for pos, sym, dname, needle in hits:
        if pos in seen_pos:
            continue
        seen_pos.add(pos)
        deduped.append((pos, sym, dname, needle))

    segments: list[tuple[str, str, str]] = []
    for i, (pos, sym, dname, _needle) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(t)
        chunk = t[pos:end].strip()
        # 去掉 leading "英维克：" 前缀，正文已含标题感
        chunk = re.sub(rf"^{re.escape(dname)}[：:]\s*", "", chunk)
        chunk = re.sub(rf"^{re.escape(sym.split('.')[0])}[：:]\s*", "", chunk)
        if chunk:
            segments.append((sym, dname, chunk))
    return segments


def _render_verdict_by_symbol(
    text: str | None,
    *,
    label: str,
    ctx_map: dict[str, dict[str, Any]],
) -> str:
    """L3/L4 按标的分段展示，并标注 T1 浮盈/浮亏（避免组合段误读）。"""
    t = (text or "").strip()
    if not t:
        return ""

    segments = _split_prose_by_symbol_names(t, ctx_map)
    if not segments:
        if not t:
            return ""
        return (
            f"<section class='t2-reply-section'>"
            f"<h4 class='t2-reply-section-title'>{_esc(label)}</h4>"
            f"<p class='t2-reply-section-body'>{_esc(t)}</p></section>"
        )

    blocks: list[str] = []
    for sym, dname, chunk in segments:
        ctx = ctx_map.get(sym, {})
        title = f"{_esc(dname)} · {_esc(sym)}"
        blocks.append(
            f"<div class='t2-segment'>"
            f"<div class='t2-segment-head'>"
            f"<span class='t2-segment-title'>{title}</span>"
            f"{_pnl_badge(ctx.get('unrealized_profit_pct'))}"
            f"</div>"
            f"<p class='t2-segment-body'>{_esc(chunk)}</p>"
            f"</div>"
        )

    return (
        f"<section class='t2-reply-section'>"
        f"<h4 class='t2-reply-section-title'>{_esc(label)}</h4>"
        f"<p class='t2-segment-hint'>按标的分段 · 浮盈/浮亏以 T1 为准</p>"
        f"<div class='t2-segment-group'>{''.join(blocks)}</div>"
        f"</section>"
    )


def _ordered_symbols(payload: dict[str, Any], audits: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for s in payload.get("symbols") or []:
        key = s if "." in str(s) else f"{str(s).zfill(6)[-6:]}"
        for candidate in (s, f"{str(s).zfill(6)[-6:]}.SH", f"{str(s).zfill(6)[-6:]}.SZ"):
            if candidate in audits and candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
                break
    for sym in audits:
        if sym not in seen:
            ordered.append(sym)
    return ordered


def _target_map(cmd: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t in cmd.get("targets") or []:
        if isinstance(t, dict) and t.get("symbol"):
            out[str(t["symbol"])] = t
    return out


_JL_STATUS_BADGE: dict[str, str] = {
    "filled": "bg-emerald-100 text-emerald-800",
    "partial": "bg-amber-100 text-amber-800",
    "empty": "bg-gray-100 text-gray-500",
}

_JL_STATUS_LABEL: dict[str, str] = {
    "filled": "有数据",
    "partial": "部分推断",
    "empty": "无数据",
}


def _render_jl_checklist_layer(
    items: list[dict[str, Any]],
    *,
    layer: str,
    id_key: str = "topic_id",
) -> str:
    """渲染 JL1/JL2/JL3 checklist 填空（empty 也展示）。"""
    if not items:
        return (
            f"<p class='text-[11px] text-gray-400'>{_esc(layer)}：无 checklist 题</p>"
        )
    rows: list[str] = []
    for item in items:
        status = (item.get("status") or "empty").strip().lower()
        badge_cls = _JL_STATUS_BADGE.get(status, _JL_STATUS_BADGE["empty"])
        badge_lbl = _JL_STATUS_LABEL.get(status, status)
        key = item.get(id_key) or item.get("key") or item.get("topic_id") or "—"
        ans = (item.get("answer") or "").strip()
        body = _esc(ans) if ans else "（无数据）"
        rows.append(
            f"<div class='rounded border border-gray-100 bg-white/80 px-2 py-1.5'>"
            f"<div class='flex flex-wrap items-center gap-2 mb-0.5'>"
            f"<span class='text-[10px] font-mono text-gray-500'>{_esc(key)}</span>"
            f"<span class='text-[10px] px-1.5 py-0.5 rounded {badge_cls}'>{_esc(badge_lbl)}</span>"
            f"</div>"
            f"<p class='text-[11px] text-gray-700 leading-relaxed'>{body}</p>"
            f"</div>"
        )
    return (
        f"<div class='space-y-1'>"
        f"<p class='text-[11px] font-medium text-gray-500'>{_esc(layer)}</p>"
        f"{''.join(rows)}"
        f"</div>"
    )


def _jl4_summary(jl4_read: list[dict[str, Any]], limit: int = 4) -> str:
    lines: list[str] = []
    for item in jl4_read or []:
        reading = (item.get("reading") or "").strip()
        if not reading:
            continue
        key = item.get("key") or "—"
        lines.append(f"· {_esc(key)}：{_esc(reading[:200])}")
        if len(lines) >= limit:
            break
    if not lines:
        return "<p class='text-[11px] text-gray-400'>暂无 JL4 解读</p>"
    return "<div class='text-[11px] text-gray-600 space-y-0.5'>" + "".join(
        f"<p>{ln}</p>" for ln in lines
    ) + "</div>"


def _conf_bar(conf: Any) -> str:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        c = 0.0
    pct = max(0, min(100, int(c * 100)))
    return (
        f"<span class='t2-conf-bar' aria-hidden='true'>"
        f"<span class='t2-conf-fill' style='width:{pct}%'></span></span>"
        f"<span class='t2-conf-pct'>{pct}%</span>"
    )


def _render_target_chips(cmd: dict[str, Any]) -> str:
    """逐标的操作建议 · 横向芯片摘要。"""
    chips: list[str] = []
    for t in cmd.get("targets") or []:
        if not isinstance(t, dict) or not t.get("symbol"):
            continue
        sym = str(t["symbol"])
        advice = str(t.get("advice") or "")
        pct = (t.get("pct_change") or "").strip()
        rat = (t.get("rationale") or "").strip()
        badge_cls = _action_badge(advice)
        pct_s = f"<span class='t2-target-pct'>{_esc(pct)}</span>" if pct else ""
        rat_s = (
            f"<p class='t2-target-rat'>{_esc(rat)}</p>" if rat else ""
        )
        chips.append(
            f"<div class='t2-target-chip'>"
            f"<div class='t2-target-chip-head'>"
            f"<span class='t2-target-sym'>{_esc(sym)}</span>"
            f"<span class='t2-target-badge {_esc(badge_cls)}'>"
            f"{_esc(_action_label(advice))}</span>{pct_s}</div>{rat_s}</div>"
        )
    if not chips:
        return ""
    return f"<div class='t2-target-chips'>{''.join(chips)}</div>"


def _render_radar_nine_dimensions_block(radar: dict[str, Any] | None) -> str:
    """渲染 symbol_audits.radar_nine_dimensions（与雷达九维卡片同构）。"""
    if not isinstance(radar, dict) or not radar:
        return ""
    dims = radar.get("dimensions") or {}
    if not isinstance(dims, dict) or not dims:
        return ""
    overall = radar.get("overall") or {}
    cards: list[str] = []
    for key, dim in dims.items():
        if not isinstance(dim, dict):
            continue
        verdict = (dim.get("verdict") or "—").strip() or "—"
        if key == "market_phase" and verdict in MARKET_PHASE_LABELS:
            verdict = f"{MARKET_PHASE_LABELS[verdict]}（{verdict}）"
        reasoning = (dim.get("reasoning") or "").strip()
        cards.append(
            f"<details class='t2-nine-dim-card'>"
            f"<summary class='t2-nine-dim-summary'>"
            f"<span class='t2-nine-dim-label'>{_esc(_dim_display(key))}</span>"
            f"<span class='t2-nine-dim-verdict'>{_esc(verdict)}</span>"
            f"{_conf_bar(dim.get('confidence'))}</summary>"
            f"<div class='t2-nine-dim-body'>{_esc(reasoning) or '—'}</div>"
            f"</details>"
        )
    if not cards:
        return ""
    head = (overall.get("conclusion") or "").strip()
    head_html = (
        f"<p class='t2-nine-dim-overall'>{_esc(head)}</p>" if head else ""
    )
    return (
        f"<div class='t2-nine-dim-block'>"
        f"<p class='t2-nine-dim-title'>雷达九维研报</p>"
        f"{head_html}"
        f"<div class='t2-nine-dim-grid'>{''.join(cards)}</div>"
        f"</div>"
    )


def _render_symbol_section(
    symbol: str,
    audit: dict[str, Any],
    *,
    target: dict[str, Any] | None,
    ctx: dict[str, Any],
    open_default: bool = False,
) -> str:
    name = ctx.get("name") or symbol
    advice = audit.get("near_term_advice") or (target or {}).get("advice")
    pct = (target or {}).get("pct_change") or ""
    rationale = (target or {}).get("rationale") or ""
    honesty = audit.get("holding_honesty") or ""
    cross = audit.get("cross_validation") or ""
    pos = ctx.get("position_pct")
    price = ctx.get("current_price")
    vol = ctx.get("holding_volume")
    pnl = ctx.get("unrealized_profit_pct")
    pos_line = ""
    if pos is not None or price is not None or pnl:
        pos_line = (
            f"<p class='text-[11px] text-gray-500 mt-0.5 flex flex-wrap items-center gap-2'>"
            f"<span>仓 {_esc(pos)}% · 现价 {_esc(price)} · {_esc(vol)} 股</span>"
            f"{_pnl_badge(pnl) if pnl else ''}"
            f"</p>"
        )
    badge = _action_badge(str(advice))
    open_attr = " open" if open_default else ""
    return f"""
<details class="t2-symbol-card group"{open_attr}>
  <summary class="t2-symbol-summary">
    <div class="t2-symbol-head">
      <h4 class="t2-symbol-title">{_esc(symbol)} · {_esc(name)}</h4>
      <span class="t2-symbol-hint group-open:hidden">点击展开详情</span>
      {pos_line}
    </div>
    <span class="t2-symbol-badge {_esc(badge)}">
      {_esc(_action_label(str(advice)))}{(' · ' + _esc(pct)) if pct else ''}
    </span>
  </summary>
  <div class="t2-symbol-body">
    {_para(rationale, label="建议理由：")}
    {_para(honesty, label="持仓诚实（加仓/维持/减仓 · 剩余资金）：")}
    {_para(cross, label="JL1–JL4 交叉验证：")}
    <div class="mt-2 pt-2 border-t border-gray-200/80 space-y-2">
      {_render_jl_checklist_layer(audit.get("jl1") or [], layer="JL1 宏观", id_key="topic_id")}
      {_render_jl_checklist_layer(audit.get("jl2") or [], layer="JL2 产业链", id_key="topic_id")}
      {_render_jl_checklist_layer(audit.get("jl3") or [], layer="JL3 微观靶向", id_key="key")}
    </div>
    <div class="mt-2 pt-2 border-t border-gray-200/80">
      <p class="text-[11px] font-medium text-gray-500 mb-1">JL4 读数摘要（本地 T1）</p>
      {_jl4_summary(audit.get("jl4_read") or [])}
    </div>
    {_render_radar_nine_dimensions_block(audit.get("radar_nine_dimensions"))}
  </div>
</details>
"""


def _render_truncation_warning(meta: dict[str, Any], payload: dict[str, Any]) -> str:
    if not meta.get("truncated"):
        return ""
    max_out = meta.get("max_output_tokens") or (payload.get("token_limits") or {}).get(
        "max_output_tokens"
    )
    return (
        "<p class='text-[11px] text-amber-700 bg-amber-50 border border-amber-200 "
        "rounded px-2 py-1 mt-2'>"
        f"⚠️ 输出已达上限（{ _esc(max_out) } tokens），JSON 可能被截断；"
        "请减少标的数量或精简问题后重试</p>"
    )


def _render_portfolio_section(audit: dict[str, Any], payload: dict[str, Any]) -> str:
    cmd = audit.get("Execution_Command") or {}
    daily = audit.get("Executing_Daily_Audit") or {}
    reasoning = audit.get("Reasoning_Engine") or {}
    action = cmd.get("action")
    meta = payload.get("opus_meta") or {}
    cost = meta.get("cost_yuan")
    cost_s = f"¥{float(cost):.4f}" if cost is not None else "—"
    ctx_map = _t1_context(payload)

    summary = (cmd.get("one_sentence_summary") or "").strip()
    stop = (cmd.get("stop_loss_line") or "").strip()
    cross = (reasoning.get("cross_validation_logic") or "").strip()
    conflicts = (reasoning.get("signal_conflicts") or "").strip()
    l3_block = _render_verdict_by_symbol(
        daily.get("L3_Fundamental_Verdict"), label="L3 基本面", ctx_map=ctx_map
    )
    l4_block = _render_verdict_by_symbol(
        daily.get("L4_Microstructure_Verdict"), label="L4 资金博弈", ctx_map=ctx_map
    )
    targets_block = _render_target_chips(cmd)
    extra_sections: list[str] = []
    if stop:
        extra_sections.append(
            f"<section class='t2-reply-section t2-reply-section--stop'>"
            f"<h4 class='t2-reply-section-title'>止盈止损</h4>"
            f"<p class='t2-reply-section-body'>{_esc(stop)}</p></section>"
        )
    if cross:
        extra_sections.append(
            f"<section class='t2-reply-section'>"
            f"<h4 class='t2-reply-section-title'>推理链</h4>"
            f"<p class='t2-reply-section-body'>{_esc(cross)}</p></section>"
        )
    if conflicts:
        extra_sections.append(
            f"<section class='t2-reply-section t2-reply-section--warn'>"
            f"<h4 class='t2-reply-section-title'>信号冲突</h4>"
            f"<p class='t2-reply-section-body'>{_esc(conflicts)}</p></section>"
        )

    return f"""
<section class="t2-reply-portfolio">
  <div class="t2-reply-hero">
    <div class="t2-reply-hero-text">
      <span class="t2-reply-hero-label">组合结论</span>
      <p class="t2-reply-summary">{_esc(summary) or '—'}</p>
    </div>
    <span class="t2-reply-action-badge {_esc(_action_badge(str(action)))}">
      {_esc(_action_label(str(action)))}
    </span>
  </div>
  <div class="t2-reply-sections">
    {l3_block}
    {l4_block}
    {''.join(extra_sections)}
    {f'<section class="t2-reply-section t2-reply-section--targets"><h4 class="t2-reply-section-title">逐标的</h4>{targets_block}</section>' if targets_block else ''}
  </div>
  <p class="t2-reply-meta">
    模型 {_esc(meta.get('model') or payload.get('model_id') or '—')} · {cost_s} ·
    入{_esc(meta.get('tokens_in', 0))}/出{_esc(meta.get('tokens_out', 0))}/
    {_esc(meta.get('max_output_tokens') or (payload.get('token_limits') or {}).get('max_output_tokens') or '—')} tok
  </p>
  {_render_truncation_warning(meta, payload)}
</section>
"""


def _render_compact_reply(payload: dict[str, Any]) -> str:
    """轻量分区排版（未勾选九维时的对话区）。"""
    audit = structured_audit_from_payload(payload)
    if not audit.get("Execution_Command") and not audit.get("symbol_audits"):
        return ""
    return _render_portfolio_section(audit, payload)


def _render_error_section(payload: dict[str, Any], meta: dict[str, Any]) -> str:
    err = (meta.get("error") or payload.get("opus_error") or "").strip()
    reason = (payload.get("opus_skip_reason") or "Opus 调用失败").strip()
    syms = ", ".join(payload.get("symbols") or [])
    jl4 = payload.get("jl4_indicator_counts") or {}
    jl4_line = " · ".join(f"{k} {v}项" for k, v in jl4.items()) or "—"

    return f"""
<section class="rounded-lg border border-rose-200 bg-rose-50/70 p-3 mb-3">
  <h3 class="text-sm font-semibold text-rose-900 mb-2">⚠️ 分析未完成</h3>
  <p class="text-xs text-rose-800 leading-relaxed whitespace-pre-wrap">{_esc(err or reason)}</p>
  <ul class="text-[11px] text-rose-700/90 mt-2 space-y-1 list-disc list-inside">
    <li>数据已拼接：标的 {_esc(syms or '—')} · JL4 {_esc(jl4_line)}</li>
    <li>可刷新后重试，或换 Opus 4.5 模型</li>
    <li>完整 payload 已写入审计，可展开下方 JSON 检查</li>
  </ul>
</section>
"""


def _render_assembly_section(payload: dict[str, Any]) -> str:
    reason = (payload.get("opus_skip_reason") or "仅数据拼接").strip()
    syms = ", ".join(payload.get("symbols") or [])
    jl4 = payload.get("jl4_indicator_counts") or {}
    jl4_line = " · ".join(f"{k} {v}项" for k, v in jl4.items()) or "—"
    return f"""
<section class="rounded-lg border border-amber-200 bg-amber-50/70 p-3 mb-3">
  <h3 class="text-sm font-semibold text-amber-900 mb-2">仅数据拼接（未调用 Opus）</h3>
  <p class="text-xs text-amber-800">{_esc(reason)}</p>
  <p class="text-[11px] text-amber-700/90 mt-2">标的 {_esc(syms)} · JL4 {_esc(jl4_line)}</p>
</section>
"""


def _render_truncated_fail_section(payload: dict[str, Any], meta: dict[str, Any]) -> str:
    """Opus 已响应但输出 token 触顶，JSON 不完整无法渲染组合结论。"""
    opus_meta = payload.get("opus_meta") or {}
    audit = payload.get("opus_audit") or {}
    raw = (
        payload.get("opus_raw_text")
        or (audit.get("raw_text") if isinstance(audit, dict) else "")
        or ""
    )
    max_out = opus_meta.get("max_output_tokens") or (payload.get("token_limits") or {}).get(
        "max_output_tokens"
    )
    excerpt = _esc(str(raw)[-1200:]) if raw else "（无缓存文本）"
    return f"""
<section class="rounded-lg border border-amber-300 bg-amber-50/80 p-3 mb-3">
  <h3 class="text-sm font-semibold text-amber-900 mb-2">⚠️ Opus 已返回，但输出被 token 上限截断</h3>
  <p class="text-xs text-amber-900 leading-relaxed">
    本次输出 <strong>{_esc(opus_meta.get('tokens_out', '?'))}</strong> tokens，触顶
    <strong>{_esc(max_out)}</strong>（stop_reason=max_tokens），JSON 不完整，无法解析组合结论。
    请<strong>减少同时分析的标的数量</strong>或精简 JL1–3 问题后重新提交；Prompt 已要求 Opus 在 { _esc(max_out) } tokens 内闭合 JSON。
  </p>
  <p class="text-[11px] text-amber-800 mt-2">响应末尾片段（供人工扫读）：</p>
  <pre class="text-[10px] bg-white/80 border border-amber-200 rounded p-2 mt-1 max-h-40 overflow-auto whitespace-pre-wrap">{excerpt}</pre>
  {_render_truncation_warning(opus_meta, payload)}
</section>
"""


def _render_json_parse_fail_section(payload: dict[str, Any], meta: dict[str, Any]) -> str:
    """Opus 已响应但 JSON 解析失败（常见：末尾多余字符）。"""
    opus_meta = payload.get("opus_meta") or {}
    raw = payload.get("opus_raw_text") or (payload.get("opus_audit") or {}).get("raw_text") or ""
    reparsed = structured_audit_from_payload(payload)
    if reparsed.get("Execution_Command") or reparsed.get("symbol_audits"):
        return ""
    excerpt = _esc(str(raw)[-800:]) if raw else "（无缓存文本）"
    return f"""
<section class="rounded-lg border border-amber-300 bg-amber-50/80 p-3 mb-3">
  <h3 class="text-sm font-semibold text-amber-900 mb-2">⚠️ Opus 已返回，但 JSON 解析失败</h3>
  <p class="text-xs text-amber-900 leading-relaxed">
    模型已输出 { _esc(opus_meta.get('tokens_out', '?')) } tokens，结构不符合 output_contract
    （常见原因：JSON 末尾多余字符）。请<strong>重新提交</strong>；若重复出现请联系排查。
  </p>
  <p class="text-[11px] text-amber-800 mt-2">响应末尾片段：</p>
  <pre class="text-[10px] bg-white/80 border border-amber-200 rounded p-2 mt-1 max-h-32 overflow-auto whitespace-pre-wrap">{excerpt}</pre>
</section>
"""


def extract_t2_prose_text(payload: dict[str, Any]) -> str:
    """从 T2 结构化 audit 提取对话区展示用的中文正文（不含 JSON / JL 表格）。"""
    audit = structured_audit_from_payload(payload)
    if not isinstance(audit, dict) or not audit:
        raw = (payload.get("opus_raw_text") or "").strip()
        if raw and not raw.startswith("{"):
            return raw[:8000]
        return ""

    parts: list[str] = []
    cmd = audit.get("Execution_Command") or {}
    daily = audit.get("Executing_Daily_Audit") or {}
    reasoning = audit.get("Reasoning_Engine") or {}

    summary = (cmd.get("one_sentence_summary") or "").strip()
    if summary:
        parts.append(summary)

    action = cmd.get("action")
    if action:
        parts.append(f"【操作建议】{_action_label(str(action))}")

    l3 = (daily.get("L3_Fundamental_Verdict") or "").strip()
    if l3:
        parts.append(f"【基本面】\n{l3}")

    l4 = (daily.get("L4_Microstructure_Verdict") or "").strip()
    if l4:
        parts.append(f"【资金博弈】\n{l4}")

    cross = (reasoning.get("cross_validation_logic") or "").strip()
    if cross:
        parts.append(f"【推理链】\n{cross}")

    conflicts = (reasoning.get("signal_conflicts") or "").strip()
    if conflicts:
        parts.append(f"【信号冲突】\n{conflicts}")

    stop = (cmd.get("stop_loss_line") or "").strip()
    if stop:
        parts.append(f"【止盈止损】{stop}")

    target_lines: list[str] = []
    for t in cmd.get("targets") or []:
        if not isinstance(t, dict):
            continue
        sym = (t.get("symbol") or "").strip()
        adv = _action_label(str(t.get("advice") or ""))
        pct = (t.get("pct_change") or "").strip()
        rat = (t.get("rationale") or "").strip()
        line = f"· {sym} {adv}"
        if pct:
            line += f" {pct}"
        if rat:
            line += f"：{rat}"
        target_lines.append(line)
    if target_lines:
        parts.append("【逐标的】\n" + "\n".join(target_lines))

    return "\n\n".join(parts).strip()


def _payload_has_radar_nine_dimensions(payload: dict[str, Any]) -> bool:
    if payload.get("include_radar_nine_dim"):
        return True
    audit = structured_audit_from_payload(payload)
    for sym_audit in (audit.get("symbol_audits") or {}).values():
        if not isinstance(sym_audit, dict):
            continue
        radar = sym_audit.get("radar_nine_dimensions")
        if isinstance(radar, dict) and (radar.get("dimensions") or {}):
            return True
    return False


def render_t2_chat_reply(payload: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    """Opus 对话区主渲染：勾选九维或已有九维 JSON 时用结构化卡片，否则 prose。"""
    if _payload_has_radar_nine_dimensions(payload):
        return render_t2_assistant_card(payload, meta)
    return render_t2_chat_prose(payload, meta)


def render_t2_chat_prose(payload: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    """Opus 分析区 · 仅展示模型中文回复（JSON / 审计详情见 /audit）。"""
    meta = meta or {}
    status = meta.get("status") or ""
    opus_meta = payload.get("opus_meta") or {}
    audit = structured_audit_from_payload(payload)
    if audit is not payload.get("opus_audit"):
        payload = {**payload, "opus_audit": audit}
    has_structured = bool(
        isinstance(audit, dict)
        and (audit.get("Execution_Command") or audit.get("symbol_audits"))
    )
    api_ok = bool(payload.get("api_connected") and has_structured)
    truncated = bool(opus_meta.get("truncated"))
    parse_failed = bool(
        payload.get("api_connected") and not has_structured and not truncated
    )

    if api_ok:
        compact = _render_compact_reply(payload)
        if compact:
            return f"<div class='t2-analyst-result t2-analyst-result--compact'>{compact}</div>"
        prose = extract_t2_prose_text(payload)
        if prose:
            return (
                f"<div class='t2-analyst-result t2-analyst-result--compact'>"
                f"<div class='t2-reply-fallback prose'>{_esc(prose)}</div></div>"
            )

    if truncated and payload.get("api_connected"):
        return (
            "<div class='t2-analyst-result rounded-lg border border-amber-200 bg-amber-50/80 "
            "p-3 text-sm text-amber-900'>"
            "<p class='font-medium mb-1'>输出被截断</p>"
            "<p class='text-xs leading-relaxed'>模型回复过长未能完整解析。"
            "请减少标的数量或缩短问题后重试；完整原始输出可在审计页查看。</p></div>"
        )
    if parse_failed:
        prose = extract_t2_prose_text(payload)
        if prose:
            return (
                f"<div class='t2-analyst-result'>"
                f"<div class='mb-2 rounded-lg border border-amber-200 bg-amber-50/80 "
                f"p-2 text-xs text-amber-900'>"
                f"<p class='font-medium mb-0.5'>JSON 未完整闭合，已尽力展示正文</p>"
                f"<p class='leading-relaxed'>建议减少标的数量后重试以获取可同步执行区的结构化结论；"
                f"完整原始输出见审计页。</p></div>"
                f"<div class='text-sm text-gray-800 leading-relaxed whitespace-pre-wrap'>"
                f"{_esc(prose)}</div></div>"
            )
        return (
            "<div class='t2-analyst-result rounded-lg border border-amber-200 bg-amber-50/80 "
            "p-3 text-sm text-amber-900'>"
            "<p class='font-medium mb-1'>回复格式异常</p>"
            "<p class='text-xs leading-relaxed'>模型已返回但未能解析为结构化结论，"
            "请重试；完整内容可在审计页查看。</p></div>"
        )
    if status == "error" or payload.get("opus_error"):
        err = (meta.get("error") or payload.get("opus_error") or "分析失败").strip()
        return (
            f"<div class='t2-analyst-result rounded-lg border border-rose-200 bg-rose-50/80 "
            f"p-3 text-sm text-rose-900'>"
            f"<p class='font-medium mb-1'>分析未完成</p>"
            f"<p class='text-xs leading-relaxed whitespace-pre-wrap'>{_esc(err)}</p></div>"
        )
    if payload.get("preview_only"):
        reason = (payload.get("opus_skip_reason") or "数据已拼接，模型未调用").strip()
        return (
            f"<div class='t2-analyst-result rounded-lg border border-amber-200 bg-amber-50/70 "
            f"p-3 text-sm text-amber-900'>"
            f"<p class='leading-relaxed whitespace-pre-wrap'>{_esc(reason)}</p></div>"
        )

    return (
        "<div class='t2-analyst-result text-sm text-gray-500'>"
        "暂无分析内容</div>"
    )


def _assistant_pin_eligible(payload: dict[str, Any], meta: dict[str, Any]) -> bool:
    if not (meta.get("request_id") or payload.get("request_id")):
        return False
    if not payload.get("api_connected"):
        return False
    audit = structured_audit_from_payload(payload)
    return bool(
        isinstance(audit, dict)
        and (audit.get("Execution_Command") or audit.get("symbol_audits"))
    )


def render_opus_assistant_bubble(
    card_html: str,
    *,
    request_id: str = "",
    pin_eligible: bool = False,
) -> str:
    """助手回复外层：⋯ 菜单（同步执行区 / 审计 / 复制）。"""
    rid = _esc(request_id)
    audit = (
        f"<a href='/audit?t2_id={rid}' class='opus-msg-menu-item' target='_blank' rel='noopener'>"
        f"<span class='opus-msg-menu-icon'>📋</span>查看审计</a>"
        if request_id
        else ""
    )
    if pin_eligible and request_id:
        pin_btn = (
            f"<button type='button' class='opus-msg-menu-item' data-opus-action='pin-executing' "
            f"data-request-id='{rid}'>"
            f"<span class='opus-msg-menu-icon'>📌</span>固定为 T2 摘要"
            f"<span class='opus-msg-menu-hint'>阻塞自动同步</span></button>"
        )
    else:
        pin_btn = (
            "<span class='opus-msg-menu-item is-disabled' "
            "title='需分析成功，且在上方勾选标的后可用'>"
            "<span class='opus-msg-menu-icon'>📌</span>固定为 T2 摘要"
            "<span class='opus-msg-menu-hint'>需先选标的</span></span>"
        )
    copy_btn = (
        "<button type='button' class='opus-msg-menu-item' data-opus-action='copy-reply'>"
        "<span class='opus-msg-menu-icon'>📄</span>复制正文</button>"
    )
    exec_link = (
        "<a href='/planning?view=executing' class='opus-msg-menu-item' target='_blank' "
        "rel='noopener'><span class='opus-msg-menu-icon'>↗</span>打开执行区</a>"
    )
    data_rid = f' data-request-id="{rid}"' if request_id else ""
    return (
        f"<div class='opus-assistant-bubble group w-full'{data_rid}>"
        f"<div class='flex justify-end items-center gap-1 mb-1 pr-1'>"
        f"<details class='opus-msg-menu'>"
        f"<summary class='opus-msg-menu-trigger' aria-label='更多操作' title='更多'>"
        f"<svg width='16' height='16' viewBox='0 0 24 24' fill='currentColor' "
        f"aria-hidden='true'><circle cx='5' cy='12' r='2'/><circle cx='12' cy='12' r='2'/>"
        f"<circle cx='19' cy='12' r='2'/></svg></summary>"
        f"<div class='opus-msg-menu-panel' role='menu'>{pin_btn}{audit}{copy_btn}{exec_link}</div>"
        f"</details></div>"
        f"<div class='rounded-2xl rounded-tl-sm bg-white border border-violet-100 "
        f"shadow-sm opus-assistant-body t2-assistant-body'>{card_html}</div>"
        f"<p class='opus-pin-toast hidden text-[11px] text-emerald-700 mt-1 pr-1 text-right'></p>"
        f"</div>"
    )


def render_t2_assistant_card(payload: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    """生成助手回复结构化 HTML（成功 / 失败 / 仅拼接）。"""
    meta = meta or {}
    status = meta.get("status") or ""
    opus_meta = payload.get("opus_meta") or {}
    audit = structured_audit_from_payload(payload)
    if audit is not payload.get("opus_audit"):
        payload = {**payload, "opus_audit": audit}
    has_structured = bool(
        isinstance(audit, dict)
        and (audit.get("Execution_Command") or audit.get("symbol_audits"))
    )
    api_ok = bool(payload.get("api_connected") and has_structured)
    truncated = bool(opus_meta.get("truncated"))
    parse_failed = bool(
        payload.get("api_connected") and not has_structured and not truncated
    )
    parts: list[str] = []

    if api_ok:
        audit = payload.get("opus_audit") or {}
        parts.append(_render_portfolio_section(audit, payload))
        audits = audit.get("symbol_audits") or {}
        targets = _target_map(audit.get("Execution_Command") or {})
        ctx_map = _t1_context(payload)
        symbols = _ordered_symbols(payload, audits)
        if symbols:
            parts.append("<div class='t2-symbol-list'>")
            parts.append("<h3 class='t2-symbol-list-title'>逐标的详情</h3>")
            for i, sym in enumerate(symbols):
                parts.append(
                    _render_symbol_section(
                        sym,
                        audits.get(sym) or {},
                        target=targets.get(sym),
                        ctx=ctx_map.get(sym, {}),
                        open_default=(i == 0),
                    )
                )
            parts.append("</div>")
    elif truncated and payload.get("api_connected"):
        parts.append(_render_truncated_fail_section(payload, meta))
    elif parse_failed:
        parts.append(_render_json_parse_fail_section(payload, meta))
    elif status == "error" or payload.get("opus_error"):
        parts.append(_render_error_section(payload, meta))
    elif payload.get("preview_only"):
        parts.append(_render_assembly_section(payload))

    rid = meta.get("request_id") or payload.get("request_id")
    footer = ""
    if rid:
        footer = (
            f"<p class='text-[10px] text-violet-600 mt-2 pt-2 border-t border-violet-100'>"
            f"<a href='/audit?t2_id={_esc(rid)}' class='underline font-medium'>审计 {_esc(rid)}</a>"
            f" · <a href='/api/executing/analyst/audit/{_esc(rid)}' class='underline' target='_blank'>JSON</a>"
            f"</p>"
        )

    return (
        f"<div class='t2-analyst-result t2-analyst-result--structured'>"
        f"{''.join(parts)}{footer}</div>"
    )
