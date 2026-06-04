"""Context-Aware Agentic Sandbox schema 契约。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


AssetStatus = Literal["planning", "executing", "archived", "discarded"]
ProbeStatus = Literal["pending_code", "data_ready"]


class ProbeBlueprint(BaseModel):
    dimension: str
    target_data_desc: str
    primary_source_name: str
    why_this_source: str
    alternative_sources: list[str] = Field(default_factory=list)
    collection_guidance: str
    falsification_logic: str


class OneShotPlanningOutput(BaseModel):
    probes: list[ProbeBlueprint] = Field(default_factory=list)


class OneShotDeductionOutput(BaseModel):
    cross_validation_analysis: str
    falsified_flag: bool
    final_recommendation: str


class ProbeTaskOut(BaseModel):
    id: str
    asset_id: str
    status: ProbeStatus
    probe_blueprint: dict
    refined_data: Optional[dict] = None


class AssetSandboxOut(BaseModel):
    asset_id: str
    symbol_code: str
    status: AssetStatus
    core_logic: str
    radar_initial_analysis: dict = Field(default_factory=dict)
    planning_snapshot: Optional[dict] = None
    deduction_snapshot: Optional[dict] = None
    probes: list[ProbeTaskOut] = Field(default_factory=list)
    all_data_ready: bool = False
