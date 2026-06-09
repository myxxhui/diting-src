"""执行中工作区 HTML 片段渲染 · 现代 SaaS 指标卡片设计系统。

[Ref: 28_ §4 · executing_routes]
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Callable

from apps.copilot.db.datetime_util import utc_naive_to_shanghai_display
from apps.copilot.modules.executing.indicator_nodes import (
    SOURCE_INTRADAY_TICK,
    raw_metrics_for_display,
)
from apps.copilot.modules.executing.profile import PROBE_KEYS
from apps.copilot.modules.executing.probe_card_timing import ProbeCardTiming, render_card_timing_bar
from apps.copilot.modules.executing.probe_labels import probe_indicator_name, probe_label

# ── Design tokens（Tailwind · 卡片间距 gap-6 · 左侧 accent · Tag 语义色）──
_CARD_BASE = (
    "probe-indicator-card bg-white border border-gray-200 rounded-xl "
    "shadow-sm hover:shadow-md transition-shadow p-6 mb-0"
)
_SECTION = "executing-probe-section mb-6"

# probe_key → 分类主题（Tailwind 完整类名 + inline 左边框兜底）
PROBE_THEMES: dict[str, dict[str, str]] = {
    "qmt_atr_trailing": {
        "category": "risk",
        "accent_hex": "#3b82f6",
        "border": "border border-gray-200 border-l-[4px] border-l-blue-500",
        "badge": "bg-blue-50 text-blue-700",
        "formula_accent": "border-l-blue-500",
    },
    "volume_price_div": {
        "category": "volume_price",
        "accent_hex": "#a855f7",
        "border": "border border-gray-200 border-l-[4px] border-l-purple-500",
        "badge": "bg-purple-50 text-purple-700",
        "formula_accent": "border-l-purple-500",
    },
    "smart_money_flow": {
        "category": "flow",
        "accent_hex": "#f97316",
        "border": "border border-gray-200 border-l-[4px] border-l-orange-500",
        "badge": "bg-orange-50 text-orange-700",
        "formula_accent": "border-l-orange-500",
    },
    "level2_super_order": {
        "category": "percentile",
        "accent_hex": "#14b8a6",
        "border": "border border-gray-200 border-l-[4px] border-l-teal-500",
        "badge": "bg-teal-50 text-teal-800",
        "formula_accent": "border-l-teal-500",
    },
    "margin_short_skew": {
        "category": "percentile",
        "accent_hex": "#14b8a6",
        "border": "border border-gray-200 border-l-[4px] border-l-teal-500",
        "badge": "bg-teal-50 text-teal-800",
        "formula_accent": "border-l-teal-500",
    },
    "turnover_acceleration": {
        "category": "volume_price",
        "accent_hex": "#0ea5e9",
        "border": "border border-gray-200 border-l-[4px] border-l-sky-500",
        "badge": "bg-sky-50 text-sky-700",
        "formula_accent": "border-l-sky-500",
    },
    "tech_beta_correlation": {
        "category": "percentile",
        "accent_hex": "#8b5cf6",
        "border": "border border-gray-200 border-l-[4px] border-l-violet-500",
        "badge": "bg-violet-50 text-violet-700",
        "formula_accent": "border-l-violet-500",
    },
    "block_trade_discount": {
        "category": "event",
        "accent_hex": "#6366f1",
        "border": "border border-gray-200 border-l-[4px] border-l-indigo-500",
        "badge": "bg-indigo-50 text-indigo-700",
        "formula_accent": "border-l-indigo-500",
    },
    "retail_concentration": {
        "category": "percentile",
        "accent_hex": "#14b8a6",
        "border": "border border-gray-200 border-l-[4px] border-l-teal-500",
        "badge": "bg-teal-50 text-teal-800",
        "formula_accent": "border-l-teal-500",
    },
    "insider_sell_actual": {
        "category": "insider",
        "accent_hex": "#e11d48",
        "border": "border border-gray-200 border-l-[4px] border-l-rose-500",
        "badge": "bg-rose-50 text-rose-700",
        "formula_accent": "border-l-rose-500",
    },
    "etf_redemption_impact": {
        "category": "passive_flow",
        "accent_hex": "#7c3aed",
        "border": "border border-gray-200 border-l-[4px] border-l-violet-500",
        "badge": "bg-violet-50 text-violet-700",
        "formula_accent": "border-l-violet-500",
    },
}
_DEFAULT_THEME = {
    "category": "neutral",
    "accent_hex": "#9ca3af",
    "border": "border border-gray-200 border-l-[4px] border-l-gray-400",
    "badge": "bg-slate-50 text-slate-700",
    "formula_accent": "border-l-gray-400",
}

_TAG_NEUTRAL = "inline-flex items-baseline gap-1.5 px-2 py-1 rounded text-xs bg-gray-50 text-gray-800"
_TAG_HIGHLIGHT = "inline-flex items-baseline gap-1.5 px-2 py-1 rounded text-xs bg-blue-50 text-blue-800"
_TAG_POSITIVE = "inline-flex items-baseline gap-1.5 px-2 py-1 rounded text-xs bg-red-50 text-red-700"
_TAG_NEGATIVE = "inline-flex items-baseline gap-1.5 px-2 py-1 rounded text-xs bg-emerald-50 text-emerald-700"
_TAG_OUTLINE = "inline-flex items-baseline gap-1.5 px-2 py-1 rounded text-xs text-gray-700"
_FORMULA = (
    "mt-4 mb-1 px-4 py-3 rounded-r-md bg-slate-100 border-l-4 "
    "font-mono text-xs sm:text-sm text-gray-700 leading-relaxed"
)


def _esc(v: Any) -> str:
    return _html.escape(str(v)) if v is not None else ""


def _indicator_status(node: dict[str, Any]) -> str:
    return "ok" if node.get("value") is not None else "missing"


def _format_cst_time(raw: str | None) -> str | None:
    """统一北京时间展示；已是 CST 格式的 last_tick_time 原样保留。"""
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "T" in text:
        return utc_naive_to_shanghai_display(text) or text
    return text


def _is_intraday_node(node: dict[str, Any]) -> bool:
    rm = raw_metrics_for_display(node)
    src = str(node.get("source") or "")
    return bool(rm.get("last_tick_time")) or SOURCE_INTRADAY_TICK in src


def _status_dot(ok: bool) -> str:
    cls = "bg-emerald-500" if ok else "bg-red-500"
    return f'<span class="inline-block w-2 h-2 rounded-full {cls} shrink-0" aria-hidden="true"></span>'


def _value_color_class(
    val: Any,
    *,
    mode: str = "neutral",
) -> str:
    """mode: neutral | signed | percentile | atr"""
    if val is None:
        return "text-gray-900"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "text-gray-900"
    if mode == "signed":
        return "text-emerald-500" if f >= 0 else "text-rose-500"
    if mode == "percentile":
        if f >= 95:
            return "text-rose-600"
        if f <= 5:
            return "text-emerald-500"
        return "text-gray-900"
    if mode == "atr":
        return "text-emerald-500"
    return "text-gray-900"


def _probe_theme(probe_key: str) -> dict[str, str]:
    return PROBE_THEMES.get(probe_key, _DEFAULT_THEME)


def _card_shell(probe_key: str, *, visual_cooldown: bool = False) -> tuple[str, str]:
    """返回 (class, inline-style) · 双保险确保左侧 accent 可见。"""
    if visual_cooldown:
        cls = f"{_CARD_BASE} border border-gray-200 border-l-[4px] border-l-gray-400 opacity-90"
        style = (
            "border-left-width:4px;border-left-style:solid;border-left-color:#9ca3af;"
            "opacity:0.88;"
        )
        return cls, style
    theme = _probe_theme(probe_key)
    cls = f"{_CARD_BASE} {theme['border']}"
    style = f"border-left-width:4px;border-left-style:solid;border-left-color:{theme['accent_hex']};"
    return cls, style


def _highlight_formula(formula: str) -> str:
    """公式区：逐 token 转义后再包 span，避免 HTML 被当作纯文本输出。"""
    if not formula:
        return ""
    parts: list[str] = []
    for m in re.finditer(r"\d+\.?\d*|[+\-=/*()]|.", formula):
        tok = m.group(0)
        if re.fullmatch(r"\d+\.?\d*", tok):
            parts.append(f'<span class="text-slate-900 font-semibold">{_esc(tok)}</span>')
        elif re.fullmatch(r"[+\-=/*()]", tok):
            parts.append(f'<span class="text-gray-400">{_esc(tok)}</span>')
        else:
            parts.append(_esc(tok))
    return "".join(parts)


def _infer_tag_tone(label: str, raw: Any) -> str:
    """A 股习惯：正数红（涨/流入）· 负数绿（跌/流出）。"""
    signed_hints = ("净", "折价", "delta", "Delta", "比", "分位")
    if not any(h in label for h in signed_hints):
        return "neutral"
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return "neutral"
    if f > 0:
        return "positive"
    if f < 0:
        return "negative"
    return "neutral"


def _tag_shell(tone: str) -> tuple[str, str]:
    if tone == "highlight":
        return _TAG_HIGHLIGHT, "text-blue-800"
    if tone == "positive":
        return _TAG_POSITIVE, "text-red-700"
    if tone == "negative":
        return _TAG_NEGATIVE, "text-emerald-700"
    if tone == "outline":
        return _TAG_OUTLINE, "text-gray-800"
    return _TAG_NEUTRAL, "text-gray-900"


def _render_metric_tags(
    items: list[tuple[str, Any] | tuple[str, Any, str]],
    *,
    formatters: dict[str, Callable[[Any], str]] | None = None,
) -> str:
    formatters = formatters or {}
    tags: list[str] = []
    for item in items:
        label = item[0]
        raw = item[1]
        tone = item[2] if len(item) > 2 else _infer_tag_tone(label, raw)
        if tone == "signed":
            tone = _infer_tag_tone(label, raw)
        if raw is None or raw == "":
            continue
        if label in formatters:
            disp = formatters[label](raw)
        else:
            disp = _esc(raw)
        shell, val_cls = _tag_shell(tone)
        tags.append(
            f'<span class="{shell}">'
            f'<span class="text-gray-400">{_esc(label)}</span>'
            f'<span class="font-semibold {val_cls}">{disp}</span>'
            f"</span>"
        )
    if not tags:
        return ""
    return f'<div class="flex flex-wrap gap-2 mt-5">{"".join(tags)}</div>'


def _render_t1_json_details(probe_key: str, t1_json: dict[str, Any]) -> str:
    json_block = _esc(json.dumps(t1_json, ensure_ascii=False, indent=2))
    return f"""
