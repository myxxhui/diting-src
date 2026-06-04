"""ModelProfile 路由 + T2 开关。

[Ref: step_14 · 25_ §4 ModelProfile]
"""
from __future__ import annotations

import os
from typing import Any

DEFAULT_PROFILES: list[dict[str, Any]] = [
    {
        "workspace": "radar",
        "task": "t1_distill",
        "tier": "T1",
        "model_id": "deepseek:deepseek-chat",
        "override_allowed": True,
        "pinned": False,
    },
    {
        "workspace": "radar",
        "task": "t2_assess",
        "tier": "T2",
        "model_id": "anthropic:opus",
        "override_allowed": True,
        "pinned": False,
    },
]


def radar_t2_enabled() -> bool:
    return os.getenv("RADAR_T2_ENABLED", "false").lower() in ("1", "true", "yes")


def radar_t1_mode() -> str:
    """rule | deepseek | auto（有 DEEPSEEK_API_KEY 则用 deepseek）。"""
    return os.getenv("RADAR_T1_MODE", "auto").strip().lower()


def radar_t1_uses_deepseek() -> bool:
    mode = radar_t1_mode()
    if mode == "rule":
        return False
    if mode == "deepseek":
        return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
    return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())


def t1_step_label() -> str:
    if radar_t1_uses_deepseek():
        mid = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
        return f"T1 DeepSeek 事实矩阵压缩（{mid}）"
    return "T1 规则事实矩阵压缩"


def _default_t1_model_id() -> str:
    if radar_t1_uses_deepseek():
        mid = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
        return f"deepseek:{mid}"
    return "rule:context_matrix"


def resolve_model(workspace: str, task: str) -> dict[str, Any]:
    for p in DEFAULT_PROFILES:
        if p["workspace"] == workspace and p["task"] == task:
            out = dict(p)
            if task == "t1_distill":
                out["model_id"] = _default_t1_model_id()
            return out
    return {"workspace": workspace, "task": task, "tier": "T0", "model_id": "rule:default"}
