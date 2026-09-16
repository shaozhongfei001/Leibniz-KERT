"""D-23 纳入入口：执行 `tests/e2e/kert_api_validation.py` 的 21 条业务期望（逐条断言）。

方案：`evidence/m7-3/PLAN_D-23-PYTEST-ADOPTION.md`（方案 B + 7 处改名同轮）。

设计边界：

- **不改** legacy 脚本的任何判据；本文件只做「执行 + 逐条断言」。
- 逐条断言**复用** legacy 的 `EndpointResult.passed`（= `expect_http` 且 `expect_status` 且 结构检查），
  **不新增**任何「只看 HTTP 200」的弱判据。
- 防空转：21 条静态 ID 与实测结果**逐条一一对应**（每个 ID 恰好命中一条）。
- 防复发（TL 追加要求）：legacy 模块内**不得再出现 `test_*` 函数** —— 否则一旦有人把文件名改成
  `test_*.py` 或给 pytest 加 `python_files` 配置，它们会**静默复活成 7 条 ERROR**；并断言 legacy
  文件名**不出现在收集结果**中。

环境：需要 KERT 活服务；`kert_client` 夹具（`tests/e2e/conftest.py`）在服务缺失且被 require 时
**失败而非跳过**（`E2E_REQUIRE_KERT=1`）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from . import kert_api_validation
from .kert_api_validation import TEST_CUSTOMER_ID, run_validation

#: e2e 目录**收集下限**：既有 15 条（`test_all_skills_execution.py`）+ 本文件 22 条
#: （21 逐条 + 1 条收集契约）。取**入库态**而非当轮实测值（口径同 D-6 §6.4 的 E-12）。
E2E_COLLECTION_FLOOR = 37

#: 21 条**稳定 ID**（动态路径用前缀匹配，见 `_matches`）。
CASE_IDS: tuple[str, ...] = (
    "health",
    "gates",
    "gates_audit",
    "skill:SP-20",
    "skill:SP-21",
    "skill:skill-customer-previsit-report",
    "skill:bank-front-supply-chain-graph",
    "skill:skill-customer-outreach-script",
    "skill:skill-customer-meeting-script",
    "skill:bank-front-commitment-script",
    "skill:bank-front-eight-dimension",
    "skill:bank-front-fact-reconciliation",
    "skill:bank-front-kyc-gap-check",
    "skill:bank-front-product-recommendation",
    "skill:bank-front-report-assembler",
    "async_sp20",
    "job_status",
    "job_404",
    "report",
    "report_404",
    "unknown_skill",
)

#: legacy 脚本文件名（用于「不得被收集」的断言）。
_LEGACY_FILENAME = Path(kert_api_validation.__file__).name


def _matches(case_id: str, result: kert_api_validation.EndpointResult) -> bool:
    """稳定 ID ↔ legacy `EndpointResult.endpoint` 的机械匹配（动态路径用前缀 + 排除哨兵）。"""
    endpoint = result.endpoint
    if case_id == "health":
        return endpoint == "/api/skill/health"
    if case_id == "gates":
        return endpoint == f"/api/skill/gates/{TEST_CUSTOMER_ID}"
    if case_id == "gates_audit":
        return endpoint == "/api/skill/gates/audit"
    if case_id.startswith("skill:"):
        return endpoint.startswith(f"/api/skill/execute ({case_id.split(':', 1)[1]} /")
    if case_id == "async_sp20":
        return endpoint == "/api/skill/execute (async SP-20)"
    if case_id == "unknown_skill":
        return endpoint == "/api/skill/execute (UNKNOWN)"
    if case_id == "job_status":
        return endpoint.startswith("/v1/jobs/") and endpoint != "/v1/jobs/NONEXISTENT-JOB"
    if case_id == "job_404":
        return endpoint == "/v1/jobs/NONEXISTENT-JOB"
    if case_id == "report":
        return endpoint.startswith("/api/skill/report/") and endpoint != "/api/skill/report/NONEXISTENT"
    if case_id == "report_404":
        return endpoint == "/api/skill/report/NONEXISTENT"
    raise AssertionError(f"未登记的 case_id：{case_id!r}（CASE_IDS 与 _matches 必须同步）")


def _pick(validation_result: kert_api_validation.ValidationResult, case_id: str):
    """取该 ID 命中的**唯一**一条结果；0 条或 >1 条都失败（防空转、防含糊匹配）。"""
    hits = [r for r in validation_result.endpoint_results if _matches(case_id, r)]
    assert len(hits) == 1, (
        f"case_id={case_id!r} 命中 {len(hits)} 条（必须恰好 1 条）；"
        f"实际端点={[r.endpoint for r in validation_result.endpoint_results]}"
    )
    return hits[0]


@pytest.fixture(scope="session")
def validation_result(kert_client: object) -> kert_api_validation.ValidationResult:
    """用**既有** session 夹具 `kert_client` 执行一次全量验证（缺失服务 ⇒ require 语义 fail，不 skip）。

    `run_validation()` 只跑一次；21 条断言由 parametrize 派生 ⇒ 既省时又保留逐条可归因性。
    """
    # rstrip("/")：legacy 内部按 f"{base_url}{path}" 拼接（path 以 / 开头）
    return run_validation(str(kert_client.base_url).rstrip("/"))  # type: ignore[attr-defined]


def test_collection_contract(request: pytest.FixtureRequest, validation_result) -> None:
    """收集/覆盖契约（D-23 TL 追加要求）：(a1) 收集下限 (a2) legacy 未被收集 (b) 防复发。"""
    ours = Path(__file__)
    e2e_items = [item for item in request.session.items if Path(str(item.path)).parent == ours.parent]
    others = [item for item in e2e_items if Path(str(item.path)) != ours]

    # (a2) legacy 文件名**不得**出现在收集结果中（任何调用范围下都成立）
    leaked = [str(item.path) for item in e2e_items if Path(str(item.path)).name == _LEGACY_FILENAME]
    assert not leaked, (
        f"legacy 脚本 {_LEGACY_FILENAME} 被 pytest 收集了：{leaked}；"
        "D-23 方案 B 要求它保持「非收集」状态"
    )

    # (a1) 收集下限：仅当本次 session 覆盖到**其它 e2e 文件**（= 目录级/全量运行）时判定；
    #      单文件调用（`pytest tests/e2e/test_api_validation_adoption.py`）不适用本下限（已在方案中声明）。
    if others:
        assert len(e2e_items) >= E2E_COLLECTION_FLOOR, (
            f"e2e 收集数 {len(e2e_items)} < 下限 {E2E_COLLECTION_FLOOR}"
            f"（= 既有 15 + 本文件 {len(CASE_IDS) + 1}）—— 存在计划外裁减/排除"
        )

    # (b) 防复发：legacy 模块内**不得**再出现 test_* 函数
    revived = sorted(name for name in dir(kert_api_validation) if name.startswith("test_"))
    assert not revived, (
        f"legacy 模块内出现 test_* 函数 {revived} —— 一旦文件名改为 test_*.py 或 pyproject 增加 "
        "python_files 配置，它们会静默复活成 7 条 ERROR（见 D-23）"
    )

    # (a3) 条数契约：本文件 = 21 逐条 + 本条；且验证器确实产出 21 条结果
    assert len(e2e_items) - len(others) == len(CASE_IDS) + 1
    assert len(validation_result.endpoint_results) == len(CASE_IDS)


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_endpoint(validation_result: kert_api_validation.ValidationResult, case_id: str) -> None:
    """逐条断言：**复用** legacy 的 `passed` 判据（不新增弱于它的判据）。"""
    result = _pick(validation_result, case_id)
    assert result.passed, f"{result.endpoint} → HTTP {result.status_code}；{result.error}；{result.notes}"