<details class="mt-3 group">
  <summary class="text-[11px] text-gray-500 cursor-pointer hover:text-gray-700 font-medium list-none">
    T1 白盒 JSON（喂 T2）<span class="text-gray-400 group-open:hidden"> ▾</span><span class="hidden group-open:inline text-gray-400"> ▴</span>
  </summary>
  <pre class="text-[10px] bg-gray-900 text-emerald-300 p-3 rounded-lg mt-2 overflow-x-auto font-mono leading-relaxed">{json_block}</pre>
</details>"""


def _render_probe_card(
    *,
    probe_key: str,
    title: str,
    short_label: str,
    value_html: str,
    value_color: str = "text-gray-900",
    timestamp: str | None = None,
    card_timing: ProbeCardTiming | None = None,
    subtitle: str | None = None,
    fact_statement: str = "",
    calculation_logic: str = "",
    source: str = "",
    metric_items: list[tuple[str, Any]] | None = None,
    metric_formatters: dict[str, Callable[[Any], str]] | None = None,
    formula_accent: str = "",
    alert_html: str = "",
    t1_json: dict[str, Any] | None = None,
    status_ok: bool = True,
    visual_cooldown: bool = False,
) -> str:
    """统一指标卡片：Header · 描述 · 公式区 · Tag 栏 · 来源 Footer。"""
    theme = _probe_theme(probe_key)
    card_cls, card_style = _card_shell(probe_key, visual_cooldown=visual_cooldown)
    badge_cls = theme["badge"]
    formula_border = formula_accent or theme["formula_accent"]
    timing_bar = render_card_timing_bar(card_timing)
    if not timing_bar and timestamp:
        timing_bar = f'<p class="text-[11px] text-gray-400 mb-3 font-mono">{_esc(timestamp)}</p>'
    status_ok_effective = status_ok
    if card_timing and card_timing.health in ("failed", "stale", "missing"):
        status_ok_effective = False
    sub_line = (
        f'<p class="text-xs text-gray-500 mt-1">{_esc(subtitle)}</p>' if subtitle else ""
    )
    fact_block = (
        f'<p class="text-sm text-gray-600 leading-relaxed mt-4">{_esc(fact_statement)}</p>'
        if fact_statement
        else ""
    )
    formula_block = ""
    if calculation_logic:
        formula_block = (
            f'<div class="{_FORMULA} {formula_border}">'
            f"{_highlight_formula(calculation_logic)}</div>"
        )
    tags_html = _render_metric_tags(metric_items or [], formatters=metric_formatters)
    footer_json = _render_t1_json_details(probe_key, t1_json) if t1_json else ""
    source_line = _esc(source or "—")

    timing_attr = ""
    if card_timing is not None:
        timing_attr = f' data-timing-health="{_esc(card_timing.health)}"'

    return f"""
