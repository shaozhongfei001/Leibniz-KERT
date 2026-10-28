"""`kert provision` CLI 面测试（M7.3 第五步）。

**独立成文件**的原因：`typer` 是声明依赖（CI 由 ``pip install -e .[dev]`` 安装），
但精简开发环境可能未装。若把 ``pytest.importorskip("typer")`` 放在
``test_provision.py`` 顶部，会连**整个模块**（含核心供给测试）一起被跳过，
退出码变成 5（no tests ran）——那是"看起来跑了其实没跑"。故 CLI 面单独成文件：
本模块可跳，供给核心测试永不跳。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

typer = pytest.importorskip("typer")

from typer.testing import CliRunner  # noqa: E402

from kert.cli.main import app as cli_app  # noqa: E402
from kert.domain.errors import SchemaValidationError, UsageError  # noqa: E402
from kert.domain.workspace import init_workspace  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
CATALOG = "90_control/catalog"
SCHEMA_DIR = "90_control/schema"


@pytest.fixture
def target(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    init_workspace(ws)
    return ws


@pytest.fixture
def source_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "src"
    shutil.copytree(SOURCE, dst)
    return dst


def _run(args: list[str]):
    return CliRunner().invoke(cli_app, args)


_COUNTS_RE = re.compile(r"新建 (\d+) / 覆盖 (\d+) / 未变 (\d+)")


def _counts(output: str) -> tuple[int, int, int]:
    """从 CLI 文本输出取（新建 / 覆盖 / 未变）三元组。

    **刻意不硬编码总数**：源侧声明数会随"第三方在途"件入库而变化
    （`schema/activations/AC-*.json` 未入库时 6 份、入库后 8 份）。
    把总数写死会把"源内容变动"误报成"供给逻辑错误" —— 实测于 PR #6：
    3 条用例因 `8 vs 6` 变红，而供给逻辑本身正确。
    本文件断言的是**关系**（首次全新建 / 复跑全未变），与总数无关。
    """
    m = _COUNTS_RE.search(output)
    assert m, f"未找到计数行（新建/覆盖/未变）：{output!r}"
    created, overwritten, unchanged = (int(x) for x in m.groups())
    return created, overwritten, unchanged


def test_apply_then_idempotent_rerun(target):
    r = _run(["provision", "-w", str(target), "-s", str(SOURCE)])
    assert r.exit_code == 0, r.output
    created, overwritten, unchanged = _counts(r.output)
    assert created > 0 and overwritten == 0 and unchanged == 0
    assert "RP-KERT-BANKFRONT-001@1.1.0" in r.output

    r2 = _run(["provision", "-w", str(target), "-s", str(SOURCE)])
    assert r2.exit_code == 0, r2.output
    # 幂等：复跑**零新建、零覆盖**，且"未变"恰好等于首次供给份数
    assert _counts(r2.output) == (0, 0, created)


def test_json_output_follows_standard_envelope(target):
    r = _run(["provision", "-w", str(target), "-s", str(SOURCE), "--output", "json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["status"] == "OK"
    items = payload["data"]["items"]
    assert payload["data"]["counts"]["CREATED"] == len(items) > 0
    assert payload["data"]["policyId"] == "RP-KERT-BANKFRONT-001"
    assert any(i["relPath"].endswith("knowledge_sources.json")
               for i in payload["data"]["items"])


def test_dry_run_leaves_workspace_empty(target):
    r = _run(["provision", "-w", str(target), "-s", str(SOURCE), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "未落盘" in r.output
    assert list((target / CATALOG).glob("KM-*.json")) == []


def test_invalid_source_fails_closed(target, source_copy):
    bad = source_copy / CATALOG / "KM-CORP-RM-MEETING.json"
    doc = json.loads(bad.read_text(encoding="utf-8"))
    del doc["mapId"]
    bad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    r = _run(["provision", "-w", str(target), "-s", str(source_copy)])
    assert r.exit_code != 0
    assert isinstance(r.exception, SchemaValidationError)
    assert list((target / CATALOG).glob("KM-*.json")) == []
    assert list((target / SCHEMA_DIR).glob("*.json")) == []


# --------------------------------------------------------------------------- #
# `--init`：容器化首次部署的空卷（编排依赖此行为；起因是冒烟实测 provision 失败）
# --------------------------------------------------------------------------- #

def test_init_flag_initializes_fresh_volume_then_provisions(tmp_path):
    ws = tmp_path / "fresh"          # 不存在（等价于首次挂载的空卷）
    r = _run(["provision", "-w", str(ws), "-s", str(SOURCE), "--init"])
    assert r.exit_code == 0, r.output
    assert "已初始化工作区" in r.output
    assert (ws / ".kert_workspace").is_file()
    # 推导式：与**受控源**的地图张数一致（M7 ② 起为 7；不写死总数）
    assert len(list((ws / CATALOG).glob("KM-*.json"))) == \
        len(list((SOURCE / CATALOG).glob("KM-*.json"))) >= 7
    created, _, _ = _counts(r.output)

    # 已初始化 ⇒ no-op，且照常幂等供给
    r2 = _run(["provision", "-w", str(ws), "-s", str(SOURCE), "--init"])
    assert r2.exit_code == 0, r2.output
    assert "跳过 init" in r2.output
    assert _counts(r2.output) == (0, 0, created)


def test_without_init_flag_uninitialized_target_fails_closed(tmp_path):
    """不带 ``--init`` ⇒ 目标未初始化即报错，**不隐式创建**。"""
    ws = tmp_path / "fresh2"
    r = _run(["provision", "-w", str(ws), "-s", str(SOURCE)])
    assert r.exit_code != 0
    assert isinstance(r.exception, UsageError)


def test_init_flag_refuses_nonempty_uninitialized_dir(tmp_path):
    """非空且未初始化 ⇒ 仍按既有纪律报错，**不静默改写**他人在用目录。"""
    ws = tmp_path / "notempty"
    ws.mkdir()
    (ws / "keep.txt").write_text("运维在用", encoding="utf-8")

    r = _run(["provision", "-w", str(ws), "-s", str(SOURCE), "--init"])
    assert r.exit_code != 0
    assert isinstance(r.exception, UsageError)
    assert (ws / "keep.txt").read_text(encoding="utf-8") == "运维在用"
    assert not (ws / ".kert_workspace").exists()
