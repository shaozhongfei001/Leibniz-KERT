"""内部契约测试共享夹具。

集中负责：Schema 目录定位、``$ref`` 注册表构建、示例加载。
不引入除 ``jsonschema`` / ``PyYAML`` 以外的新依赖。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_DIR = REPO_ROOT / "docs" / "contracts" / "internal"
SCHEMA_DIR = CONTRACT_DIR / "schemas"
EXAMPLE_DIR = CONTRACT_DIR / "examples"
OPENAPI_FILE = CONTRACT_DIR / "openapi" / "dkws-skill-runtime-internal-v1.yaml"

#: 内部契约 Schema 文件名（与 scripts/internal_contract_hash.py 白名单一致）。
SCHEMA_FILES = (
    "execution-plan.schema.json",
    "execution-result.schema.json",
    "tool-call-receipt.schema.json",
    "model-call-receipt.schema.json",
    "runtime-error.schema.json",
    "runtime-capabilities.schema.json",
)

#: RFC3339 UTC 时间戳（契约仅使用 ``Z`` 结尾的 UTC 形式）。
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def _build_format_checker() -> FormatChecker:
    """返回带 ``date-time`` 校验的 FormatChecker。

    仓库未安装 ``rfc3339-validator``，因此自行注册 ``date-time``，
    避免为契约测试新增运行时依赖。
    """
    checker = FormatChecker()

    @checker.checks("date-time", raises=())
    def _check_date_time(value: object) -> bool:
        if not isinstance(value, str):
            return True
        return bool(_RFC3339_UTC.match(value))

    return checker


FORMAT_CHECKER = _build_format_checker()


def load_schema(name: str) -> dict[str, Any]:
    """按文件名加载单个 Schema。

    Args:
        name: Schema 文件名，例如 ``execution-plan.schema.json``。

    Returns:
        Schema 字典。
    """
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def load_example(name: str) -> Any:
    """按文件名加载单个示例 JSON。"""
    return json.loads((EXAMPLE_DIR / name).read_text(encoding="utf-8"))


def build_registry() -> Registry:
    """构建可解析相对 ``$ref`` 的 Schema 注册表。

    契约 Schema 未声明 ``$id``，彼此以相对文件名互引
    （如 ``tool-call-receipt.schema.json``），因此按文件名注册。
    """
    resources = [
        (name, Resource.from_contents(load_schema(name)))
        for name in SCHEMA_FILES
    ]
    return Registry().with_resources(resources)


def build_validator(schema_name: str) -> Draft202012Validator:
    """为指定 Schema 构建带 ``$ref`` 解析与格式校验的校验器。"""
    return Draft202012Validator(
        load_schema(schema_name),
        registry=build_registry(),
        format_checker=FORMAT_CHECKER,
    )


def assert_valid(schema_name: str, instance: Any) -> None:
    """断言实例通过 Schema；失败时输出全部错误路径。"""
    validator = build_validator(schema_name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, "\n".join(
        f"{list(e.path)}: {e.message}" for e in errors
    )


def assert_invalid(schema_name: str, instance: Any) -> list[str]:
    """断言实例被 Schema 拒绝，并返回错误消息列表。"""
    validator = build_validator(schema_name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    assert errors, f"预期 {schema_name} 拒绝该实例，但校验通过"
    return [e.message for e in errors]


@pytest.fixture(scope="session")
def registry() -> Registry:
    """会话级 Schema 注册表。"""
    return build_registry()
