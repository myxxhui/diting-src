"""JL3 探针前端卡片 · 统一模板渲染器。

所有 JL3 探针须按本模块契约产出 ``node.raw_metrics.card_strategy``，并由
:func:`render_jl3_probe_card` 渲染（禁止在 ``executing_render`` 再写探针专属 HTML）。

[Ref: 28_ §6 · JL3 蓝域折叠卡片 · fii_twse_cloud 样板]

card_strategy 契约
------------------

必填::

    panel_title: str          # 折叠栏标题（如「三目标实战面板 · 601138 影子定价锚」）
    help_html: str            # 探针级 ? 说明（HTML 片段，服务端生成）
    signal: {
        status: green|yellow|red,
        label: str,
        summary: str,
        reasons: list[str],    # 可选
    }
    sections: list[Section]

Section（至少一项）::

    title: str
    subtitle: str             # 可选
    table: TableSpec          # 与 custom_html 二选一或并存
    custom_html: str          # 探针自定义块（仅服务端 build_card_strategy 产出）
    footnote: str             # 可选 · section 底部说明

TableSpec::

    rows: list[dict]          # 每行含 period / mom_pct / 数值列
    value_key: str
    value_label: str
    billion_key: str | None   # 可选 · 有则展示「X 亿」
    column_helps: dict[str, str]   # 列 key → ? 说明 HTML
    freshness_note_html: str       # 可选 · 表下数据滞后说明

indicator_node 还须含：value / value_detail / fact_statement / calculation_logic /
source / t1_json（与 JL4 卡片 footer 一致）。

新增 JL3 探针 checklist
-----------------------
1. ``l3/<probe>/card_strategy.py`` 实现 ``build_card_strategy(...) -> dict`` 符合上表
2. ``indicator_node.py`` 写入 ``raw_metrics["card_strategy"]``
3. ``l3_probe_registry`` 注册探针 · **勿** 在 ``render_l3_probe_domain`` 写 if key 分支
4. 单测：``build_card_strategy`` 结构 + ``render_jl3_probe_card`` HTML 关键字
"""
from __future__ import annotations

import html as _html
import json
from typing import Any, Callable

from apps.copilot.modules.executing.indicator_nodes import raw_metrics_for_display
from apps.copilot.modules.executing.probe_card_timing import ProbeCardTiming
from apps.copilot.modules.executing.probe_labels import probe_indicator_name, probe_label

# 延迟导入避免 executing_render ↔ jl3_card_render 循环
_render_probe_card: Callable[..., str] | None = None


def _get_render_probe_card() -> Callable[..., str]:
    global _render_probe_card
    if _render_probe_card is None:
        from apps.copilot.modules.executing.executing_render import _render_probe_card as rpc

        _render_probe_card = rpc
    return _render_probe_card


def _esc(v: Any) -> str:
    return _html.escape(str(v)) if v is not None else ""


def render_inline_help_btn(help_html: str, *, title: str = "说明") -> str:
    """列头/字段旁 ? 注释（stopPropagation 防误触外层标的折叠卡）。"""
    if not help_html:
        return ""
    return f"""
<details class="inline-block relative align-middle ml-0.5">
  <summary class="executing-fold-summary list-none cursor-pointer w-4 h-4 rounded-full bg-gray-100 text-gray-500 text-[10px] font-bold inline-flex items-center justify-center hover:bg-blue-100 hover:text-blue-700 select-none" title="{_esc(title)}" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()">?</summary>
  <div class="absolute z-30 left-0 sm:left-auto sm:right-0 mt-1 w-64 sm:w-80 p-3 rounded-lg border border-gray-200 bg-white shadow-lg text-[11px] text-gray-600 leading-relaxed">{help_html}</div>
</details>"""


def _render_table_header_label(label: str, help_html: str = "") -> str:
    inner = _esc(label)
    if help_html:
        inner = (
            f'<span class="inline-flex items-center gap-0.5">'
            f"{inner}{render_inline_help_btn(help_html, title=label)}</span>"
        )
    return inner


def format_mom_cell(mom: Any) -> str:
    if mom is None or mom == "":
        return "—"
    try:
        v = float(mom)
    except (TypeError, ValueError):
        return _esc(mom)
    cls = "text-red-600" if v > 0 else "text-emerald-600" if v < 0 else "text-gray-600"
    return f'<span class="font-semibold tabular-nums {cls}">{v:+.1f}%</span>'


