"""一键创建 5 套 Label Studio 项目（幂等）。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03_C2_Label_Studio部署.md]

用法: PYTHONPATH=. python3 scripts/labeling/init_projects.py
"""
from __future__ import annotations

import logging
import sys

from apps.super_evo.labeling.client import LabelStudioClient, load_template
from apps.super_evo.labeling.importer import PROJECT_TITLE_BY_TASK

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    client = LabelStudioClient()
    try:
        health = client.health()
        if not health.get("ok"):
            logger.error("Label Studio not healthy: %s", health)
            return 1

        summary = []
        for task_type, title in PROJECT_TITLE_BY_TASK.items():
            config = load_template(task_type)
            project = client.create_project(title=title, label_config=config)
            summary.append((task_type, project.get("id"), title))
            logger.info("project ok task=%s id=%s title=%s", task_type, project.get("id"), title)

        print("=== created/reused projects ===")
        for task_type, pid, title in summary:
            print(f"  {task_type:18s} id={pid}  {title}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
