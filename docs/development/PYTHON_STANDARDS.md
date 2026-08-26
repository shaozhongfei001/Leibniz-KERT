# Python 开发规范

## 版本

- Python 3.11+
- 使用 `pyproject.toml` 管理依赖

## 代码风格

- 遵循 PEP 8
- 使用类型注解
- 使用 `ruff` / `black` 风格（如引入）
- 函数和类必须有 docstring

## 项目结构

```text
src/dkws/
├── api/          # FastAPI 路由
├── application/  # 应用服务
├── domain/       # 领域模型
├── infrastructure/ # 基础设施适配
└── cli/          # CLI
```

## 测试

- 单元测试：`pytest tests/unit`
- 集成测试：`pytest tests/integration`
- 契约测试：`pytest tests/contract`
- 安全/恢复：`pytest tests/security tests/recovery`

## 禁止

- 不把密钥写入代码/日志
- 不直接修改 03_core 权威资产
- 不在生产 profile 使用 autoReload
