# DKWS 数据分类与脱敏说明（M2-P4 / M2.9）

对应任务包：`M2-P4`，范围 `M2.9 数据分类与脱敏`。
依据：独立评审 L659（LLM 出站合规）、`ADR-013`、规格 `§9.20`（作业日志契约）。

> **非声明**：本文档不代表 DKWS 已生产就绪，不代表安全审计已完成，
> 不代表满足任何具体监管要求（如《个人信息保护法》合规认定需法务与合规部门评估）。

## 1. 设计原则

### 1.1 分类驱动而非散落规则

先给字段打上分类标记，再由策略决定各出站通道如何处理。
避免「哪里想到就在哪里加一条 if」导致规则漂移与遗漏。

| 等级 | 数值 | 含义 | 示例字段 |
|---|---|---|---|
| `PUBLIC` | 0 | 可公开 | — |
| `INTERNAL` | 1 | 内部标识 | `customerId`、`rmId` |
| `CONFIDENTIAL` | 2 | 商业敏感 | `creditCode`、`riskRating`、`creditLimit` |
| `RESTRICTED` | 3 | 个人隐私/监管强约束 | `idCardNo`、`mobile`、`bankAccount` |

数值越大越敏感，便于用「阈值」表达策略。

### 1.2 未知标记按较敏感处理

`Classification.parse()` 对无法识别的标记回落 `INTERNAL` 而非 `PUBLIC`。
理由：拼写错误（如 `RESTRICTEED`）不应导致意外泄漏。

### 1.3 出站点收口，内部保持明文

脱敏在**离开进程的边界**执行：API 响应、日志、LLM 提示词。
内部计算与产物始终用明文，因为：

- 脱敏后的数据无法用于业务逻辑（如按身份证号匹配客户）；
- 报告产物是审计留痕，需保留原文可追溯性；
- 一旦内部也脱敏，将无法区分「原本就没有」与「被掩码了」。

## 2. 掩码风格

| 风格 | 行为 | 适用 | 示例 |
|---|---|---|---|
| `FULL` | 完全替换 `***` | 凭据（无需核对） | `password` → `***` |
| `TAIL` | 保留尾部 N 位 | 手机号/账号（需核对） | `13812348000` → `*******8000` |
| `EDGES` | 保留首尾 N 位 | 姓名/企业名 | `华鑫轴承材料集团` → `华******团` |
| `SHAPE` | 仅暴露长度 | 完全不可见但需知存在 | `secret` → `<6字符>` |

### 2.1 长度保持（重要）

`TAIL`/`EDGES` 掩码后**长度与原值一致**。两个原因：

1. 便于运维核对「值是否存在、格式是否正常」；
2. 避免早期实现的缺陷——`keep` 为 0 或负数时曾产出 `'******abcdef'`，
   **长度翻倍且原值完整暴露**。现已修正为完全掩码且保持长度。

短值（长度 ≤ `keep`）同样完全掩码，不因保留位数大于长度而泄漏全部内容。

## 3. 值模式检测

无字段名线索时（自由文本、列表元素）按**值形态**识别：

| 模式 | 覆盖 | 掩码风格 |
|---|---|---|
| `id_card` | 18 位身份证号（末位可 X） | `TAIL` 4 |
| `credit_code` | 18 位统一社会信用代码 | `TAIL` 4 |
| `mobile` | 中国大陆手机号 | `TAIL` 4 |
| `bank_card` | 16~19 位银行卡号 | `TAIL` 4 |
| `email` | 邮箱 | `EDGES` 2 |

仅覆盖**高置信度强模式**，不触碰企业名等业务内容，
因此不会破坏报告正文的可读性。已用 5 种正常内容（`授信额度评估完成`、
`订单号 A12345`、`金额 1234.56 元` 等）验证**不误伤**。

## 4. 字段名规则优先于值模式（关键语义）

已登记字段**完全由其分类与阈值决定**，未达阈值即保留原文。

反例说明为何需要此优先级：`creditCode` 按字段名为 `CONFIDENTIAL`
（API 策略阈值 `RESTRICTED`，应保留），但其值形态又匹配 `credit_code`
值模式。若无优先级，该字段会被文本掩码意外命中，
造成「策略说保留、实际被掩码」的自相矛盾。

同一个值出现在**未登记字段**（如 `remark`）中时，仍按值模式掩码。

## 5. 预置策略

| 策略 | 阈值 | 文本掩码 | 用途 |
|---|---|---|---|
| `POLICY_API_RESPONSE` | `RESTRICTED` | **是** | API JSON 响应 |
| `POLICY_LOG` | `CONFIDENTIAL` | 是 | 结构化日志（留存久、暴露面大） |
| `POLICY_LLM` | `CONFIDENTIAL` | 是 | LLM 提示词出站（最严） |

### 5.1 为何 API 策略也启用文本掩码

