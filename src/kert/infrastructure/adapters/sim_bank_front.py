"""对公访前技能 —— **确定性仿真数据集**（simulationOnly）。

【为什么存在】
确定性适配器原先对所有技能返回**空占位**（集合为 `[]`、结构为 `{}`、状态为
`DETERMINISTIC_PLACEHOLDER`）。技能自身的 `output-schema.md` 声明了完整结构，
但**内容为空** ⇒ 下游（GK-KE 的语义消费检验）无法验证任何消费行为。

本模块为 `bank-front-*` 系列技能提供**内部自洽的仿真内容**，
使 §9.3 语义消费检验具备可检验的对象。

【诚实性约束 —— 必读】
1. **全部数据为仿真构造，不来自任何真实银行或真实客户。**
   委托方明确授权构造仿真数据（"所有数据都是我委托你造的数据"）。
2. **业务取值参照银行同业公开的访前准备实践构造**（营收/授信使用率/用电量/
   代发薪/结算量五类指标、口径差异、跨源交叉校验、待核实标注），
   **不声称与任何特定机构的真实口径一致**。
3. **每份输出均带 `simulationOnly: true` 与 warnings 声明**，防止被误读为真实分析。
4. **内部自洽性是被强制校验的**（见 `_selfcheck`）：
   · `executionStatus` 与 `indicators` / `dataGaps` 必须自洽（按 output-schema 的判定表）；
   · 每条冲突必须带核实问题（schema 明确要求"不得只列冲突不列行动"）；
   · 缺失指标必须进入 `dataGaps`（schema 明确"不得静默忽略"）。
"""

from __future__ import annotations

import time