def render_jl3_monthly_table(table: dict[str, Any]) -> str:
    """标准 JL3 月序列表（月份 · 数值列 · MoM · 可选新鲜度脚注）。"""
    rows = table.get("rows") or []
    if not rows:
        return '<p class="text-xs text-gray-400">暂无序列</p>'
    value_key = str(table.get("value_key") or "value")
    value_label = str(table.get("value_label") or "数值")
    billion_key = table.get("billion_key")
    column_helps = table.get("column_helps") or {}
    body: list[str] = []
    for r in rows:
        period = _esc(r.get("period", ""))
        mom = format_mom_cell(r.get("mom_pct"))
        val = r.get(value_key)
        if billion_key and r.get(billion_key) is not None:
            val_txt = f"{r[billion_key]} 亿"
        elif val is not None:
            val_txt = _esc(val)
        else:
            val_txt = "—"
        body.append(
            f'<tr class="border-t border-gray-100">'
            f'<td class="py-1.5 pr-3 text-gray-600 font-mono text-[11px]">{period}</td>'
            f'<td class="py-1.5 pr-3 text-gray-800 text-[11px]">{_esc(val_txt)}</td>'
            f'<td class="py-1.5 text-right text-[11px]">{mom}</td>'
            f"</tr>"
        )
    val_header = _render_table_header_label(
        value_label,
        column_helps.get(value_key) or column_helps.get("value") or "",
    )
    mom_header = _render_table_header_label(
        "MoM",
        column_helps.get("mom_pct") or column_helps.get("mom") or "",
    )
    freshness = table.get("freshness_note_html") or ""
    if freshness:
        freshness = f'<div class="mt-2">{freshness}</div>'
    return (
        f'<div class="overflow-x-auto">'
        f'<table class="w-full text-left mt-2 min-w-[16rem]">'
        f'<thead><tr class="text-[10px] text-gray-400 uppercase tracking-wide">'
        f'<th class="pb-1 font-medium">月份</th>'
        f'<th class="pb-1 font-medium">{val_header}</th>'
        f'<th class="pb-1 font-medium text-right">{mom_header}</th></tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
        f"{freshness}</div>"
    )


def render_jl3_goal3_corner_chip(g3: dict[str, Any]) -> str:
    """目标三发令 · 卡面右上角紧凑状态 + ? 规则说明。"""
    status = str(g3.get("status") or "yellow")
    label = str(g3.get("label") or "观察区")
    summary = str(g3.get("summary") or "")
    reasons = g3.get("reasons") or []
    palette = {
        "green": "bg-emerald-100 border-emerald-400 text-emerald-950 shadow-sm shadow-emerald-100",
        "yellow": "bg-amber-100 border-amber-400 text-amber-950 shadow-sm shadow-amber-100",
        "red": "bg-red-100 border-red-400 text-red-950 shadow-sm shadow-red-100",
    }
    icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(status, "🟡")
    shell = palette.get(status, palette["yellow"])
    reason_items = "".join(f"<li>{_esc(r)}</li>" for r in reasons[:5])
    help_html = f"""
<p class="font-semibold text-gray-800">目标三 · 程序化发令枪</p>
<p class="mt-1 text-[11px] text-gray-600">依据<strong>云端网路推导 MoM</strong>（非合并总营收 MoM）判定进攻 / 防守 / 观察。</p>
<ul class="list-disc pl-4 space-y-1 mt-2 text-[11px]">
  <li>🟢 <strong>进攻</strong>：连续两月云端 MoM &gt; 15%，且 IR 四板块 MoM 排名第 1</li>
  <li>🔴 <strong>防守</strong>：IR 出现持平/衰退词，或云端 MoM 排名跌出前二</li>
  <li>🟡 <strong>观察</strong>：以上皆不满足</li>
</ul>
<p class="mt-2 text-[11px]"><strong>当前摘要：</strong>{_esc(summary)}</p>
<ul class="list-disc pl-4 mt-1 space-y-0.5 text-[11px] text-gray-700">{reason_items}</ul>
"""
    help_btn = render_inline_help_btn(help_html.strip(), title="目标三发令规则")
    return (
        f'<div class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-[11px] font-bold {shell}" '
        f'onclick="event.stopPropagation()">'
        f'<span class="text-sm leading-none">{icon}</span>'
        f'<span class="truncate max-w-[5.5rem]">{_esc(label)}</span>'
        f"{help_btn}</div>"
    )


