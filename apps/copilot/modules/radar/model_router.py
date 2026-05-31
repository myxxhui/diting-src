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
        "model_id": "rule:context_matrix",
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


def resolve_model(workspace: str, task: str) -> dict[str, Any]:
    for p in DEFAULT_PROFILES:
        if p["workspace"] == workspace and p["task"] == task:
            return dict(p)
    return {"workspace": workspace, "task": task, "tier": "T0", "model_id": "rule:default"}