<article class="{card_cls}" style="{card_style}" data-probe-key="{_esc(probe_key)}" data-probe-category="{_esc(theme.get('category', ''))}"{timing_attr}>
  {timing_bar}
  <header class="flex items-start justify-between gap-4">
    <div class="min-w-0 flex-1">
      <h3 class="text-base font-semibold text-gray-900 leading-snug">{_esc(title)}</h3>
      <div class="mt-1.5 flex flex-wrap items-center gap-2">
        <span class="text-xs text-gray-500">{_esc(short_label)}</span>
        <code class="text-[11px] font-mono px-2 py-0.5 rounded-md {badge_cls}">{_esc(probe_key)}</code>
      </div>
      {sub_line}
    </div>
    <div class="flex items-center gap-2 shrink-0">
      {_status_dot(status_ok_effective)}
      <span class="text-xl font-bold tabular-nums {value_color}">{value_html}</span>
    </div>
  </header>
  {fact_block}
  {formula_block}
  {alert_html}
  {tags_html}
  <footer class="mt-5 pt-3 border-t border-gray-200">
    <p class="text-[11px] text-gray-400">来源 · {source_line}</p>
    {footer_json}
  </footer>
</article>
"""


def render_hot_data_timeline(
    node: dict[str, Any] | None,
    *,
    quote_job_at: str | None = None,
) -> str:
    """层 B 热数据时间线：盘中 tick / 盘后 PG 日K。"""
    if not node or not isinstance(node, dict):
        return """
<article class="bg-white border border-gray-200 rounded-xl shadow-sm px-5 py-4 mb-4">
  <p class="text-sm font-semibold text-gray-900">热数据时间线</p>
  <p class="text-xs text-gray-500 mt-1">暂无 ATR 指标 · 填写建仓日并刷新</p>
</article>
"""
    rm = raw_metrics_for_display(node)
    intraday = _is_intraday_node(node)
    tick = rm.get("last_tick_time")
    bar_as_of = rm.get("bar_as_of")
    quote_cst = _format_cst_time(quote_job_at)

    if intraday and tick:
        badge = "盘中热数据"
        badge_cls = "bg-emerald-50 text-emerald-700 border-emerald-200"
        time_main = f"北京时间 {_format_cst_time(str(tick)) or tick}"
        sub = "Redis Tick · T0 穿透存活"
    elif bar_as_of:
        badge = "盘后 PG 日K"
        badge_cls = "bg-gray-100 text-gray-700 border-gray-200"
        time_main = f"K线交易日 {bar_as_of}"
        if quote_cst:
            sub = f"最近热采集 北京时间 {quote_cst}（Cron 任务时刻，非交易所收盘时刻）"
        else:
            sub = "盘中 Redis 未命中 · 现价取自 PG 日K 收盘价"
    else:
        badge = "数据模式未知"
        badge_cls = "bg-amber-50 text-amber-800 border-amber-200"
        time_main = "—"
        sub = "缺少 tick 与收盘日元数据"

    return f"""
<article class="bg-white border border-gray-200 rounded-xl shadow-sm px-5 py-4 mb-4">
  <div class="flex flex-wrap items-center gap-2 text-xs">
    <span class="text-sm font-semibold text-gray-900">热数据时间线</span>
    <span class="px-2 py-0.5 rounded border text-[10px] font-medium {badge_cls}">{badge}</span>
    <span class="font-mono text-gray-800">{_esc(time_main)}</span>
  </div>
  <p class="text-xs text-gray-500 mt-2 leading-relaxed">{_esc(sub)}</p>
  <p class="text-[10px] text-gray-400 mt-1">A 股连续竞价 15:00 收盘；16:00 PG 落正式日K</p>
