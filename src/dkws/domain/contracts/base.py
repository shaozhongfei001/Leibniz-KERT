"""契约化 Markdown Schema 校验框架（规格 §8.5、§9）。

每个合同 = SchemaSpec（schema 名、字段表、正文标题、交叉校验），
validate_contract 执行：通则校验 + 字段必填/类型/枚举/未知字段/主ID/标题/交叉约束。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .. import ids, timeutil
from ..errors import SchemaValidationError
from ...infrastructure import markdown

MISSING = object()


@dataclass
class FieldSpec:
    name: str
    type: str = "string"  # string/integer/number/boolean/enum/list/map/timestamp/date/any
    required: bool = False
    nullable: bool = False
    enum: list | None = None
    element_type: str | None = None
    element_fields: dict | None = None  # list[dict] 元素的子字段白名单
    condition: Callable[[dict], bool] | None = None  # 条件必填：(fm)->bool
    default: Any = MISSING
    validator: Callable[[Any, dict], list[str]] | None = None  # (value, fm)->errors


@dataclass
class SchemaSpec:
    schema_name: str
    primary_id: str | None = None
    fields: list[FieldSpec] = field(default_factory=list)
    required_headings: list[str] | None = None
    extra_validator: Callable[[dict, str], list[str]] | None = None  # (fm, body)->errors


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    front_matter: dict
    body: str
    headings: list[tuple[int, str]]

    def raise_if_invalid(self, path: str = "<memory>") -> "ValidationResult":
        if not self.ok:
            raise SchemaValidationError(
                f"合同校验失败 {path}: " + "; ".join(self.errors),
                details={"path": path, "errors": self.errors},
            )
        return self


def _type_errors(value: Any, ftype: str, field_name: str, fm: dict) -> list[str]:
    if value is None:
        return []
    if ftype == "any":
        return []
    if ftype == "string":
        if not isinstance(value, str):
            return [f"字段 {field_name} 应为 string，实际 {type(value).__name__}"]
    elif ftype == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return [f"字段 {field_name} 应为 integer，实际 {type(value).__name__}"]
    elif ftype == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return [f"字段 {field_name} 应为 number，实际 {type(value).__name__}"]
    elif ftype == "boolean":
        if not isinstance(value, bool):
            return [f"字段 {field_name} 应为 boolean，实际 {type(value).__name__}"]
    elif ftype == "enum":
        # 枚举值域检查在主循环（f.enum）执行
        pass
    elif ftype == "list":
        if not isinstance(value, list):
            return [f"字段 {field_name} 应为 list，实际 {type(value).__name__}"]
    elif ftype == "map":
        if not isinstance(value, dict):
            return [f"字段 {field_name} 应为 map，实际 {type(value).__name__}"]
    elif ftype == "timestamp":
        try:
            timeutil.parse_ts(str(value))
        except Exception:
            return [f"字段 {field_name} 应为 RFC 3339 时间戳"]
    elif ftype == "date":
        try:
            timeutil.parse_business_date(str(value))
        except Exception:
            return [f"字段 {field_name} 应为 YYYY-MM-DD 日期"]
    else:
        return [f"未知字段类型: {ftype}"]
    return []


def validate_contract(text: str, spec: SchemaSpec, *, path: str = "<memory>") -> ValidationResult:
    parsed = markdown.parse_contract_md(text, path=path)
    errors = list(parsed.errors)
    warnings: list[str] = []
    fm = parsed.front_matter

    if not parsed.ok:
        return ValidationResult(False, errors, warnings, fm, parsed.body, parsed.headings)

    if fm.get("schema") != spec.schema_name:
        errors.append(f"schema 应为 {spec.schema_name!r}，实际 {fm.get('schema')!r}")

    field_map = {f.name: f for f in spec.fields}
    # 未知字段（§8.5.9）；schema 是通用固定字段（§8.5.5）
    for key in fm:
        if key.startswith("x_") or key == "schema":
            continue
        if key not in field_map:
            errors.append(f"未声明字段: {key!r}（扩展字段必须以 x_ 开头）")

    for f in spec.fields:
        present = f.name in fm and fm[f.name] is not MISSING
        value = fm.get(f.name)
        # 必填 / 条件必填
        if not present:
            if f.required:
                errors.append(f"缺少必填字段: {f.name}")
            elif f.condition is not None and f.condition(fm):
                errors.append(f"条件必填字段缺失: {f.name}")
            elif f.default is not MISSING:
                fm[f.name] = f.default
            continue
        # null 处理（§8.6）
        if value is None and not f.nullable:
            errors.append(f"字段 {f.name} 不允许为 null")
            continue
        if value is None:
            continue
        errors += _type_errors(value, f.type, f.name, fm)
        if f.enum is not None and f.type == "enum" and value not in f.enum:
            errors.append(f"字段 {f.name} 非法枚举值: {value!r}（允许 {f.enum}）")
        if f.type == "list" and f.element_type and isinstance(value, list):
            for i, item in enumerate(value):
                if item is None:
                    continue
                sub = _type_errors(item, f.element_type, f"{f.name}[{i}]", fm)
                if f.element_type == "map" and f.element_fields and isinstance(item, dict):
                    for sk in item:
                        if not sk.startswith("x_") and sk not in f.element_fields:
                            errors.append(f"字段 {f.name}[{i}] 未声明子字段: {sk!r}")
                    for ef_name, ef in f.element_fields.items():
                        if ef_name not in item:
                            if ef.required:
                                errors.append(f"字段 {f.name}[{i}] 缺少必填子字段: {ef_name}")
                            continue
                        ev = item[ef_name]
                        if ev is None:
                            if not ef.nullable:
                                errors.append(f"字段 {f.name}[{i}].{ef_name} 不允许为 null")
                            continue
                        sub += _type_errors(ev, ef.type, f"{f.name}[{i}].{ef_name}", fm)
                        if ef.enum is not None and ef.type == "enum" and ev not in ef.enum:
                            errors.append(
                                f"字段 {f.name}[{i}].{ef_name} 非法枚举值: {ev!r}（允许 {ef.enum}）"
                            )
                        if ef.validator is not None:
                            sub += ef.validator(ev, fm)
                errors += sub
        if f.validator is not None:
            errors += f.validator(value, fm)

    # 主 ID（§8.2：ID 规范）
    if spec.primary_id:
        pid = fm.get(spec.primary_id)
        if pid is not None:
            try:
                ids.validate_id(str(pid), f"主ID({spec.primary_id})")
            except Exception as exc:
                errors.append(str(exc))

    # 正文标题（§9 各节）
    if spec.required_headings:
        found = [h for _, h in parsed.headings]
        for h in spec.required_headings:
            if h not in found:
                errors.append(f"正文缺少固定标题: {h}")

    if spec.extra_validator is not None:
        errors += spec.extra_validator(fm, parsed.body)

    return ValidationResult(not errors, errors, warnings, fm, parsed.body, parsed.headings)
