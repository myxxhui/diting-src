"""DeepSeek API 型号 · 与官方 changelog 对齐。

[Ref: https://api-docs.deepseek.com/updates · 2026-04-24 V4]
- 旗舰：deepseek-v4-pro（思考模式）
- 快速：deepseek-v4-flash
- 兼容别名（2026-07-24 下线）：deepseek-chat / deepseek-reasoner（R1 思考链）
- 官方 API **无** R2 型号；R1 对应 reasoner / V4 思考模式
"""
from __future__ import annotations

from typing import Any

# slug（不含 deepseek: 前缀）→ API 参数
DEEPSEEK_MODEL_SPECS: dict[str, dict[str, Any]] = {
    "deepseek-v4-pro": {
        "api_model": "deepseek-chat",
        "thinking": True,
        "label": "DeepSeek V4 Pro（旗舰 · 思考）",
    },
    "deepseek-v4-flash": {
        "api_model": "deepseek-v4-flash",
        "thinking": False,
        "label": "DeepSeek V4 Flash（快速 · 推荐）",
    },
    "deepseek-v4-flash-think": {
        "api_model": "deepseek-v4-flash",
        "thinking": True,
        "label": "DeepSeek V4 Flash 思考",
    },
    "deepseek-reasoner": {
        "api_model": "deepseek-reasoner",
        "thinking": True,
        "label": "DeepSeek R1 思考链（兼容别名）",
    },
    "deepseek-chat": {
        "api_model": "deepseek-chat",
        "thinking": False,
        "label": "DeepSeek 对话（兼容别名）",
    },
}

DEEPSEEK_CHAT_MODELS: list[tuple[str, str]] = [
    (f"deepseek:{slug}", spec["label"]) for slug, spec in DEEPSEEK_MODEL_SPECS.items()
]

DEEPSEEK_MODEL_ALIASES: dict[str, str] = {
    "deepseek-chat": "deepseek:deepseek-chat",
    "deepseek-reasoner": "deepseek:deepseek-reasoner",
    "deepseek-r1": "deepseek:deepseek-reasoner",
    "deepseek-r1-0528": "deepseek:deepseek-reasoner",
    "deepseek-v4-pro": "deepseek:deepseek-v4-pro",
    "deepseek-v4-flash": "deepseek:deepseek-v4-flash",
    "deepseek-v4-flash-think": "deepseek:deepseek-v4-flash-think",
}


def resolve_deepseek_api(model_override: str | None) -> tuple[str, bool]:
    """解析 DeepSeek 调用参数 → (api_model, enable_thinking)。"""
    raw = (model_override or "").strip()
    if raw.startswith("deepseek:"):
        raw = raw.split(":", 1)[1]
    if not raw:
        raw = "deepseek-chat"
    spec = DEEPSEEK_MODEL_SPECS.get(raw)
    if spec:
        return str(spec["api_model"]), bool(spec.get("thinking"))
    # 未知 slug：reasoner 系默认开思考，其余直连 API
    thinking = raw == "deepseek-reasoner" or "reasoner" in raw or raw.endswith("-think")
    return raw, thinking
