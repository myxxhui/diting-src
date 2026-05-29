"""Teacher 蒸馏器单元测试与契约测试。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.super_evo.main import app
from apps.super_evo.teacher.clients.anthropic_client import (
    AnthropicTeacherClient,
    TeacherResponse,
    TransientAPIError,
)
from apps.super_evo.teacher.distiller import TeacherDistiller
from apps.super_evo.teacher.prompts import get_prompt
from apps.super_evo.teacher.rate_limiter import RateLimiter, TokenBucket
from apps.super_evo.teacher.schemas import DistillInput

SAMPLE = DistillInput(
    task_type="financial_fraud",
    sample_id="s1",
    raw_data={
        "symbol": "002450",
        "company_name": "康得新",
        "report_date": "2018-12-31",
        "financial_data": {"cash": 150e8, "interest_debt": 100e8, "revenue": 75e8},
    },
)


def test_schema_rejects_empty_raw_data():
    with pytest.raises(Exception):
        DistillInput(task_type="financial_fraud", raw_data={})


def test_prompt_registry_has_three_tasks():
    for t in ("financial_fraud", "shareholder", "related_party"):
        p = get_prompt(t)
        msgs = p.to_messages({"x": 1}, None)
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"


@pytest.mark.asyncio
async def test_token_bucket_blocks_after_capacity():
    bucket = TokenBucket(rate=2.0, capacity=2.0)
    t0 = time.monotonic()
    for _ in range(3):
        await bucket.acquire(1.0)
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.4


@pytest.mark.asyncio
async def test_rate_limiter_caps_burst_to_per_minute():
    limiter = RateLimiter(per_minute=60, burst=3)
    t0 = time.monotonic()
    for _ in range(8):
        await limiter.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 4.5 * (1 / 1.0)


@pytest.mark.asyncio
async def test_rate_limiter_enforces_pause_beyond_burst():
    """限流：突发用尽后须按 per_minute 匀速等待（12 次 & burst=3 → ≥6s）。"""
    limiter = RateLimiter(per_minute=60, burst=3)
    t0 = time.monotonic()
    for _ in range(12):
        await limiter.acquire()
    assert time.monotonic() - t0 >= 6.0


@pytest.mark.asyncio
async def test_dry_run_client_returns_valid_json():
    client = AnthropicTeacherClient(dry_run=True)
    resp = await client.chat(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
    )
    data = json.loads(resp.text)
    assert data["decision"] in {"pass", "degrade", "reject"}


@pytest.mark.asyncio
async def test_client_retries_on_transient_then_succeeds(monkeypatch):
    client = AnthropicTeacherClient(dry_run=False, api_key="fake", max_attempts=3)
    call_count = {"n": 0}

    async def fake_call(messages):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise TransientAPIError("simulated 429")
        return TeacherResponse(
            text=json.dumps(
                {
                    "risk_score": 0.9,
                    "decision": "reject",
                    "evidence": ["e1"],
                    "reasoning": "r",
                    "confidence": 0.8,
                }
            ),
            raw={},
            model="mock",
        )

    monkeypatch.setattr(client, "_call_once", fake_call)
    resp = await client.chat([{"role": "user", "content": "x"}])
    assert call_count["n"] == 3
    assert json.loads(resp.text)["decision"] == "reject"


@pytest.mark.asyncio
async def test_distill_one_dry_run_produces_valid_jsonl_line():
    distiller = TeacherDistiller(minio=None)
    out = await distiller.distill_one(SAMPLE)
    line = out.to_jsonl_line()
    parsed = json.loads(line)
    assert parsed["metadata"]["task_type"] == "financial_fraud"
    inner = json.loads(parsed["output"])
    assert "risk_score" in inner


@pytest.mark.asyncio
async def test_distill_batch_writes_jsonl_and_reports_throughput(tmp_path: Path):
    distiller = TeacherDistiller(minio=None, concurrency=4, per_minute=600, burst=20)
    items = [SAMPLE.model_copy(update={"sample_id": f"s{i}"}) for i in range(8)]
    result = await distiller.distill_batch(
        items, task_type="financial_fraud", output_dir=tmp_path, upload_minio=False
    )
    assert result.num_success == 8
    assert Path(result.jsonl_path).exists()
    lines = Path(result.jsonl_path).read_text().splitlines()
    assert len(lines) == 8
    assert result.throughput_per_day > 0


@pytest.mark.asyncio
async def test_distill_batch_five_within_sixty_seconds(tmp_path: Path):
    """准出：并发 4、60 秒内 ≥ 5 条（dry_run）。"""
    distiller = TeacherDistiller(minio=None, concurrency=4, per_minute=600, burst=50)
    items = [SAMPLE.model_copy(update={"sample_id": f"s{i}"}) for i in range(5)]
    t0 = time.monotonic()
    result = await distiller.distill_batch(
        items, task_type="financial_fraud", output_dir=tmp_path, upload_minio=False
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 60.0
    assert result.num_success >= 5


@pytest.mark.asyncio
async def test_distill_batch_skips_failed_items(monkeypatch, tmp_path: Path):
    distiller = TeacherDistiller(minio=None, per_minute=600, burst=20)

    real = distiller.distill_one
    n = {"i": 0}

    async def flaky(item, batch_id=None):
        n["i"] += 1
        if n["i"] % 3 == 0:
            raise RuntimeError("simulated parse failure")
        return await real(item, batch_id=batch_id)

    monkeypatch.setattr(distiller, "distill_one", flaky)
    items = [SAMPLE.model_copy(update={"sample_id": f"s{i}"}) for i in range(6)]
    result = await distiller.distill_batch(
        items, task_type="financial_fraud", output_dir=tmp_path, upload_minio=False
    )
    assert result.num_failed >= 1
    assert result.num_success + result.num_failed == 6


@pytest.mark.asyncio
async def test_distill_batch_minio_key_format(tmp_path: Path):
    from apps.super_evo.storage.minio_client import MinIOClient

    minio = MinIOClient(bucket="super-evo-test")
    if not minio.health().get("ok"):
        pytest.skip("MinIO 不可用")
    distiller = TeacherDistiller(minio=minio, concurrency=2, per_minute=600, burst=10)
    items = [SAMPLE.model_copy(update={"sample_id": f"u{i}"}) for i in range(2)]
    result = await distiller.distill_batch(
        items, task_type="financial_fraud", output_dir=tmp_path, upload_minio=True
    )
    assert result.minio_uri
    assert "distilled/financial_fraud/" in result.minio_uri
    assert result.minio_uri.endswith(".jsonl")


def test_distill_health_endpoint():
    with TestClient(app) as client:
        r = client.get("/api/distill/health")
        assert r.status_code == 200
        body = r.json()
        assert "teacher_model" in body


def test_distill_single_endpoint():
    with TestClient(app) as client:
        r = client.post("/api/distill/single", json=SAMPLE.model_dump())
        assert r.status_code == 200
        body = r.json()
        assert body["metadata"]["task_type"] == "financial_fraud"