def render_jl3_signal_badge(status: str, label: str, summary: str) -> str:
    palette = {
        "green": ("bg-emerald-50 border-emerald-200 text-emerald-800", "🟢"),
        "yellow": ("bg-amber-50 border-amber-200 text-amber-900", "🟡"),
        "red": ("bg-red-50 border-red-200 text-red-800", "🔴"),
    }
    shell, icon = palette.get(status, palette["yellow"])
    return (
        f'<div class="flex items-start gap-3 p-3 rounded-lg border {shell}">'
        f'<span class="text-lg leading-none mt-0.5">{icon}</span>'
        f'<div class="min-w-0"><p class="text-sm font-semibold">{_esc(label)}</p>'
        f'<p class="text-xs mt-0.5 opacity-90">{_esc(summary)}</p></div></div>'
    )


def render_fii_cloud_primary_block(
    rows: list[dict[str, Any]],
    *,
    signal: dict[str, Any] | None = None,
) -> str:
    """卡面主区 · 云端网路近五月推导营收 + 月环比（始终可见）。"""
    if not rows:
        return '<p class="text-xs text-gray-400 mt-3">暂无云端近月序列 · 等待 l3-fii-twse-monthly</p>'
    from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import FII_COL_HELP_CLOUD

    sig = signal or {}
    status = str(sig.get("status") or "yellow")
    sig_palette = {
        "green": "bg-emerald-50 border-emerald-200 text-emerald-900",
        "yellow": "bg-amber-50 border-amber-200 text-amber-950",
        "red": "bg-red-50 border-red-200 text-red-900",
    }
    sig_cls = sig_palette.get(status, sig_palette["yellow"])
    sig_icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(status, "🟡")
    reasons = sig.get("reasons") or []
    reason_line = _esc(reasons[0]) if reasons else _esc(sig.get("summary") or "")

    body: list[str] = []
    for r in rows:
        period = _esc(r.get("period"))
        cloud_b = _esc(r.get("cloud_lo_billion_ntd"))
        mom = r.get("cloud_mom_pct")
        row_bg = ""
        if period and period == _esc(rows[-1].get("period")):
            row_bg = " bg-blue-50/60"
        body.append(
            f'<tr class="border-t border-blue-100{row_bg}">'
            f'<td class="py-2 pr-3 font-mono text-xs text-gray-700">{period}</td>'
            f'<td class="py-2 pr-3 text-sm font-semibold text-blue-950 tabular-nums">{cloud_b} 亿</td>'
            f'<td class="py-2 text-right text-sm">{format_mom_cell(mom)}</td>'
            f"</tr>"
        )

    th_cloud = _render_table_header_label("云端推导(亿NTD)", FII_COL_HELP_CLOUD)
    th_mom = _render_table_header_label("月环比", FII_COL_HELP_CLOUD)

    return f"""
<div class="mt-4 rounded-xl border-2 border-blue-200 bg-gradient-to-b from-blue-50/90 to-white overflow-hidden" onclick="event.stopPropagation()">
  <div class="px-3 py-2.5 border-b border-blue-100 flex flex-wrap items-center justify-between gap-2">
    <div>
      <p class="text-sm font-bold text-blue-950">云端网路 · 近 {len(rows)} 月环比</p>
      <p class="text-[10px] text-blue-700/80 mt-0.5">Solver 推导下限 · 发令看此列 MoM（非合并总营收）</p>
    </div>
    <span class="text-[11px] px-2 py-1 rounded-md border {sig_cls} font-medium">{sig_icon} {_esc(sig.get('label') or '观察区')}</span>
  </div>
  <div class="px-2 pb-1 overflow-x-auto">
    <table class="w-full text-left min-w-[14rem]">
      <thead><tr class="text-[10px] text-blue-800/70 uppercase tracking-wide">
        <th class="py-2 pl-1 font-semibold">月份</th>
        <th class="py-2 font-semibold">{th_cloud}</th>
        <th class="py-2 pr-1 font-semibold text-right">{th_mom}</th>
      </tr></thead>
      <tbody>{''.join(body)}</tbody>
    </table>
  </div>
  <p class="px-3 pb-2.5 text-[10px] text-gray-600 border-t border-blue-50">{reason_line}</p>
</div>"""


