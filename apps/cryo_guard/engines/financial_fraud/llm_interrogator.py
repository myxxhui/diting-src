"""N5 llm_interrogator — 调 vLLM + LoRA adapter 做最终裁决。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §3.5.2·N5]
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from apps.cryo_guard.engines.financial_fraud.schemas import (
    EvidenceItem,
    FraudLabel,
    LLMInterrogatorOutput,
    RiskLevel,
)

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
你是专业财务分析师，负责判断一家上市公司是否存在财务造假或盈余管理风险。

公司：{symbol}  报告期：{report_period}

【6类粉饰特征检测结果】
{features_text}

【历史趋势】
{trends_text}

【同行百分位】
{peer_text}

请综合以上信息，输出严格 JSON（不要 markdown 代码块）：
{{"label": "fraud|normal", "confidence": 0-1, "risk_level": "high|medium|low|unknown",
  "category": "特征类别", "evidence": [{{"source_table":"...", "source_period":"...", "human_readable_reason":"..."}}],
  "reason_zh": "中文说明"}}
"""


def _format_features(features: dict) -> str:
    lines = []
    for name, info in features.items():
        t = "⚠️ 触发" if info.get("triggered") else "✅ 正常"
        lines.append(f"  {name}: {t} — {info.get('note', '')}")
    return "\n".join(lines) or "（无特征数据）"


def _format_trends(trends: dict) -> str:
    if not trends:
        return "（历史数据不足）"
    return "  " + "  ".join(f"{k}:{v:+.2%}" if v is not None else f"{k}:N/A" for k, v in trends.items())


def _format_peer(peer_result: dict) -> str:
    if peer_result.get("peer_fallback") == "no_db":
        return "（无同行数据）"
    return (
        f"  同行数量: {peer_result.get('peer_count', 0)}"
        f"  fallback: {peer_result.get('peer_fallback', 'none')}"
        f"  百分位: {peer_result.get('percentiles', {})}"
    )


def interrogate(
    symbol: str,
    report_period: str,
    features: dict,
    time_series_result: dict,
    peer_result: dict,
    vllm_url: Optional[str] = None,
    adapter_path: Optional[str] = None,
) -> LLMInterrogatorOutput:
    """调用 vLLM + LoRA 做财务造假裁决。

    vllm_url 为 None 时返回降级结果（confidence=0.5，lora_loaded=False）。
    [Ref: step_04 §3.5.2·N5]
    """
    if vllm_url is None:
        logger.warning("[N5] vllm_url 未设置，返回降级结果（lora_loaded=False）")
        return LLMInterrogatorOutput(
            label=FraudLabel.NORMAL,
            confidence=0.5,
            risk_level=RiskLevel.UNKNOWN,
            category="",
            evidence=[],
            reason_zh="vLLM 降级：未连接推理服务，结论不可信",
            lora_loaded=False,
        )

    prompt = _PROMPT_TEMPLATE.format(
        symbol=symbol,
        report_period=report_period,
        features_text=_format_features(features),
        trends_text=_format_trends(time_series_result.get("trends", {})),
        peer_text=_format_peer(peer_result),
    )

    try:
        import httpx
        payload = {
            "model": adapter_path or "default",
            "prompt": prompt,
            "max_tokens": 512,
            "temperature": 0.1,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{vllm_url}/v1/completions", json=payload)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["text"].strip()
            data = json.loads(text)
    except Exception as e:
        logger.error("[N5] vLLM 调用失败：%s，返回降级", e)
        return LLMInterrogatorOutput(
            label=FraudLabel.NORMAL,
            confidence=0.5,
            risk_level=RiskLevel.UNKNOWN,
            category="",
            evidence=[],
            reason_zh=f"vLLM 调用异常（{type(e).__name__}），结论不可信",
            lora_loaded=False,
        )

    evidence = [
        EvidenceItem(
            source_table=e.get("source_table", "unknown"),
            source_period=e.get("source_period", report_period),
            human_readable_reason=e.get("human_readable_reason", ""),
        )
        for e in data.get("evidence", [])
    ]

    return LLMInterrogatorOutput(
        label=FraudLabel(data.get("label", "normal")),
        confidence=float(data.get("confidence", 0.5)),
        risk_level=RiskLevel(data.get("risk_level", "unknown")),
        category=data.get("category", ""),
        evidence=evidence,
        reason_zh=data.get("reason_zh", ""),
        lora_loaded=True,
    )
