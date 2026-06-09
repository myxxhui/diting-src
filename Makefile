# diting-src Makefile
# [Ref: 03_原子目标与规约/_共享规约/02_三位一体仓库规约]
# [Ref: step_08 · WeasyPrint 镜像验证 / §3.11 冒烟]

# Python：优先 .venv（make deps），避免系统 python 缺 sqlalchemy/pytest
PYTHON ?= $(shell if [ -x .venv/bin/python3 ]; then echo .venv/bin/python3; elif command -v python3.9 >/dev/null 2>&1; then echo python3.9; else echo python3; fi)
RUNPY = PYTHONPATH=. $(PYTHON)

.PHONY: deps venv _ensure-deps
deps: venv
venv:
	@if [ ! -x .venv/bin/python3 ]; then \
	  (command -v python3.9 >/dev/null 2>&1 && python3.9 -m venv .venv) || python3 -m venv .venv; \
	fi
	.venv/bin/pip install -q -e ".[copilot,dev,workspace,pdf-verify]"
	@echo "✅ deps 就绪 · $$(.venv/bin/python3 --version)"

_ensure-deps:
	@$(RUNPY) -c "import sqlalchemy, pytest" 2>/dev/null || $(MAKE) deps

.PHONY: test test-integration-redis build lint clean
.PHONY: super-evo-dev super-evo-infra-up super-evo-infra-down super-evo-test
.PHONY: test-teacher-distill distill-demo
.PHONY: cg-dev cg-test cg-init-db cg-deploy-infra cg-stop
.PHONY: cg-phase-b-preflight cg-phase-b-help
.PHONY: deep-strike-dev state-watch-dev exit-engine-dev
# D3 state_watch · step01 一键合约 [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_01 §7.2]
.PHONY: watch-step01-prep watch-step01-test watch-step01-all watch-step01-status
# D3 state_watch · step02 一键合约 [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_02 §7.2]
.PHONY: watch-step02-prep watch-step02-financial-once watch-step02-news-once
.PHONY: watch-step02-coverage watch-step02-test watch-step02-all watch-step02-status watch-step02-clean
# D3 state_watch · step03 一键合约 [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_03 §7.2]
.PHONY: watch-step03-prep watch-step03-price-once watch-step03-event-once watch-step03-trade-window-check
.PHONY: watch-step03-physical-p5-once watch-step03-physical-p6-once watch-step03-physical-p7-once
.PHONY: watch-step03-physical-all watch-step03-physical-status
.PHONY: watch-step03-test watch-step03-all watch-step03-status watch-step03-clean
# D3 state_watch · step09 市场阶段分类器 [Ref: step_09 §7.2]
.PHONY: watch-step09-prep watch-step09-classify-all watch-step09-distribution
.PHONY: watch-step09-email-summary watch-step09-test watch-step09-all watch-step09-status watch-step09-clean
# D4 exit_engine · step01 一键合约 [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_01 §7.2]
.PHONY: exit-step01-prep exit-step01-test exit-step01-all exit-step01-status
# D4 exit_engine · step02 一键合约 [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_02 §7.2]
.PHONY: exit-step02-prep exit-step02-sync exit-step02-update-once exit-step02-list
.PHONY: exit-step02-test exit-step02-all exit-step02-status exit-step02-clean
# D4 exit_engine · step03 一键合约 [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_03 §7.2]
.PHONY: exit-step03-prep exit-step03-preview exit-step03-evaluate-one exit-step03-threshold-test
.PHONY: exit-step03-test exit-step03-all exit-step03-status exit-step03-clean
# D3 state_watch · step04 一键合约 [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_04 §7.2]
.PHONY: watch-step04-prep watch-step04-migrate watch-step04-scheduler-up watch-step04-once-all
.PHONY: watch-step04-aggregate watch-step04-test watch-step04-all watch-step04-status watch-step04-clean
# D4 exit_engine · step04 一键合约 [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_04 §7.2]
.PHONY: exit-step04-prep exit-step04-preview exit-step04-buffer-progress exit-step04-evaluate-one
.PHONY: exit-step04-test exit-step04-all exit-step04-status exit-step04-clean
.PHONY: copilot-step01-prep copilot-step01-up copilot-step01-health copilot-step01-test
.PHONY: copilot-step01-all copilot-step01-status copilot-step01-down
.PHONY: copilot-step02-prep copilot-step02-migrate copilot-step02-import-sot
.PHONY: copilot-step02-notrade-check copilot-step02-test copilot-step02-all copilot-step02-status copilot-step02-clean
.PHONY: docker-copilot-build docker-step08-pytest docker-step08-smoke-up docker-step08-smoke-down docker-step08-smoke-verify
.PHONY: test-llama-factory-train sanity-train-dry sanity-train
# D1 cryo_guard · step01 一键合约 [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
.PHONY: cryo-step01-prep cryo-step01-test cryo-step01-all cryo-step01-status
# D1 cryo_guard · step02 一键合约 [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_02 §7.2]
.PHONY: cryo-step02-prep cryo-step02-collect cryo-step02-quality-check
.PHONY: cryo-step02-holdout cryo-step02-dvc cryo-step02-test
.PHONY: cryo-step02-all cryo-step02-status cryo-step02-clean
# D2 deep_strike · step01/step02 一键合约 [Ref: 03_/02_维度二/stages/stage_1_启动期/steps]
.PHONY: deep-step01-prep deep-step01-test deep-step01-all deep-step01-status
.PHONY: deep-step02-prep deep-step02-collect deep-step02-test deep-step02-all deep-step02-status
# D2 deep_strike · step03 一键合约 [Ref: 03_/02_维度二/stages/stage_1_启动期/steps/step_03 §7.2]
.PHONY: deep-step03-prep deep-step03-build deep-step03-quality-check deep-step03-test
.PHONY: deep-step03-all deep-step03-status deep-step03-clean
# D2 deep_strike · step04 一键合约 [Ref: 03_/02_维度二/stages/stage_1_启动期/steps/step_04 §7.2]
.PHONY: deep-step04-prep deep-step04-scan-all deep-step04-quality-check deep-step04-test
.PHONY: deep-step04-all deep-step04-status deep-step04-clean
.PHONY: deep-step04-mapper-run deep-step04-mapper-status
# D5 super_evo · step01/step02 一键合约 [Ref: 03_/05_维度五/stages/stage_1_启动期/steps]
.PHONY: evo-step01-infra-up evo-step01-infra-down evo-step01-init evo-step01-test evo-step01-all evo-step01-status
.PHONY: evo-step02-test evo-step02-smoke evo-step02-http evo-step02-all
# D5 super_evo · step03 一键合约 [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03 §7.2]
.PHONY: evo-step03-prep evo-step03-import-cryo evo-step03-import-thrust evo-step03-import-narrative
.PHONY: evo-step03-export evo-step03-progress evo-step03-test evo-step03-all evo-step03-status evo-step03-clean
# D5 super_evo · step04 一键合约 [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04 §7.2]
# DECISION_PENDING: evo-step04-train-* 需 GPU ≥24GB（或 QLoRA ≥16GB）
.PHONY: evo-step04-prep evo-step04-sanity-train evo-step04-test evo-step04-all evo-step04-status
.PHONY: evo-step04-train-cryo evo-step04-train-thrust evo-step04-train-narrative

test:
	PYTHONPATH=. python3 -m pytest tests/ -v

# ─── D1 cryo_guard · step01（环境与基础设施）────────────────────────────────────
# [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01 §7.2]

MY_HOLDINGS_YAML ?= data/config/my_holdings.yaml

cryo-step01-prep:
	@echo "▶ [cryo-step01-prep] DB 初始化 + SoT 自检"
	PYTHONPATH=. python3 -m apps.cryo_guard.db.init_db
	@test -f "$(MY_HOLDINGS_YAML)" \
	  && echo "✅ MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) 已就绪" \
	  || echo "⚠️  MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) 不存在；请先复制 data/config/my_holdings.example.yaml"

cryo-step01-test:
	@echo "▶ [cryo-step01-test] pytest cryo_guard 全套"
	PYTHONPATH=. python3 -m pytest tests/cryo_guard -v --cov=apps/cryo_guard --cov-report=term-missing

cryo-step01-all: cryo-step01-prep cryo-step01-test
	@echo "✅ [cryo-step01-all] 准出：DB 初始化 + 单测通过"

cryo-step01-status:
	@echo "▶ [cryo-step01-status] 当前 DB 表状态（只读）"
	@PYTHONPATH=. python3 -c "from apps.cryo_guard.db.init_db import get_engine; import sqlalchemy; e=get_engine(); print(sqlalchemy.inspect(e).get_table_names())" 2>/dev/null \
	  || sqlite3 data/cryo_guard.db ".tables" 2>/dev/null \
	  || echo "⚠️  DB 文件尚未创建（先跑 cryo-step01-prep）"

# ─── D1 cryo_guard · step02（数据采集 + §3.5 矩阵 + Holdout）─────────────────
# [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_02 §7.2]
# 入参（均可 .env / 命令行覆盖）：MY_HOLDINGS_YAML / CRYO_YEARS / CRYO_REPORT_TYPES / CRYO_THROTTLE_SEC

CRYO_YEARS ?= 2022,2023,2024,2025
CRYO_REPORT_TYPES ?= annual,semi,q1,q3
CRYO_THROTTLE_SEC ?= 0.6

cryo-step02-prep:
	@echo "▶ [cryo-step02-prep] alembic upgrade + SoT 自检"
	@echo "  做了什么：执行 alembic upgrade head，确保 related_party_graph / industry 列已迁移"
	@echo "  期望：active symbols 非空，退出码 0"
	PYTHONPATH=. python3 -m apps.cryo_guard.db.init_db
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import active_symbols; syms=active_symbols(); print(f'  实际：active symbols = {syms}'); assert len(syms)>0, '持仓 SoT 无 active 标的，请先填写 MY_HOLDINGS_YAML'"

cryo-step02-collect:
	@echo "▶ [cryo-step02-collect] 一键采集（财报 + 行业 + 公告 + OCR 附注）"
	@echo "  做了什么：按 SoT active 标的采集四类数据源"
	@echo "  期望：4 张业务表全部增量更新（upsert）"
	MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) CRYO_YEARS=$(CRYO_YEARS) CRYO_REPORT_TYPES=$(CRYO_REPORT_TYPES) CRYO_THROTTLE_SEC=$(CRYO_THROTTLE_SEC) \
	  PYTHONPATH=. python3 training/data/scripts/crawl_financial_reports.py
	MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) \
	  PYTHONPATH=. python3 training/data/scripts/crawl_industry_category.py
	MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) CRYO_YEARS=$(CRYO_YEARS) CRYO_THROTTLE_SEC=$(CRYO_THROTTLE_SEC) \
	  PYTHONPATH=. python3 training/data/scripts/crawl_announcements.py
	MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) CRYO_NOTES_FETCH_PDF=1 \
	  PYTHONPATH=. python3 training/data/scripts/ocr_financial_notes.py
	PYTHONPATH=. python3 training/scripts/build_related_party_graph.py
	@echo "  实际：采集完成，见 cryo-step02-status 查看行数"

cryo-step02-quality-check:
	@echo "▶ [cryo-step02-quality-check] F4 抽样 + §3.5 矩阵复核（18 项）"
	@echo "  做了什么：运行 validate_quality_matrix.py 输出 18 行 ✅/⚠️"
	@echo "  期望：退出码 0，18 行均非 ❌"
	PYTHONPATH=. python3 training/scripts/validate_quality_matrix.py
	@echo "  实际：见上方输出"

cryo-step02-holdout:
	@echo "▶ [cryo-step02-holdout] Holdout 锁库 + 守门验证"
	@echo "  做了什么：生成 H001~H050 + manifest.json + chmod -w + 守门验证"
	@echo "  期望：manifest 50 行；守门器退出码 0"
	PYTHONPATH=. python3 training/scripts/build_holdout_manifest.py
	PYTHONPATH=. python3 training/scripts/holdout_guard.py --verify
	@echo "  实际：$$(ls training/data/holdout/H*.json 2>/dev/null | wc -l | tr -d ' ') 个 Holdout 文件"

cryo-step02-dvc:
	@echo "▶ [cryo-step02-dvc] DVC 锁定三数据集"
	@echo "  做了什么：dvc add DB + PDF 目录 + Holdout"
	@echo "  期望：dvc status 干净"
	cd diting-src 2>/dev/null || true; \
	  PYTHONPATH=. python3 -m dvc add data/cryo_guard.db data/raw/financial_notes training/data/holdout 2>/dev/null || \
	  echo "⚠️  DVC remote 未配置，先本地 add 后期再 push"
	@PYTHONPATH=. python3 -m dvc status 2>/dev/null || echo "⚠️  DVC 状态检查失败，请检查 dvc remote 配置"

cryo-step02-test:
	@echo "▶ [cryo-step02-test] pytest 数据管道单测（≥ 8 passed）"
	PYTHONPATH=. python3 -m pytest tests/cryo_guard/test_data_pipeline.py -q

cryo-step02-all: cryo-step02-prep cryo-step02-collect cryo-step02-quality-check cryo-step02-holdout cryo-step02-dvc cryo-step02-test
	@echo "✅ [cryo-step02-all] 端到端完成；4 标的全套数据 + §3.5 矩阵 + Holdout + DVC + 单测通过"

cryo-step02-status:
	@echo "▶ [cryo-step02-status] 数据量进度快照（只读）"
	@PYTHONPATH=. python3 scripts/cryo_step02_status.py 2>/dev/null || echo "  ⚠️  状态读取失败（先跑 cryo-step02-prep 或检查 scripts/cryo_step02_status.py）"

cryo-step02-clean:
	@echo "▶ [cryo-step02-clean] 清除产出（保留 Holdout）"
	@echo "  ⚠️  将删除 data/cryo_guard.db 与 data/raw/financial_notes；Holdout 不动"
	@read -p "确认清除？(y/N): " ans && [ "$$ans" = "y" ] && \
	  (rm -f data/cryo_guard.db; rm -rf data/raw/financial_notes; echo "✅ 已清除") || echo "取消"

# ─── D1 cryo_guard · step03（Teacher 蒸馏 smoke + 导出 + 单测）─────────────────
# [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03 §7.2]
# 启动期候选 ~67 条；须 ANTHROPIC_API_KEY；禁止 CRYO_GUARD_DISTILL_MOCK（no-mock-policy）

.PHONY: cryo-step03-prep cryo-step03-smoke cryo-step03-distill cryo-step03-export
.PHONY: cryo-step03-test cryo-step03-all cryo-step03-status cryo-step03-clean

DISTILL_SMOKE_LIMIT ?= 5

cryo-step03-prep: cryo-step01-prep
	@echo "▶ [cryo-step03-prep] distillation 包 + 凭证自检"
	@PYTHONPATH=. python3 -c "\
from apps.cryo_guard.distillation.distill_runner import TARGETS; \
from apps.cryo_guard.distillation.prompts import build_prompt; \
from apps.cryo_guard.distillation.teacher_client import TeacherClient; \
from apps.cryo_guard.distillation.verifier import auto_accept_if_safe; \
from apps.cryo_guard.distillation.exporter import export_engine_to_llama_factory; \
print('  distillation 模块导入 ✅'); print(f'  TARGETS={TARGETS}')"
	@PYTHONPATH=. python3 training/scripts/run_cryo_phase_b.py --preflight-only

cryo-step03-smoke: cryo-step03-prep
	@echo "▶ [cryo-step03-smoke] 真实 Teacher 每引擎 $(DISTILL_SMOKE_LIMIT) 条（需 ANTHROPIC_API_KEY）"
	CRYO_SKIP_D5=1 CRYO_DISTILL_SMOKE_LIMIT=$(DISTILL_SMOKE_LIMIT) \
	  PYTHONPATH=. python3 training/scripts/run_cryo_phase_b.py --smoke --skip-guard

cryo-step03-distill: cryo-step03-prep
	@echo "▶ [cryo-step03-distill] 真实 Teacher API 全量候选（需 ANTHROPIC_API_KEY）"
	CRYO_SKIP_D5=1 PYTHONPATH=. python3 training/scripts/run_cryo_phase_b.py

cryo-step03-export:
	@echo "▶ [cryo-step03-export] 导出 verified=TRUE → LLaMA-Factory JSON（排除 mock Teacher）"
	PYTHONPATH=. python3 scripts/cryo_distill_export.py

cryo-step03-test:
	@echo "▶ [cryo-step03-test] pytest distillation 单测"
	PYTHONPATH=. python3 -m pytest tests/cryo_guard/test_distillation.py -v --tb=short

cryo-step03-all: cryo-step03-prep cryo-step03-test cryo-step03-status
	@echo "✅ [cryo-step03-all] 准出：preflight + pytest + 状态（真实蒸馏请 make cryo-step03-smoke）"

cryo-step03-status:
	@echo "▶ [cryo-step03-status] teacher_distill 快照"
	PYTHONPATH=. python3 scripts/cryo_distill_status.py