</article>
"""


def _qmt_timestamp_line(
    rm: dict[str, Any],
    *,
    quote_job_at: str | None = None,
) -> str | None:
    tick = rm.get("last_tick_time")
    bar_as_of = rm.get("bar_as_of")
    quote_cst = _format_cst_time(quote_job_at)
    if tick:
        cst = _format_cst_time(str(tick)) or tick
        return f"热数据快照 · 北京时间 {cst} · 盘中快照现价"
    if bar_as_of:
        extra = f" · 最近采集 北京时间 {quote_cst}" if quote_cst else ""
        return f"K线交易日 {bar_as_of}{extra}"
    return None


def render_qmt_atr_trailing_card(
    node: dict[str, Any],
    *,
    quote_job_at: str | None = None,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#15 ATR 止盈。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("qmt_atr_trailing")
    short = probe_label("qmt_atr_trailing")
    rm = raw_metrics_for_display(node)
    val_disp = _esc(val if val is not None else "—")
    value_html = f"{val_disp} <span class='text-sm font-medium text-gray-500'>倍</span>"

    return _render_probe_card(
        probe_key="qmt_atr_trailing",
        title=name,
        short_label=short,
        value_html=value_html,
        value_color=_value_color_class(val, mode="atr"),
        card_timing=card_timing,
        timestamp=_qmt_timestamp_line(rm, quote_job_at=quote_job_at) if not card_timing else None,
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("ATR₂₀", rm.get("atr_20"), "outline"),
            ("峰值价", rm.get("peak_price"), "highlight"),
            ("现价", rm.get("current_price"), "neutral"),
            ("快照时间", rm.get("last_tick_time"), "outline"),
        ],
        status_ok=st == "ok",
    )


def render_volume_price_div_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#16 15分钟高位量价背离。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("volume_price_div")
    short = probe_label("volume_price_div")
    rm = raw_metrics_for_display(node)
    val_disp = _esc(val if val is not None else "—")
    last_bar = rm.get("last_bar_datetime")
    ts = f"15m 末根 K 线 · {_esc(last_bar)}" if last_bar else None

    return _render_probe_card(
        probe_key="volume_price_div",
        title=name,
        short_label=short,
        value_html=val_disp,
        value_color="text-gray-900",
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("高位阴线量", rm.get("high_zone_down_vol"), "outline"),
            ("高位阳线量", rm.get("high_zone_up_vol"), "outline"),
            ("高位阈值价", rm.get("high_zone_threshold_price"), "highlight"),
            ("区间最高", rm.get("period_max"), "neutral"),
            ("区间最低", rm.get("period_min"), "neutral"),
            ("全样本量比", rm.get("global_vol_ratio"), "neutral"),
        ],
        status_ok=st == "ok",
    )


def render_smart_money_flow_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#17 L2 主力大单 · 3 日 Smart Money Delta。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("smart_money_flow")
    short = probe_label("smart_money_flow")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):+.4f}%" if val is not None else "—"
    direction = "净流入" if val is not None and float(val) >= 0 else "净流出"
    last_date = rm.get("last_update_date")
    ts = f"数据截止日 {last_date}" if last_date else None
    t1_json = {
        "smart_money_flow": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    return _render_probe_card(
        probe_key="smart_money_flow",
        title=name,
        short_label=short,
        value_html=_esc(pct_disp),
        value_color=_value_color_class(val, mode="signed"),
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle=f"近 3 交易日主力（特大单+大单）相对自由流通盘 · {direction}",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("3日主力净股数", rm.get("3d_smart_money_net_vol"), "signed"),
            ("3日散户净股数", rm.get("3d_retail_net_vol"), "signed"),
            ("自由流通股本", rm.get("free_float_shares"), "neutral"),
        ],
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_level2_super_order_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#18 L2 特大单 · 120 日历史分位。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("level2_super_order")
    short = probe_label("level2_super_order")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):.1f}%" if val is not None else "—"
    t1_json = {
        "level2_super_order": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    return _render_probe_card(
        probe_key="level2_super_order",
        title=name,
        short_label=short,
        value_html=_esc(pct_disp),
        value_color=_value_color_class(val, mode="percentile"),
        card_timing=card_timing,
        subtitle="仅特大单(elg) · 120 交易日历史分位",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("今日特大单净额(元)", rm.get("current_net_elg_amount"), "signed"),
            ("今日特大单买入(元)", rm.get("current_buy_elg_amount"), "positive"),
            ("今日特大单卖出(元)", rm.get("current_sell_elg_amount"), "negative"),
            ("120日均值(元)", rm.get("120d_mean_net_amount"), "outline"),
            ("120日P95(元)", rm.get("120d_p95_threshold"), "outline"),
            ("120日P05(元)", rm.get("120d_p05_threshold"), "outline"),
            ("回看窗口(日)", rm.get("lookback_window_days"), "outline"),
        ],
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_margin_short_skew_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#19 两融杠杆倾斜度 · 250 日历史分位。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("margin_short_skew")
    short = probe_label("margin_short_skew")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):.1f}%" if val is not None else "—"
    ratio = rm.get("margin_to_float_ratio")
    ratio_pct = f"{float(ratio) * 100:.2f}%" if ratio is not None else "—"
    inferred = rm.get("inferred_trade_date")
    ts = f"数据交易日 {inferred} · T+1 披露" if inferred else "T+1 两融披露"
    alert = ""
    if val is not None and float(val) >= 95:
        alert = (
            '<p class="mt-3 text-xs font-medium text-rose-600">'
            "⚠ 杠杆分位 &gt;95% · 高危堰塞湖区间</p>"
        )
    t1_json = {
        "margin_short_skew": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    def _ratio_fmt(v: Any) -> str:
        try:
            return f"{float(v) * 100:.2f}%"
        except (TypeError, ValueError):
            return _esc(v)

    return _render_probe_card(
        probe_key="margin_short_skew",
        title=name,
        short_label=short,
        value_html=_esc(pct_disp),
        value_color=_value_color_class(val, mode="percentile"),
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle=f"融资余额/流通市值 · 250 日历史分位 · 占盘 {ratio_pct}",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("融资余额(元)", rm.get("margin_balance"), "neutral"),
            ("融券余额(元)", rm.get("short_balance"), "outline"),
            ("融资买入额(元)", rm.get("margin_purchase_today"), "positive"),
            ("杠杆占流通盘", rm.get("margin_to_float_ratio"), "highlight"),
            ("250日均占盘比", rm.get("250d_mean_ratio"), "outline"),
            ("披露滞后(日)", rm.get("settlement_lag_days"), "outline"),
        ],
        metric_formatters={
            "杠杆占流通盘": _ratio_fmt,
            "250日均占盘比": _ratio_fmt,
        },
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_turnover_acceleration_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#20 自由换手率异动倍数。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("turnover_acceleration")
    short = probe_label("turnover_acceleration")
    rm = raw_metrics_for_display(node)
    val_disp = f"{float(val):.2f}" if val is not None else "—"
    value_html = f"{_esc(val_disp)} <span class='text-sm font-medium text-gray-500'>倍</span>"
    pct = rm.get("120d_accel_percentile")
    trade_date = rm.get("trade_date")
    ts = f"数据交易日 {trade_date} · 盘后 daily_basic" if trade_date else "盘后 turnover_rate_f"
    alert = ""
    if val is not None and float(val) >= 3.0:
        alert = (
            '<p class="mt-3 text-xs font-medium text-rose-600">'
            "⚠ 异动倍数 ≥3.0 · 流动性心跳异常加速</p>"
        )
    t1_json = {
        "turnover_acceleration": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    def _pct_fmt(v: Any) -> str:
        try:
            return f"{float(v) * 100:.2f}%"
        except (TypeError, ValueError):
            return _esc(v)

    value_color = "text-rose-600" if val is not None and float(val) >= 3.0 else "text-gray-900"

    return _render_probe_card(
        probe_key="turnover_acceleration",
        title=name,
        short_label=short,
        value_html=value_html,
        value_color=value_color,
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle=(
            f"自由流通换手率 turnover_rate_f · 120日加速分位 {pct}%"
            if pct is not None
            else "自由流通换手率 · 相对自身 20 日均值加速"
        ),
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("今日换手(小数)", rm.get("current_turnover_f"), "highlight"),
            ("20日均换手", rm.get("20d_mean_turnover_f"), "outline"),
            ("120日加速分位", rm.get("120d_accel_percentile"), "neutral"),
            ("量比", rm.get("volume_ratio"), "outline"),
        ],
        metric_formatters={
            "今日换手(小数)": _pct_fmt,
            "20日均换手": _pct_fmt,
            "120日加速分位": lambda v: f"{float(v):.1f}%",
        },
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_tech_beta_correlation_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#25 板块 Beta 共振度与解释系数。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("tech_beta_correlation")
    short = probe_label("tech_beta_correlation")
    rm = raw_metrics_for_display(node)
    val_disp = f"{float(val):.2f}" if val is not None else "—"
    value_html = f"{_esc(val_disp)} <span class='text-sm font-medium text-gray-500'>ρ</span>"
    r2 = rm.get("r_squared")
    beta = rm.get("beta_coefficient")
    sector = rm.get("sector_index_name") or rm.get("sector_index_used")
    trade_date = rm.get("trade_date")
    ts = f"数据交易日 {trade_date} · 盘后 index_daily" if trade_date else "盘后 daily + index_daily"
    alert = ""
    if r2 is not None and float(r2) >= 0.64:
        alert = (
            '<p class="mt-3 text-xs font-medium text-amber-600">'
            "⚠ R² ≥0.64 · 板块大势主导标的波动，警惕 Alpha 幻觉</p>"
        )
    t1_json = {
        "tech_beta_correlation": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }
    value_color = "text-amber-600" if r2 is not None and float(r2) >= 0.64 else "text-gray-900"

    return _render_probe_card(
        probe_key="tech_beta_correlation",
        title=name,
        short_label=short,
        value_html=value_html,
        value_color=value_color,
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle=(
            f"基准 {sector} · 60日 Pearson ρ · Beta {beta}"
            if beta is not None
            else f"基准 {sector} · 60日滚动相关"
        ),
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("Pearson ρ", rm.get("pearson_r"), "highlight"),
            ("R²", rm.get("r_squared"), "neutral"),
            ("Beta", rm.get("beta_coefficient"), "outline"),
            ("今日 Alpha 残差", rm.get("alpha_deviation_today"), "outline"),
        ],
        metric_formatters={
            "R²": lambda v: f"{float(v) * 100:.1f}%",
            "今日 Alpha 残差": lambda v: f"{float(v) * 100:.2f}%",
        },
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_block_trade_silent_card(state: dict[str, Any]) -> str:
    """#21 静默态 · 已采集但未达实质冲击阈值（事件驱动探针常驻可见）。"""
    mode = str(state.get("mode") or "silent")
    name = probe_indicator_name("block_trade_discount")
    short = probe_label("block_trade_discount")
    message = str(state.get("message") or "无实质大宗冲击 · 探针静默")
    theme = _probe_theme("block_trade_discount")
    card_cls, card_style = _card_shell("block_trade_discount")
    card_cls = f"{card_cls} opacity-95"

    if mode == "not_ready":
        value_html = "待同步"
        value_color = "text-amber-600 text-base"
        status_ok = False
    elif mode == "no_events":
        value_html = "无成交"
        value_color = "text-gray-400 text-base"
        status_ok = True
    else:
        value_html = "静默"
        value_color = "text-gray-500 text-base"
        status_ok = True

    metric_items: list[tuple[str, Any] | tuple[str, Any, str]] = []
    if state.get("latest_trade_date"):
        metric_items.append(("最近大宗日", state.get("latest_trade_date"), "outline"))
    if state.get("vwap_discount_rate") is not None:
        metric_items.append(("最近折价率", state.get("vwap_discount_rate"), "signed"))
    if state.get("float_impact_ratio") is not None:
        metric_items.append(("最近冲击比", state.get("float_impact_ratio"), "outline"))
    if state.get("history_event_days") is not None:
        metric_items.append(("3年有成交日", state.get("history_event_days"), "neutral"))

    def _ratio_fmt(v: Any) -> str:
        try:
            return f"{float(v) * 100:+.2f}%"
        except (TypeError, ValueError):
            return _esc(v)

    def _impact_fmt(v: Any) -> str:
        try:
            return f"{float(v) * 100:.3f}%"
        except (TypeError, ValueError):
            return _esc(v)

    badge_cls = theme["badge"]
    return f"""
<article class="{card_cls}" style="{card_style}" data-probe-key="block_trade_discount" data-probe-mode="{_esc(mode)}">
  <header class="flex items-start justify-between gap-4">
    <div class="min-w-0 flex-1">
      <h3 class="text-base font-semibold text-gray-900 leading-snug">{_esc(name)}</h3>
      <div class="mt-1.5 flex flex-wrap items-center gap-2">
        <span class="text-xs text-gray-500">{_esc(short)}</span>
        <code class="text-[11px] font-mono px-2 py-0.5 rounded-md {badge_cls}">block_trade_discount</code>
        <span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-100">事件驱动 · 监控中</span>
      </div>
      <p class="text-xs text-gray-500 mt-1">仅当盘口冲击 ≥0.1% 时升级为完整 T1 卡片并喂 Opus</p>
    </div>
    <div class="flex items-center gap-2 shrink-0">
      {_status_dot(status_ok)}
      <span class="font-bold tabular-nums {value_color}">{value_html}</span>
    </div>
  </header>
  <p class="text-sm text-gray-600 leading-relaxed mt-4">{_esc(message)}</p>
  {_render_metric_tags(metric_items, formatters={"最近折价率": _ratio_fmt, "最近冲击比": _impact_fmt})}
  <footer class="mt-5 pt-3 border-t border-gray-200">
    <p class="text-[11px] text-gray-400">来源 · Tushare Block Trade · 静默过滤已生效（非探针故障）</p>
  </footer>
</article>
"""


