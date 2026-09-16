"""`kert egress` CLI 面测试（M7 · ①）：**统一信封 + 具名退出码**（零网络）。

**独立成文件**的原因同 ``test_provision_cli.py``：``typer`` 是声明依赖，但精简开发环境可能未装；
把 ``importorskip("typer")`` 放进 ``test_egress_ops.py`` 会连**服务层**用例一起被跳过
（退出码变 5 = "看着跑了其实没跑"）。故 CLI 面单独成文件：本模块可跳，服务层用例永不跳。

短接方式：把 ``kert.cli.egress._client`` 换成**内存假实例**（与 ``test_egress_ops.py`` 同法，
此处按 CLI 断言需要保留一份**精简**副本；不抽公共夹具是为了不动既有 ``conftest.py``）。

要证明的东西（对应用户/脚本可见行为）：

- ``status``/``publish`` 的 ``stale`` ⇒ **退出码 4**（脚本据此判定，不靠解析文本）；
- ``publish --refresh`` 被归属校验拒绝 ⇒ **具名** ``LIGHTRAG_RETRACT_REFUSED`` + 退出码 4，
  且**一个删除都没发生**（D-34 反例）；
- 空匹配 / 白名单外 ⇒ 具名 + 退出码 2（**不静默回空表**）；
- 三条命令都**逐字节**不动工作区。
"""

from __future__ import annotations

import hashlib
import json

import pytest

typer = pytest.importorskip("typer")

from typer.testing import CliRunner  # noqa: E402

from kert.cli import egress as egress_mod  # noqa: E402
from kert.cli.main import app as cli_app  # noqa: E402
from kert.infrastructure.lightrag_client import (  # noqa: E402
    ALREADY_PUBLISHED,
    PUBLISHED,
    LightRagDocument,
    LightRagPipelineTimeout,
    PublishOutcome,
)

ARTIFACT_DIR = "04_serve/egress_cli_probe/version=2026.09.17.1"
ARTIFACT = f"{ARTIFACT_DIR}/ONTOLOGY.md"
BODY = "# 本体物化产物\n实体 CUST-CORP-0001。\n"
WINDOW = 400


class _Instance:
    """精简内存假实例（只实现 CLI 触达的客户端面）。"""

    def __init__(self, docs=()):
        self.docs = list(docs)
        self.published: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def documents(self, *, page_size: int = 200):
        return tuple(self.docs)

    def find_documents(self, file_source: str):
        return tuple(d for d in self.docs if d.file_path == file_source)

    def wait_until_present(self, file_source: str, *, timeout: float = 30.0,
                           interval: float = 1.0):
        found = self.find_documents(file_source)
        if not found:
            raise LightRagPipelineTimeout("fake：窗口内未可见")
        return found

    def publish_text(self, text: str, *, file_source: str, visibility_timeout: float = 30.0):
        existing = self.find_documents(file_source)
        if existing:
            return PublishOutcome(file_source=file_source, status=ALREADY_PUBLISHED,
                                  track_id=existing[0].doc_id)
        self.published.append((file_source, text))
        self.docs.append(LightRagDocument(
            doc_id=f"doc-{len(self.docs) + 1}", file_path=file_source, status="processed",
            chunks_count=1, content_summary=text[:WINDOW]))
        return PublishOutcome(file_source=file_source, status=PUBLISHED, track_id="track-1")

    def delete_documents(self, doc_ids):
        ids = [str(i) for i in doc_ids if str(i)]
        self.deleted.extend(ids)
        self.docs = [d for d in self.docs if d.doc_id not in set(ids)]
        return {"status": "ok"}

    def wait_until_absent(self, doc_ids, *, timeout: float = 180.0, interval: float = 3.0):
        want = {str(i) for i in doc_ids if str(i)}
        if {d.doc_id for d in self.docs} & want:
            raise LightRagPipelineTimeout("fake：删除未落地")


