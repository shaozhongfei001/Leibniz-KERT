"""M2.9 数据分类与脱敏单元测试。"""

from __future__ import annotations

import dataclasses

import pytest

from dkws.infrastructure.classification import (
    FIELD_RULES,
    MASK_TOKEN,
    POLICY_API_RESPONSE,
    POLICY_LLM,
    POLICY_LOG,
    VALUE_PATTERNS,
    Classification,
    FieldRule,
    MaskStyle,
    RedactionPolicy,
    RedactionReport,
    classification_inventory,
    classify_field,
    detect_value_patterns,
    lookup_rule,
    mask_text_patterns,
    mask_value,
    redact_for_llm,
    redact_structure,
)

MOBILE = "13812348000"
ID_CARD = "110101199001011234"
CREDIT_CODE = "91310000MA1K35Q12X"
BANK_CARD = "6222021234567890123"
EMAIL = "zhangsan@huaxin.com"


# ---------------------------------------------------------------- 分类等级

class TestClassification:
    """分类等级语义。"""

    def test_levels_ordered_by_sensitivity(self):
        """数值越大越敏感，便于阈值比较。"""
        assert (Classification.PUBLIC < Classification.INTERNAL
                < Classification.CONFIDENTIAL < Classification.RESTRICTED)

    @pytest.mark.parametrize(("raw", "expected"), [
        ("PUBLIC", Classification.PUBLIC),
        ("public", Classification.PUBLIC),
        ("公开", Classification.PUBLIC),
        ("INTERNAL", Classification.INTERNAL),
        ("内部", Classification.INTERNAL),
        ("CONFIDENTIAL", Classification.CONFIDENTIAL),
        ("保密", Classification.CONFIDENTIAL),
        ("SECRET", Classification.CONFIDENTIAL),
        ("RESTRICTED", Classification.RESTRICTED),
        ("受限", Classification.RESTRICTED),
        ("PII", Classification.RESTRICTED),
        ("个人信息", Classification.RESTRICTED),
        ("  restricted  ", Classification.RESTRICTED),
        ("RE-STRICTED", Classification.RESTRICTED),
    ])
    def test_parse_aliases(self, raw, expected):
        """支持中英文与大小写别名。"""
        assert Classification.parse(raw) == expected

    def test_parse_unknown_defaults_to_internal(self):
        """未知标记按较敏感处理，避免拼写错误导致意外泄漏。"""
        assert Classification.parse("typo-level") == Classification.INTERNAL
        assert Classification.parse(None) == Classification.INTERNAL
        assert Classification.parse("") == Classification.INTERNAL

    def test_parse_respects_explicit_default(self):
        """可指定回落等级。"""
        assert Classification.parse("nope", Classification.RESTRICTED) == \
            Classification.RESTRICTED

    def test_parse_accepts_int(self):
        """接受数值形式。"""
        assert Classification.parse(3) == Classification.RESTRICTED
        assert Classification.parse(99) == Classification.INTERNAL

    def test_parse_rejects_bool(self):
        """布尔值不被当作等级数值。"""
        assert Classification.parse(True) == Classification.INTERNAL


# ---------------------------------------------------------------- 掩码