def render_block_trade_discount_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#21 大宗交易加权折价与盘口冲击。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("block_trade_discount")
    short = probe_label("block_trade_discount")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):+.2f}%" if val is not None else "—"
    trade_date = rm.get("trade_date")
    ts = f"数据交易日 {trade_date} · 盘后 block_trade" if trade_date else "18:00 盘后采集"
    impact = rm.get("float_impact_ratio")
    impact_pct = f"{float(impact) * 100:.2f}%" if impact is not None else "—"
    alert = ""
    if val is not None and float(val) <= -10:
        alert = (
            '<p class="mt-3 text-xs font-medium text-rose-600">'
            "⚠ 加权折价率 ≤-10% · 实质性暗盘抛压</p>"
        )
    t1_json = {
        "block_trade_discount": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    def _amt_fmt(v: Any) -> str:
        try:
            f = float(v)
            if abs(f) >= 1e8:
                return f"{f / 1e8:.2f}亿"
            if abs(f) >= 1e4:
                return f"{f / 1e4:.0f}万"
            return f"{f:.0f}"
        except (TypeError, ValueError):
            return _esc(v)

    def _ratio_fmt(v: Any) -> str:
        try:
            return f"{float(v) * 100:.2f}%"
        except (TypeError, ValueError):
            return _esc(v)

    value_color = "text-rose-600" if val is not None and float(val) < 0 else "text-gray-900"

    return _render_probe_card(
        probe_key="block_trade_discount",
        title=name,
        short_label=short,
        value_html=_esc(pct_disp),
        value_color=value_color,
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle=f"盘口冲击 {impact_pct} · 仅冲击≥0.1% 才上报 Opus",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("加权折价率", rm.get("vwap_discount_rate"), "signed"),
            ("盘口冲击比", rm.get("float_impact_ratio"), "highlight"),
            ("大宗总额", rm.get("total_block_amount"), "neutral"),
            ("自由流通市值", rm.get("free_float_mv"), "outline"),
            ("历史均折价", rm.get("historical_mean_discount"), "signed"),
            ("成交笔数", rm.get("trades_count"), "outline"),
        ],
        metric_formatters={
            "加权折价率": _ratio_fmt,
            "盘口冲击比": _ratio_fmt,
            "大宗总额": _amt_fmt,
            "自由流通市值": _amt_fmt,
            "历史均折价": _ratio_fmt,
        },
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_retail_concentration_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#22 户均持股集中度 · 3 年分位 + 时效性标注。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("retail_concentration")
    short = probe_label("retail_concentration")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):.1f}%" if val is not None else "—"
    end_date = rm.get("snapshot_end_date")
    days = rm.get("days_since_snapshot")
    stale = bool(rm.get("data_stale_warning"))
    ts = f"快照截止 {end_date} · 距今 {days} 天" if end_date else "股东户数快照"
    alert = ""
    if stale:
        alert = (
            '<p class="mt-3 text-xs font-medium text-amber-700">'
            "⚠ data_stale_warning · 快照超过 30 天，请勿刻舟求剑</p>"
        )
    elif val is not None and float(val) <= 20:
        alert = (
            '<p class="mt-3 text-xs font-medium text-rose-600">'
            "⚠ 户均持股分位 ≤20% · 高危散户化区间</p>"
        )
    t1_json = {
        "retail_concentration": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    def _chg_fmt(v: Any) -> str:
        try:
            return f"{float(v) * 100:+.1f}%"
        except (TypeError, ValueError):
            return _esc(v)

    def _vol_fmt(v: Any) -> str:
        try:
            f = float(v)
            if f >= 1e4:
                return f"{f/1e4:.1f}万"
            return f"{f:.0f}"
        except (TypeError, ValueError):
            return _esc(v)

    value_color = _value_color_class(val, mode="percentile")
    if val is not None and float(val) <= 20:
        value_color = "text-rose-600"

    return _render_probe_card(
        probe_key="retail_concentration",
        title=name,
        short_label=short,
        value_html=_esc(pct_disp),
        value_color=value_color,
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle=f"数据可靠性 {rm.get('data_reliability', '—')} · 户均持股历史分位（越低越分散）",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("股东户数", rm.get("current_holder_num"), "neutral"),
            ("户数变动率", rm.get("holder_change_rate"), "signed"),
            ("户均持股", rm.get("current_avg_hold_vol"), "highlight"),
            ("3年P80户均", rm.get("3yr_p80_concentration"), "outline"),
            ("距今(天)", rm.get("days_since_snapshot"), "outline"),
        ],
        metric_formatters={
            "户数变动率": _chg_fmt,
            "户均持股": _vol_fmt,
            "3年P80户均": _vol_fmt,
        },
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok" and not stale,
    )


