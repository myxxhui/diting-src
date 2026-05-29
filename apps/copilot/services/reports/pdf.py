"""WeasyPrint PDF 渲染器。中文字体 Noto Sans CJK SC。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
[DNA: _System_DNA/00_co_pilot/dna_stage_1_启动期.yaml#tech_stack.pdf]
"""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from apps.copilot.services.reports.base import ReportContext

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "reports"


class WeasyPDFRenderer:
    def __init__(self, template_dir: Path | None = None) -> None:
        td = template_dir or TEMPLATE_DIR
        self._template_dir = td
        self.env = Environment(
            loader=FileSystemLoader(str(td)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._css_path = td / "monthly_report.css"

    def render(self, ctx: ReportContext, out_path: Path) -> Path:
        from weasyprint import CSS, HTML

        template = self.env.get_template("monthly_report.html")
        html = template.render(ctx=ctx, p=ctx.payload, octants_chart=self._octants_chart(ctx))
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheets = [CSS(filename=str(self._css_path))] if self._css_path.exists() else []
        HTML(string=html, base_url=str(self._template_dir)).write_pdf(
            target=str(out_path),
            stylesheets=sheets,
        )
        log.info(
            "monthly pdf generated: %s (%d bytes)",
            out_path,
            out_path.stat().st_size,
        )
        return out_path

    def _octants_chart(self, ctx: ReportContext) -> str:
        counts = ctx.payload["octants"]["counts"]
        max_val = max((v["count"] for v in counts.values()), default=1) or 1
        bars = []
        x = 20
        for label in "ABCDEFGH":
            v = counts[label]
            h = int(180 * (v["count"] / max_val))
            color = "#16a34a" if v["pnl"] >= 0 else "#dc2626"
            bars.append(
                f'<rect x="{x}" y="{200 - h}" width="36" height="{h}" fill="{color}"/>'
                f'<text x="{x + 18}" y="220" font-size="12" text-anchor="middle">{label}</text>'
                f'<text x="{x + 18}" y="{195 - h}" font-size="10" text-anchor="middle">{v["count"]}</text>'
            )
            x += 50
        return f'<svg width="440" height="240" xmlns="http://www.w3.org/2000/svg">{"".join(bars)}</svg>'
