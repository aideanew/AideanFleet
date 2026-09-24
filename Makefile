# AideanFleet Makefile — 统一命令入口
# 用法：make <target>   例如 make test, make run, make setup
# 原则：初中生都能用——每个命令一行，不需要记参数

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python

.DEFAULT_GOAL := help

##@ 基础设置

.PHONY: setup
setup: ## 创建虚拟环境并安装依赖
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -e ".[dev]"
	$(VENV_PYTHON) -m pip install -r requirements.txt
	@echo "✅ 环境就绪：source $(VENV)/bin/activate"

##@ 开发

.PHONY: run
run: ## 启动控制台服务（端口 5000）
	$(VENV_PYTHON) -m fleet.console.server

.PHONY: run-cli
run-cli: ## CLI 交互模式启动
	$(VENV_PYTHON) run_interactive.py

.PHONY: test
test: ## 运行全部测试
	$(VENV_PYTHON) -m pytest tests -q

.PHONY: test-e2e
test-e2e: ## 运行端到端测试
	$(VENV_PYTHON) -m pytest tests-e2e -q

.PHONY: test-all
test-all: ## 运行所有测试（含 e2e）
	$(VENV_PYTHON) -m pytest tests tests-e2e -q

.PHONY: lint
lint: ## 代码检查（pyflakes）
	$(VENV_PYTHON) -m pyflakes fleet/ || true

##@ 数据维护

.PHONY: clean-data
clean-data: ## 清空运行时数据（data/ 目录）
	@echo "⚠️  将清空 data/ 目录，按 Ctrl+C 取消"
	@sleep 3
	rm -rf data/*
	@echo "✅ data/ 已清空"

.PHONY: clean-cache
clean-cache: ## 清理缓存文件
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache
	@echo "✅ 缓存已清理"

.PHONY: clean-all
clean-all: clean-cache ## 清理缓存和虚拟环境
	rm -rf $(VENV) *.egg-info
	@echo "✅ 全部清理完毕，运行 make setup 重新初始化"

##@ 前端

.PHONY: frontend-install
frontend-install: ## 安装前端依赖
	cd fleet/console/web && pnpm install

.PHONY: frontend-build
frontend-build: ## 构建前端
	cd fleet/console/web && pnpm build

.PHONY: frontend-dev
frontend-dev: ## 前端开发模式
	cd fleet/console/web && pnpm dev

##@ Git

.PHONY: git-status
git-status: ## 查看 git 状态
	git status -s

##@ 帮助

.PHONY: help
help: ## 显示此帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