def render_fii_secondary_collapsed(
    *,
    total_rows: list[dict[str, Any]],
    signal: dict[str, Any] | None = None,
) -> str:
    """次要参考 · 默认折叠：合并总营收 + 发令规则。"""
    from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import (
        FII_COL_HELP_MOM,
        FII_COL_HELP_TOTAL,
    )

    slim_rows: list[str] = []
    for r in (total_rows or [])[-5:]:
        slim_rows.append(
            f'<tr class="border-t border-gray-100 text-[10px]">'
            f'<td class="py-1 pr-2 font-mono text-gray-500">{_esc(r.get("period"))}</td>'
            f'<td class="py-1 pr-2 text-gray-600">{_esc(r.get("total_billion_ntd"))} 亿</td>'
            f'<td class="py-1 text-right">{format_mom_cell(r.get("mom_pct"))}</td>'
            f"</tr>"
        )
    total_table = ""
    if slim_rows:
        total_table = (
            f'<p class="text-[10px] font-medium text-gray-500 mb-1">合并总营收（次要参考 · 含果链）</p>'
            f'<table class="w-full mb-3"><thead><tr class="text-[10px] text-gray-400">'
            f'<th class="pb-1">月份</th><th class="pb-1">合并营收</th>'
            f'<th class="pb-1 text-right">MoM</th></tr></thead>'
            f"<tbody>{''.join(slim_rows)}</tbody></table>"
        )

    sig = signal or {}
    reasons = sig.get("reasons") or []
    reason_items = "".join(f"<li>{_esc(x)}</li>" for x in reasons[:4])

    return f"""
<details class="mt-3 border border-gray-200 rounded-lg bg-gray-50/50">
  <summary class="executing-fold-summary cursor-pointer list-none block select-none px-3 py-2 text-[11px] text-gray-600 hover:bg-gray-100 [&::-webkit-details-marker]:hidden" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()">
    合并总营收参考 · 发令规则说明 ▾
  </summary>
  <div class="px-3 pb-3 pt-1 border-t border-gray-200 text-[11px] text-gray-600">
    {total_table}
    <p class="text-[10px] font-medium text-gray-500 mb-1">目标三 · 发令规则</p>
    <ul class="list-disc pl-4 space-y-0.5 text-[10px]">
      <li>🟢 进攻：连续两月<strong>云端</strong> MoM &gt; 15% 且四板块 MoM 排名第 1</li>
      <li>🔴 防守：IR 持平/衰退词，或云端排名跌出前二</li>
      <li>🟡 观察：以上皆不满足（<strong>不看合并总营收 MoM</strong>）</li>
    </ul>
    <ul class="mt-2 list-disc pl-4 space-y-0.5 text-[10px] text-gray-500">{reason_items}</ul>
  </div>
</details>"""


def render_fii_cloud_vs_total_table(rows: list[dict[str, Any]], *, footnote_html: str = "") -> str:
    """已弃用宽表 · 保留供单测兼容。"""
    return render_fii_cloud_primary_block(rows)


def render_fii_ownership_card_face(ownership: dict[str, Any]) -> str:
    """卡面 · 鸿海系持股摘要 +「详细了解」折叠说明。"""
    if not ownership:
        return ""
    concert = _esc(ownership.get("concert_party_label") or ownership.get("concert_party_pct"))
    galaxy = _esc(ownership.get("china_galaxy_label") or ownership.get("china_galaxy_pct"))
    as_of = _esc(ownership.get("as_of") or "")
    detail = ownership.get("detail_html") or ""
    return f"""
<div class="mt-2.5 flex flex-col gap-2 w-full" onclick="event.stopPropagation()">
  <div class="flex flex-wrap items-center gap-2">
    <span class="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-md bg-indigo-50 border border-indigo-200 text-indigo-950">
      <span class="text-indigo-700 font-medium">鸿海系持股</span>
      <strong class="text-sm tabular-nums text-indigo-900">{concert}</strong>
    </span>
    <span class="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-gray-50 border border-gray-200 text-gray-700">
      中坚企业直接 <strong class="tabular-nums ml-0.5">{galaxy}</strong>
    </span>
    <span class="text-[10px] text-gray-400">截至 {as_of}</span>
  </div>
  <details class="group/own w-full">
    <summary class="list-none cursor-pointer inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-md border border-blue-200 bg-blue-50 text-blue-800 hover:bg-blue-100 w-fit [&::-webkit-details-marker]:hidden">
      详细了解股权与分红
      <span class="text-gray-400 group-open/own:hidden">▾</span>
      <span class="text-gray-400 hidden group-open/own:inline">▴</span>
    </summary>
    <div class="mt-2 p-3 rounded-lg border border-gray-200 bg-white shadow-sm">{detail}</div>
  </details>
</div>"""


