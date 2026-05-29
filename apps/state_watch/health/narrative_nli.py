"""叙事一致性 NLI 客户端（D3 step_05）。

降级策略：
  - adapter 未加载 → 返回 degraded 标注，score=None；禁止伪造 entailment
  - 无 GPU 时在 tier-1 本地运行降级模式

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_05_叙事一致性NLI_LoRA.md §F]
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

logger = logging.getLogger(__name__)

NLILabel = Literal["entailment", "neutral", "contradiction", "degraded"]

# 运行时 guard：禁止 stub label 进入业务路径
if os.environ.get("THESIS_NLI_MODE", "").lower() == "stub":
    raise RuntimeError(
        "THESIS_NLI_MODE=stub 禁止在生产路径启用。stub 仅允许在 tests/ fixture 使用。"
    )


@dataclass
class NLIResult:
    label: NLILabel
    score: Optional[float]           # None 表示 degraded
    evidence_hash: str               # sha1(thesis+announcement)[:12]
    degraded: bool = False
    reason: Optional[str] = None     # degraded 时填原因
    latency_ms: Optional[float] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _hash_evidence(thesis_text: str, announcement_text: str) -> str:
    raw = (thesis_text + "|" + announcement_text).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


class NarrativeNLIClient:
    """叙事一致性 NLI 推理客户端。

    tier-1 模式：本地无 GPU，统一返回 degraded（不伪造标签）。
    tier-2 模式：调 vLLM 热加载 adapter（启动期可选）。
    """

    def __init__(
        self,
        vllm_url: Optional[str] = None,
        model_name: str = "narrative_nli_lora_v1",
        timeout_seconds: float = 8.0,
    ) -> None:
        self.vllm_url = vllm_url or os.environ.get("VLLM_URL")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self._adapter_loaded = False
        self._check_adapter()

    def _check_adapter(self) -> None:
        """检查 vLLM adapter 是否可用。"""
        if not self.vllm_url:
            logger.info("NarrativeNLI: 未配置 VLLM_URL，降级运行（degraded 模式）。")
            return
        try:
            import httpx
            resp = httpx.get(f"{self.vllm_url}/health", timeout=3.0)
            if resp.status_code == 200:
                self._adapter_loaded = True
                logger.info("NarrativeNLI: vLLM 健康检查通过，adapter 可用。")
        except Exception as e:
            logger.warning("NarrativeNLI: vLLM 不可达 (%s)，降级运行。", e)

    def predict(
        self,
        thesis_text: str,
        announcement_text: str,
        symbol: Optional[str] = None,
    ) -> NLIResult:
        """
        输入：thesis 摘要文本 + 公告/财报片段文本。
        输出：NLIResult（label + score，degraded 时 label='degraded', score=None）。
        禁止在非降级路径返回 entailment 占位。
        """
        evidence_hash = _hash_evidence(thesis_text, announcement_text)

        if not self._adapter_loaded:
            return NLIResult(
                label="degraded",
                score=None,
                evidence_hash=evidence_hash,
                degraded=True,
                reason="vLLM adapter 未加载；tier-2 训练完成后可切换",
            )

        # tier-2: 调 vLLM
        import time
        t0 = time.monotonic()
        try:
            result = self._call_vllm(thesis_text, announcement_text, evidence_hash)
            result.latency_ms = (time.monotonic() - t0) * 1000
            return result
        except Exception as e:
            logger.warning("NarrativeNLI: vLLM 调用失败 (%s)，返回 degraded。", e)
            return NLIResult(
                label="degraded",
                score=None,
                evidence_hash=evidence_hash,
                degraded=True,
                reason=f"vLLM error: {e}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    def _call_vllm(
        self, thesis_text: str, announcement_text: str, evidence_hash: str
    ) -> NLIResult:
        """调 vLLM openai-compatible chat API，解析 NLI label。"""
        import httpx
        import json

        prompt = (
            f"以下是一段投资观点（thesis）和一段公司公告/财报摘录，"
            f"请判断两者的关系，输出 JSON：{{\"label\": \"entailment|neutral|contradiction\", \"score\": 0.0-1.0}}\n\n"
            f"thesis: {thesis_text[:600]}\n\n"
            f"公告摘录: {announcement_text[:600]}"
        )

        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64,
            "temperature": 0.0,
        }
        resp = httpx.post(
            f"{self.vllm_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        # 鲁棒解析
        import re
        m = re.search(r'\{.*?\}', content, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
        raw_label = parsed.get("label", "").lower()
        label: NLILabel = raw_label if raw_label in ("entailment", "neutral", "contradiction") else "degraded"
        score = float(parsed.get("score", 0.5)) if label != "degraded" else None

        return NLIResult(
            label=label,
            score=score,
            evidence_hash=evidence_hash,
            degraded=(label == "degraded"),
        )

    def batch_predict(
        self,
        pairs: list[tuple[str, str]],
        symbol: Optional[str] = None,
    ) -> list[NLIResult]:
        """批量推理（串行，后续可改并发）。"""
        return [self.predict(thesis, announcement, symbol) for thesis, announcement in pairs]
