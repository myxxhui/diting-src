"""执行中工作区 HTML 片段渲染 · 现代 SaaS 指标卡片设计系统。

[Ref: 28_ §4 · executing_routes]
"""
from __future__ import annotations

import html as _html
import json
from typing import Any, Callable

from apps.copilot.db.datetime_util import utc_naive_to_shanghai_display
from apps.copilot.modules.executing.indicator_nodes import (
    SOURCE_INTRADAY_TICK,
    raw_metrics_for_display,
)
from apps.copilot.modules.executing.profile import PROBE_KEYS
from apps.copilot.modules.executing.probe_labels import probe_indicator_name, probe_label

# ── Design tokens（Tailwind · 对齐 #F9FAFB / #FFFFFF / #E5E7EB / #10B981）──
_CARD = (
    "probe-indicator-card bg-white border border-gray-200 rounded-xl "
    "shadow-sm hover:shadow-md transition-shadow p-6 mb-4"
)
_SECTION = "executing-probe-section mb-6"
_TAG = (
    "inline-flex items-center justify-between gap-3 min-w-[7rem] "
    "px-2.5 py-1.5 rounded border border-gray-200 bg-gray-50"
)
_FORMULA = (
    "mt-4 mb-1 px-4 py-3 rounded-r-md bg-gray-100 border-l-4 "
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


def _render_metric_tags(
    items: list[tuple[str, Any]],
    *,
    formatters: dict[str, Callable[[Any], str]] | None = None,
) -> str:
    formatters = formatters or {}
    tags: list[str] = []
    for label, raw in items:
        if raw is None or raw == "":
            continue
        if label in formatters:
            disp = formatters[label](raw)
        else:
            disp = _esc(raw)
        tags.append(
            f'<div class="{_TAG}">'
            f'<span class="text-[11px] text-gray-400">{_esc(label)}</span>'
            f'<span class="text-sm font-semibold text-gray-900">{disp}</span>'
            f"</div>"
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
    subtitle: str | None = None,
    fact_statement: str = "",
    calculation_logic: str = "",
    source: str = "",
    metric_items: list[tuple[str, Any]] | None = None,
    metric_formatters: dict[str, Callable[[Any], str]] | None = None,
    formula_accent: str = "border-indigo-500",
    alert_html: str = "",
    t1_json: dict[str, Any] | None = None,
    status_ok: bool = True,
) -> str:
    """统一指标卡片：Header · 描述 · 公式区 · Tag 栏 · 来源 Footer。"""
    ts_line = (
        f'<p class="text-[11px] text-gray-400 mb-3 font-mono">{_esc(timestamp)}</p>'
        if timestamp
        else ""
    )
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
            f'<div class="{_FORMULA} {formula_accent}">{_esc(calculation_logic)}</div>'
        )
    tags_html = _render_metric_tags(metric_items or [], formatters=metric_formatters)
    footer_json = _render_t1_json_details(probe_key, t1_json) if t1_json else ""
    source_line = _esc(source or "—")

    return f"""
<article class="{_CARD}" data-probe-key="{_esc(probe_key)}">
  {ts_line}
  <header class="flex items-start justify-between gap-4">
    <div class="min-w-0 flex-1">
      <h3 class="text-base font-semibold text-gray-900 leading-snug">{_esc(title)}</h3>
      <div class="mt-1.5 flex flex-wrap items-center gap-2">
        <span class="text-xs text-gray-500">{_esc(short_label)}</span>
        <code class="text-[11px] font-mono text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">{_esc(probe_key)}</code>
      </div>
      {sub_line}
    </div>
    <div class="flex items-center gap-2 shrink-0">
      {_status_dot(status_ok)}
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
        timestamp=_qmt_timestamp_line(rm, quote_job_at=quote_job_at),
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("ATR₂₀", rm.get("atr_20")),
            ("峰值价", rm.get("peak_price")),
            ("现价", rm.get("current_price")),
            ("快照时间", rm.get("last_tick_time")),
        ],
        formula_accent="border-orange-500",
        status_ok=st == "ok",
    )


def render_volume_price_div_card(node: dict[str, Any]) -> str:
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
        timestamp=ts,
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("高位阴线量", rm.get("high_zone_down_vol")),
            ("高位阳线量", rm.get("high_zone_up_vol")),
            ("高位阈值价", rm.get("high_zone_threshold_price")),
            ("区间最高", rm.get("period_max")),
            ("区间最低", rm.get("period_min")),
            ("全样本量比", rm.get("global_vol_ratio")),
        ],
        formula_accent="border-violet-500",
        status_ok=st == "ok",
    )


def render_smart_money_flow_card(node: dict[str, Any]) -> str:
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
        timestamp=ts,
        subtitle=f"近 3 交易日主力（特大单+大单）相对自由流通盘 · {direction}",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("3日主力净股数", rm.get("3d_smart_money_net_vol")),
            ("3日散户净股数", rm.get("3d_retail_net_vol")),
            ("自由流通股本", rm.get("free_float_shares")),
        ],
        formula_accent="border-emerald-500",
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_level2_super_order_card(node: dict[str, Any]) -> str:
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
        subtitle="仅特大单(elg) · 120 交易日历史分位",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("今日特大单净额(元)", rm.get("current_net_elg_amount")),
            ("今日特大单买入(元)", rm.get("current_buy_elg_amount")),
            ("今日特大单卖出(元)", rm.get("current_sell_elg_amount")),
            ("120日均值(元)", rm.get("120d_mean_net_amount")),
            ("120日P95(元)", rm.get("120d_p95_threshold")),
            ("120日P05(元)", rm.get("120d_p05_threshold")),
            ("回看窗口(日)", rm.get("lookback_window_days")),
        ],
        formula_accent="border-amber-500",
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_margin_short_skew_card(node: dict[str, Any]) -> str:
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
        timestamp=ts,
        subtitle=f"融资余额/流通市值 · 250 日历史分位 · 占盘 {ratio_pct}",
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("融资余额(元)", rm.get("margin_balance")),
            ("融券余额(元)", rm.get("short_balance")),
            ("融资买入额(元)", rm.get("margin_purchase_today")),
            ("杠杆占流通盘", rm.get("margin_to_float_ratio")),
            ("250日均占盘比", rm.get("250d_mean_ratio")),
            ("披露滞后(日)", rm.get("settlement_lag_days")),
        ],
        metric_formatters={
            "杠杆占流通盘": _ratio_fmt,
            "250日均占盘比": _ratio_fmt,
        },
        formula_accent="border-rose-500",
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_turnover_acceleration_card(node: dict[str, Any]) -> str:
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
        timestamp=ts,
        subtitle=(
            f"自由流通换手率 turnover_rate_f · 120日加速分位 {pct}%"
            if pct is not None
            else "自由流通换手率 · 相对自身 20 日均值加速"
        ),
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=[
            ("今日换手(小数)", rm.get("current_turnover_f")),
            ("20日均换手", rm.get("20d_mean_turnover_f")),
            ("120日加速分位", rm.get("120d_accel_percentile")),
            ("量比", rm.get("volume_ratio")),
        ],
        metric_formatters={
            "今日换手(小数)": _pct_fmt,
            "20日均换手": _pct_fmt,
            "120日加速分位": lambda v: f"{float(v):.1f}%",
        },
        formula_accent="border-sky-500",
        alert_html=alert,
        t1_json=t1_json,
        status_ok=st == "ok",
    )


def render_generic_probe_card(key: str, node: dict[str, Any]) -> str:
    val = node.get("value")
    st = _indicator_status(node)
    name = node.get("indicator_name") or probe_indicator_name(key)
    return _render_probe_card(
        probe_key=key,
        title=name,
        short_label=probe_label(key),
        value_html=_esc(val if val is not None else "—"),
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
) -> str:
    _ = accent  # 保留签名兼容；新设计不再使用彩色 accent 包裹
    if not domain:
        return f"""
