# 任务包：e2e 打通（用本仓编排启动的服务跑 `tests/e2e/`）

```text
TASK_ID    : M7-VERIFY-E2E-STACK-UP
派发人     : Tech Lead
背景       : `tests/e2e/` 打的是**外部活服务**（`KERT_BASE_URL`，默认 127.0.0.1:8106）。
             本机 8106 被**另一个正在服务的 KERT 实例**占用（非本仓、非本任务可停）。
             现状：e2e 的"服务维度 require"在 CI 是硬要求（.github/workflows/ci.yml）
             但缺少"由本仓编排拉起服务"的可复现路径。
性质       : 验证打通 + 最小改动
```

## 1. 目标

1. 产出**可复现步骤**（写入 `evidence/m7-3/EVIDENCE-E2E-STACK-UP.md`）：
   用 `deploy/docker-compose.yml` 拉起本仓服务（**允许用 compose 覆盖文件改端口**，见下），
   对目标 base URL 跑 `python -m pytest tests/e2e/ -rs`，记录**原始退出码与失败归因**；
2. 打通后给出**哪些 e2e 用例通过 / 哪些因外部依赖（GITS `:8082`、真实 LLM 凭据等）不可用而失败**，
   逐条给出**归因证据**（不得用"环境问题"一句带过）；
3. 若需要，允许**最小改动**：`tests/e2e/conftest.py` 或新增一个启动脚本
   （例如 `scripts/run_e2e_local.sh`），使"起服务 → 跑 e2e → 停服务"成为一条命令。

## 2. 硬性边界（违反即返工）

- **禁止**修改 `deploy/docker-compose.yml` 的**语义**（服务清单、依赖链、加固项、
  `provision` 供给任务）；端口冲突请用**覆盖文件**（`-f a.yml -f /tmp/override.yml`）解决；
- **禁止**修改 `src/**`；若发现必须改源码才能跑通，**停下来报告**，不要自行改；
- **禁止**停止/干扰 8106 上的其他实例；**禁止** `docker compose down` 全局清理
  （只 `down` 本仓 stack，且不要 `-v` 删别人的卷）；
- 跑完必须**撤栈**并确认无残留容器；不得 push。

## 3. 必须记录的证据

| 项 | 要求 |
|---|---|
命令与退出码 | 逐条原始输出（构建/启动/e2e 运行/撤栈） |
服务就绪判据 | `/livez`、`/readyz` 实测状态码 |
控制面就绪判据 | `/v1/knowledge-maps` 的 `count`（**须 >0**；=0 说明供给未生效） |
鉴权口径 | `X-API-Key` 的值是**密钥本身（secret）**，不是 `key_id:secret` |
失败归因 | 每条失败用例：是外部依赖缺失、还是本仓缺陷（**不得混为一谈**） |

## 4. 非声明

不是 QA 通过；本任务只产出"打通路径 + 归因"，不改变任何生产语义。
