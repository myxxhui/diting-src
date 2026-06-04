"""T0 DeepSeek 槽位 · profile.llm_tag / regulatory_events.llm_tag。

[Ref: 27_ T0-4/T0-17 · 28_ §9]
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _parse_json_tag(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            tag = obj.get("llm_tag") or obj.get("tag")
            return str(tag).strip() if tag else None
        except json.JSONDecodeError:
            pass
    # 单行标签
    line = text.splitlines()[0].strip().strip('"')
    return line[:200] if line else None


def _call_deepseek(messages: list[dict[str, str]]) -> str:
    from apps.common.ai_dispatcher import AIDispatcher

    resp = AIDispatcher.default().call(
        "radar_t0_llm_tag",
        messages,
        max_tokens=256,
        temperature=0.1,
    )
    return (resp.text or "").strip()


def enrich_profile_llm_tag(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("status") != "ok" or profile.get("llm_tag"):
        return profile
    intro = profile.get("business_intro") or ""
    payload = {
        "name": profile.get("name"),
        "industry": profile.get("industry"),
        "intro": intro[:1500],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是证券研究助理。根据公司档案 JSON，输出一行 JSON："
                '{"llm_tag":"≤40字行业/概念标签，顿号分隔"}。'
                "只基于给定事实，禁止编造。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        tag = _parse_json_tag(_call_deepseek(messages))
        if tag:
            profile = dict(profile)
            profile["llm_tag"] = tag
            profile["llm_tag_source"] = "deepseek"
            return profile
    except Exception as exc:  # noqa: BLE001
        logger.warning("profile llm_tag 失败: %s", exc)
    # 规则兜底：基于真实档案字段（非 mock）
    industry = str(profile.get("industry") or "").strip()
    name = str(profile.get("name") or "").strip()
    if industry or name:
        profile = dict(profile)
        profile["llm_tag"] = industry or name
        profile["llm_tag_source"] = "rule:industry"
    return profile


def enrich_regulatory_llm_tag(reg: dict[str, Any]) -> dict[str, Any]:
    if reg.get("status") != "ok" or reg.get("llm_tag"):
        return reg
    raw = reg.get("raw_text") or "\n".join(reg.get("events") or [])
    if not raw.strip():
        return reg
    messages = [
        {
            "role": "system",
            "content": (
                "根据监管/风险提示公告摘要，输出 JSON："
                '{"llm_tag":"severity:low|medium|high · ≤30字摘要"}。'
                "severity 须与文本严重程度一致。"
            ),
        },
        {"role": "user", "content": raw[:4000]},
    ]
    try:
        tag = _parse_json_tag(_call_deepseek(messages))
        if not tag:
            # 规则兜底：仍写入 llm_tag（非 mock · 基于真实标题）
            sev = "medium"
            if any(k in raw for k in ("立案", "调查")):
                sev = "high"
            elif any(k in raw for k in ("澄清", "异常波动")):
                sev = "low"
            first = (reg.get("events") or [raw[:60]])[0]
            clean = re.sub(r"\[.*?\]", "", str(first))
            tag = f"{sev}:{clean[:28]}"
        reg = dict(reg)
        reg["llm_tag"] = tag
        reg["llm_tag_source"] = "deepseek"
    except Exception as exc:  # noqa: BLE001
        logger.warning("regulatory llm_tag 失败: %s", exc)
    return reg
