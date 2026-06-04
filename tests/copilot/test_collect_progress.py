"""T0 采集进度状态与面板渲染。"""
from apps.copilot.modules.radar.collect_progress import (
    finish_job,
    init_job,
    load,
    new_job_id,
    update_job,
)
from apps.copilot.routers.planning_routes import _render_collect_progress_panel


def test_steps_done_only_after_step_transition():
    job_id = new_job_id()
    init_job(None, job_id, symbol="300394", name="天孚通信")
    update_job(None, job_id, step="quote", step_label="行情", pct=28)
    state = load(None, job_id)
    assert state["step"] == "quote"
    assert "quote" not in state["steps_done"]
    assert "resolve" in state["steps_done"]

    update_job(None, job_id, step="profile", step_label="公司资料", pct=45)
    state = load(None, job_id)
    assert "quote" in state["steps_done"]
    assert "profile" not in state["steps_done"]


def test_render_panel_running_and_done():
    job_id = new_job_id()
    init_job(None, job_id, symbol="300394", name="测试")
    update_job(None, job_id, step="financials", step_label="财务", pct=62)
    html = _render_collect_progress_panel(load(None, job_id))
    assert "hx-get" in html
    assert "financials" not in html or "⏳" in html or "财务" in html
    assert "62%" in html

    finish_job(None, job_id, {"version_id": "v1", "t0_ok_parts": 4, "status": "ok"})
    done_html = _render_collect_progress_panel(load(None, job_id))
    assert "data-done" in done_html
    assert "hx-get" not in done_html
    assert "采集完成" in done_html
