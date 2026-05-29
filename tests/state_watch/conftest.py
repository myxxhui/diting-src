"""state_watch 测试配置.

行情 K 线集成测试默认走规约 21 MarketQuote（腾讯 fqkline 优先），不再全局 stub 跳过腾讯路径。
纯函数单测使用本地构造 Bar，不依赖外网。

若需离线强制空行情（仅调试）：``STATE_WATCH_QUOTE_AKSHARE_FALLBACK=0`` 且 mock ``fetch_bars_60d``。
"""
from __future__ import annotations
