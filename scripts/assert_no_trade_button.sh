#!/usr/bin/env bash
# 扫描 copilot 模板/路由中禁止出现的自动下单关键字
# [Ref: 03_/00_维度零/.../step_02 §7.2]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${ROOT}/apps/copilot"
PATTERN='place_order|submit_order|broker_api|buy_now|sell_now|下单'

if rg -i "$PATTERN" "$TARGET" 2>/dev/null; then
  echo "❌ no-trade 检查失败：发现禁止关键字"
  exit 1
fi
echo "✅ no-trade 检查通过（apps/copilot 无自动下单关键字）"