def render_insider_sell_actual_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#23 内部人90日净减持当量 · 集群逃生检测。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("insider_sell_actual")
    short = probe_label("insider_sell_actual")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):+.2f}%" if val is not None else "—"
    latest = rm.get("latest_trade_date")
    days = rm.get("days_since_last_sale")
    threat = str(rm.get("threat_urgency") or "")
    try:
        days_int = int(days) if days is not None else None
    except (TypeError, ValueError):
        days_int = None
    faded = threat == "LOW_FADED" or (days_int is not None and days_int > 30)
    ts = f"最近卖出 {latest} · 距今 {days} 天" if latest and latest != "—" else "stk_holdertrade 事件流"
    cluster = bool(rm.get("cluster_escape_triggered"))
    alert = ""
    if faded:
        alert = (
            '<p class="mt-3 text-xs font-medium text-gray-500">'
            "🌋 信号已衰减 · 最近卖出已超过 30 天 · 休眠火山（统计仍计入 90 日窗口）</p>"
        )
    elif cluster:
        alert = (
            '<p class="mt-3 text-xs font-medium text-rose-600">'
            "⚠ 集群逃生触发 · 净抛售≥1% 且独立卖出人数≥3</p>"
        )
    elif val is not None and float(val) >= 1.0:
        alert = (
            '<p class="mt-3 text-xs font-medium text-amber-700">'
            "⚠ 净减持占流通盘 ≥1% · 关注内部人抛压</p>"
        )
    t1_json = {
        "insider_sell_actual": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    def _vol_fmt(v: Any) -> str:
        try:
            f = float(v)
            if abs(f) >= 1e8:
                return f"{f/1e8:.2f}亿股"
            if abs(f) >= 1e4:
                return f"{f/1e4:.0f}万股"
            return f"{f:.0f}股"
        except (TypeError, ValueError):
            return _esc(v)

    value_color = "text-gray-500" if faded else (
        "text-rose-600" if val is not None and float(val) > 0 else "text-gray-900"
    )

    return _render_probe_card(
        probe_key="insider_sell_actual",
        title=name,
        short_label=short,
        value_html=_esc(pct_disp),
        value_color=value_color,
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle="仅实际 stk_holdertrade · 禁止减持计划公告口径",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("90日净卖量", rm.get("90d_net_sell_vol"), "signed"),
            ("占流通盘比", rm.get("net_sell_to_float_ratio"), "highlight"),
            ("独立卖出人数", rm.get("unique_sellers_count"), "neutral"),
            ("威胁紧迫度", threat or "—", "outline"),
            ("独立买入人数", rm.get("unique_buyers_count"), "outline"),
            ("90日卖出总量", rm.get("90d_sell_vol"), "outline"),
        ],
        metric_formatters={
            "90日净卖量": _vol_fmt,
            "90日卖出总量": _vol_fmt,
            "占流通盘比": lambda v: f"{float(v)*100:+.2f}%",
        },
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
        visual_cooldown=faded,
    )


