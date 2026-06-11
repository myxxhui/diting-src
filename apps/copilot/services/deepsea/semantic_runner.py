"""DeepSea 语义探针 · JSON 契约调用。

[Ref: 29_ §5.2 · 28_ §2.13]
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _resolve_model(*, model_tier: str = "flash") -> str:
    tier = str(model_tier or "flash").strip().lower()
    if tier in ("pro", "pro_required", "reasoner"):
        return (
            os.getenv("DEEPSEEK_MODEL_PRO")
            or os.getenv("DEEPSEEK_REASONER_MODEL")
            or "deepseek-reasoner"
        ).strip() or "deepseek-reasoner"
    return (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip() or "deepseek-chat"


def call_semantic_json(
    *,
    prompt: str,
    temperature: float = 0.12,
    timeout_sec: int = 120,
    model_tier: str = "flash",
) -> dict[str, Any]:
    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    base_url = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = _resolve_model(model_tier=model_tier)
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("语义模型返回非 JSON 对象")
    return parsed
