"""业绩会 QA 语料 · DeepSeek 鉴别与模糊词抽取。

[Ref: 28_ §2.8 · fii_odm_direct_ratio T1]
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.constants import (
    FUZZY_TERM_CONSTRAINTS,
)

logger = logging.getLogger(__name__)

_SKIP_NOTICE = re.compile(r"关于召开|召开.*的公告")
_QA_RECORD = re.compile(r"投资者关系活动记录表|活动记录表")
_QA_MARKERS = re.compile(r"Q\d+[：:]|回复[：:]")


def score_qa_document(title: str, text: str) -> int:
    """巨潮 QA 候选打分：记录表 > 含 Q&A 标记；召开公告降权。"""
    score = 0
    if _QA_RECORD.search(title):
        score += 100
    if _SKIP_NOTICE.search(title):
        score -= 200
    if _QA_MARKERS.search(text):
        score += 50
    if "关于召开" in text and not _QA_RECORD.search(title):
        score -= 40
    if len(text) >= 800:
        score += 20
    elif len(text) < 400:
        score -= 30
    return score


def rule_classify_qa(title: str, text: str) -> dict[str, Any]:
    """无 LLM 时的规则兜底分类。"""
    is_record = bool(_QA_RECORD.search(title) or _QA_RECORD.search(text[:200]))
    is_notice = bool(_SKIP_NOTICE.search(title))
    has_markers = bool(_QA_MARKERS.search(text))
    matched = [t for t in FUZZY_TERM_CONSTRAINTS if t in text]
    return {
        "doc_type": (
            "ir_activity_record"
            if is_record
            else ("earnings_call_notice" if is_notice else "unknown")
        ),
        "is_authentic_qa_transcript": is_record and has_markers and not is_notice,
        "matched_fuzzy_terms": matched,
        "evidence_sentences": [],
        "llm_tag": "rule_only",
    }


def analyze_qa_transcript(
    qa_text: str,
    *,
    report_period: str = "",
    title: str = "",
) -> dict[str, Any]:
    """DeepSeek 鉴别 QA 语料并抽取模糊词；失败时回退规则层。"""
    qa_text = (qa_text or "").strip()
    base = rule_classify_qa(title, qa_text)
    if not qa_text:
        return {
            **base,
            "doc_type": "empty",
            "is_authentic_qa_transcript": False,
            "llm_tag": "empty",
        }

    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return base

    fuzzy_list = "、".join(FUZZY_TERM_CONSTRAINTS.keys())
    prompt = f"""你是 A 股 IR 文档鉴别器。分析下列文本是否为「{report_period} 业绩说明会 Q&A 实录 / 投资者关系活动记录表」，并抽取 ODM/直供/CSP 客户结构相关证据。

模糊词表（仅当原文出现才算命中）：{fuzzy_list}

标题：{title[:200]}
正文（截断）：
{qa_text[:12000]}

输出严格 JSON：
{{
  "doc_type": "ir_activity_record|earnings_call_notice|quarterly_report_excerpt|unknown",
  "is_authentic_qa_transcript": true,
  "matched_fuzzy_terms": [],
  "customer_structure_evidence": ["原句≤512字"],
  "odm_ratio_inferable": "yes|partial|no",
  "verdict_zh": "一句话结论"
}}"""

    try:
        base_url = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip() or "deepseek-chat"
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=90,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        llm_terms = parsed.get("matched_fuzzy_terms") or []
        if isinstance(llm_terms, list):
            llm_terms = [str(t) for t in llm_terms if str(t) in FUZZY_TERM_CONSTRAINTS]
        rule_terms = base.get("matched_fuzzy_terms") or []
        merged_terms = list(dict.fromkeys([*rule_terms, *llm_terms]))
        return {
            "doc_type": parsed.get("doc_type") or base["doc_type"],
            "is_authentic_qa_transcript": bool(
                parsed.get("is_authentic_qa_transcript")
            ),
            "matched_fuzzy_terms": merged_terms,
            "evidence_sentences": parsed.get("customer_structure_evidence") or [],
            "odm_ratio_inferable": parsed.get("odm_ratio_inferable") or "no",
            "verdict_zh": parsed.get("verdict_zh") or "",
            "llm_tag": "deepseek",
        }
    except Exception as exc:
        logger.warning("fii_odm QA DeepSeek 分析失败: %s", exc)
        return {**base, "llm_tag": f"deepseek_error:{type(exc).__name__}"}
