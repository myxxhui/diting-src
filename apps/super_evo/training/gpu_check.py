"""GPU 与显存检查工具。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04_C3_LLaMA_Factory训练流水线.md]
[Ref: 03_/05_维度五/04_模型训练与部署.md#2.1]
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class GpuInfo:
    available: bool
    count: int
    names: list[str]
    free_mib: list[int]
    total_mib: list[int]
    reason: str | None = None

    def smallest_free_mib(self) -> int:
        return min(self.free_mib) if self.free_mib else 0


def check_gpu(min_free_mib: int = 18_000) -> GpuInfo:
    try:
        import torch  # type: ignore
    except ImportError:
        return GpuInfo(
            available=False,
            count=0,
            names=[],
            free_mib=[],
            total_mib=[],
            reason="torch not installed",
        )

    if not torch.cuda.is_available():
        return GpuInfo(
            available=False,
            count=0,
            names=[],
            free_mib=[],
            total_mib=[],
            reason="cuda not available",
        )

    n = torch.cuda.device_count()
    names = [torch.cuda.get_device_name(i) for i in range(n)]
    free_mib: list[int] = []
    total_mib: list[int] = []
    for i in range(n):
        free, total = torch.cuda.mem_get_info(i)
        free_mib.append(int(free // (1024 * 1024)))
        total_mib.append(int(total // (1024 * 1024)))

    info = GpuInfo(available=True, count=n, names=names, free_mib=free_mib, total_mib=total_mib)
    if info.smallest_free_mib() < min_free_mib:
        info.reason = f"free {info.smallest_free_mib()}MiB < required {min_free_mib}MiB"
        info.available = False
    return info


def is_llamafactory_installed() -> bool:
    return shutil.which("llamafactory-cli") is not None
