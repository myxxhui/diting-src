#!/usr/bin/env bash
# K8s 启动：初始化 SQLite + 从挂载 SoT 导入持仓，再拉起 uvicorn
set -euo pipefail
cd /app
export PYTHONPATH=/app

python scripts/copilot_k8s_bootstrap.py

exec uvicorn apps.copilot.main:app --host 0.0.0.0 --port "${COPILOT_PORT:-8080}"
