"""执行区 profile YAML 加载。

[Ref: 28_ §1.2 · §2.1.1]
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
    "profile_l3_keys",
    "profile_enabled_probe_keys",
    "profile_expected_probe_count",
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


def profile_l3_keys(profile: dict[str, Any]) -> tuple[str, ...]:
    """Profile YAML `l3_probes` 键列表（可变长 · 顺序稳定）。"""
    l3 = profile.get("l3_probes") or {}
    if not isinstance(l3, dict):
        return ()
    return tuple(k for k in l3 if isinstance(k, str))


def profile_enabled_l4_keys(profile: dict[str, Any]) -> tuple[str, ...]:
    """Profile YAML `probes` 中 enabled!=false 的 L4 键；缺省按 PROBE_KEYS 全启用。"""
    probes = profile.get("probes")
    if not isinstance(probes, dict) or not probes:
        return PROBE_KEYS
    enabled: list[str] = []
    for key in PROBE_KEYS:
        cfg = probes.get(key)
        if cfg is None:
            enabled.append(key)
        elif isinstance(cfg, dict) and cfg.get("enabled") is False:
            continue
        else:
            enabled.append(key)
    return tuple(enabled)


def profile_enabled_probe_keys(profile: dict[str, Any]) -> tuple[str, ...]:
    """Profile 期望采集的全量探针 = l3_probes + 已启用 L4。"""
    return profile_l3_keys(profile) + profile_enabled_l4_keys(profile)


def profile_expected_probe_count(profile: dict[str, Any]) -> int:
    return len(profile_enabled_probe_keys(profile))
