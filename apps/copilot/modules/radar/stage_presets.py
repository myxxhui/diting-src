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


def workflow_summary(
    enable_t0: bool,
    enable_t1: bool,
    enable_t2: bool,
    *,
    t2_model: str | None = None,
) -> str:
    """进度面板顶部流程说明（与勾选一致）。"""
    t2 = (t2_model or "Opus").strip()
    if enable_t0 and enable_t1 and enable_t2:
        return (
            f"流程：解析标的 → T0 采集 → T1 压缩事实矩阵入库 → T2 深度研报（{t2}）；"
            "索引框触发为全新推演。"
        )
    if enable_t0 and enable_t2:
        return (
            f"流程：解析标的 → T0 采集（原始数据不压缩）→ T2 深度研报（{t2}）；"
            "不经 T1，索引框触发为全新推演。"
        )
    if enable_t2:
        return (
            f"流程：解析标的 → T2 按布局维度主题自主推演（{t2}）→ 写入；"
            "不加载 T0/T1 缓存；索引框每次重新分析。"
        )
    return RADAR_STAGE_COMBO_MSG


def scan_steps_for_combo(
    enable_t0: bool,
    enable_t1: bool,
    enable_t2: bool,
    *,
    t1_mode: str | None = None,
    t2_model: str | None = None,
) -> list[dict[str, str | int]]:
    """进度清单与百分比边界（仅包含本组合会执行的步骤）。"""
    from apps.copilot.modules.radar.model_router import t1_step_label

    t2_lbl = (t2_model or "Opus").strip()
    steps: list[tuple[str, str, int]] = [("resolve", "解析标的代码", 5)]

    if enable_t0:
        steps.append(("t0", "T0 采集行情与公司资料", 22))
    elif enable_t2:
        pass

    if enable_t1:
        steps.append(("t1", t1_step_label(t1_mode=t1_mode), 48))
    elif enable_t0 and enable_t2:
        steps.append(("t1", "T1 已跳过（T0 直供 T2）", 40))

    if enable_t2:
        steps.append(("t2", f"T2 深度研报（{t2_lbl}）", 78))

    steps.append(("persist", "写入缓存与候选库", 92))
    steps.append(("done", "分析完成", 100))

    return [{"id": sid, "label": label, "pct": pct} for sid, label, pct in steps]


def pct_for_step(steps: list[dict[str, str | int]], step_id: str) -> int | None:
    for s in steps:
        if s.get("id") == step_id:
            return int(s["pct"])
    return None
