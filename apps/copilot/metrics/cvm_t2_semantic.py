"""CVM T2 语义评分引擎（Claude Opus 驱动的 C2/C5/C6 深度分析）。

[Ref: 32_ §2.4.4 · 34_ §3.7]

Pipeline:
  1. 读取 L1 provisional scorecard
  2. 对每只候选标的构建 T2 Prompt（role_tag + 行业上下文 + T1 scores）
  3. Claude Opus 分析 → JSON 结构化输出
  4. 更新 scorecard C2/C5/C6 维度

降级策略:
  - T2 不可用（LLM 超时/余额不足）→ 保留 T1 规则结果，provisional=True 不变
  - 单标的失败不影响其他标的
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── T2 System Prompt ──

_CVM_T2_SYSTEM_PROMPT = """你是一个中国 A 股产业链深度分析专家。你的任务是：
对给定标的在特定产业链节点中的竞争地位，从三个维度进行深度语义分析。

你必须始终返回纯 JSON 对象，无 markdown 包裹，结构如下：
{
  "c2_chokepoint": {
    "score": 0.75,
    "replacement_cost": "high",
    "certification_barrier": true,
    "capacity_bottleneck": false,
    "reasoning": "中文判断依据，40-100字"
  },
  "c5_migration": {
    "s_curve_position": "mid",
    "upgrade_probability": 0.6,
    "bypass_risk": "low",
    "reasoning": "中文判断依据，40-100字"
  },
  "c6_durability": {
    "cross_phase_decay": 0.3,
    "valuation_stability": 0.7,
    "phase_span_estimate": 3,
    "reasoning": "中文判断依据，40-100字"
  }
}
"""


def score_peer_set_t2(
    l1_rows: list[dict[str, Any]],
    *,
    scene: str = "z0_t2_concept_analysis",
    model_override: str = "claude-opus-4-6",
) -> list[dict[str, Any]]:
    """T2 语义评分：对 L1 行逐标的调用 LLM 增强 C2/C5/C6。

    Args:
        l1_rows: score_peer_set() 输出的 T1 行列表
        scene: AIDispatcher 场景名
        model_override: 使用的模型

    Returns:
        更新后的 rows（每行含 t2_enriched 标志）
    """
    from apps.common.ai_dispatcher import AIDispatcher

    dispatcher = AIDispatcher.default()
    updated = []

    for row in l1_rows:
        symbol = row.get("symbol", "??????")
        try:
            result = _score_single_t2(symbol, row, dispatcher, scene, model_override)
            scores = row.get("scores", {})
            if result.get("c2_chokepoint"):
                cp = result["c2_chokepoint"]
                scores["c2"] = {
                    "band": _score_to_band(cp.get("score", 0.5)),
                    "replacement_cost": cp.get("replacement_cost", "mid"),
                    "certification_barrier": cp.get("certification_barrier", False),
                    "capacity_bottleneck": cp.get("capacity_bottleneck", False),
                    "evidence_refs": [cp.get("reasoning", "")],
                    "needs_semantic_review": False,
                    "t2_enriched": True,
                }
            if result.get("c5_migration"):
                m = result["c5_migration"]
                scores["c5"] = {
                    "bypass_risk": m.get("bypass_risk", "mid"),
                    "s_curve_position": m.get("s_curve_position", "mid"),
                    "upgrade_probability": m.get("upgrade_probability", 0.5),
                    "evidence_refs": [m.get("reasoning", "")],
                    "t2_enriched": True,
                }
            if result.get("c6_durability"):
                d = result["c6_durability"]
                scores["c6"] = {
                    "band": _score_to_band(1.0 - d.get("cross_phase_decay", 0.5)),
                    "cross_phase_decay": d.get("cross_phase_decay", 0.5),
                    "valuation_stability": d.get("valuation_stability", 0.5),
                    "phase_span_estimate": d.get("phase_span_estimate", 1),
                    "evidence_refs": [d.get("reasoning", "")],
                    "t2_enriched": True,
                }
            row["scores"] = scores
            row["provisional"] = False
            row["t2_enriched"] = True
            logger.info("[cvm_t2] %s T2 语义增强完成", symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cvm_t2] %s T2 失败（保留 T1）: %s", symbol, exc)
            row["t2_enriched"] = False
            row["t2_error"] = str(exc)[:120]
        updated.append(row)

    return updated


def _score_single_t2(
    symbol: str,
    row: dict[str, Any],
    dispatcher: Any,
    scene: str,
    model_override: str,
) -> dict[str, Any]:
    """单标的 T2 语义分析。"""
    scores = row.get("scores", {})
    role_suggested = row.get("role_suggested", "?")
    anchor_path = row.get("anchor_path", "?")
    c7 = scores.get("c7", {})
    role_tag = row.get("role_tag_source", role_suggested)

    # T1 已有信息摘要
    c1_band = scores.get("c1", {}).get("band", "?")
    c3_band = scores.get("c3", {}).get("band", "?")
    c4_band = scores.get("c4", {}).get("band", "?")
    c7_pass = c7.get("pass", True)
    c7_cat = c7.get("category", "?")

    user_prompt = f"""请分析以下标的的产业链竞争地位：

标的代码：{symbol}
角色标签：{role_tag}
建议角色：{role_suggested}
锚定路径：{anchor_path}
C7 分类：{c7_cat} / 通过：{c7_pass}

T1 初步评分：
- C1 利润池占有：{c1_band}
- C3 价值量弹性：{c3_band}
- C4 结构主导权：{c4_band}

请从以下三个维度输出严格 JSON（无 markdown）：
1. C2 卡脖子深度（替换成本、认证壁垒、产能瓶颈）
2. C5 生态迁移安全（S曲线位置、升格概率、bypass风险）
3. C6 价值持续性（跨phase衰减、估值稳定性）"""

    resp = dispatcher.call(
        scene=scene,
        messages=[
            {"role": "system", "content": _CVM_T2_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
        model_override=model_override,
    )
    raw = resp.text if hasattr(resp, "text") else str(resp)
    return _parse_t2_output(raw)


def _parse_t2_output(raw: str) -> dict[str, Any]:
    """鲁棒解析 T2 LLM JSON 输出。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    logger.warning("[cvm_t2] JSON 解析失败: %s", raw[:150])
    return {}


def _score_to_band(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "mid_high"
    if score >= 0.4:
        return "mid"
    if score >= 0.2:
        return "acceptable"
    return "low"