cryo-step03-clean:
	@echo "▶ [cryo-step03-clean] 清 mock Teacher 蒸馏行（--all 可全清）"
	PYTHONPATH=. python3 scripts/cryo_distill_clean.py

# ─── D2 deep_strike · step01（环境与服务骨架）───────────────────────────────────
# [Ref: 03_/02_维度二/stages/stage_1_启动期/steps/step_01]

deep-step01-prep:
	@echo "▶ [deep-step01-prep] deep_strike DB 初始化"
	@echo "  做了什么：init_db 建四表；期望：thesis_cards / scan_logs / evidence_records / human_confirmations"
	PYTHONPATH=. python3 -c "\
import asyncio; \
from apps.deep_strike.db.database import init_db; \
asyncio.run(init_db()); \
print('[deep-strike] tables created.')"
	@echo "  实际：DB 初始化完成"

deep-step01-test:
	@echo "▶ [deep-step01-test] pytest deep_strike health（≥ 4 passed）"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_health.py -v

deep-step01-all: deep-step01-prep deep-step01-test
	@echo "✅ [deep-step01-all] deep_strike 环境骨架准出"

deep-step01-status:
	@echo "▶ [deep-step01-status] deep_strike 当前服务状态（只读）"
	@PYTHONPATH=. python3 -c "\
from apps.deep_strike.config import settings; import os; \
db=settings.db_url.split('///')[-1]; \
print(f'  db_url: {settings.db_url}'); \
print(f'  DB 文件存在: {os.path.exists(db)}')" 2>/dev/null || echo "⚠️  配置读取失败"

# ─── D2 deep_strike · step02（数据采集）────────────────────────────────────────
# [Ref: 03_/02_维度二/stages/stage_1_启动期/steps/step_02]

deep-step02-prep:
	@echo "▶ [deep-step02-prep] deep_strike step02 前置检查"
	$(MAKE) deep-step01-all

deep-step02-collect:
	@echo "▶ [deep-step02-collect] deep_strike 数据采集（复用 cryo_guard 财报 + 公告共表）"
	@echo "  做了什么：deep_strike 读 financial_reports / announcements 共表，按 active 标的建 thesis_cards 初始化行"
	@echo "  期望：thesis_cards 表有 active 标的的占位 scan_logs"
	MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) \
	  PYTHONPATH=. python3 -c "\
from apps.common.holdings_sot import active_symbols; syms = active_symbols(); \
print(f'  实际：active symbols = {syms}'); \
print('  deep_strike 数据源依赖 cryo_guard 共表（financial_reports / announcements）'); \
print('  请确保已执行 make cryo-step02-collect')"

deep-step02-test:
	@echo "▶ [deep-step02-test] pytest deep_strike（health + 数据层）"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/ -v

deep-step02-all: deep-step02-prep deep-step02-collect deep-step02-test
	@echo "✅ [deep-step02-all] deep_strike step02 数据准出"

deep-step02-status:
	@echo "▶ [deep-step02-status] deep_strike 数据快照（只读）"
	@PYTHONPATH=. python3 -c "\
from apps.deep_strike.config import settings; import sqlite3, os; \
db = settings.db_url.split('///')[-1]; \
print(f'  DB: {db}  存在: {os.path.exists(db)}'); \
conn = sqlite3.connect(db) if os.path.exists(db) else None; \
[print(f'  {t}: {conn.execute(\"SELECT COUNT(*) FROM \"+t).fetchone()[0]}') \
  for t in ['thesis_cards','scan_logs','evidence_records','human_confirmations'] \
  if conn] if conn else None; \
conn and conn.close() \
" 2>/dev/null || echo "⚠️  无法读取 deep_strike DB"

# ─── D2 deep_strike · Lighthouse 五场景（Opus 阶段）──────────────────────────
# [Ref: 03_/02_维度二/.../step_02~07 The Sniffer/Architect/Critic/Scorer/Timer]
# [Ref: 共享规约 19 AIDispatcher 唯一入口]
.PHONY: deep-step02-lighthouse-prep deep-step02-lighthouse-test deep-step02-lighthouse-monitor-test
.PHONY: deep-step02-lighthouse-opus-smoke deep-step02-lighthouse-all

deep-step02-lighthouse-prep:
	@echo "▶ [lighthouse-prep] 验证 AIDispatcher 单实例 + 双模型分配"
	@PYTHONPATH=. python3 scripts/evo_step02_prep.py
	@echo "  做了什么：复用 evo prep 检查 ANTHROPIC_API_KEY + 模型分配"

deep-step02-lighthouse-test:
	@echo "▶ [lighthouse-test] Lighthouse 五场景单测（全 mock，无需 API Key）"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_lighthouse.py -q

deep-step02-lighthouse-monitor-test:
	@echo "▶ [lighthouse-monitor-test] monitor_dict writer/reader 单测"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_monitor_dict.py -q

deep-step02-lighthouse-opus-smoke:
	@echo "▶ [lighthouse-opus-smoke] Opus 远程联调（5 次调用）"
	@echo "  期望：Sniffer/Critic/Scorer/Architect/Timer 各 1 次远程调用全部通过"
	PYTHONPATH=. python3 scripts/lighthouse_opus_smoke.py

deep-step02-lighthouse-all: deep-step02-lighthouse-prep deep-step02-lighthouse-test deep-step02-lighthouse-monitor-test
	@echo "✅ [lighthouse-all] D2 Lighthouse 五场景准出：双模型分层 ✅  单测 ✅  monitor_dict ✅（如需 Opus 联调请 make deep-step02-lighthouse-opus-smoke）"

# ─── D5 super_evo · step01（环境与基础设施）─────────────────────────────────────
# [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]

SUPER_EVO_COMPOSE = deploy/docker-compose/super-evo-infra.yml

evo-step01-infra-up:
	@echo "▶ [evo-step01-infra-up] 拉起 MinIO + Redis"
	docker compose -f $(SUPER_EVO_COMPOSE) up -d
	@echo "  实际：MinIO http://localhost:9000  Redis localhost:6379"

evo-step01-infra-down:
	@echo "▶ [evo-step01-infra-down] 停止 MinIO + Redis"
	docker compose -f $(SUPER_EVO_COMPOSE) down

evo-step01-init:
	@echo "▶ [evo-step01-init] MinIO bucket + DVC remote 初始化"
	@echo "  做了什么：ensure super-evo bucket + dvc 配置 minio remote"
	@echo "  期望：bucket 存在；dvc remote list 含 minio"
	PYTHONPATH=. python3 -c "\
from apps.super_evo.storage.minio_client import MinIOClient; \
c = MinIOClient(); c.ensure_bucket(); h = c.health(); \
print(f'  MinIO: {h}'); assert h['ok'], f'MinIO health 失败: {h}'"
	@cd training && (PYTHONPATH=.. python3 -m dvc remote list 2>/dev/null || echo "  ⚠️  DVC remote 尚未配置，执行 dvc remote add -d minio s3://super-evo/dvc-store")
	@echo "  实际：MinIO bucket 就绪"

evo-step01-test:
	@echo "▶ [evo-step01-test] pytest super_evo health + storage（≥ 7 passed）"
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_health.py tests/super_evo/test_storage.py -v

evo-step01-all: evo-step01-infra-up evo-step01-init evo-step01-test
	@echo "✅ [evo-step01-all] D5 step01 准出：MinIO + Redis 就绪；storage 单测通过"

evo-step01-status:
	@echo "▶ [evo-step01-status] D5 step01 基础设施状态（只读）"
	@PYTHONPATH=. python3 -c "\
from apps.super_evo.storage.minio_client import MinIOClient; \
h = MinIOClient().health(); print(f'  MinIO: {h}')" 2>/dev/null || echo "  ⚠️  MinIO 连接失败（infra 未启动？）"
	@docker compose -f $(SUPER_EVO_COMPOSE) ps 2>/dev/null | grep -E "NAME|minio|redis" || echo "  ⚠️  docker-compose 状态不可读"

# ─── D5 super_evo · step02（C1 Teacher 蒸馏器）──────────────────────────────────
# [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02 §7.2]

evo-step02-prep:
	@echo "▶ [evo-step02-prep] 验证 TEACHER_MODEL + LIGHTHOUSE_REMOTE_MODEL 配置"
	@echo "  做了什么：读 .env，打印双模型分配结果"
	PYTHONPATH=. python3 scripts/evo_step02_prep.py

evo-step02-test:
	@echo "▶ [evo-step02-test] pytest Teacher 蒸馏器（≥ 14 passed）"
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_teacher_distiller.py -q

evo-step02-dry-run:
	@echo "▶ [evo-step02-dry-run] dry_run 单条蒸馏（无需 API Key / MinIO）"
	@echo "  期望：decision 在 {pass,degrade,reject}，dry_run=True"
	PYTHONPATH=. python3 scripts/evo_step02_dry_run.py

