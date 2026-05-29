# diting-src

核心逻辑仓（重构版）。[Ref: 03_原子目标与规约/_共享规约/02_三位一体仓库规约]

> 旧版实现保留在 `diting-src`（同级目录），可供重构时参考借鉴。

## 目录结构

与 `global_const.trinity_repos.repo_i.directories` 一致：

- `diting/abstraction/` - 接口抽象层
- `diting/drivers/` - 驱动层
- `diting/moe/` - MoE 议会
- `diting/risk/` - 风控
- `diting/strategy/` - 策略层
- `tests/` - 单测
- `design/` - 设计产物（Proto、Schema、Rules）
- `config/` - 运行配置
- `scripts/` - 本地脚本

## Copilot · Linux 验证镜像（step_04 / step_08 · WeasyPrint）

与生产 **Debian/Ubuntu** 对齐；**月报 PDF / 中文 glyph 单测以容器内结果为准**（macOS 可能缺 Pango 而 skip）。

```bash
# 构建（Dockerfile 含 fonts-noto-cjk + pip install -e ".[pdf-verify]"）
make docker-copilot-build
# step_08：月报 + 熔断（10 passed，无 PDF skip）
make docker-step08-pytest
# §3.11：Redis + uvicorn 冒烟（验毕请 down）
make docker-step08-smoke-up
sleep 12 && make docker-step08-smoke-verify && make docker-step08-smoke-down
```

等价：`docker build -t diting-copilot-verify:local .` 后 `docker run --rm … python -m pytest tests/copilot/ -q`。详见 L4：[实践记录_step_08_月报与熔断.md](../diting-doc/04_阶段规划与实践/00_维度零_AI投资副驾驶/stage_1_启动期/实践记录_step_08_月报与熔断.md)。

## 快速开始

```bash
cp .env.template .env   # 填写 TIMESCALE_DSN、PG_L2_DSN 等
make test               # 运行单测
```

## 环境变量

见 `.env.template`。
