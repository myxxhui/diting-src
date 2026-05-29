"""加载 market_phase_rules.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DEFAULT = Path(__file__).resolve().parents[3] / "data" / "config" / "market_phase_rules.yaml"


@lru_cache(maxsize=1)
def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else _DEFAULT
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}
