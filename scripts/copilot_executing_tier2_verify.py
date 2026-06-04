#!/usr/bin/env python3
"""28_ 执行中工作区 · K3s 生产 tier-2 HTTP 验收（须在镜像部署后执行）。

验收项：路由存在 · 持仓 API · 同步状态 · HTMX 三层详情 · 规划页执行区入口。
不宣称 25/25 探针全绿（见 executing-pipeline-status / §9 阻塞报告）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _load_prod_conn() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    for conn in (root.parent / "diting-infra" / "prod.conn", root / "diting-infra" / "prod.conn"):
        if conn.is_file():
            out: dict[str, str] = {}
            for line in conn.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
            return out
    return {}


def _get(url: str, timeout: float = 60.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    conn = _load_prod_conn()
    ip = os.environ.get("PUBLIC_IP") or conn.get("PUBLIC_IP", "127.0.0.1")
    port = os.environ.get("COPILOT_NODE_PORT", "30080")
    base = f"http://{ip}:{port}"
    symbol = os.environ.get("EXECUTING_SYMBOL", "601138").strip().zfill(6)[-6:]
    failures: list[str] = []

    print(f"▶ [copilot-executing-tier2-verify] base={base} symbol={symbol}")

    code, body = _get(f"{base}/api/executing/positions")
    if code != 200:
        failures.append(f"GET /api/executing/positions → {code}")
    else:
        try:
            positions = json.loads(body)
        except json.JSONDecodeError:
            failures.append("positions 非 JSON")
            positions = []
        if not isinstance(positions, list):
            failures.append("positions 响应非数组")
        elif not any(str(p.get("symbol", "")).zfill(6).endswith(symbol) for p in positions):
            failures.append(f"positions 未含 {symbol}（可先 helm holdingsYaml 或集群内 executing-import-positions）")

    code, body = _get(f"{base}/api/executing/sync-status")
    if code != 200:
        failures.append(f"GET /api/executing/sync-status → {code}")
    else:
        try:
            sync = json.loads(body)
        except json.JSONDecodeError:
            failures.append("sync-status 非 JSON")
            sync = {}
        for key in ("stale_count", "missing_count", "probes"):
            if key not in sync:
                failures.append(f"sync-status 缺字段 {key}")

    code, body = _get(f"{base}/planning?view=executing")
    if code != 200:
        failures.append(f"GET /planning?view=executing → {code}")
    elif "executing" not in body.lower() and "执行" not in body:
        failures.append("planning 执行区页面无执行中入口文案")

    code, body = _get(f"{base}/api/executing/{symbol}/detail")
    if code != 200:
        failures.append(f"GET /api/executing/{symbol}/detail → {code}")
    else:
        for needle in ("executing-workspace", "层 A", "层 B", "层 C", "no-auto-execute"):
            if needle not in body:
                failures.append(f"detail 缺片段: {needle}")

    code, body = _get(f"{base}/openapi.json", timeout=30.0)
    if code == 200 and "/api/executing/positions" not in body:
        failures.append("openapi 未注册 executing 路由（镜像可能过旧）")

    if failures:
        print("❌ 执行中工作区 tier-2 生产验收失败:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✅ 执行中工作区 tier-2 HTTP 验收通过（不含 25/25 数据准出）")
    print("ℹ️  数据准出请 Pod 内: python -m apps.copilot.jobs.executing_t0 --status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
