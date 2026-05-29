"""D3 step_05 — NarrativeNLIClient 降级模式测试。

[Ref: 03_/03_维度三/.../step_05_叙事一致性NLI_LoRA.md §F §I2~I4]
"""
from __future__ import annotations

import importlib

import pytest

from apps.state_watch.health.narrative_nli import NarrativeNLIClient, NLIResult


# ──────────────────────────────────────────────────────────────────────────────
# 降级模式（无 vLLM URL）
# ──────────────────────────────────────────────────────────────────────────────

class TestNLIDegradedMode:
    @pytest.fixture
    def client(self):
        return NarrativeNLIClient(vllm_url=None)

    def test_degraded_returns_label_degraded(self, client):
        result = client.predict("thesis text", "announcement text")
        assert result.label == "degraded"

    def test_degraded_score_is_none(self, client):
        result = client.predict("thesis text", "announcement text")
        assert result.score is None

    def test_degraded_flag_set(self, client):
        result = client.predict("thesis text", "announcement text")
        assert result.degraded is True

    def test_degraded_reason_not_empty(self, client):
        result = client.predict("thesis text", "announcement text")
        assert result.reason and len(result.reason) > 5

    def test_no_fake_entailment(self, client):
        """禁止在降级路径伪造 entailment。"""
        result = client.predict("买入 thesis", "公告利好")
        assert result.label != "entailment"

    def test_no_fake_neutral(self, client):
        """禁止在降级路径伪造 neutral（应返回 degraded）。"""
        result = client.predict("中性 thesis", "中性公告")
        assert result.label == "degraded"

    def test_evidence_hash_generated(self, client):
        result = client.predict("thesis", "announcement")
        assert result.evidence_hash and len(result.evidence_hash) == 12

    def test_different_inputs_different_hash(self, client):
        r1 = client.predict("thesis A", "announcement A")
        r2 = client.predict("thesis B", "announcement B")
        assert r1.evidence_hash != r2.evidence_hash

    def test_batch_predict_returns_list(self, client):
        pairs = [("thesis1", "ann1"), ("thesis2", "ann2"), ("thesis3", "ann3")]
        results = client.batch_predict(pairs)
        assert len(results) == 3
        assert all(isinstance(r, NLIResult) for r in results)

    def test_batch_all_degraded_without_vllm(self, client):
        pairs = [("t", "a") for _ in range(5)]
        results = client.batch_predict(pairs)
        assert all(r.degraded for r in results)


# ──────────────────────────────────────────────────────────────────────────────
# no-mock policy guard
# ──────────────────────────────────────────────────────────────────────────────

class TestNoMockPolicy:
    def test_stub_mode_env_raises(self, monkeypatch):
        """THESIS_NLI_MODE=stub 禁止在生产路径启用。"""
        import apps.state_watch.health.narrative_nli as nli_module

        monkeypatch.setenv("THESIS_NLI_MODE", "stub")
        with pytest.raises(RuntimeError, match="stub"):
            importlib.reload(nli_module)

        monkeypatch.delenv("THESIS_NLI_MODE", raising=False)
        importlib.reload(nli_module)