手机号出现在 `note` 自由文本里与出现在 `mobile` 字段里**同样敏感**。
若只按字段名脱敏，会留下明显泄漏口。

> 此判断是在 E2E 验收中修正的：初版 API 策略 `mask_text=False`，
> 导致 `{"note": "联系 13812348000"}` 明文出站。已修正并加回归测试防护。

### 5.2 深度保护

`max_depth`（默认 16）限制递归深度，超出即停止并在报告中标记 `truncated`，
防御深层嵌套或环引用导致的栈溢出。

## 6. 出站通道接入

### 6.1 API 响应（`ResponseRedactionMiddleware`）

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_REDACT_RESPONSE` | **`false`** | 是否脱敏 JSON 响应 |
| `DKWS_REDACT_THRESHOLD` | `RESTRICTED` | 脱敏阈值 |
| `DKWS_REDACT_RESPONSE_TEXT` | `false` | 响应自由文本是否额外掩码 |

**默认关闭**：既有响应契约与测试依赖原文（例如报告正文含企业名），
全局脱敏会破坏门禁。生产可显式开启。

行为要点：

- 仅处理 `application/json`；Prometheus 文本、Markdown 报告、二进制**原样透传**
  （报告类产物的脱敏应在**生成阶段**按分类处理，而非在传输层粗暴替换）；
- 5xx 响应体不处理，避免二次处理掩盖原始错误；
- 声明 JSON 但内容不可解析时原样返回，不做猜测；
- 重算 `content-length`，避免响应截断；
- 有字段被掩码时在 `meta.redaction` 附说明（可关闭）。

### 6.2 LLM 提示词（`_call_model`）

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_LLM_REDACTION` | **`true`** | 是否在提示词出站前脱敏 |

**默认开启**（安全默认）：客户数据进入外部模型属重大合规风险（独立评审 L659）。
`_call_model` 是**唯一**的模型出站点，故在此收口。

**仅对外部适配器生效**：按类型判定（`isinstance(adapter, OpenAiCompatibleLlmAdapter)`）
而非字符串比较。`DeterministicLlmAdapter` 与库内检索不出网，
对其脱敏只会降低结果质量。

脱敏动作在 `assemblyTrace` 留 `llm_redaction` 阶段记录，可审计。
无敏感内容时不产生该记录，避免噪声。

### 6.3 日志

三层纵深防御，叠加使用：

| 层 | 实现 | 作用范围 |
|---|---|---|
| 键名匹配 | `logging.mask_sensitive` | §9.20 文件日志（**未改动**） |
| 正文正则 | `observability.redact_message` | stdout JSON 日志 |
| 分类结构化 | `classification.redact_structure` | 结构化字段（本次新增） |

## 7. 配置示例

```bash
# 生产：响应脱敏 + LLM 脱敏 + 结构化日志
export DKWS_PROFILE=prod
export DKWS_REDACT_RESPONSE=true
export DKWS_REDACT_THRESHOLD=RESTRICTED
export DKWS_LLM_REDACTION=true
export DKWS_STRUCTURED_LOGS=true
python scripts/serve_skill_service.py --workspace ./workspace --host 127.0.0.1

# 内网自建模型：可关闭 LLM 脱敏以保留完整上下文
export DKWS_LLM_REDACTION=false
```

## 8. 分类清单维护

`classification_inventory()` 导出全部规则，可用于生成合规文档与人工评审。
清单按字段名排序，便于 diff 审查。当前 31 条：
`RESTRICTED` 20 条、`CONFIDENTIAL` 8 条、`INTERNAL` 3 条。

导出样例见 `evidence/m2-p4/classification_inventory.json`。

**新增字段时**：在 `FIELD_RULES` 中登记（必须带中文 `note`），
或依赖后缀匹配（如 `customerMobile` 自动命中 `mobile` 规则）。

## 9. 已知限制与遗留项

| 项 | 说明 | 归属 |
|---|---|---|
| 正则启发式，非语义识别 | 无法覆盖全部密钥/PII 形态；姓名、地址等自由文本中的 PII 需 NER 才能可靠识别 | 后续（需引入模型，成本与收益待评估） |
| 报告产物未脱敏 | Markdown 报告在生成阶段保留原文（审计需要）；若需脱敏版本应另生成 | 后续 |
| 字段清单需人工维护 | 新增数据结构时需同步登记，否则按 `INTERNAL` 默认处理 | 流程约束 |
| 无字段级权限 | 当前按分类统一脱敏，未实现「按调用方角色返回不同字段」 | M3+ |
| 无脱敏审计留痕落库 | 脱敏动作仅记日志与 `meta.redaction`，未写入审计表 | 后续 |
| 合规认定需法务评估 | 本实现是技术手段，不构成对任何法规的合规认定 | **非本任务包能力范围** |
