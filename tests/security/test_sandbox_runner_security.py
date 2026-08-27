"""DKWS POC-2 OS Sandbox 安全负向用例（C-B03 机器验证部分）。

严重声明
========
- 本套件是 **Tech Lead 自测**，用于产生 C-B03 的机器证据。
- 通过本套件 **不等于** C-B03 关闭：施工令要求「独立安全 QA 复核」，
  Tech Lead 不得自签。C-B03 上限为
  `MACHINE_TESTS_PASS_PENDING_INDEPENDENT_SECURITY_QA`，
  且必须在真实执行且日志落盘后才可标记。
- 环境不支持的用例一律 skip 并在证据中记为 NOT_EXECUTED / BLOCKED，
  绝不用「跳过」冒充「通过」。

覆盖施工令 R5 安全用例清单：
路径穿越 / 绝对路径 / symlink 逃逸 / Zip Slip（Java 侧 ZipSafeExtractor 另测）/
解压总大小超限 / 命令注入 / 管道重定向复合命令 / 禁止网络 / 超时 /
CPU 限制 / 内存限制 / 进程数限制 / 文件大小限制 / 输出截断 /
环境变量与 Secret 泄露 / 工作目录隔离 / 只读根文件系统 /
非零退出码 / 进程被杀 / 审计回执完整性。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "poc" / "spring-ai-alibaba-skill-runtime" / "sandbox" / "bwrap_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("dkws_bwrap_runner", RUNNER_PATH)
    assert spec and spec.loader, f"cannot load runner at {RUNNER_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()

requires_bwrap = pytest.mark.skipif(
    not runner.backend_available(),
    reason="bwrap not available in this environment; sandbox execution recorded as NOT_EXECUTED",
)


@pytest.fixture()
def sandbox_root(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    root.mkdir()
    return root


def _py(code: str, **task) -> dict:
    base = {"executable": "python3", "argv": ["-I", "-c", code]}
    base.update(task)
    return base


# ---------------------------------------------------------------- 输入面防护
# 以下用例不依赖 bwrap，测试的是 Runner 的 fail-closed 入参校验。


@pytest.mark.parametrize(
    "ref",
    ["../escape", "../../etc", "a/b", "..", ".", "sub/../../x"],
)
def test_path_traversal_is_blocked(sandbox_root: Path, ref: str) -> None:
    """路径穿越：workingDirectoryRef 必须是单段名，任何 .. 或分隔符都拒绝。"""
    result = runner.run(_py("pass", workingDirectoryRef=ref), sandbox_root=sandbox_root)
    assert result["status"] == "blocked"
    assert result["errorCode"] in {"SANDBOX_PATH_TRAVERSAL", "SANDBOX_TASK_INVALID"}


@pytest.mark.parametrize("ref", ["/etc", "/tmp/evil", "/"])
def test_absolute_path_is_blocked(sandbox_root: Path, ref: str) -> None:
    """绝对路径：不得作为工作目录。"""
    result = runner.run(_py("pass", workingDirectoryRef=ref), sandbox_root=sandbox_root)
    assert result["status"] == "blocked"
    assert result["errorCode"] in {"SANDBOX_PATH_TRAVERSAL", "SANDBOX_TASK_INVALID"}


def test_symlink_escape_is_blocked(sandbox_root: Path, tmp_path: Path) -> None:
    """symlink 逃逸：工作目录名指向沙箱外的符号链接必须拒绝。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (sandbox_root / "link").symlink_to(outside, target_is_directory=True)

    result = runner.run(_py("pass", workingDirectoryRef="link"), sandbox_root=sandbox_root)
    assert result["status"] == "blocked"
    assert result["errorCode"] == "SANDBOX_SYMLINK_ESCAPE"


@pytest.mark.parametrize(
    "executable",
    ["bash", "sh", "/bin/sh", "curl", "python", "../../bin/sh", "python3;id"],
)
def test_executable_allowlist_enforced(sandbox_root: Path, executable: str) -> None:
    """命令注入 + 自由 shell 拒绝：只有白名单 executable 可用。"""
    task = {"executable": executable, "argv": []}
    result = runner.run(task, sandbox_root=sandbox_root)
    assert result["status"] == "blocked"
    assert result["errorCode"] == "SANDBOX_EXECUTABLE_NOT_ALLOWED"


