"""执行区探针注册表 · 逐项启用（当前 #15+#16+#17+#18）。

[Ref: 28_ §4.5]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# 权威启用列表（T0/T1/前端覆盖率均以此为准）
PROBE_KEYS: tuple[str, ...] = (
    "qmt_atr_trailing",
    "volume_price_div",
    "smart_money_flow",
    "level2_super_order",
)

L3_KEYS: tuple[str, ...] = ()
L4_KEYS: tuple[str, ...] = PROBE_KEYS


def load_profile(profile: str = "601138") -> dict[str, Any]:
    # 镜像内：apps/copilot/config/executing_profiles；本地开发仍可读 data/config
    pkg_root = Path(__file__).resolve().parents[2]
    root = pkg_root / "config" / "executing_profiles"
    if not root.is_dir():
        root = Path(__file__).resolve().parents[4] / "data" / "config" / "executing_profiles"
    path = root / f"{profile}.yaml"
    if not path.is_file():
        return {"symbol": "601138", "probes": {}}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
