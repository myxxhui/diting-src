"""ODM/CSP 语义证据层 · DeepSeek 抽原文 + 景气评估。

[Ref: 28_ §2.8 · fii_odm_direct_ratio T1-Semantic]
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

_GROWTH_LABELS: dict[str, tuple[str, str]] = {
    "strong_up": ("green", "CSP/ODM·强↑"),
    "moderate_up": ("yellow", "结构改善↑"),
    "flat": ("yellow", "持平观察"),
    "unclear": ("yellow", "语料不足"),
    "down": ("red", "走弱"),
}

_DIMENSION_ZH: dict[str, str] = {
    "cloud_revenue_growth": "云营收增速",
    "csp_odm_deepening": "CSP/ODM合作",
    "order_volume_surge": "订单/出货",
    "revenue_mix_shift": "结构抬升",
    "negative_or_uncertain": "风险/不确定",
}


def growth_signal_display(signal: str) -> tuple[str, str]:
    return _GROWTH_LABELS.get(str(signal or "unclear"), _GROWTH_LABELS["unclear"])


def _rule_fallback_semantic(
    report_excerpt: str,
    ir_text: str,
    *,
    report_period: str,
) -> dict[str, Any]:
    """无 DeepSeek 时的规则兜底（仅抽明显句式）。"""
    quotes: list[dict[str, Any]] = []
    blob_a = report_excerpt or ""
    blob_b = ir_text or ""

    for pat, dim in (
        (r"云计算业务方面.{0,80}?同比增长\s*[\d.]+\s*倍", "cloud_revenue_growth"),
        (r"云计算业务.{0,60}?同比增长\s*[\d.]+\s*%", "cloud_revenue_growth"),
        (r"AIGPU机柜同比出货量增长[\d.]+\s*倍", "order_volume_surge"),
        (r"高端AI服务器ODM.{0,40}?制造优势", "csp_odm_deepening"),
        (r"核心客户合作根基深厚", "csp_odm_deepening"),
    ):
        for blob, src in ((blob_a, "quarterly_report"), (blob_b, "ir_activity_record")):
            m = re.search(pat, blob, re.S)
            if m:
                quotes.append(
                    {
                        "dimension": dim,
                        "source_doc": src,
                        "quote_zh": m.group(0)[:512],
                        "semantic_summary_zh": _DIMENSION_ZH.get(dim, dim),
                        "strength": "medium",
                    }
                )

    strong = sum(1 for q in quotes if q.get("strength") == "strong")
    medium = sum(1 for q in quotes if q.get("strength") == "medium")
    if medium + strong >= 3:
        sig = "strong_up"
    elif medium + strong >= 1:
        sig = "moderate_up"
    else:
        sig = "unclear"

    return {
        "llm_tag": "rule_fallback",
        "report_period": report_period,
        "evidence_quotes": quotes[:12],
        "semantic_assessment": {
            "odm_csp_growth_signal": sig,
            "cloud_share_of_total_signal": "rising_but_unquantified",
            "meets_investment_thesis_odm_direct": sig in ("strong_up", "moderate_up"),
            "thesis_rationale_zh": f"规则层命中 {len(quotes)} 条片段（无 DeepSeek）",
        },
        "inferred_odm_share_of_cloud_pct": {
            "point": None,
            "lo": None,
            "hi": None,
            "confidence": "none",
            "method_zh": "规则层不推断占比",
            "disclaimer_zh": "语义推断非财报直接披露",
        },
        "gaps_and_blockers": [],
        "overall_verdict_zh": "",
    }


def analyze_semantic_evidence(
    *,
    report_excerpt: str,
    ir_qa_text: str,
    report_period: str = "",
    total_cloud_revenue_cny: int | None = None,
    total_cloud_yoy_pct: float | None = None,
    ir_doc_title: str = "",
) -> dict[str, Any]:
    """季报节选 + IR 记录表 → 语义证据 JSON（DeepSeek 优先）。"""
    report_excerpt = (report_excerpt or "").strip()
    ir_qa_text = (ir_qa_text or "").strip()
    if not report_excerpt and not ir_qa_text:
        return {
            "llm_tag": "empty",
            "evidence_quotes": [],
            "semantic_assessment": {
                "odm_csp_growth_signal": "unclear",
                "meets_investment_thesis_odm_direct": False,
                "thesis_rationale_zh": "无 T0 文本",
            },
            "inferred_odm_share_of_cloud_pct": {"confidence": "none"},
        }

    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return _rule_fallback_semantic(report_excerpt, ir_qa_text, report_period=report_period)

    hard = ""
    if total_cloud_revenue_cny is not None:
        hard += f"云营收(硬锚)={total_cloud_revenue_cny/1e8:.2f}亿元；"
    if total_cloud_yoy_pct is not None:
        hard += f"云YoY(硬锚)={float(total_cloud_yoy_pct):.1f}%；"

    prompt = f"""你是 A 股「ODM直供/CSP 客户结构」语义证据分析师。
从一手官方文本抽取**原文短句**（每条≤512字，必须逐字来自输入，禁止改写），评估 ODM/直供云业务是否在大幅增长、合作加深、出货跳升。

硬锚（Python已算，可引用）：{hard or '无'}

【A 季报节选 · {report_period}】
{report_excerpt[:8000]}

【B IR活动记录 · {ir_doc_title[:120]}】
{ir_qa_text[:12000]}

输出严格 JSON：
{{
  "evidence_quotes": [
    {{
      "dimension": "cloud_revenue_growth|csp_odm_deepening|order_volume_surge|revenue_mix_shift|negative_or_uncertain",
      "source_doc": "quarterly_report|ir_activity_record",
      "quote_zh": "原文",
      "semantic_summary_zh": "10-30字",
      "strength": "strong|medium|weak"
    }}
  ],
  "semantic_assessment": {{
    "odm_csp_growth_signal": "strong_up|moderate_up|flat|unclear|down",
    "cloud_share_of_total_signal": "large_and_rising|rising_but_unquantified|unclear",
    "meets_investment_thesis_odm_direct": true,
    "thesis_rationale_zh": "2-4句"
  }},
  "inferred_odm_share_of_cloud_pct": {{
    "point": null,
    "lo": null,
    "hi": null,
    "confidence": "high|medium|low|none",
    "method_zh": "",
    "disclaimer_zh": "语义推断非财报直接披露"
  }},
  "gaps_and_blockers": [],
  "overall_verdict_zh": ""
}}

规则：禁止编造 A/B 未出现的数字；无 ODM占云业务比例披露时 confidence=none 且 point/lo/hi=null。"""

    try:
        base_url = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip() or "deepseek-chat"
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.15,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        resp.raise_for_status()
        parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
        parsed["llm_tag"] = "deepseek"
        parsed["report_period"] = report_period
        return parsed
    except Exception as exc:
        logger.warning("fii_odm semantic DeepSeek 失败: %s", exc)
        fb = _rule_fallback_semantic(report_excerpt, ir_qa_text, report_period=report_period)
        fb["llm_tag"] = f"rule_fallback:{type(exc).__name__}"
        return fb
