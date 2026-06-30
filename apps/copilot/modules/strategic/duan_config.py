"""段永平双闸配置加载 · duan_node_gates.yaml / gates.yaml / cognition_gates.yaml。

[Ref: 32_ §2.4.9.a · §2.4.9.b · §2.4.9.c]
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    path = _CONFIG_ROOT / name
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_duan_node_gates() -> dict[str, Any]:
    return _load_yaml("duan_node_gates.yaml")


@lru_cache(maxsize=1)
def load_gates() -> dict[str, Any]:
    return _load_yaml("gates.yaml")


@lru_cache(maxsize=1)
def load_cognition_gates() -> dict[str, Any]:
    return _load_yaml("cognition_gates.yaml")


def z0_cvm_gates() -> dict[str, Any]:
    return (load_gates().get("z0_cvm") or {})


def clear_config_cache() -> None:
    load_duan_node_gates.cache_clear()
    load_gates.cache_clear()
    load_cognition_gates.cache_clear()
