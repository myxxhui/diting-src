"""监控字典消费器单测（MC1～MC5）。

[Ref: 03_/_共享规约/20_监控字典规约.md §五]
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from apps.state_watch.probes.monitor_dict_reader import (
    MonitorDictReader,
    MonitorFieldView,
    aggregate_keywords,
    aggregate_source_urls,
)


class _FakeRedis:
    """最小同步 redis-py 兼容 Mock（仅 GET/SET/EXISTS/KEYS）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str) -> bool:
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def keys(self, pattern: str) -> list[str]:
        # 仅支持末尾 * 的简化匹配
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self.store if k.startswith(prefix)]
        return [k for k in self.store if k == pattern]


def _seed_dict(redis: _FakeRedis, symbol: str, fields: list[dict[str, Any]]) -> None:
    redis.set(
        f"monitor:{symbol}:dict:_meta",
        json.dumps({"count": len(fields), "last_updated": "2026-05-24T00:00:00Z"}),
    )
    for f in fields:
        redis.set(
            f"monitor:{symbol}:dict:{f['field_id']}",
            json.dumps({"symbol": symbol, **f}),
        )


def _base_field(field_id: str, probe_id: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "field_id": field_id,
        "probe_id": probe_id,
        "metric_name": f"metric_{field_id}",
        "data_source_type": "WEB_SCRAPING",
        "source_api": None,
        "source_url": "https://www.ccgp.gov.cn",
        "specific_target": "test target",
        "keywords": kwargs.get("keywords", ["液冷", "光模块"]),
        "alert_threshold": "test",
        "alert_threshold_struct": {"operator": "gt", "value": 1.0, "window_days": 7},
        "polling_frequency": kwargs.get("polling_frequency", "daily"),
        "mapped_logic_chain_nodes": ["node_x"],
        "status": kwargs.get("status", "active"),
        "thesis_card_id": "thesis_test",
        "last_hit_at": None,
    }


# ──────────────────────────────────────────────────────────────────────
# MC1：无 _meta 不阻塞
# ──────────────────────────────────────────────────────────────────────


def test_has_dict_false_when_no_meta():
    redis = _FakeRedis()
    reader = MonitorDictReader(redis)
    assert reader.has_dict("999999") is False
    assert reader.fields_for_probe("999999", "P5") == []


def test_has_dict_true_when_meta_exists():
    redis = _FakeRedis()
    _seed_dict(redis, "300308", [_base_field("f1", "P5")])
    reader = MonitorDictReader(redis)
    assert reader.has_dict("300308") is True


# ──────────────────────────────────────────────────────────────────────
# 按 probe_id 过滤
# ──────────────────────────────────────────────────────────────────────


def test_fields_for_probe_filter():
    redis = _FakeRedis()
    _seed_dict(redis, "300308", [
        _base_field("f1_p5", "P5"),
        _base_field("f2_p6", "P6"),
        _base_field("f3_p7", "P7"),
        _base_field("f4_p5", "P5"),
    ])
    reader = MonitorDictReader(redis)

    p5_fields = reader.fields_for_probe("300308", "P5")
    p6_fields = reader.fields_for_probe("300308", "P6")
    p7_fields = reader.fields_for_probe("300308", "P7")

    assert {f.field_id for f in p5_fields} == {"f1_p5", "f4_p5"}
    assert {f.field_id for f in p6_fields} == {"f2_p6"}
    assert {f.field_id for f in p7_fields} == {"f3_p7"}


def test_only_active_filter():
    redis = _FakeRedis()
    _seed_dict(redis, "300308", [
        _base_field("active_f", "P5", status="active"),
        _base_field("stale_f", "P5", status="stale"),
    ])
    reader = MonitorDictReader(redis)

    active = reader.fields_for_probe("300308", "P5")
    assert {f.field_id for f in active} == {"active_f"}

    both = reader.fields_for_probe("300308", "P5", only_active=False)
    assert {f.field_id for f in both} == {"active_f", "stale_f"}


# ──────────────────────────────────────────────────────────────────────
# MC3：last_hit_at 写回
# ──────────────────────────────────────────────────────────────────────


