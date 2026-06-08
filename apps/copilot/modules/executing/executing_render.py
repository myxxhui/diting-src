"""执行中工作区 HTML 片段渲染。

[Ref: 28_ §4 · executing_routes]
"""
from __future__ import annotations

import html as _html
from typing import Any

from apps.copilot.db.datetime_util import utc_naive_to_shanghai_display
from apps.copilot.modules.executing.indicator_nodes import (
    SOURCE_INTRADAY_TICK,
    raw_metrics_for_display,
)
from apps.copilot.modules.executing.profile import PROBE_KEYS
from apps.copilot.modules.executing.probe_labels import probe_indicator_name, probe_label


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
    # ISO/T 分隔且带微秒 → 视为 DB UTC 水位
    if "T" in text:
        return utc_naive_to_shanghai_display(text) or text
    return text


def _is_intraday_node(node: dict[str, Any]) -> bool:
    rm = raw_metrics_for_display(node)
    src = str(node.get("source") or "")
    return bool(rm.get("last_tick_time")) or SOURCE_INTRADAY_TICK in src


def render_hot_data_timeline(
    node: dict[str, Any] | None,
    *,
    quote_job_at: str | None = None,
) -> str:
    """层 B 热数据时间线：盘中 tick 时间 / 盘后收盘日 / 采集水位。"""
    if not node or not isinstance(node, dict):
        return """
<div class="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-2 mb-3 text-xs text-gray-500">
  <span class="font-medium text-gray-700">热数据时间线</span>
  <span class="ml-2">暂无 ATR 指标 · 填写建仓日并刷新</span>
</div>
"""
    rm = raw_metrics_for_display(node)
    intraday = _is_intraday_node(node)
    tick = rm.get("last_tick_time")
    bar_as_of = rm.get("bar_as_of")

    quote_cst = _format_cst_time(quote_job_at)

    if intraday and tick:
        mode_cls = "bg-emerald-100 text-emerald-800 border-emerald-200"
        mode_txt = "盘中热数据"
        time_main = _esc(f"北京时间 {_format_cst_time(str(tick)) or tick}")
        sub = "Redis Tick · T0 穿透存活"
    elif bar_as_of:
        mode_cls = "bg-slate-100 text-slate-700 border-slate-200"
        mode_txt = "盘后 PG 日K"
        time_main = _esc(f"K线交易日 {bar_as_of}")
        if quote_cst:
            sub = (
                f"最近热采集 北京时间 {quote_cst}（Cron 任务时刻，非交易所收盘时刻）"
            )
        else:
            sub = "盘中 Redis 未命中 · 现价取自 PG 日K 收盘价"
    else:
        mode_cls = "bg-amber-50 text-amber-800 border-amber-200"
        mode_txt = "数据模式未知"
        time_main = "—"
        sub = "缺少 tick 与收盘日元数据"

    return f"""
<div class="rounded-lg border border-sky-100 bg-sky-50/40 px-3 py-2 mb-3">
  <div class="flex flex-wrap items-center gap-2 text-xs">
    <span class="font-semibold text-sky-900">热数据时间线</span>
    <span class="px-1.5 py-0.5 rounded border text-[10px] font-medium {mode_cls}">{mode_txt}</span>
    <span class="font-mono text-sky-950">{time_main}</span>
    <span class="text-gray-500">{_esc(sub)}</span>
  </div>
  <p class="text-[10px] text-gray-400 mt-1">A 股连续竞价 15:00 收盘；16:00 PG 落正式日K</p>
</div>
"""


