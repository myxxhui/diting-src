"""雷达 Opus 对话会话存储。"""
from __future__ import annotations

from apps.copilot.modules.radar.chat import (
    _build_system_extra,
    _build_system_for_turn,
    clear_session,
    load_messages,
    new_session_id,
    save_messages,
    summarize_context_meta,
)


def test_build_system_extra_with_research_context():
    ctx = {
        "name": "英维克",
        "jl4_indicator_count": 12,
        "compact": {"checklist": {"JL1": []}, "jl4_catalog": {"002837": {}}},
    }
    text = _build_system_extra("002837", None, research_context=ctx)
    assert "JL1–JL4 本地数据包" in text
    assert "英维克" in text
    assert "JL4 T1 指标数：12" in text


def test_summarize_context_meta_t1_envelope():
    research = {
        "signal_key": "002837.SZ",
        "name": "英维克",
        "jl4_indicator_count": 8,
        "compact": {"checklist": {"JL1": [], "JL2": []}},
    }
    system = _build_system_extra("002837", None, research_context=research)
    meta = summarize_context_meta(
        symbol="002837",
        research_context=research,
        scan_context=None,
        user_text="问题\n\n【JL1–JL3 公开市场数据补充要求】",
        system_prompt=system,
    )
    assert meta["context_mode"] == "t1_envelope"
    assert meta["has_jl_envelope_in_system"] is True
    assert meta["jl13_appended"] is True
    assert meta["jl4_indicator_count"] == 8


def test_summarize_context_meta_scan_fallback():
    meta = summarize_context_meta(
        symbol="002837",
        research_context=None,
        scan_context={"name": "英维克"},
        user_text="问题",
        system_prompt="",
    )
    assert meta["context_mode"] == "radar_scan_fallback"


def test_summarize_context_meta_subsequent_turn():
    meta = summarize_context_meta(
        symbol="601138",
        research_context=None,
        scan_context=None,
        user_text="后续问题",
        system_prompt="CHAT_SYSTEM\n\n【会话级上下文】标的 601138...",
        is_subsequent_turn=True,
    )
    assert meta["context_mode"] == "cached_context"
    assert meta["turn"] == 2
    assert meta["has_jl_envelope_in_system"] is False
    assert meta["jl13_appended"] is False


def test_build_system_for_turn_first_turn_with_envelope():
    ctx = {
        "name": "工业富联",
        "jl4_indicator_count": 12,
        "compact": {"checklist": {}, "jl4_catalog": {}},
    }
    system = _build_system_for_turn(
        symbol="601138",
        research_context=ctx,
        scan_context=None,
        has_prior_assistant=False,
    )
    assert "JL1–JL4 本地数据包" in system
    assert "工业富联" in system


def test_build_system_for_turn_subsequent_turn():
    system = _build_system_for_turn(
        symbol="601138",
        research_context=None,
        scan_context=None,
        has_prior_assistant=True,
    )
    assert "会话级上下文" in system
    assert "601138" in system
    assert "JL1–JL4 本地数据包" not in system


def test_chat_memory_roundtrip():
    sid = new_session_id()
    msgs = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
    ]
    save_messages(None, sid, msgs)
    loaded = load_messages(None, sid)
    assert len(loaded) == 2
    clear_session(None, sid)
    assert load_messages(None, sid) == []
