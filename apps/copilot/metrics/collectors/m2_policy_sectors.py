"""Z0-M2 政策赛道支路 · DeepSea PG 契约（indicator_state + doc_registry · no-mock）。

[Ref: 29_ §5.1 · 34_ §3.2 · 废止 OpenSearch/BM25]
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.copilot.services.deepsea.policy_reader import read_policy_sectors_from_pg


def _ok(data: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "metric_id": "M.sector.policy_direction",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "source": source,
    }


def _err(detail: str) -> dict[str, Any]:
    return {"status": "error", "metric_id": "M.sector.policy_direction", "detail": detail}


def collect_policy_sector_direction(*, top_n: int = 10) -> dict[str, Any]:
    """读 DeepSea PG · T1 状态快照优先 · doc_registry 政策元数据次之。"""
    result = read_policy_sectors_from_pg(top_n=top_n)
    if not result.get("ok"):
        return _err(str(result.get("detail") or "DeepSea PG 无政策赛道数据"))

    layer = result.get("source_layer") or "deepsea_pg"
    return _ok(
        {
            "top_sectors": result.get("top_sectors") or [],
            "evidence": result.get("evidence") or [],
            "probe_key": result.get("probe_key"),
            "source_layer": layer,
        },
        f"deepsea:pg:{layer}",
    )
