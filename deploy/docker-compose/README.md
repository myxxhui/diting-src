# docker-compose（本地）

## super-evo-stack（Teacher / 蒸馏 API + 依赖）

**对应节奏**：W1/W2 **D5·super_evo**（M1 蒸馏）；与根目录 **`Dockerfile.super_evo`** 配套。

```bash
cd /path/to/diting-src/deploy/docker-compose

# 可选：真蒸馏时注入 Key（否则 API 为 dry_run）
export ANTHROPIC_API_KEY=sk-ant-...

docker compose -f super-evo-stack.yml up --build
```

- **API**：`http://127.0.0.1:8090` · 健康/模式：`curl -s http://127.0.0.1:8090/api/distill/health`
- **MinIO 控制台**：`http://127.0.0.1:9001`（默认账号见 compose 或 `.env`）
- **仅依赖**（不含 API）：`docker compose -f super-evo-infra.yml up -d`

## 与根目录 `Dockerfile` 的区别

| 文件 | 用途 |
|------|------|
| `Dockerfile` | **Copilot（D0）** · WeasyPrint / copilot pytest |
| `Dockerfile.super_evo` | **super-evo（D5）** · `uvicorn apps.super_evo.main:app` |

上架 ECS/K3s 仍以 **diting-infra + deploy-engine** 与 L3 **`### [Deploy]`** 为准；本 compose 为**本地/联调容器**路径。