class TestMaskValue:
    """掩码风格。"""

    def test_full_style(self):
        """FULL 完全替换。"""
        assert mask_value("hunter2", style=MaskStyle.FULL) == MASK_TOKEN

    def test_tail_preserves_last_digits(self):
        """TAIL 保留尾部，便于运维核对。"""
        assert mask_value(MOBILE, style=MaskStyle.TAIL, keep=4) == "*******8000"

    def test_tail_masks_short_value_fully(self):
        """短值不足保留位数时完全掩码，且保持长度（避免泄漏全部内容）。"""
        assert mask_value("123", style=MaskStyle.TAIL, keep=4) == "***"
        assert "3" not in mask_value("123", style=MaskStyle.TAIL, keep=4)

    def test_edges_preserves_both_ends(self):
        """EDGES 保留首尾。"""
        assert mask_value("华鑫轴承材料集团", style=MaskStyle.EDGES, keep=1) == "华******团"

    def test_edges_masks_short_value_fully(self):
        """长度不足两倍保留位时完全掩码。"""
        assert mask_value("ab", style=MaskStyle.EDGES, keep=2) == "**"
        assert mask_value("abcd", style=MaskStyle.EDGES, keep=3) == "****"

    def test_shape_hides_all_characters(self):
        """SHAPE 只暴露长度，不保留任何原字符。"""
        assert mask_value("secret", style=MaskStyle.SHAPE) == "<6字符>"

    def test_empty_and_none(self):
        """空值统一为掩码占位符。"""
        assert mask_value("") == MASK_TOKEN
        assert mask_value(None) == MASK_TOKEN

    def test_non_string_coerced(self):
        """非字符串先转字符串。"""
        assert mask_value(12345678, style=MaskStyle.TAIL, keep=2) == "******78"

    def test_negative_keep_treated_as_zero(self):
        """负数保留位按 0 处理：完全掩码且长度不变。

        回归防护：早期实现会产生 ``'******abcdef'``——长度翻倍且原值完整暴露。
        """
        assert mask_value("abcdef", style=MaskStyle.TAIL, keep=-3) == "******"
        assert mask_value("abcdef", style=MaskStyle.EDGES, keep=-1) == "******"

    def test_zero_keep_masks_fully(self):
        """keep=0 时完全掩码，不保留任何原字符。"""
        assert mask_value("abcdef", style=MaskStyle.TAIL, keep=0) == "******"
        assert "a" not in mask_value("abcdef", style=MaskStyle.EDGES, keep=0)

    def test_masked_length_preserved(self):
        """掩码后长度与原值一致，避免泄漏长度差异之外的信息。"""
        assert len(mask_value(ID_CARD, style=MaskStyle.TAIL, keep=4)) == len(ID_CARD)


# ---------------------------------------------------------------- 字段规则

class TestFieldRules:
    """字段分类与规则查找。"""

    @pytest.mark.parametrize("name", [
        "idCardNo", "id_card_no", "IDCARDNO", "  idCardNo  ",
    ])
    def test_lookup_is_name_normalized(self, name):
        """字段名匹配忽略大小写、下划线与空白。"""
        assert lookup_rule(name) is not None
        assert classify_field(name) == Classification.RESTRICTED

    @pytest.mark.parametrize(("name", "expected"), [
        ("mobile", Classification.RESTRICTED),
        ("idCardNo", Classification.RESTRICTED),
        ("bankAccount", Classification.RESTRICTED),
        ("email", Classification.RESTRICTED),
        ("password", Classification.RESTRICTED),
        ("apiKey", Classification.RESTRICTED),
        ("creditCode", Classification.CONFIDENTIAL),
        ("riskRating", Classification.CONFIDENTIAL),
        ("creditLimit", Classification.CONFIDENTIAL),
        ("customerId", Classification.INTERNAL),
        ("rmId", Classification.INTERNAL),
    ])
    def test_classification_by_field(self, name, expected):
        """真实字段的分类判定。"""
        assert classify_field(name) == expected

    def test_suffix_match_covers_compound_names(self):
        """复合字段名经后缀匹配命中，无需逐一登记。"""
        assert classify_field("customerMobile") == Classification.RESTRICTED
        assert classify_field("contactEmail") == Classification.RESTRICTED
        assert classify_field("enterpriseCreditCode") == Classification.CONFIDENTIAL

    def test_unknown_field_is_internal(self):
        """未登记字段按保守默认（INTERNAL）。"""
        assert lookup_rule("someRandomField") is None
        assert classify_field("someRandomField") == Classification.INTERNAL

    def test_short_names_do_not_trigger_suffix_match(self):
        """短名不参与后缀匹配，避免误伤（如 id 命中大量字段）。"""
        assert lookup_rule("bid") is None
        assert lookup_rule("uid") is None

    def test_inventory_lists_all_rules(self):
        """分类清单覆盖全部规则，可用于合规文档。"""
        inventory = classification_inventory()
        assert len(inventory) == len(FIELD_RULES)
        assert all({"field", "classification", "mask_style", "keep", "note"} == set(r)
                   for r in inventory)

    def test_inventory_sorted(self):
        """清单按字段名排序，便于 diff 审查。"""
        fields = [r["field"] for r in classification_inventory()]
        assert fields == sorted(fields)

    def test_all_rules_have_notes(self):
        """每条规则都有中文说明，便于人工评审。"""
        assert all(rule.note for rule in FIELD_RULES.values())

    def test_credential_fields_use_full_mask(self):
        """凭据类字段一律完全掩码，不保留任何位。"""
        for name in ("password", "token", "apikey", "secret", "privatekey"):
            assert FIELD_RULES[name].style is MaskStyle.FULL