def render_etf_redemption_silent_card(state: dict[str, Any]) -> str:
    """#24 静默态 · 已监控关联 ETF 但穿透冲击 <1%。"""
    mode = str(state.get("mode") or "silent")
    name = probe_indicator_name("etf_redemption_impact")
    short = probe_label("etf_redemption_impact")
    message = str(state.get("message") or "无实质 ETF 被动冲击 · 探针静默")
    theme = _probe_theme("etf_redemption_impact")
    card_cls, card_style = _card_shell("etf_redemption_impact")
    card_cls = f"{card_cls} opacity-95"

    if mode == "not_ready":
        value_html = "待同步"
        value_color = "text-amber-600 text-base"
        status_ok = False
    else:
        value_html = "静默"
        value_color = "text-gray-500 text-base"
        status_ok = True

    metric_items: list[tuple[str, Any] | tuple[str, Any, str]] = []
    if state.get("links_count") is not None:
        metric_items.append(("关联 ETF", state.get("links_count"), "neutral"))
    if state.get("latest_trade_date"):
        metric_items.append(("T-1 交易日", state.get("latest_trade_date"), "outline"))

    badge_cls = theme["badge"]
    return f"""
<article class="{card_cls}" style="{card_style}" data-probe-key="etf_redemption_impact" data-probe-mode="{_esc(mode)}">
  <header class="flex items-start justify-between gap-4">
    <div class="min-w-0 flex-1">
      <h3 class="text-base font-semibold text-gray-900 leading-snug">{_esc(name)}</h3>
      <div class="mt-1.5 flex flex-wrap items-center gap-2">
        <span class="text-xs text-gray-500">{_esc(short)}</span>
        <code class="text-[11px] font-mono px-2 py-0.5 rounded-md {badge_cls}">etf_redemption_impact</code>
        <span class="text-[10px] px-2 py-0.5 rounded-full bg-violet-50 text-violet-600 border border-violet-100">穿透监控 · T+1</span>
      </div>
      <p class="text-xs text-gray-500 mt-1">仅当个股穿透冲击 ≥1% 时升级完整 T1 卡片（剥离 ETF 总额幻觉）</p>
    </div>
    <div class="flex items-center gap-2 shrink-0">
      {_status_dot(status_ok)}
      <span class="font-bold tabular-nums {value_color}">{value_html}</span>
    </div>
  </header>
  <p class="text-sm text-gray-600 leading-relaxed mt-4">{_esc(message)}</p>
  {_render_metric_tags(metric_items)}
  <footer class="mt-5 pt-3 border-t border-gray-200">
    <p class="text-[11px] text-gray-400">来源 · Tushare fund_share + index_weight · 静默过滤已生效</p>
  </footer>
</article>
"""


