"""雷达扫描阶段组合校验。"""
import pytest

from apps.copilot.modules.radar.stage_presets import (
    RADAR_STAGE_COMBO_MSG,
    combo_label,
    scan_steps_for_combo,
    validate_radar_stage_combo,
    workflow_summary,
)


@pytest.mark.parametrize(
    "t0,t1,t2",
    [
        (False, False, True),
        (True, False, True),
        (True, True, True),
    ],
)
def test_valid_combos(t0, t1, t2):
    validate_radar_stage_combo(t0, t1, t2)


@pytest.mark.parametrize(
    "t0,t1,t2",
    [
        (False, False, False),
        (True, False, False),
        (True, True, False),
        (False, True, True),
        (False, True, False),
    ],
)
def test_invalid_combos(t0, t1, t2):
    with pytest.raises(ValueError) as exc:
        validate_radar_stage_combo(t0, t1, t2)
    msg = str(exc.value)
    assert RADAR_STAGE_COMBO_MSG in msg or "勾选 T1" in msg


def test_combo_label():
    assert combo_label(False, False, True) == "仅 T2"
    assert combo_label(True, False, True) == "T0+T2"
    assert combo_label(True, True, True) == "T0+T1+T2"


def test_scan_steps_t2_only():
    ids = [s["id"] for s in scan_steps_for_combo(False, False, True)]
    assert ids == ["resolve", "t2", "persist", "done"]
    assert "自主推演" in workflow_summary(False, False, True)


def test_scan_steps_t0_t2():
    steps = scan_steps_for_combo(True, False, True)
    ids = [s["id"] for s in steps]
    assert "t0" in ids and "t2" in ids
    t1 = next(s for s in steps if s["id"] == "t1")
    assert "跳过" in str(t1["label"])


def test_scan_steps_full():
    ids = [s["id"] for s in scan_steps_for_combo(True, True, True)]
    assert ids == ["resolve", "t0", "t1", "t2", "persist", "done"]