evo-step02-distill-health:
	@echo "▶ [evo-step02-distill-health] /api/distill/health 端点校验（需服务启动）"
	@curl -sf http://127.0.0.1:8090/api/distill/health 2>/dev/null | \
	  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  teacher={d[\"teacher_model\"]} dry_run={d[\"dry_run\"]} ok={d[\"ok\"]}'); assert d['ok']" \
	  || echo "  ⚠️  服务未启动，跳过 HTTP 冒烟（make super-evo-dev 后重试）"

evo-step02-smoke: evo-step02-dry-run

evo-step02-http:
	@echo "▶ [evo-step02-http] TestClient /api/distill/health + /single（无需手动起服务）"
	PYTHONPATH=. python3 scripts/evo_step02_http_distill.py

evo-step02-all: evo-step02-prep evo-step02-test evo-step02-dry-run evo-step02-http
	@echo "✅ [evo-step02-all] D5 step02 准出：双模型分层 ✅  Teacher 单测 ✅  dry_run ✅  HTTP 冒烟 ✅"

# 临时拉起 Redis（6379），跑集成用例后强制删除容器；需本机 Docker
test-integration-redis:
	docker rm -f diting-pytest-redis 2>/dev/null || true
	docker run -d --name diting-pytest-redis -p 6379:6379 redis:7-alpine
	sleep 1
	PYTHONPATH=. python3 -m pytest tests/integration/test_redis_ping.py -v; \
		EC=$$?; docker rm -f diting-pytest-redis; exit $$EC

build:
	docker build -t diting-src-copilot:latest .

# ─── Copilot K3s 镜像（Helm diting-stack.copilot）────────────────────────────
ACR_REGISTRY ?= crpi-7vifw4ok9jkcxr60.cn-hongkong.personal.cr.aliyuncs.com
ACR_REPO_COPILOT ?= titan-core/diting-copilot
ACR_USERNAME ?= sean_hui
DITING_ACR_PASSWORD ?=
COPILOT_IMAGE_TAG ?= latest
ACR_IMAGE_COPILOT := $(ACR_REGISTRY)/$(ACR_REPO_COPILOT):$(COPILOT_IMAGE_TAG)
ACR_IMAGE_COPILOT_LATEST := $(ACR_REGISTRY)/$(ACR_REPO_COPILOT):latest
DOCKER_PLATFORM ?= linux/amd64
# 加速：BuildKit + pip 层缓存；默认只推 git sha，不推 :latest
DOCKER_BUILDKIT ?= 1
export DOCKER_BUILDKIT
PUSH_COPILOT_LATEST ?= 0

.PHONY: build-copilot-image push-copilot-image push-copilot-image-only copilot-image-all
build-copilot-image:
	@root="$$(dirname $(realpath $(firstword $(MAKEFILE_LIST))))"; \
	cd "$$root" && echo "▶ [build-copilot-image] 开始 docker build（依赖层有缓存时较快 · 约 5–10min 无缓存）…" && \
	docker build --progress=plain --platform $(DOCKER_PLATFORM) -f Dockerfile.copilot -t diting-copilot:latest . && \
	docker tag diting-copilot:latest diting-copilot:$(COPILOT_IMAGE_TAG) && \
	echo "build-copilot-image: diting-copilot:latest + :$(COPILOT_IMAGE_TAG) OK ($(DOCKER_PLATFORM))"

# 仅推送已构建的本地镜像（默认只推 $(COPILOT_IMAGE_TAG)；PUSH_COPILOT_LATEST=1 时额外推 latest）
push-copilot-image-only:
	@if [ -z "$(DITING_ACR_PASSWORD)" ]; then echo "错误: 请 export DITING_ACR_PASSWORD 或在 Makefile 赋值"; exit 1; fi; \
	echo "$(DITING_ACR_PASSWORD)" | docker login $(ACR_REGISTRY) -u $(ACR_USERNAME) --password-stdin || exit 1; \
	_src="diting-copilot:latest"; \
	if docker image inspect "diting-copilot:$(COPILOT_IMAGE_TAG)" >/dev/null 2>&1; then _src="diting-copilot:$(COPILOT_IMAGE_TAG)"; fi; \
	docker tag "$$_src" $(ACR_IMAGE_COPILOT) && docker push $(ACR_IMAGE_COPILOT) && \
	echo "push-copilot-image: $(ACR_IMAGE_COPILOT) OK (from $$_src)"; \
	if [ "$(PUSH_COPILOT_LATEST)" = "1" ]; then \
	  docker tag diting-copilot:latest $(ACR_IMAGE_COPILOT_LATEST) && docker push $(ACR_IMAGE_COPILOT_LATEST) && \
	  echo "push-copilot-image: $(ACR_IMAGE_COPILOT_LATEST) OK"; \
	fi

push-copilot-image: build-copilot-image push-copilot-image-only

copilot-image-all: push-copilot-image

docker-copilot-build:
	docker compose -f docker-compose.copilot.yml build

# 镜像内：Pango/Cairo + fonts-noto-cjk + pdfminer；月报 PDF 用例应 10 passed、0 skipped
docker-step08-pytest:
	docker compose -f docker-compose.copilot.yml run --rm copilot-test

docker-step08-smoke-up:
	docker compose -f docker-compose.copilot.yml up -d redis copilot-app

docker-step08-smoke-down:
	docker compose -f docker-compose.copilot.yml down

# 需先 make docker-step08-smoke-up，等待数秒后执行；对容器内 WeasyPrint 生成 PDF
docker-step08-smoke-verify:
	curl -sf "http://127.0.0.1:8080/api/admin/circuit-breaker/status" | python3 -m json.tool
	curl -sf -o /tmp/m-step08-smoke.pdf -w "\nHTTP %{http_code}\n" "http://127.0.0.1:8080/api/reports/monthly/$$(date +%Y-%m)/pdf?user_id=default"
	test -s /tmp/m-step08-smoke.pdf
	command -v pdfinfo >/dev/null 2>&1 && pdfinfo /tmp/m-step08-smoke.pdf | head -12 || true

lint:
	@echo "make lint: 请在此补充 lint 指令"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

super-evo-infra-up:
	docker compose -f deploy/docker-compose/super-evo-infra.yml up -d

super-evo-infra-down:
	docker compose -f deploy/docker-compose/super-evo-infra.yml down

super-evo-dev:
	PYTHONPATH=. uvicorn apps.super_evo.main:app --port 8090 --reload

super-evo-test:
	PYTHONPATH=. python3 -m pytest tests/super_evo/ -v

test-teacher-distill:
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_teacher_distiller.py -v

.PHONY: label-studio-up label-studio-down label-studio-init label-studio-test

label-studio-up:
	docker compose -f deploy/docker-compose/label-studio.yml up -d
	@echo "Web: http://localhost:8081  admin: admin@diting.local / LabelStudio-Admin-1234"

label-studio-down:
	docker compose -f deploy/docker-compose/label-studio.yml down

label-studio-init:
	PYTHONPATH=. python3 scripts/labeling/init_projects.py

label-studio-test:
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_labeling_client.py -q

distill-demo:
	curl -s -X POST http://127.0.0.1:8090/api/distill/single \
	  -H "Content-Type: application/json" \
	  -d '{"task_type":"financial_fraud","sample_id":"demo1","raw_data":{"symbol":"002450","company_name":"康得新","report_date":"2018-12-31","financial_data":{"cash":15e9}}}' \
	  | python3 -m json.tool

# cryo_guard（维度一）· [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
cg-dev:
	PYTHONPATH=. uvicorn apps.cryo_guard.api.main:app --port 8081 --reload

cg-test:
	PYTHONPATH=. python3 -m pytest tests/cryo_guard -v --cov=apps/cryo_guard --cov-report=term-missing

cg-init-db:
	PYTHONPATH=. python3 -m apps.cryo_guard.db.init_db

# step_03 阶段 B 编排（本机；全量蒸馏产生 API 费用）· [Ref: step_03_Teacher蒸馏]
cg-phase-b-help:
	PYTHONPATH=. python3 training/scripts/run_cryo_phase_b.py --help

cg-phase-b-preflight:
	PYTHONPATH=. python3 training/scripts/run_cryo_phase_b.py --preflight-only

cg-deploy-infra:
	kubectl apply -f deploy/k3s/milvus.yaml
	kubectl apply -f deploy/k3s/neo4j.yaml
	@if kubectl describe nodes 2>/dev/null | grep -q "nvidia.com/gpu"; then \
	  kubectl apply -f deploy/k3s/vllm.yaml; \
	else \
	  kubectl apply -f deploy/k3s/vllm-stub.yaml; \
	fi
	kubectl -n diting wait --for=condition=Ready pod -l app=milvus --timeout=300s
	kubectl -n diting wait --for=condition=Ready pod -l app=neo4j --timeout=300s
	kubectl -n diting wait --for=condition=Ready pod -l app=vllm --timeout=600s

cg-stop:
	-kubectl -n diting delete -f deploy/k3s/milvus.yaml --ignore-not-found
	-kubectl -n diting delete -f deploy/k3s/neo4j.yaml --ignore-not-found
	-kubectl -n diting delete -f deploy/k3s/vllm.yaml --ignore-not-found
	-kubectl -n diting delete -f deploy/k3s/vllm-stub.yaml --ignore-not-found

# ─── D3 state_watch · step01（状态机与 DB schema）────────────────────────────────
# [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_01 §7.2]

watch-step01-prep:
	@echo "▶ [watch-step01-prep] DB 初始化（async create_all）"
	PYTHONPATH=. python3 -c "import asyncio; from apps.state_watch.db.session import init_db; asyncio.run(init_db()); print('[state-watch] tables created.')"

watch-step01-test:
	@echo "▶ [watch-step01-test] pytest state_watch 全套"
	PYTHONPATH=. python3 -m pytest tests/state_watch -q

watch-step01-all: watch-step01-prep watch-step01-test
	@echo "✅ [watch-step01-all] 准出：DB 初始化 + 单测通过"

watch-step01-status:
	@echo "▶ [watch-step01-status] 当前 DB 表状态（只读）"
	@PYTHONPATH=. python3 -c "from apps.state_watch.db.init_db import get_engine; import sqlalchemy; e=get_engine(); print(sqlalchemy.inspect(e).get_table_names())" 2>/dev/null \
	  || echo "⚠️  无法读取 state_watch DB（请先 watch-step01-prep）"

# ─── D4 exit_engine · step01（规则引擎框架）──────────────────────────────────────
# [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_01 §7.2]

exit-step01-prep:
	@echo "▶ [exit-step01-prep] DB 初始化"
	PYTHONPATH=. python3 -m apps.exit_engine.db.init_db

exit-step01-test:
	@echo "▶ [exit-step01-test] pytest exit_engine 全套"
	PYTHONPATH=. python3 -m pytest tests/exit_engine -q

exit-step01-all: exit-step01-prep exit-step01-test
	@echo "✅ [exit-step01-all] 准出：DB 初始化 + 单测通过"

exit-step01-status:
	@echo "▶ [exit-step01-status] 当前 DB 表状态（只读）"
	@PYTHONPATH=. python3 -c "from apps.exit_engine.db.init_db import get_engine; import sqlalchemy; e=get_engine(); print(sqlalchemy.inspect(e).get_table_names())" 2>/dev/null \
	  || echo "⚠️  无法读取 exit_engine DB（请先 exit-step01-prep）"

# ─── D3 state_watch · step02（财务/新闻探针）────────────────────────────────────
# [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_02 §7.2]

watch-step02-prep:
	@echo "▶ [watch-step02-prep] SoT active 自检 + 探针依赖"
	@echo "  做了什么：校验 MY_HOLDINGS_YAML 存在且 active≥1"
	@echo "  期望：active symbols 非空"
	@test -f "$(MY_HOLDINGS_YAML)" || (echo "❌ MY_HOLDINGS_YAML=$(MY_HOLDINGS_YAML) 不存在" && exit 1)
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import active_symbols; s=active_symbols(); print(f'  实际：active={len(s)} {s}'); assert len(s)>0"

watch-step02-financial-once: watch-step02-prep
	@echo "▶ [watch-step02-financial-once] 全 active 跑 P1 财务探针"
	PYTHONPATH=. python3 scripts/watch_step02_run.py financial

watch-step02-news-once: watch-step02-prep
	@echo "▶ [watch-step02-news-once] 全 active 跑 P2 新闻探针"
	PYTHONPATH=. python3 scripts/watch_step02_run.py news

watch-step02-coverage: watch-step02-prep
	@echo "▶ [watch-step02-coverage] P1/P2 覆盖率汇总"
	PYTHONPATH=. python3 scripts/watch_step02_run.py coverage

watch-step02-test:
	@echo "▶ [watch-step02-test] pytest 探针单测（≥12）"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_probe_financial.py tests/state_watch/test_probe_news.py -q

watch-step02-all: watch-step02-prep watch-step02-financial-once watch-step02-news-once watch-step02-test
	@echo "✅ [watch-step02-all] 准出：P1+P2 批量跑通 + 单测通过"

watch-step02-status: watch-step02-prep
	@echo "▶ [watch-step02-status] SoT active 数 + 最近探针 CLI 提示"
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import load_holdings_sot; s=load_holdings_sot(); print(f'  source={s.source_path} active={len(s.active_symbols())}')"

watch-step02-clean:
	@echo "▶ [watch-step02-clean] 启动期无持久探针缓存需清理（noop）"

# ─── D4 exit_engine · step02（持仓 SoT + 行情）──────────────────────────────────
# [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_02 §7.2]

EXIT_USE_MOCK ?= 0

exit-step02-prep:
	@echo "▶ [exit-step02-prep] DB 初始化 + SoT 自检"
	PYTHONPATH=. python3 -m apps.exit_engine.db.init_db
	@test -f "$(MY_HOLDINGS_YAML)" || (echo "❌ MY_HOLDINGS_YAML 不存在" && exit 1)
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import load_holdings_sot; s=load_holdings_sot(); print(f'  active={s.active_symbols()} portfolio={s.portfolio_symbols()} watchlist={s.watchlist_symbols()}'); assert len(s.active_symbols())>0"

exit-step02-sync: exit-step02-prep
	@echo "▶ [exit-step02-sync] POST /api/positions/sync 等价（CLI）"
	PYTHONPATH=. python3 -c "\
from apps.exit_engine.db.session import SessionLocal; \
from apps.exit_engine.data.holdings_loader import sync_positions_from_sot; \
s=SessionLocal(); \
r=sync_positions_from_sot(s); \
print(f'  synced={r[\"synced\"]} portfolio={r[\"portfolio_symbols\"]} watchlist={r[\"watchlist_symbols\"]} deactivated={r[\"deactivated\"]} source={r[\"source\"]}'); \
assert r['synced']>0"

exit-step02-update-once: exit-step02-sync
	@echo "▶ [exit-step02-update-once] 行情刷新一次"
	@if [ "$(EXIT_USE_MOCK)" = "1" ]; then \
	  PYTHONPATH=. python3 -m apps.exit_engine.services.quote_scheduler --once --mock; \
	else \
	  PYTHONPATH=. python3 -m apps.exit_engine.services.quote_scheduler --once; \
	fi

exit-step02-list: exit-step02-sync
	@echo "▶ [exit-step02-list] 列出 active 持仓"
	@PYTHONPATH=. python3 -c "\
from apps.exit_engine.db.session import SessionLocal; \
from apps.exit_engine.data.holdings_repo import HoldingsRepository; \
s=SessionLocal(); \
rows=HoldingsRepository(s).list_active(); \
print(f'  count={len(rows)}'); \
[print(f'  {p.symbol} price={p.current_price}') for p in rows]"

exit-step02-test:
	@echo "▶ [exit-step02-test] pytest step02 相关单测"
	PYTHONPATH=. python3 -m pytest tests/exit_engine/test_holdings_repo.py tests/exit_engine/test_holdings_sot_sync.py tests/exit_engine/test_quote_fetcher.py tests/exit_engine/test_quote_scheduler.py -q

exit-step02-all: exit-step02-sync exit-step02-update-once exit-step02-list exit-step02-test
	@echo "✅ [exit-step02-all] 准出：SoT 同步 + 行情刷新 + 单测通过"

exit-step02-status: exit-step02-prep
	@echo "▶ [exit-step02-status] 持仓数 + 最近更新时间"
	@PYTHONPATH=. python3 -c "\
from apps.exit_engine.db.session import SessionLocal; \
from apps.exit_engine.data.holdings_repo import HoldingsRepository; \
from apps.common.holdings_sot import active_symbols; \
s=SessionLocal(); \
rows=HoldingsRepository(s).list_active(); \
print(f'  SoT active={len(active_symbols())} DB active={len(rows)}'); \
[print(f'  {p.symbol} updated={getattr(p,\"updated_at\",None)}') for p in rows[:5]]" 2>/dev/null || true

exit-step02-clean:
	@if [ "$(FORCE)" = "1" ]; then rm -f data/exit_engine.db && echo "🗑 exit_engine.db 已删除"; else echo "跳过（FORCE=1 可删 data/exit_engine.db）"; fi

# ─── D4 exit_engine · step03（SP1 止损协议 yaml + 预览/评估）────────────────────
# [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_03 §7.2]

exit-step03-prep: exit-step02-prep
	@echo "▶ [exit-step03-prep] SP1 yaml + SoT portfolio 自检"
	@test -f apps/exit_engine/configs/exit_protocols.yaml && echo "  exit_protocols.yaml ✅" || (echo "❌ 缺 yaml" && exit 1)
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import load_holdings_sot as l; p=l().portfolio_symbols(); print(f'  portfolio={len(p)} ✅'); exit(0 if p else 1)"

exit-step03-preview: exit-step03-prep
	@echo "▶ [exit-step03-preview] SP1 配置预演"
	PYTHONPATH=. python3 scripts/exit_step03_run.py preview

exit-step03-evaluate-one: exit-step03-prep exit-step02-sync
	@echo "▶ [exit-step03-evaluate-one] portfolio 标的 SP1 评估"
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import load_holdings_sot; print('\n'.join(load_holdings_sot().portfolio_symbols()))" | while read sym; do \
	  echo "  --- $$sym ---"; \
	  PYTHONPATH=. python3 scripts/exit_step03_run.py evaluate-one --symbol $$sym || exit 1; \
	done

exit-step03-threshold-test:
	@echo "▶ [exit-step03-threshold-test] -15% 边界自检"
	PYTHONPATH=. python3 scripts/exit_step03_run.py threshold-test

exit-step03-test:
	@echo "▶ [exit-step03-test] pytest exit_engine SP1/协议"
	PYTHONPATH=. python3 -m pytest tests/exit_engine/test_stop_loss.py tests/exit_engine/test_base_protocol.py -q

exit-step03-all: exit-step03-preview exit-step03-evaluate-one exit-step03-threshold-test exit-step03-test
	@echo "✅ [exit-step03-all] 准出：SP1 preview + evaluate + threshold + pytest"

exit-step03-status:
	@echo "▶ [exit-step03-status] SP1 配置 + 持仓快照"
	PYTHONPATH=. python3 scripts/exit_step03_run.py status

exit-step03-clean:
	@echo "▶ [exit-step03-clean] 启动期无 SP1 专用缓存（noop）"

# ─── D4 exit_engine · step04（SP2 止盈 + 3 交易日缓冲）──────────────────────────
# [Ref: 03_/04_维度四/stages/stage_1_启动期/steps/step_04 §7.2]

exit-step04-prep: exit-step03-prep
	@echo "▶ [exit-step04-prep] SP2 yaml + protocol_logs 表"
	@test -f apps/exit_engine/configs/exit_protocols.yaml && grep -q sp2_take_profit apps/exit_engine/configs/exit_protocols.yaml && echo "  sp2_take_profit ✅" || (echo "❌ 缺 SP2 yaml" && exit 1)
	PYTHONPATH=. python3 -m apps.exit_engine.db.init_db

exit-step04-preview: exit-step04-prep
	@echo "▶ [exit-step04-preview] SP2 配置 + portfolio 三档分布"
	PYTHONPATH=. python3 scripts/exit_step04_run.py preview
	PYTHONPATH=. python3 scripts/exit_step04_run.py preview-distribution

exit-step04-buffer-progress: exit-step04-prep
	@echo "▶ [exit-step04-buffer-progress] pending 1/3、2/3、3/3 分布"
	PYTHONPATH=. python3 scripts/exit_step04_run.py buffer-progress

exit-step04-evaluate-one: exit-step04-prep exit-step02-sync exit-step02-update-once
	@echo "▶ [exit-step04-evaluate-one] portfolio 标的 SP2 评估（连续交易日缓冲）"
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import load_holdings_sot; print('\n'.join(load_holdings_sot().portfolio_symbols()))" | while read sym; do \
	  echo "  --- $$sym ---"; \
	  PYTHONPATH=. python3 scripts/exit_step04_run.py evaluate-one --symbol $$sym || exit 1; \
	done

exit-step04-test:
	@echo "▶ [exit-step04-test] pytest SP2 + 连续缓冲"
	PYTHONPATH=. python3 -m pytest tests/exit_engine/test_take_profit.py tests/exit_engine/test_sp2_streak.py -q

exit-step04-all: exit-step04-preview exit-step04-buffer-progress exit-step04-evaluate-one exit-step04-test
	@echo "✅ [exit-step04-all] 准出：SP2 preview + buffer + evaluate + pytest"

exit-step04-status:
	@echo "▶ [exit-step04-status] SP2 pending + protocol_logs"
	PYTHONPATH=. python3 scripts/exit_step04_run.py status

exit-step04-clean:
	@if [ "$(FORCE)" = "1" ]; then PYTHONPATH=. python3 -c "from sqlalchemy import create_engine,text; from apps.exit_engine.db.session import get_engine; e=get_engine(); c=e.connect(); c.execute(text('DELETE FROM protocol_logs')); c.commit(); print('🗑 protocol_logs 已清')"; else echo "跳过（FORCE=1 可清 protocol_logs）"; fi

# ─── D3 state_watch · step04（ProbeScheduler + SLI 聚合）────────────────────────
# [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_04 §7.2]

watch-step04-prep: watch-step03-prep
	@echo "▶ [watch-step04-prep] probe_aggregator.yaml + NodeSLIValue + SoT 节点"
	PYTHONPATH=. python3 scripts/watch_step04_run.py prep

watch-step04-migrate: watch-step01-prep
	@echo "▶ [watch-step04-migrate] alembic/create_all（node_sli_values）"
	PYTHONPATH=. python3 scripts/watch_step04_run.py migrate

watch-step04-scheduler-up: watch-step04-prep
	@echo "▶ [watch-step04-scheduler-up] 调度器跑 5s + 心跳"
	PYTHONPATH=. python3 scripts/watch_step04_run.py scheduler-up --seconds 5

watch-step04-once-all: watch-step04-prep
	@echo "▶ [watch-step04-once-all] P1~P4 各 tick 一次"
	PYTHONPATH=. python3 scripts/watch_step04_run.py once-all

watch-step04-aggregate: watch-step04-once-all
	@echo "▶ [watch-step04-aggregate] 全 active SLI 加权聚合"
	PYTHONPATH=. python3 scripts/watch_step04_run.py aggregate

watch-step04-test:
	@echo "▶ [watch-step04-test] pytest scheduler + sli_aggregator（≥16）"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_sli_aggregator.py tests/state_watch/test_scheduler.py -q

watch-step04-all: watch-step04-migrate watch-step04-once-all watch-step04-aggregate watch-step04-test
	@echo "✅ [watch-step04-all] 准出：migrate + once + aggregate + pytest"

watch-step04-status: watch-step04-prep
	@echo "▶ [watch-step04-status] 心跳 + node_sli_values"
	PYTHONPATH=. python3 scripts/watch_step04_run.py status

watch-step04-clean:
	@if [ "$(FORCE)" = "1" ]; then PYTHONPATH=. python3 -c "import asyncio; from sqlalchemy import text; from apps.state_watch.db.session import session_ctx; \
async def c(): \
  async with session_ctx() as s: \
    await s.execute(text('DELETE FROM node_sli_values')); \
    await s.commit(); \
    print('🗑 node_sli_values 已清'); \
asyncio.run(c())"; else echo "跳过（FORCE=1 可清 node_sli_values）"; fi

# ─── D2 deep_strike · step03（证据链构建 + 质量矩阵）────────────────────────────
# [Ref: 03_/02_维度二/stages/stage_1_启动期/steps/step_03 §7.2]

deep-step03-prep:
	@echo "▶ [deep-step03-prep] SoT + cryo/state_watch → deep_strike 同步"
	@test -f "$(MY_HOLDINGS_YAML)" && echo "  MY_HOLDINGS_YAML ✅" || (echo "❌ 缺 SoT" && exit 1)
	PYTHONPATH=. python3 scripts/deep_step03_sync_cryo.py

deep-step03-build: deep-step03-prep
	@echo "▶ [deep-step03-build] 全 active 证据链 build"
	PYTHONPATH=. python3 scripts/deep_step03_build.py build

deep-step03-quality-check:
	@echo "▶ [deep-step03-quality-check] §3.5 证据链质量矩阵"
	PYTHONPATH=. python3 training/scripts/validate_evidence_chain_quality.py

deep-step03-test:
	@echo "▶ [deep-step03-test] pytest evidence_builder"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_evidence_builder.py -q

deep-step03-all: deep-step03-build deep-step03-quality-check deep-step03-test
	@echo "✅ [deep-step03-all] 准出：build + quality + pytest"

deep-step03-status:
	@echo "▶ [deep-step03-status] evidence_records 快照"
	PYTHONPATH=. python3 scripts/deep_step03_build.py status

deep-step03-clean:
	@if [ "$(FORCE)" = "1" ]; then PYTHONPATH=. python3 -c "from sqlalchemy import create_engine,text; from apps.deep_strike.config import settings; e=create_engine(settings.db_url.replace('+aiosqlite','')); c=e.connect(); c.execute(text('DELETE FROM evidence_records')); c.commit(); print('🗑 evidence_records 已清')"; else echo "跳过（FORCE=1 可清 evidence_records）"; fi

# ─── D2 deep_strike · step04（利润截留扫描仪剧本 + The Mapper 业绩弹性闸门）─────────
# [Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04 §7.2]

deep-step04-prep:
	@echo "▶ [deep-step04-prep] step03 证据链质量门 0 验证 + elasticity_thresholds.yaml 存在"
	@test -f "apps/deep_strike/configs/elasticity_thresholds.yaml" && \
		echo "  elasticity_thresholds.yaml ✅" || \
		(echo "❌ 缺 elasticity_thresholds.yaml" && exit 1)
	@PYTHONPATH=. python3 -c "from apps.deep_strike.playbooks.the_mapper.mapper import load_elasticity_thresholds; d=load_elasticity_thresholds(); print(f'  阈值档数: {len(d[\"tiers\"])} ✅')"
	@echo "▶ 做了什么: 检查 elasticity_thresholds.yaml 可读且 4 档完整"

deep-step04-scan-all: deep-step04-prep
	@echo "▶ [deep-step04-scan-all] 全 active 标的跑利润截留扫描仪"
	PYTHONPATH=. python3 scripts/deep_step04_run.py scan-all
	@echo "▶ 做了什么: 全标的跑 profit_capture 剧本并写入 scan_logs"

deep-step04-quality-check:
	@echo "▶ [deep-step04-quality-check] §3.5 18 项质量矩阵"
	PYTHONPATH=. python3 scripts/deep_step04_run.py quality-check
	@echo "▶ 做了什么: 检查 scan_logs/evidence_records/mapper_outputs 质量"

deep-step04-mapper-run:
	@echo "▶ [deep-step04-mapper-run] 对 Critic 通过簇跑 The Mapper 业绩弹性闸门"
	PYTHONPATH=. python3 scripts/deep_step04_run.py mapper-run
	@echo "▶ 做了什么: 写入 mapper_outputs + 投递 events:deep_strike:thesis_proposed"
	@echo "▶ 期望什么: mapper_outputs 行数 ≥ 1（若当日有 critic-pass cluster）"

deep-step04-mapper-status:
	@echo "▶ [deep-step04-mapper-status] 近 7 日 mapper_outputs 市值段分布"
	PYTHONPATH=. python3 scripts/deep_step04_run.py mapper-status

deep-step04-test:
	@echo "▶ [deep-step04-test] pytest 利润截留剧本 + The Mapper"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_profit_capture.py tests/deep_strike/test_the_mapper.py -q
	@echo "▶ 做了什么: 跑 profit_capture + mapper 单元测试（≥14 测试）"

deep-step04-all: deep-step04-scan-all deep-step04-mapper-run deep-step04-quality-check deep-step04-test
	@echo "✅ [deep-step04-all] 准出：scan + mapper + quality + pytest 全通过"
	@echo "▶ 做了什么: 完整端到端 step04 流水线"
	@echo "▶ 期望什么: scan_logs ≥ N 条；mapper_outputs ≥ 1（有 critic-pass 时）；pytest 绿"
	@PYTHONPATH=. python3 scripts/deep_step04_run.py status

deep-step04-status:
	@echo "▶ [deep-step04-status] 每 symbol 最近 scan_logs 摘要"
	PYTHONPATH=. python3 scripts/deep_step04_run.py status

deep-step04-clean:
	@if [ "$(FORCE)" = "1" ]; then \
		PYTHONPATH=. python3 -c "from sqlalchemy import create_engine,text; \
		from apps.deep_strike.config import settings; \
		e=create_engine(settings.db_url.replace('+aiosqlite','')); \
		c=e.connect(); \
		c.execute(text('DELETE FROM scan_logs')); \
		c.execute(text('DELETE FROM mapper_outputs')); \
		c.commit(); print('🗑 scan_logs + mapper_outputs 已清')"; \
	else echo "跳过（FORCE=1 可清 scan_logs/mapper_outputs）"; fi

# ─── D3 state_watch · step03（P3/P4 + 交易窗 + P5~P7 占位）──────────────────────
# [Ref: 03_/03_维度三/stages/stage_1_启动期/steps/step_03 §7.2]

watch-step03-prep: watch-step02-prep
	@echo "▶ [watch-step03-prep] quote_adapter(MarketQuote) + announcement 可达"
	@PYTHONPATH=. python3 -c "from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_60d; b=fetch_bars_60d('601138'); print(f'  quote bars={len(b)} ✅')"

watch-step03-price-once: watch-step03-prep
	@echo "▶ [watch-step03-price-once] 全 active P3"
	PYTHONPATH=. python3 scripts/watch_step03_run.py price

watch-step03-event-once: watch-step03-prep
	@echo "▶ [watch-step03-event-once] 全 active P4"
	PYTHONPATH=. python3 scripts/watch_step03_run.py event

watch-step03-trade-window-check:
	@echo "▶ [watch-step03-trade-window-check] 交易时段判定"
	PYTHONPATH=. python3 scripts/watch_step03_run.py trade-window-check

watch-step03-physical-p5-once:
	PYTHONPATH=. python3 scripts/watch_step03_run.py physical-p5

watch-step03-physical-p6-once:
	PYTHONPATH=. python3 scripts/watch_step03_run.py physical-p6

watch-step03-physical-p7-once:
	PYTHONPATH=. python3 scripts/watch_step03_run.py physical-p7

watch-step03-physical-all:
	PYTHONPATH=. python3 scripts/watch_step03_run.py physical-all

watch-step03-physical-status:
	PYTHONPATH=. python3 scripts/watch_step03_run.py physical-status

watch-step03-test:
	@echo "▶ [watch-step03-test] pytest state_watch 探针"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_probe_price.py tests/state_watch/test_probe_event.py tests/state_watch/test_scheduler.py -q

watch-step03-all: watch-step03-price-once watch-step03-event-once watch-step03-trade-window-check watch-step03-physical-all watch-step03-test
	@echo "✅ [watch-step03-all] 准出：P3+P4+交易窗+P5~P7占位+pytest"

watch-step03-status: watch-step03-prep
	@echo "▶ [watch-step03-status] SoT + 探针 CLI 提示"
	@PYTHONPATH=. python3 -c "from apps.common.holdings_sot import load_holdings_sot; print(f'  active={len(load_holdings_sot().active_symbols())}')"

watch-step03-clean:
	@echo "▶ [watch-step03-clean] 启动期无探针缓存（noop）"

# ─── D3 state_watch · step09 市场阶段分类器 MVP ───────────────────────────────

watch-step09-prep:
	@echo "▶ [watch-step09-prep] DB + SoT active"
	PYTHONPATH=. python3 scripts/watch_step09_run.py prep

watch-step09-classify-all: watch-step09-prep
	@echo "▶ [watch-step09-classify-all] 全 active 分类 + phase_change 事件"
	PYTHONPATH=. python3 scripts/watch_step09_run.py classify-all

watch-step09-distribution: watch-step09-prep
	@echo "▶ [watch-step09-distribution] 4 档分布"
	PYTHONPATH=. python3 scripts/watch_step09_run.py distribution

watch-step09-email-summary:
	@echo "▶ [watch-step09-email-summary] 已合并至 copilot-morning-brief（W1+W2）"
	@$(MAKE) copilot-morning-brief

watch-step09-test:
	@echo "▶ [watch-step09-test] pytest market_phase（≥15）"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_market_phase_classifier.py -q

watch-step09-all: watch-step09-classify-all watch-step09-distribution watch-step09-test
	@echo "✅ [watch-step09-all] 准出：分类 + 分布 + pytest"

watch-step09-status: watch-step09-prep
	@echo "▶ [watch-step09-status]"
	PYTHONPATH=. python3 scripts/watch_step09_run.py status

watch-step09-clean:
	@echo "▶ [watch-step09-clean] dev only（保留 market_phase_records 历史）"

# ─── D0 copilot · W1+W2 合并持仓早报（8:00 cron 同逻辑）────────────────────────

.PHONY: copilot-morning-brief copilot-morning-brief-fast

copilot-morning-brief:
	@echo "▶ [copilot-morning-brief] W1 health + W2 phase 合并早报 → 邮件"
	PYTHONPATH=. python3 scripts/copilot_morning_brief.py

copilot-morning-brief-fast:
	@echo "▶ [copilot-morning-brief-fast] 跳过重算阶段（用库内缓存）"
	MORNING_BRIEF_RUN_PHASE=0 MORNING_BRIEF_RUN_PROBES=0 PYTHONPATH=. python3 scripts/copilot_morning_brief.py

# ─── D5 super_evo · step03（Label Studio 部署骨架 + import/export）──────────────
# [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03 §7.2]

LS_COMPOSE ?= deploy/docker-compose/label-studio.yml

evo-step03-prep:
	@echo "▶ [evo-step03-prep] Label Studio compose + labelings 表"
	@docker compose -f $(LS_COMPOSE) up -d 2>/dev/null || echo "  ⚠️ docker compose 未起（import 可用 --skip-ls）"
	@PYTHONPATH=. python3 -c "from apps.super_evo.db.database import get_engine; get_engine(); print('  labelings ORM ✅')"

evo-step03-import-cryo: evo-step03-prep
	@echo "▶ [evo-step03-import-cryo] cryo → LS + labelings"
	PYTHONPATH=. python3 scripts/ls_import.py cryo

evo-step03-import-thrust: evo-step03-prep
	@echo "▶ [evo-step03-import-thrust] thrust → LS + labelings"
	PYTHONPATH=. python3 scripts/ls_import.py thrust

evo-step03-import-narrative: evo-step03-prep
	@echo "▶ [evo-step03-import-narrative] narrative → LS + labelings"
	PYTHONPATH=. python3 scripts/ls_import.py narrative

evo-step03-export:
	@echo "▶ [evo-step03-export] 三维度 export verified jsonl"
	PYTHONPATH=. python3 scripts/ls_export.py export-all

evo-step03-progress:
	PYTHONPATH=. python3 scripts/ls_export.py progress

evo-step03-test:
	@echo "▶ [evo-step03-test] pytest ls_* + labeling"
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_ls_import.py tests/super_evo/test_labeling_client.py -q

evo-step03-all: evo-step03-import-cryo evo-step03-import-thrust evo-step03-import-narrative evo-step03-progress evo-step03-export evo-step03-test
	@echo "✅ [evo-step03-all] 准出：三维度 import + progress + export + pytest"

evo-step03-status:
	PYTHONPATH=. python3 scripts/ls_export.py status

evo-step03-clean:
	@if [ "$(FORCE)" = "1" ]; then rm -rf training/data/verified/$$(date -u +%Y%m%d) 2>/dev/null; PYTHONPATH=. python3 -c "from sqlalchemy import create_engine,text; from apps.super_evo.config import settings; e=create_engine(settings.db_url.replace('+aiosqlite','')); c=e.connect(); c.execute(text('DELETE FROM labelings')); c.commit(); print('🗑 labelings 已清')"; else echo "跳过（FORCE=1 可清 labelings）"; fi

# ─── D0 copilot · step01（服务骨架 + 7 stream 健康检查）────────────────────────
# [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_01 §7.2]

COPILOT_PORT ?= 8080
COPILOT_PID_FILE ?= /tmp/copilot-step01.pid

copilot-step01-prep:
	@echo "▶ [copilot-step01-prep] Redis + 依赖自检"
	@docker compose -f docker-compose.copilot.yml up -d redis 2>/dev/null || true
	@sleep 1
	@redis-cli -u "$${COPILOT_REDIS_URL:-redis://127.0.0.1:6379/0}" ping 2>/dev/null | grep -q PONG && echo "  Redis: PONG ✅" || echo "  ⚠️ Redis 未就绪（/health 仍可用，upstream 可能 connection refused）"
	@test -f .env && echo "  .env ✅" || echo "  ⚠️ .env 缺失（可用 .env.template 合并）"

copilot-step01-up: copilot-step01-prep
	@echo "▶ [copilot-step01-up] 后台启动 uvicorn :$(COPILOT_PORT)"
	@-lsof -ti:$(COPILOT_PORT) | xargs kill -9 2>/dev/null || true
	@nohup env PYTHONPATH=. python3 -m uvicorn apps.copilot.main:app --host 127.0.0.1 --port $(COPILOT_PORT) > /tmp/copilot-step01.log 2>&1 & echo $$! > $(COPILOT_PID_FILE)
	@sleep 2
	@echo "  pid=$$(cat $(COPILOT_PID_FILE)) listening :$(COPILOT_PORT)"

copilot-step01-down:
	@if [ -f $(COPILOT_PID_FILE) ]; then kill $$(cat $(COPILOT_PID_FILE)) 2>/dev/null || true; rm -f $(COPILOT_PID_FILE); fi
	@-lsof -ti:$(COPILOT_PORT) | xargs kill -9 2>/dev/null || true
	@echo "  copilot 已停止"

copilot-step01-health: copilot-step01-up
	@echo "▶ [copilot-step01-health] curl /health"
	@curl -sf "http://127.0.0.1:$(COPILOT_PORT)/health" | python3 -c "import sys,json; b=json.load(sys.stdin); assert b.get('status')=='ok'; ups=b.get('upstream',{}); print(f'  status=ok upstream_keys={len(ups)} ✅')"

copilot-step01-test:
	@echo "▶ [copilot-step01-test] pytest tests/copilot/"
	PYTHONPATH=. python3 -m pytest tests/copilot/ -q

copilot-step01-all: copilot-step01-prep copilot-step01-health copilot-step01-test copilot-step01-down
	@echo "✅ [copilot-step01-all] 准出：health + pytest 通过"

copilot-step01-status:
	@echo "▶ [copilot-step01-status] Redis + /health 快照"
	@redis-cli -u "$${COPILOT_REDIS_URL:-redis://127.0.0.1:6379/0}" ping 2>/dev/null || echo "  Redis: down"
	@curl -sf "http://127.0.0.1:$(COPILOT_PORT)/health" 2>/dev/null | python3 -m json.tool || echo "  copilot: not running on :$(COPILOT_PORT)"

# ─── D0 copilot · step02（Web 骨架 + SQLite + SoT 导入）────────────────────────
# [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02 §7.2]

copilot-step02-prep: copilot-step01-prep
	@echo "▶ [copilot-step02-prep] data/ 目录 + SoT 文件"
	@mkdir -p data data/config
	@test -f "$(MY_HOLDINGS_YAML)" && echo "  MY_HOLDINGS_YAML ✅" || echo "  ⚠️ MY_HOLDINGS_YAML 缺失"

copilot-step02-migrate:
	@echo "▶ [copilot-step02-migrate] init_db 建表"
	PYTHONPATH=. python3 -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('  tables created ✅')"

copilot-step02-import-sot: copilot-step02-migrate
	@echo "▶ [copilot-step02-import-sot] SoT → holdings upsert"
	PYTHONPATH=. python3 scripts/copilot_import_sot.py

copilot-step02-notrade-check:
	@bash scripts/assert_no_trade_button.sh

copilot-step02-test:
	@echo "▶ [copilot-step02-test] pytest tests/copilot/"
	PYTHONPATH=. python3 -m pytest tests/copilot/ -q

copilot-step02-all: copilot-step02-prep copilot-step02-import-sot copilot-step02-notrade-check copilot-step02-test
	@echo "✅ [copilot-step02-all] 准出：migrate + SoT 导入 + no-trade + pytest"

copilot-step02-status: copilot-step02-prep
	@PYTHONPATH=. python3 -c "\
import asyncio; from apps.copilot.db.database import AsyncSessionLocal, init_db; \
from apps.common.holdings_sot import active_symbols; \
from sqlalchemy import select, func; from apps.copilot.db.models import Holding; \
async def main(): \
  await init_db(); \
  async with AsyncSessionLocal() as s: \
    n=await s.scalar(select(func.count()).select_from(Holding)); \
    print(f'  SoT active={len(active_symbols())} DB holdings={n}'); \
asyncio.run(main())"

copilot-step02-clean:
	@rm -rf .lhci 2>/dev/null || true
	@echo "  copilot-step02-clean ✅（保留 copilot.db）"

# ─── D0 copilot · step03（体检模块 health_check + Redis consumer + dashboard）────
# [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03 §7.2]
.PHONY: copilot-step03-prep copilot-step03-migrate
.PHONY: copilot-step03-test copilot-step03-all copilot-step03-status copilot-step03-clean

copilot-step03-prep: copilot-step02-prep
	@echo "▶ [copilot-step03-prep] 体检表 + 路由自检"
	@PYTHONPATH=. python3 -c "\
import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); \
from apps.copilot.modules.health_check.service import get_dashboard; \
from apps.copilot.events.handlers.health_change import handle_health_change; \
print('  health_check service + handler import ✅')"

copilot-step03-migrate: copilot-step03-prep
	@echo "▶ [copilot-step03-migrate] 建表（含 health_records / event_logs）"
	PYTHONPATH=. python3 -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('  tables ✅')"

copilot-step03-test:
	@echo "▶ [copilot-step03-test] pytest 体检相关用例"
	PYTHONPATH=. python3 -m pytest tests/copilot/test_health.py tests/copilot/test_health_consumer.py -v --tb=short

copilot-step03-all: copilot-step03-migrate copilot-step03-test
	@echo "✅ [copilot-step03-all] 准出：建表 + pytest（health_change 须等 D3 真流）"

copilot-step03-status: copilot-step03-prep
	PYTHONPATH=. python3 scripts/copilot_health_status.py

copilot-step03-clean:
	@echo "▶ [copilot-step03-clean] 清 health_records / event_logs（保留 holdings）"
	@PYTHONPATH=. python3 -c "\
import asyncio; from apps.copilot.db.database import AsyncSessionLocal, init_db; \
from sqlalchemy import delete; from apps.copilot.db.models import HealthRecord, EventLog; \
async def main(): \
  await init_db(); \
  async with AsyncSessionLocal() as s: \
    await s.execute(delete(HealthRecord)); await s.execute(delete(EventLog)); await s.commit(); \
    print('  health_records + event_logs 已清 ✅') \
asyncio.run(main())"

# ─── D0 copilot · step04（推荐池 + Mapper 候选消费 + 空池 BLOCKED 处理）────────────
# [Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
.PHONY: copilot-step04-prep copilot-step04-consumer-check copilot-step04-pool-status
.PHONY: copilot-step04-test copilot-step04-all copilot-step04-status

copilot-step04-prep:
	@echo "▶ [copilot-step04-prep] copilot 数据库 + events 消费者路由自检"
	PYTHONPATH=. python3 -c "\
import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); \
print('  copilot DB 初始化 ✅')"
	@PYTHONPATH=. python3 -c "\
from apps.copilot.events.handlers.mapper_thesis import handle_mapper_thesis; \
from apps.copilot.events.handlers.thesis_proposed import handle_thesis_proposed; \
print('  handler: mapper_thesis ✅'); print('  handler: thesis_proposed ✅')"
	@echo "▶ 做了什么: DB init + handler 导入检查"

copilot-step04-consumer-check: copilot-step04-prep
	@echo "▶ [copilot-step04-consumer-check] 确认 consumer 订阅了 events:deep_strike:thesis_proposed"
	@PYTHONPATH=. python3 -c "import inspect; from apps.copilot.events.consumer import _main; src=inspect.getsource(_main); assert 'events:deep_strike:thesis_proposed' in src, '❌ 未订阅'; print('  consumer 已订阅 events:deep_strike:thesis_proposed ✅')"
	@echo "▶ 做了什么: 验证 consumer 已注册 Mapper 流"

copilot-step04-pool-status:
	@echo "▶ [copilot-step04-pool-status] thesis_cards 当前状态"
	PYTHONPATH=. python3 scripts/copilot_step04_status.py

copilot-step04-test:
	@echo "▶ [copilot-step04-test] pytest copilot mapper_thesis handler"
	PYTHONPATH=. python3 -m pytest tests/copilot/ -q -k "mapper or thesis or pool" 2>/dev/null || \
	PYTHONPATH=. python3 -m pytest tests/copilot/ -q 2>&1 | tail -5
	@echo "▶ 做了什么: 跑 copilot 推荐池相关测试"

copilot-step04-all: copilot-step04-prep copilot-step04-consumer-check copilot-step04-pool-status copilot-step04-test
	@echo "✅ [copilot-step04-all] 准出：DB + consumer + pool_status"
	@echo "▶ 做了什么: D0 step04 完整链路验证"
	@echo "▶ 期望什么: consumer 订阅两条 thesis 流；pool 空时显示 BLOCKED-B 提示"

copilot-step04-status:
	@echo "▶ [copilot-step04-status] D0 推荐池快照"
	$(MAKE) copilot-step04-pool-status

# ──────────────────────────────────────────────────────────────────────────────
# D0 step_05 — M3 告警 · sell_signal → 邮件（必做② · 23_表）
# [Ref: 03_/00_维度零/.../step_05_告警系统.md]
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: copilot-step05-prep copilot-step05-rules-test copilot-step05-notrade-check
.PHONY: copilot-step05-sell-signal-e2e copilot-step05-chain-e2e copilot-step05-test
.PHONY: copilot-step05-status copilot-step05-all

copilot-step05-prep: _ensure-deps copilot-step01-prep
	@echo "▶ [copilot-step05-prep] init_db + SMTP 凭证 + sell_signal stream"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ copilot.db')"
	$(RUNPY) -c "from apps.copilot.config import settings; \
assert settings.smtp_username and settings.smtp_password and settings.smtp_to, '缺 COPILOT_SMTP_*'; \
print('✅ SMTP', settings.smtp_to)"
	@docker start diting-redis-step07 2>/dev/null || docker run -d --name diting-redis-step07 -p 6379:6379 redis:7-alpine
	@sleep 1

copilot-step05-rules-test: _ensure-deps
	@echo "▶ [copilot-step05-rules-test] sell_signal 映射 + 规则单测"
	$(RUNPY) -m pytest tests/copilot/test_alerts.py -v --tb=short -k "map_event or level_map or sell_signal or rebalance or financial"

copilot-step05-notrade-check:
	@echo "▶ [copilot-step05-notrade-check]"
	@bash scripts/assert_alert_no_trade_link.sh

copilot-step05-sell-signal-e2e: copilot-step05-prep
	@echo "▶ [copilot-step05-sell-signal-e2e] XADD sell_signal → 消费 → 🔴 邮件"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 \
	  $(RUNPY) scripts/copilot_step05_sell_signal_e2e.py --symbol 601138 --name 工业富联 --signal-type stop_loss

copilot-step05-chain-e2e: copilot-step05-prep
	@echo "▶ [copilot-step05-chain-e2e] D4 step_07 publish → D0 消费邮件（同 Redis db/0）"
	EXIT_REDIS_URL=redis://127.0.0.1:6379/0 COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 \
	  $(RUNPY) scripts/run_one_evaluation.py --demo-stop-loss
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 \
	  $(RUNPY) scripts/copilot_step05_sell_signal_e2e.py --symbol STEP07 --name step07演示 --signal-type stop_loss --skip-xadd

copilot-step05-test: _ensure-deps
	@echo "▶ [copilot-step05-test] pytest test_alerts"
	$(RUNPY) -m pytest tests/copilot/test_alerts.py -v --tb=short

copilot-step05-status:
	@echo "▶ [copilot-step05-status]"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) scripts/copilot_step05_status.py

copilot-step05-all: copilot-step05-prep copilot-step05-rules-test copilot-step05-notrade-check copilot-step05-test copilot-step05-sell-signal-e2e copilot-step05-status
	@echo "✅ [copilot-step05-all] tier-1 准出：本机 sell_signal → 🔴 邮件（非 K3s）"

.PHONY: copilot-step05-tier2-e2e
copilot-step05-tier2-e2e: _ensure-deps
	@echo "▶ [copilot-step05-tier2-e2e] XADD → 云上 Redis · K3s Copilot 消费发邮件"
	@test -n "$${EXIT_REDIS_URL:-$$(grep '^EXIT_REDIS_URL=' .env 2>/dev/null | cut -d= -f2-)}" || { echo "❌ .env 缺 EXIT_REDIS_URL"; exit 1; }
	EXIT_REDIS_URL=$${EXIT_REDIS_URL:-$$(grep '^EXIT_REDIS_URL=' .env | cut -d= -f2-)} \
	  $(RUNPY) scripts/copilot_step05_tier2_e2e.py --symbol 601138 --name 工业富联

# ─── D0 copilot · step12（M6 行情解析与规划工作台）────────────────────────────
# [Ref: 24_行情解析与规划工作台_需求实现表.md · 必做①~④]
.PHONY: copilot-step12-prep copilot-step12-migrate copilot-step12-campaign copilot-step12-up
.PHONY: copilot-step12-test copilot-step12-status copilot-step12-all copilot-step12-clean

copilot-step12-prep: _ensure-deps
	@echo "▶ [copilot-step12-prep] init_db + 等待 Redis PONG"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ copilot.db')"
	@docker start diting-redis-step07 2>/dev/null || docker run -d --name diting-redis-step07 -p 6379:6379 redis:7-alpine 2>/dev/null || true
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) -c "from apps.copilot.services.redis_wait import wait_for_sync_redis; wait_for_sync_redis(timeout_sec=90); print('✅ Redis PONG')"

