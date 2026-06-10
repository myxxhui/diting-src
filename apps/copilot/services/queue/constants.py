"""ARQ 队列命名契约。

[Ref: 29_ §4.1]
"""
from __future__ import annotations

QUEUE_INTERACTIVE = "copilot:q:interactive"
QUEUE_CRAWL = "copilot:q:crawl"
QUEUE_PERSIST = "copilot:q:persist"
QUEUE_SEARCH_INDEX = "copilot:q:search_index"

# ARQ Worker 默认队列名（单 Worker 消费全部函数）
ARQ_DEFAULT_QUEUE = "arq:queue"
