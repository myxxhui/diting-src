#!/usr/bin/env python3
"""radar-pipeline-status CLI。

[Ref: 27_ §5.2]
"""
from __future__ import annotations

import asyncio
import json
import sys

from apps.copilot.jobs.radar_t0.__main__ import main as job_main


if __name__ == "__main__":
    raise SystemExit(job_main(["--status"] + sys.argv[1:]))
