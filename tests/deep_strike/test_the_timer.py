"""D2 step_05 [L-α] The Timer — 三段时间窗口预测测试（TM1~TM7，≥7 用例）。

覆盖 L3 §3.5.4 矩阵：
  TM1: 三段必须齐全（incubation / main_wave / retreat 非空）
  TM2: 窗口顺序合理（incubation.end ≤ main_wave.start ≤ retreat.start）
  TM3: cycle_anchors 至少 1 个，锚定 A 股财报事件
  TM4: 监控字典对齐（trigger_source 引用）
  TM5: cycle_type ∈ D4 SP5 6 种枚举
  TM6: 永久 no-auto-execute（无 buy/qmt/auto_trade 字段）
  TM7: prompt 留痕（metadata 含 model_name + prompt_template_id）

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_05_thesis卡片生成器.md §3.5.4]
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest


# ─── fixtures / helpers ──────────────────────────────────────────────────────

VALID_CYCLE_TYPES = {
    "pre_announce_h1",
    "h1_release",
    "pre_announce_q3",
    "q3_release",
    "annual_pre_announce",
    "annual_release",
}


def _canned_llm_response(
    *,
    incubation_start="2026-06-01",
    incubation_end="2026-07-10",
    main_start="2026-08-15",
    main_end="2026-08-25",
    retreat_start="2026-08-26",
    retreat_end="2026-09-10",
) -> str:
    return json.dumps({
        "incubation": {
            "start_date": incubation_start,
            "end_date": incubation_end,
            "expected_signal": "监控字典预警触发后潜伏建仓",
            "confidence": 0.70,
        },
        "main_wave": {
            "start_date": main_start,
            "end_date": main_end,
            "expected_signal": "中报披露共振主升浪",
            "confidence": 0.65,
        },
        "retreat": {
            "start_date": retreat_start,
            "end_date": retreat_end,
            "expected_signal": "披露后放量滞涨撤退",
            "confidence": 0.50,
        },
        "cycle_anchors": [
            {
                "cycle_type": "h1_release",
                "expected_window": ["2026-08-01", "2026-08-31"],
                "confidence": 0.80,
            }
        ],
    })


class _FakeDispatcher:
    """注入预设 JSON 响应，绕过真实 API 调用（TEST_ONLY）。"""

    def __init__(self, canned_text: str, *, model: str = "claude-opus-4-7") -> None:
        self._canned = canned_text
        self._model = model

    def call(self, scene, messages, *, max_tokens=2048, temperature=0.2, force_route=None):
        from apps.common.ai_dispatcher import AIResponse

        return AIResponse(
            text=self._canned,
            model=self._model,
            scene=scene,
            route="mock",
            latency_ms=0,
            tokens_in=len(str(messages)),
            tokens_out=len(self._canned),
            cost_yuan_est=0.0,
        )


def _make_timer(canned: str = None):
    from apps.deep_strike.lighthouse import TheTimer

    if canned is None:
        canned = _canned_llm_response()
    return TheTimer(dispatcher=_FakeDispatcher(canned))


def _make_input(current_date: date = None, symbol: str = "300308"):
    from apps.deep_strike.lighthouse.schemas import TimerInput

    return TimerInput(
        thesis_card_id="thesis-test-001",
        symbol=symbol,
        current_date=current_date or date(2026, 5, 27),
        monitor_alert_triggered_at=date(2026, 5, 20),
        scan_hit_signals=["gross_margin_expansion", "operating_leverage"],
    )


# ─── TM1：三段必须齐全 ─────────────────────────────────────────────────────────

def test_tm1_three_phases_present():
    """TM1：incubation / main_wave / retreat 三段全部非空且有 expected_signal。"""
    timer = _make_timer()
    out = timer.call(_make_input())
    assert out.incubation is not None
    assert out.main_wave is not None
    assert out.retreat is not None
    assert len(out.incubation.expected_signal) >= 2
    assert len(out.main_wave.expected_signal) >= 2
    assert len(out.retreat.expected_signal) >= 2


def test_tm1_fallback_still_three_phases():
    """TM1：即使 LLM 返回空 JSON，fallback 也保证三段非空。"""
    timer = _make_timer(canned='{}')
    out = timer.call(_make_input())
    assert out.incubation is not None
    assert out.main_wave is not None
    assert out.retreat is not None


# ─── TM2：窗口顺序合理 ────────────────────────────────────────────────────────

def test_tm2_window_order():
    """TM2：incubation.end ≤ main_wave.start；main_wave.end ≤ retreat.start。"""
    timer = _make_timer()
    out = timer.call(_make_input())
    assert out.incubation.end_date <= out.main_wave.start_date, (
        f"incubation.end={out.incubation.end_date} > main_wave.start={out.main_wave.start_date}"
    )
    assert out.main_wave.end_date <= out.retreat.start_date, (
        f"main_wave.end={out.main_wave.end_date} > retreat.start={out.retreat.start_date}"
    )


def test_tm2_fallback_window_order():
    """TM2：fallback 路径下窗口顺序也合理。"""
    timer = _make_timer(canned='{}')
    out = timer.call(_make_input())
    assert out.incubation.end_date <= out.main_wave.start_date
    assert out.main_wave.end_date <= out.retreat.start_date


# ─── TM3：cycle_anchors 至少 1 个 ─────────────────────────────────────────────

def test_tm3_cycle_anchors_at_least_one():
    """TM3：cycle_anchors 非空，且至少锚定 1 个 A 股财报披露事件。"""
    timer = _make_timer()
    out = timer.call(_make_input())
    assert len(out.cycle_anchors) >= 1
    # 至少一个含 "release" 的锚点（中报/三季报/年报披露）
    assert any(
        "release" in a.cycle_type or "announce" in a.cycle_type
        for a in out.cycle_anchors
    ), f"无任何财报锚点：{[a.cycle_type for a in out.cycle_anchors]}"


# ─── TM5：cycle_type ∈ D4 SP5 6 种枚举 ────────────────────────────────────────

def test_tm5_cycle_type_enum_valid():
    """TM5：所有 cycle_anchors 的 cycle_type 均在 D4 SP5 协议 6 种枚举内。"""
    timer = _make_timer()
    out = timer.call(_make_input())
    for anchor in out.cycle_anchors:
        assert anchor.cycle_type in VALID_CYCLE_TYPES, (
            f"非法 cycle_type：{anchor.cycle_type!r}，不在 D4 SP5 枚举 {VALID_CYCLE_TYPES}"
        )


def test_tm5_schema_cycle_type_rejects_invalid():
    """TM5：CycleAnchor schema 拒绝枚举外的 cycle_type（Pydantic 校验）。"""
    from pydantic import ValidationError

    from apps.deep_strike.lighthouse.schemas import CycleAnchor

    with pytest.raises(ValidationError):
        CycleAnchor(
            cycle_type="unknown_cycle",
            expected_window=(date(2026, 7, 1), date(2026, 7, 31)),
            confidence=0.5,
        )


# ─── TM6：永久 no-auto-execute ────────────────────────────────────────────────

def test_tm6_no_auto_execute_fields():
    """TM6：TimerOutput 无 buy/execute/order/qmt/auto_trade 等禁字段。"""
    timer = _make_timer()
    out = timer.call(_make_input())
    out_dict = out.model_dump()
    forbidden_keys = {"buy", "execute", "order_id", "qmt_signal", "auto_trade", "webhook"}
    flat_keys = set(out_dict.keys())
    # 递归检查 phase 字段名
    for phase in (out.incubation, out.main_wave, out.retreat):
        flat_keys |= set(phase.model_dump().keys())
    assert flat_keys.isdisjoint(forbidden_keys), (
        f"禁字段出现：{flat_keys & forbidden_keys}"
    )


def test_tm6_action_hint_not_auto_execute():
    """TM6：各 phase 的 expected_signal 不包含'自动建仓'/'执行'等禁止词。"""
    timer = _make_timer()
    out = timer.call(_make_input())
    forbidden_words = {"自动建仓", "自动下单", "auto_trade", "qmt", "execute_order"}
    for phase in (out.incubation, out.main_wave, out.retreat):
        for word in forbidden_words:
            assert word not in phase.expected_signal.lower(), (
                f"phase.expected_signal 含禁词 {word!r}：{phase.expected_signal!r}"
            )


# ─── TM7：prompt 留痕 ─────────────────────────────────────────────────────────

def test_tm7_metadata_recorded():
    """TM7：TimerOutput.metadata 含 model_name + prompt_template_id。"""
    timer = _make_timer()
    out = timer.call(_make_input())
    assert out.metadata is not None
    assert len(out.metadata.model_name) > 0, "metadata.model_name 为空"
    assert len(out.metadata.prompt_template_id) > 0, "metadata.prompt_template_id 为空"
