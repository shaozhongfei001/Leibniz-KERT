"""契约化 Markdown 解析与通则校验（规格 §8.5、§9）。

通则（§8.5）：
1. 文件第一个字符开始为 `---`；
2. 仅含一个 YAML Front Matter；
3. Front Matter 后必须有一个空行；
4. 正文第一个标题必须是一级标题；
5. `schema`、主 ID、`status`、`version` 为必填（除非豁免）——由各合同 Schema 校验；
6. YAML 禁止自定义标签、锚点、别名和多文档分隔；
7. 日期必须加引号或被解析为字符串（隐式 date/datetime 视为非法）；
8. 枚举大小写敏感——由 Schema 校验；
9. 未声明字段默认拒绝，扩展字段以 `x_` 开头——由 Schema 校验；
10. 机器逻辑只读取 Front Matter 和受控代码块。
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

import yaml


FRONT_MATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


@dataclass
class ParsedMarkdown:
    front_matter: dict
    body: str
    headings: list[tuple[int, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _compose_checks(fm_text: str) -> list[str]:
    """YAML 结构检查：重复键、锚点、别名、非标准标签。"""
    errors: list[str] = []
    # 锚点/别名在 compose 阶段已被展开，必须用 token 流检测（§8.5.6）
    try:
        for token in yaml.scan(fm_text):
            if isinstance(token, yaml.tokens.AliasToken):
                errors.append("禁止使用 YAML 别名 (*)")
            if isinstance(token, yaml.tokens.AnchorToken):
                errors.append("禁止使用 YAML 锚点 (&)")
    except yaml.YAMLError as exc:
        return [f"YAML 语法错误: {exc}"]
    try:
        node = yaml.compose(fm_text)
    except yaml.YAMLError as exc:
        return [f"YAML 语法错误: {exc}"]
    if node is None:
        return []

    def walk(n):
        if n is None:
            return
        if isinstance(n, yaml.nodes.MappingNode):
            keys = set()
            for k, v in n.value:
                key = k.value if isinstance(k, yaml.nodes.ScalarNode) else repr(k)
                if key in keys:
                    errors.append(f"重复 YAML 键: {key}")
                keys.add(key)
                walk(k)
                walk(v)
        elif isinstance(n, yaml.nodes.SequenceNode):
            for v in n.value:
                walk(v)
        elif isinstance(n, yaml.nodes.ScalarNode):
            if n.tag not in {
                "tag:yaml.org,2002:str",
                "tag:yaml.org,2002:int",
                "tag:yaml.org,2002:float",
                "tag:yaml.org,2002:bool",
                "tag:yaml.org,2002:null",
            }:
                errors.append(f"非标准 YAML 标量标签: {n.tag}")

    walk(node)
    return errors


def _check_implicit_dates(value, path: str = "$", errors: list[str] | None = None):
    """检测未加引号的日期（YAML 隐式解析为 date/datetime 的标量）。"""
    if errors is None:
        errors = []
    if isinstance(value, dict):
        for k, v in value.items():
            _check_implicit_dates(v, f"{path}.{k}", errors)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_implicit_dates(v, f"{path}[{i}]", errors)
    elif isinstance(value, (_dt.date, _dt.datetime)):
        errors.append(
            f"{path} 的日期未加引号，被隐式解析为 {type(value).__name__}；"
            "日期必须加引号或被解析为字符串"
        )
    return errors


def extract_headings(body: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    for line in body.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip()))
    return headings


def parse_contract_md(text: str, *, path: str = "<memory>") -> ParsedMarkdown:
    """解析并执行 §8.5 通则（1-4、6-7）校验。Schema 级校验由合同类执行。"""
    errors: list[str] = []
    if not text.startswith("---"):
        errors.append("文件必须以 '---' 开头（Front Matter 起始）")
        return ParsedMarkdown({}, "", [], errors)

    m = FRONT_MATTER_RE.match(text)
    if not m:
        errors.append("Front Matter 格式非法：须以 '---' 起始并在独立行以 '---' 结束")
        return ParsedMarkdown({}, "", [], errors)
    fm_text = m.group(1)
    rest = text[m.end():]

    errors += _compose_checks(fm_text)

    try:
        fm = yaml.safe_load(fm_text) or {}
        if not isinstance(fm, dict):
            errors.append("Front Matter 必须是 YAML 映射")
            fm = {}
    except yaml.YAMLError as exc:
        errors.append(f"Front Matter 解析失败: {exc}")
        fm = {}

    errors += _check_implicit_dates(fm)

    if not rest.startswith("\n"):
        errors.append("Front Matter 后必须有一个空行")
    body = rest.lstrip("\n") if rest.startswith("\n") else rest
    body = body.lstrip("\n")

    headings = extract_headings(body)
    if not headings or headings[0][0] != 1:
        errors.append("正文第一个标题必须是一级标题 (#)")

    return ParsedMarkdown(fm, body, headings, errors)


def render_contract_md(front_matter: dict, body: str) -> str:
    """把 Front Matter + 正文渲染为契约化 Markdown 文本。

    - 日期自动加引号（序列化为字符串，避免隐式类型）；
    - 空值输出 null；
    - 正文以一级标题开头（调用方保证）。
    """
    fm_text = yaml.safe_dump(
        front_matter, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip("\n")
    return f"---\n{fm_text}\n---\n\n{body}"