def render_fii_twse_cloud_body(node: dict[str, Any]) -> str:
    """fii 专用 · 云端网路 + 合并总营收双表（同款月序列表）+ 发令信号。"""
    from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import (
        FII_COL_HELP_CLOUD,
        FII_COL_HELP_MOM,
        FII_COL_HELP_TOTAL,
        fii_table_freshness_note_html,
        refresh_card_strategy_for_node,
    )

    cs = refresh_card_strategy_for_node(node)
    if not cs:
        return ""
    g1 = cs.get("goal1_time_lag") or {}
    g1b = cs.get("goal1b_cloud_vs_total") or {}

    cloud_cmp = g1b.get("comparison_series") or []
    cloud_rows = [
        {
            "period": r.get("period"),
            "cloud_lo_billion_ntd": r.get("cloud_lo_billion_ntd"),
            "mom_pct": r.get("cloud_mom_pct"),
        }
        for r in cloud_cmp
    ]
    total_rows = (g1.get("monthly_series") or [])[-5:]

    cloud_table = render_jl3_monthly_table(
        {
            "rows": cloud_rows,
            "value_key": "cloud_lo_billion_ntd",
            "value_label": "云端推导(亿NTD)",
            "billion_key": "cloud_lo_billion_ntd",
            "column_helps": {
                "cloud_lo_billion_ntd": FII_COL_HELP_CLOUD,
                "mom_pct": FII_COL_HELP_MOM,
            },
        }
    )
    total_table = render_jl3_monthly_table(
        {
            "rows": total_rows,
            "value_key": "total_billion_ntd",
            "value_label": "合并营收(亿NTD)",
            "billion_key": "total_billion_ntd",
            "column_helps": {
                "total_billion_ntd": FII_COL_HELP_TOTAL,
                "mom_pct": FII_COL_HELP_MOM,
            },
            "freshness_note_html": fii_table_freshness_note_html(total_rows),
        }
    )

    return f"""
<div class="mt-3 space-y-4" onclick="event.stopPropagation()">
  <section class="rounded-lg border border-blue-200 bg-blue-50/40 px-3 py-2.5">
    <h4 class="text-xs font-bold text-blue-950">云端网路 · 近 {len(cloud_rows) or 5} 月环比</h4>
    <p class="text-[10px] text-blue-800/80 mt-0.5 mb-1">Solver 推导下限 · 发令看此列 MoM（非合并总营收）</p>
    {cloud_table}
  </section>
  <section class="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2.5">
    <h4 class="text-xs font-semibold text-gray-800">合并总营收</h4>
    <p class="text-[10px] text-gray-500 mt-0.5 mb-1">母公司鸿海 2317 · 含果链与其他板块</p>
    {total_table}
  </section>
</div>"""


def render_fii_odm_direct_ratio_body(node: dict[str, Any]) -> str:
    """fii_odm 专用 · 云业务硬锚表 + 防置换摘要。"""
    from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.card_strategy import (
        refresh_card_strategy_for_node,
    )

    cs = refresh_card_strategy_for_node(node)
    if not cs:
        return ""
    sections = cs.get("sections") or []
    parts: list[str] = ['<div class="mt-3 space-y-3" onclick="event.stopPropagation()">']
    for sec in sections:
        title = _esc(str(sec.get("title") or ""))
        if sec.get("table"):
            tbl = sec["table"]
            rows = tbl.get("rows") or []
            if not rows:
                continue
            r0 = rows[0]
            parts.append(
                f'<section class="rounded-lg border border-indigo-200 bg-indigo-50/40 px-3 py-2.5">'
                f'<h4 class="text-xs font-bold text-indigo-950">{title}</h4>'
                f'<p class="text-[10px] text-indigo-800/80 mt-0.5 mb-1">{_esc(str(sec.get("subtitle") or ""))}</p>'
                f'<dl class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs mt-1">'
                f'<div><dt class="text-gray-500">云营收</dt><dd class="font-semibold tabular-nums">'
                f'{r0.get("cloud_billion_cny", "—")} 亿元</dd></div>'
                f'<div><dt class="text-gray-500">YoY</dt><dd class="font-semibold tabular-nums">'
                f'{r0.get("yoy_pct", "—")}%</dd></div>'
            )
            sem_l = r0.get("semantic_label")
            odm_lo, odm_hi = r0.get("odm_lo_pct"), r0.get("odm_hi_pct")
            if odm_lo is not None and odm_hi is not None:
                parts.append(
                    f'<div><dt class="text-gray-500">ODM占比</dt><dd class="font-semibold tabular-nums">'
                    f'{odm_lo}–{odm_hi}%</dd></div>'
                )
            elif sem_l:
                parts.append(
                    f'<div class="col-span-2"><dt class="text-gray-500">语义信号</dt>'
                    f'<dd class="font-semibold text-indigo-900">{_esc(str(sem_l))}</dd></div>'
                )
            parts.append(f"</dl></section>")
        elif sec.get("custom_html"):
            parts.append(
                f'<section class="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2.5">'
                f'<h4 class="text-xs font-semibold text-gray-800">{title}</h4>'
                f'{sec["custom_html"]}'
                f"</section>"
            )
    parts.append("</div>")
    return "".join(parts)


