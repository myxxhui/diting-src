"""Z0-M2 政策 T1 Phase B1 · 逐篇 LLM 语义评分。

每篇政策文档独立调用 LLM，输出结构化 JSON（含 doc_metadata）。
无 fallback：LLM 不可用或输出格式错误直接抛异常。

[Ref: 36_ §4/§5.0/§10 · 34_ §3.2 M.policy.sector_direction]
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是一位专业的投研政策分析助手。你的任务是阅读**单篇**政策全文，判断其对各个产业赛道的影响。

## 输出格式（必须严格 JSON）
{
  "sectors": [
    {
      "sector_name": "赛道名",
      "direction": "strong_tailwind|weak_tailwind|neutral|weak_headwind|strong_headwind",
      "impact_score": 0-100,
      "evidence_quotes": ["原文引用的句子"],
      "reasoning": "判断依据"
    }
  ],
  "overall_assessment": "一句话总体判断",
  "doc_metadata": {
    "impl_status": "已发布_待执行|已执行_进行中|已执行_完成|征求意见稿|废止_替代|状态未知",
    "impl_status_reasoning": "推断依据"
  }
}

## 文档实施状态定义
状态             | 含义
已发布_待执行     | 政策已正式发布（含"印发""发布""通知"等），但尚未到执行日期或刚发布不久
已执行_进行中     | 政策正在执行中，正文含进度汇报、阶段成果、继续推进等表述
已执行_完成       | 政策目标已完成、总结、收官、回顾
征求意见稿       | 尚未正式实施，仍在公开征求意见阶段（标题或正文含"征求意见"且未正式发布）
废止_替代         | 已被新政策废止或替代，不再生效（正文含"废止""同时废止""替代"）
状态未知         | 无法从文本中判断

## 影响方向定义
方向               | 含义
strong_tailwind   | 强利好：明确扶持、补贴、财政支持、立法保障、国家规划
weak_tailwind     | 弱利好：提及鼓励发展、方向性认可、研究探索
neutral           | 中性：无直接关联或平衡表述
weak_headwind     | 弱利空：规范管理、提高准入门槛、窗口指导
strong_headwind   | 强利空：限制、禁止、淘汰、惩罚性措施、征收

## 影响强度评分（0-100）
范围       | 含义
----------|------
81-100    | 重大影响：政策直接针对该赛道，且有实质性措施
61-80     | 显著影响：政策明确涉及该赛道，有具体条款
41-60     | 中等影响：政策部分涉及
21-40     | 轻度影响：间接涉及或顺带提及
0-20      | 可忽略：几乎无关联

## 重要规则
1. 只从下方 allowed_sectors 列表中选择赛道名
2. 每条 evidence_quotes 必须是原文中完整的一句话（至少 1 条）
3. 如果没有赛道受影响，sectors 数组为空
4. 如果对同一赛道既有利好又有利空，方向选择影响更大的那个，在 reasoning 中说明
5. doc_metadata.impl_status 须基于全文内容判断，不要仅看标题
"""

_KEYWORDS_CFG = (
    Path(__file__).resolve().parents[4]
    / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
)

ALLOWED_DIRECTIONS: set[str] = {
    "strong_tailwind", "weak_tailwind", "neutral",
    "weak_headwind", "strong_headwind",
}

ALLOWED_IMPL_STATUS: set[str] = {
    "已发布_待执行", "已执行_进行中", "已执行_完成",
    "征求意见稿", "废止_替代", "状态未知",
}


def _load_keywords() -> dict[str, Any]:
    if not _KEYWORDS_CFG.is_file():
        return {
            "sector_prompt_descriptions": {},
            "sector_aliases": {},
        }
    with _KEYWORDS_CFG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_allowed_sectors() -> list[str]:
    cfg = _load_keywords()
    aliases = cfg.get("sector_aliases") or {}
    return list(aliases.keys())


def _get_sector_descriptions() -> dict[str, str]:
    cfg = _load_keywords()
    return cfg.get("sector_prompt_descriptions") or {}


def _estimate_tokens(text: str) -> int:
    """中文 token 近似估算。"""
    return int(len(text) * 0.28) + 1


def _truncate_middle(text: str, max_chars: int) -> str:
    """保留首尾，截断中间。"""
    if len(text) <= max_chars:
        return text
    head_end = int(max_chars * 0.6)
    tail_start = max_chars - head_end
    return text[:head_end] + "\n...（中间截断）...\n" + text[-tail_start:]


def assemble_context(
    title: str,
    summary: str,
    full_text: str | None,
    *,
    full_text_budget: int = 6000,
) -> str:
    """组装单篇政策全文上下文。"""
    text = title or ""
    if summary and summary != title:
        text = f"{title}\n\n摘要：{summary}"
    if full_text:
        truncated = _truncate_middle(full_text, full_text_budget)
        text = f"{text}\n\n正文：\n{truncated}"
    return text