def _write(ws, rel: str = ARTIFACT, body: str = BODY) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _snapshot(ws) -> dict:
    return {p.relative_to(ws).as_posix(): p.read_bytes()
            for p in ws.rglob("*") if p.is_file()}


def _seeded(monkeypatch, ws, *, rel: str = ARTIFACT, body: str = BODY):
    """发布一份**本工作区自己的**内容到假实例（走生产发布路径 ⇒ 摘要窗口与生产同形）。"""
    from kert.application.services import KnowledgeService

    inst = _Instance()
    _write(ws, rel, body)
    KnowledgeService(ws).publish_artifact(rel, client=inst)
    inst.published.clear()
    monkeypatch.setattr(egress_mod, "_client", lambda: inst)
    return inst


def _run(args: list[str]):
    return CliRunner().invoke(cli_app, args)


def _envelope(result):
    """统一信封（``--json``）⇒ (status, data, errors)。"""
    payload = json.loads(result.output)
    return payload["status"], payload["data"], payload["errors"]


def _assert_stale_hint_spells_both_commands(text: str) -> None:
    """``stale`` 的处置必须**原样打出两条命令**（人不用猜命令名与先后顺序）。

    「反例」：把提示改回"…后再 publish"这类**半句**（缺命令名/缺 `--force`）⇒ 本条必红。
    """
    assert "kert egress retract <rel> --force" in text, text
    assert "kert egress publish <rel>" in text, text
    # 反向提醒也要在：**不得**无条件教人 force（那正是 D-34 要拦的）
    assert "疑似他人文档时" in text and "不要" in text, text


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #

def test_status_current_json(monkeypatch, ws):
    _seeded(monkeypatch, ws)
    r = _run(["egress", "status", ARTIFACT, "-w", str(ws), "--json"])
    assert r.exit_code == 0, r.output
    status, data, errors = _envelope(r)
    assert status == "OK" and errors == []
    assert data["states"] == ["current"] and data["count"] == 1
    row = data["artifacts"][0]
    assert row["artifact"] == ARTIFACT
    assert row["sha256"] == hashlib.sha256((ws / ARTIFACT).read_bytes()).hexdigest()
    assert row["documents"][0]["marker_hit"] is True


def test_status_missing_is_exit_0(monkeypatch, ws):
    _write(ws)
    monkeypatch.setattr(egress_mod, "_client", lambda: _Instance())
    r = _run(["egress", "status", ARTIFACT, "-w", str(ws), "--json"])
    assert r.exit_code == 0, r.output
    _, data, _ = _envelope(r)
    assert data["states"] == ["missing"] and data["artifacts"][0]["documents"] == []


def test_status_stale_exit_4_and_text_mode_names_it(monkeypatch, ws):
    """``stale`` ⇒ **退出码 4**；文本模式也要**看得见** ``[stale]``（人侧不能只有 json）。"""
    _seeded(monkeypatch, ws)
    _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
    r = _run(["egress", "status", ARTIFACT, "-w", str(ws)])
    assert r.exit_code == 4, r.output
    assert "[stale]" in r.output, r.output
    _assert_stale_hint_spells_both_commands(r.stderr)

    rj = _run(["egress", "status", ARTIFACT, "-w", str(ws), "--output", "json"])
    assert rj.exit_code == 4, rj.output
    _, data, _ = _envelope(rj)
    assert data["states"] == ["stale"] and data["artifacts"][0]["documents"][0]["marker_hit"] is False
    _assert_stale_hint_spells_both_commands(data["hint"])   # 脚本侧也能拿到同一处置