# ---------------------------------------------------------------- 值模式

class TestValuePatterns:
    """按值形态检测与掩码。"""

    @pytest.mark.parametrize(("text", "pattern"), [
        (f"手机 {MOBILE}", "mobile"),
        (f"身份证 {ID_CARD}", "id_card"),
        (f"信用代码 {CREDIT_CODE}", "credit_code"),
        (f"卡号 {BANK_CARD}", "bank_card"),
        (f"邮箱 {EMAIL}", "email"),
    ])
    def test_detect_patterns(self, text, pattern):
        """各类敏感值形态被识别。"""
        assert pattern in detect_value_patterns(text)

    def test_detect_multiple(self):
        """可同时识别多种形态。"""
        hits = detect_value_patterns(f"手机 {MOBILE} 邮箱 {EMAIL}")
        assert {"mobile", "email"} <= set(hits)

    def test_detect_empty(self):
        """空文本无命中。"""
        assert detect_value_patterns("") == ()

    @pytest.mark.parametrize("secret", [MOBILE, ID_CARD, CREDIT_CODE, BANK_CARD, EMAIL])
    def test_mask_text_removes_secret(self, secret):
        """掩码后原值不再出现。"""
        masked = mask_text_patterns(f"内容包含 {secret} 结束")
        assert secret not in masked
        assert "*" in masked

    def test_mask_text_preserves_context(self):
        """保留上下文以维持可读性。"""
        masked = mask_text_patterns(f"客户手机 {MOBILE} 已验证")
        assert masked.startswith("客户手机 ")
        assert masked.endswith(" 已验证")

    @pytest.mark.parametrize("benign", [
        "授信额度评估完成",
        "订单号 A12345",
        "金额 1234.56 元",
        "日期 2026-08-27",
        "版本 v1.3.0",
    ])
    def test_mask_text_does_not_harm_benign(self, benign):
        """正常内容不被误伤，避免脱敏过度损害可诊断性。"""
        assert mask_text_patterns(benign) == benign

    def test_mask_text_handles_multiple_patterns_correctly(self):
        """多个模式同时命中时各自使用正确的掩码风格。

        这是对闭包延迟绑定缺陷的回归防护：若循环变量未正确绑定，
        所有模式会错误地使用最后一组风格参数。
        """
        masked = mask_text_patterns(f"手机 {MOBILE} 邮箱 {EMAIL}")
        assert MOBILE not in masked
        assert EMAIL not in masked
        # 手机号用 TAIL（尾部 4 位保留），邮箱用 EDGES（首尾各 2）
        assert "8000" in masked
        assert masked.count("zh") == 1

    def test_patterns_are_compiled(self):
        """模式预编译，避免重复编译开销。"""
        assert all(hasattr(p, "search") for _, p, _, _ in VALUE_PATTERNS)


# ---------------------------------------------------------------- 结构脱敏

