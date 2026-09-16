# KERT 部署指南（M2.7）

> 本文档描述 KERT（Data Knowledge Workspace Service）的单节点部署流程。

## 目录

- [架构概览](#架构概览)
- [前置条件](#前置条件)
- [安装步骤](#安装步骤)
- [配置说明](#配置说明)
- [验证方法](#验证方法)
- [备份与恢复](#备份与恢复)
- [常见问题](#常见问题)

## 架构概览

KERT 采用单机单实例架构（ADR-015），由两个服务组成：

```
                    ┌─────────────┐
                    │   Nginx     │  TLS 终止 + 安全头
                    │  (反向代理)  │
                    └──────┬──────┘
                           │ :443 → :8106
                    ┌──────┴──────┐
                    │  KERT API   │  Python Core，唯一公共入口
                    │  :8106      │  (FastAPI + Uvicorn)
                    └──────┬──────┘
                           │ 共享 workspace volume
                    ┌──────┴──────┐
                    │ KERT Worker │  持久化异步 Worker（无 HTTP）
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
git clone <repo-url> /opt/kert
cd /opt/kert
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
KERT_API_KEYS=gits-caller:$(openssl rand -hex 24):read|execute,ops-admin:$(openssl rand -hex 24):read|execute|admin
```

> **安全警告**：`CHANGE_ME_AT_LEAST_16_CHARS` 是占位值，生产 profile 会拒绝启动。
> 建议用 `openssl rand -hex 24` 生成。

**控制面供给（M7.3 P2）**：`KERT_CONTROL_PLANE_SOURCE` 指向**容器内**的控制面元数据源
（默认 `/app/examples/bank-front-knowledge-maps`，镜像已自带）。compose 会先跑一次性任务
`provision` 把它装入 workspace；**未声明该变量则 compose 直接失败** ——
这是 fail-closed 的部署前置：未供给的工作区会让三个 customer-engagement 技能**全部拒绝**
（表现是"服务健康、业务全挂"，比起不来更难排查）。

### 3. 构建与启动

```bash
# 构建镜像
docker compose -f deploy/docker-compose.yml build

# 启动服务（后台运行）
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

# 查看状态
docker compose -f deploy/docker-compose.yml ps
```

`up -d` 会**先**执行一次性任务 `provision`（控制面供给，**幂等**：内容未变不改写，
源内任一份定义非法则**一份都不写**），`api` 在其成功后启动，`worker` 再等 `api` 健康。
"忘了供给"因此不会变成运行时故障，而是部署阶段就暴露。

该任务带 `--init`：首次部署的空卷会先被初始化（`kert init`）；已初始化则 no-op；
**非空且未初始化**仍按既有纪律报错（不静默改写他人在用的目录）。

手动重跑供给（可随时执行，幂等）：

```bash
make deploy-provision    # 等价于 docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm provision
```

### 4. 验证部署

```bash
# 快速检查
curl http://localhost:8106/livez

# 控制面是否真的供给成功？（需带 API Key；生产 profile 强制认证）
# 注意：X-API-Key 的值是**密钥本身（secret）**，不是 "key_id:secret"
# （cpgk/runtime_config.verify 对 presented 做摘要比对，见 middleware.py:144）。
curl -H "X-API-Key: <secret>" http://localhost:8106/v1/knowledge-maps
# 期望 data.count > 0；count=0 说明供给未生效（此时路由按 fail-closed 默认拒绝）

# 完整验证
python deploy/verify_deployment.py

# 或冒烟测试（含构建→启动→检查→停止完整流程）
bash deploy/smoke_test.sh
```

### 5. 配置反向代理（生产必需）

```bash
# 参考 Nginx 配置模板
cp deploy/nginx/kert.conf.example /etc/nginx/sites-available/kert
# 编辑 server_name、TLS 证书路径等
ln -s /etc/nginx/sites-available/kert /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## 配置说明

### 环境变量

完整列表见 `deploy/.env.example`，关键项：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `KERT_API_KEYS` | **是** | — | API 密钥声明，格式 `id:secret:scope1\|scope2` |
| `KERT_LOG_LEVEL` | 否 | `INFO` | 日志级别 |
| `KERT_RATE_LIMIT_RPM` | 否 | `600` | 每分钟请求限流 |
| `KERT_METRICS_REQUIRE_ADMIN` | 否 | `true` | `/metrics` 是否要求 admin 权限 |
| `KERT_WORKER_LEASE_SECONDS` | 否 | `30` | Worker 任务租约时长 |
| `KERT_WORKER_POLL_INTERVAL` | 否 | `1.0` | Worker 空闲轮询间隔（秒） |

**不要在 `.env` 中配置的变量：**

- `KERT_PROFILE` — 已在 compose 中固定为 `prod`
- `KERT_BIND_HOST` — 容器内固定 `0.0.0.0`，对外暴露由 ports 回环绑定控制
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
| `kert_workspace` | `/data/workspace` | 知识资产（权威源，必须持久化） |
| `kert_backups` | `/data/backups` | 备份集输出目录 |

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
docker run --rm -v kert_backups:/data/backups busybox ls -la /data/backups/

# 将备份集复制到宿主机
docker cp kert-backup:/data/backups/<backup-dir> /var/backups/kert/
```

### Systemd 部署备份

```bash
# 手动触发
sudo systemctl start kert-backup

# 查看定时器状态
sudo systemctl list-timers kert-backup.timer

# 查看备份日志
journalctl -u kert-backup
```

### 恢复

```bash
# 从备份集恢复（建议恢复到新目录，勿直接覆盖生产）
python scripts/kert_ops.py restore \
    --backup /var/backups/kert/backup-<timestamp> \
    --target /tmp/restore-drill

# 校验备份集完整性
python scripts/kert_ops.py verify \
    --backup /var/backups/kert/backup-<timestamp>
```

## 常见问题

### Q: 启动报错 "需在 .env 中配置 API Key"

**原因**：`KERT_API_KEYS` 未配置或仍为占位值。

**解决**：
```bash
# 检查 .env 文件
cat deploy/.env | grep KERT_API_KEYS
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
# 在 .env 中设置 KERT_METRICS_REQUIRE_ADMIN=false
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
- [Nginx 配置模板](nginx/kert.conf.example)
- [Systemd 服务配置](systemd/)
- [Dockerfile](Dockerfile)
