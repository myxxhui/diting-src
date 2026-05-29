"""exit_engine 协议 yaml 配置加载.

[Ref: 03_/04_维度四/.../step_03_SP1止损协议.md]
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parent / "configs" / "exit_protocols.yaml"


def _config_path() -> Path:
    env = os.environ.get("EXIT_PROTOCOLS_YAML", "").strip()
    if env:
        p = Path(env)
        return p if p.is_absolute() else Path.cwd() / p
    return _DEFAULT_PATH


def load_exit_protocols() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def load_sp1_config() -> dict[str, Any]:
    root = load_exit_protocols()
    sp1 = root.get("sp1_stop_loss") or {}
    return sp1 if isinstance(sp1, dict) else {}


def load_sp2_config() -> dict[str, Any]:
    root = load_exit_protocols()
    sp2 = root.get("sp2_take_profit") or {}
    return sp2 if isinstance(sp2, dict) else {}
