"""WeasyPrint Thesis 卡 PDF 渲染。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "recommendation"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_thesis_pdf(thesis: dict) -> bytes:
    """运行时再加载 WeasyPrint，避免无系统库环境下 import 即失败。

    [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
    """
    from weasyprint import HTML

    template = _env.get_template("_pdf.html")
    html_content = template.render(thesis=thesis)
    return HTML(string=html_content).write_pdf()
