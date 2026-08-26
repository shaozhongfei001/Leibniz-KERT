# DKWS 独立服务端产品边界 V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 依据：独立评审报告 B-03 / 4.1 / 10
> 关联 ADR：ADR-014

## 1. 目标

明确 DKWS 作为独立安装、配置、启动、运行、升级和审计的知识工程服务端软件的产品边界。
外部智能体、GITS 或其他系统只能是 API 客户端，不能成为 DKWS 启动、配置、运行、密钥管理、Skill 加载或运维的必要依赖。

## 2. 产品组件

| 组件 | 名称 | 职责 |
|---|---|---|
| 服务端 | `dkws-server` | HTTP API、Skill 执行、知识服务 |
| 异步 Worker | `dkws-worker` | 持久化 Job 消费、重试、租约、恢复 |
| 管理 CLI | `dkws-admin` | 安装、配置、密钥注入、Skill 安装、状态查看、备份恢复 |
| 配置目录 | `DKWS_CONFIG_DIR` | 服务配置、密钥引用、Skill 资产注册 |
| Runtime Store | SQLite 文件 | 幂等、Job、Evidence 元数据、Gate 审计、操作审计 |
| 知识资产 | 五层工作区 | 01_raw / 02_work / 03_core / 04_serve / 90_control |
| 契约 | OpenAPI/JSON Schema | 对外 API 唯一权威源 |

## 3. 非依赖声明

DKWS 产品运行**不依赖**：

- 任何 Agent Harness / DSH / 动态插件会话
- 外部智能体的 Skill 注册表
- 外部用户目录凭据文件（如 `~/.dsh/.credentials.yaml`）
- 外部会话级 web server 注册
- 外部平台提供的 LLM 凭据注入

以下仅作为**可选客户端或开发集成**：

- GITS：API Consumer
- DSH/智能体：API Consumer 或开发调试工具
- 前端报告页：可选浏览器客户端

## 4. 独立运行边界

```text
DKWS 独立安装包
├── bin/dkws-server
├── bin/dkws-worker
├── bin/dkws-admin
├── config/dkws.yaml
├── schema/ (OpenAPI/JSON Schema)
├── skills/ (随包自带，带版本/哈希)
├── assets/ (知识资产模板/种子)
└── runtime/ (SQLite、日志、PID)
```

### 4.1 安装

- 支持 systemd 部署
- 支持 Docker Compose 部署
- 干净主机/容器无需安装外部智能体

### 4.2 配置

- 配置来源：`DKWS_CONFIG_DIR/dkws.yaml` + 环境变量
- 端口、监听、工作区、Runtime DB、日志级别均为配置项
- 禁止在合同/文档中硬编码环境 IP

### 4.3 密钥管理

- 通过 `DKWS_SECRET_PROVIDER` 抽象注入
- 首期支持：环境变量、文件注入、Docker Secret
- 后续可扩展：OS Keychain、Vault/KMS
- 禁止密钥明文入仓库、日志或普通配置

### 4.4 Skill 加载

- Skill 资产随 DKWS 发布包自带
- 每个 Skill 包包含 SKILL.md、schema、版本、哈希
- 安装/升级通过 `dkws-admin skill install <package>` 受控执行
- 不依赖外部插件注册表

### 4.5 运维

- 启动、停止、升级、回滚、备份、恢复均有 CLI/systemd 入口
- 健康检查：`/livez` `/readyz`
- 指标：`/metrics`
- 日志：结构化 JSON

## 5. 外部客户端接入

- GITS 配置：`DKWS_BASE_URL`、`DKWS_API_KEY`
- 不使用 `DSH_BASE_URL` 作为产品配置名
- 客户端必须支持认证、超时、错误空态

## 6. 独立性验收测试

在一台干净主机上，不安装、不启动任何 Agent Harness 或类似平台，DKWS 必须能完成：

1. 安装依赖与发布包
2. 写入配置与注入密钥
3. 初始化工作区与 Runtime DB
4. 启动 `dkws-server`
5. 通过 `/livez`、`/readyz`
6. 查询 Skill 列表（`/api/skill/health`）
7. 执行受控 Skill（如供应链图谱）
8. 创建并恢复异步 Job（Worker 进程）
9. 读取证据/审计
10. 执行受控工具调用
11. 停止服务并备份/恢复

## 7. 当前差距

- 现有 `serve_skill_service.py` 从 `~/.dsh/.credentials.yaml` 注入 LLM Key → 需改为独立 Secret Provider
- 现有 Skill 资产同时来自本地 `skills/` 和 `examples/bank-front-skills/` → 需统一随包资产
- 现有配置名/文档仍含 `DSH_*` 命名 → 需产品中性命名
- 无 `dkws-admin`、Docker、CI → Phase 1 补齐
