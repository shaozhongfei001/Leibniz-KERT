"""D-28 层 2 第三片：**文件合同 `schema` 标签域**的单源核对（源 ↔ 声明 ↔ 写入方 ↔ 合同 enum）。

本域的性质（**为什么这处该立源**）：标签是 **KERT 自己写出**的合同标识（不是外部传入的结论、
也不是推模式入参）⇒ 实现侧**拥有**该词汇；此前"声明处（`SchemaSpec.schema_name`）"与
"写入处（`_write_status` / `_write_report` 的字典字面量）"**各自硬编码**同一字符串，
无任何机械关系 ⇒ 改名只会静默分叉（声明与写出的文件不再互相印证）。

三处分工：

- **源** = `domain/contracts/specs.JOB_STATUS_SCHEMA` / `RUN_REPORT_SCHEMA`
  （`activation_plan.SCHEMA` 早已存在，本批只补登记）—— 本文件 ①；
- **声明侧** = `JOB_STATUS_SPEC.schema_name` / `RUN_REPORT_SPEC.schema_name` —— 本文件 ①；
- **写入侧（真实路径）** = `application/jobs.py` 的 `_write_status` / `_write_report` —— 本文件 ②；
- **合同侧** = OpenAPI `JobStatusData.schema` / `ActivationPlan.schema` —— 由
  `tests/unit/test_contract_enum_single_source.py` 的 `MAPPINGS` 机械核对（本文件不重复）；
  `run_report/v1` **不在** OpenAPI 内 ⇒ 无合同行，只有"声明 == 常量 + 写入方无字面量"。

⚠ 边界：`specs.py` 内还有约 24 个同类标签（`raw_manifest/v1`…`gate_report/v1`）**本批不动**
（逐域切片）；本文件**不**声称全仓标签已单源。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.jobs import JobController, read_job_status  # noqa: E402
from kert.domain.activation_plan import SCHEMA as ACTIVATION_PLAN_SCHEMA  # noqa: E402
from kert.domain.contracts import specs as contract_specs  # noqa: E402
from kert.domain.contracts.specs import (  # noqa: E402
    JOB_STATUS_SCHEMA,
    RUN_REPORT_SCHEMA,
)
from kert.infrastructure import markdown  # noqa: E402
from kert.infrastructure.fs import WorkspaceWriter  # noqa: E402

JOBS_SRC = REPO_ROOT / "src" / "kert" / "application" / "jobs.py"
PLAN_SRC = REPO_ROOT / "src" / "kert" / "domain" / "activation_plan.py"


# --------------------------------------------------------------------------- #
# ① 源自身 + 声明侧
# --------------------------------------------------------------------------- #

def test_sources_are_named_and_pinned():
    """值域钉住（**零行为变化**基线）：改名必须在此显形。"""
    assert JOB_STATUS_SCHEMA == "job_status/v1"
    assert RUN_REPORT_SCHEMA == "run_report/v1"
    assert ACTIVATION_PLAN_SCHEMA == "activation_plan/v1"
    assert len({JOB_STATUS_SCHEMA, RUN_REPORT_SCHEMA, ACTIVATION_PLAN_SCHEMA}) == 3, "标签必须互异"


def test_declarations_use_the_named_sources():
    """声明侧**必须**引用命名源（否则"源"与"被校验的形状"又会分叉）。"""
    assert contract_specs.JOB_STATUS_SPEC.schema_name == JOB_STATUS_SCHEMA
    assert contract_specs.RUN_REPORT_SPEC.schema_name == RUN_REPORT_SCHEMA


# --------------------------------------------------------------------------- #
# ② 写入侧（真实路径：真写 STATUS.md / RUN_REPORT.md 再读回）
# --------------------------------------------------------------------------- #

def _run_job(ws, job_type: str = "INGEST", key: str = "tags-001") -> JobController:
    ctrl = JobController(ws, WorkspaceWriter(ws), job_type=job_type,
                         requested_by="c20-tag-test", idempotency_key=key)
    return ctrl.start()


def test_status_doc_writes_the_named_tag(ws):
    """走真实写入路径：STATUS.md 的 front matter `schema` == 命名源（字节钉子）。"""
    ctrl = _run_job(ws, key="tags-status")
    fm = read_job_status(ws, ctrl.job_id)
    assert fm["schema"] == JOB_STATUS_SCHEMA, fm.get("schema")
    assert fm["schema"] == "job_status/v1", "立源是零行为变化：写出的字节必须不变"


def test_run_report_writes_the_named_tag(ws):
    """RUN_REPORT.md 同样钉住（该标签不在 OpenAPI 内 ⇒ 只能靠本类核对）。

    走**真实解析路径**（`markdown.parse_contract_md` 按标签查合同）⇒ `parsed.ok` 同时证明
    "写出的标签能对上已声明的合同"，比字符串包含更强。
    """
    ctrl = _run_job(ws, key="tags-report")
    ctrl.fail("E_TAG_TEST", "标签域用例：故意失败以产出 RUN_REPORT.md")
    rel = f"90_control/jobs/{ctrl.job_id}/RUN_REPORT.md"
    parsed = markdown.parse_contract_md((ws / rel).read_text(encoding="utf-8"), path=rel)
    assert parsed.ok, parsed.errors
    assert parsed.front_matter["schema"] == RUN_REPORT_SCHEMA == "run_report/v1"


def test_writers_have_no_stray_tag_literals():
    """**防复发**：`jobs.py` 内不得再出现两枚标签的字面量（只许用命名源常量）。"""
    src = JOBS_SRC.read_text(encoding="utf-8")
    strays = [tag for tag in (JOB_STATUS_SCHEMA, RUN_REPORT_SCHEMA) if f'"{tag}"' in src]
    assert strays == [], f"写入方仍硬编码标签字面量（须改用命名源）: {strays}"


def test_plan_module_uses_named_schema_in_both_places():
    """`activation_plan.py`：构造（`schema=SCHEMA`）与渲染（`schema={SCHEMA}`）都取同一命名源，
    且标签字面量**只允许出现在定义行**（其余用法一律走常量 ⇒ 改名只动一处）。"""
    src = PLAN_SRC.read_text(encoding="utf-8")
    occurrences = src.count(f'"{ACTIVATION_PLAN_SCHEMA}"')
    assert occurrences == 1, (
        f"标签字面量只允许出现在定义行 `SCHEMA = \"{ACTIVATION_PLAN_SCHEMA}\"`（实测 {occurrences} 次）")
    assert f'SCHEMA = "{ACTIVATION_PLAN_SCHEMA}"' in src, "命名源定义行未找到（可能被改名）"
    assert 'schema=SCHEMA' in src and "schema={SCHEMA}" in src, (
        "命名源必须同时被构造与渲染使用（否则两处又可分叉）")
