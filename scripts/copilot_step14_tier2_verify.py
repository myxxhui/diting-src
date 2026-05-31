#!/usr/bin/env python3
"""step_14 tier-2：K3s 生产 Copilot 雷达三段流水线验收。

在 step_12 tier-2 基础上增加 ⑦ 雷达扫描 + artifact + promote。
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
    conn = root.parent / "diting-infra" / "prod.conn"
    if not conn.is_file():
        conn = root / "diting-infra" / "prod.conn"
    out: dict[str, str] = {}
    if conn.is_file():
        for line in conn.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _get(url: str, timeout: float = 30.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _post_form(url: str, data: dict[str, str], timeout: float = 120.0) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    # 先跑 step_12 基线
    from scripts.copilot_step12_tier2_verify import main as step12_main

    if step12_main() != 0:
        print("❌ step_12 基线未通过，跳过 step_14 增量验收")
        return 1

    conn = _load_prod_conn()
    ip = os.environ.get("PUBLIC_IP") or conn.get("PUBLIC_IP", "127.0.0.1")
    port = os.environ.get("COPILOT_NODE_PORT", "30080")
    base = f"http://{ip}:{port}"
    symbol = os.environ.get("RADAR_SYMBOL", "601138").strip().zfill(6)[-6:]
    failures: list[str] = []

    print(f"▶ [copilot-step14-tier2-verify] base={base} symbol={symbol}")

    code, body = _post_form(
        f"{base}/api/radar/scans",
        {"input_type": "symbol", "query_text": symbol},
        timeout=180.0,
    )
    if code not in (200, 201):
        failures.append(f"POST /api/radar/scans → {code}: {body[:300]}")
    else:
        try:
            scan = json.loads(body)
        except json.JSONDecodeError:
            failures.append("POST /api/radar/scans 非 JSON（可能为 HTML hx 响应，请用 Accept: json）")
            scan = {}
        if scan.get("status") != "done":
            failures.append(f"scan status={scan.get('status')}")
        cands = scan.get("candidates") or []
        if not cands:
            failures.append("scan 无 candidates")
        else:
            cid = cands[0]["id"]
            code_a, body_a = _get(f"{base}/api/radar/candidates/{cid}/artifacts")
            if code_a != 200:
                failures.append(f"GET artifacts → {code_a}")
            else:
                arts = json.loads(body_a)
                stages = {a["stage"] for a in arts}
                if not stages >= {"T0_raw", "T1_distilled", "T2_verdict"}:
                    failures.append(f"三段 artifact 不齐: {stages}")
            code_p, body_p = _post_form(
                f"{base}/api/radar/candidates/{cid}/promote",
                {"new_theme": f"云验收雷达晋级·{symbol}"},
            )
            if code_p not in (200, 201):
                failures.append(f"POST promote → {code_p}: {body_p[:200]}")
            else:
                promo = json.loads(body_p)
                if not promo.get("campaign_id") or not promo.get("analysis_snapshot"):
                    failures.append("promote 缺 campaign_id 或 analysis_snapshot")

    if failures:
        print("❌ step_14 tier-2 生产验收失败:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✅ step_14 tier-2 生产验收通过（⑦ 雷达 + 三段 artifact + promote）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