class TestRedactStructure:
    """结构化脱敏。"""

    def test_masks_restricted_fields(self):
        """RESTRICTED 字段被掩码。"""
        out = redact_structure({"mobile": MOBILE, "idCardNo": ID_CARD})
        assert out["mobile"] != MOBILE
        assert out["idCardNo"] != ID_CARD

    def test_api_policy_preserves_confidential(self):
        """API 策略默认阈值为 RESTRICTED，保留商业字段供业务使用。"""
        out = redact_structure({"creditCode": CREDIT_CODE}, POLICY_API_RESPONSE)
        assert out["creditCode"] == CREDIT_CODE

    def test_llm_policy_masks_confidential(self):
        """LLM 策略更严，掩码 CONFIDENTIAL 及以上。"""
        out = redact_structure({"creditCode": CREDIT_CODE}, POLICY_LLM)
        assert out["creditCode"] != CREDIT_CODE

    def test_log_policy_masks_confidential(self):
        """日志策略同样掩码 CONFIDENTIAL（日志留存久、暴露面大）。"""
        out = redact_structure({"riskRating": "BBB"}, POLICY_LOG)
        assert out["riskRating"] == MASK_TOKEN

    def test_does_not_mutate_input(self):
        """不修改入参，避免污染内部计算用的明文数据。"""
        data = {"mobile": MOBILE, "nested": {"phone": MOBILE}}
        redact_structure(data)
        assert data["mobile"] == MOBILE
        assert data["nested"]["phone"] == MOBILE

    def test_recurses_into_nested_dict(self):
        """递归处理嵌套字典。"""
        out = redact_structure({"a": {"b": {"mobile": MOBILE}}})
        assert out["a"]["b"]["mobile"] != MOBILE

    def test_recurses_into_list(self):
        """递归处理列表。"""
        out = redact_structure({"items": [{"mobile": MOBILE}, {"mobile": MOBILE}]})
        assert all(i["mobile"] != MOBILE for i in out["items"])

    def test_preserves_tuple_type(self):
        """元组类型被保留。"""
        out = redact_structure({"items": ({"mobile": MOBILE},)})
        assert isinstance(out["items"], tuple)

    def test_masks_list_valued_sensitive_field(self):
        """敏感字段值为列表时逐元素掩码。"""
        out = redact_structure({"mobile": [MOBILE, "13900001111"]})
        assert all(v != MOBILE for v in out["mobile"])

    def test_preserves_none(self):
        """None 值保持为 None，不变成掩码字符串。"""
        assert redact_structure({"mobile": None})["mobile"] is None

    def test_preserves_non_sensitive_types(self):
        """非敏感数值与布尔保持原类型。"""
        out = redact_structure({"count": 42, "ok": True, "ratio": 1.5})
        assert out == {"count": 42, "ok": True, "ratio": 1.5}

    def test_depth_limit_prevents_runaway(self):
        """超过深度上限时停止递归并标记，防御深层嵌套。"""
        deep = current = {}
        for _ in range(30):
            current["child"] = {}
            current = current["child"]
        current["mobile"] = MOBILE
        report = RedactionReport()
        redact_structure(deep, RedactionPolicy(max_depth=5), report=report)
        assert report.truncated is True

    def test_report_records_masked_paths(self):
        """报告记录被掩码的字段路径，便于审计。"""
        report = RedactionReport()
        redact_structure({"mobile": MOBILE, "nested": {"idCardNo": ID_CARD}},
                         report=report)
        paths = report.as_dict()["masked_fields"]
        assert "mobile" in paths
        assert "nested.idCardNo" in paths

    def test_report_records_list_index(self):
        """列表元素路径含索引。"""
        report = RedactionReport()
        redact_structure({"items": [{"mobile": MOBILE}]}, report=report)
        assert "items[0].mobile" in report.as_dict()["masked_fields"]

    def test_report_count(self):
        """报告统计掩码字段数。"""
        report = RedactionReport()
        redact_structure({"mobile": MOBILE, "email": EMAIL}, report=report)
        assert report.count == 2

    def test_text_masking_when_enabled(self):
        """启用文本掩码时，自由文本中的敏感值被处理。"""
        out = redact_structure({"note": f"联系 {MOBILE}"}, POLICY_LLM)
        assert MOBILE not in out["note"]

    def test_api_policy_also_masks_free_text(self):
        """API 策略同样掩码自由文本中的 PII。

        手机号出现在 note 里与出现在 mobile 字段里同样敏感；
        若只按字段名脱敏会留下明显泄漏口（本用例为该缺陷的回归防护）。
        """
        out = redact_structure({"note": f"联系 {MOBILE}"}, POLICY_API_RESPONSE)
        assert MOBILE not in out["note"]
        assert out["note"].startswith("联系 ")

    def test_field_rule_takes_precedence_over_value_pattern(self):
        """字段名规则优先于值模式。

        ``creditCode`` 按字段名为 CONFIDENTIAL（API 策略应保留），但其值形态
        又匹配 credit_code 值模式。若不设优先级，该字段会被文本掩码意外命中，
        导致策略语义自相矛盾。本用例锁定「已登记字段完全由其分类决定」。
        """
        out = redact_structure({"creditCode": CREDIT_CODE}, POLICY_API_RESPONSE)
        assert out["creditCode"] == CREDIT_CODE
        # 同一个值出现在未登记字段中时，仍按值模式掩码
        out2 = redact_structure({"remark": CREDIT_CODE}, POLICY_API_RESPONSE)
        assert out2["remark"] != CREDIT_CODE

    def test_api_policy_text_masking_spares_business_content(self):
        """文本掩码只处理高置信度强模式，不触碰企业名等业务内容。"""
        out = redact_structure({"note": "华鑫轴承材料集团授信额度评估完成"},
                               POLICY_API_RESPONSE)
        assert out["note"] == "华鑫轴承材料集团授信额度评估完成"

    def test_handles_empty_structures(self):
        """空结构不报错。"""
        assert redact_structure({}) == {}
        assert redact_structure([]) == []

    def test_handles_scalar_input(self):
        """标量输入原样返回。"""
        assert redact_structure("plain") == "plain"
        assert redact_structure(42) == 42


