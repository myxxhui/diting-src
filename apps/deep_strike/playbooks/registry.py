"""剧本注册表。[Ref: step_04]"""
from __future__ import annotations

from apps.deep_strike.playbooks.base_playbook import BasePlaybook
from apps.deep_strike.playbooks.profit_capture.playbook import ProfitCapturePlaybook

_REGISTRY: dict[str, BasePlaybook] = {}


def _ensure_registered() -> None:
    if "profit_capture" not in _REGISTRY:
        _REGISTRY["profit_capture"] = ProfitCapturePlaybook()


def get(playbook_id: str) -> BasePlaybook:
    _ensure_registered()
    pb = _REGISTRY.get(playbook_id)
    if pb is None:
        raise KeyError(playbook_id)
    return pb


def list_playbooks() -> list[dict]:
    _ensure_registered()
    return [
        {"id": p.id, "cn": p.cn_name, "priority": p.priority, "status": "ready"}
        for p in _REGISTRY.values()
    ]
