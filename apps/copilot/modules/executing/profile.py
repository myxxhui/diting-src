"""执行区 profile YAML 加载。

[Ref: 28_ §4.5]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from apps.copilot.modules.executing.probe_keys import (
    L3_KEYS,
    L4_KEYS,
    OPTIONAL_EVENT_PROBE_KEYS,
    PROBE_KEYS,
)

__all__ = [
    "PROBE_KEYS",
    "L3_KEYS",
    "L4_KEYS",
    "OPTIONAL_EVENT_PROBE_KEYS",
    "load_profile",
]


def load_profile(profile: str = "601138") -> dict[str, Any]:
    pkg_root = Path(__file__).resolve().parents[2]
    root = pkg_root / "config" / "executing_profiles"
    if not root.is_dir():
        root = Path(__file__).resolve().parents[4] / "data" / "config" / "executing_profiles"
    path = root / f"{profile}.yaml"
    if not path.is_file():
        return {"symbol": "601138", "probes": {}}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