def render_etf_redemption_impact_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """#24 ETF 被动资金穿透冲击当量。"""
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name("etf_redemption_impact")
    short = probe_label("etf_redemption_impact")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):+.2f}%" if val is not None else "—"
    trade_date = rm.get("inferred_trade_date")
    ts = f"T-1 数据日 {trade_date} · 08:30 盘前采集" if trade_date else "T+1 盘前 fund_share"
    urgency = str(rm.get("threat_urgency") or "")
    alert = ""
    if urgency == "ELEVATED":
        alert = (
            '<p class="mt-3 text-xs font-medium text-violet-700">'
            "⚠ 实质性被动抛压 · 穿透冲击 ≥3%</p>"
        )
    elif val is not None and abs(float(val)) >= 1.0:
        alert = (
            '<p class="mt-3 text-xs font-medium text-amber-700">'
            "⚠ 穿透冲击 ≥1% · 关注 ETF 赎回连带</p>"
        )

    t1_json = {
        "etf_redemption_impact": {
            "indicator_name": name,
            "value": val,
            "fact_statement": node.get("fact_statement"),
            "calculation_logic": node.get("calculation_logic"),
            "source": node.get("source"),
            "raw_metrics": rm,
        }
    }

    def _amt_fmt(v: Any) -> str:
        try:
            f = float(v)
            if abs(f) >= 1e8:
                return f"{f/1e8:.2f}亿"
            if abs(f) >= 1e4:
                return f"{f/1e4:.0f}万"
            return f"{f:.0f}"
        except (TypeError, ValueError):
            return _esc(v)

    value_color = "text-violet-700" if val is not None and float(val) < 0 else "text-gray-900"

    return _render_probe_card(
        probe_key="etf_redemption_impact",
        title=name,
        short_label=short,
        value_html=_esc(pct_disp),
        value_color=value_color,
        card_timing=card_timing,
        timestamp=ts if not card_timing else None,
        subtitle="穿透当量化 · 禁止将 ETF 总申赎额直接等同于个股威胁",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("核心 ETF", rm.get("top_associated_etf"), "highlight"),
            ("标的权重", rm.get("stock_weight_in_etf"), "outline"),
            ("被动抛压", rm.get("implied_passive_sell_amount"), "signed"),
            ("成交额基数", rm.get("stock_daily_amount_base"), "neutral"),
            ("穿透冲击比", rm.get("impact_ratio"), "highlight"),
            ("威胁紧迫度", urgency or "—", "outline"),
        ],
        metric_formatters={
            "标的权重": lambda v: f"{float(v)*100:.2f}%",
            "被动抛压": _amt_fmt,
            "成交额基数": _amt_fmt,
            "穿透冲击比": lambda v: f"{float(v)*100:+.2f}%",
        },
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_generic_probe_card(
    key: str,
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name(key)
    return _render_probe_card(
        probe_key=key,
        title=name,
        short_label=probe_label(key),
        value_html=_esc(val if val is not None else "—"),
        card_timing=card_timing,
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        status_ok=st == "ok",
    )


def render_layer_b_prerequisite_banner() -> str:
    """未填建仓日：禁止展示历史/旧版缓存指标（no-mock）。"""
    return """
<article class="bg-white border border-amber-200 rounded-xl shadow-sm px-5 py-4 mb-4">
  <p class="text-sm font-semibold text-gray-900">层 B 未启用</p>
  <p class="text-sm text-gray-600 mt-2 leading-relaxed">请先在层 A 填写<strong class="text-gray-900">建仓时间</strong>并点「保存标的基础数据」。
  ATR 止盈须以建仓日为峰值起点；未配置前<strong class="text-gray-900">不展示</strong>任何指标数值（禁止沿用旧缓存冒充持仓监控）。</p>
</article>
"""


def render_degraded_probes(hints: list[str]) -> str:
    if not hints:
        return ""
    items = "".join(f"<li class='py-0.5 text-gray-600'>{_esc(h)}</li>" for h in hints)
    return f"""
<article class="bg-white border border-red-200 rounded-xl shadow-sm px-5 py-4 mb-4">
  <p class="text-sm font-semibold text-gray-900">探针降级 / 未就绪</p>
  <ul class="mt-2 text-xs list-disc list-inside text-gray-600">{items}</ul>
</article>
"""


def _quote_intraday_watermark(sync: dict[str, Any] | None, symbol: str) -> str | None:
    if not sync:
        return None
    sym = symbol.zfill(6)[-6:]
    for w in sync.get("watermarks") or []:
        if w.get("job_id") == "quote-intraday" and w.get("symbol") in (sym, "*"):
            return w.get("last_success_at_cst") or w.get("last_success_at")
    return None


def render_probe_domain(
    domain: dict[str, Any],
    *,
    title: str,
    accent: str,
    empty_hint: str = "尚无 T1 数据 · 点击下方「立即跑今日体检」",
    symbol: str = "",
    sync: dict[str, Any] | None = None,
    event_probe_states: dict[str, dict[str, Any]] | None = None,
    timing_map: dict[str, ProbeCardTiming] | None = None,
) -> str:
    _ = accent  # 保留签名兼容；新设计不再使用彩色 accent 包裹
    event_probe_states = event_probe_states or {}
    domain = domain or {}
    if not domain and not event_probe_states:
        return f"""
<section class="{_SECTION}">
  <h4 class="text-sm font-semibold text-gray-900 pb-2 mb-3 border-b border-gray-200">{_esc(title)}</h4>
  <p class="text-sm text-gray-500">{_esc(empty_hint)}</p>
</section>
"""
    quote_at = _quote_intraday_watermark(sync, symbol) if symbol else None
    timing_map = timing_map or {}
    cards: list[str] = []
    for k in PROBE_KEYS:
        node = domain.get(k)
        card_timing = timing_map.get(k)
        if k == "block_trade_discount" and not isinstance(node, dict):
            bt_state = event_probe_states.get("block_trade_discount")
            if bt_state and bt_state.get("mode") != "active":
                cards.append(render_block_trade_silent_card(bt_state))
            continue
        if k == "etf_redemption_impact" and not isinstance(node, dict):
            etf_state = event_probe_states.get("etf_redemption_impact")
            if etf_state and etf_state.get("mode") != "active":
                cards.append(render_etf_redemption_silent_card(etf_state))
            continue
        if not isinstance(node, dict):
            continue
        if k == "qmt_atr_trailing":
            cards.append(
                render_qmt_atr_trailing_card(node, quote_job_at=quote_at, card_timing=card_timing)
            )
        elif k == "volume_price_div":
            cards.append(render_volume_price_div_card(node, card_timing=card_timing))
        elif k == "smart_money_flow":
            cards.append(render_smart_money_flow_card(node, card_timing=card_timing))
        elif k == "level2_super_order":
            cards.append(render_level2_super_order_card(node, card_timing=card_timing))
        elif k == "margin_short_skew":
            cards.append(render_margin_short_skew_card(node, card_timing=card_timing))
        elif k == "turnover_acceleration":
            cards.append(render_turnover_acceleration_card(node, card_timing=card_timing))
        elif k == "block_trade_discount":
            cards.append(render_block_trade_discount_card(node, card_timing=card_timing))
        elif k == "retail_concentration":
            cards.append(render_retail_concentration_card(node, card_timing=card_timing))
        elif k == "insider_sell_actual":
            cards.append(render_insider_sell_actual_card(node, card_timing=card_timing))
        elif k == "etf_redemption_impact":
            cards.append(render_etf_redemption_impact_card(node, card_timing=card_timing))
        elif k == "tech_beta_correlation":
            cards.append(render_tech_beta_correlation_card(node, card_timing=card_timing))
        else:
            cards.append(render_generic_probe_card(k, node, card_timing=card_timing))
    body = "".join(cards) or '<p class="text-sm text-gray-500">尚无 T1 数据</p>'
    return f"""
<section class="{_SECTION}">
  <h4 class="text-sm font-semibold text-gray-900 pb-2 mb-1 border-b border-gray-200">{_esc(title)}</h4>
  <div class="flex flex-col gap-6 mt-4">{body}</div>
</section>
"""
