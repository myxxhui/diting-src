"""step_02 财报/公告采集：加载配置到进程环境。

加载顺序（后者不覆盖前者 —— 已在 shell / 系统中导出的变量优先）：

1. 仓库根目录 ``.env``（与 Copilot / cryo_guard 服务共用同一文件）
2. 可选 YAML：环境变量 ``CRYO_CRAWL_CONFIG`` 指向配置文件路径（相对路径相对仓库根）

在 ``training/data/scripts/crawl_*.py`` 入口最早调用 ``bootstrap_crawl_env(repo_root)``。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _set_env_default(key: str, value: str | None) -> None:
    if value is None or value == "":
        return
    if os.environ.get(key, "").strip():
        return
    os.environ[key] = value


def _resolve_path(repo_root: Path, p: str) -> str:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return str(path)


def _apply_yaml_config(path: Path, repo_root: Path) -> None:
    try:
        import yaml  # type: ignore
    except ImportError:
        return
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return

    if "symbol_list" in raw and raw["symbol_list"]:
        _set_env_default("CRYO_SYMBOL_LIST", _resolve_path(repo_root, str(raw["symbol_list"])))
    if "years" in raw and raw["years"] is not None:
        ys = raw["years"]
        if isinstance(ys, list):
            _set_env_default("CRYO_YEARS", ",".join(str(int(y)) for y in ys))
    y0, y1 = raw.get("year_start"), raw.get("year_end")
    if y0 is not None:
        _set_env_default("CRYO_YEAR_START", str(int(y0)))
    if y1 is not None:
        _set_env_default("CRYO_YEAR_END", str(int(y1)))
    if "report_types" in raw and raw["report_types"]:
        rt = raw["report_types"]
        if isinstance(rt, list):
            _set_env_default("CRYO_REPORT_TYPES", ",".join(str(x).strip().lower() for x in rt))
    if raw.get("throttle_sec") is not None:
        _set_env_default("CRYO_THROTTLE_SEC", str(float(raw["throttle_sec"])))
    if raw.get("max_symbols") is not None:
        _set_env_default("CRYO_MAX_SYMBOLS", str(int(raw["max_symbols"])))
    if raw.get("mock") is True:
        logger.warning("CRYO_CRAWL_CONFIG mock=true 已忽略（no-mock-policy）")


def bootstrap_crawl_env(repo_root: Path) -> None:
    repo_root = repo_root.resolve()
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        pass
    else:
        load_dotenv(repo_root / ".env", override=False)

    cfg = os.environ.get("CRYO_CRAWL_CONFIG", "").strip()
    if not cfg:
        return
    path = Path(cfg).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve()
    if not path.is_file():
        logger.warning("CRYO_CRAWL_CONFIG=%s 未找到可读文件，跳过 YAML", cfg)
        return
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        _apply_yaml_config(path, repo_root)
