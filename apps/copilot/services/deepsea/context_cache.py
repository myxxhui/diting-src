"""DeepSea Context Cache 预热 · 同 cache_group 全文只写一次。

[Ref: 29_ §5.2 · §5.4 Dispatcher 批推]
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# 进程内 LRU · 生产可换 Redis `deepsea:ctx:{cache_group}:{doc_id}`
_CACHE: dict[str, "ContextCacheRef"] = {}
_MAX_ENTRIES = 32


@dataclass(frozen=True)
class ContextCacheRef:
    cache_group: str
    doc_id: str
    text: str
    cache_key: str
    warmed_at: str
    char_count: int

    def as_metadata(self) -> dict[str, Any]:
        return {
            "cache_group": self.cache_group,
            "doc_id": self.doc_id,
            "cache_key": self.cache_key,
            "warmed_at": self.warmed_at,
            "char_count": self.char_count,
        }


def _cache_key(cache_group: str, doc_id: str, text: str) -> str:
    digest = hashlib.sha256(f"{cache_group}:{doc_id}:{text[:8192]}".encode()).hexdigest()[:24]
    return f"deepsea:{cache_group}:{doc_id}:{digest}"


def warm_context_cache(
    *,
    cache_group: str,
    doc_id: str,
    text: str,
) -> ContextCacheRef:
    """将全文写入 Context Cache 池，返回可被多 probe 共享的 cache_ref。"""
    key = _cache_key(cache_group, doc_id, text)
    existing = _CACHE.get(key)
    if existing is not None:
        logger.info("DeepSea Cache Hit · %s · %s chars", key, existing.char_count)
        return existing

    ref = ContextCacheRef(
        cache_group=cache_group,
        doc_id=doc_id,
        text=text,
        cache_key=key,
        warmed_at=datetime.now(_CST).isoformat(),
        char_count=len(text),
    )
    if len(_CACHE) >= _MAX_ENTRIES:
        oldest = next(iter(_CACHE))
        _CACHE.pop(oldest, None)
    _CACHE[key] = ref
    logger.info("DeepSea Cache Warm · %s · %s chars", key, ref.char_count)
    return ref


def inject_cache_ref(t0: dict[str, Any], ref: ContextCacheRef) -> dict[str, Any]:
    """为 T0 payload 注入批推元数据（runner 可读 `_deepsea`）。"""
    out = dict(t0)
    out["_deepsea"] = ref.as_metadata()
    return out


def clear_context_cache_for_tests() -> None:
    _CACHE.clear()


__all__ = [
    "ContextCacheRef",
    "clear_context_cache_for_tests",
    "inject_cache_ref",
    "warm_context_cache",
]
