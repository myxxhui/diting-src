"""行情雷达扫描结果 · 用户可配置展示模块（顺序 / 显隐 / 自定义维）。

布局 JSON 由前端 localStorage 保存，经请求头 `X-Radar-Display-Layout` 传给 HTMX 渲染。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from apps.copilot.modules.radar.schema import DIM_KEYS, DIMENSIONS, DIM_META

logger = logging.getLogger(__name__)

LAYOUT_STORAGE_KEY = "radar_scan_layout_v1"
LAYOUT_HEADER = "x-radar-display-layout"

DEFAULT_LAYOUT: dict[str, Any] = {
    "version": 1,
    "order": list(DIM_KEYS),
    "hidden": [],
    "custom": [],
    "show_summary": True,
    "show_overall_in_detail": False,
    "max_visible": None,
}

PROMPT_WRITING_GUIDE = """自定义模块 · 提示词编写规范（供复制到 Opus 或后续扩展扫描）

1. **模块 id**：英文小写+下划线，如 `supply_chain_risk`，勿与内置 9 维 key 重复。
2. **label / hint**：用一句话说明「要回答什么问题」，避免空泛（坏例：「分析一下」）。
3. **prompt_snippet**（建议 80～300 字）结构：
   - 角色：你是…分析师
   - 输入：仅基于事实矩阵中的…字段
   - 输出：verdict（一句话结论）+ reasoning（3～5 句）+ evidence（引用矩阵字段名）
   - 禁止：编造矩阵外数字；不足则 verdict=「数据不足」并 confidence≤0.4
4. **JSON 片段**（追加到 Opus 输出 dimensions 时）：
   "your_id": {"verdict":"","reasoning":"","evidence":[],"confidence":0.0}
5. 重新扫描且服务端已配置自定义维后，结果会出现在对应卡片；仅改布局不重新扫描则只影响展示顺序。
"""


def default_layout() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_LAYOUT, ensure_ascii=False))


def parse_layout_from_header(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return default_layout()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("雷达展示布局 JSON 无效，使用默认")
        return default_layout()
    if not isinstance(data, dict):
        return default_layout()
    base = default_layout()
    if isinstance(data.get("order"), list):
        base["order"] = [str(k) for k in data["order"] if k]
    if isinstance(data.get("hidden"), list):
        base["hidden"] = {str(k) for k in data["hidden"]}
    elif isinstance(data.get("hidden"), set):
        base["hidden"] = {str(k) for k in data["hidden"]}
    else:
        base["hidden"] = set()
    if isinstance(data.get("custom"), list):
        base["custom"] = [c for c in data["custom"] if isinstance(c, dict)]
    if "show_summary" in data:
        base["show_summary"] = bool(data["show_summary"])
    if "show_overall_in_detail" in data:
        base["show_overall_in_detail"] = bool(data["show_overall_in_detail"])
    mv = data.get("max_visible")
    if mv is not None:
        try:
            base["max_visible"] = max(1, int(mv))
        except (TypeError, ValueError):
            base["max_visible"] = None
    return base


def layout_schema_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "storage_key": LAYOUT_STORAGE_KEY,
        "header_name": LAYOUT_HEADER,
        "default": default_layout(),
        "builtin_dimensions": DIMENSIONS,
        "prompt_writing_guide": PROMPT_WRITING_GUIDE,
    }


def ordered_display_metas(layout: dict[str, Any]) -> list[dict[str, str]]:
    """合并内置 + 自定义维，按用户顺序与显隐过滤。"""
    hidden = layout.get("hidden") or set()
    if isinstance(hidden, list):
        hidden = set(hidden)
    order = layout.get("order") or list(DIM_KEYS)
    seen: set[str] = set()
    metas: list[dict[str, str]] = []

    def _add(meta: dict[str, str]) -> None:
        key = meta["key"]
        if key in hidden or key in seen:
            return
        seen.add(key)
        metas.append(meta)

    for key in order:
        if key in DIM_META:
            _add(dict(DIM_META[key]))
        else:
            for c in layout.get("custom") or []:
                if c.get("id") == key and c.get("enabled", True):
                    _add(
                        {
                            "key": key,
                            "label": str(c.get("label") or key),
                            "emoji": str(c.get("emoji") or "📌"),
                            "hint": str(c.get("hint") or ""),
                            "custom": "true",
                            "prompt_guide": str(c.get("prompt_guide") or ""),
                        }
                    )
                    break

    for d in DIMENSIONS:
        if d["key"] not in seen and d["key"] not in hidden:
            _add(dict(d))

    for c in layout.get("custom") or []:
        cid = str(c.get("id") or "").strip()
        if not cid or cid in seen or cid in DIM_META or cid in hidden:
            continue
        if not c.get("enabled", True):
            continue
        _add(
            {
                "key": cid,
                "label": str(c.get("label") or cid),
                "emoji": str(c.get("emoji") or "📌"),
                "hint": str(c.get("hint") or ""),
                "custom": "true",
                "prompt_guide": str(c.get("prompt_guide") or ""),
            }
        )

    max_v = layout.get("max_visible")
    if max_v is not None and len(metas) > int(max_v):
        metas = metas[: int(max_v)]
    return metas