<section class="{_SECTION}">
  <h4 class="text-sm font-semibold text-gray-900 pb-2 mb-3 border-b border-gray-200">{_esc(title)}</h4>
  <p class="text-sm text-gray-500">{_esc(empty_hint)}</p>
</section>
"""
    quote_at = _quote_intraday_watermark(sync, symbol) if symbol else None
    cards: list[str] = []
    for k in PROBE_KEYS:
        node = domain.get(k)
        if not isinstance(node, dict):
            continue
        if k == "qmt_atr_trailing":
            cards.append(render_qmt_atr_trailing_card(node, quote_job_at=quote_at))
        elif k == "volume_price_div":
            cards.append(render_volume_price_div_card(node))
        elif k == "smart_money_flow":
            cards.append(render_smart_money_flow_card(node))
        elif k == "level2_super_order":
            cards.append(render_level2_super_order_card(node))
        elif k == "margin_short_skew":
            cards.append(render_margin_short_skew_card(node))
        elif k == "turnover_acceleration":
            cards.append(render_turnover_acceleration_card(node))
        else:
            cards.append(render_generic_probe_card(k, node))
    body = "".join(cards) or '<p class="text-sm text-gray-500">尚无 T1 数据</p>'
    return f"""
<section class="{_SECTION}">
  <h4 class="text-sm font-semibold text-gray-900 pb-2 mb-1 border-b border-gray-200">{_esc(title)}</h4>
  <div class="mt-4 space-y-0">{body}</div>
</section>
"""
