"""monitor_dict writer/reader 单测（mock Redis，无需真实实例）。

[Ref: 03_/_共享规约/20_监控字典规约.md]
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from apps.deep_strike.lighthouse.monitor_dict_writer import MonitorDictWriter, validate_field_payload
from apps.deep_strike.lighthouse.schemas import (
    AlertThresholdStruct,
    CallMetadata,
    MonitorField,
    MonitorMatrix,
)
from apps.state_watch.monitor_dict_reader import MonitorDictReader


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def scan_iter(self, match: str, count: int = 100):
        prefix = match.replace("*", "")
        for k in self.store:
            if k.startswith(prefix.rstrip(":")) and not k.endswith(":_meta"):
                yield k


def _sample_matrix() -> MonitorMatrix:
    meta = CallMetadata(
        model_name="test-opus",
        prompt_template_id="the_architect_v1",
        generated_at=datetime.utcnow(),
    )
    field = MonitorField(
        field_id="field_test_bid",
        probe_id="P5",
        metric_name="液冷招标金额",
        data_source_type="WEB_SCRAPING",
        source_api=None,
        source_url="https://www.ccgp.gov.cn",
        specific_target="ccgp 液冷关键词",
        keywords=["液冷", "智算中心"],
        alert_threshold="30天累计 > 营收20%",
        alert_threshold_struct=AlertThresholdStruct(operator="sum_pct", value=0.2, window_days=30),
        polling_frequency="daily",
        mapped_logic_chain_nodes=["node_supply_demand_mismatch"],
    )
    return MonitorMatrix(
        thesis_card_id="thesis_002837_liquid_cooling_20260523",
        target_company="英维克 (002837)",
        symbol="002837",
        monitor_matrix=[field],
        metadata=meta,
    )


def test_validate_field_payload_ok():
    payload = {
        "field_id": "field_x",
        "probe_id": "P5",
        "metric_name": "测试指标名",
        "data_source_type": "WEB_SCRAPING",
        "source_url": "https://example.com",
        "specific_target": "关键词组",
        "keywords": ["液冷"],
        "alert_threshold": "累计超过阈值",
        "alert_threshold_struct": {"operator": "gt", "value": 1.0, "window_days": 7},
        "polling_frequency": "daily",
        "mapped_logic_chain_nodes": ["node_x"],
        "status": "active",
    }
    assert validate_field_payload(payload) == []


def test_validate_field_payload_ma4_fail():
    payload = {
        "field_id": "field_x",
        "probe_id": "P5",
        "metric_name": "测试指标名",
        "data_source_type": "WEB_SCRAPING",
        "specific_target": "无来源",
        "alert_threshold": "累计超过阈值",
        "alert_threshold_struct": {"operator": "gt", "value": 1.0, "window_days": 7},
        "polling_frequency": "daily",
        "mapped_logic_chain_nodes": ["node_x"],
        "status": "active",
    }
    errs = validate_field_payload(payload)
    assert any("MA4" in e for e in errs)


def test_writer_and_reader_roundtrip():
    redis = _FakeRedis()
    matrix = _sample_matrix()
    result = MonitorDictWriter(redis).write(matrix)
    assert result["written"] == ["field_test_bid"]

    reader = MonitorDictReader(redis)
    assert reader.has_monitor_dict("002837") is True
    fields = reader.load_fields("002837", probe_id="P5")
    assert len(fields) == 1
    assert fields[0]["probe_id"] == "P5"
    assert reader.record_hit("002837", "field_test_bid") is True
    updated = json.loads(redis.get("monitor:002837:dict:field_test_bid"))
    assert updated["last_hit_at"] is not None
