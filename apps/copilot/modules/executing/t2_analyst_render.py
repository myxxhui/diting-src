"""T2 持仓分析 · 对话区结构化 HTML 渲染。

[Ref: 28_ §5]
"""
from __future__ import annotations

import html
import json
import re
from typing import Any


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
        return _para(t, label=f"{label}：")

    blocks: list[str] = []
    for sym, dname, chunk in segments:
        ctx = ctx_map.get(sym, {})
        title = f"{_esc(dname)} · {_esc(sym)}"
        blocks.append(
            f"<div class='rounded border border-gray-200/80 bg-white/70 px-2.5 py-2 mt-1.5'>"
            f"<div class='flex flex-wrap items-center gap-2 mb-1'>"
            f"<span class='text-xs font-semibold text-gray-800'>{title}</span>"
            f"{_pnl_badge(ctx.get('unrealized_profit_pct'))}"
            f"</div>"
            f"<p class='text-xs text-gray-700 leading-relaxed'>{_esc(chunk)}</p>"
            f"</div>"
        )

    return (
        f"<div class='mt-1.5'>"
        f"<p class='text-xs text-gray-500 mb-1'>"
        f"<span class='text-gray-400'>{_esc(label)}：</span>"
        f"按标的分段 · 浮盈/浮亏以 T1 持仓为准（非组合加总）</p>"
        f"{''.join(blocks)}"
        f"</div>"
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


def _render_symbol_section(
    symbol: str,
    audit: dict[str, Any],
    *,
    target: dict[str, Any] | None,
    ctx: dict[str, Any],
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
    return f"""
<details class="rounded-lg border border-gray-200 bg-gray-50/80 group">
  <summary class="cursor-pointer list-none p-3 flex flex-wrap items-center justify-between gap-2 marker:content-none">
    <div>
      <h4 class="text-sm font-semibold text-gray-900 inline">{_esc(symbol)} · {_esc(name)}</h4>
      <span class="text-[10px] text-gray-400 ml-2 group-open:hidden">点击展开</span>
      {pos_line}
    </div>
    <span class="text-xs font-medium px-2.5 py-1 rounded-full {_esc(badge)}">
      {_esc(_action_label(str(advice)))}{(' · ' + _esc(pct)) if pct else ''}
    </span>
  </summary>
  <div class="px-3 pb-3 pt-0 border-t border-gray-200/60">
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
        "可提高 EXECUTING_T2_MAX_OUTPUT_TOKENS 后重试</p>"
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

    return f"""
<section class="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 mb-3">
  <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
    <h3 class="text-sm font-semibold text-emerald-900">组合结论</h3>
    <span class="text-xs font-semibold px-2.5 py-1 rounded-full {_esc(_action_badge(str(action)))}">
      {_esc(_action_label(str(action)))}
    </span>
  </div>
  {_para(cmd.get("one_sentence_summary"), label="一句话：", cls="text-sm text-gray-800 font-medium leading-relaxed")}
  {_render_verdict_by_symbol(daily.get("L3_Fundamental_Verdict"), label="L3 基本面", ctx_map=ctx_map)}
  {_render_verdict_by_symbol(daily.get("L4_Microstructure_Verdict"), label="L4 资金博弈", ctx_map=ctx_map)}
  {_para(cmd.get("stop_loss_line"), label="止盈止损界碑：")}
  {_para(reasoning.get("cross_validation_logic"), label="JL1–JL4 组合推理链：")}
  {_para(reasoning.get("signal_conflicts"), label="信号冲突：")}
  <p class="text-[10px] text-gray-400 mt-2 pt-2 border-t border-emerald-100">
    模型 {_esc(meta.get('model') or payload.get('model_id') or '—')} · {cost_s} ·
    入{_esc(meta.get('tokens_in', 0))}/出{_esc(meta.get('tokens_out', 0))}/
    {_esc(meta.get('max_output_tokens') or (payload.get('token_limits') or {}).get('max_output_tokens') or '—')} tok
  </p>
  {_render_truncation_warning(meta, payload)}
</section>
"""


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


def render_t2_assistant_card(payload: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    """生成助手回复结构化 HTML（成功 / 失败 / 仅拼接）。"""
    meta = meta or {}
    status = meta.get("status") or ""
    api_ok = payload.get("api_connected") and payload.get("opus_audit")
    parts: list[str] = []

    if api_ok:
        audit = payload.get("opus_audit") or {}
        parts.append(_render_portfolio_section(audit, payload))
        audits = audit.get("symbol_audits") or {}
        targets = _target_map(audit.get("Execution_Command") or {})
        ctx_map = _t1_context(payload)
        symbols = _ordered_symbols(payload, audits)
        if symbols:
            parts.append(
                "<div class='space-y-2 mb-2'>"
                "<h3 class='text-xs font-semibold text-gray-500 uppercase tracking-wide'>"
                "逐标的建议</h3>"
            )
            for sym in symbols:
                parts.append(
                    _render_symbol_section(
                        sym,
                        audits.get(sym) or {},
                        target=targets.get(sym),
                        ctx=ctx_map.get(sym, {}),
                    )
                )
            parts.append("</div>")
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

    return f"<div class='t2-analyst-result space-y-1'>{''.join(parts)}{footer}</div>"
