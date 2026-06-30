# apps/industry_graph/backend/api/graph_reason.py
"""LLM 推演 API"""

from fastapi import APIRouter, HTTPException
from ..models.reason_models import ReasoningRequest, ReasoningResponse
from ..engine.llm_reasoner import reason_chain_impact
from ..engine.path_finder import find_downstream_paths

router = APIRouter(prefix="/api/graph/reason", tags=["reason"])


@router.post("/", response_model=ReasoningResponse, summary="执行产业传导推演")
async def run_reasoning(request: ReasoningRequest):
    """触发 LLM 推演：给定变量变化 → 下游传导分析

    Example:
        POST /api/graph/reason/
        {
            "trigger": {"node_id": "lithium_carbonate", "variable": "price",
                        "new_value": "150000元/吨", "change_pct": 50.0},
            "max_depth": 3
        }
    """
    try:
        result = await reason_chain_impact(request.trigger, request.max_depth)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"推演失败: {str(e)}")


@router.post("/preview-paths", summary="预览受影响路径（不调用 LLM）")
async def preview_paths(request: ReasoningRequest):
    """仅查询 Neo4j 路径，不调用 LLM — 用于快速预览"""
    try:
        paths = await find_downstream_paths(request.trigger.node_id, request.max_depth)
        return {"paths": paths, "count": len(paths)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"图谱查询失败: {str(e)}")
