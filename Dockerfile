# Copilot 验证/运行镜像（Linux + WeasyPrint + Noto CJK，与 K8s/CI / step_08 对齐）
# [Ref: 03_/00_维度零/steps/step_04]
# [Ref: 03_/00_维度零/steps/step_08 · §3.2 容器内 pytest / pdfminer 中文断言]
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    COPILOT_ALERT_CONSUMER_ENABLED=false \
    COPILOT_LEDGER_SCHEDULER_ENABLED=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libcairo2 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/data

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY tests ./tests
COPY scripts ./scripts

RUN pip install --upgrade pip setuptools wheel \
    && pip install -e ".[pdf-verify]"

# 默认：全量 copilot 单测（镜像内 WeasyPrint 应有 Pango/Cairo，PDF 用例不 skip）
CMD ["python", "-m", "pytest", "tests/copilot/", "-q", "--tb=short"]
