from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.copilot.main import app
from apps.copilot.modules.planning import sandbox as sb


def _fake_plan_json() -> str:
    probes = []
    dims = [
        "维度 1：宏观政策与产业周期",
        "维度 2：上游供给与成本约束",
        "维度 3：下游需求与资本开支",
        "维度 4：微观高频与财务印证",
        "维度 5：竞争格局与壁垒探测",
    ]
    for i, d in enumerate(dims, start=1):
        probes.append(
            {
                "dimension": d,
                "target_data_desc": f"探针{i}目标数据",
                "primary_source_name": f"官方源{i}",
                "why_this_source": "因为权威",
                "alternative_sources": ["备选源A"],
                "collection_guidance": "采集建议",
                "falsification_logic": "证伪条件",
            }
        )
    return json.dumps({"probes": probes}, ensure_ascii=False)


def _fake_deduce_json() -> str:
    return json.dumps(
        {
            "cross_validation_analysis": "多维一致，暂无核心矛盾。",
            "falsified_flag": False,
            "final_recommendation": "晋级执行中并持续监控。",
        },
        ensure_ascii=False,
    )


def test_sandbox_plan_and_gate(monkeypatch):
    class FakeResp:
        def __init__(self, text: str):
            self.text = text
            self.model = "claude-opus-4-6"
            self.tokens_in = 100
            self.tokens_out = 200
            self.cost_yuan_est = 1.23

    seq = [_fake_plan_json(), _fake_deduce_json()]

    def fake_call(*args, **kwargs):  # noqa: ANN001
        return FakeResp(seq.pop(0))

    monkeypatch.setattr(sb.AIDispatcher, "default", classmethod(lambda cls: type("X", (), {"call": fake_call})()))

    with TestClient(app) as client:
        r = client.get("/api/planning/sandbox/002837")
        assert r.status_code == 200
        assert r.json()["symbol_code"] == "002837"

        r2 = client.post("/api/planning/sandbox/002837/plan")
        assert r2.status_code == 200
        probes = r2.json()["probes"]
        assert len(probes) >= 5
        assert r2.json()["all_data_ready"] is False

        for p in probes:
            rr = client.post(
                f"/api/planning/sandbox/probes/{p['id']}/result",
                data={"mock_result": '{"metric": 1}'},
            )
            assert rr.status_code == 200

        r3 = client.post("/api/planning/sandbox/002837/deduce")
        assert r3.status_code == 200
        body = r3.json()
        assert body["all_data_ready"] is True
        assert body["deduction_snapshot"]["falsified_flag"] is False

