"""The Architect 监控字典生产端 — 写 Redis `monitor:{symbol}:dict:*`。

写前 jsonschema 校验（共享规约 20 MA1）；失败拒绝写入并返回 errors。

[Ref: 03_/_共享规约/20_监控字典规约.md]
[Ref: 03_/02_维度二/.../step_02 §3.5.5]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.deep_strike.lighthouse.schemas import MonitorField, MonitorMatrix

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "data/sniffer/schemas/monitor_field.schema.json"
_REDIS_PREFIX = "monitor"


def _load_validator():
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema 未安装；pip install jsonschema") from exc

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def field_to_redis_payload(matrix: MonitorMatrix, field: MonitorField) -> dict[str, Any]:
    """单字段 → Redis JSON 文档。"""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "field_id": field.field_id,
        "probe_id": field.probe_id,
        "metric_name": field.metric_name,
        "data_source_type": field.data_source_type,
        "source_api": field.source_api,
        "source_url": field.source_url,
        "specific_target": field.specific_target,
        "keywords": field.keywords,
        "alert_threshold": field.alert_threshold,
        "alert_threshold_struct": field.alert_threshold_struct.model_dump(),
        "polling_frequency": field.polling_frequency,
        "mapped_logic_chain_nodes": field.mapped_logic_chain_nodes,
        "status": field.status,
        "thesis_card_id": matrix.thesis_card_id,
        "symbol": matrix.symbol,
        "target_company": matrix.target_company,
        "generated_by": {
            "model_name": matrix.metadata.model_name,
            "prompt_template_id": matrix.metadata.prompt_template_id,
            "generated_at": matrix.metadata.generated_at.isoformat(),
            "tokens_used": matrix.metadata.tokens_in + matrix.metadata.tokens_out,
        },
        "created_at": now,
        "last_hit_at": None,
    }


def validate_field_payload(payload: dict[str, Any]) -> list[str]:
    """返回校验错误列表；空列表 = 通过。"""
    validator = _load_validator()
    errors = sorted({e.message for e in validator.iter_errors(payload)})
    # MA4: HS Code / source_url / keywords 至少一项
    if not payload.get("source_api") and not payload.get("source_url") and not payload.get("keywords"):
        errors.append("MA4: source_api / source_url / keywords 至少一项非空")
    return errors


class MonitorDictWriter:
    """写 Redis monitor 字典（同步 redis-py）。"""

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    def write(self, matrix: MonitorMatrix) -> dict[str, Any]:
        symbol = matrix.symbol
        written: list[str] = []
        rejected: list[dict[str, str]] = []

        for field in matrix.monitor_matrix:
            payload = field_to_redis_payload(matrix, field)
            errs = validate_field_payload(payload)
            if errs:
                rejected.append({"field_id": field.field_id, "errors": "; ".join(errs)})
                logger.warning("[monitor_dict] 拒绝写入 %s: %s", field.field_id, errs)
                continue
            key = f"{_REDIS_PREFIX}:{symbol}:dict:{field.field_id}"
            self.redis.set(key, json.dumps(payload, ensure_ascii=False))
            written.append(field.field_id)

        meta = {
            "count": len(written),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source_thesis_card_id": matrix.thesis_card_id,
            "rejected_count": len(rejected),
        }
        self.redis.set(
            f"{_REDIS_PREFIX}:{symbol}:dict:_meta",
            json.dumps(meta, ensure_ascii=False),
        )

        return {
            "symbol": symbol,
            "written": written,
            "rejected": rejected,
            "meta_key": f"{_REDIS_PREFIX}:{symbol}:dict:_meta",
        }
