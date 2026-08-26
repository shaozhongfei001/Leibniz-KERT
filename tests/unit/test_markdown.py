"""P0 测试：契约化 Markdown 解析通则（§8.5）与 Schema 校验框架。"""

from __future__ import annotations

import pytest
import yaml

from dkws.domain.contracts.base import FieldSpec, SchemaSpec, validate_contract
from dkws.domain.errors import SchemaValidationError
from dkws.infrastructure import markdown


def _sample(**overrides):
    fm = {"schema": "demo/v1", "id": "DEMO-001", "status": "ACTIVE",
          "version": "1.0", "cond": "ok"}
    fm.update(overrides)
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_text}\n---\n\n# 标题\n\n正文\n"


class TestParseGeneral:
    def test_must_start_with_dashes(self):
        r = markdown.parse_contract_md("not dashes\n---\nx: 1\n---\n")
        assert not r.ok
        assert any("---" in e for e in r.errors)

    def test_empty_line_after_front_matter(self):
        r = markdown.parse_contract_md("---\nschema: x/v1\n---\n# 标题\n")
        assert not r.ok
        assert any("空行" in e for e in r.errors)

    def test_first_heading_must_be_h1(self):
        r = markdown.parse_contract_md("---\nschema: x/v1\n---\n\n## 二级\n")
        assert not r.ok
        assert any("一级标题" in e for e in r.errors)

    def test_duplicate_yaml_key_rejected(self):
        r = markdown.parse_contract_md("---\nschema: x/v1\nschema: y/v1\n---\n\n# 标题\n")
        assert any("重复 YAML 键" in e for e in r.errors)

    def test_anchor_rejected(self):
        r = markdown.parse_contract_md("---\nschema: x/v1\nbase: &b 1\nv: *b\n---\n\n# 标题\n")
        assert any("锚点" in e or "别名" in e for e in r.errors)

    def test_implicit_date_rejected(self):
        r = markdown.parse_contract_md("---\nschema: x/v1\nwhen: 2026-08-19\n---\n\n# 标题\n")
        assert any("日期" in e for e in r.errors)

    def test_quoted_date_ok(self):
        r = markdown.parse_contract_md('---\nschema: x/v1\nwhen: "2026-08-19"\n---\n\n# 标题\n')
        assert r.ok, r.errors


class TestSchemaSpec:
    SPEC = SchemaSpec(
        schema_name="demo/v1",
        primary_id="id",
        fields=[
            FieldSpec("id", required=True),
            FieldSpec("status", type="enum", required=True, enum=["ACTIVE", "INACTIVE"]),
            FieldSpec("version", required=True),
            FieldSpec("count", type="integer"),
            FieldSpec("nullable_field", nullable=True),
            FieldSpec("cond", condition=lambda fm: fm.get("status") == "ACTIVE"),
        ],
        required_headings=["标题"],
    )

    def test_valid(self):
        r = validate_contract(_sample(), self.SPEC)
        assert r.ok, r.errors

    def test_missing_required(self):
        r = validate_contract(_sample(id=None), self.SPEC)
        assert not r.ok
        assert any("id" in e for e in r.errors)

    def test_bad_enum(self):
        r = validate_contract(_sample(status="BOGUS"), self.SPEC)
        assert not r.ok
        assert any("枚举" in e for e in r.errors)

    def test_unknown_field(self):
        r = validate_contract(_sample(mystery=1), self.SPEC)
        assert not r.ok
        assert any("未声明字段" in e for e in r.errors)

    def test_x_extension_allowed(self):
        r = validate_contract(_sample(x_note="ok"), self.SPEC)
        assert r.ok, r.errors

    def test_bad_id(self):
        r = validate_contract(_sample(id="lowercase-bad"), self.SPEC)
        assert not r.ok
        assert any("ID" in e for e in r.errors)

    def test_conditional_required(self):
        r = validate_contract(_sample(cond=None), self.SPEC)  # status=ACTIVE 但 cond 为 null
        assert not r.ok
        assert any("cond" in e for e in r.errors)

    def test_null_not_allowed(self):
        r = validate_contract(_sample(count=None), self.SPEC)
        assert not r.ok
        assert any("null" in e for e in r.errors)

    def test_null_allowed(self):
        r = validate_contract(_sample(nullable_field=None), self.SPEC)
        assert r.ok, r.errors

    def test_raise_if_invalid(self):
        with pytest.raises(SchemaValidationError):
            validate_contract(_sample(status="NOPE"), self.SPEC).raise_if_invalid()

    def test_missing_heading(self):
        spec = SchemaSpec(schema_name="demo/v1", fields=[FieldSpec("id")],
                          required_headings=["必须存在", "说明"])
        r = validate_contract(_sample(), spec)
        assert not r.ok
        assert any("标题" in e for e in r.errors)


class TestRender:
    def test_roundtrip(self):
        fm = {"schema": "demo/v1", "when": "2026-08-19", "n": 1, "flag": True, "none": None}
        text = markdown.render_contract_md(fm, "# 标题\n\n正文\n")
        parsed = markdown.parse_contract_md(text)
        assert parsed.ok, parsed.errors
        assert parsed.front_matter["when"] == "2026-08-19"
        assert parsed.front_matter["n"] == 1
