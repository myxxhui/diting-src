"""审计查询路由占位（step_08 启用）。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/audit", tags=["audit"])
