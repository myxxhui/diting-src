"""P6 海关月度数据探针.

数据源主路：AKShare macro_china_exports_yoy（中国月度出口同比，总量宏观代理）
数据源备路：AKShare macro_china_imports_yoy
降级：双源失败 → status='data_unavailable'，不告警不阻塞

启动期说明：
  - 尚未建立 HS Code → 标的行业映射表（industry_hs_code.yaml 占位）
  - 以宏观出口同比作为全行业代理信号（启动期降级路径，L3 §PC1 覆盖率 70% 注释）
  - 扩展期接入 per-HS-Code 月度数据

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03 §3.5.4.2]
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from apps.state_watch.probes.base_probe import BaseProbe, ProbeError

logger = logging.getLogger(__name__)


_AKSHARE_CALL_TIMEOUT = 8.0  # 单次 AKShare 调用超时（秒）；双源串行最多 16s


def _akshare_exports_yoy() -> float | None:
    """调用 AKShare 获取最新月度出口同比（%）。同步函数，在 executor 中运行。

    设置 socket 默认超时，确保线程在超时后快速退出（防止线程池 drain 等待）。
    """
    import socket as _socket
    _socket.setdefaulttimeout(_AKSHARE_CALL_TIMEOUT)
    try:
        import akshare as ak  # type: ignore[import]
        df = ak.macro_china_exports_yoy()
        if df is None or df.empty:
            return None
        # 列名：月份 / 今值 / 预期值 / 前值
        val_col = [c for c in df.columns if "今" in str(c) or "value" in str(c).lower()]
        if val_col:
            last_val = df[val_col[0]].dropna().iloc[-1]
        else:
            last_val = df.iloc[-1, 1]
        return float(str(last_val).replace("%", "").strip())
    except Exception as exc:
        logger.warning("AKShare macro_china_exports_yoy 失败: %s", exc)
        return None
    finally:
        _socket.setdefaulttimeout(None)  # 恢复默认，避免影响其他代码


def _akshare_imports_yoy() -> float | None:
    """调用 AKShare 获取最新月度进口同比（%）。"""
    import socket as _socket
    _socket.setdefaulttimeout(_AKSHARE_CALL_TIMEOUT)
    try:
        import akshare as ak  # type: ignore[import]
        df = ak.macro_china_imports_yoy()
        if df is None or df.empty:
            return None
        val_col = [c for c in df.columns if "今" in str(c) or "value" in str(c).lower()]
        if val_col:
            last_val = df[val_col[0]].dropna().iloc[-1]
        else:
            last_val = df.iloc[-1, 1]
        return float(str(last_val).replace("%", "").strip())
    except Exception as exc:
        logger.warning("AKShare macro_china_imports_yoy 失败: %s", exc)
        return None
    finally:
        _socket.setdefaulttimeout(None)


def _signal_from_yoy(exports_yoy: float | None, imports_yoy: float | None) -> str:
    """三色信号（L3 §PC2/PC3）。

    green: 出口 yoy > 5%
    yellow: -5% ~ 5%
    red: < -5%
    双源都 None → data_unavailable（由调用方处理）
    """
    primary = exports_yoy if exports_yoy is not None else imports_yoy
    if primary is None:
        return "unknown"
    if primary > 5.0:
        return "green"
    if primary < -5.0:
        return "red"
    return "yellow"


class CustomsProbe(BaseProbe):
    """P6 海关月度数据探针（月度节奏，启动期：AKShare 宏观代理）。

    超时策略：每次 AKShare 调用独立设 _AKSHARE_CALL_TIMEOUT 上限；
    双源串行最多 16s；无重试（retry_max=0），AKShare 不稳定时直接 data_unavailable。

    [Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03 §7.1 I]
    """

    probe_type = "P6_customs"
    timeout_seconds = 20.0  # 外层安全兜底（双源 16s + 2s 余量）
    retry_max = 0  # AKShare 不稳定，重试无益，直接 data_unavailable

    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        loop = asyncio.get_event_loop()

        async def _run_with_timeout(fn) -> float | None:
            """在 executor 中运行同步 fn，超时后返回 None 而非挂住。"""
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(None, fn),
                    timeout=_AKSHARE_CALL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("AKShare call timeout (%.0fs): %s", _AKSHARE_CALL_TIMEOUT, fn.__name__)
                return None

        # 主源
        exports_yoy: float | None = await _run_with_timeout(_akshare_exports_yoy)
        # 备源
        imports_yoy: float | None = await _run_with_timeout(_akshare_imports_yoy)

        if exports_yoy is None and imports_yoy is None:
            logger.warning("P6 symbol=%s 双源失败，标注 data_unavailable", symbol)
            return {
                "probe_id": "P6",
                "symbol": symbol,
                "status": "data_unavailable",
                "physical_signal": "unknown",
                "note": "AKShare 双源失败；扩展期接入 per-HS-Code 数据",
            }

        signal = _signal_from_yoy(exports_yoy, imports_yoy)
        return {
            "probe_id": "P6",
            "symbol": symbol,
            "status": "ok",
            "physical_signal": signal,
            "customs_export_yoy_pct": exports_yoy,
            "customs_import_yoy_pct": imports_yoy,
            "data_scope": "macro_china_total（启动期降级，扩展期接 per-HS-Code）",
            "note": (
                "启动期未建 HS Code 映射，以宏观总量出口 YoY 为代理信号 [L3 §PC1 降级路径]"
            ),
        }