def render_qmt_atr_trailing_card(
    node: dict[str, Any],
    *,
    quote_job_at: str | None = None,
) -> str:
    """#15 ATR 止盈 · 名牌 + 客观事实 + raw_metrics 抽屉。"""
    val = node.get("value")
    st = _indicator_status(node)
    dot = "🟢" if st == "ok" else "🔴"
    name = node.get("indicator_name") or probe_indicator_name("qmt_atr_trailing")
    short = probe_label("qmt_atr_trailing")
    rm = raw_metrics_for_display(node)

    metric_labels = (
        ("ATR₂₀", "atr_20"),
        ("峰值价", "peak_price"),
        ("现价", "current_price"),
        ("快照时间", "last_tick_time"),
    )
    audit_rows = []
    for lbl, fld in metric_labels:
        v = rm.get(fld)
        if v is not None and v != "":
            audit_rows.append(
                f"<span class='inline-flex gap-1 px-2 py-0.5 rounded bg-gray-50 border "
                f"border-gray-100'><span class='text-gray-500'>{lbl}</span>"
                f"<strong class='text-gray-800'>{_esc(v)}</strong></span>"
            )
    audit_html = (
        f"<div class='flex flex-wrap gap-1.5 mt-2'>{''.join(audit_rows)}</div>"
        if audit_rows
        else ""
    )
    rm = raw_metrics_for_display(node)
    tick = rm.get("last_tick_time")
    bar_as_of = rm.get("bar_as_of")
    quote_cst = _format_cst_time(quote_job_at)
    if tick:
        tick_line = (
            f"<p class='text-[11px] text-emerald-800 mb-2 font-mono'>"
            f"⏱ 热数据快照（北京时间）<strong>{_esc(_format_cst_time(str(tick)) or tick)}</strong></p>"
        )
    elif bar_as_of:
        extra = (
            f" · 最近采集（北京时间）{_esc(quote_cst)}"
            if quote_cst
            else ""
        )
        tick_line = (
            f"<p class='text-[11px] text-slate-600 mb-2'>"
            f"⏱ K线交易日 <strong>{_esc(bar_as_of)}</strong>{extra}</p>"
        )
    else:
        tick_line = ""

    return f"""
<div class="rounded-lg border border-orange-100 bg-orange-50/30 p-3 mb-2">
  {tick_line}
  <div class="flex flex-wrap items-center gap-2 mb-1">
    <span class="text-sm font-semibold text-gray-900">{_esc(name)}</span>
    <span class="text-[10px] text-gray-500">({short})</span>
    <span class="text-[10px] font-mono text-gray-400">qmt_atr_trailing</span>
    <span class="text-sm ml-auto">{dot} <strong>{_esc(val if val is not None else '—')}</strong> 倍</span>
  </div>
  <p class="text-xs text-gray-800 leading-relaxed">{_esc(node.get('fact_statement', ''))}</p>
  <p class="text-[11px] text-gray-500 mt-1 font-mono">{_esc(node.get('calculation_logic', ''))}</p>
  <p class="text-[10px] text-gray-400 mt-1">来源：{_esc(node.get('source', '—'))}</p>
  {audit_html}
</div>
"""


def render_volume_price_div_card(node: dict[str, Any]) -> str:
    """#16 15分钟高位量价背离 · 可溯源 raw_metrics 抽屉。"""
    val = node.get("value")
    st = _indicator_status(node)
    dot = "🟢" if st == "ok" else "🔴"
    name = node.get("indicator_name") or probe_indicator_name("volume_price_div")
    short = probe_label("volume_price_div")
    rm = raw_metrics_for_display(node)

    metric_labels = (
        ("高位阴线量", "high_zone_down_vol"),
        ("高位阳线量", "high_zone_up_vol"),
        ("高位阈值价", "high_zone_threshold_price"),
        ("区间最高", "period_max"),
        ("区间最低", "period_min"),
        ("全样本量比", "global_vol_ratio"),
        ("末根K线", "last_bar_datetime"),
    )
    audit_rows = []
    for lbl, fld in metric_labels:
        v = rm.get(fld)
        if v is not None and v != "":
            audit_rows.append(
                f"<span class='inline-flex gap-1 px-2 py-0.5 rounded bg-violet-50 border "
                f"border-violet-100'><span class='text-violet-600'>{lbl}</span>"
                f"<strong class='text-violet-950'>{_esc(v)}</strong></span>"
            )
    audit_html = (
        f"<div class='flex flex-wrap gap-1.5 mt-2'>{''.join(audit_rows)}</div>"
        if audit_rows
        else ""
    )
    last_bar = rm.get("last_bar_datetime")
    time_line = (
        f"<p class='text-[11px] text-violet-800 mb-2 font-mono'>"
        f"⏱ 15m 末根 <strong>{_esc(last_bar)}</strong></p>"
        if last_bar
        else ""
    )

    return f"""
<div class="rounded-lg border border-violet-100 bg-violet-50/30 p-3 mb-2">
  {time_line}
  <div class="flex flex-wrap items-center gap-2 mb-1">
    <span class="text-sm font-semibold text-gray-900">{_esc(name)}</span>
    <span class="text-[10px] text-gray-500">({short})</span>
    <span class="text-[10px] font-mono text-gray-400">volume_price_div</span>
    <span class="text-sm ml-auto">{dot} <strong>{_esc(val if val is not None else '—')}</strong></span>
  </div>
  <p class="text-xs text-gray-800 leading-relaxed">{_esc(node.get('fact_statement', ''))}</p>
  <p class="text-[11px] text-gray-500 mt-1 font-mono">{_esc(node.get('calculation_logic', ''))}</p>
  <p class="text-[10px] text-gray-400 mt-1">来源：{_esc(node.get('source', '—'))}</p>
  {audit_html}
</div>
"""