def normalize_jl3_card_strategy(cs: dict[str, Any]) -> dict[str, Any]:
    """将 card_strategy 规范化为 sections 格式（兼容 fii goal1/2/3 旧键）。"""
    if not cs:
        return {}
    if cs.get("sections"):
        return cs
    if cs.get("goal1b_cloud_vs_total") or cs.get("goal3_trend_trigger"):
        g3 = cs.get("goal3_trend_trigger") or {}
        return {
            **cs,
            "panel_title": cs.get("panel_title") or "601138 云端监控",
            "signal": {
                "status": g3.get("status") or "yellow",
                "label": g3.get("label") or "观察区",
                "summary": g3.get("summary") or "",
                "reasons": g3.get("reasons") or [],
            },
            "sections": [],
        }
    # fii_twse_cloud  legacy → standard
    g1 = cs.get("goal1_time_lag") or {}
    g1b = cs.get("goal1b_cloud_vs_total") or {}
    g2 = cs.get("goal2_noise_isolation") or {}
    g3 = cs.get("goal3_trend_trigger") or {}
    if not g1 and not g1b and not g2 and not g3:
        return cs
    from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import (
        FII_COL_HELP_MOM,
        FII_COL_HELP_TOTAL,
        fii_table_freshness_note_html,
    )

    cloud_mom = g2.get("cloud_lo_mom_pct")
    consumer_mom = g2.get("consumer_mom_proxy_pct")
    cloud_terms = "、".join(g2.get("cloud_ir_terms") or []) or "—"
    consumer_terms = "、".join(g2.get("consumer_ir_terms") or []) or "—"
    g2_html = (
        f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">'
        f'<div class="rounded-md bg-blue-50/80 px-3 py-2 border border-blue-100">'
        f'<p class="text-[10px] text-blue-700 font-medium">云端网路 · 推导下限</p>'
        f'<p class="text-lg font-bold text-blue-900 tabular-nums">{g2.get("cloud_lo_billion", "—")} 亿</p>'
        f'<p class="text-[11px] text-blue-800">MoM {format_mom_cell(cloud_mom)} · IR：{_esc(cloud_terms)}</p>'
        f"</div>"
        f'<div class="rounded-md bg-slate-50 px-3 py-2 border border-slate-200">'
        f'<p class="text-[10px] text-slate-600 font-medium">消费智能 · 代理对照</p>'
        f'<p class="text-lg font-bold text-slate-800 tabular-nums">MoM {format_mom_cell(consumer_mom)}</p>'
        f'<p class="text-[10px] text-slate-500">{_esc(g2.get("consumer_mom_note") or "")}</p>'
        f'<p class="text-[11px] text-slate-600">IR：{_esc(consumer_terms)}</p>'
        f"</div></div>"
    )
    honhai_rows = g1.get("monthly_series") or []
    cloud_cmp_rows = g1b.get("comparison_series") or []
    sections: list[dict[str, Any]] = [
        {
            "title": g1.get("title") or "目标一 · 时间差套利",
            "subtitle": g1.get("subtitle") or "",
            "table": {
                "rows": honhai_rows,
                "value_key": "total_billion_ntd",
                "value_label": "合并营收(亿NTD)",
                "billion_key": "total_billion_ntd",
                "column_helps": {
                    "total_billion_ntd": FII_COL_HELP_TOTAL,
                    "mom_pct": FII_COL_HELP_MOM,
                },
                "freshness_note_html": fii_table_freshness_note_html(honhai_rows),
            },
        },
    ]
    if cloud_cmp_rows:
        sections.append(
            {
                "title": g1b.get("title") or "云端网路 · 近五月环比对照",
                "subtitle": g1b.get("subtitle") or "",
                "custom_html": render_fii_cloud_vs_total_table(cloud_cmp_rows),
            }
        )
    sections.extend(
        [
            {
                "title": g2.get("title") or "目标二 · 剥离果链噪音",
                "subtitle": g2.get("subtitle") or "",
                "custom_html": g2_html,
            },
            {
                "title": g3.get("title") or "目标三 · 程序化发令枪",
                "subtitle": "Bool 开关 · 供 QMT/PTrade 策略订阅（绿=进攻 / 红=防守 / 黄=观察）",
            },
        ]
    )
    return {
        **cs,
        "panel_title": cs.get("panel_title") or "三目标实战面板 · 601138 影子定价锚",
        "signal": {
            "status": g3.get("status") or "yellow",
            "label": g3.get("label") or "观察区",
            "summary": g3.get("summary") or "",
            "reasons": g3.get("reasons") or [],
        },
        "sections": sections,
    }