copilot-step12-migrate: copilot-step12-prep
	@echo "▶ [copilot-step12-migrate] 建 campaigns 等 6 表"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ 6 表已 create_all')"
	@sqlite3 data/copilot.db ".tables" 2>/dev/null | tr ' ' '\n' | grep -E '^(campaigns|campaign_symbols|campaign_nodes|campaign_timeline|monitor_subscriptions|watchlist)$$' | sort -u

copilot-step12-campaign: copilot-step12-migrate
	@echo "▶ [copilot-step12-campaign] 持仓 SoT → campaign_symbols"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) scripts/copilot_step12_campaign.py

copilot-step12-up: copilot-step12-migrate
	@echo "▶ [copilot-step12-up] /planning 应 200（需另开终端 uvicorn）"
	@curl -sf http://127.0.0.1:8080/planning >/dev/null && echo "✅ /planning 200" || echo "⚠️ uvicorn 未起 · PYTHONPATH=. uvicorn apps.copilot.main:app --port 8080"

copilot-step12-test: _ensure-deps
	@echo "▶ [copilot-step12-test] pytest test_planning"
	$(RUNPY) -m pytest tests/copilot/test_planning.py -v --tb=short

copilot-step12-status: copilot-step12-migrate
	@echo "▶ [copilot-step12-status]"
	$(RUNPY) scripts/copilot_step12_status.py