def build_prompt(context: str) -> str:
    """构建用户 Prompt（必须与系统 Prompt 配合）。"""
    allowed = _get_allowed_sectors()
    descs = _get_sector_descriptions()

    lines = ["## 可用的赛道列表", ""]
    for s in allowed:
        desc = descs.get(s, "")
        if desc:
            lines.append(f"- {s}：{desc}")
        else:
            lines.append(f"- {s}")
    lines.append("")

    sector_prompt = "\n".join(lines)

    return f"""{sector_prompt}

## 政策全文
{context}

请输出 JSON 格式的评分结果（包含 sectors、overall_assessment 和 doc_metadata）。"""


def parse_llm_json(raw: str) -> dict[str, Any]:
    """解析并校验 LLM 返回的 JSON（含 doc_metadata）。"""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    data = json.loads(clean)

    if not isinstance(data, dict):
        raise ValueError(f"LLM 输出不是 JSON 对象: {type(data).__name__}")
    sectors = data.get("sectors")
    if not isinstance(sectors, list):
        raise ValueError("LLM 输出缺少 sectors 数组")

    allowed = set(_get_allowed_sectors())
    validated = []
    for item in sectors:
        if not isinstance(item, dict):
            continue
        sector = str(item.get("sector_name") or "").strip()
        if not sector or sector not in allowed:
            continue
        direction = str(item.get("direction") or "neutral")
        if direction not in ALLOWED_DIRECTIONS:
            direction = "neutral"
        score = float(item.get("impact_score") or 0)
        score = max(0.0, min(100.0, score))
        quotes = item.get("evidence_quotes") or []
        if not isinstance(quotes, list):
            quotes = [str(quotes)] if quotes else []
        quotes = [str(q).strip() for q in quotes if q]
        reasoning = str(item.get("reasoning") or "无推理过程").strip()
        validated.append({
            "sector_name": sector,
            "direction": direction,
            "impact_score": round(score, 1),
            "evidence_quotes": quotes,
            "reasoning": reasoning,
        })

    # 解析 doc_metadata
    meta = data.get("doc_metadata") or {}
    impl_status = str(meta.get("impl_status") or "状态未知")
    if impl_status not in ALLOWED_IMPL_STATUS:
        impl_status = "状态未知"
    impl_reasoning = str(meta.get("impl_status_reasoning") or "无法推断")

    return {
        "sectors": validated,
        "overall_assessment": str(data.get("overall_assessment") or ""),
        "doc_metadata": {
            "impl_status": impl_status,
            "impl_status_reasoning": impl_reasoning,
        },
    }


async def score_policy_document(
    doc: dict[str, Any],
    *,
    model: str = "deepseek-chat",
    temperature: float = 0.1,
) -> dict[str, Any]:
    """单篇政策文档 LLM 语义评分。失败抛异常（无 fallback）。"""
    from apps.common.ai_dispatcher import AIDispatcher

    context = assemble_context(
        title=str(doc.get("title") or ""),
        summary=str(doc.get("summary") or ""),
        full_text=str(doc.get("full_text") or None) or None,
    )
    prompt = build_prompt(context)

    dispatcher = AIDispatcher.default()
    result = dispatcher.call(
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature,
        max_tokens=4000,
    )

    raw = result.get("content") or ""
    parsed = parse_llm_json(raw)
    token_used = (result.get("usage") or {}).get("total_tokens", 0)

    return {
        "doc_id": str(doc.get("doc_id") or ""),
        "sectors": parsed["sectors"],
        "overall_assessment": parsed["overall_assessment"],
        "doc_metadata": parsed.get("doc_metadata") or {
            "impl_status": "状态未知",
            "impl_status_reasoning": "LLM 未输出",
        },
        "t1_source": f"llm:{model}",
        "llm_confidence": _estimate_confidence(parsed),
        "token_used": token_used,
    }


def _estimate_confidence(parsed: dict[str, Any]) -> float:
    """基于输出质量估计置信度。"""
    sectors = parsed.get("sectors") or []
    if not sectors:
        return 0.3
    with_evidence = sum(1 for s in sectors if len(s.get("evidence_quotes") or []) >= 2)
    total = len(sectors)
    if total == 0:
        return 0.3
    # 考虑 doc_metadata 的存在也加分
    meta = parsed.get("doc_metadata") or {}
    meta_bonus = 0.05 if meta.get("impl_status") else 0
    evidence_ratio = with_evidence / total
    return round(0.5 + evidence_ratio * 0.4 + meta_bonus, 2)


async def dispatch_b1(
    docs: list[dict[str, Any]],
    *,
    model: str = "deepseek-chat",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """B1 逐篇并行 LLM 评分。返回 (successes, errors)。"""
    import asyncio

    async def _score_one(doc: dict[str, Any]) -> dict[str, Any]:
        return await score_policy_document(doc, model=model)

    tasks = [_score_one(doc) for doc in docs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for doc, result in zip(docs, results):
        if isinstance(result, Exception):
            errors.append({
                "doc_id": str(doc.get("doc_id") or ""),
                "error": str(result)[:200],
            })
            logger.warning("B1 评分失败 doc_id=%s: %s", doc.get("doc_id"), result)
        else:
            successes.append(result)

    return successes, errors


__all__ = [
    "assemble_context",
    "build_prompt",
    "parse_llm_json",
    "score_policy_document",
    "dispatch_b1",
]
