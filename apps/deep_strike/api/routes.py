"""deep-strike API 路由 - step_04 接入 profit_capture 剧本。[Ref: step_04]"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.deep_strike.playbooks import registry as pb_registry

router = APIRouter(prefix="/api", tags=["deep-strike"])


@router.get("/playbooks")
async def list_playbooks() -> dict:
    return {"playbooks": pb_registry.list_playbooks()}


@router.post("/playbooks/{playbook_id}/scan")
async def scan(playbook_id: str, body: dict) -> dict:
    symbol = body.get("symbol")
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")
    try:
        pb = pb_registry.get(playbook_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown playbook")
    result = await pb.scan(symbol, pass_event_id=body.get("pass_event_id"))
    return result.model_dump(mode="json")


@router.post("/playbooks/{playbook_id}/batch-scan")
async def batch_scan(playbook_id: str, body: dict) -> dict:
    symbols = body.get("symbols") or []
    if not symbols:
        raise HTTPException(status_code=400, detail="symbols required")
    try:
        pb = pb_registry.get(playbook_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown playbook")
    results = await pb.batch_scan(symbols, pass_event_id=body.get("pass_event_id"))
    return {"results": [r.model_dump(mode="json") for r in results]}
