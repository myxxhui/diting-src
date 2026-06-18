"""雷达扫描用户可见错误文案（避免 SQLAlchemy 原始堆栈直出页面）。"""
from __future__ import annotations

import re

_SQLA_BG_RE = re.compile(r"\s*\(Background on this error at: https?://sqlalche\.me[^)]*\)\s*$")


def friendly_scan_error(exc: BaseException) -> str:
    """将异常转为中文说明；技术细节写入日志，不整段展示给用户。"""
    msg = str(exc).strip()
    low = msg.lower()

    if "offset-naive and offset-aware" in msg:
        if "last_analyzed_at" in msg or "campaign_symbols" in msg:
            return (
                "扫描收尾写入「最近分析时间」失败（数据库时区字段格式）。"
                "服务已修复该写入方式，请重新点击「启动扫描」。"
            )
        if "collected_at" in msg or "radar_symbol_versions" in msg:
            return (
                "采集版本入库时时间字段格式不兼容（PostgreSQL 与 SQLite 差异）。"
                "服务已按 UTC 规范化写入，请重新点击「启动扫描」。"
            )
        return "数据库时间字段格式不兼容，请重新点击「启动扫描」。"
    if "radar_symbol_versions" in msg and "insert" in low:
        return "采集数据未能写入版本库，请重试；若仍失败请检查 PostgreSQL 连接与迁移。"
    if "opus" in low or "anthropic" in low or "budget" in low and "超限" in msg:
        if "不可达" in msg or "proxy" in low or "地域" in msg:
            return (
                "Opus 深度推理暂不可用（网络/代理限制）。"
                "可先「仅采集 T0」或使用历史缓存研报；配置 HTTPS_PROXY 后可 live 推理。"
            )
        return f"Opus 深度推理失败：{_shorten(msg, 120)}"
    if "resolve" in low or "未找到" in msg or "无法解析" in msg:
        return f"标的解析失败：{_shorten(msg, 100)}"
    if "connection" in low or "connect" in low or "timeout" in low:
        return "数据库或 Redis 连接异常，请稍后重试。"
    if "jqdata" in low or "akshare" in low:
        return f"行情数据采集失败：{_shorten(msg, 120)}"

    # 去掉 SQLAlchemy/asyncpg 冗长包装 + 尾部背景链接
    if "sqlalchemy" in low or "asyncpg" in low:
        clean = _SQLA_BG_RE.sub("", msg).strip()
        # 优先提取异常类名后面的实际错误
        m = re.search(r":\s*(.+)$", clean, re.DOTALL)
        if m:
            inner = m.group(1).strip().split("\n")[0]
            if inner and len(inner) > 5 and "sqlalchemy" not in inner.lower():
                return _shorten(inner, 180)
        # 回退：取不含 SQLA 包装的行
        lines = [l.strip() for l in clean.split("\n") if l.strip() and "sqlalchemy" not in l.lower()]
        if lines:
            return _shorten(lines[0], 180)
        return "扫描过程发生数据库错误，请重试；详情已记入服务日志。"

    return _shorten(msg, 200) if msg else "扫描失败，请重试。"


def _shorten(text: str, max_len: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
