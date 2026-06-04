"""T1 事实矩阵：DeepSeek 压缩 + 规则回退。

[Ref: step_14 · 25_ §2 T1_distilled]
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from apps.copilot.modules.radar.context_matrix import build_context_matrix
from apps.copilot.modules.radar.t1.fact_matrix_builder import enrich_t1_payload
from apps.copilot.modules.radar.model_router import (
    radar_t1_uses_deepseek,
    t1_step_label,
    t1_uses_deepseek_mode,
)

logger = logging.getLogger(__name__)


async def build_t1_payload(
    t0_raw: dict[str, Any],
    *,
    t1_mode: str | None = None,
) -> dict[str, Any]:
    """T1 输出：优先 DeepSeek 压缩；失败或未配置则 rule。t1_mode: rule | deepseek | None=auto。"""
    if not t1_uses_deepseek_mode(t1_mode):
        return enrich_t1_payload(t0_raw, build_context_matrix(t0_raw))
    try:
        return await _build_context_matrix_deepseek(t0_raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("T1 DeepSeek 失败，回退规则: %s", exc)
        out = build_context_matrix(t0_raw)
        out["t1_fallback"] = "rule"
        out["t1_error"] = str(exc)[:200]
        return enrich_t1_payload(t0_raw, out)


async def _build_context_matrix_deepseek(t0_raw: dict[str, Any]) -> dict[str, Any]:
    from apps.common.ai_dispatcher import AIDispatcher

    sym = t0_raw.get("symbol") or ""
    name = t0_raw.get("name") or sym
    t0_json = json.dumps(
        {k: t0_raw.get(k) for k in ("quote", "profile", "financials", "valuation")},
        ensure_ascii=False,
        default=str,
    )[:12000]

    messages = [
        {
            "role": "system",
            "content": (
                "你是证券研究助理。将 T0 原始 JSON 压缩为紧凑事实矩阵 JSON，"
                "只保留 status=ok 的事实；失败源写入 unavailable 列表。"
                "输出必须是单个 JSON 对象，含 keys: matrix, unavailable（数组）。"
                "matrix 下分 行情/公司资料/财务摘要/估值 等中文键，勿编造。"
            ),
        },
        {
            "role": "user",
            "content": f"标的 {sym} {name}\nT0:\n{t0_json}",
        },
    ]

    def _blocking() -> Any:
        return AIDispatcher.default().call(
            "radar_distill",
            messages,
            max_tokens=2048,
            temperature=0.1,
        )

    resp = await asyncio.to_thread(_blocking)
    parsed = _parse_matrix_json(resp.text)
    model_id = resp.model or "deepseek:deepseek-chat"
    return enrich_t1_payload(
        t0_raw,
        {
            "model_id": model_id,
            "t1_fallback": "deepseek",
            "symbol": sym,
            "name": name,
            "matrix": parsed.get("matrix") or {},
            "unavailable": parsed.get("unavailable") or [],
            "fact_count": len(parsed.get("matrix") or {}),
            "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out,
            "cost_yuan": resp.cost_yuan_est,
            "t1_step_label": t1_step_label(),
        },
    )


def _parse_matrix_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                text = p
                break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("DeepSeek 未返回 JSON 矩阵")
    return json.loads(text[start : end + 1])
