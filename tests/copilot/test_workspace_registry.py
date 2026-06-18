"""产品工作区注册表 pytest · [Ref: 32_ §1.4]"""
from __future__ import annotations

from apps.copilot.modules.planning.workspace_registry import (
    ALLOWED_WORKBENCH_VIEWS,
    WORKBENCH_TAB_VIEWS,
    funnel_progress_items,
    get_workspace,
    workbench_tab_items,
)


def test_workbench_tab_order_follows_funnel():
    assert WORKBENCH_TAB_VIEWS == (
        "roadmap",
        "radar",
        "planning",
        "executing",
        "ledger",
    )


def test_funnel_progress_excludes_ledger():
    keys = [k for k, _, _ in funnel_progress_items()]
    assert keys == ["roadmap", "radar", "planning", "executing"]
    assert "ledger" not in keys


def test_workspace_labels():
    assert get_workspace("radar").tab_label == "机会雷达"
    assert get_workspace("roadmap").display_name == "产业风向台"
    assert get_workspace("planning").tab_label == "买入论证"
    assert get_workspace("executing").display_name == "持仓监护室"
    assert get_workspace("ledger").zone_code == "Z4"


def test_allowed_views():
    assert "ledger" in ALLOWED_WORKBENCH_VIEWS
    assert len(workbench_tab_items()) == 5