def render_jl3_strategy_sections(cs: dict[str, Any]) -> str:
    """渲染 card_strategy.sections 正文（不含折叠外壳）。"""
    cs = normalize_jl3_card_strategy(cs)
    if not cs:
        return ""
    signal = cs.get("signal") or {}
    reasons = signal.get("reasons") or []
    reasons_html = ""
    if reasons:
        items = "".join(f"<li>{_esc(r)}</li>" for r in reasons)
        reasons_html = (
            f'<ul class="text-[11px] text-gray-600 mb-3 list-disc pl-4 space-y-0.5">{items}</ul>'
        )
    blocks: list[str] = [reasons_html]
    for sec in cs.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = sec.get("title") or ""
        subtitle = sec.get("subtitle") or ""
        inner = ""
        table = sec.get("table")
        if isinstance(table, dict):
            inner += render_jl3_monthly_table(table)
        custom = sec.get("custom_html")
        if custom:
            inner += str(custom)
        footnote = sec.get("footnote")
        if footnote:
            inner += f'<p class="text-[10px] text-gray-500 mt-2">{_esc(footnote)}</p>'
        blocks.append(
            f"<section>"
            f'<h5 class="text-[11px] font-semibold text-gray-800">{_esc(title)}</h5>'
            f'<p class="text-[10px] text-gray-500">{_esc(subtitle)}</p>'
            f"{inner}"
            f"</section>"
        )
    return f'<div class="space-y-4">{"".join(blocks)}</div>'


def render_jl3_strategy_collapsible(
    cs: dict[str, Any],
    *,
    probe_key: str,
    panel_title: str | None = None,
) -> str:
    """JL3 标准折叠面板 · 默认收起。"""
    cs = normalize_jl3_card_strategy(cs)
    if not cs:
        return ""
    signal = cs.get("signal") or {}
    status = str(signal.get("status") or "yellow")
    label = str(signal.get("label") or "观察区")
    summary_line = str(signal.get("summary") or "")
    help_html = cs.get("help_html") or ""
    title = panel_title or cs.get("panel_title") or probe_label(probe_key)
    help_btn = render_inline_help_btn(help_html, title=f"{probe_key} 指标说明") if help_html else ""
    badge_palette = {
        "green": "bg-emerald-50 text-emerald-800 border-emerald-200",
        "yellow": "bg-amber-50 text-amber-900 border-amber-200",
        "red": "bg-red-50 text-red-800 border-red-200",
    }
    badge_cls = badge_palette.get(status, badge_palette["yellow"])
    panel_body = render_jl3_strategy_sections(cs)
    group_id = probe_key.replace("_", "-")

    return f"""
<details class="mt-4 border border-blue-100 rounded-lg bg-blue-50/30 overflow-hidden group/jl3-{group_id}">
  <summary class="executing-fold-summary cursor-pointer list-none block select-none px-3 py-2.5 flex flex-wrap items-center justify-between gap-2 hover:bg-blue-50/80 [&::-webkit-details-marker]:hidden" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()">
    <div class="flex items-center gap-2 min-w-0">
      <span class="text-xs font-semibold text-blue-900">{_esc(title)}</span>
      {help_btn}
      <span class="text-[10px] px-1.5 py-0.5 rounded border {badge_cls} font-medium shrink-0">{_esc(label)}</span>
    </div>
    <span class="text-[10px] text-gray-400 shrink-0 group-open/jl3-{group_id}:hidden">展开详情 ▾</span>
    <span class="text-[10px] text-gray-400 shrink-0 hidden group-open/jl3-{group_id}:inline">收起 ▴</span>
  </summary>
  <div class="px-3 pb-3 pt-1 border-t border-blue-100 bg-white/60">
    {render_jl3_signal_badge(status, label, summary_line)}
    {panel_body}
  </div>
</details>"""


def jl3_value_color_from_signal(cs: dict[str, Any]) -> tuple[str, bool]:
    cs = normalize_jl3_card_strategy(cs)
    signal = cs.get("signal") or {}
    status = str(signal.get("status") or "yellow")
    value_color = {
        "green": "text-emerald-700",
        "yellow": "text-amber-700",
        "red": "text-red-700",
    }.get(status, "text-gray-900")
    return value_color, status != "red"


