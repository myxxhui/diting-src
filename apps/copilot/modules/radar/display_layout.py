"""行情雷达扫描结果 · 用户可配置展示模块（顺序 / 显隐 / 自定义维）。

布局持久化在 `RADAR_T0_CACHE_DIR/display_layout.json`（与 workbench_prefs 同 PVC），
平台停机/机器重建后仍保留；前端 localStorage 仅作离线缓存。
请求头 `X-Radar-Display-Layout` 可覆盖单次渲染，缺省读服务端已存布局。

[Ref: 24_行情解析工作台 · 26_行情雷达与AI模型工作流]
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from apps.copilot.modules.radar.schema import DIM_KEYS, DIMENSIONS, DIM_META
from apps.copilot.modules.radar.workbench_prefs import radar_cache_root
from apps.copilot.modules.copilot_ui_settings import (
    SETTING_DISPLAY_LAYOUT,
    get_cached,
    set_cached,
)

logger = logging.getLogger(__name__)

LAYOUT_STORAGE_KEY = "radar_scan_layout_v1"
LAYOUT_HEADER = "x-radar-display-layout"
LAYOUT_FILENAME = "display_layout.json"

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


def _layout_path() -> Path:
    root = radar_cache_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / LAYOUT_FILENAME


def layout_to_jsonable(layout: dict[str, Any]) -> dict[str, Any]:
    """API/磁盘序列化：hidden 统一为 list（接受 parse 后的 set）。"""
    hidden = layout.get("hidden") or set()
    if isinstance(hidden, set):
        hidden_list = sorted(hidden)
    else:
        hidden_list = [str(k) for k in hidden]
    return {
        "version": layout.get("version", 1),
        "order": [str(k) for k in (layout.get("order") or []) if k],
        "hidden": hidden_list,
        "custom": list(layout.get("custom") or []),
        "show_summary": bool(layout.get("show_summary", True)),
        "show_overall_in_detail": bool(layout.get("show_overall_in_detail", False)),
        "max_visible": layout.get("max_visible"),
    }


def load_saved_layout() -> dict[str, Any] | None:
    """读取 PG 缓存或 PVC/本地已存布局；不存在返回 None。"""
    cached = get_cached(SETTING_DISPLAY_LAYOUT)
    if isinstance(cached, dict):
        return parse_layout_from_header(json.dumps(cached, ensure_ascii=False))
    path = _layout_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("读取 display_layout 失败: %s", exc)
        return None
    return parse_layout_from_header(raw)


def save_saved_layout(payload: dict[str, Any]) -> dict[str, Any]:
    """校验并写入 display_layout（内存 + 磁盘）。"""
    to_parse = dict(payload)
    hidden_in = to_parse.get("hidden")
    if isinstance(hidden_in, set):
        to_parse["hidden"] = sorted(hidden_in)
    merged = parse_layout_from_header(json.dumps(to_parse, ensure_ascii=False))
    out = layout_to_jsonable(merged)
    set_cached(SETTING_DISPLAY_LAYOUT, out)
    path = _layout_path()
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("display_layout 已写入 %s", path)
    return out


async def save_saved_layout_async(session, payload: dict[str, Any]) -> dict[str, Any]:
    from apps.copilot.modules.copilot_ui_settings import save_setting_row

    out = save_saved_layout(payload)
    await save_setting_row(session, SETTING_DISPLAY_LAYOUT, out)
    return out


async def reset_saved_layout_async(session) -> dict[str, Any]:
    from apps.copilot.modules.copilot_ui_settings import delete_setting_row

    path = _layout_path()
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("删除 display_layout 失败: %s", exc)
    await delete_setting_row(session, SETTING_DISPLAY_LAYOUT)
    defaults = default_layout()
    set_cached(SETTING_DISPLAY_LAYOUT, layout_to_jsonable(defaults))
    return defaults


def reset_saved_layout() -> dict[str, Any]:
    path = _layout_path()
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("删除 display_layout 失败: %s", exc)
    defaults = default_layout()
    set_cached(SETTING_DISPLAY_LAYOUT, layout_to_jsonable(defaults))
    return defaults


def resolve_layout_for_request(header_raw: str | None) -> dict[str, Any]:
    """单次请求：请求头优先，否则服务端持久化，最后默认。"""
    if header_raw and str(header_raw).strip():
        return parse_layout_from_header(header_raw)
    saved = load_saved_layout()
    if saved:
        return saved
    return default_layout()


def layout_schema_payload() -> dict[str, Any]:
    saved = load_saved_layout()
    return {
        "version": 1,
        "storage_key": LAYOUT_STORAGE_KEY,
        "header_name": LAYOUT_HEADER,
        "persist_path": str(_layout_path()),
        "persist_api": "/api/radar/display-layout",
        "default": default_layout(),
        "saved": layout_to_jsonable(saved) if saved else None,
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
