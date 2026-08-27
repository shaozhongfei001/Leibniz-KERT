# M2-P4 证据清单

- **任务包**：`M2-P4`
- **范围**：`M2.9 数据分类与脱敏`
- **分支**：`feature/m2-remaining`（基线 `develop` @ `4b28a7d`）
- **生成时间**：2026-08-27

> **非声明**
> - 本次不代表 DKWS 已生产就绪。
> - 本次不代表 GITS UAT 已通过。
> - 本次不代表安全审计已完成。
> - **本次不构成对任何法规（含《个人信息保护法》）的合规认定**——
>   本实现是技术手段，合规认定需法务与合规部门评估。
> - 本次不代表 C′ 受控混合架构已成为正式基线。
> - Tech Lead 自验不代替 Owner 或 Independent QA 签署。

## 1. 验收标准对照

WBS 验收标准：**脱敏测试通过**。

| 标准 | 实现 | 证据 |
|---|---|---|
| 字段敏感标记 | 4 级分类 + 31 条字段规则（含中文说明） | E2E 检查 1；`test_classification.py` 分类组 |
| 日志脱敏 | 三层纵深（键名 / 正文正则 / 分类结构化） | E2E 检查 21；M2-P3 已有键名与正则两层 |
| 响应脱敏 | `ResponseRedactionMiddleware`（默认关闭，生产可开） | E2E 检查 17-20；`test_redaction.py` 响应组 |
| **LLM 出站脱敏** | `_call_model` 单点收口，默认开启 | E2E 检查 12-15；独立评审 L659 要求 |
| 脱敏测试通过 | 90 个测试函数（收集 136 项） | `logs/pytest_*.log` |

## 2. 环境版本

| 项 | 值 |
|---|---|
| Python | 3.12.8（`.venv`） |
| 平台 | Linux |
| **新增第三方依赖** | **无**（纯 stdlib `re`/`dataclasses`/`enum`） |
| `pyproject.toml` | **未改动** |

## 3. 测试命令与结果

| 命令 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| `python -m pytest tests -v` | **738 passed** / 0 failed / 0 skipped | 0 | `logs/pytest_all.log` |
| `python -m pytest tests/unit -v` | 361 passed | 0 | `logs/pytest_unit.log` |
| `python -m pytest tests/integration -v` | 269 passed | 0 | `logs/pytest_integration.log` |
| `python -m pytest tests/security -v` | 36 passed | 0 | `logs/pytest_security.log` |
| `python -m pytest tests/recovery -v` | 18 passed | 0 | `logs/pytest_recovery.log` |
| `python scripts/verify_m2p4_redaction.py` | **22/22 → PASS** | 0 | `e2e_redaction_report.json` |
| `ruff check <改动文件>` | All checks passed | 0 | — |

### 3.1 门禁未降低

| 项 | M2-P3 基线 | 本次 |
|---|---|---|
| 全量测试通过数 | 602 | **738** |
| 失败 / 跳过 | 0 / 0 | 0 / 0 |
| 新增测试 | — | **136**（90 个函数，含参数化展开） |

### 3.2 新增测试分布

| 文件 | 函数数 | 覆盖内容 |
|---|---|---|
| `tests/unit/test_classification.py` | 65 | 分类别名解析（14 种写法）、掩码 4 风格与边界（含泄漏回归防护）、字段规则与后缀匹配、值模式（5 类敏感 + 5 类正常不误伤）、结构脱敏（嵌套/列表/深度保护/不可变性）、字段名优先级、LLM 出站、策略配置 |
| `tests/integration/test_redaction.py` | 25 | 配置默认值与环境覆盖、响应中间件（信封完整/content-length/非 JSON 透传）、LLM 出站（外部脱敏/本地不脱敏/开关生效/trace 留痕）、既有行为不破坏 |

## 4. E2E 验收（真实进程）

脚本 `scripts/verify_m2p4_redaction.py`，**22/22 全部通过**：