def test_mark_field_hit_updates_last_hit_at():
    redis = _FakeRedis()
    _seed_dict(redis, "300308", [_base_field("f1", "P5")])
    reader = MonitorDictReader(redis)

    at = datetime(2026, 5, 24, 10, 0, 0, tzinfo=timezone.utc)
    assert reader.mark_field_hit("300308", "f1", at=at) is True

    raw = redis.get("monitor:300308:dict:f1")
    payload = json.loads(raw)
    assert payload["last_hit_at"] == at.isoformat()
    # MC5：业务字段未变
    assert payload["probe_id"] == "P5"
    assert payload["keywords"] == ["液冷", "光模块"]


def test_mark_field_hit_returns_false_for_missing_key():
    redis = _FakeRedis()
    reader = MonitorDictReader(redis)
    assert reader.mark_field_hit("999999", "nonexistent") is False


# ──────────────────────────────────────────────────────────────────────
# 聚合工具
# ──────────────────────────────────────────────────────────────────────


def test_aggregate_keywords_dedup_keep_order():
    fields = [
        MonitorFieldView.from_redis_payload("k1", _base_field("f1", "P5", keywords=["A", "B"])),
        MonitorFieldView.from_redis_payload("k2", _base_field("f2", "P5", keywords=["B", "C"])),
        MonitorFieldView.from_redis_payload("k3", _base_field("f3", "P5", keywords=["A", "D"])),
    ]
    assert aggregate_keywords(fields) == ("A", "B", "C", "D")


def test_aggregate_source_urls_dedup():
    f1 = MonitorFieldView.from_redis_payload(
        "k1", {**_base_field("f1", "P5"), "source_url": "https://a.com"}
    )
    f2 = MonitorFieldView.from_redis_payload(
        "k2", {**_base_field("f2", "P5"), "source_url": "https://a.com"}
    )
    f3 = MonitorFieldView.from_redis_payload(
        "k3", {**_base_field("f3", "P5"), "source_url": "https://b.com"}
    )
    urls = aggregate_source_urls([f1, f2, f3])
    assert urls == ("https://a.com", "https://b.com")


# ──────────────────────────────────────────────────────────────────────
# B4 E2E：监控字典 → 探针 → 命中写回
# ──────────────────────────────────────────────────────────────────────


def test_e2e_monitor_keywords_passed_to_p5_probe():
    """B4 端到端：reader 读取 → keywords 聚合 → 传入 P5 探针构造器。"""
    from apps.state_watch.probes.physical.p5_tender import TenderProbe

    redis = _FakeRedis()
    _seed_dict(redis, "300308", [
        _base_field("f1", "P5", keywords=["光模块", "800G"]),
        _base_field("f2", "P5", keywords=["液冷", "光模块"]),  # 重复 keyword
    ])
    reader = MonitorDictReader(redis)

    fields = reader.fields_for_probe("300308", "P5")
    keywords = aggregate_keywords(fields)
    assert keywords == ("光模块", "800G", "液冷")

    probe = TenderProbe(monitor_keywords=keywords)
    assert probe.monitor_keywords == ("光模块", "800G", "液冷")

    # 验证 pattern 包含监控字典关键词
    assert probe._pattern.search("某公司光模块订单 800G 中标公告")
    assert probe._pattern.search("液冷数据中心建设项目")
    # 原有招标关键词仍能命中
    assert probe._pattern.search("XX 项目招标公告")


def test_e2e_no_monitor_dict_no_extra_keywords_for_probe():
    """无监控字典时探针行为不变（默认招标关键词）。"""
    from apps.state_watch.probes.physical.p5_tender import TenderProbe

    redis = _FakeRedis()
    reader = MonitorDictReader(redis)

    fields = reader.fields_for_probe("999999", "P5")  # MC1 跳过，返回空
    keywords = aggregate_keywords(fields)
    assert keywords == ()

    probe = TenderProbe(monitor_keywords=keywords)
    # 招标默认关键词依旧生效
    assert probe._pattern.search("XX 项目招标公告")
    # 没有传入的字典关键词时不该命中无关词
    assert probe._pattern.search("光模块订单签订") is None


def test_e2e_p7_keyword_match_helper():
    """P7 的 _matches_monitor_keywords 直接验。"""
    from apps.state_watch.probes.physical.p7_capacity import CapacityProbe

    probe = CapacityProbe(monitor_keywords=("产能爬坡", "新增产能"))
    assert probe._matches_monitor_keywords("公司公告：产能爬坡顺利推进") is True
    assert probe._matches_monitor_keywords("无关公告") is False

    probe_empty = CapacityProbe()
    assert probe_empty._matches_monitor_keywords("产能爬坡") is False