def render_jl3_probe_card(
    probe_key: str,
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
    subtitle: str | None = None,
) -> str:
    """JL3 探针统一卡片入口（所有 JL3 须走此函数）。"""
    t1_json = node.get("t1_json") if isinstance(node.get("t1_json"), dict) else None
    rm = raw_metrics_for_display(node)
    cs = rm.get("card_strategy") if isinstance(rm.get("card_strategy"), dict) else {}
    if probe_key == "fii_twse_cloud":
        from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import (
            refresh_card_strategy_for_node,
        )

        cs = refresh_card_strategy_for_node(node)
    elif probe_key == "fii_odm_direct_ratio":
        from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.card_strategy import (
            refresh_card_strategy_for_node,
        )

        cs = refresh_card_strategy_for_node(node)
    elif probe_key == "fii_gb200_milestone":
        from apps.copilot.modules.executing.l3.fii_gb200_milestone.card_strategy import (
            refresh_card_strategy_for_node,
        )

        cs = refresh_card_strategy_for_node(node)
    value_color, status_ok = jl3_value_color_from_signal(cs)
    header_extra = ""
    header_corner = ""
    alert_html = ""
    if probe_key == "fii_twse_cloud":
        own = cs.get("honhai_ownership") if isinstance(cs.get("honhai_ownership"), dict) else {}
        g3 = cs.get("goal3_trend_trigger") or {}
        header_extra = render_fii_ownership_card_face(own)
        header_corner = render_jl3_goal3_corner_chip(g3)
        alert_html = render_fii_twse_cloud_body(node)
    elif probe_key == "fii_odm_direct_ratio":
        alert_html = render_fii_odm_direct_ratio_body(node)
    elif probe_key == "fii_gb200_milestone":
        from apps.copilot.modules.executing.l3.fii_gb200_milestone.card_strategy import (
            refresh_card_strategy_for_node,
            render_gb200_milestone_body,
        )

        cs = refresh_card_strategy_for_node(node)
        alert_html = render_gb200_milestone_body(node)
    else:
        alert_html = render_jl3_strategy_collapsible(cs, probe_key=probe_key)

    sub = subtitle
    if not sub and rm.get("report_year") and rm.get("report_month"):
        sub = f"{rm['report_year']}-{int(rm['report_month']):02d}"
    if not sub and rm.get("report_period"):
        sub = str(rm["report_period"])

    rpc = _get_render_probe_card()
    fii_kw: dict[str, Any] = {}
    metric_items: list[tuple[str, Any]] = []
    if probe_key in ("fii_twse_cloud", "fii_odm_direct_ratio"):
        fii_kw = {
            "show_source_footer": False,
            "show_fact_block": False,
            "show_formula_block": False,
        }
    elif probe_key == "fii_gb200_milestone":
        contract = node.get("t1_json") if isinstance(node.get("t1_json"), dict) else {}
        dc = contract.get("deepsea_contract") if isinstance(contract.get("deepsea_contract"), dict) else {}
        sm = contract.get("state_machine") if isinstance(contract.get("state_machine"), dict) else {}
        sv = contract.get("shadow_validation") if isinstance(contract.get("shadow_validation"), dict) else {}
        metric_items = [
            ("NPI", sm.get("current_stage_label") or sm.get("current_stage") or "未识别"),
            ("动量", dc.get("momentum_delta") or contract.get("momentum_delta")),
            ("侧翼验真", "PASS" if sv.get("passed") else "待验"),
        ]
        fii_kw = {
            "show_source_footer": True,
            "show_fact_block": True,
            "show_formula_block": False,
        }
    return rpc(
        probe_key=probe_key,
        title=node.get("indicator_name") or probe_indicator_name(probe_key),
        short_label=probe_label(probe_key),
        value_html=_esc(node.get("value_detail") or node.get("value") or "—"),
        value_color=value_color,
        subtitle=sub,
        card_timing=card_timing,
        header_extra_html=header_extra,
        header_corner_html=header_corner,
        fact_statement=str(node.get("fact_statement") or ""),
        calculation_logic=str(node.get("calculation_logic") or ""),
        source=str(node.get("source") or ""),
        metric_items=metric_items,
        alert_html=alert_html,
        t1_json=t1_json,
        status_ok=status_ok,
        layer_badge="",
        **fii_kw,
    )


def render_fii_twse_cloud_card(
    node: dict[str, Any],
    *,
    card_timing: ProbeCardTiming | None = None,
) -> str:
    """兼容别名 · 新代码请直接用 :func:`render_jl3_probe_card`。"""
    period = None
    rm = raw_metrics_for_display(node)
    if rm.get("report_year") and rm.get("report_month"):
        period = f"{rm['report_year']}-{int(rm['report_month']):02d} · 鸿海2317 → 601138"
    return render_jl3_probe_card(
        "fii_twse_cloud",
        node,
        card_timing=card_timing,
        subtitle=period,
    )
