"""DeepSea Dispatcher · doc 入库后按 cache_group 批推。

[Ref: 29_ §5.2 · §5.4 · 28_ §2.11.5]
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from apps.copilot.services.deepsea.config_loader import get_cohort_probe_keys, get_l3_probe_config
from apps.copilot.services.deepsea.context_cache import warm_context_cache
from apps.copilot.services.deepsea.contract import DeepSeaContract
from apps.copilot.services.deepsea.probe_runners import run_probe_infer

logger = logging.getLogger(__name__)


def _combined_markdown(t0: dict[str, Any]) -> str:
    parts = [
        str(t0.get("event_raw_text") or ""),
        str(t0.get("official_announcement_text") or ""),
        str(t0.get("investor_relations_qa") or ""),
        str(t0.get("interactive_e_text") or ""),
        str(t0.get("announcement_title") or ""),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return "\n".join(out)


def _filter_event_driven(symbol: str, probe_keys: list[str]) -> list[str]:
    sym = symbol.zfill(6)[-6:]
    out: list[str] = []
    for key in probe_keys:
        try:
            cfg = get_l3_probe_config(sym, key)
        except (FileNotFoundError, KeyError):
            continue
        if cfg.get("update_trigger") == "event_driven" and cfg.get("t1_pipeline") == "deepsea_semantic":
            out.append(key)
    return out


async def dispatch_cohort_inference(
    *,
    symbol: str,
    cache_group: str,
    t0_payload: dict[str, Any],
    force_probes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """同 cache_group · 一次 Cache 预热 · N 路 probe 并发推理。"""
    sym = symbol.zfill(6)[-6:]
    doc_id = str(t0_payload.get("doc_id") or f"doc_{sym}_unknown")
    text = _combined_markdown(t0_payload)
    if len(text.strip()) < 20:
        raise ValueError(f"T0 全文过短，无法批推: doc_id={doc_id}")

    probe_keys = force_probes or get_cohort_probe_keys(sym, cache_group)
    probe_keys = _filter_event_driven(sym, probe_keys)
    cache_ref = warm_context_cache(cache_group=cache_group, doc_id=doc_id, text=text)

    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(
            None,
            run_probe_infer,
            key,
            t0_payload,
            cache_ref,
            sym,
        )
        for key in probe_keys
    ]
    raw_results = await asyncio.gather(*tasks)

    batch: list[dict[str, Any]] = []
    for raw in raw_results:
        if raw.get("status") in ("skipped", "pending", "error"):
            batch.append(raw)
            continue
        contract = DeepSeaContract.from_semantic_dict(raw)
        batch.append(
            {
                "probe_key": contract.probe_key,
                "status": "ok",
                "cache_group": cache_group,
                "cache_key": cache_ref.cache_key,
                "contract": contract.to_dict(),
            }
        )
    logger.info(
        "DeepSea 批推完成 · %s · %s · probes=%d ok=%d",
        sym,
        cache_group,
        len(probe_keys),
        sum(1 for b in batch if b.get("status") == "ok"),
    )
    return batch


async def dispatch_doc_inference(
    doc_id: str,
    *,
    symbol: str,
    t0_payload: dict[str, Any],
    cache_group: str | None = None,
    force_probes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """doc 入库事件入口 · 与 29_ §5.4 伪码等价。"""
    payload = {**t0_payload, "doc_id": doc_id}
    group = cache_group or str(t0_payload.get("cache_group") or "")
    if not group:
        sym = symbol.zfill(6)[-6:]
        if force_probes:
            cfg = get_l3_probe_config(sym, force_probes[0])
            group = str(cfg.get("cache_group") or "")
        if not group:
            raise ValueError("cache_group 未指定且无法从 probe 推断")
    return await dispatch_cohort_inference(
        symbol=symbol,
        cache_group=group,
        t0_payload=payload,
        force_probes=force_probes,
    )


__all__ = ["dispatch_cohort_inference", "dispatch_doc_inference"]
