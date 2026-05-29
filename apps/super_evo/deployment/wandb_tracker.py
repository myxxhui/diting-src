"""WandB 实验跟踪封装。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from apps.super_evo.config import settings


def _import_wandb():
    try:
        import wandb  # type: ignore

        return wandb
    except ImportError as exc:
        raise RuntimeError("wandb is not installed; run pip install wandb") from exc


class WandbTracker:
    """启动期实验跟踪薄封装。

    本阶段不强制 online；如 WANDB_API_KEY 未设置自动 fallback 为 offline。
    """

    def __init__(
        self,
        project: str | None = None,
        entity: str | None = None,
        mode: str | None = None,
    ) -> None:
        self.project = project or settings.wandb_project
        self.entity = entity or settings.wandb_entity
        self.mode = mode or settings.wandb_mode
        if not os.getenv("WANDB_API_KEY") and self.mode != "disabled":
            self.mode = "offline"
        self._wandb = _import_wandb()

    @contextmanager
    def run(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[Any]:
        run = self._wandb.init(
            project=self.project,
            entity=self.entity,
            name=name,
            config=config or {},
            tags=tags or [],
            mode=self.mode,
            reinit=True,
        )
        try:
            yield run
        finally:
            self._wandb.finish()

    def log_metrics(self, run: Any, metrics: dict[str, float], step: int | None = None) -> None:
        if step is None:
            run.log(metrics)
        else:
            run.log(metrics, step=step)

    def health(self) -> dict:
        return {
            "ok": True,
            "project": self.project,
            "mode": self.mode,
            "key_set": bool(os.getenv("WANDB_API_KEY")),
        }
