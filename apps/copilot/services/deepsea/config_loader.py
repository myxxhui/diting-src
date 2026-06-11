"""加载 probe_registry YAML · 实现路由真相源。

[Ref: 28_ §2.13]
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_REGISTRY_ROOT = Path(__file__).resolve().parents[4] / "data" / "config" / "probe_registry"


@lru_cache(maxsize=16)
def load_probe_registry(symbol: str) -> dict[str, Any]:
    sym = str(symbol).zfill(6)[-6:]
    path = _REGISTRY_ROOT / f"{sym}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"probe_registry 不存在: {path}")
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("#"):
        raw = raw.split("\n\n", 1)[-1]
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"probe_registry 格式无效: {path}")
    return data


def get_l3_probe_config(symbol: str, probe_key: str) -> dict[str, Any]:
    reg = load_probe_registry(symbol)
    l3 = reg.get("l3_probes") or {}
    cfg = l3.get(probe_key)
    if not isinstance(cfg, dict):
        raise KeyError(f"{symbol} l3_probes 无 {probe_key}")
    return cfg


def get_cohort_probe_keys(symbol: str, cache_group: str) -> list[str]:
    reg = load_probe_registry(symbol)
    groups = reg.get("batch_groups") or {}
    for _gid, meta in groups.items():
        if not isinstance(meta, dict):
            continue
        if _gid == cache_group or meta.get("cache_group") == cache_group:
            keys = meta.get("probe_keys") or []
            return [str(k) for k in keys]
    # 回退：扫描 l3 同 cache_group
    l3 = reg.get("l3_probes") or {}
    return [k for k, v in l3.items() if isinstance(v, dict) and v.get("cache_group") == cache_group]


__all__ = ["load_probe_registry", "get_l3_probe_config", "get_cohort_probe_keys"]
