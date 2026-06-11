"""Opus 持仓 T2 · 可选同步行情雷达九维模板（display_layout）。

[Ref: radar/schema.py · display_layout.py · 28_ §5]
"""
from __future__ import annotations

import copy
from typing import Any

from apps.copilot.modules.radar.display_layout import (
    default_layout,
    load_saved_layout,
    ordered_display_metas,
)
from apps.copilot.modules.radar.schema import (
    DIM_KEYS,
    MARKET_PHASE_LABELS,
    dimension_keys_from_layout,
    format_dimension_brief,
    schema_hint_for_keys,
)


def resolve_radar_display_layout(layout: dict[str, Any] | None = None) -> dict[str, Any]:
    """与行情雷达工作台同源：PVC/PG display_layout，缺省内置九维。"""
    if layout is not None:
        return layout
    return load_saved_layout() or default_layout()


def build_empty_dimensions_example(dim_keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in dim_keys:
        node: dict[str, Any] = {
            "verdict": "",
            "reasoning": "",
            "evidence": [],
            "confidence": 0.0,
        }
        if key == "catalyst_timeline":
            node["items"] = []
        elif key == "valuation":
            node["davis_double"] = ""
            node["pe_percentile"] = None
        out[key] = node
    return out


def inject_radar_nine_dim_into_envelope(
    envelope: dict[str, Any],
    *,
    enabled: bool,
    layout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按用户选项注入/禁止 radar_nine_dimensions 输出契约。"""
    out = copy.deepcopy(envelope)
    oc = out.setdefault("output_contract", {})
    rules = list(oc.get("rules") or [])

    if not enabled:
        rules.append(
            "本请求未启用 radar_nine_dimensions：禁止在 symbol_audits 内输出该字段"
        )
        oc["rules"] = rules
        out["radar_nine_dim"] = {"enabled": False}
        return out

    layout = resolve_radar_display_layout(layout)
    dim_keys = dimension_keys_from_layout(layout) or list(DIM_KEYS)
    brief = format_dimension_brief(layout)
    dim_example = build_empty_dimensions_example(dim_keys)
    radar_example = {
        "overall": {
            "conclusion": "",
            "action_advisory": "",
            "confidence": 0.0,
        },
        "dimensions": dim_example,
    }

    section = (
        "\n\n## 雷达九维深度研报（用户已启用 · 每票必填）\n"
        f"与行情雷达工作台 display_layout 同步的 {len(dim_keys)} 个分析维度：\n"
        f"{brief}\n\n"
        "每只标的须在 symbol_audits.<symbol>.radar_nine_dimensions 输出与雷达模式 C 同构 JSON：\n"
        "- overall：conclusion、action_advisory、confidence\n"
        "- dimensions：每项含 verdict、reasoning、evidence[]、confidence\n"
        "可结合 JL1–JL3 补全与行业逻辑；禁止编造 JL4 indicators 未出现的数值。\n"
        "全部为 research advisory，非交易指令。\n\n"
        f"{schema_hint_for_keys(dim_keys)}"
    )
    out["system_prompt"] = (out.get("system_prompt") or "") + section

    example = oc.get("example") or {}
    symbol_audits = example.get("symbol_audits") or {}
    for audit in symbol_audits.values():
        if isinstance(audit, dict):
            audit["radar_nine_dimensions"] = copy.deepcopy(radar_example)
    example["symbol_audits"] = symbol_audits
    oc["example"] = example

    rules.append(
        "radar_nine_dimensions：每票必填；dimensions 须覆盖 "
        + "、".join(dim_keys)
        + "；结构与雷达模式 C 一致"
    )
    oc["rules"] = rules

    qa = list(out.get("qa_index") or [])
    qa.append(
        {
            "id": "radar_nine_dimensions",
            "asks": f"雷达九维深度研报（{len(dim_keys)} 维 · 与 display_layout 同步）",
            "reply_path": "symbol_audits.{symbol}.radar_nine_dimensions",
            "reply_type": "radar_mode_c_json",
        }
    )
    out["qa_index"] = qa
    out["radar_nine_dim"] = {
        "enabled": True,
        "dim_keys": dim_keys,
        "layout_version": layout.get("version", 1),
    }
    return out


def radar_layout_panel_summary(layout: dict[str, Any] | None = None) -> dict[str, Any]:
    """供 Opus 面板展示：维度数与标签摘要。"""
    layout = resolve_radar_display_layout(layout)
    metas = ordered_display_metas(layout)
    labels = [f"{m.get('emoji', '')} {m.get('label', m['key'])}".strip() for m in metas]
    return {
        "dim_count": len(metas),
        "labels_preview": " · ".join(labels[:5]) + ("…" if len(labels) > 5 else ""),
    }