| # | 检查项 | 观测结果 |
|---|---|---|
| 1 | `classification_inventory_exportable` | 31 条规则，`{RESTRICTED: 20, CONFIDENTIAL: 8, INTERNAL: 3}`，全部含中文说明 |
| 2 | `unknown_classification_fails_safe` | 未知标记回落 `INTERNAL`，不当作 `PUBLIC` |
| 3 | `mask_styles_correct` | 保留尾部可核对且长度不变 |
| 4 | `mask_boundary_no_leak` | `keep=0`/`keep=-3` 均完全掩码 |
| 5 | `mask_short_value_no_leak` | 短值 `'123'` → `'***'` |
| 6 | `api_policy_masks_restricted` | 掩码 5 个 RESTRICTED 字段（含嵌套与列表元素） |
| 7 | `api_policy_preserves_confidential` | 保留 `creditCode` 与 `customerId` |
| 8 | `llm_policy_stricter_than_api` | LLM 掩码 7 个 > API 掩码 5 个 |
| 9 | `llm_policy_masks_free_text` | `note='联系 *******8000'` |
| 10 | `redaction_does_not_mutate_input` | 入参未被修改 |
| 11 | `redaction_depth_guard` | 40 层嵌套触发 `truncated` |
| 12 | `llm_external_prompt_redacted` | 外部适配器收到脱敏提示词 |
| 13 | `llm_redaction_traced` | `assemblyTrace` 含 `llm_redaction` |
| 14 | `llm_local_prompt_not_redacted` | 本地适配器收到原文 |
| 15 | `llm_redaction_switch_effective` | 关闭后原文出站 |
| 16 | `server_starts_with_redaction` | prod + 响应脱敏 + LLM 脱敏组合正常启动 |
| 17 | `response_envelope_intact` | 信封结构完整 |
| 18 | `content_length_correct` | `content-length=467` 与实际字节一致 |
| 19 | `non_json_passthrough` | Prometheus 文本原样透传 |
| 20 | `probes_work_with_redaction` | 探针正常 |
| 21 | `logs_no_sensitive_leak` | 日志无 API Key 与敏感值明文 |
| 22 | `internal_artifacts_keep_plaintext` | Skill 执行成功，内部产物保持明文 |

### 原始日志与导出

| 文件 | 内容 |
|---|---|
| `logs/01_server_redact_on.log` | 生产 profile + 全脱敏开启的真实服务 stdout |
| `classification_inventory.json` | 31 条字段分类清单（合规文档基础） |
| `logs/pytest_*.log` | 全量 + 四套件测试日志 |

## 5. Loop Engineering 记录（发现并修复 3 个真实缺陷）

### 5.1 掩码边界泄漏（严重）

`mask_value(..., keep=0)` 或 `keep<0` 时产出 `'******abcdef'`——
**长度翻倍且原值完整暴露**。

- 发现方式：单元测试 `test_negative_keep_treated_as_zero` 失败
- 修复：`keep==0` 或值过短时返回等长星号
- 防护：新增 `test_zero_keep_masks_fully` 与 E2E 检查 4

### 5.2 自由文本 PII 泄漏（严重）

初版 API 策略 `mask_text=False`，导致 `{"note": "联系 13812348000"}` 明文出站。

- 发现方式：E2E 检查 6 失败（5 个字段已掩码但断言不通过）
- 判断：手机号在 `note` 里与在 `mobile` 里**同样敏感**，原权衡是错的
- 修复：API 策略改为 `mask_text=True`，仅覆盖高置信度强模式
- 防护：`test_api_policy_also_masks_free_text` +
  `test_api_policy_text_masking_spares_business_content`（验证不误伤业务内容）

### 5.3 字段名规则与值模式冲突

`creditCode` 按字段名为 `CONFIDENTIAL`（API 策略应保留），
但值形态匹配 `credit_code` 模式，被文本掩码意外命中——策略语义自相矛盾。

