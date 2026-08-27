# DKWS 部署指南（M2.7）

> 本文档描述 DKWS（Data Knowledge Workspace Service）的单节点部署流程。

## 目录

- [架构概览](#架构概览)
- [前置条件](#前置条件)
- [安装步骤](#安装步骤)
- [配置说明](#配置说明)
- [验证方法](#验证方法)
- [备份与恢复](#备份与恢复)
- [常见问题](#常见问题)

## 架构概览

DKWS 采用单机单实例架构（ADR-015），由两个服务组成：

```
                    ┌─────────────┐
                    │   Nginx     │  TLS 终止 + 安全头
                    │  (反向代理)  │
                    └──────┬──────┘
                           │ :443 → :8106
                    ┌──────┴──────┐
                    │  DKWS API   │  Python Core，唯一公共入口
                    │  :8106      │  (FastAPI + Uvicorn)
                    └──────┬──────┘
                           │ 共享 workspace volume
                    ┌──────┴──────┐
                    │ DKWS Worker │  持久化异步 Worker（无 HTTP）
                    │             │  消费 Job Queue
                    └─────────────┘
```

**关键设计决策：**

- API 与 Worker 共享同一 SQLite Runtime Store，必须部署在同一主机同一文件系统
- TLS 由外层 Nginx 终止，Docker Compose 仅绑回环地址
- 知识资产经 Docker Volume 持久化，不随镜像不可变

## 前置条件

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Docker | 20.10+ | 容器运行时 |
| Docker Compose | v2.0+ | `docker compose` 命令（非旧版 `docker-compose`） |
| curl | 任意 | 健康检查与冒烟测试 |
| Python 3.11+ | 3.11+ | 部署验证脚本（可选） |

**硬件建议：**

- CPU: 2 核+
- 内存: 2 GB+（Worker 默认限制 2 GB）
- 磁盘: 10 GB+（取决于知识资产规模，备份空间另计）

## 安装步骤

### 1. 克隆仓库

```bash
git clone <repo-url> /opt/dkws
cd /opt/dkws
git checkout <target-branch>
```

### 2. 配置环境变量

```bash
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
```

编辑 `deploy/.env`，**必须**修改：

```bash
# 生成安全的 API Key（每个至少 16 字符）
DKWS_API_KEYS=gits-caller:$(openssl rand -hex 24):read|execute,ops-admin:$(openssl rand -hex 24):read|execute|admin
```

> **安全警告**：`CHANGE_ME_AT_LEAST_16_CHARS` 是占位值，生产 profile 会拒绝启动。
> 建议用 `openssl rand -hex 24` 生成。

### 3. 构建与启动

```bash
# 构建镜像
docker compose -f deploy/docker-compose.yml build

# 启动服务（后台运行）
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

# 查看状态
docker compose -f deploy/docker-compose.yml ps
```

### 4. 验证部署

```bash
# 快速检查
curl http://localhost:8106/livez

# 完整验证
python deploy/verify_deployment.py

# 或冒烟测试（含构建→启动→检查→停止完整流程）
bash deploy/smoke_test.sh
```

### 5. 配置反向代理（生产必需）

```bash
# 参考 Nginx 配置模板
cp deploy/nginx/dkws.conf.example /etc/nginx/sites-available/dkws
# 编辑 server_name、TLS 证书路径等
ln -s /etc/nginx/sites-available/dkws /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## 配置说明

### 环境变量

完整列表见 `deploy/.env.example`，关键项：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DKWS_API_KEYS` | **是** | — | API 密钥声明，格式 `id:secret:scope1\|scope2` |
| `DKWS_LOG_LEVEL` | 否 | `INFO` | 日志级别 |
| `DKWS_RATE_LIMIT_RPM` | 否 | `600` | 每分钟请求限流 |
| `DKWS_METRICS_REQUIRE_ADMIN` | 否 | `true` | `/metrics` 是否要求 admin 权限 |
| `DKWS_WORKER_LEASE_SECONDS` | 否 | `30` | Worker 任务租约时长 |
| `DKWS_WORKER_POLL_INTERVAL` | 否 | `1.0` | Worker 空闲轮询间隔（秒） |

**不要在 `.env` 中配置的变量：**

- `DKWS_PROFILE` — 已在 compose 中固定为 `prod`
- `DKWS_BIND_HOST` — 容器内固定 `0.0.0.0`，对外暴露由 ports 回环绑定控制
- LLM 凭据 — 由外部密钥管理注入，不写入 `.env`

### Docker Compose 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `api` | 127.0.0.1:8106 | Python Core API，唯一公共入口 |
| `worker` | 无 | 持久化异步 Worker，消费 Job Queue |
| `backup` | 无 | 一次性服务，手动触发备份 |

### Volume 说明

| Volume | 挂载点 | 说明 |
|--------|--------|------|
| `dkws_workspace` | `/data/workspace` | 知识资产（权威源，必须持久化） |
| `dkws_backups` | `/data/backups` | 备份集输出目录 |

## 验证方法

### 快速健康检查

```bash
# 存活探针 — 进程是否活着
curl http://localhost:8106/livez
# 期望：{"status": "alive", ...}

# 就绪探针 — 能否承接流量
curl http://localhost:8106/readyz
# 期望：{"status": "ready", ...} 或 {"status": "not_ready", "degraded": [...], ...}

# 指标端点 — Prometheus 格式
curl -H "X-API-Key: <admin-key>" http://localhost:8106/metrics
# 期望：HTTP 200 + Prometheus 文本格式
# 无密钥时返回 401，属正常行为
```

### 部署验证脚本

```bash
python deploy/verify_deployment.py --base-url http://localhost:8106
```

检查项：
1. `/livez` — HTTP 200，响应含 `status`
2. `/readyz` — HTTP 200 或 503（降级但不死）
3. `/metrics` — HTTP 200 或 401（需 admin 密钥）

### 冒烟测试

```bash
bash deploy/smoke_test.sh
```

完整流程：构建镜像 → 启动服务 → 等待就绪 → 健康端点验证 → Skill 列表测试 → 停止服务。

## 备份与恢复

### Docker 部署备份

```bash
# 手动触发备份（使用 backup 服务）
docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm backup

# 查看备份集
docker run --rm -v dkws_backups:/data/backups busybox ls -la /data/backups/

# 将备份集复制到宿主机
docker cp dkws-backup:/data/backups/<backup-dir> /var/backups/dkws/
```

### Systemd 部署备份

```bash
# 手动触发
sudo systemctl start dkws-backup

# 查看定时器状态
sudo systemctl list-timers dkws-backup.timer

# 查看备份日志
journalctl -u dkws-backup
```

### 恢复

```bash
# 从备份集恢复（建议恢复到新目录，勿直接覆盖生产）
python scripts/dkws_ops.py restore \
    --backup /var/backups/dkws/backup-<timestamp> \
    --target /tmp/restore-drill

# 校验备份集完整性
python scripts/dkws_ops.py verify \
    --backup /var/backups/dkws/backup-<timestamp>
```

## 常见问题

### Q: 启动报错 "需在 .env 中配置 API Key"

**原因**：`DKWS_API_KEYS` 未配置或仍为占位值。

**解决**：
```bash
# 检查 .env 文件
cat deploy/.env | grep DKWS_API_KEYS
# 确保密钥长度 >= 16 字符
```

### Q: Worker 启动后立即退出

**原因**：Worker 依赖 API 服务健康后才启动（`depends_on: api: condition: service_healthy`）。

**解决**：
```bash
# 检查 API 服务状态
docker compose -f deploy/docker-compose.yml logs api
# 常见原因：API Key 配置错误、端口冲突
```

### Q: /readyz 返回 503

**原因**：就绪探针检测到依赖降级（如 Runtime Store 未初始化）。

**解决**：
```bash
# 查看具体降级项
curl -s http://localhost:8106/readyz | python3 -m json.tool
# 检查 "degraded" 和 "checks" 字段
```

### Q: /metrics 返回 401

**原因**：默认配置要求 admin 权限才能访问指标端点。

**解决**：
```bash
# 方案 1：携带 admin 密钥
curl -H "X-API-Key: <admin-key>" http://localhost:8106/metrics

# 方案 2：关闭密钥要求（仅限内网监控场景）
# 在 .env 中设置 DKWS_METRICS_REQUIRE_ADMIN=false
```

### Q: 如何查看容器日志

```bash
# API 日志
docker compose -f deploy/docker-compose.yml logs -f api

# Worker 日志
docker compose -f deploy/docker-compose.yml logs -f worker

# 最近 100 行
docker compose -f deploy/docker-compose.yml logs --tail=100 api
```

### Q: 如何更新镜像

```bash
# 拉取最新代码
git pull origin <branch>

# 重新构建并启动
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

# 建议先备份
docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm backup
```

### Q: Systemd 部署 vs Docker 部署

| 特性 | Systemd | Docker |
|------|---------|--------|
| 隔离性 | 进程级 | 容器级（更强） |
| 部署复杂度 | 低 | 中 |
| 资源开销 | 低 | 略高 |
| 适用场景 | 单机长期运行 | 需要隔离/多环境 |

Systemd 配置文件在 `deploy/systemd/`，安装方法见各 `.service` 文件头部注释。

---

**相关文档：**
- [环境变量模板](.env.example)
- [Nginx 配置模板](nginx/dkws.conf.example)
- [Systemd 服务配置](systemd/)
- [Dockerfile](Dockerfile)
