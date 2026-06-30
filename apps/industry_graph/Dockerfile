# ============================================================
# diting-src/apps/industry_graph/Dockerfile
# 产业图谱服务 — 多阶段分层构建
# 与 Dockerfile.copilot / Dockerfile.super_evo 对齐
# ============================================================

# ===================== Stage 1: 依赖层 =====================
FROM python:3.11-slim-bookworm AS deps

WORKDIR /app

# 系统依赖（Neo4j 驱动需 g++ 编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY apps/industry_graph/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ===================== Stage 2: 构建层 =====================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY apps/industry_graph/frontend/package.json \
     apps/industry_graph/frontend/package-lock.json* ./
RUN npm ci --production

COPY apps/industry_graph/frontend/ ./
RUN npm run build

# ===================== Stage 3: 运行层 =====================
FROM deps AS runtime

WORKDIR /app

# 后端代码
COPY apps/industry_graph/backend/ ./apps/industry_graph/backend/
COPY apps/common/ ./apps/common/

# 前端构建产物
COPY --from=frontend-builder /app/frontend/dist/ ./static/

# 入口脚本
COPY apps/industry_graph/backend/scripts/ ./scripts/

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=10s \
  CMD curl -f http://localhost:8090/health || exit 1

CMD ["uvicorn", "apps.industry_graph.backend.main:app", "--host", "0.0.0.0", "--port", "8090"]
