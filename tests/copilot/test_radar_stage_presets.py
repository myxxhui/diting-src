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
    assert RADAR_STAGE_COMBO_MSG in str(exc.value)


def test_combo_label():
    assert combo_label(False, False, True) == "仅 T2"
    assert combo_label(True, False, True) == "T0+T2"
    assert combo_label(True, True, True) == "T0+T1+T2"


def test_scan_steps_t2_only():
    ids = [s["id"] for s in scan_steps_for_combo(False, False, True)]
    assert ids == ["resolve", "t0", "t1", "t2", "persist", "done"]
    assert "仅 T2" in workflow_summary(False, False, True)


def test_scan_steps_t0_t2():
    ids = [s["id"] for s in scan_steps_for_combo(True, False, True)]
    assert "t0" in ids and "t2" in ids
    assert "t1" not in ids


def test_scan_steps_full():
    ids = [s["id"] for s in scan_steps_for_combo(True, True, True)]
    assert ids == ["resolve", "t0", "t1", "t2", "persist", "done"]
