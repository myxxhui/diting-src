"""Lighthouse-Alpha FastAPI 路由。

[Ref: 03_/02_维度二/.../step_03~07]
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import redis
from fastapi import APIRouter, HTTPException, Request

from apps.deep_strike.config import settings
from apps.deep_strike.lighthouse import LighthouseOrchestrator
from apps.deep_strike.lighthouse.monitor_dict_writer import MonitorDictWriter
from apps.deep_strike.lighthouse.schemas import (
    ArchitectInput,
    CriticInput,
    ScorerInput,
    SnifferInput,
    TimerInput,
)
from apps.deep_strike.lighthouse.architect import TheArchitect
from apps.deep_strike.lighthouse.critic import TheCritic
from apps.deep_strike.lighthouse.scorer import TheScorer
from apps.deep_strike.lighthouse.sniffer import TheSniffer
from apps.deep_strike.lighthouse.timer import TheTimer

router = APIRouter(prefix="/api/lighthouse", tags=["lighthouse"])


def _sync_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


@router.get("/health")
async def lighthouse_health() -> dict[str, Any]:
    return {"ok": True, "service": "lighthouse", "scenes": ["sniffer", "critic", "scorer", "architect", "timer"]}


@router.post("/sniffer/run")
async def run_sniffer(body: dict) -> dict[str, Any]:
    inp = SnifferInput(
        raw_texts=body.get("raw_texts") or [],
        window_start=date.fromisoformat(body["window_start"]),
        window_end=date.fromisoformat(body["window_end"]),
        source_hint=body.get("source_hint"),
    )
    out = TheSniffer().call(inp)
    return out.model_dump(mode="json")


@router.post("/critic/run")
async def run_critic(body: dict) -> dict[str, Any]:
    inp = CriticInput.model_validate(body)
    out = TheCritic().call(inp)
    return out.model_dump(mode="json")


@router.post("/scorer/run")
async def run_scorer(body: dict) -> dict[str, Any]:
    inp = ScorerInput.model_validate(body)
    out = TheScorer().call(inp)
    return out.model_dump(mode="json")


@router.post("/sniffer/{cluster_id}/score")
async def sniffer_cluster_score(cluster_id: str, body: dict) -> dict[str, Any]:
    """The Scorer 三维分（L3 step_07 D 项）。"""
    inp = ScorerInput(
        cluster_id=cluster_id,
        cluster_keyword=body.get("cluster_keyword", cluster_id),
        candidate_symbols=body.get("candidate_symbols", []),
        policy_text_excerpts=body.get("policy_text_excerpts", []),
        industry_research_excerpts=body.get("industry_research_excerpts", []),
        a_share_mapping_excerpts=body.get("a_share_mapping_excerpts", []),
    )
    out = TheScorer().call(inp)
    return out.model_dump(mode="json")


@router.post("/architect/run")
async def run_architect(body: dict, request: Request) -> dict[str, Any]:
    inp = ArchitectInput.model_validate(body)
    matrix = TheArchitect().call(inp)
    r = _sync_redis()
    write_result = MonitorDictWriter(r).write(matrix)
    return {
        "matrix": matrix.model_dump(mode="json"),
        "redis": write_result,
    }


@router.post("/orchestrate")
async def orchestrate(body: dict) -> dict[str, Any]:
    sniffer_in = SnifferInput(
        raw_texts=body.get("raw_texts") or [],
        window_start=date.fromisoformat(body["window_start"]),
        window_end=date.fromisoformat(body["window_end"]),
    )
    orch = LighthouseOrchestrator()
    result = orch.run_for_clusters(sniffer_in, candidate_context=body.get("candidate_context"))
    return {
        "summary": result.summary(),
        "sniffer": result.sniffer.model_dump(mode="json"),
        "outcomes": [
            {
                "cluster_id": o.cluster.cluster_id,
                "keyword": o.cluster.keyword,
                "status": o.status,
                "physical_gate": o.critic.physical_gate if o.critic else None,
                "decision": o.scorer.decision if o.scorer else None,
                "composite": o.scorer.composite if o.scorer else None,
            }
            for o in result.outcomes
        ],
        "errors": result.errors,
    }
