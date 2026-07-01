"""Z0-A 节点环节 T2 语义研判（每 BOM 节点 1 次 LLM）。

[Ref: 32_ §2.4.9.a · node_segment_t2 合约]
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from apps.copilot.modules.strategic.duan_config import load_duan_node_gates

logger = logging.getLogger(__name__)

_NODE_T2_SYSTEM = """**重要：所有输出必须用简体中文，禁止输出英文。**

你是中国 A 股产业链环节分析专家。任务：对**单个产业链环节**（不是具体上市公司）做段永平式「环节是不是好生意」初判。

禁止：分析具体股票代码、公司财报、管理层、估值。
必须：只讨论该环节在技术路线中的位置、是否会被 bypass、利润池归属、5～10 年趋势。

返回纯 JSON（无 markdown）：
{
  "segment_bypass_risk": "low|mid|high",
  "profit_pool_anchor": "in_segment|upstream|downstream|diffuse",
  "horizon_outlook": "expand|stable|shrink",
  "reasoning": "40-100字中文"
}"""


def score_node_segment_t2(
    *,
    node_id: str,
    node_name: str,
    tier: str,
    ecosystem_layer: str = "",
    sector_context: str = "",
    topology_snippet: str = "",
    model_override: Optional[str] = None,
) -> dict[str, Any]:
    """单节点 T2 · 失败返回空 dict（调用方 → provisional）。"""
    cfg = (load_duan_node_gates().get("node_segment_t2") or {})
    model = model_override or cfg.get("model", "deepseek-v4-pro")
    scene = cfg.get("scene", "z0_node_segment_t2")

    user_prompt = f"""请用简体中文输出。环节 node_id={node_id}
环节名称：{node_name}
tier：{tier}
ecosystem_layer：{ecosystem_layer or '未标注'}
赛道上下文：{sector_context or '战略板块'}
拓扑摘要：{topology_snippet or '无'}

请输出 segment_bypass_risk / profit_pool_anchor / horizon_outlook / reasoning（reasoning 必须用中文）。"""

    try:
        from apps.common.ai_dispatcher import AIDispatcher

        dispatcher = AIDispatcher.default()
        resp = dispatcher.call(
            scene=scene,
            messages=[
                {"role": "system", "content": _NODE_T2_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=int(cfg.get("max_output_tokens", 500)),
            model_override=model,
        )
        raw = resp.text if hasattr(resp, "text") else str(resp)
        parsed = _parse_node_t2(raw)
        if parsed:
            parsed["node_id"] = node_id
            parsed["source"] = "node_segment_t2"
            logger.info("[node_t2] %s OK bypass=%s pool=%s horizon=%s",
                        node_id, parsed.get("segment_bypass_risk"), parsed.get("profit_pool_anchor"),
                        parsed.get("horizon_outlook"))
        return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("[node_t2] %s 失败: %s", node_id, exc)
        return {}


def score_node_set_t2(
    nodes: list[dict[str, Any]],
    *,
    sector_context: str = "",
    topology_snippet: str = "",
) -> list[dict[str, Any]]:
    """批量节点 T2（顺序调用 · 单节点失败不影响其他）。"""
    out: list[dict[str, Any]] = []
    for node in nodes:
        nid = str(node.get("node_id", ""))
        t2 = score_node_segment_t2(
            node_id=nid,
            node_name=str(node.get("name", "")),
            tier=str(node.get("tier", "配套")),
            ecosystem_layer=str(node.get("ecosystem_layer") or node.get("layer") or ""),
            sector_context=sector_context,
            topology_snippet=topology_snippet,
        )
        enriched = dict(node)
        if t2:
            enriched["node_duan_t2"] = t2
            enriched["node_t2"] = t2
        out.append(enriched)
    return out


def _parse_node_t2(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}

    bypass = str(data.get("segment_bypass_risk", "mid")).lower()
    pool = str(data.get("profit_pool_anchor", "diffuse")).lower()
    horizon = str(data.get("horizon_outlook", "stable")).lower()
    if bypass not in ("low", "mid", "high"):
        bypass = "mid"
    if pool not in ("in_segment", "upstream", "downstream", "diffuse"):
        pool = "diffuse"
    if horizon not in ("expand", "stable", "shrink"):
        horizon = "stable"
    return {
        "segment_bypass_risk": bypass,
        "profit_pool_anchor": pool,
        "horizon_outlook": horizon,
        "reasoning": str(data.get("reasoning", ""))[:200],
    }
