# diting-src Makefile
# [Ref: 03_原子目标与规约/_共享规约/02_三位一体仓库规约]

.PHONY: test build lint clean

test:
	PYTHONPATH=. python3 -m pytest tests/ -v

build:
	@echo "make build: 请在此补充 Docker 镜像构建指令"

lint:
	@echo "make lint: 请在此补充 lint 指令"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
