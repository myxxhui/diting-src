"""health_score → push_level 映射（0 绿 / 1 黄 / 2 橙 / 3 红）。

[Ref: 03_/03_维度三/.../step_06_健康度计算与push_level.md §3.5.1 F6]
"""
from __future__ import annotations


def health_to_push_level(health_score: float) -> int:
    """DNA 映射：0-29→3 红 / 30-59→2 橙 / 60-79→1 黄 / 80-100→0 绿。"""
    score = max(0.0, min(100.0, float(health_score)))
    if score <= 29:
        return 3
    if score <= 59:
        return 2
    if score <= 79:
        return 1
    return 0
