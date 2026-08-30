"""JR-1：内部契约哈希可重算性测试（JR-1 §6.4）。

契约哈希是双端一致性的锚点：Python Core 与 Java Runtime 必须对
同一份契约算出同一个哈希，否则视为契约漂移。
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from .conftest import REPO_ROOT, SCHEMA_FILES

HASH_SCRIPT = REPO_ROOT / "scripts" / "internal_contract_hash.py"
EVIDENCE_HASH_FILE = REPO_ROOT / "evidence" / "jr1" / "internal-contract-hash.txt"


def _run_hash_script() -> dict:
    """执行契约哈希脚本并返回其 JSON 输出。"""
    proc = subprocess.run(
        [sys.executable, str(HASH_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"哈希脚本失败: {proc.stderr}"
    return json.loads(proc.stdout)


def _file_map(output: dict) -> dict[str, str]:
    """把 ``files`` 列表转为 ``相对路径 -> sha256`` 映射。"""
    return {entry["path"]: entry["sha256"] for entry in output["files"]}


@pytest.fixture(scope="module")
def hash_output() -> dict:
    """契约哈希脚本输出（模块级缓存）。"""
    return _run_hash_script()


class TestHashScriptRunnable:
    """哈希脚本可运行且输出结构稳定（JR-1 §6.1）。"""

    def test_script_exists(self):
        """哈希脚本存在。"""
        assert HASH_SCRIPT.is_file(), f"缺失 {HASH_SCRIPT}"

    def test_script_outputs_expected_envelope(self, hash_output):
        """脚本输出合法 JSON 且含关键字段。"""
        assert hash_output["schema"] == "dkws-internal-contract-bundle/v1"
        assert hash_output["base_dir"] == "docs/contracts/internal"
        assert "bundle_hash" in hash_output
        assert isinstance(hash_output["files"], list)

    def test_bundle_hash_is_sha256(self, hash_output):
        """bundle 哈希为 64 位十六进制 SHA-256。"""
        value = hash_output["bundle_hash"]
        assert len(value) == 64
        assert all(c in "0123456789abcdef" for c in value)

    def test_covers_all_schema_files(self, hash_output):
        """哈希覆盖全部 6 份 Schema。"""
        covered = {p.split("/")[-1] for p in _file_map(hash_output)}
        for name in SCHEMA_FILES:
            assert name in covered, f"哈希未覆盖 {name}"

    def test_covers_openapi_file(self, hash_output):
        """哈希覆盖内部 OpenAPI 文件。"""
        assert (
            "openapi/dkws-skill-runtime-internal-v1.yaml" in _file_map(hash_output)
        )

    def test_covers_exactly_seven_controlled_files(self, hash_output):
        """哈希范围恰好为 6 份 Schema + 1 份 OpenAPI，无多余文件。"""
        paths = _file_map(hash_output)
        assert len(paths) == 7, f"受控文件数异常: {sorted(paths)}"

    def test_examples_not_in_hash_scope(self, hash_output):
        """示例文件不参与契约哈希（示例是测试资产，非契约本体）。"""
        offenders = [p for p in _file_map(hash_output) if p.startswith("examples/")]
        assert not offenders, f"示例被计入契约哈希: {offenders}"

    def test_per_file_hashes_are_sha256(self, hash_output):
        """每个文件的分项哈希均为 SHA-256。"""
        for path, digest in _file_map(hash_output).items():
            assert len(digest) == 64, f"{path} 哈希长度异常"


class TestHashDeterminism:
    """哈希可重算：同一契约多次计算结果一致。"""

    def test_recomputation_is_stable(self, hash_output):
        """连续两次计算得到相同 bundle 哈希与分项哈希。"""
        again = _run_hash_script()
        assert again["bundle_hash"] == hash_output["bundle_hash"]
        assert _file_map(again) == _file_map(hash_output)


class TestHashMatchesRecordedEvidence:
    """记录的证据哈希与当前契约一致（JR-1 §7）。"""

    def test_evidence_file_exists(self):
        """证据哈希文件已落盘。"""
        assert EVIDENCE_HASH_FILE.is_file(), f"缺失 {EVIDENCE_HASH_FILE}"

    def test_evidence_hash_matches_current_contract(self, hash_output):
        """证据文件记录的哈希等于当前重算值。

        该断言是契约漂移的主闸门：任何 Schema/OpenAPI 改动都会使其失败，
        强制同步更新证据与双端实现。
        """
        recorded = None
        for line in EVIDENCE_HASH_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("bundle_hash="):
                recorded = stripped.split("=", 1)[1].strip()
                break
        assert recorded, "证据文件未记录 bundle_hash="
        assert recorded == hash_output["bundle_hash"], (
            f"契约哈希漂移: 证据={recorded} 当前={hash_output['bundle_hash']}"
        )

    def test_no_pending_compute_placeholder(self):
        """证据文件不得残留 PENDING_COMPUTE 占位符。"""
        content = EVIDENCE_HASH_FILE.read_text(encoding="utf-8")
        assert "PENDING_COMPUTE" not in content
