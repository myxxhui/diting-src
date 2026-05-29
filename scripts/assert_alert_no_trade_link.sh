#!/usr/bin/env bash
# 告警文案禁止含下单链接
# [Ref: 03_/00_维度零/.../step_05 §7.2 copilot-step05-notrade-check]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PATTERN='立即买入|立即卖出|broker\.|qmt|下单链接'
if rg -n -i "$PATTERN" apps/copilot/services/alerts/ apps/copilot/templates/alerts/ 2>/dev/null; then
  echo "❌ 告警文案含禁止词"
  exit 1
fi
echo "✅ 告警 no-trade-link 检查通过"
