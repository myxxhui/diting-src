#!/usr/bin/env python3
"""本机预拉雷达 T0 缓存（持仓 SoT active 标的）；可选 --with-t2 含 Opus 9 维研报。

A 路径（推荐）：
  make radar-t0-prefetch-with-t2   # Mac 上 T0→T1→Opus T2 → bundle JSON
  cd ../diting-infra && make radar-t0-sync

B 路径：生产 pod 经 HTTPS_PROXY live 调 Opus（缓存 miss 时）

[Ref: step_14 §3.5 · 持仓 SoT · 21_行情数据源]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

T0_KEYS = ("quote", "profile", "financials", "valuation")


async def _prefetch_one(symbol: str, name: str, *, with_t2: bool) -> dict:
    from apps.copilot.modules.radar.context_matrix import build_context_matrix
    from apps.copilot.modules.radar.pipeline import run_t2_live
    from apps.copilot.modules.radar.scanner import collect_t0_live
    from apps.copilot.modules.radar.t0_cache import save_cache

    t0 = await collect_t0_live(symbol, name=name)
    bundle: dict = {**t0, "source": "prefetch_with_t2" if with_t2 else "prefetch"}

    ok = sum(1 for k in T0_KEYS if (t0.get(k) or {}).get("status") == "ok")
    t2_status = None
    t2_dims = 0
    t2_cost = None

    if with_t2:
        t1 = build_context_matrix(t0)
        bundle["t1_distilled"] = t1
        t2 = await run_t2_live(t1, t0)
        bundle["t2_verdict"] = t2
        t2_status = t2.get("status")
        t2_dims = len((t2.get("deep_analysis") or {}).get("dimensions") or {})
        t2_cost = t2.get("cost_yuan")
        if t2_status != "ok":
            print(
                f"  ⚠️  {symbol} T2 {t2_status}: {(t2.get('detail') or '')[:120]}"
            )

    path = save_cache(bundle)
    suffix = ""
    if with_t2:
        suffix = f" | T2 {t2_status} {t2_dims}/9 维"
        if t2_cost is not None:
            suffix += f" ¥{t2_cost:.4f}"
    print(f"  ✅ {symbol} {t0.get('name')} | T0 {ok}/4 绿{suffix} | → {path}")
    return {
        "symbol": symbol,
        "name": t0.get("name"),
        "collected_at": t0.get("collected_at"),
        "ok_parts": ok,
        "t2_status": t2_status,
        "t2_dims": t2_dims,
        "path": str(path),
    }


async def _run(symbols: list[tuple[str, str]], throttle: float, *, with_t2: bool) -> int:
    from apps.copilot.modules.radar.model_router import radar_t2_enabled
    from apps.copilot.modules.radar.t0_cache import cache_dir, write_manifest

    if with_t2 and not radar_t2_enabled():
        print("❌ --with-t2 需要 RADAR_T2_ENABLED=true 且 ANTHROPIC_API_KEY", file=sys.stderr)
        return 2

    mode = "T0+T1+T2" if with_t2 else "T0"
    print(f"▶ [radar-t0-prefetch] mode={mode} cache_dir={cache_dir().resolve()} 标的数={len(symbols)}")
    entries = []
    fail = 0
    for i, (sym, name) in enumerate(symbols):
        if i > 0 and throttle > 0:
            time.sleep(throttle)
        try:
            entry = await _prefetch_one(sym, name, with_t2=with_t2)
            entries.append(entry)
            if entry["ok_parts"] < 2:
                fail += 1
                print(f"  ⚠️  {sym} T0 仅 {entry['ok_parts']}/4 绿（准出建议 ≥2）")
            if with_t2 and entry.get("t2_status") != "ok":
                fail += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  ❌ {sym} 预拉失败: {exc}")
            entries.append({"symbol": sym, "name": name, "ok_parts": 0, "error": str(exc)[:200]})
    manifest = write_manifest(entries)
    print(f"▶ manifest → {manifest}")
    print(f"▶ 完成：{len(symbols)} 只，不足准出或异常 {fail} 只")
    return 1 if fail else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="预拉雷达 T0 缓存（持仓 SoT）")
    parser.add_argument("--symbol", action="append", help="仅拉指定 6 位代码（可重复）")
    parser.add_argument("--portfolio-only", action="store_true", help="仅 portfolio 真实持仓")
    parser.add_argument(
        "--with-t2",
        action="store_true",
        help="本机 Opus T2 9 维研报写入 bundle（A 路径；需 Mac 可访问 Anthropic）",
    )
    args = parser.parse_args()

    from apps.common.holdings_sot import load_holdings_sot

    sot = load_holdings_sot()
    if args.symbol:
        pairs: list[tuple[str, str]] = []
        for s in args.symbol:
            sym = s.zfill(6)[-6:]
            ent = sot.by_symbol(sym)
            pairs.append((sym, ent.name if ent else sym))
    elif args.portfolio_only:
        pairs = [
            (h.symbol, h.name)
            for h in sot.holdings
            if h.active and h.role == "portfolio"
        ]
    else:
        pairs = [(h.symbol, h.name) for h in sot.holdings if h.active]

    if not pairs:
        print("❌ 无 active 标的（检查 my_holdings.yaml）", file=sys.stderr)
        return 2

    return asyncio.run(_run(pairs, sot.throttle_sec, with_t2=args.with_t2))


if __name__ == "__main__":
    raise SystemExit(main())