def render_smart_money_flow_card(node: dict[str, Any]) -> str:
    """#17 L2 主力大单 · 3 日 Smart Money Delta。"""
    val = node.get("value")
    st = _indicator_status(node)
    dot = "🟢" if st == "ok" else "🔴"
    name = node.get("indicator_name") or probe_indicator_name("smart_money_flow")
    short = probe_label("smart_money_flow")
    rm = raw_metrics_for_display(node)
    pct_disp = f"{float(val):+.4f}%" if val is not None else "—"
    direction = "净流入" if val is not None and float(val) >= 0 else "净流出"

    metric_labels = (
        ("3日主力净股数", "3d_smart_money_net_vol"),
        ("3日散户净股数", "3d_retail_net_vol"),
        ("自由流通股本", "free_float_shares"),
        ("数据截止日", "last_update_date"),
    )
    audit_rows = []
    for lbl, fld in metric_labels:
        v = rm.get(fld)
        if v is not None and v != "":
            audit_rows.append(
                f"<span class='inline-flex gap-1 px-2 py-0.5 rounded bg-violet-50 border "
                f"border-violet-100'><span class='text-gray-500'>{lbl}</span>"
                f"<strong class='text-gray-800'>{_esc(v)}</strong></span>"
            )
    audit_html = (
        f"<div class='flex flex-wrap gap-1.5 mt-2'>{''.join(audit_rows)}</div>"
        if audit_rows
        else ""
    )

    return f"""
<div class="rounded-lg border border-violet-100 bg-violet-50/30 p-3 mb-2">
  <div class="flex flex-wrap items-center gap-2 mb-1">
    <span class="text-sm font-semibold text-gray-900">{_esc(name)}</span>
    <span class="text-[10px] text-gray-500">({short})</span>
    <span class="text-[10px] font-mono text-gray-400">smart_money_flow</span>
    <span class="text-sm ml-auto">{dot} <strong>{_esc(pct_disp)}</strong></span>
  </div>
  <p class="text-xs text-gray-600 mb-1">近3交易日主力（特大单+大单）相对自由流通盘 · {direction}</p>
  <p class="text-xs text-gray-800 leading-relaxed">{_esc(node.get('fact_statement', ''))}</p>
  <p class="text-[11px] text-gray-500 mt-1 font-mono">{_esc(node.get('calculation_logic', ''))}</p>
  <p class="text-[10px] text-gray-400 mt-1">来源：{_esc(node.get('source', '—'))}</p>
  {audit_html}
</div>
"""


def render_generic_probe_card(key: str, node: dict[str, Any]) -> str:
    val = node.get("value")
    st = _indicator_status(node)
    dot = "🟢" if st == "ok" else "🔴"
    name = node.get("indicator_name") or probe_indicator_name(key)
    return f"""
<div class="rounded-lg border border-gray-100 bg-white p-3 mb-2">
  <div class="flex flex-wrap items-center gap-2 mb-1">
    <span class="text-sm font-semibold text-gray-900">{_esc(name)}</span>
    <span class="text-[10px] font-mono text-gray-400">{_esc(key)}</span>
    <span class="text-sm">{dot} <strong>{_esc(val if val is not None else '—')}</strong></span>
  </div>
  <p class="text-xs text-gray-700">{_esc(node.get('fact_statement', ''))}</p>
  <p class="text-[11px] text-gray-500 mt-1">{_esc(node.get('calculation_logic', ''))}</p>
  <p class="text-[10px] text-gray-400 mt-1">来源：{_esc(node.get('source', '—'))}</p>
</div>
"""


def render_layer_b_prerequisite_banner() -> str:
    """未填建仓日：禁止展示历史/旧版缓存指标（no-mock）。"""
    return """
<div class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-900">
  <p class="font-medium">层 B 未启用</p>
  <p class="mt-1">请先在层 A 填写<strong>建仓时间</strong>并点「保存标的基础数据」。
  ATR止盈 须以建仓日为峰值起点；未配置前<strong>不展示</strong>任何指标数值（禁止沿用旧缓存冒充持仓监控）。</p>
</div>
"""


def render_degraded_probes(hints: list[str]) -> str:
    if not hints:
        return ""
    items = "".join(f"<li class='py-0.5'>{_esc(h)}</li>" for h in hints)
    return f"""
<div class="rounded-lg border border-red-100 bg-red-50 px-3 py-2 mb-3 text-xs text-red-800">
  <p class="font-medium">探针降级 / 未就绪</p>
  <ul class="mt-1 list-disc list-inside">{items}</ul>
</div>
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
    if not domain:
        return f"""
<div class="border-l-4 border-{accent}-500 pl-3 mb-4">
  <h4 class="font-semibold mb-2 text-sm text-gray-800">{_esc(title)}</h4>
  <p class="text-xs text-gray-500">{_esc(empty_hint)}</p>
</div>
"""
    quote_at = _quote_intraday_watermark(sync, symbol) if symbol else None
    cards = []
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
        else:
            cards.append(render_generic_probe_card(k, node))
    body = "".join(cards) or "<p class='text-xs text-gray-500'>尚无 T1 数据</p>"
    return f"""
<div class="border-l-4 border-{accent}-500 pl-3 mb-4">
  <h4 class="font-semibold mb-2 text-sm text-gray-800">{_esc(title)}</h4>
  {body}
</div>
"""
