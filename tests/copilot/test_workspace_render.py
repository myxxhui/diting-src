"""规划/执行工作区卡片渲染 pytest。"""
from __future__ import annotations

from apps.copilot.modules.planning.workspace_render import (
    render_executing_symbol_card,
    render_planning_symbol_card,
    render_workspace_symbol_list,
    render_workspace_tag_oob,
)


def _chip(_tag, *, symbol, editable=False):
    edit = (
        f"<button data-edit='{symbol}'>改</button>" if editable else ""
    )
    return f"<span data-chip='{symbol}'>{edit}</span>"


def _t2_banner(sym, advice, *, embedded=False):
    return f"<div data-t2='{sym}' embedded={embedded}></div>"


def test_planning_card_modal_strategic_section():
    html = render_planning_symbol_card(
        {"symbol": "601138", "name": "工业富联", "market_phase": "expectation"},
        container_id=1,
        tags_map={},
        render_strategic_chip=_chip,
    )
    assert "planning-symbol-card" in html
    assert "① 战略归属" in html
    assert "设置战略归属" in html
    assert "/api/strategic/tags/edit?symbol=601138" in html
    assert "workspace-tag-hint-601138" in html
    assert "② 晋级执行" in html
    assert "board_id" not in html  # 无内联下拉
    assert "hx-trigger='revealed once'" in html


def test_executing_card_modal_strategic_section():
    html = render_executing_symbol_card(
        {
            "symbol": "601138",
            "name": "工业富联",
            "position_pct": 10.5,
            "quantity": 100,
            "cost_price": 50,
        },
        container_id=1,
        t2_summaries={},
        tags_map={},
        render_strategic_chip=_chip,
        render_executing_t2_banner=_t2_banner,
    )
    assert "executing-symbol-card" in html
    assert "executing-t2-panel" in html
    assert "data-detail-url='/api/executing/601138/detail'" in html
    assert "① 战略归属" in html
    assert "设置战略归属" in html
    assert "workspace-tag-601138" in html
    assert "T2 · 待分析" in html
    assert "战略上下文" not in html


def test_workspace_tag_oob_fragments():
    html = render_workspace_tag_oob("601138", {"board_name": "AI", "phase_name": "算力"})
    assert "hx-swap-oob='true'" in html
    assert "workspace-tag-601138" in html
    assert "workspace-tag-hint-601138" in html


def test_workspace_list_header():
    html = render_workspace_symbol_list(["<div>x</div>"], view="executing", count=3)
    assert "执行中 · 3 只标的" in html
