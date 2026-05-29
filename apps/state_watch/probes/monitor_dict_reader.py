"""D3 物理量探针的监控字典消费器（Redis monitor:{symbol}:dict:* 读端）。

实现共享规约 20 §五消费端契约 MC1～MC5：
  - MC1：消费前先读 `monitor:{symbol}:dict:_meta`，不存在则 skip 不阻塞；
  - MC2：本模块仅负责 Read + last_hit_at 写回；轮询频率由调用方按 polling_frequency 控制；
  - MC3：alert 命中后调 `mark_field_hit()` 写回 `last_hit_at`；
  - MC4：探针产 `events:monitor:health_change` 时，须带回 `monitor_field_id`（调用方处理）；
  - MC5：本模块**只读**业务字段，不修改 monitor:* 任何业务列。

[Ref: 03_/_共享规约/20_监控字典规约.md §五]
[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

logger = logging.getLogger(__name__)

_PROBE_LITERAL = Literal["P5", "P6", "P7"]
_REDIS_PREFIX = "monitor"


@dataclass(frozen=True)
class MonitorFieldView:
    """监控字典字段的消费端只读视图（Pydantic schema 的精简快照）。"""

    field_id: str
    probe_id: str
    metric_name: str
    data_source_type: str  # STRUCT_DATA_API / WEB_SCRAPING
    source_api: str | None
    source_url: str | None
    specific_target: str
    keywords: tuple[str, ...]
    alert_threshold: str
    alert_threshold_struct: dict[str, Any]  # operator / value / window_days
    polling_frequency: str
    mapped_logic_chain_nodes: tuple[str, ...]
    status: str
    symbol: str
    thesis_card_id: str
    raw_key: str

    @classmethod
    def from_redis_payload(cls, key: str, payload: dict[str, Any]) -> "MonitorFieldView":
        return cls(
            field_id=str(payload.get("field_id", "")),
            probe_id=str(payload.get("probe_id", "")),
            metric_name=str(payload.get("metric_name", "")),
            data_source_type=str(payload.get("data_source_type", "")),
            source_api=payload.get("source_api"),
            source_url=payload.get("source_url"),
            specific_target=str(payload.get("specific_target", "")),
            keywords=tuple(payload.get("keywords") or ()),
            alert_threshold=str(payload.get("alert_threshold", "")),
            alert_threshold_struct=dict(payload.get("alert_threshold_struct") or {}),
            polling_frequency=str(payload.get("polling_frequency", "daily")),
            mapped_logic_chain_nodes=tuple(payload.get("mapped_logic_chain_nodes") or ()),
            status=str(payload.get("status", "active")),
            symbol=str(payload.get("symbol", "")),
            thesis_card_id=str(payload.get("thesis_card_id", "")),
            raw_key=key,
        )


class MonitorDictReader:
    """共享规约 20 §5.2 消费端时序的具体实现（同步 redis-py）。

    用法（典型 D3 探针调用）：

        reader = MonitorDictReader(redis_client)
        if not reader.has_dict(symbol):
            return {"status": "no_monitor_dict"}  # MC1：不阻塞
        fields = reader.fields_for_probe(symbol, "P5")
        # ... 按 fields 调真源（AkShare/Playwright）...
        if matched:
            reader.mark_field_hit(symbol, field.field_id)  # MC3
    """

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    # ------------------------------------------------------------------
    # MC1：读 _meta 判断 symbol 是否有字典
    # ------------------------------------------------------------------

    def has_dict(self, symbol: str) -> bool:
        """检查 monitor:{symbol}:dict:_meta 是否存在（MC1）。"""
        return bool(self.redis.exists(f"{_REDIS_PREFIX}:{symbol}:dict:_meta"))

    def get_meta(self, symbol: str) -> dict[str, Any] | None:
        raw = self.redis.get(f"{_REDIS_PREFIX}:{symbol}:dict:_meta")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError) as exc:
            logger.warning("[monitor_dict] meta 解析失败 symbol=%s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # 字段读取（按 probe_id 过滤）
    # ------------------------------------------------------------------

    def list_field_keys(self, symbol: str) -> list[str]:
        """返回 monitor:{symbol}:dict:* 下所有字段 key（排除 _meta）。"""
        pattern = f"{_REDIS_PREFIX}:{symbol}:dict:*"
        keys = self.redis.keys(pattern) or []
        # redis-py decode_responses=True 直接返回 str；False 返回 bytes
        out: list[str] = []
        for k in keys:
            ks = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            if ks.endswith(":dict:_meta"):
                continue
            out.append(ks)
        return out

    def fields_for_probe(
        self, symbol: str, probe_id: _PROBE_LITERAL, *, only_active: bool = True
    ) -> list[MonitorFieldView]:
        """按 probe_id 过滤字段；MC1：无 _meta 时返回空列表（不阻塞）。"""
        if not self.has_dict(symbol):
            logger.debug("[monitor_dict] symbol=%s 无 _meta，跳过（MC1）", symbol)
            return []
        out: list[MonitorFieldView] = []
        for key in self.list_field_keys(symbol):
            raw = self.redis.get(key)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError) as exc:
                logger.warning("[monitor_dict] %s 解析失败: %s", key, exc)
                continue
            if str(payload.get("probe_id", "")).upper() != probe_id:
                continue
            if only_active and payload.get("status", "active") != "active":
                continue
            out.append(MonitorFieldView.from_redis_payload(key, payload))
        return out

    def all_active_fields(self, symbol: str) -> list[MonitorFieldView]:
        """按 symbol 列出全部 active 字段（任意 probe）。"""
        if not self.has_dict(symbol):
            return []
        out: list[MonitorFieldView] = []
        for key in self.list_field_keys(symbol):
            raw = self.redis.get(key)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if payload.get("status", "active") != "active":
                continue
            out.append(MonitorFieldView.from_redis_payload(key, payload))
        return out

    # ------------------------------------------------------------------
    # MC3：alert 命中写回 last_hit_at
    # ------------------------------------------------------------------

    def mark_field_hit(
        self,
        symbol: str,
        field_id: str,
        *,
        at: datetime | None = None,
    ) -> bool:
        """触发 alert 后写回 last_hit_at；防 GC 误删（MC3）。

        Returns True 表示成功更新；False 表示字段不存在（不抛错，调用方自决）。
        """
        key = f"{_REDIS_PREFIX}:{symbol}:dict:{field_id}"
        raw = self.redis.get(key)
        if not raw:
            logger.warning("[monitor_dict] mark_field_hit: key 不存在 %s", key)
            return False
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            logger.warning("[monitor_dict] mark_field_hit: 解析失败 %s: %s", key, exc)
            return False
        # MC5：只更新 last_hit_at，业务字段不动
        payload["last_hit_at"] = (at or datetime.now(timezone.utc)).isoformat()
        self.redis.set(key, json.dumps(payload, ensure_ascii=False))
        return True


# ──────────────────────────────────────────────────────────────────────
# 工具：关键词聚合（探针匹配用）
# ──────────────────────────────────────────────────────────────────────


def aggregate_keywords(fields: Sequence[MonitorFieldView]) -> tuple[str, ...]:
    """从多条 MonitorFieldView 抽出去重 keywords，按出现顺序保序。"""
    seen: set[str] = set()
    out: list[str] = []
    for f in fields:
        for k in f.keywords:
            kk = k.strip()
            if not kk or kk in seen:
                continue
            seen.add(kk)
            out.append(kk)
    return tuple(out)


def aggregate_source_urls(fields: Sequence[MonitorFieldView]) -> tuple[str, ...]:
    """从 WEB_SCRAPING 字段抽 source_url 列表（用于 P5/P7 抓取入口）。"""
    seen: set[str] = set()
    out: list[str] = []
    for f in fields:
        url = (f.source_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return tuple(out)
