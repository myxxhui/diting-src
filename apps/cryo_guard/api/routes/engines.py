"""三引擎 HTTP 路由占位（step_07 启用）。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/engines", tags=["engines"])
