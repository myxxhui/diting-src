"""D3 监控字典消费端 — 读 Redis `monitor:{symbol}:dict:*`。

[Ref: 03_/_共享规约/20_监控字典规约.md §消费端 MC1~MC5]
[Ref: 03_/03_维度三/.../step_03 P5/P6/P7]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REDIS_PREFIX = "monitor"


class MonitorDictReader:
    """只读消费 monitor 字典；触发 alert 时可更新 last_hit_at。"""

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    def has_monitor_dict(self, symbol: str) -> bool:
        raw = self.redis.get(f"{_REDIS_PREFIX}:{symbol}:dict:_meta")
        return raw is not None

    def load_meta(self, symbol: str) -> Optional[dict[str, Any]]:
        raw = self.redis.get(f"{_REDIS_PREFIX}:{symbol}:dict:_meta")
        if not raw:
            return None
        return json.loads(raw)

    def load_fields(self, symbol: str, *, probe_id: str | None = None) -> list[dict[str, Any]]:
        """加载 symbol 下全部监控字段；可按 probe_id 过滤 P5/P6/P7。"""
        meta = self.load_meta(symbol)
        if meta is None:
            logger.debug("[monitor_dict] symbol=%s 无 _meta，跳过", symbol)
            return []

        pattern = f"{_REDIS_PREFIX}:{symbol}:dict:*"
        fields: list[dict[str, Any]] = []
        for key in self.redis.scan_iter(match=pattern, count=100):
            if key.endswith(":_meta"):
                continue
            raw = self.redis.get(key)
            if not raw:
                continue
            try:
                doc = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if probe_id and doc.get("probe_id") != probe_id:
                continue
            if doc.get("status") == "stale":
                continue
            fields.append(doc)
        return fields

    def record_hit(self, symbol: str, field_id: str) -> bool:
        """MC3: 触发 alert 后更新 last_hit_at。"""
        key = f"{_REDIS_PREFIX}:{symbol}:dict:{field_id}"
        raw = self.redis.get(key)
        if not raw:
            return False
        doc = json.loads(raw)
        doc["last_hit_at"] = datetime.now(timezone.utc).isoformat()
        self.redis.set(key, json.dumps(doc, ensure_ascii=False))
        return True

    def weight_summary(self, symbol: str) -> dict[str, Any]:
        """探针调度权重摘要：active 字段数 / 按 probe_id 分布。"""
        fields = self.load_fields(symbol)
        by_probe: dict[str, int] = {"P5": 0, "P6": 0, "P7": 0}
        for f in fields:
            pid = f.get("probe_id")
            if pid in by_probe:
                by_probe[pid] += 1
        return {
            "symbol": symbol,
            "active_fields": len(fields),
            "by_probe_id": by_probe,
            "has_meta": self.has_monitor_dict(symbol),
        }