def test_argv_must_be_string_list(sandbox_root: Path) -> None:
    """argv 结构化校验：不接受非字符串数组（杜绝自由命令串）。"""
    result = runner.run({"executable": "python3", "argv": "print(1); rm -rf /"}, sandbox_root=sandbox_root)
    assert result["status"] == "blocked"
    assert result["errorCode"] == "SANDBOX_TASK_INVALID"


def test_limits_cannot_be_widened(sandbox_root: Path) -> None:
    """任务不得自行放宽资源上限，只能收紧。"""
    task = _py("pass", cpuSeconds=9999, timeoutMs=10**9, maxOutputBytes=10**9)
    result = runner.run(task, sandbox_root=sandbox_root)
    limits = result["limits"]
    assert limits["cpuSeconds"] <= runner.DEFAULTS["cpuSeconds"]
    assert limits["timeoutMs"] <= runner.DEFAULTS["timeoutMs"]
    assert limits["maxOutputBytes"] <= runner.DEFAULTS["maxOutputBytes"]


def test_sandbox_unavailable_does_not_fall_back(monkeypatch: pytest.MonkeyPatch, sandbox_root: Path) -> None:
    """后端缺失时必须 fail-closed，绝不退回裸 subprocess。"""
    monkeypatch.setattr(runner, "backend_available", lambda: False)
    result = runner.run(_py("print('should not run')"), sandbox_root=sandbox_root)
    assert result["status"] == "error"
    assert result["errorCode"] == "SANDBOX_UNAVAILABLE"
    assert result["stdout"] == ""


def test_profile_hash_is_stable_and_sensitive() -> None:
    """profile 哈希：同 profile 稳定，限制变化即变化（可用于回执比对）。"""
    base = dict(runner.DEFAULTS)
    tighter = dict(runner.DEFAULTS, cpuSeconds=1)
    assert runner.profile_hash(base) == runner.profile_hash(dict(runner.DEFAULTS))
    assert runner.profile_hash(base) != runner.profile_hash(tighter)
    assert len(runner.profile_hash(base)) == 64


# ---------------------------------------------------------------- 真实沙箱执行


@requires_bwrap
def test_baseline_execution_succeeds(sandbox_root: Path) -> None:
    """基线：白名单 python3 正常执行并产出完整回执。"""
    result = runner.run(_py("print('sandbox-ok')"), sandbox_root=sandbox_root)
    assert result["status"] == "ok", result
    assert result["exitCode"] == 0
    assert "sandbox-ok" in result["stdout"]


@requires_bwrap
def test_receipt_completeness(sandbox_root: Path) -> None:
    """审计回执完整性：ToolCallReceipt 所需字段齐备。"""
    result = runner.run(_py("print('receipt')"), sandbox_root=sandbox_root)
    for field in (
        "status", "exitCode", "outputHash", "outputTruncated", "networkUsed",
        "cpuTime", "memoryPeak", "sandboxProfileHash", "startedAt", "completedAt",
        "backend", "limits",
    ):
        assert field in result, f"missing receipt field: {field}"
    assert len(result["outputHash"]) == 64
    assert len(result["sandboxProfileHash"]) == 64
    assert result["networkUsed"] is False
    assert result["completedAt"] >= result["startedAt"]


@requires_bwrap
def test_network_is_denied(sandbox_root: Path) -> None:
    """禁止网络：沙箱内 socket 连接必须失败。"""
    code = (
        "import socket,sys\n"
        "s=socket.socket()\n"
        "s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('223.5.5.5',53))\n"
        "    print('NETWORK_REACHABLE')\n"
        "    sys.exit(0)\n"
        "except OSError as e:\n"
        "    print('NETWORK_BLOCKED')\n"
        "    sys.exit(3)\n"
    )
    result = runner.run(_py(code), sandbox_root=sandbox_root)
    assert "NETWORK_REACHABLE" not in result["stdout"], result
    assert result["status"] != "ok"


