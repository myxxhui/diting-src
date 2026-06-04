"""雷达 Opus 对话会话存储。"""
from __future__ import annotations

from apps.copilot.modules.radar.chat import (
    clear_session,
    load_messages,
    new_session_id,
    save_messages,
)


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
