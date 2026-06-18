"""产品工作区注册表 · 工程区码 Z0～Z4 与用户可见命名。

[Ref: diting-doc/03_/_共享规约/32_五区漏斗工作流与数据工程标准化规约.md §1.4]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WorkspaceMeta:
    workspace_id: str
    zone_code: str
    view_key: str
    tab_icon: str
    tab_label: str
    display_name: str
    tagline: str
    funnel_order: Optional[int] = None  # None = 横切（Z4）


WORKSPACES: tuple[WorkspaceMeta, ...] = (
    WorkspaceMeta(
        workspace_id="strategic_wind",
        zone_code="Z0",
        view_key="roadmap",
        tab_icon="🧭",
        tab_label="产业风向",
        display_name="产业风向台",
        tagline="先看风往哪吹，再决定打哪一场",
        funnel_order=1,
    ),
    WorkspaceMeta(
        workspace_id="opportunity_radar",
        zone_code="Z1",
        view_key="radar",
        tab_icon="🔭",
        tab_label="机会雷达",
        display_name="机会雷达",
        tagline="广撒网找值得深究的候选",
        funnel_order=2,
    ),
    WorkspaceMeta(
        workspace_id="thesis_lab",
        zone_code="Z2",
        view_key="planning",
        tab_icon="📝",
        tab_label="买入论证",
        display_name="买入论证台",
        tagline="把信念写成可证伪的买入合同",
        funnel_order=3,
    ),
    WorkspaceMeta(
        workspace_id="position_guard",
        zone_code="Z3",
        view_key="executing",
        tab_icon="🛡️",
        tab_label="持仓监护",
        display_name="持仓监护室",
        tagline="论文在手才持仓，前提死了就动",
        funnel_order=4,
    ),
    WorkspaceMeta(
        workspace_id="decision_ledger",
        zone_code="Z4",
        view_key="ledger",
        tab_icon="📊",
        tab_label="决策复盘",
        display_name="决策复盘库",
        tagline="验过去对错，校系统规则",
        funnel_order=None,
    ),
)

_BY_VIEW: dict[str, WorkspaceMeta] = {w.view_key: w for w in WORKSPACES}

WORKBENCH_TAB_VIEWS: tuple[str, ...] = tuple(w.view_key for w in WORKSPACES)

FUNNEL_WORKSPACES: tuple[WorkspaceMeta, ...] = tuple(
    w for w in WORKSPACES if w.funnel_order is not None
)

ALLOWED_WORKBENCH_VIEWS: frozenset[str] = frozenset(WORKBENCH_TAB_VIEWS)


DEFAULT_WORKBENCH_VIEW = "roadmap"


def get_workspace(view: str) -> WorkspaceMeta:
    key = (view or DEFAULT_WORKBENCH_VIEW).strip()
    return _BY_VIEW.get(key, _BY_VIEW[DEFAULT_WORKBENCH_VIEW])


def workspace_display_name(view: str) -> str:
    return get_workspace(view).display_name


def workspace_tab_label(view: str) -> str:
    return get_workspace(view).tab_label


def workspace_list_label(view: str) -> str:
    """标的列表区标题用完整产品名。"""
    return workspace_display_name(view)


def workbench_tab_items() -> list[tuple[str, str, str, str, str, str]]:
    """(view_key, icon, tab_label, display_name, tagline, zone_code)"""
    return [
        (w.view_key, w.tab_icon, w.tab_label, w.display_name, w.tagline, w.zone_code)
        for w in WORKSPACES
    ]


def funnel_progress_items() -> list[tuple[str, str, str]]:
    """(view_key, icon, tab_label) · 主漏斗四步。"""
    ordered = sorted(FUNNEL_WORKSPACES, key=lambda w: w.funnel_order or 0)
    return [(w.view_key, w.tab_icon, w.tab_label) for w in ordered]
