"""雷达缓存审计页 HTML 渲染（T0/T1/T2 版本查看）。

[Ref: step_14 · t0_cache 版本目录]
"""
from __future__ import annotations

import html
import json
from typing import Any


def _esc(v: Any) -> str:
    return html.escape(str(v) if v is not None else "")


def _json_block(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return (
        f"<pre class='text-xs bg-gray-900 text-gray-100 p-3 rounded-lg overflow-x-auto "
        f"max-h-[480px] overflow-y-auto'>{_esc(text)}</pre>"
    )


def render_audit_page(
    *,
    symbol: str,
    name: str,
    versions: list[dict[str, Any]],
    selected_version_id: str | None,
    bundle: dict[str, Any] | None,
) -> str:
    sym = _esc(symbol)
    rows = ""
    for v in versions:
        vid = v.get("version_id") or ""
        active = vid == selected_version_id
        cls = "bg-blue-50 border-blue-300" if active else "bg-white border-gray-200 hover:bg-gray-50"
        t2 = v.get("t2_status") or "—"
        cost = v.get("t2_cost_yuan")
        cost_txt = f"¥{float(cost):.4f}" if cost else "—"
        latest_badge = "<span class='text-[10px] text-green-700'>最新</span> " if v.get("is_latest") else ""
        rows += (
            f"<a href='/audit?symbol={sym}&amp;version={_esc(vid)}' "
            f"class='block border rounded-lg p-3 mb-2 no-underline {cls}'>"
            f"<div class='flex justify-between text-sm text-gray-900'>"
            f"<span class='font-mono'>{latest_badge}{_esc(vid)}</span>"
            f"<span class='text-gray-500'>{_esc(v.get('collected_at','')[:19])}</span></div>"
            f"<div class='text-xs text-gray-500 mt-1'>T0 {v.get('ok_parts',0)}/4 · T2 {t2} · {cost_txt}</div>"
            f"</a>"
        )

    body = "<p class='text-sm text-gray-500'>请选择左侧版本</p>"
    if bundle:
        t1 = bundle.get("t1_distilled") or {}
        t2 = bundle.get("t2_verdict") or {}
        body = (
            f"<div class='mb-3 text-sm text-gray-600'>"
            f"<span class='font-semibold text-gray-900'>{_esc(bundle.get('name') or name)}</span> "
            f"<span class='font-mono text-gray-400'>{sym}</span> · "
            f"版本 <span class='font-mono'>{_esc(bundle.get('version_id'))}</span> · "
            f"采集 {_esc(str(bundle.get('collected_at',''))[:19])}</div>"
            f"<div class='flex gap-2 mb-3 text-xs'>"
            f"<span class='px-2 py-1 rounded bg-gray-100'>source={_esc(bundle.get('source'))}</span>"
            f"<span class='px-2 py-1 rounded bg-gray-100'>T1 {_esc(t1.get('model_id'))}</span>"
            f"<span class='px-2 py-1 rounded bg-gray-100'>T2 {_esc(t2.get('status'))}</span>"
            f"</div>"
            f"<details open class='mb-3'><summary class='cursor-pointer text-sm font-semibold text-gray-800'>T0 原始四源</summary>"
            f"{_json_block({k: bundle.get(k) for k in ('quote','profile','financials','valuation')})}</details>"
            f"<details open class='mb-3'><summary class='cursor-pointer text-sm font-semibold text-gray-800'>T1 事实矩阵</summary>"
            f"{_json_block(t1)}</details>"
            f"<details open class='mb-3'><summary class='cursor-pointer text-sm font-semibold text-gray-800'>T2 深度研报</summary>"
            f"{_json_block(t2)}</details>"
        )

    empty_versions = "<p class='text-sm text-gray-400'>暂无历史版本</p>"
    side = rows or empty_versions
    return (
        f"<div class='grid grid-cols-1 lg:grid-cols-3 gap-4'>"
        f"<div class='lg:col-span-1'><h3 class='text-sm font-semibold text-gray-800 mb-2'>"
        f"最近 {len(versions)} 个版本（保留 7 天）</h3>{side}</div>"
        f"<div class='lg:col-span-2'>{body}</div></div>"
    )