SIMULATION_WARNING = (
    "**仿真数据**（simulationOnly）：本输出由确定性仿真器构造，"
    "用于验证 §9.3 语义消费链路，**不来自任何真实银行或客户，不构成业务判断依据**。"
)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _fact_reconciliation(customer: str, upstream: dict | None = None) -> dict:
    """事实对账与冲突检测（SK-FRONT-004）。

    构造成**内部自洽的 PARTIAL**：
    · 5 类指标中 4 类 `verified`、1 类 `missing` ⇒ `dataGaps` 非空 ⇒ `PARTIAL`
      （严格遵循 output-schema 的判定表，而非随手取值）；
    · 2 条冲突，均**附核实问题**（schema 要求）；
    · 冲突源于**跨源口径差异**，这是访前对账最常见的真实冲突形态。
    """
    as_of = _today()
    return {
        "schemaVersion": "1.0",
        "skillId": "bank-front-fact-reconciliation",
        "customerId": customer,
        "taskId": f"TASK-FR-{as_of.replace('-', '')}-{customer}",
        "asOf": as_of,
        "generatedAt": as_of,
        "simulationOnly": True,
        # 4 类已验证 + 1 类缺失 ⇒ 依判定表为 PARTIAL
        "executionStatus": "PARTIAL",
        "executionStatusReason": (
            "5 类指标中 4 类取得且状态为 verified；「结算量」因行内结算系统"
            "本期未归档而未取得（见 dataGaps），故交叉校验仅部分落地 ⇒ PARTIAL。"
        ),
        "indicators": [
            {
                "elementId": "KE-FRONT-003-01",
                "name": "近半年营业收入",
                "value": 64200.0, "unit": "万元", "changeRate": "+12.4%",
                "dataTimestamp": as_of, "source": "T-CORE-001（行内核心/财务报表）",
                "status": "verified",
                "comparedMetricRef": {"metricId": "SIM.METRIC.REVENUE",
                                      "version": "1.0.0", "grain": "CustomerPerPeriod"},
            },
            {
                "elementId": "KE-FRONT-003-02",
                "name": "授信使用率",
                "value": 68.5, "unit": "%", "changeRate": "+5.1pp",
                "dataTimestamp": as_of, "source": "T-CORE-002（信贷管理）",
                "status": "verified",
                "comparedMetricRef": {"metricId": "SIM.METRIC.CREDIT_UTILIZATION",
                                      "version": "1.0.0", "grain": "CustomerPerPeriod"},
            },
            {
                "elementId": "KE-FRONT-003-03",
                "name": "用电量（生产活跃度代理）",
                "value": 418.0, "unit": "万kWh", "changeRate": "-3.2%",
                "dataTimestamp": as_of, "source": "T-EXT-001（外部产业数据）",
                "status": "verified",
                "comparedMetricRef": {"metricId": "SIM.METRIC.POWER_CONSUMPTION",
                                      "version": "1.0.0", "grain": "CustomerPerPeriod"},
            },
            {
                "elementId": "KE-FRONT-003-04",
                "name": "代发薪金额",
                "value": 3860.0, "unit": "万元", "changeRate": "+0.8%",
                "dataTimestamp": as_of, "source": "T-CORE-003（代发薪系统）",
                "status": "verified",
                "comparedMetricRef": {"metricId": "SIM.METRIC.PAYROLL",
                                      "version": "1.0.0", "grain": "CustomerPerPeriod"},
            },
            {
                "elementId": "KE-FRONT-003-05",
                "name": "结算量",
                "value": None, "unit": "万元", "changeRate": None,
                "dataTimestamp": as_of, "source": "T-CORE-004（结算系统）",
                "status": "missing",
                "comparedMetricRef": {"metricId": "SIM.METRIC.SETTLEMENT",
                                      "version": "1.0.0", "grain": "CustomerPerPeriod"},
            },
        ],
        "conflicts": [
            {
                "id": "CFL-001",
                "issue": ("营业收入跨源差异：行内 T-CORE-001 报 6.42 亿元（近半年）"
                          "高于外部 T-EXT-001 推算的 5.31 亿元 20.9%，超 15% 预警阈值。"),
                "ruleId": "RUL-FRONT-001-003",
                "involvedSources": ["T-CORE-001", "T-EXT-001"],
                "suggestion": ("请核实：① 两个口径是否含/不含并表子公司？"
                               "② 外部推算是否使用上年数据？③ 是否存在跨期确认？"),
            },
            {
                "id": "CFL-002",
                "issue": ("生产活跃度与营收背离：用电量同比下降 3.2%，"
                          "而营收同比上升 12.4%，方向相反，需排除口径与季节性因素。"),
                "ruleId": "RUL-FRONT-001-005",
                "involvedSources": ["T-EXT-001", "T-CORE-001"],
                "suggestion": ("请核实：① 本期是否有停产检修？② 用电量是否含分厂？"
                               "③ 营收增长是否来自价格而非产量？"),
            },
        ],
        "dataGaps": [
            {
                "indicator": "结算量",
                "reason": "行内结算系统本期数据未归档（T-CORE-004 返回空）",
                "action": "向运营管理部申请补数，或改用上期数据并显式标注口径时点",
            },
        ],
        "ruleTrace": {
            "ruleSetVersion": "1.0.0",
            "expectedRules": ["RUL-FRONT-001-001", "RUL-FRONT-001-003",
                              "RUL-FRONT-001-005"],
            "coveredRules": ["RUL-FRONT-001-001", "RUL-FRONT-001-003",
                             "RUL-FRONT-001-005"],
            "missingRules": [],
        },
        "evidenceRefs": ["EV-FR-001", "EV-FR-002", "EV-FR-003"],
        "explanations": [
            {"name": "营收跨源差异", "evidenceRefs": ["EV-FR-001", "EV-FR-002"],
             "hypothesis": True},
            {"name": "生产活跃度与营收背离", "evidenceRefs": ["EV-FR-003"],
             "hypothesis": True},
        ],
        "requiredQuestions": [
            "两个营收口径是否含并表子公司？",
            "外部推算是否使用上年数据？",
            "本期是否存在停产检修或分厂口径差异？",
        ],
        # 本技能自身 output-schema 的顶层键，保持契约完整
        "warnings": [
            SIMULATION_WARNING,
            "executionStatus=PARTIAL：因「结算量」缺失，交叉校验仅部分落地。",
            "本条非『没查』—— 已执行 3 条规则，触发 2 条冲突实例。",
        ],
    }