# ---------------------------------------------------------------- LLM 出站

class TestLlmRedaction:
    """LLM 出站脱敏（独立评审 L659）。"""

    @pytest.mark.parametrize("secret", [MOBILE, ID_CARD, CREDIT_CODE, BANK_CARD, EMAIL])
    def test_redacts_all_secret_types(self, secret):
        """各类敏感值在出站前被掩码。"""
        assert secret not in redact_for_llm(f"客户信息：{secret}")

    def test_preserves_business_context(self):
        """保留业务上下文，使模型仍能理解语义。"""
        out = redact_for_llm(f"客户张三，手机 {MOBILE}，需评估授信额度")
        assert "客户张三" in out
        assert "需评估授信额度" in out
        assert MOBILE not in out

    def test_idempotent(self):
        """重复脱敏结果稳定。"""
        once = redact_for_llm(f"手机 {MOBILE}")
        assert redact_for_llm(once) == once

    def test_empty_input(self):
        """空输入不报错。"""
        assert redact_for_llm("") == ""


# ---------------------------------------------------------------- 策略

class TestPolicies:
    """预置策略配置。"""

    def test_api_policy_threshold(self):
        """API 策略阈值为 RESTRICTED，且启用文本掩码防自由文本泄漏。"""
        assert POLICY_API_RESPONSE.threshold == Classification.RESTRICTED
        assert POLICY_API_RESPONSE.mask_text is True

    def test_llm_policy_is_strictest(self):
        """LLM 策略最严：更低阈值 + 文本掩码。"""
        assert POLICY_LLM.threshold == Classification.CONFIDENTIAL
        assert POLICY_LLM.mask_text is True

    def test_log_policy_masks_text(self):
        """日志策略启用文本掩码。"""
        assert POLICY_LOG.mask_text is True

    def test_policy_is_enabled(self):
        """策略可判断是否会产生脱敏动作。"""
        assert POLICY_API_RESPONSE.is_enabled() is True

    def test_custom_policy(self):
        """支持自定义策略。"""
        policy = RedactionPolicy(threshold=Classification.PUBLIC, mask_text=True)
        out = redact_structure({"customerId": "CUST-0001"}, policy)
        assert out["customerId"] != "CUST-0001"

    def test_field_rule_dataclass(self):
        """FieldRule 为不可变数据类。"""
        rule = FieldRule(Classification.RESTRICTED, MaskStyle.TAIL, 4, "测试")
        with pytest.raises(dataclasses.FrozenInstanceError):
            rule.keep = 8
