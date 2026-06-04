"""行情雷达扫描阶段组合：仅允许三种预设。

[Ref: 行情解析工作台 · 雷达分阶段扫描]
"""
from __future__ import annotations

RADAR_STAGE_COMBO_MSG = "仅支持三种组合：仅 T2、T0+T2、T0+T1+T2"


def validate_radar_stage_combo(
    enable_t0: bool,
    enable_t1: bool,
    enable_t2: bool,
) -> None:
    """合法：T2 | T0+T2 | T0+T1+T2。"""
    if enable_t1 and not enable_t0:
        raise ValueError("勾选 T1 须同时勾选 T0（基础采集数据）")
    if enable_t0 and enable_t1 and enable_t2:
        return
    if enable_t0 and not enable_t1 and enable_t2:
        return
    if not enable_t0 and not enable_t1 and enable_t2:
        return
    raise ValueError(RADAR_STAGE_COMBO_MSG)


def combo_label(enable_t0: bool, enable_t1: bool, enable_t2: bool) -> str:
    if enable_t0 and enable_t1 and enable_t2:
        return "T0+T1+T2"
    if enable_t0 and enable_t2:
        return "T0+T2"
    if enable_t2:
        return "仅 T2"
    return "未选择"