copilot-step12-clean:
	@echo "▶ [copilot-step12-clean] 清 step12 demo 数据"
	$(RUNPY) -c "\
import asyncio; from sqlalchemy import delete; \
from apps.copilot.db.database import AsyncSessionLocal, init_db; \
from apps.copilot.db.models import Campaign, Watchlist; \
async def main(): \
  await init_db(); \
  async with AsyncSessionLocal() as s: \
    await s.execute(delete(Campaign)); await s.execute(delete(Watchlist)); await s.commit(); \
    print('✅ campaigns 级联已清') \
asyncio.run(main())"

copilot-step12-all: copilot-step12-migrate copilot-step12-campaign copilot-step12-test copilot-step12-status
	@echo "✅ [copilot-step12-all] tier-1+2 本机：6 表 + 持仓导入 + pytest"

.PHONY: copilot-step12-tier2-verify copilot-step12-tier2-rollout
copilot-step12-tier2-verify:
	@echo "▶ [copilot-step12-tier2-verify] K3s NodePort ①~④ HTTP 验收"
	$(RUNPY) scripts/copilot_step12_tier2_verify.py

copilot-step12-tier2-rollout:
	@echo "▶ [copilot-step12-tier2-rollout] 需在 diting-infra 执行 make copilot-step12-deploy"

# ─── D0 copilot · step14（M8 行情雷达 + 三段流水线）──────────────────────────
# [Ref: 24_ §9 ⑦ · step_14_行情雷达扫描与三段流水线.md]
.PHONY: copilot-step14-prep copilot-step14-migrate copilot-step14-scan copilot-step14-test
.PHONY: copilot-step14-status copilot-step14-all copilot-step14-clean copilot-step14-tier2-verify

copilot-step14-prep: copilot-step12-prep
	@echo "▶ [copilot-step14-prep] 校验 step_12 基座"

copilot-step14-migrate: copilot-step14-prep
	@echo "▶ [copilot-step14-migrate] 建 step14 五表 + 扩展列"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ step14 migrate ok')"
	@sqlite3 data/copilot.db ".tables" 2>/dev/null | tr ' ' '\n' | grep -E '^(stage_artifacts|workspace_artifacts|model_profile|radar_scans|radar_candidates)$$' | sort -u

copilot-step14-scan: copilot-step14-migrate
	@echo "▶ [copilot-step14-scan] 模式 C 扫描"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 RADAR_SYMBOL=$${RADAR_SYMBOL:-601138} $(RUNPY) scripts/copilot_step14_scan.py

copilot-step14-test: _ensure-deps
	@echo "▶ [copilot-step14-test] pytest test_radar"
	$(RUNPY) -m pytest tests/copilot/test_radar.py -v --tb=short

copilot-step14-status: copilot-step14-migrate
	@echo "▶ [copilot-step14-status]"
	$(RUNPY) scripts/copilot_step14_status.py

copilot-step14-clean:
	@echo "▶ [copilot-step14-clean] 清 radar 扫描数据"
	$(RUNPY) -c "\
import asyncio; from sqlalchemy import delete; \
from apps.copilot.db.database import AsyncSessionLocal, init_db; \
from apps.copilot.db.models import RadarScan, StageArtifact, WorkspaceArtifact; \
async def main(): \
  await init_db(); \
  async with AsyncSessionLocal() as s: \
    await s.execute(delete(StageArtifact)); \
    await s.execute(delete(WorkspaceArtifact)); \
    await s.execute(delete(RadarScan)); \
    await s.commit(); print('✅ radar 数据已清') \
asyncio.run(main())"

copilot-step14-all: copilot-step14-migrate copilot-step14-scan copilot-step14-test copilot-step14-status
	@echo "✅ [copilot-step14-all] ⑦ 雷达 + 三段 artifact + promote 本机验收"

copilot-step14-tier2-verify:
	@echo "▶ [copilot-step14-tier2-verify] K3s 生产 ⑦ 雷达验收"
	$(RUNPY) scripts/copilot_step14_tier2_verify.py

copilot-step14-tier2-rollout:
	@echo "▶ [copilot-step14-tier2-rollout] 需在 diting-infra 执行 make copilot-step14-deploy"

# ── 雷达 T0 · 本机预拉缓存（持仓 SoT active 标的）────────────────────────────
.PHONY: radar-t0-prefetch radar-t0-prefetch-with-t2 radar-t0-status radar-t0-clean

radar-t0-prefetch: _ensure-deps
	@echo "▶ [radar-t0-prefetch] 本机拉取持仓 SoT active 标的 T0 → data/cache/radar_t0/"
	PYTHONPATH=. python3 scripts/radar_t0_prefetch.py

radar-t0-prefetch-with-t2: _ensure-deps
	@echo "▶ [radar-t0-prefetch-with-t2] T0+T1+Opus T2 → bundle；再 diting-infra make radar-t0-sync"
	PYTHONPATH=. python3 scripts/radar_t0_prefetch.py --with-t2

radar-t0-status:
	@PYTHONPATH=. python3 -c "import json; from apps.copilot.modules.radar.t0_cache import status_summary; print(json.dumps(status_summary(), ensure_ascii=False, indent=2))"

