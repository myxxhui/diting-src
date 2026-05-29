"""HTML / Markdown 渲染器（Jinja2）。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from apps.copilot.services.reports.base import ReportContext

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "reports"


class ReportRenderer:
    def __init__(self, template_dir: Path = TEMPLATE_DIR) -> None:
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, kind: str, fmt: str, ctx: ReportContext) -> str:
        ext = "html" if fmt == "html" else "md.j2"
        template_name = f"{kind}_report.{ext}"
        template = self.env.get_template(template_name)
        return template.render(ctx=ctx, p=ctx.payload)
