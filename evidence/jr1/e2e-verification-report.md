# JR-1 内部契约端到端验证报告

- 生成命令：`python scripts/verify_jr1_internal_contract.py`
- 总体结果：**PASS**
- 契约 bundle hash：`64b9b432d6ee9fc9e017436171f05e1198ab920121202266c835c471ff2c4550`

| # | 检查项 | 结果 | 说明 |
|---|--------|------|------|
| 1 | 受控契约文件齐备（6 Schema + 1 OpenAPI） | PASS |  |
| 2 | Schema 目录无白名单外文件（防影子契约） | PASS |  |
| 3 | 全部 JSON Schema 可解析且符合 Draft 2020-12 | PASS |  |
| 4 | 内部 OpenAPI 可解析且 $ref 全部指向受控 Schema | PASS |  |
| 5 | 全部契约示例通过 Schema 校验（12 份） | PASS |  |
| 6 | Python 侧契约测试通过（tests/contract） | PASS | 170 passed in 0.42s |
| 7 | Java 侧契约测试通过（poc/spring-ai-alibaba-skill-runtime） | PASS | [INFO] Tests run: 73, Failures: 0, Errors: 0, Skipped: 0 |
| 8 | 契约 hash 可重算且 Python/Java/证据三方一致 | PASS | bundle_hash=64b9b432d6ee9fc9e017436171f05e1198ab920121202266c835c471ff2c4550 |

## 非声明

- 本报告不代表 DKWS 已生产就绪。
- 本报告不代表 GITS UAT 已通过。
- 本报告不代表安全审计已完成。
- 本报告不代表 Java Runtime 已生产可用。
- 本报告不代表 C′ 混合架构已成为正式基线。
- Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署。
