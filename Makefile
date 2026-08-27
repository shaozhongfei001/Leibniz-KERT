# DKWS Makefile（M2.7）
#
# 部署相关目标，简化 docker compose 操作。
#
# 用法：
#   make deploy-build        构建镜像
#   make deploy-up           启动服务
#   make deploy-down         停止服务
#   make deploy-logs         查看日志
#   make deploy-backup       手动触发备份
#   make deploy-restore      从备份恢复（需 BACKUP= 参数）
#   make deploy-smoke-test   冒烟测试
#   make deploy-verify       部署验证

# ---------- 配置 ----------
COMPOSE_FILE = deploy/docker-compose.yml
ENV_FILE     = deploy/.env
BASE_URL     = http://localhost:8106

# ---------- 部署目标 ----------

.PHONY: deploy-build deploy-up deploy-down deploy-logs deploy-backup deploy-restore deploy-smoke-test deploy-verify

deploy-build: ## 构建 Docker 镜像
	docker compose -f $(COMPOSE_FILE) build

deploy-up: ## 启动服务（后台运行）
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d

deploy-down: ## 停止服务并移除容器
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down --remove-orphans

deploy-logs: ## 查看服务日志（跟随输出，Ctrl-C 退出）
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) logs -f

deploy-backup: ## 手动触发备份
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) run --rm backup

deploy-restore: ## 从备份恢复（需 BACKUP= 参数）
	@echo "用法: make deploy-restore BACKUP=/path/to/backup-dir TARGET=/path/to/restore"
	@echo "注意：建议恢复到新目录，勿直接覆盖生产"
	@if [ -z "$(BACKUP)" ] || [ -z "$(TARGET)" ]; then \
		echo "错误：BACKUP 和 TARGET 参数均为必填" >&2; exit 1; \
	fi
	python scripts/dkws_ops.py restore --backup "$(BACKUP)" --target "$(TARGET)"

deploy-smoke-test: ## 冒烟测试（构建→启动→健康检查→Skill测试→停止）
	bash deploy/smoke_test.sh

deploy-verify: ## 部署验证（检查 /livez /readyz /metrics）
	python deploy/verify_deployment.py --base-url $(BASE_URL)

# ---------- 帮助 ----------

.PHONY: help
help: ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'
