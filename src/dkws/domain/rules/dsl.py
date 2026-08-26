"""规则 DSL：白名单解析、安全校验与确定性求值（规格 §9.8、§14）。

- 逻辑：all / any / not；
- 比较：eq ne gt gte lt lte in not_in contains starts_with exists is_null；
- 值：字面量、输入字段引用（$facts.x / $input.x）、受控常量；
- 动作：set / emit / require / compute（sum min max round date_diff）；
- 禁止 eval/exec、网络、文件写入、反射、任意代码求值（§14.2）。

求值模型（§14.1）：字段缺失与 null 区分；条件记录 TRUE/FALSE/UNKNOWN；
UNKNOWN 不自动等于 FALSE。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..errors import UsageError

LOGIC_OPS = {"all", "any", "not"}
COMPARE_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in",
               "contains", "starts_with", "exists", "is_null"}
ACTION_OPS = {"set", "emit", "require", "compute"}
CALC_FUNCS = {"sum", "min", "max", "round", "date_diff"}
WHITELIST = LOGIC_OPS | COMPARE_OPS | ACTION_OPS | CALC_FUNCS

MAX_DEPTH = 20
MAX_NODES = 500

# 规则正文/提示中的危险模式（用于静态检查规则资产正文）
DANGEROUS_PATTERNS = [
    r"\beval\s*\(", r"\bexec\s*\(", r"__import__\s*\(", r"\bsubprocess\b",
    r"\bos\.system\b", r"\bopen\s*\(", r"requests\.", r"\bcurl\b", r"\bwget\b",
    r"import\s+", r"\bexecfile\b", r"pickle\.", r"\bcompile\s*\(",
]

REF_RE = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


@dataclass
class EvalResult:
    value: object
    trace: list[dict] = field(default_factory=list)


class UnknownValue:
    """字段缺失（与 null 区分）。"""

    def __repr__(self):
        return "UNKNOWN"


UNKNOWN = UnknownValue()


# ---------------- 静态校验 ----------------

def validate_dsl(node, *, _depth: int = 0, _nodes: list = None) -> list[str]:
    """校验 DSL 结构：白名单、深度、节点数、值引用。"""
    errors: list[str] = []
    if _nodes is None:
        _nodes = []
    _nodes.append(node)
    if len(_nodes) > MAX_NODES:
        errors.append(f"DSL 节点数超过上限 {MAX_NODES}")
        return errors
    if _depth > MAX_DEPTH:
        errors.append(f"DSL 深度超过上限 {MAX_DEPTH}")
        return errors
    if isinstance(node, dict):
        if len(node) != 1:
            errors.append(f"DSL 节点必须为单键操作: {list(node.keys())[:3]}")
            return errors
        op, arg = next(iter(node.items()))
        if op not in WHITELIST:
            errors.append(f"DSL 非法操作: {op!r}（白名单 {sorted(WHITELIST)}）")
            return errors
        if op in ("in", "not_in"):
            if not isinstance(arg, list) or len(arg) != 2:
                errors.append(f"{op} 需要 [值, 列表]")
            else:
                errors += validate_dsl(arg[0], _depth=_depth + 1, _nodes=_nodes)
                if not isinstance(arg[1], list):
                    errors.append(f"{op} 第二参数必须为列表")
        elif op == "compute":
            if not isinstance(arg, dict):
                errors.append("compute 需要映射")
            else:
                # arg 映射自身一层 + 值表达式一层
                for key, expr in arg.items():
                    errors += validate_dsl(expr, _depth=_depth + 2, _nodes=_nodes)
        elif isinstance(arg, list):
            for item in arg:
                errors += validate_dsl(item, _depth=_depth + 1, _nodes=_nodes)
        elif isinstance(arg, dict):
            # 操作节点一层 + arg 映射一层
            for key, val in arg.items():
                errors += validate_dsl(val, _depth=_depth + 2, _nodes=_nodes)
        else:
            # 标量参数
            if isinstance(arg, str) and arg.startswith("$") and not REF_RE.match(arg):
                errors.append(f"非法字段引用: {arg!r}")
    elif isinstance(node, list):
        for item in node:
            errors += validate_dsl(item, _depth=_depth + 1, _nodes=_nodes)
    return errors


def validate_rule_body_text(text: str) -> list[str]:
    """规则资产正文/提示的静态安全检查（禁止 eval 等模式）。"""
    errors = []
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            errors.append(f"规则文本包含危险模式: {pat}")
    return errors


# ---------------- 求值 ----------------

def _resolve_ref(ref: str, facts: dict) -> object:
    if not ref.startswith("$"):
        return ref
    path = ref[1:].split(".")
    cur: object = facts
    for part in path[1:]:
        if not isinstance(cur, dict) or part not in cur:
            return UNKNOWN
        cur = cur[part]
    return cur


def _coerce_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _compare(a, b):
    """返回 (ok, known)；unknown 时 known=False。"""
    if isinstance(a, UnknownValue) or isinstance(b, UnknownValue):
        return False, False
    return a == b, True


def evaluate(node, facts: dict, *, _depth: int = 0) -> EvalResult:
    trace: list[dict] = []
    value = _eval(node, facts, _depth, trace)
    return EvalResult(value=value, trace=trace)


def _eval(node, facts, depth, trace) -> object:
    if depth > MAX_DEPTH:
        raise UsageError("DSL 求值深度超限")
    if isinstance(node, list):
        return [_eval(x, facts, depth + 1, trace) for x in node]
    if not isinstance(node, dict) or len(node) != 1:
        return node
    op, arg = next(iter(node.items()))
    if op == "all":
        vals = [_eval(x, facts, depth + 1, trace) for x in arg]
        unknown = any(isinstance(v, UnknownValue) for v in vals)
        result = all(v is True for v in vals)
        trace.append({"op": op, "value": True if result else (UNKNOWN if unknown else False)})
        return True if result else (UNKNOWN if unknown else False)
    if op == "any":
        vals = [_eval(x, facts, depth + 1, trace) for x in arg]
        unknown = any(isinstance(v, UnknownValue) for v in vals)
        result = any(v is True for v in vals)
        trace.append({"op": op, "value": True if result else (UNKNOWN if unknown else False)})
        return True if result else (UNKNOWN if unknown else False)
    if op == "not":
        v = _eval(arg, facts, depth + 1, trace)
        if isinstance(v, UnknownValue):
            trace.append({"op": op, "value": "UNKNOWN"})
            return UNKNOWN
        trace.append({"op": op, "value": not v})
        return not v
    if op in ("eq", "ne", "gt", "gte", "lt", "lte"):
        a, b = arg[0], arg[1]
        av = a if not isinstance(a, str) or not a.startswith("$") else _resolve_ref(a, facts)
        bv = b if not isinstance(b, str) or not b.startswith("$") else _resolve_ref(b, facts)
        if isinstance(av, UnknownValue) or isinstance(bv, UnknownValue):
            trace.append({"op": op, "value": "UNKNOWN"})
            return UNKNOWN
        if op in ("gt", "gte", "lt", "lte"):
            an, bn = _coerce_number(av), _coerce_number(bv)
            if an is None or bn is None:
                trace.append({"op": op, "value": "UNKNOWN"})
                return UNKNOWN
            result = {"gt": an > bn, "gte": an >= bn, "lt": an < bn, "lte": an <= bn}[op]
        else:
            result = (av == bv) if op == "eq" else (av != bv)
        trace.append({"op": op, "value": result})
        return result
    if op in ("in", "not_in"):
        v = _resolve_ref(arg[0], facts) if isinstance(arg[0], str) and arg[0].startswith("$") else arg[0]
        lst = arg[1]
        if isinstance(v, UnknownValue):
            trace.append({"op": op, "value": "UNKNOWN"})
            return UNKNOWN
        result = (v in lst) if op == "in" else (v not in lst)
        trace.append({"op": op, "value": result})
        return result
    if op == "contains":
        s = _resolve_ref(arg[0], facts) if isinstance(arg[0], str) and arg[0].startswith("$") else arg[0]
        sub = arg[1] if not isinstance(arg[1], str) or not arg[1].startswith("$") else _resolve_ref(arg[1], facts)
        if isinstance(s, UnknownValue) or isinstance(sub, UnknownValue):
            trace.append({"op": op, "value": "UNKNOWN"})
            return UNKNOWN
        result = sub in s
        trace.append({"op": op, "value": result})
        return result
    if op == "starts_with":
        s = _resolve_ref(arg[0], facts) if isinstance(arg[0], str) and arg[0].startswith("$") else arg[0]
        sub = arg[1]
        if isinstance(s, UnknownValue):
            trace.append({"op": op, "value": "UNKNOWN"})
            return UNKNOWN
        result = str(s).startswith(str(sub))
        trace.append({"op": op, "value": result})
        return result
    if op == "exists":
        ref = arg[0]
        path = ref[1:].split(".")
        cur = facts
        for part in path[1:]:
            if not isinstance(cur, dict) or part not in cur:
                trace.append({"op": op, "value": False})
                return False
            cur = cur[part]
        trace.append({"op": op, "value": True})
        return True
    if op == "is_null":
        ref = arg[0]
        v = _resolve_ref(ref, facts) if ref.startswith("$") else arg[0]
        if isinstance(v, UnknownValue):
            trace.append({"op": op, "value": "UNKNOWN"})
            return UNKNOWN
        result = v is None
        trace.append({"op": op, "value": result})
        return result
    if op == "set":
        # then/else 动作：设置结果字段
        out = {}
        for k, v in arg.items():
            out[k] = _eval(v, facts, depth + 1, trace) if isinstance(v, (dict, list)) else v
        return out
    if op == "emit":
        return {"message": arg}
    if op == "require":
        return {"requirements": arg if isinstance(arg, list) else [arg]}
    if op == "compute":
        out = {}
        for k, expr in arg.items():
            out[k] = _eval(expr, facts, depth + 1, trace)
        return out
    if op in CALC_FUNCS:
        vals = [_eval(x, facts, depth + 1, trace) for x in arg] if isinstance(arg, list) else [arg]
        nums = [_coerce_number(v) for v in vals]
        if any(n is None for n in nums):
            return UNKNOWN
        if op == "sum":
            return sum(nums)
        if op == "min":
            return min(nums)
        if op == "max":
            return max(nums)
        if op == "round":
            return round(nums[0])
        if op == "date_diff":
            return UNKNOWN  # 日期差值需显式格式，未配置时返回 UNKNOWN
    return node
