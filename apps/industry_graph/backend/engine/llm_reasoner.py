# apps/industry_graph/backend/engine/llm_reasoner.py
"""LLM 产业传导推演引擎"""

import json
import logging
from typing import Optional
from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
from ..models.reason_models import (
    TriggerEvent, ReasoningResult, PropagationStep,
    PathImpact, Beneficiary, ReasoningResponse,
)
from ..models.enums import ImpactLevel
from .path_finder import find_downstream_paths

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个产业链传导分析专家。给定产业链图谱的局部结构和触发事件，请做实测算分析。

## 分析规则
1. **传导比例**：考虑库存缓冲、长协锁价、替代可能性
2. **利润影响**：基于毛利率和成本占比计算毛利率受损区间（轻<3pp/中3-8pp/重8-15pp/致命>15pp）
3. **时间延迟**：考虑采购周期、库存消化周期
4. **受益方**：识别上游原材料供应商、替代品生产商
5. **置信度**：基于数据完整度和传导逻辑清晰度给出0-1置信度

## 输出格式（严格 JSON）
{
  "paths": [{
    "path_id": "P1",
    "path_chain": ["节点A", "节点B"],
    "propagation": [{"step":1,"from":"A","to":"B","cost_pass_through_pct":0,"margin_hit":{"min":0,"max":0,"level":"轻"},"lag_days":0,"reasoning":""}],
    "endpoint_impact": {"node":"","margin_hit_level":"","summary":""},
    "confidence":0.0
  }],
  "beneficiaries": [{"node_name":"","reason":""}],
  "overall_assessment": "",
  "confidence_overall": 0.0
}
"""


async def reason_chain_impact(
    trigger: TriggerEvent,
    max_depth: int = 3,
) -> ReasoningResponse:
    """执行产业传导推演

    Args:
        trigger: 触发事件（哪个节点、什么变量变化）
        max_depth: 下游遍历深度

    Returns:
        ReasoningResponse
    """
    if not settings.ENABLE_LLM_REASONING or not settings.CLAUDE_API_KEY:
        return ReasoningResponse(
            status="llm_unavailable",
            error_detail="LLM 推理未启用或缺少 CLAUDE_API_KEY",
        )

    # 第一步：查询 Neo4j 下游路径
    try:
        paths = await find_downstream_paths(trigger.node_id, max_depth)
    except Exception as e:
        logger.error(f"Neo4j 路径查询失败: {e}")
        return ReasoningResponse(
            status="error",
            error_detail=f"图谱查询失败: {str(e)}",
        )

    if not paths:
        return ReasoningResponse(
            status="ok",
            result=ReasoningResult(
                trigger=trigger.model_dump(),
                paths=[],
                overall_assessment="未找到该节点的下游供应关系链",
                confidence_overall=0.0,
            ),
        )

    # 第二步：组装 Prompt 并调用 Claude
    prompt = build_reasoning_prompt(trigger, paths)
    try:
        result = await call_claude(prompt)
    except Exception as e:
        logger.error(f"Claude 调用失败: {e}")
        return ReasoningResponse(
            status="error",
            error_detail=f"LLM 推理失败: {str(e)}",
        )

    return ReasoningResponse(status="ok", result=result)


def build_reasoning_prompt(trigger: TriggerEvent, paths: list[dict]) -> str:
    """组装推理 Prompt"""
    path_text = "\n".join([
        f"路径{i+1}: {' → '.join(p['path_chain'])} "
        f"(边属性: {json.dumps(p.get('edges', []), ensure_ascii=False)})"
        for i, p in enumerate(paths)
    ])
    return f"""【触发事件】{trigger.node_id}的{trigger.variable}变为{trigger.new_value}（变化{trigger.change_pct:+.1f}%）

【受影响路径】
{path_text}

请按分析规则做实测算并返回规定的 JSON 格式。"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
async def call_claude(prompt: str) -> ReasoningResult:
    """调用 Claude API（含自动重试 3 次）"""
    client = AsyncAnthropic(api_key=settings.CLAUDE_API_KEY)

    response = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=settings.LLM_TEMPERATURE,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text
    # 尝试提取 JSON
    json_text = text
    if "```json" in text:
        json_text = text.split("```json")[1].split("```")[0]
    elif "{" in text:
        start = text.index("{")
        json_text = text[start:]

    data = json.loads(json_text)

    # 解析为 Pydantic 模型
    paths = []
    for p in data.get("paths", []):
        propagation = []
        for prop in p.get("propagation", []):
            propagation.append(PropagationStep(
                step=prop["step"],
                from_node=prop["from"],
                to_node=prop["to"],
                cost_pass_through_pct=prop["cost_pass_through_pct"],
                margin_hit_min=prop.get("margin_hit", {}).get("min", 0),
                margin_hit_max=prop.get("margin_hit", {}).get("max", 0),
                level=ImpactLevel(prop.get("margin_hit", {}).get("level", "轻")),
                lag_days=prop.get("lag_days", 0),
                reasoning=prop.get("reasoning", ""),
            ))
        paths.append(PathImpact(
            path_id=p.get("path_id", ""),
            path_chain=p.get("path_chain", []),
            propagation=propagation,
            endpoint_impact=p.get("endpoint_impact", {}),
            confidence=p.get("confidence", 0.5),
        ))

    beneficiaries = [
        Beneficiary(node_name=b["node_name"], node_id="", reason=b.get("reason", ""))
        for b in data.get("beneficiaries", [])
    ]

    return ReasoningResult(
        trigger={"node_id": prompt[:100], "change_pct": 0},
        paths=paths,
        beneficiaries=beneficiaries,
        overall_assessment=data.get("overall_assessment", ""),
        confidence_overall=data.get("confidence_overall", 0.5),
        model_id=settings.CLAUDE_MODEL,
        tokens_in=response.usage.input_tokens if response.usage else 0,
        tokens_out=response.usage.output_tokens if response.usage else 0,
    )
