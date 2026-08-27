"""数据分类与脱敏（M2.9）。

设计原则
--------
1. **分类驱动**：先给字段打上分类标记（``PUBLIC``/``INTERNAL``/``CONFIDENTIAL``/
   ``RESTRICTED``），再由策略决定各出站通道如何处理，避免散落的硬编码规则。
2. **出站点收口**：脱敏在**离开进程的边界**执行——API 响应、日志、LLM 提示词、
   报告产物。内部计算始终用明文，避免脱敏破坏业务逻辑（如按身份证号匹配）。
3. **默认不改既有响应**：API 响应脱敏**默认关闭**（``dev`` 与既有测试依赖原文），
   生产 profile 可显式开启。这样引入分类体系不会破坏现有门禁。
4. **保留可诊断性**：掩码保留尾部若干位与类型信息（如 ``手机号: 138****8000``），
   使运维仍可核对，同时不泄漏完整值。

与既有脱敏的关系
----------------
- :mod:`dkws.infrastructure.logging` 的 ``mask_sensitive`` 按**键名**脱敏，
  作用于 §9.20 文件日志，**不改动**；
- :mod:`dkws.infrastructure.observability` 的 ``redact_message`` 按**正文正则**脱敏，
  作用于 stdout JSON 日志；
- 本模块提供**按分类**的结构化脱敏，是上述两者的补充与统一策略层。
  三者叠加使用，形成纵深防御。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

# ---------------------------------------------------------------- 分类等级


class Classification(IntEnum):
    """数据分类等级（数值越大越敏感，便于比较与阈值判断）。

    与 ``docs/`` 中知识资产的 ``classification`` front-matter 保持同名，
    并额外引入 ``RESTRICTED`` 表达「个人隐私/监管强约束」层级。
    """

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3

    @classmethod
    def parse(cls, raw: str | int | None, default: Classification = None
              ) -> Classification:
        """宽松解析分类标记；无法识别时返回 ``default``（缺省 ``INTERNAL``）。

        采取「无法识别按较敏感处理」的保守策略：未知标记不应被当作 PUBLIC，
        否则拼写错误会导致意外泄漏。
        """
        fallback = cls.INTERNAL if default is None else default
        if raw is None or raw == "":
            return fallback
        if isinstance(raw, int) and not isinstance(raw, bool):
            try:
                return cls(raw)
            except ValueError:
                return fallback
        # 去除连字符/下划线/空白，使 RE-STRICTED、RE_STRICTED 等写法均可识别
        text = re.sub(r"[-_\s]", "", str(raw).strip().upper())
        aliases = {
            "PUBLIC": cls.PUBLIC, "公开": cls.PUBLIC,
            "INTERNAL": cls.INTERNAL, "内部": cls.INTERNAL,
            "CONFIDENTIAL": cls.CONFIDENTIAL, "保密": cls.CONFIDENTIAL,
            "SECRET": cls.CONFIDENTIAL,
            "RESTRICTED": cls.RESTRICTED, "受限": cls.RESTRICTED,
            "PII": cls.RESTRICTED, "个人信息": cls.RESTRICTED,
            "PERSONALINFO": cls.RESTRICTED,
        }
        return aliases.get(text, fallback)


# ---------------------------------------------------------------- 掩码策略


class MaskStyle(IntEnum):
    """掩码风格。"""

    #: 完全替换为 ***（用于密钥等无需核对的值）
    FULL = 0
    #: 保留尾部若干位（用于手机号/账号等需核对的值）
    TAIL = 1
    #: 保留首尾（用于姓名/企业名）
    EDGES = 2
    #: 仅标注类型与长度，不保留任何原字符
    SHAPE = 3


#: 掩码占位符
MASK_TOKEN = "***"


def mask_value(value, *, style: MaskStyle = MaskStyle.FULL, keep: int = 4) -> str:
    """按风格掩码单个值。

    Args:
        value: 原始值（非字符串会先转为字符串）。
        style: 掩码风格。
        keep: ``TAIL``/``EDGES`` 风格下保留的字符数。

    Returns:
        掩码后的字符串。

    Examples:
        >>> mask_value("13812348000", style=MaskStyle.TAIL)
        '*******8000'
        >>> mask_value("华鑫轴承材料集团", style=MaskStyle.EDGES, keep=1)
        '华******团'
    """
    text = "" if value is None else str(value)
    if not text:
        return MASK_TOKEN
    if style is MaskStyle.FULL:
        return MASK_TOKEN
    if style is MaskStyle.SHAPE:
        return f"<{len(text)}字符>"
    keep = max(0, int(keep))
    if style is MaskStyle.TAIL:
        if keep == 0 or len(text) <= keep:
            # keep 为 0 或值过短时完全掩码，且保持长度不变（避免泄漏与长度膨胀）
            return "*" * len(text)
        return "*" * (len(text) - keep) + text[-keep:]
    # EDGES
    if keep == 0 or len(text) <= keep * 2:
        return "*" * len(text)
    return text[:keep] + "*" * (len(text) - keep * 2) + text[-keep:]


@dataclass(frozen=True)
class FieldRule:
    """单个字段的分类与掩码规则。

    Attributes:
        classification: 字段分类等级。
        style: 掩码风格。
        keep: 保留字符数。
        note: 说明（用于生成分类清单文档）。
    """

    classification: Classification
    style: MaskStyle = MaskStyle.FULL
    keep: int = 4
    note: str = ""


#: 字段名 → 规则。键为**小写**字段名，匹配时忽略大小写与下划线/连字符差异。
#:
#: 字段来源于真实数据结构（examples/output/gits-crm-customer-master.json、
#: 客户知识库投影、Skill 请求体），不做臆测。
FIELD_RULES: dict[str, FieldRule] = {
    # ---- RESTRICTED：个人隐私与监管强约束 ----
    "idcardno": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "身份证号"),
    "idcard": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "身份证号"),
    "idnumber": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "身份证号"),
    "mobile": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "手机号"),
    "phone": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "电话"),
    "telephone": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "电话"),
    "contactphone": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "联系电话"),
    "email": FieldRule(Classification.RESTRICTED, MaskStyle.EDGES, 2, "邮箱"),
    "bankaccount": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "银行账号"),
    "accountno": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "账号"),
    "cardno": FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "卡号"),
    "address": FieldRule(Classification.RESTRICTED, MaskStyle.EDGES, 3, "地址"),
    "homeaddress": FieldRule(Classification.RESTRICTED, MaskStyle.EDGES, 3, "住址"),
    # ---- CONFIDENTIAL：商业敏感 ----
    "creditcode": FieldRule(Classification.CONFIDENTIAL, MaskStyle.TAIL, 4,
                            "统一社会信用代码"),
    "unifiedsocialcreditcode": FieldRule(Classification.CONFIDENTIAL,
                                         MaskStyle.TAIL, 4, "统一社会信用代码"),
    "taxno": FieldRule(Classification.CONFIDENTIAL, MaskStyle.TAIL, 4, "税号"),
    "legalperson": FieldRule(Classification.CONFIDENTIAL, MaskStyle.EDGES, 1,
                             "法定代表人"),
    "creditlimit": FieldRule(Classification.CONFIDENTIAL, MaskStyle.FULL, 0,
                             "授信额度"),
    "balance": FieldRule(Classification.CONFIDENTIAL, MaskStyle.FULL, 0, "余额"),
    "revenue": FieldRule(Classification.CONFIDENTIAL, MaskStyle.FULL, 0, "营收"),
    "riskrating": FieldRule(Classification.CONFIDENTIAL, MaskStyle.FULL, 0, "风险评级"),
    # ---- 凭据类：一律 FULL ----
    "password": FieldRule(Classification.RESTRICTED, MaskStyle.FULL, 0, "口令"),
    "token": FieldRule(Classification.RESTRICTED, MaskStyle.FULL, 0, "令牌"),
    "apikey": FieldRule(Classification.RESTRICTED, MaskStyle.FULL, 0, "API 密钥"),
    "secret": FieldRule(Classification.RESTRICTED, MaskStyle.FULL, 0, "密钥"),
    "credential": FieldRule(Classification.RESTRICTED, MaskStyle.FULL, 0, "凭据"),
    "authorization": FieldRule(Classification.RESTRICTED, MaskStyle.FULL, 0, "授权头"),
    "privatekey": FieldRule(Classification.RESTRICTED, MaskStyle.FULL, 0, "私钥"),
    # ---- INTERNAL：内部标识（默认不脱敏，仅登记分类） ----
    "customerid": FieldRule(Classification.INTERNAL, MaskStyle.FULL, 0, "客户号"),
    "rmid": FieldRule(Classification.INTERNAL, MaskStyle.FULL, 0, "客户经理号"),
    "customername": FieldRule(Classification.INTERNAL, MaskStyle.EDGES, 1, "客户名称"),
}


def _normalize_key(name: str) -> str:
    """规范化字段名：小写、去下划线与连字符，便于宽松匹配。"""
    return re.sub(r"[_\-\s]", "", str(name)).lower()


def lookup_rule(field_name: str) -> FieldRule | None:
    """查找字段规则；先精确匹配，再做后缀包含匹配。

    后缀包含匹配用于覆盖 ``customerMobile``、``contact_email`` 这类复合名，
    避免为每种前缀组合重复登记。
    """
    key = _normalize_key(field_name)
    rule = FIELD_RULES.get(key)
    if rule is not None:
        return rule
    for candidate, candidate_rule in FIELD_RULES.items():
        # 仅当字段名以已登记名结尾时才命中，避免 "id" 误伤 "idcardno" 之外的字段
        if len(candidate) >= 5 and key.endswith(candidate):
            return candidate_rule
    return None


def classify_field(field_name: str) -> Classification:
    """返回字段分类；未登记字段视为 ``INTERNAL``（保守默认）。"""
    rule = lookup_rule(field_name)
    return rule.classification if rule else Classification.INTERNAL


# ---------------------------------------------------------------- 值模式检测

#: 无字段名线索时按**值形态**识别敏感内容（用于自由文本与列表元素）
VALUE_PATTERNS: tuple[tuple[str, re.Pattern, MaskStyle, int], ...] = (
    # 身份证号：18 位，末位可为 X
    ("id_card", re.compile(r"\b\d{17}[\dXx]\b"), MaskStyle.TAIL, 4),
    # 统一社会信用代码：18 位大写字母数字
    ("credit_code", re.compile(r"\b[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}\b"),
     MaskStyle.TAIL, 4),
    # 中国大陆手机号
    ("mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), MaskStyle.TAIL, 4),
    # 银行卡号：16~19 位连续数字
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)"), MaskStyle.TAIL, 4),
    # 邮箱
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), MaskStyle.EDGES, 2),
)


def detect_value_patterns(text: str) -> tuple[str, ...]:
    """返回文本中命中的敏感值模式名（用于审计与告警，不改内容）。"""
    if not text:
        return ()
    return tuple(name for name, pattern, _, _ in VALUE_PATTERNS
                 if pattern.search(text))


def mask_text_patterns(text: str) -> str:
    """按值形态掩码自由文本中的敏感内容。

    用于无字段名线索的场景（报告正文、LLM 提示词、自由文本备注）。
    仅替换命中片段，保留其余上下文以维持可读性。
    """
    if not text:
        return text
    result = text
    for _, pattern, style, keep in VALUE_PATTERNS:
        # 默认参数绑定当前循环值，避免闭包延迟绑定导致全部使用最后一组参数
        def _sub(match, _style=style, _keep=keep):
            """按当前模式的风格掩码命中片段。"""
            return mask_value(match.group(0), style=_style, keep=_keep)

        result = pattern.sub(_sub, result)
    return result


# ---------------------------------------------------------------- 脱敏策略


@dataclass(frozen=True)
class RedactionPolicy:
    """脱敏策略：决定某个出站通道如何处理各分类等级。

    Attributes:
        threshold: 达到或超过此等级的字段将被掩码。
        mask_text: 是否对自由文本做值形态掩码。
        annotate: 是否在结果中附加脱敏说明字段（便于调用方感知）。
        max_depth: 递归深度上限，防御深层嵌套或环引用。
    """

    threshold: Classification = Classification.RESTRICTED
    mask_text: bool = False
    annotate: bool = False
    max_depth: int = 16

    def is_enabled(self) -> bool:
        """策略是否会产生任何脱敏动作。"""
        return self.threshold <= Classification.RESTRICTED or self.mask_text


#: 预置策略：API 响应
#:
#: ``mask_text=True`` 的理由：手机号出现在 ``note`` 自由文本里与出现在
#: ``mobile`` 字段里同样敏感，若只按字段名脱敏会留下明显泄漏口。
#: 值模式仅覆盖**高置信度强模式**（身份证/手机号/银行卡/邮箱/信用代码），
#: 不触碰企业名等业务内容，因此不会破坏报告正文的可读性。
POLICY_API_RESPONSE = RedactionPolicy(threshold=Classification.RESTRICTED,
                                      mask_text=True, annotate=True)

#: 预置策略：日志（掩码 CONFIDENTIAL 及以上 + 文本模式，日志留存久、暴露面大）
POLICY_LOG = RedactionPolicy(threshold=Classification.CONFIDENTIAL, mask_text=True)

#: 预置策略：LLM 出站（最严：掩码 CONFIDENTIAL 及以上 + 文本模式）
#: 依据独立评审 L659：客户数据进入外部模型属重大合规风险。
POLICY_LLM = RedactionPolicy(threshold=Classification.CONFIDENTIAL, mask_text=True)


@dataclass
class RedactionReport:
    """脱敏结果报告（供审计与 E2E 断言）。"""

    masked_fields: list[str] = field(default_factory=list)
    masked_patterns: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def count(self) -> int:
        """被掩码的字段数。"""
        return len(self.masked_fields)

    def as_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"masked_fields": sorted(set(self.masked_fields)),
                "masked_patterns": sorted(set(self.masked_patterns)),
                "truncated": self.truncated}


def redact_structure(data, policy: RedactionPolicy = POLICY_API_RESPONSE,
                     *, report: RedactionReport | None = None,
                     _depth: int = 0, _path: str = "") -> object:
    """按策略递归脱敏结构化数据（dict/list/标量）。

    行为要点：
    - **不修改入参**，返回新结构（避免污染内部计算用的明文数据）；
    - 字段名命中规则且分类达到阈值 → 按规则风格掩码；
    - ``policy.mask_text=True`` 时，字符串值额外做值形态掩码；
    - 超过 ``max_depth`` 时停止递归并在报告中标记 ``truncated``，
      防御深层嵌套导致的栈溢出。

    Args:
        data: 待脱敏数据。
        policy: 脱敏策略。
        report: 可选报告收集器。
        _depth: 内部递归深度。
        _path: 内部字段路径（用于报告）。

    Returns:
        脱敏后的新结构。
    """
    if _depth > policy.max_depth:
        if report is not None:
            report.truncated = True
        return data

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            child_path = f"{_path}.{key}" if _path else str(key)
            rule = lookup_rule(str(key))
            if rule is not None:
                # 字段名规则优先于值模式：已登记字段完全由其分类与阈值决定，
                # 未达阈值即保留原文。否则 creditCode 这类「按字段名应保留、
                # 但值形态又像敏感值」的字段会被文本掩码意外命中，
                # 造成策略语义自相矛盾。
                if rule.classification >= policy.threshold:
                    result[key] = _mask_by_rule(value, rule, policy, report, child_path)
                else:
                    result[key] = value
            else:
                result[key] = redact_structure(value, policy, report=report,
                                               _depth=_depth + 1, _path=child_path)
        return result

    if isinstance(data, (list, tuple)):
        items = [redact_structure(item, policy, report=report, _depth=_depth + 1,
                                  _path=f"{_path}[{idx}]")
                 for idx, item in enumerate(data)]
        return items if isinstance(data, list) else tuple(items)

    if isinstance(data, str) and policy.mask_text:
        hits = detect_value_patterns(data)
        if hits:
            if report is not None:
                report.masked_patterns.extend(hits)
                if _path:
                    report.masked_fields.append(_path)
            return mask_text_patterns(data)
    return data


def _mask_by_rule(value, rule: FieldRule, policy: RedactionPolicy,
                  report: RedactionReport | None, path: str) -> object:
    """按字段规则掩码值；容器类型逐元素掩码。"""
    if report is not None:
        report.masked_fields.append(path)
    if isinstance(value, dict):
        return {k: _mask_by_rule(v, rule, policy, report, f"{path}.{k}")
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        masked = [_mask_by_rule(v, rule, policy, report, f"{path}[{i}]")
                  for i, v in enumerate(value)]
        return masked if isinstance(value, list) else tuple(masked)
    if value is None:
        return None
    return mask_value(value, style=rule.style, keep=rule.keep)


def redact_for_llm(text: str) -> str:
    """LLM 出站脱敏：自由文本进入外部模型前掩码敏感值。

    依据独立评审 L659：客户数据进入外部模型属重大合规风险，
    须在提示词构造处收口。此处只处理**文本**，结构化数据用
    :func:`redact_structure` 配合 :data:`POLICY_LLM`。
    """
    return mask_text_patterns(text)


def classification_inventory() -> list[dict]:
    """导出字段分类清单（用于生成合规文档与人工评审）。"""
    rows = []
    for name, rule in sorted(FIELD_RULES.items()):
        rows.append({"field": name,
                     "classification": rule.classification.name,
                     "mask_style": rule.style.name,
                     "keep": rule.keep,
                     "note": rule.note})
    return rows