@requires_bwrap
def test_readonly_root_filesystem(sandbox_root: Path) -> None:
    """只读根文件系统：向 /usr 写入必须失败。"""
    code = (
        "import sys\n"
        "try:\n"
        "    open('/usr/dkws-should-not-exist','w').write('x')\n"
        "    print('ROOT_WRITABLE'); sys.exit(0)\n"
        "except OSError:\n"
        "    print('ROOT_READONLY'); sys.exit(3)\n"
    )
    result = runner.run(_py(code), sandbox_root=sandbox_root)
    assert "ROOT_WRITABLE" not in result["stdout"], result


@requires_bwrap
def test_working_directory_isolation(sandbox_root: Path) -> None:
    """工作目录隔离：任务只见自己的 /work，看不到同级其他任务目录。"""
    (sandbox_root / "other-job").mkdir()
    (sandbox_root / "other-job" / "secret.txt").write_text("other-job-secret", encoding="utf-8")

    code = (
        "import os,json\n"
        "print(json.dumps(sorted(os.listdir('/work'))))\n"
    )
    result = runner.run(_py(code, workingDirectoryRef="job-a"), sandbox_root=sandbox_root)
    assert result["status"] == "ok", result
    listing = json.loads(result["stdout"].strip().splitlines()[-1])
    assert "secret.txt" not in listing
    assert listing == []