def test_status_expands_directory_and_glob(monkeypatch, ws):
    """目录 / glob 两种目标形式；``--json`` 与 ``--output json`` 等价。"""
    inst = _Instance()
    monkeypatch.setattr(egress_mod, "_client", lambda: inst)
    _write(ws, f"{ARTIFACT_DIR}/A.md")
    _write(ws, f"{ARTIFACT_DIR}/B.md")
    r_dir = _run(["egress", "status", ARTIFACT_DIR, "-w", str(ws), "--json"])
    assert r_dir.exit_code == 0, r_dir.output
    _, data, _ = _envelope(r_dir)
    assert data["count"] == 2 and data["states"] == ["missing"]
    assert sorted(a["artifact"].rsplit("/", 1)[-1] for a in data["artifacts"]) == ["A.md", "B.md"]

    r_glob = _run(["egress", "status", f"{ARTIFACT_DIR}/*.md", "-w", str(ws), "--output", "json"])
    assert r_glob.exit_code == 0, r_glob.output
    _, data_glob, _ = _envelope(r_glob)      # 信封含随机 request_id ⇒ 只比 data
    assert data_glob == data


def test_status_empty_match_is_named_exit_2(monkeypatch, ws):
    """**不静默回空表**：空匹配 ⇒ 具名 ``ASSET_NOT_FOUND`` + 退出码 2。"""
    monkeypatch.setattr(egress_mod, "_client", lambda: _Instance())
    r = _run(["egress", "status", f"{ARTIFACT_DIR}/NOPE.md", "-w", str(ws), "--json"])
    assert r.exit_code == 2, r.output
    status, data, errors = _envelope(r)
    assert status == "ERROR" and data["error_code"] == "ASSET_NOT_FOUND"
    assert errors[0]["code"] == "ASSET_NOT_FOUND"


def test_status_outside_egress_root_exit_2(monkeypatch, ws):
    """白名单外（本地产物真的存在也不行）⇒ 具名 ``LIGHTRAG_ARTIFACT_REFUSED`` + 退出码 2。"""
    monkeypatch.setattr(egress_mod, "_client", lambda: _Instance())
    _write(ws, "02_work/draft.md")
    r = _run(["egress", "status", "02_work/draft.md", "-w", str(ws), "--json"])
    assert r.exit_code == 2, r.output
    status, data, _ = _envelope(r)
    assert status == "ERROR" and data["error_code"] == "LIGHTRAG_ARTIFACT_REFUSED"


# --------------------------------------------------------------------------- #
# publish
# --------------------------------------------------------------------------- #

def test_publish_missing_exit_0(monkeypatch, ws):
    inst = _Instance()
    monkeypatch.setattr(egress_mod, "_client", lambda: inst)
    _write(ws)
    before = _snapshot(ws)
    r = _run(["egress", "publish", ARTIFACT, "-w", str(ws), "--json"])
    assert r.exit_code == 0, r.output
    _, data, _ = _envelope(r)
    assert data["artifacts"][0]["state"] == "published"
    assert len(inst.published) == 1 and _snapshot(ws) == before


def test_publish_stale_exit_4_and_writes_nothing(monkeypatch, ws):
    """**功能缺口反例**：内容变了 ⇒ 具名 ``stale`` + 退出码 4，且**不写不删**。"""
    inst = _seeded(monkeypatch, ws)
    _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
    summary_before = inst.docs[0].content_summary
    r = _run(["egress", "publish", ARTIFACT, "-w", str(ws), "--json"])
    assert r.exit_code == 4, r.output
    _, data, _ = _envelope(r)
    assert data["stale"] == [ARTIFACT]
    assert data["artifacts"][0]["state"] == "stale"
    assert data["artifacts"][0]["published"] is False
    assert inst.published == [] and inst.deleted == []
    assert inst.docs[0].content_summary == summary_before
    _assert_stale_hint_spells_both_commands(data["hint"])


def test_publish_current_is_idempotent_exit_0(monkeypatch, ws):
    inst = _seeded(monkeypatch, ws)
    r = _run(["egress", "publish", ARTIFACT, "-w", str(ws), "--json"])
    assert r.exit_code == 0, r.output
    _, data, _ = _envelope(r)
    assert data["artifacts"][0]["state"] == "current"
    assert data["artifacts"][0]["status"] == ALREADY_PUBLISHED
    assert inst.published == [] and len(inst.docs) == 1