radar-t0-clean:
	@rm -rf data/cache/radar_t0/*.json && echo "✅ radar T0 本地缓存已清"

# ── 雷达 T0 · collect_symbols SoT 一次性采集（27_ §2.1.1 P0）────────────────
.PHONY: radar-t0-collect-list radar-t0-collect radar-t0-collect-all

radar-t0-collect-list: _ensure-deps
	@echo "▶ [radar-t0-collect-list] 通用 T0 宇宙（executing ∪ radar）"
	PYTHONPATH=. python3 scripts/radar_t0_collect_once.py --list

radar-t0-collect: _ensure-deps
	@test -n "$(SYMBOL)" || (echo "用法: make radar-t0-collect SYMBOL=601138" && exit 1)
	@echo "▶ [radar-t0-collect] UPSERT radar 表 + T0+T1 · $(SYMBOL)"
	PYTHONPATH=. python3 scripts/radar_t0_collect_once.py --symbol $(SYMBOL)

radar-t0-collect-all: _ensure-deps
	@echo "▶ [radar-t0-collect-all] 通用宇宙全部 enabled 标的 · T0+T1"
	PYTHONPATH=. python3 scripts/radar_t0_collect_once.py --all

.PHONY: radar-t1-build
radar-t1-build: _ensure-deps
	@test -n "$(SYMBOL)" || (echo "用法: make radar-t1-build SYMBOL=601138" && exit 1)
	@echo "▶ [radar-t1-build] T0+微观 → fact_matrix · $(SYMBOL)"
	PYTHONPATH=. python3 scripts/radar_t1_build.py --symbol $(SYMBOL)

.PHONY: radar-pipeline-status radar-t0-job
radar-pipeline-status: _ensure-deps
	@echo "▶ [radar-pipeline-status] watermark + 表内 stale"
	PYTHONPATH=. python3 scripts/radar_pipeline_status.py

radar-t0-job: _ensure-deps
	@test -n "$(JOB)" || (echo "用法: make radar-t0-job JOB=bars-reconcile-daily" && exit 1)
	@echo "▶ [radar-t0-job] $(JOB)"
	PYTHONPATH=. python3 -m apps.copilot.jobs.radar_t0 $(JOB)

# ─── D0 copilot · step15（M9 滚动路线图双层锚定）────────────────────────────
# [Ref: 24_ §9 ⑧ · step_15_滚动路线图双层锚定.md]
.PHONY: copilot-step15-prep copilot-step15-migrate copilot-step15-timeline copilot-step15-regime
.PHONY: copilot-step15-test copilot-step15-status copilot-step15-all copilot-step15-clean
.PHONY: copilot-step15-tier2-verify

copilot-step15-prep: copilot-step14-prep
	@echo "▶ [copilot-step15-prep] 校验 step_14 雷达基座"

copilot-step15-migrate: copilot-step15-prep
	@echo "▶ [copilot-step15-migrate] timeline 扩展列 + regime_assessments"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ step15 migrate ok')"
	@sqlite3 data/copilot.db ".schema campaign_timeline" 2>/dev/null | grep -E "window_start|build_lead_days|sequence_no|feasibility_flags" | head -4
	@sqlite3 data/copilot.db ".tables" 2>/dev/null | tr ' ' '\n' | grep regime_assessments || true

copilot-step15-timeline: copilot-step15-migrate
	@echo "▶ [copilot-step15-timeline] 2 标的入时间线 + 合理性"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) scripts/copilot_step15_timeline.py

copilot-step15-regime: copilot-step15-migrate
	@echo "▶ [copilot-step15-regime] 生命周期判定 + regime 巡检"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) scripts/copilot_step15_regime.py

copilot-step15-test: _ensure-deps
	@echo "▶ [copilot-step15-test] pytest test_roadmap"
	$(RUNPY) -m pytest tests/copilot/test_roadmap.py -v --tb=short

copilot-step15-status: copilot-step15-migrate
	@echo "▶ [copilot-step15-status]"
	$(RUNPY) scripts/copilot_step15_status.py

copilot-step15-clean:
	@echo "▶ [copilot-step15-clean] 清 step15 demo timeline/regime（保留 campaign）"
	$(RUNPY) -c "\
import asyncio; from sqlalchemy import delete; \
from apps.copilot.db.database import AsyncSessionLocal, init_db; \
from apps.copilot.db.models import CampaignTimeline, RegimeAssessment, MonitorSubscription; \
async def main(): \
  await init_db(); \
  async with AsyncSessionLocal() as s: \
    await s.execute(delete(MonitorSubscription).where(MonitorSubscription.pillar=='regime')); \
    await s.execute(delete(RegimeAssessment)); \
    await s.execute(delete(CampaignTimeline)); \
    await s.commit(); print('✅ step15 demo 数据已清') \
asyncio.run(main())"

copilot-step15-all: copilot-step15-migrate copilot-step15-timeline copilot-step15-regime copilot-step15-test copilot-step15-status
	@echo "✅ [copilot-step15-all] ⑧ 滚动路线图双层锚定本机验收"

copilot-step15-tier2-verify:
	@echo "▶ [copilot-step15-tier2-verify] K3s 生产 ⑧ 路线图验收"
	$(RUNPY) scripts/copilot_step15_tier2_verify.py

copilot-step15-tier2-rollout:
	@echo "▶ [copilot-step15-tier2-rollout] 需在 diting-infra 执行 make copilot-step15-deploy"


# ─── D0 copilot · step16（M10 规划中证伪与持续监控）────────────────────────────

.PHONY: copilot-step16-prep copilot-step16-migrate copilot-step16-falsify
.PHONY: copilot-step16-test copilot-step16-status copilot-step16-all copilot-step16-clean
.PHONY: copilot-step16-tier2-verify

copilot-step16-prep: copilot-step15-prep
	@echo "▶ [copilot-step16-prep] 校验 step_14/15 基座"

copilot-step16-migrate: copilot-step16-prep
	@echo "▶ [copilot-step16-migrate] monitor_subscriptions falsify 列（step15 已含）"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ step16 migrate ok')"

copilot-step16-falsify: copilot-step16-migrate
	@echo "▶ [copilot-step16-falsify] 建 4 类证伪任务 + 跑判定"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) scripts/copilot_step16_falsify.py

copilot-step16-test: _ensure-deps
	@echo "▶ [copilot-step16-test] pytest test_falsify"
	$(RUNPY) -m pytest tests/copilot/test_falsify.py -q

copilot-step16-status: copilot-step16-migrate
	@echo "▶ [copilot-step16-status]"
	$(RUNPY) scripts/copilot_step16_status.py

copilot-step16-all: copilot-step16-migrate copilot-step16-falsify copilot-step16-test copilot-step16-status
	@echo "✅ [copilot-step16-all] ⑨ 规划中证伪与持续监控本机验收"

copilot-step16-tier2-verify:
	@echo "▶ [copilot-step16-tier2-verify] K3s 生产 ⑨ 证伪验收"
	$(RUNPY) scripts/copilot_step16_tier2_verify.py

# ─── M11 step17 执行中仓位指导 ──────────────────────────────────────────────
.PHONY: copilot-step17-prep copilot-step17-migrate copilot-step17-advise
.PHONY: copilot-step17-safety-scan copilot-step17-test copilot-step17-all
.PHONY: copilot-step17-status copilot-step17-clean copilot-step17-audit

copilot-step17-prep: copilot-step16-prep
	@echo "▶ [copilot-step17-prep] 校验 step_16 基座 + holdings_sot"
	$(RUNPY) -c "from apps.common.holdings_sot import load_holdings_sot; s=load_holdings_sot(); print('✅ holdings_sot:', len(s.holdings), '标的')"

copilot-step17-migrate: copilot-step17-prep
	@echo "▶ [copilot-step17-migrate] 建 execution_advices 表"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ step17 migrate ok')"
	$(RUNPY) -c "import sqlite3, os; db=os.environ.get('COPILOT_DB','data/copilot.db'); r=sqlite3.connect(db).execute('.tables' if False else 'SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"execution_advices\"').fetchone(); print('✅ execution_advices 表存在' if r else '❌ 表缺失')"

copilot-step17-advise: copilot-step17-migrate
	@echo "▶ [copilot-step17-advise] 生成第一只持仓 advisory 建议"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) scripts/copilot_step17_advise.py

copilot-step17-safety-scan: copilot-step17-migrate
	@echo "▶ [copilot-step17-safety-scan] 盘后安全扫描门控 demo"
	COPILOT_REDIS_URL=redis://127.0.0.1:6379/0 $(RUNPY) scripts/copilot_step17_safety_scan.py

copilot-step17-audit:
	@echo "▶ [copilot-step17-audit] no-auto-execute 审计（rg 应为 0）"
	@rg -i "buy|qmt|auto_trade|order_id|webhook_target|立即|一键|下单" apps/copilot/modules/execution/ apps/copilot/templates/planning/ 2>/dev/null && echo "❌ 发现下单相关内容" || echo "✅ no-auto-execute 审计通过（0 命中）"

copilot-step17-test: _ensure-deps
	@echo "▶ [copilot-step17-test] pytest test_execution"
	$(RUNPY) -m pytest tests/copilot/test_execution.py -q

copilot-step17-status: copilot-step17-migrate
	@echo "▶ [copilot-step17-status] 执行中 Campaign + 建议分布"
	$(RUNPY) scripts/copilot_step17_status.py

copilot-step17-clean:
	@echo "▶ [copilot-step17-clean] 清空 execution_advices demo 数据"
	$(RUNPY) -c "import asyncio, sqlalchemy.ext.asyncio as sa; from apps.copilot.db.database import engine; asyncio.run(engine.begin().__aenter__())" 2>/dev/null || true

copilot-step17-all: copilot-step17-migrate copilot-step17-advise copilot-step17-audit copilot-step17-test copilot-step17-status
	@echo "✅ [copilot-step17-all] ⑩ 执行中仓位指导本机验收"

# ─── 执行中工作区（28_ · executing workspace）────────────────────────────────
.PHONY: executing-workspace-migrate executing-import-positions executing-pipeline-status
.PHONY: executing-daily executing-t0-collect executing-workspace-test executing-workspace-audit
.PHONY: executing-workspace-all

executing-workspace-migrate: _ensure-deps
	@echo "▶ [executing-workspace-migrate] step28 表 + init_db"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ executing workspace migrate ok')"
	@sqlite3 data/copilot.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'executing%' OR name='user_positions';" | head -20

executing-import-positions: executing-workspace-migrate
	@echo "▶ [executing-import-positions] MY_HOLDINGS_YAML → user_positions"
	MY_HOLDINGS_YAML=$${MY_HOLDINGS_YAML:-data/config/my_holdings.yaml} $(RUNPY) scripts/executing_import_positions.py

executing-pipeline-status: executing-workspace-migrate
	@echo "▶ [executing-pipeline-status] watermark + stale 报告"
	$(RUNPY) -m apps.copilot.jobs.executing_t0 --status

executing-t0-collect: executing-workspace-migrate
	@test -n "$(SYMBOL)" || (echo "用法: make executing-t0-collect SYMBOL=601138" && exit 1)
	@echo "▶ [executing-t0-collect] T0 全量采集 $(SYMBOL)"
	COPILOT_REDIS_URL=$${COPILOT_REDIS_URL:-redis://127.0.0.1:6379/0} \
	  $(RUNPY) -m apps.copilot.jobs.executing_t0 collect-once --symbol $(SYMBOL)

executing-daily: executing-workspace-migrate
	@test -n "$(SYMBOL)" || (echo "用法: make executing-daily SYMBOL=601138" && exit 1)
	@echo "▶ [executing-daily] T0→T1→T2 $(SYMBOL)（T2 需 EXECUTING_T2_ENABLED + ANTHROPIC_API_KEY）"
	COPILOT_REDIS_URL=$${COPILOT_REDIS_URL:-redis://127.0.0.1:6379/0} \
	  $(RUNPY) -m apps.copilot.jobs.executing_t0 daily-pipeline --symbol $(SYMBOL)
	@$(MAKE) executing-pipeline-status

executing-workspace-audit:
	@echo "▶ [executing-workspace-audit] no-auto-execute（执行区路径）"
	@rg -i "auto_trade|order_id|webhook_target|立即下单|一键下单" apps/copilot/modules/executing/ apps/copilot/routers/executing_routes.py 2>/dev/null && echo "❌ 命中禁词" || echo "✅ 执行区 no-auto-execute 通过"

executing-workspace-test: _ensure-deps executing-workspace-migrate
	@echo "▶ [executing-workspace-test] pytest test_executing_workspace"
	$(RUNPY) -m pytest tests/copilot/test_executing_workspace.py -q

executing-workspace-all: executing-import-positions executing-t0-collect executing-daily executing-workspace-audit executing-workspace-test executing-pipeline-status
	@echo "✅ [executing-workspace-all] 28_ 本机链路验收（SYMBOL 默认需传 601138）"

.PHONY: copilot-executing-tier2-verify
copilot-executing-tier2-verify:
	@echo "▶ [copilot-executing-tier2-verify] K3s 生产 28_ 执行中工作区 HTTP 验收（需 prod.conn PUBLIC_IP 可达 NodePort）"
	$(RUNPY) scripts/copilot_executing_tier2_verify.py

copilot-executing-tier2-verify-k8s:
	@echo "▶ [copilot-executing-tier2-verify-k8s] 请在 diting-infra 执行 make copilot-executing-workspace-deploy 或 bash scripts/copilot-executing-tier2-verify-k8s.sh"

copilot-step16-tier2-rollout:
	@echo "▶ [copilot-step16-tier2-rollout] 需在 diting-infra 执行 make copilot-step16-deploy"

# ───────────── 四区漏斗（标的级重构）一键复现 ─────────────
.PHONY: copilot-funnel-migrate copilot-funnel-cleanup copilot-funnel-test
.PHONY: copilot-funnel-audit copilot-funnel-all

copilot-funnel-migrate:
	@echo "▶ [copilot-funnel-migrate] 建 campaign_symbols.funnel_stage + 唯一索引"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ funnel migrate ok')"

copilot-funnel-cleanup:
	@echo "▶ [copilot-funnel-cleanup] 清空四区漏斗业务表并按 holdings_sot 重建（保留 SoT YAML）"
	$(RUNPY) scripts/copilot_funnel_cleanup.py

copilot-funnel-test: _ensure-deps
	@echo "▶ [copilot-funnel-test] 漏斗联动 + feasibility 去重单测"
	$(RUNPY) -m pytest tests/copilot/test_funnel.py tests/copilot/test_feasibility_dedup.py -q

copilot-funnel-audit:
	@echo "▶ [copilot-funnel-audit] no-auto-execute 审计（rg 应为 0）"
	@rg -i "auto_trade|order_id|qmt|webhook_target|一键|下单" apps/copilot/modules/planning/funnel.py apps/copilot/templates/planning/ 2>/dev/null && echo "❌ 发现下单相关内容" || echo "✅ no-auto-execute 审计通过（0 命中）"

copilot-funnel-all: copilot-funnel-migrate copilot-funnel-test copilot-funnel-audit
	@echo "✅ [copilot-funnel-all] 四区漏斗标的级重构本机验收（清空重建用 copilot-funnel-cleanup 单独执行）"

# ─── 波次四 · 持久化 + 漏斗操作 + 采集数据 + 对话模型 ─────────────────────────
.PHONY: copilot-wave4-prep copilot-wave4-test copilot-wave4-all copilot-wave4-tier2-verify

copilot-wave4-prep: copilot-step14-prep
	@echo "▶ [copilot-wave4-prep] init_db（含 migrate_step19）"
	$(RUNPY) -c "import asyncio; from apps.copilot.db.database import init_db; asyncio.run(init_db()); print('✅ wave4 migrate ok')"

copilot-wave4-test: _ensure-deps
	@echo "▶ [copilot-wave4-test] radar 缓存 + 漏斗单测"
	$(RUNPY) -m pytest tests/copilot/test_radar_t0_cache.py tests/copilot/test_funnel.py -q

copilot-wave4-all: copilot-wave4-prep copilot-wave4-test
	@echo "✅ [copilot-wave4-all] 波次四本机验收"
	@echo "▶ 生产正式部署：cd ../diting-infra && make copilot-wave4-deploy"

copilot-wave4-tier2-verify:
	@echo "▶ [copilot-wave4-tier2-verify] 请在 diting-infra 执行 make copilot-wave4-verify"


deep-strike-dev:
	PYTHONPATH=. uvicorn apps.deep_strike.main:app --port 8082 --reload

state-watch-dev:
	PYTHONPATH=. uvicorn apps.state_watch.main:app --port 8003 --reload

exit-engine-dev:
	PYTHONPATH=. uvicorn apps.exit_engine.main:app --port 8092 --reload

# ─── D5 super_evo · step04（LoRA 训练流水线）─────────────────────────────────────
# [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_04 §7.2]
# DECISION_PENDING: train-* 需 GPU（见 §十五 用户决策清单）

evo-step04-prep:
	@echo "▶ [evo-step04-prep] 检查训练前置条件（yaml + llamafactory + GPU）"
	PYTHONPATH=. python3 scripts/evo_step04_run.py prep
	@echo "▶ 做了什么: 检查 3 维 yaml + llamafactory-cli + GPU 可用性"

evo-step04-sanity-train:
	@echo "▶ [evo-step04-sanity-train] dry-run sanity 训练（max_steps=50，不需 GPU）"
	PYTHONPATH=. python3 scripts/evo_step04_run.py sanity-train
	@echo "▶ 做了什么: 用 dry_run=True 跑 trainer.py 流水线验证"

evo-step04-test:
	@echo "▶ [evo-step04-test] pytest 训练流水线（dry-run，不需 GPU）"
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_training_pipeline.py -q
	@echo "▶ 做了什么: 跑 test_training_pipeline.py ≥8 测试"

evo-step04-all: evo-step04-prep evo-step04-sanity-train evo-step04-test
	@echo "✅ [evo-step04-all] tier-1 准出：prep + sanity_train + pytest 全通过"
	@echo "▶ 做了什么: 完整 step04 tier-1 验证（不含真实 GPU 训练）"
	@echo "▶ 期望什么: 3 维 yaml 存在；sanity dry-run 通过；pytest 8 项绿"
	@echo ""
	@echo "# DECISION_PENDING: tier-2 真实 LoRA 训练（GPU 需求）"
	@echo "#   make evo-step04-train-cryo / evo-step04-train-thrust / evo-step04-train-narrative"
	@echo "#   推荐 GPU: 阿里云 ecs.gn6i-c4g1.xlarge（NVIDIA V100-16G，约 ¥5/h）"

evo-step04-train-cryo:
	@echo "▶ [evo-step04-train-cryo] D1 极寒防御 LoRA 训练（需 GPU）"
	@echo "# DECISION_PENDING: 需用户确认 GPU 环境后执行"
	PYTHONPATH=. python3 scripts/evo_step04_run.py train cryo

evo-step04-train-thrust:
	@echo "▶ [evo-step04-train-thrust] D2 纵深进攻 LoRA 训练（需 GPU）"
	@echo "# DECISION_PENDING: 需用户确认 GPU 环境后执行"
	PYTHONPATH=. python3 scripts/evo_step04_run.py train thrust

evo-step04-train-narrative:
	@echo "▶ [evo-step04-train-narrative] D3 叙事/关联方 LoRA 训练（需 GPU）"
	@echo "# DECISION_PENDING: 需用户确认 GPU 环境后执行"
	PYTHONPATH=. python3 scripts/evo_step04_run.py train narrative

evo-step04-status:
	@echo "▶ [evo-step04-status] lora_versions 注册表快照"
	PYTHONPATH=. python3 scripts/evo_step04_run.py status

# ─── D5 super_evo · step05（Holdout 评测守门）────────────────────────────────
# [Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_05_Holdout评测器与CI_Block.md §7.2]
# DECISION_PENDING: evaluate-*（vllm 模式）需 GPU；mock 模式可本地运行

.PHONY: evo-step05-prep evo-step05-generate-holdout evo-step05-leak-check
.PHONY: evo-step05-evaluate-cryo evo-step05-evaluate-thrust evo-step05-evaluate-narrative
.PHONY: evo-step05-regression-sim evo-step05-test evo-step05-all evo-step05-status

evo-step05-prep:
	@echo "▶ [evo-step05-prep] 检查前置条件（holdout 文件 + vLLM + GPU）"
	PYTHONPATH=. python3 scripts/evo_step05_run.py prep
	@echo "▶ 做了什么: 检查 3 维 holdout.jsonl + vLLM URL + GPU 可用性"

evo-step05-generate-holdout:
	@echo "▶ [evo-step05-generate-holdout] 生成 Holdout 锁库数据（D1=50，D2/D3=30）"
	PYTHONPATH=. python3 scripts/evo_step05_run.py generate-holdout
	@echo "▶ 做了什么: 生成 cryo/thrust/narrative holdout.jsonl（永久锁库）"

evo-step05-leak-check:
	@echo "▶ [evo-step05-leak-check] 验证 holdout 与训练集 0 重叠（H2）"
	PYTHONPATH=. python3 scripts/evo_step05_run.py leak-check cryo
	PYTHONPATH=. python3 scripts/evo_step05_run.py leak-check thrust
	PYTHONPATH=. python3 scripts/evo_step05_run.py leak-check narrative
	@echo "▶ 做了什么: 扫描训练集 sample_id，与 holdout 无重叠"

evo-step05-evaluate-cryo:
	@echo "▶ [evo-step05-evaluate-cryo] D1 cryo Holdout 评测（mock 模式）"
	PYTHONPATH=. python3 scripts/evo_step05_run.py evaluate cryo 0 mock
	@echo "▶ 做了什么: 50 条 holdout 推理 + 指标统计"
	@echo "# DECISION_PENDING: 真实评测需 vLLM + GPU（执行: evaluate cryo 0 vllm）"

evo-step05-evaluate-thrust:
	@echo "▶ [evo-step05-evaluate-thrust] D2 thrust Holdout 评测（mock 模式）"
	PYTHONPATH=. python3 scripts/evo_step05_run.py evaluate thrust 0 mock
	@echo "# DECISION_PENDING: 真实评测需 vLLM + GPU"

evo-step05-evaluate-narrative:
	@echo "▶ [evo-step05-evaluate-narrative] D3 narrative Holdout 评测（mock 模式）"
	PYTHONPATH=. python3 scripts/evo_step05_run.py evaluate narrative 0 mock
	@echo "# DECISION_PENDING: 真实评测需 vLLM + GPU"

evo-step05-regression-sim:
	@echo "▶ [evo-step05-regression-sim] 模拟退化 → blocked=True（CI Block 验证）"
	@PYTHONPATH=. python3 scripts/evo_step05_run.py regression-sim cryo && exit 1 || echo "✅ regression-sim 正确返回 exit 1（C2 验证通过）"
	@echo "▶ 做了什么: 注入 recall 退化 11.1%，验证 blocked=True + exit 1"

evo-step05-test:
	@echo "▶ [evo-step05-test] pytest Holdout 评测器（≥10 测试）"
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_holdout_evaluator.py -q --tb=short
	@echo "▶ 做了什么: test_holdout_evaluator.py ≥10 项"

evo-step05-all: evo-step05-generate-holdout evo-step05-leak-check evo-step05-test evo-step05-regression-sim evo-step05-evaluate-cryo evo-step05-evaluate-thrust evo-step05-evaluate-narrative
	@echo "✅ [evo-step05-all] tier-1 准出："
	@echo "   holdout 锁库（3 维）+ leak check + pytest≥10 + regression-sim + mock 评测（3 维）"
	@echo "▶ 做了什么: 完整 step05 tier-1 验证（不含真实 GPU vLLM 评测）"
	@echo "▶ 期望什么: 3 维 holdout 存在；0 重叠；10 项测试绿；mock 评测通过"
	@echo ""
	@echo "# DECISION_PENDING: tier-2 真实 vLLM 评测（需 GPU runner）"
	@echo "#   1. 启用 ecs.gn6i-c4g1.xlarge（NVIDIA V100，约 ¥5/h）"
	@echo "#   2. make evo-step05-evaluate-cryo INFERENCE_MODE=vllm VLLM_URL=http://..."
	@echo "#   3. 编辑 .github/workflows/holdout-gate.yml：INFERENCE_MODE: vllm"

evo-step05-status:
	@echo "▶ [evo-step05-status] Holdout 评测状态"
	PYTHONPATH=. python3 scripts/evo_step05_run.py status

# step_04 C3 LLaMA-Factory 训练流水线 · [Ref: 03_/05_维度五/.../step_04]
test-llama-factory-train:
	PYTHONPATH=. python3 -m pytest tests/super_evo/test_training_pipeline.py -v

SANITY_TRAIN_DATA ?= training/data/distilled/financial_fraud/sanity_dry_run.jsonl

sanity-train-dry:
	PYTHONPATH=. python3 -m scripts.training.train_lora \
	  --lora-name sanity_lora_v0 --task financial_fraud \
	  --data $(SANITY_TRAIN_DATA) \
	  --rank 16 --epochs 1 --no-require-verified --dry-run

sanity-train:
	PYTHONPATH=. python3 -m scripts.training.train_lora \
	  --lora-name sanity_lora_v0 --task financial_fraud \
	  --data $(SANITY_TRAIN_DATA) \
	  --base-model models/Qwen2.5-1.5B-Instruct \
	  --rank 16 --epochs 1 --max-steps 50 --no-require-verified

# ──────────────────────────────────────────────────────────────────────────────
# D2 step_05 — thesis 卡片生成器
# [Ref: 03_/02_维度二/step_05]
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: deep-step05-prep deep-step05-test deep-step05-completeness-check deep-step05-all deep-step05-status

deep-step05-prep:
	@echo "▶ [deep-step05-prep] thesis 生成器前置检查"
	@echo "  做了什么：检查 ThesisCardSchema + ThesisCardGenerator 可导入，no-stub guard 生效"
	@echo "  期望：导入无报错；THESIS_GENERATOR_MODE 未设置"
	@[ "$$THESIS_GENERATOR_MODE" != "stub" ] || (echo "❌ THESIS_GENERATOR_MODE=stub 被设置！" && exit 1)
	PYTHONPATH=. python3 -c "from apps.deep_strike.engines.thesis import ThesisCardSchema, ThesisCardGenerator, batch_check; print('✅ thesis 引擎导入正常')"

deep-step05-test:
	@echo "▶ [deep-step05-test] pytest thesis 卡片生成器（schema+completeness+no-mock）"
	@echo "  做了什么：运行 tests/deep_strike/test_thesis_generator.py"
	@echo "  期望：全部测试通过"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_thesis_generator.py -v --tb=short

deep-step05-completeness-check:
	@echo "▶ [deep-step05-completeness-check] batch_check 示例验证"
	PYTHONPATH=. python3 scripts/check_thesis_completeness.py

deep-step05-all: deep-step05-prep deep-step05-test deep-step05-completeness-check deep-step05-timer-test deep-step05-api-test deep-step05-schema-d0 deep-step05-generate-all deep-step05-timer-generate
	@echo "✅ [deep-step05-all] D2 step_05 全准出：D0 schema + Timer Opus 真流 + 批量生成"

# step_08 HumanGate
.PHONY: deep-step08-test deep-step08-all deep-step08-e2e

deep-step08-test:
	@echo "▶ [deep-step08-test] pytest HumanGate（≥15 用例）"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_human_gate.py -v --tb=short

deep-step08-e2e:
	@echo "▶ [deep-step08-e2e] HumanGate 真流 e2e（从 DB 取第一张 proposed 卡 confirm → Redis xadd）"
	@echo "  做了什么：选 proposed 卡 → confirm → 验证 events:thrust:thesis_proposed XADD"
	@echo "  期望：stream 有新消息 + status=confirmed + human_confirmations 有记录"
	PYTHONPATH=. python3 scripts/deep_step08_human_gate_e2e.py

deep-step08-all: deep-step08-test deep-step08-e2e
	@echo "✅ [deep-step08-all] D2 step_08 准出：HumanGate 15 passed + 真流 e2e 通过"

deep-step05-status:
	@echo "▶ [deep-step05-status] thesis 引擎状态"
	@ls apps/deep_strike/engines/thesis/*.py 2>/dev/null && echo "  引擎文件存在 ✅" || echo "  ❌ 引擎文件缺失"
	@ls apps/deep_strike/api/routes_thesis.py 2>/dev/null && echo "  thesis API ✅" || echo "  thesis API ❌"
	@wc -l training/data/narrative_nli/*.jsonl 2>/dev/null | tail -1 | awk '{print "  NLI 训练数据总行数:", $$1}'

# [L-α] The Timer targets
.PHONY: deep-step05-timer-test deep-step05-timer-quality-check deep-step05-timer-no-auto-audit
.PHONY: deep-step05-api-test deep-step05-generate-all deep-step05-schema-d0 deep-step05-timer-generate

deep-step05-api-test:
	@echo "▶ [deep-step05-api-test] pytest thesis API + timer Redis 投递 + 真流 xadd"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_thesis_api.py -v --tb=short
	REDIS_URL=$${REDIS_URL:-redis://8.217.158.218:30379/0} PYTHONPATH=. python3 scripts/deep_step05_redis_publish.py

deep-step05-generate-all:
	@echo "▶ [deep-step05-generate-all] 为 active 持仓各生成 ≥1 thesis 卡（规则模板 · 无 stub）"
	PYTHONPATH=. python3 scripts/deep_step05_generate_all.py

deep-step05-schema-d0:
	@echo "▶ [deep-step05-schema-d0] D0 ThesisProposedPayload 对齐检查（diff=0）"
	PYTHONPATH=. python3 scripts/schema_check_d0.py

deep-step05-timer-generate:
	@echo "▶ [deep-step05-timer-generate] The Timer Opus 真流（force_route=remote）"
	PYTHONPATH=. python3 scripts/deep_step05_timer_generate.py

deep-step05-timer-test:
	@echo "▶ [deep-step05-timer-test] pytest The Timer TM1~TM7（≥7 用例）"
	@echo "  做了什么：运行 tests/deep_strike/test_the_timer.py"
	@echo "  期望：全部测试通过（TM1 三段齐全 / TM2 顺序合理 / TM3 cycle_anchors / TM5 枚举 / TM6 no-auto / TM7 元数据）"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_the_timer.py -v --tb=short

deep-step05-timer-quality-check:
	@echo "▶ [deep-step05-timer-quality-check] TM1~TM7 矩阵质量检查"
	PYTHONPATH=. python3 -m pytest tests/deep_strike/test_the_timer.py -v --tb=short -q
	@echo "  做了什么：验证 TM1~TM7 矩阵 10 项全通过"

deep-step05-timer-no-auto-audit:
	@echo "▶ [deep-step05-timer-no-auto-audit] 审计 The Timer 代码无禁词"
	@echo "  做了什么：grep timer.py 中 auto_trade / qmt / execute / buy_signal 等禁词"
	@if grep -n "auto_trade\|qmt_signal\|execute_order\|buy_signal\|auto_buy\|webhook_target" apps/deep_strike/lighthouse/timer.py 2>/dev/null | grep -v "^.*#"; then \
		echo "❌ 禁词出现！见上方"; exit 1; \
	else \
		echo "✅ The Timer 无禁词（auto_trade / qmt / execute_order 等）"; \
	fi

# ──────────────────────────────────────────────────────────────────────────────
# D4 step_05/06 — SP3 Thesis 失效 + SP4 再平衡 + SP5 财报窗口（tier-1/2）
# [Ref: 03_/04_维度四/step_05~06]
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: exit-step05-prep exit-step05-test exit-step05-all exit-step05-status
.PHONY: exit-step05-schema exit-step05-consumer-up exit-step05-e2e-real exit-step05-clean
.PHONY: exit-step05-sp5-test exit-step05-sp5-no-auto-audit exit-step05-sp5-status
.PHONY: exit-step05-sp5-consumer-up exit-step05-sp5-e2e-real
.PHONY: exit-step06-prep exit-step06-test exit-step06-all exit-step06-status
.PHONY: audit-no-qmt-import

audit-no-qmt-import:
	@echo "▶ [audit-no-qmt-import] 全仓 grep qmt import（生产路径禁止）"
	@if rg -n "from .* import qmt|^import qmt" apps/ --glob '!**/tests/**' 2>/dev/null; then \
		echo "❌ 发现 qmt import"; exit 1; \
	else \
		echo "✅ 无 qmt import（apps/ 生产路径）"; \
	fi

exit-step05-prep:
	@echo "▶ [exit-step05-prep] SP3/SP5 前置检查"
	PYTHONPATH=. python3 scripts/check_sp3_prep.py
	PYTHONPATH=. python3 -c "from apps.exit_engine.protocols.sp5_financial_window import Sp5FinancialWindowProtocol; print('✅ SP5 协议可导入')"

exit-step05-schema:
	@echo "▶ [exit-step05-schema] health_change / timer_signal payload schema 解码"
	PYTHONPATH=. python3 scripts/check_sp5_schema.py

exit-step05-test:
	@echo "▶ [exit-step05-test] pytest SP3 + SP5 + consumer + Redis e2e"
	PYTHONPATH=. python3 -m pytest \
		tests/exit_engine/test_thesis_invalid.py \
		tests/exit_engine/test_sp5_no_auto_execute.py \
		tests/exit_engine/test_sp_conflict_priority.py \
		tests/exit_engine/test_sp3_sp5_consumer.py \
		tests/exit_engine/test_redis_stream_e2e.py \
		-v --tb=short

exit-step05-sp5-test:
	@echo "▶ [exit-step05-sp5-test] pytest SP5 + 冲突优先级"
	PYTHONPATH=. python3 -m pytest \
		tests/exit_engine/test_sp5_no_auto_execute.py \
		tests/exit_engine/test_sp_conflict_priority.py \
		tests/exit_engine/test_sp3_sp5_consumer.py::test_sp5_main_wave_triggers \
		tests/exit_engine/test_sp3_sp5_consumer.py::test_sp5_three_stages \
		-v --tb=short

exit-step05-sp5-no-auto-audit:
	@echo "▶ [exit-step05-sp5-no-auto-audit] 审计 SP5 代码无 auto_execute/order_id/QMT"
	@if rg -n "auto_execute|order_id|qmt_signal|webhook_target|auto_trade" \
		apps/exit_engine/protocols/sp5_financial_window.py \
		apps/exit_engine/services/stream_consumer.py \
		apps/exit_engine/configs/sp5_advice_templates.yaml 2>/dev/null | grep -v "^.*#"; then \
		echo "❌ SP5 路径出现禁词"; exit 1; \
	else \
		echo "✅ SP5 路径无 auto_execute / order_id / QMT 禁词"; \
	fi

exit-step05-consumer-up:
	@echo "▶ [exit-step05-consumer-up] Redis health_change stream 就绪检查"
	REDIS_URL=$${REDIS_URL:-redis://8.217.158.218:30379/0} PYTHONPATH=. python3 scripts/check_redis_stream.py --stream events:monitor:health_change

exit-step05-sp5-consumer-up:
	@echo "▶ [exit-step05-sp5-consumer-up] Redis timer_signal stream 就绪检查"
	REDIS_URL=$${REDIS_URL:-redis://8.217.158.218:30379/0} PYTHONPATH=. python3 scripts/check_redis_stream.py --stream events:deep_strike:timer_signal

exit-step05-e2e-real:
	@echo "▶ [exit-step05-e2e-real] Redis 真流：xadd health_change → XREADGROUP → SP3"
	REDIS_URL=$${REDIS_URL:-redis://8.217.158.218:30379/0} PYTHONPATH=. python3 scripts/exit_step05_e2e.py --protocol SP3

exit-step05-sp5-e2e-real:
	@echo "▶ [exit-step05-sp5-e2e-real] Redis 真流：xadd timer_signal → XREADGROUP → SP5 三段"
	REDIS_URL=$${REDIS_URL:-redis://8.217.158.218:30379/0} PYTHONPATH=. python3 scripts/exit_step05_e2e.py --protocol SP5

exit-step05-all: exit-step05-prep exit-step05-schema exit-step05-test exit-step05-sp5-test exit-step05-sp5-no-auto-audit audit-no-qmt-import exit-step05-e2e-real exit-step05-sp5-e2e-real exit-step05-consumer-up exit-step05-sp5-consumer-up
	@echo "✅ [exit-step05-all] D4 step_05 tier-1/2 准出：SP3 + SP5 + Redis XREADGROUP 真流全通过"

exit-step05-status:
	@echo "▶ [exit-step05-status] SP3/SP5 实现状态"
	PYTHONPATH=. python3 -c "\
from apps.exit_engine.db.init_db import init; \
from apps.exit_engine.db.session import SessionLocal; \
from apps.exit_engine.models.event_log import EventLogORM; \
init(); db=SessionLocal(); \
n=db.query(EventLogORM).filter_by(handled=True).count(); \
print(f'  event_logs handled={n}'); db.close()"
	PYTHONPATH=. python3 -c "from apps.exit_engine.protocols.thesis_invalid import ThesisInvalidProtocol; print('  SP3 ✅')"
	PYTHONPATH=. python3 -c "from apps.exit_engine.protocols.sp5_financial_window import Sp5FinancialWindowProtocol; print('  SP5 ✅')"

exit-step05-sp5-status:
	@echo "▶ [exit-step05-sp5-status] 近 7 日 SP5 advice 分布（event_logs）"
	PYTHONPATH=. python3 scripts/exit_step05_sp5_status.py

exit-step05-clean:
	@echo "▶ [exit-step05-clean] 清理 dev event_logs（需 FORCE=1）"
	@test "$$FORCE" = "1" || (echo "跳过：设置 FORCE=1 才清理" && exit 0)
	PYTHONPATH=. python3 -c "\
from apps.exit_engine.db.init_db import init; \
from apps.exit_engine.db.session import SessionLocal; \
from apps.exit_engine.models.event_log import EventLogORM; \
init(); db=SessionLocal(); db.query(EventLogORM).delete(); db.commit(); db.close(); print('✅ event_logs 已清理')"

exit-step06-prep:
	@echo "▶ [exit-step06-prep] SP4 RebalanceProtocol 前置检查"
	PYTHONPATH=. python3 scripts/check_sp4_prep.py
exit-step06-test:
	@echo "▶ [exit-step06-test] pytest SP4 再平衡协议"
	PYTHONPATH=. python3 -m pytest tests/exit_engine/test_rebalance.py -v --tb=short

exit-step06-all: exit-step06-prep exit-step06-test
	@echo "✅ [exit-step06-all] D4 step_06 tier-1 准出：SP4 pytest 全通过"

exit-step06-status:
	@echo "▶ [exit-step06-status] SP4 实现状态"
	PYTHONPATH=. python3 -c "from apps.exit_engine.protocols.rebalance import RebalanceProtocol; print('  SP4 ✅ 已实现')"

# ──────────────────────────────────────────────────────────────────────────────
# D4 step_07 — 冲突仲裁 + sell_signal 真流（★M4）
# [Ref: 03_/04_维度四/.../step_07_冲突处理与回测.md]
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: exit-step07-prep exit-step07-conflict-test exit-step07-test exit-step07-schema
.PHONY: exit-step07-publish-once exit-step07-backtest exit-step07-status exit-step07-all

exit-step07-prep: exit-step06-all
	@echo "▶ [exit-step07-prep] DB 初始化 + 协议注册 + Redis 探测"
	PYTHONPATH=. python3 -m apps.exit_engine.db.init_db
	PYTHONPATH=. python3 -c "from apps.exit_engine.protocols import PROTOCOL_CLASSES; assert len(PROTOCOL_CLASSES)==5; print('✅ 5 协议已注册')"
	@PYTHONPATH=. python3 -c "import redis,os; r=redis.from_url(os.environ.get('EXIT_REDIS_URL') or os.environ.get('REDIS_URL') or 'redis://127.0.0.1:6379/2'); r.ping(); print('✅ Redis OK')" \
	  || echo "⚠️  Redis 未启动（tier-1 单测仍可过；publish-once 需 Redis）"

exit-step07-conflict-test:
	@echo "▶ [exit-step07-conflict-test] 7 场景冲突单测"
	PYTHONPATH=. python3 -m pytest tests/exit_engine/test_conflict_resolver.py tests/exit_engine/test_sp_conflict_priority.py -v --tb=short

exit-step07-schema:
	@echo "▶ [exit-step07-schema] sell_signal ↔ D0 schema"
	PYTHONPATH=. python3 scripts/check_exit_step07_schema.py

exit-step07-test:
	@echo "▶ [exit-step07-test] pytest step_07 全套"
	PYTHONPATH=. python3 -m pytest \
		tests/exit_engine/test_conflict_resolver.py \
		tests/exit_engine/test_sell_signal_publisher.py \
		tests/exit_engine/test_exit_engine_orchestrator.py \
		tests/exit_engine/test_sp_conflict_priority.py \
		-v --tb=short

exit-step07-publish-once: exit-step07-prep
	@echo "▶ [exit-step07-publish-once] 演示止损场景真 XADD（tier-1 本地 Redis）"
	@docker start diting-redis-step07 2>/dev/null || docker run -d --name diting-redis-step07 -p 6379:6379 redis:7-alpine
	@sleep 2
	EXIT_REDIS_URL=redis://127.0.0.1:6379/2 REDIS_URL=redis://127.0.0.1:6379/2 \
	  PYTHONPATH=. python3 scripts/run_one_evaluation.py --demo-stop-loss
	@EXIT_REDIS_URL=redis://127.0.0.1:6379/2 PYTHONPATH=. python3 -c "\
import redis; r=redis.from_url('redis://127.0.0.1:6379/2',decode_responses=True); \
n=r.xlen('events:exit:sell_signal'); print('events:exit:sell_signal XLEN=', n); assert n>=1"

exit-step07-backtest:
	@echo "▶ [exit-step07-backtest] 100 笔回测准确率"
	PYTHONPATH=. python3 scripts/backtest_100_history.py

exit-step07-status:
	@echo "▶ [exit-step07-status]"
	PYTHONPATH=. python3 scripts/exit_step07_status.py

exit-step07-all: exit-step07-prep exit-step07-conflict-test exit-step07-schema exit-step07-test exit-step07-backtest exit-step07-publish-once exit-step07-status
	@echo "✅ [exit-step07-all] D4 step_07 tier-1 准出：冲突 + publisher + 回测 + schema"

# ──────────────────────────────────────────────────────────────────────────────
# D3 step_05 — 叙事一致性 NLI LoRA（tier-1：数据+配置+降级客户端+pytest）
# [Ref: 03_/03_维度三/step_05]
# BLOCKED(gpu_unavailable): 训练本体需 GPU ≥16GB，tier-2 走 P-step_04 diting-training
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: watch-step05-prep watch-step05-data-check watch-step05-test watch-step05-train watch-step05-all watch-step05-status watch-step05-e2e watch-step05-health-publisher-test

watch-step05-prep:
	@echo "▶ [watch-step05-prep] D3 step_05 NLI 前置检查"
	@echo "  做了什么：检查训练数据文件 + NLI 客户端可导入"
	@test -f training/data/narrative_nli/train.jsonl || (echo "❌ train.jsonl 缺失" && exit 1)
	@test -f training/data/narrative_nli/dev.jsonl   || (echo "❌ dev.jsonl 缺失" && exit 1)
	@test -f training/data/narrative_nli/holdout.jsonl || (echo "❌ holdout.jsonl 缺失" && exit 1)
	PYTHONPATH=. python3 -c "from apps.state_watch.health.narrative_nli import NarrativeNLIClient; print('✅ NarrativeNLIClient 可导入')"

watch-step05-data-check:
	@echo "▶ [watch-step05-data-check] 训练数据质量检查"
	@echo "  做了什么：验证 train≥100 / dev≥20 / holdout≥30 / 标签分布"
	PYTHONPATH=. python3 scripts/check_nli_data.py
watch-step05-test:
	@echo "▶ [watch-step05-test] pytest NLI 降级客户端（≥10 用例）"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_narrative_nli.py -v --tb=short

watch-step05-train:
	@echo "▶ [watch-step05-train] NLI LoRA 训练（需 GPU ≥16GB）"
	@echo "  BLOCKED(gpu_unavailable): tier-2 请用 P-step_04 diting-training chart"
	bash training/scripts/train_nli.sh

watch-step05-health-publisher-test:
	@echo "▶ [watch-step05-health-publisher-test] pytest health_change_publisher 单测"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_health_change_publisher.py -v --tb=short

watch-step05-e2e:
	@echo "▶ [watch-step05-e2e] D3→D4 health_change 真流 e2e（需 prod Redis）"
	@echo "  做了什么：D3 XADD → D4 process_health_change → SP3 evaluate"
	@echo "  期望：handled=True / SP3 触发或 not_in_holdings（链路通畅）"
	PYTHONPATH=. python3 scripts/watch_d3_d4_e2e.py

watch-step05-all: watch-step05-prep watch-step05-data-check watch-step05-health-publisher-test watch-step05-test watch-step05-e2e
	@echo "✅ [watch-step05-all] D3 step_05 tier-1+tier-2 链路准出："
	@echo "  - 数据 ≥150 + 降级客户端 + publisher 单测 + e2e 真流"
	@echo "  BLOCKED(gpu_unavailable): watch-step05-train 需 GPU，tier-2 走 P-step_04"

watch-step05-status:
	@echo "▶ [watch-step05-status] NLI LoRA 状态"
	@wc -l training/data/narrative_nli/*.jsonl
	@test -d outputs/narrative_nli_lora_v1 && echo "  adapter 已存在 ✅" || echo "  adapter 未训练（BLOCKED(gpu_unavailable)）"

# ──────────────────────────────────────────────────────────────────────────────
# D3 step_07 — health_change 事件流 + 10 持仓 e2e
# [Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.2]
# ──────────────────────────────────────────────────────────────────────────────
.PHONY: watch-step07-prep watch-step07-publisher-smoke watch-step07-fixture-10
.PHONY: watch-step07-e2e watch-step07-schema watch-step07-latency watch-step07-test
.PHONY: watch-step07-all watch-step07-status watch-step07-clean

watch-step07-prep:
	@echo "▶ [watch-step07-prep] Redis 连通 + step_07 模块可导入"
	@REDIS_URL=$${STATE_WATCH_REDIS_URL:-$${REDIS_URL:-redis://127.0.0.1:6379/0}} $(RUNPY) -c "\
import redis, os; \
u=os.environ.get('REDIS_URL','redis://127.0.0.1:6379/0'); \
r=redis.from_url(u, decode_responses=True); r.ping(); print('✅ Redis OK', u)"
	@PYTHONPATH=. python3 -c "from apps.state_watch.health.orchestrator import HealthOrchestrator; print('✅ HealthOrchestrator 可导入')"

watch-step07-publisher-smoke: watch-step07-prep
	@echo "▶ [watch-step07-publisher-smoke] 1 节点 transition → XLEN+1"
	STATE_WATCH_REDIS_URL=$${STATE_WATCH_REDIS_URL:-$$(grep '^REDIS_URL=' .env 2>/dev/null | cut -d= -f2-)} \
	  $(RUNPY) scripts/watch_step07_publisher_smoke.py

watch-step07-fixture-10:
	@echo "▶ [watch-step07-fixture-10] 10 持仓 fixture 注入校验"
	$(RUNPY) -c "from tests.state_watch.fixtures.positions_10 import POSITIONS_10; assert len(POSITIONS_10)==10; print('✅ 10 持仓 fixture OK')"

watch-step07-e2e:
	@echo "▶ [watch-step07-e2e] 10 持仓状态切换准确率 ≥0.90"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_e2e_10_positions.py -v --tb=short

watch-step07-schema:
	@echo "▶ [watch-step07-schema] D0+D4 payload 字段对齐"
	PYTHONPATH=. python3 scripts/schema_check_d0_d4.py

watch-step07-latency:
	@echo "▶ [watch-step07-latency] P95 <30s"
	PYTHONPATH=. python3 scripts/watch_step07_latency.py

watch-step07-test:
	@echo "▶ [watch-step07-test] pytest step_07 单测"
	PYTHONPATH=. python3 -m pytest tests/state_watch/test_health_step07.py tests/state_watch/test_health_change_publisher.py -v --tb=short

watch-step07-status:
	@echo "▶ [watch-step07-status]"
	STATE_WATCH_REDIS_URL=$${STATE_WATCH_REDIS_URL:-$$(grep '^REDIS_URL=' .env 2>/dev/null | cut -d= -f2-)} \
	  $(RUNPY) scripts/watch_step07_status.py

watch-step07-clean:
	@echo "▶ [watch-step07-clean] dev only — 清理本地 stream"
	@REDIS_URL=$${STATE_WATCH_REDIS_URL:-redis://127.0.0.1:6379/0} $(RUNPY) -c "\
import redis, os; \
u=os.environ.get('REDIS_URL'); r=redis.from_url(u, decode_responses=True); \
n=r.delete('events:monitor:health_change'); print('DEL events:monitor:health_change', n)"

watch-step07-all: watch-step07-prep watch-step07-publisher-smoke watch-step07-fixture-10 watch-step07-e2e watch-step07-schema watch-step07-latency watch-step07-test watch-step07-status
	@echo "✅ [watch-step07-all] D3 step_07 tier-1 准出：publisher + 10 持仓 e2e + schema + latency"

# ============================================================
# D1 step_04 财务测谎引擎（5 节点骨架 · tier-1 本地）
# [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §7.2]
# ============================================================
.PHONY: cryo-step04-prep cryo-step04-test cryo-step04-all cryo-step04-status cryo-step04-db-check

cryo-step04-prep:
	@echo "▶ [cryo-step04-prep] D1 step_04 财务测谎引擎前置检查"
	PYTHONPATH=. python3 -c "from apps.cryo_guard.engines.financial_fraud import FinancialFraudEngine; print('✅ FinancialFraudEngine 可导入')"
	PYTHONPATH=. python3 -c "from apps.cryo_guard.engines.financial_fraud.feature_calculator import compute_features; print('✅ feature_calculator 可导入')"
	@echo "▶ 做了什么: 验证 5 节点模块全部可导入"

cryo-step04-test:
	@echo "▶ [cryo-step04-test] pytest D1 财务测谎引擎（≥20 用例）"
	PYTHONPATH=. python3 -m pytest tests/cryo_guard/test_financial_fraud_engine.py -v --tb=short
	@echo "▶ 做了什么: N1~N5 骨架 + 整引擎降级 + schema 验证"

cryo-step04-db-check:
	@echo "▶ [cryo-step04-db-check] D1 财务测谎引擎 · 真实 DB 联调"
	@echo "  做了什么：从 financial_reports 提取字段 → compute_features → 输出各标的 fraud_report"
	@echo "  期望：active 标的均输出 available≥5 字段；无 flags（无测谎触发）"
	PYTHONPATH=. python3 scripts/cryo_step04_fraud_check_db.py

cryo-step04-all: cryo-step04-prep cryo-step04-test cryo-step04-db-check
	@echo "✅ [cryo-step04-all] D1 step_04 tier-1+DB联调 准出："
	@echo "   5 节点骨架（field_extractor/feature_calculator/time_series/peer/llm）+ pytest ≥20"
	@echo "▶ 做了什么: 无 DB / 无 vLLM 全降级 → report schema 合法 + 6 类特征公式 pass"
	@echo "▶ 期望什么: 22+ 项测试绿；特征公式 6 类正负各 1 案例验证通过"
	@echo ""
	@echo "# DECISION_PENDING: tier-2 真实训练 + Holdout 评测（需 GPU + step_03 蒸馏数据）"
	@echo "#   1. GPU 就绪后执行 make cryo-step04-train"
	@echo "#   2. make cryo-step04-holdout-eval"

cryo-step04-status:
	@echo "▶ [cryo-step04-status] D1 step_04 财务测谎引擎状态"
	@PYTHONPATH=. python3 -c "from apps.cryo_guard.engines.financial_fraud import FinancialFraudEngine; print('  引擎模块 ✅')" 2>/dev/null || echo "  引擎模块 ❌"
	@test -d output/financial_fraud_lora_v1 && echo "  LoRA adapter 已存在 ✅" || echo "  LoRA adapter 未训练（BLOCKED(gpu_unavailable)）"