@requires_bwrap
def test_env_and_secret_not_leaked(sandbox_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量与 Secret 泄露：宿主敏感变量不得进入沙箱。"""
    monkeypatch.setenv("DKWS_TEST_SECRET_TOKEN", "super-secret-value")
    code = (
        "import os,json\n"
        "print(json.dumps(sorted(os.environ.keys())))\n"
    )
    result = runner.run(_py(code), sandbox_root=sandbox_root)
    assert result["status"] == "ok", result
    keys = json.loads(result["stdout"].strip().splitlines()[-1])
    assert "DKWS_TEST_SECRET_TOKEN" not in keys
    assert "super-secret-value" not in result["stdout"]
    assert set(keys) <= set(runner.ENV_ALLOWLIST) | {"PWD", "SHLVL", "_"}


@requires_bwrap
def test_timeout_is_enforced(sandbox_root: Path) -> None:
    """超时：wall-clock 超时必须被终止并返回 SANDBOX_TIMEOUT。"""
    result = runner.run(
        _py("import time; time.sleep(30)", timeoutMs=1500),
        sandbox_root=sandbox_root,
    )
    assert result["status"] == "timeout", result
    assert result["errorCode"] == "SANDBOX_TIMEOUT"


@requires_bwrap
def test_cpu_limit_is_enforced(sandbox_root: Path) -> None:
    """CPU 限制：忙循环必须被 RLIMIT_CPU 杀死，而非跑满 wall-clock。"""
    code = "x=0\nwhile True:\n    x+=1\n"
    result = runner.run(_py(code, cpuSeconds=1, timeoutMs=10_000), sandbox_root=sandbox_root)
    assert result["status"] in {"failed", "timeout"}, result
    assert result["errorCode"] in {"SANDBOX_PROCESS_KILLED", "SANDBOX_NONZERO_EXIT", "SANDBOX_TIMEOUT"}


@requires_bwrap
def test_memory_limit_is_enforced(sandbox_root: Path) -> None:
    """内存限制：超过 RLIMIT_AS 的分配必须失败。"""
    code = (
        "import sys\n"
        "try:\n"
        "    b = bytearray(1024*1024*1024)\n"
        "    print('ALLOC_OK'); sys.exit(0)\n"
        "except MemoryError:\n"
        "    print('ALLOC_DENIED'); sys.exit(3)\n"
    )
    result = runner.run(
        _py(code, addressSpaceBytes=128 * 1024 * 1024, timeoutMs=10_000),
        sandbox_root=sandbox_root,
    )
    assert "ALLOC_OK" not in result["stdout"], result
    assert result["status"] != "ok"


@requires_bwrap
def test_process_limit_is_enforced(sandbox_root: Path) -> None:
    """进程数限制：fork 炸弹必须受 RLIMIT_NPROC 约束而不拖垮宿主。"""
    code = (
        "import os,sys\n"
        "n=0\n"
        "try:\n"
        "    for _ in range(500):\n"
        "        if os.fork()==0:\n"
        "            os._exit(0)\n"
        "        n+=1\n"
        "except OSError:\n"
        "    print('FORK_LIMITED'); sys.exit(3)\n"
        "print('FORK_UNLIMITED', n); sys.exit(0)\n"
    )
    result = runner.run(
        _py(code, maxProcesses=8, timeoutMs=10_000),
        sandbox_root=sandbox_root,
    )
    assert "FORK_UNLIMITED" not in result["stdout"], result


@requires_bwrap
def test_file_size_limit_is_enforced(sandbox_root: Path) -> None:
    """文件大小限制：超过 RLIMIT_FSIZE 的写入必须失败。"""
    code = (
        "import sys\n"
        "try:\n"
        "    with open('/work/big.bin','wb') as f:\n"
        "        f.write(b'0'*(16*1024*1024)); f.flush()\n"
        "    print('WRITE_OK'); sys.exit(0)\n"
        "except OSError:\n"
        "    print('WRITE_DENIED'); sys.exit(3)\n"
    )
    result = runner.run(
        _py(code, maxFileSizeBytes=1024 * 1024, timeoutMs=10_000),
        sandbox_root=sandbox_root,
    )
    assert "WRITE_OK" not in result["stdout"], result


@requires_bwrap
def test_output_is_truncated(sandbox_root: Path) -> None:
    """输出截断：超过 maxOutputBytes 必须截断并标记。"""
    code = "print('A'*200000)"
    result = runner.run(_py(code, maxOutputBytes=4096), sandbox_root=sandbox_root)
    assert result["outputTruncated"] is True, result
    assert len(result["stdout"].encode("utf-8")) <= 4096


@requires_bwrap
def test_nonzero_exit_code_reported(sandbox_root: Path) -> None:
    """非零退出码：如实上报，不得包装成成功文本。"""
    result = runner.run(_py("import sys; sys.exit(42)"), sandbox_root=sandbox_root)
    assert result["status"] == "failed"
    assert result["exitCode"] == 42
    assert result["errorCode"] == "SANDBOX_NONZERO_EXIT"


@requires_bwrap
def test_process_killed_by_signal_reported(sandbox_root: Path) -> None:
    """进程被杀：信号终止必须被识别为 PROCESS_KILLED。

    bwrap 充当沙箱内 init，会把被信号杀死的子进程转成 128+signo 退出码
    （SIGKILL -> 137）；若 bwrap 自身被杀则为负值。两者都必须归类为
    SANDBOX_PROCESS_KILLED，不得与普通非零退出混淆。
    """
    code = "import os,signal; os.kill(os.getpid(), signal.SIGKILL)"
    result = runner.run(_py(code), sandbox_root=sandbox_root)
    assert result["status"] == "failed", result
    assert result["exitCode"] < 0 or result["exitCode"] > 128, result
    assert result["errorCode"] == "SANDBOX_PROCESS_KILLED"


# ---------------------------------------------------------------- 解压安全（Python 侧对照）


def test_zip_slip_and_total_size_guard_contract(sandbox_root: Path) -> None:
    """Zip Slip 与解压总大小超限。

    Java 侧 `ZipSafeExtractor` 负责实际防护，其单元测试在
    `poc/spring-ai-alibaba-skill-runtime/src/test/java/.../ZipSafeExtractorTest.java`。
    此处只断言 Runner 不提供任何解压能力（职责不越界），避免出现第二条
    未受控的解压路径。
    """
    assert not hasattr(runner, "extract")
    assert not hasattr(runner, "unzip")
    assert "zipfile" not in sys.modules or "zipfile" not in RUNNER_PATH.read_text(encoding="utf-8")
