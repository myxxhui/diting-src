"""T2 用户问题与 JL1-3 模板合并单测。"""
from __future__ import annotations

from apps.copilot.modules.executing.t2_analyst import (
    DEFAULT_JL13_DATA_TEMPLATE,
    compose_user_question,
)


def test_compose_with_jl13_default():
    q = compose_user_question("组合审计", include_jl13=True)
    assert "组合审计" in q
    assert "JL1–JL3" in q
    assert DEFAULT_JL13_DATA_TEMPLATE.split("\n")[0] in q


def test_compose_without_jl13():
    q = compose_user_question("仅审计", include_jl13=False)
    assert q == "仅审计"
    assert "JL1–JL3" not in q


def test_compose_custom_jl13():
    custom = "【自定义】每层 5 个指标"
    q = compose_user_question("审计", jl13_data_prompt=custom, include_jl13=True)
    assert custom in q
