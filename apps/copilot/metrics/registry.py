"""加载 metric_registry.yaml。

[Ref: 34_ §3 · 32_ §13 步骤 0]
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "config" / "metrics" / "metric_registry.yaml"
)


@lru_cache(maxsize=1)
def load_metric_registry() -> dict[str, Any]:
    if not _REGISTRY_PATH.is_file():
        return {"schema_version": "1.0", "metrics": [], "jobs": {}}
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def list_z0_job_ids() -> list[str]:
    jobs = load_metric_registry().get("jobs") or {}
    return list(jobs.keys())
