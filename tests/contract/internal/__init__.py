"""JR-1 内部契约测试包（Python 侧 consumer/provider contract tests）。

覆盖 ``docs/contracts/internal/`` 下 DKWS Skill Runtime 内部契约：

- 6 份 JSON Schema 可解析且自身合法
- 12 份示例通过对应 Schema
- 未知字段策略（``additionalProperties: false``）
- 必填字段缺失
- 同 key 不同 payload 的幂等冲突语义
"""