def test_publish_refresh_on_current_republishes_exit_0(monkeypatch, ws):
    inst = _seeded(monkeypatch, ws)
    r = _run(["egress", "publish", ARTIFACT, "-w", str(ws), "--refresh", "--json"])
    assert r.exit_code == 0, r.output
    _, data, _ = _envelope(r)
    assert data["artifacts"][0]["state"] == "refreshed"
    assert inst.deleted == ["doc-1"] and len(inst.published) == 1


def test_publish_refresh_on_stale_is_named_refusal_exit_4(monkeypatch, ws):
    """**D-34 反例**：``--refresh`` 撤回仍受归属校验 ⇒ 具名拒绝、退出码 4、**零删除**。"""
    inst = _seeded(monkeypatch, ws)
    _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
    r = _run(["egress", "publish", ARTIFACT, "-w", str(ws), "--refresh", "--json"])
    assert r.exit_code == 4, r.output
    status, data, errors = _envelope(r)
    assert status == "ERROR" and data["error_code"] == "LIGHTRAG_RETRACT_REFUSED"
    assert errors[0]["code"] == "LIGHTRAG_RETRACT_REFUSED"
    assert inst.deleted == [] and inst.published == [], "拒绝后不得删、不得继续发布"
    assert len(inst.docs) == 1


# --------------------------------------------------------------------------- #
# retract
# --------------------------------------------------------------------------- #

def test_retract_guard_refusal_exit_4(monkeypatch, ws):
    inst = _seeded(monkeypatch, ws)
    _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
    r = _run(["egress", "retract", ARTIFACT, "-w", str(ws)])
    assert r.exit_code == 4, r.output
    assert "ERROR[LIGHTRAG_RETRACT_REFUSED]" in r.stderr, r.stderr
    assert inst.deleted == []


def test_retract_force_is_explicit_and_traced_exit_0(monkeypatch, ws):
    """``--force`` ⇒ 跳过校验但**留痕** ``verified=false``（绝不静默）。"""
    inst = _seeded(monkeypatch, ws)
    _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
    r = _run(["egress", "retract", ARTIFACT, "-w", str(ws), "--force", "--json"])
    assert r.exit_code == 0, r.output
    _, data, _ = _envelope(r)
    assert data["artifacts"][0]["verified"] is False
    assert data["artifacts"][0]["removed"] == ["doc-1"] and inst.deleted == ["doc-1"]


def test_retract_nothing_to_retract_is_exit_0(monkeypatch, ws):
    """"本就没发布"与"撤回失败"必须可区分：前者 ``nothing_to_retract``、退出码 0。"""
    monkeypatch.setattr(egress_mod, "_client", lambda: _Instance())
    _write(ws)
    r = _run(["egress", "retract", ARTIFACT, "-w", str(ws), "--json"])
    assert r.exit_code == 0, r.output
    _, data, _ = _envelope(r)
    assert data["artifacts"][0]["removed"] == []
    assert data["artifacts"][0]["status"] == "nothing_to_retract"


def test_all_commands_are_read_only_on_workspace(monkeypatch, ws):
    """三条命令在 missing/current/refresh 路径上都**逐字节**不动工作区（ADR-017 ⑥）。"""
    inst = _Instance()
    monkeypatch.setattr(egress_mod, "_client", lambda: inst)
    _write(ws)
    before = _snapshot(ws)
    assert _run(["egress", "status", ARTIFACT, "-w", str(ws)]).exit_code == 0
    assert _run(["egress", "publish", ARTIFACT, "-w", str(ws)]).exit_code == 0
    assert _run(["egress", "publish", ARTIFACT, "-w", str(ws), "--refresh"]).exit_code == 0
    assert _run(["egress", "retract", ARTIFACT, "-w", str(ws), "--force"]).exit_code == 0
    assert _snapshot(ws) == before
