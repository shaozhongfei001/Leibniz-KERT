# PR: 修复 CI —— httpx 测试依赖声明 + develop PR 触发

- **源分支**：`fix/ci-httpx-test-dependency`
- **目标分支**：`develop`
- **范围**：仅 2 个配置文件，`+12 / −3`，无测试/源码/lock 变更
- **性质**：修复既有 CI 缺陷，与 JR-1 功能无关
- **建议合并顺序**：**本 PR 最先合**（先让 CI 转绿，再合 #1 → #2）

---

## 1. 修复两个独立的 CI 缺陷

### 缺陷一：`httpx` 从未被安装

`httpx` 只出现在 `requirements-lock.txt`，**未在 `pyproject.toml` 的任何
extra 中声明**（原为 `api = [fastapi, uvicorn]`、`dev = [pytest]`）。

CI 的安装命令是：

```bash
pip install -c requirements-lock.txt ".[api,dev]" pytest-cov
```

关键点：`-c` 是**约束（constraint）**文件 —— 它只钉版本，**不会导致任何包被
安装**。既然没有任何已声明依赖引入 `httpx`，它就根本不存在，于是用例在
收集阶段即失败：

```text
ModuleNotFoundError: No module named 'httpx'
RuntimeError: The starlette.testclient module requires the httpx package
```

`httpx` 确实是**测试依赖**：`tests/e2e` 直接 import，`tests/integration`
经 `starlette.testclient.TestClient` 间接依赖（缺失时抛 `RuntimeError`
而非 `ImportError`，所以报错信息不同）。故归入 `dev` extra 而非 `api`。

### 缺陷二：CI 从不在 `develop` 的 PR 上运行

`pull_request.branches` 原为 `[main]`，但按流程 feature 分支 PR 到
`develop`。结果 **PR #1 / #2 上没有任何 check run**，合并前无任何自动验证。

这是治理缺口：把 base 从 `main` 改为 `develop` 修正了合并目标，
却反而失去了 CI 把关。现改为 `[main, develop]`。

## 2. 验证方式（可复现）

在纯净 Python 3.12 venv 中**复现 CI 的原始安装命令**：

```bash
python3.12 -m venv /tmp/ci_verify
/tmp/ci_verify/bin/pip install -c requirements-lock.txt ".[api,dev]" pytest-cov
/tmp/ci_verify/bin/python -m pytest tests/e2e tests/integration
```

结果：

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| `httpx` | 缺失 | ✅ `0.28.1`（仍由 lock 钉住版本） |
| `tests/e2e` + `tests/integration` 收集 | **0 项**（每个模块均 collection error） | **315 项** |
| 实跑结果 | 无法执行 | **294 passed** |

## 3. 已知遗留：21 个 error 属另一独立问题

实跑仍有 21 个 error，**与本修复无关**：

```text
AssertionError: 服务未就绪: http://127.0.0.1:8082/actuator/health
([Errno 111] Connection refused)
```

这些用例经 `tests/e2e/conftest.py` 的 `gits_ready` fixture 要求
**GITS Backend 在 `127.0.0.1:8082` 运行**。任何无该外部服务的环境
（含 CI）都必然失败。

**本 PR 未处理**：让它们在服务缺失时 skip 属行为变更，
应由 Tech Lead 决策后以独立任务包处理，不混入依赖声明修复。

## 4. 为什么范围如此之小

刻意只改两处配置行：

- 不动测试代码
- 不动源码
- 不动 `requirements-lock.txt`

这样本 PR 可被独立评审、独立回滚，不与 JR-1 或发布内容纠缠。

## 5. 审查要点

1. `httpx>=0.27` 放在 `dev` 而非 `api` 是否认可（它只服务测试，不服务运行时）。
2. `pull_request.branches` 加入 `develop` 后，CI 用量增加是否可接受。
3. 是否同意将「GITS 依赖型 e2e 用例在无服务时 skip」列为独立任务包。

## 6. 相关记录

- `evidence/jr1/FAILURES.md` → `FAIL-JR1-04`（在 JR-1 分支上，随 PR #2 合入）
- 本修复不属于 JR-1 交付范围，故单独成 PR

## 7. 非声明

- 本 PR 仅修复 CI 配置，不改变任何业务行为。
- 本 PR 不代表 CI 已全绿（尚有 21 个需外部服务的 e2e error）。
- 本 PR 不代表 DKWS 已生产就绪、GITS UAT 已通过、安全审计已完成。
- Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署，且未自行 merge。