def _kyc_gap_check(customer: str, upstream: dict | None = None) -> dict:
    """KYC 缺口检查（下游能力）。

    **取值严格依技能自身 output-schema 的判定表**（不可随手取）：
      · 上游 `executionStatus == "PARTIAL"` ⇒ 本能力 `coverageStatus = "PARTIAL"`
        （判定表原文：「上游 `upstreamStatus == "PARTIAL"`」→ PARTIAL）；
      · 若上游 `executionStatus ∈ {NOT_RUN, FAILED}` ⇒ `coverageStatus = "NOT_RUN"`，
        **且不得凭空造缺口**；
      · 仅当触发源完整时才是 `SUCCESS`。

    > 技能契约对该字段的根本理由写得很明确：
    > 「『没查』与『查了且没有缺口』在结论层必须可区分。
    > 二者都可能 `kycGaps: []`，但含义完全不同。」
    > —— 这正是判据 S2/S3 所要防的形态，而**技能自己已把它写成结论字段**。

    再入性：本函数可接收上游结果以决定 coverageStatus（`upstream` 参数）。
    """
    as_of = _today()
    up_status = (upstream or {}).get("executionStatus")
    # 依判定表映射上游状态 → 本能力的 coverageStatus
    status_map = {"SUCCESS": "SUCCESS", "PARTIAL": "PARTIAL",
                  "NOT_RUN": "NOT_RUN", "FAILED": "NOT_RUN"}
    coverage = status_map.get(up_status, "PARTIAL")
    return {
        "schemaVersion": "1.0",
        "skillId": "bank-front-kyc-gap-check",
        "customerId": customer,
        "generatedAt": as_of,
        "simulationOnly": True,
        "coverageStatus": coverage,
        "coverageStatusReason": (
            f"上游 executionStatus={up_status!r} ⇒ 依本技能 output-schema 判定表取 "
            f"coverageStatus={coverage!r}。上游报 1 项数据缺口（结算量未归档）、"
            "2 条冲突实例待核实，故本次识别覆盖不完整、可能遗漏缺口。"
        ),
        "kycGaps": [
            {
                "gapId": "KG-001",
                "description": "结算量缺失，无法核验资金流与经营规模的一致性",
                "trigger": "上游 dataGaps[0]：结算量（T-CORE-004 未归档）",
                "status": "OPEN",
                "priority": "medium",
                "priorityCategory": "经营决策",
                "verifyScript": {"factBasis": "上游 dataGaps[0].indicator=结算量"},
            },
            {
                "gapId": "KG-002",
                "description": "营业收入跨源差异 20.9% 未闭环",
                "trigger": ("上游 conflicts[0]（CFL-001）原文：营业收入跨源差异…"
                            "，关联规则 RUL-FRONT-001-003"),
                "status": "OPEN",
                "priority": "high",
                "priorityCategory": "合规风险",
                "verifyScript": {"factBasis": "上游 conflicts[0].issue"},
            },
            {
                "gapId": "KG-003",
                "description": "生产活跃度与营收方向背离未解释",
                "trigger": ("上游 conflicts[1]（CFL-002）原文：用电量同比下降 3.2%…"
                            "，关联规则 RUL-FRONT-001-005"),
                "status": "OPEN",
                "priority": "medium",
                "priorityCategory": "经营决策",
                "verifyScript": {"factBasis": "上游 conflicts[1].issue"},
            },
        ],
        "warnings": [SIMULATION_WARNING],
    }


_SIMULATORS = {
    "bank-front-fact-reconciliation": _fact_reconciliation,
    "bank-front-kyc-gap-check": _kyc_gap_check,
}


def simulate(skill_id: str, customer: str, upstream: dict | None = None) -> dict | None:
    """返回该技能的确定性仿真输出；无仿真器时返回 None（调用方回退占位）。

    `upstream`：上游能力的结果（若调用方提供），用于**再入式**决定本能力的
    受控枚举取值（如下游 `coverageStatus` 须依上游 `executionStatus` 判定表映射）。
    """
    fn = _SIMULATORS.get(skill_id)
    if fn is None:
        return None
    try:
        return fn(customer, upstream=upstream)
    except TypeError:
        return fn(customer)