- 发现方式：修 5.2 后连带失败
- 修复：确立**字段名规则优先于值模式**，已登记字段完全由其分类决定
- 防护：`test_field_rule_takes_precedence_over_value_pattern`
  （同时验证同一值在未登记字段中仍被掩码）

### 5.4 分类别名规范化不足

`RE-STRICTED` 被规范化为 `RE_STRICTED`，别名表未命中，误判为 `INTERNAL`。

- 修复：连字符/下划线/空白一并去除；补 `PERSONALINFO` 别名

## 6. 变更文件清单

### 6.1 新增（源码）

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/dkws/infrastructure/classification.py` | ~430 | 分类等级、掩码风格、31 条字段规则、5 类值模式、脱敏策略与递归引擎 |

### 6.2 修改（源码）

| 文件 | 变更 |
|---|---|
| `src/dkws/infrastructure/runtime_config.py` | 新增 `RedactionConfig`（6 字段）并接入 `RuntimeConfig` 与 loader（4 个环境变量） |
| `src/dkws/api/middleware.py` | 新增 `ResponseRedactionMiddleware` |
| `src/dkws/api/server.py` | 装配响应脱敏中间件；向 Service 传 `llm_redaction` |
| `src/dkws/application/skills.py` | `_call_model` 接入 LLM 出站脱敏；新增 `_is_external_adapter()` 与 `llm_redaction` 参数 |

### 6.3 新增（测试）

- `tests/unit/test_classification.py`（65 函数）
- `tests/integration/test_redaction.py`（25 函数）

### 6.4 新增（文档 / 工具）

- `docs/architecture/DKWS_DATA_CLASSIFICATION_M2P4.md`
- `scripts/verify_m2p4_redaction.py`
- `evidence/m2-p4/**`

## 7. 关键设计取舍

| 决策 | 理由 |
|---|---|
| 响应脱敏**默认关闭** | 既有响应契约与测试依赖原文（报告正文含企业名）；全局开启会破坏门禁。生产显式开启。 |
| LLM 脱敏**默认开启** | 客户数据进外部模型属重大合规风险（独立评审 L659），采取安全默认。 |
| 仅对**外部**适配器脱敏 | 本地 `DeterministicLlmAdapter` 不出网，脱敏只会降低结果质量。按类型判定而非字符串。 |
| 内部产物保持明文 | 脱敏后数据无法用于业务逻辑（如按身份证匹配）；报告是审计留痕需可追溯。 |
| 非 JSON 响应原样透传 | 报告类产物的脱敏应在**生成阶段**按分类处理，而非传输层粗暴替换。 |
| 未知分类回落 `INTERNAL` | 拼写错误不应导致意外泄漏（不当作 `PUBLIC`）。 |

## 8. 约束遵守自查

| 约束 | 状态 |
|---|---|
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | 遵守（纯 stdlib） |
| 不把 SQLite 变成知识权威源 | 遵守（未触碰 Store schema） |
| 不修改 GITS | 遵守 |
| 不修改 Java Runtime 生产边界 | 遵守（`poc/` 零改动） |
| 不降低现有测试门禁 | 遵守（602 → 738） |
| 不改动 §9.20 文件日志契约 | 遵守（`logging.py` 未改） |
| 不直接 push main / 不自行 merge | 遵守 |

## 9. 已知限制与遗留项

| 项 | 说明 | 归属 |
|---|---|---|
| 正则启发式，非语义识别 | 姓名、地址等自由文本 PII 需 NER 才能可靠识别 | 后续（需评估引入模型的成本收益） |
| 报告产物未脱敏 | Markdown 报告生成阶段保留原文（审计需要） | 后续 |
| 字段清单需人工维护 | 新增数据结构时需同步登记，否则按 `INTERNAL` 处理 | 流程约束 |
| 无字段级权限 | 未实现「按调用方角色返回不同字段」 | M3+ |
| 无脱敏审计落库 | 仅记日志与 `meta.redaction`，未写审计表 | 后续 |
| **合规认定需法务评估** | 本实现是技术手段，不构成任何法规的合规认定 | **非本任务包能力范围** |
