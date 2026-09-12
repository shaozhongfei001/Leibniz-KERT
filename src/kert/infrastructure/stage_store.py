"""P12/P13/P14 三阶段持久化（L4-2 / Owner 裁定）。

依据建议书 §3.3 三阶段定义与 §11.5 执行控制：

    P12 缺口确认     → TaskContext、GapChecklist、目标及适用范围版本
    P13 证据装配     → EvidenceBundle、ContextPackage、内容摘要值
    P14 预览确认     → 与证据包绑定的 PrevisitPackage、确认记录

**关键不变量（§3.3 明文）**
    「P13 调整证据后，旧报告与新证据之间的确认关系失效；
      系统生成新版本，由 P14 对新版本确认。」

本模块据此实现：**P13 的证据变更使既有 P14 确认失效**，
并记录"是哪次变更是哪次确认失效"，使链路可追溯。

**与 RuntimeStore 的关系**
    复用既有 SQLite 运行时存储（同库不同表），
    不新建第二套持久化设施，避免两套事实并存。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS stage_sessions (
    session_id       TEXT PRIMARY KEY,
    task_id          TEXT NOT NULL,
    customer_id      TEXT NOT NULL,
    purpose          TEXT,
    as_of            TEXT,
    current_stage    TEXT NOT NULL,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_states (
    session_id       TEXT NOT NULL,
    stage            TEXT NOT NULL,
    payload          TEXT NOT NULL,
    payload_digest   TEXT NOT NULL,
    actor            TEXT,
    created_at       REAL NOT NULL,
    PRIMARY KEY (session_id, stage, payload_digest)
);

CREATE TABLE IF NOT EXISTS stage_transitions (
    transition_id    TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    from_stage       TEXT,
    to_stage         TEXT NOT NULL,
    reason           TEXT,
    actor            TEXT,
    created_at       REAL NOT NULL
);

-- P14 确认记录：绑定 evidence bundle 摘要值
CREATE TABLE IF NOT EXISTS stage_confirmations (
    confirmation_id  TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    package_digest   TEXT NOT NULL,
    bundle_digest    TEXT NOT NULL,
    confirmed_by     TEXT NOT NULL,
    remaining_gaps   TEXT,
    created_at       REAL NOT NULL,
    -- 关键：证据变更后置为 0，表示该确认对新版本失效
    is_current       INTEGER NOT NULL DEFAULT 1,
    invalidated_at   REAL,
    invalidated_by   TEXT
);
"""


def _canonical_digest(payload: Any) -> str:
    import hashlib
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class StageTransitionError(RuntimeError):
    """非法阶段流转（fail-closed）。"""


@dataclass
class StageSession:
    session_id: str
    task_id: str
    customer_id: str
    purpose: str | None
    as_of: str | None
    current_stage: str
    created_at: float
    updated_at: float


@dataclass
class Confirmation:
    confirmation_id: str
    session_id: str
    package_digest: str
    bundle_digest: str
    confirmed_by: str
    remaining_gaps: list = field(default_factory=list)
    created_at: float = 0.0
    is_current: int = 1
    invalidated_at: float | None = None
    invalidated_by: str | None = None


# 允许的阶段流转（§3.3 三阶段必须按序）
ALLOWED_TRANSITIONS = {
    None: {"P12"},
    "P12": {"P13"},
    "P13": {"P14", "P13"},   # 允许在 P13 内反复调整证据
    "P14": {"P13"},          # 证据变更则回到 P13，并使确认失效
}


class StageStore:
    """P12/P13/P14 阶段持久化。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ---------------- 基础设施 ----------------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(DDL)

    def schema_version(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='stage_sessions'").fetchone()
            return SCHEMA_VERSION if row else 0

    # ---------------- 会话 ----------------
    def open_session(self, task_id: str, customer_id: str, *,
                     purpose: str | None = None,
                     as_of: str | None = None) -> StageSession:
        sid = f"STG-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO stage_sessions (session_id, task_id, customer_id,"
                " purpose, as_of, current_stage, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (sid, task_id, customer_id, purpose, as_of, "P12", now, now))
        return StageSession(sid, task_id, customer_id, purpose, as_of,
                            "P12", now, now)

    def get_session(self, session_id: str) -> StageSession | None:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM stage_sessions WHERE session_id=?",
                             (session_id,)).fetchone()
        if not r:
            return None
        return StageSession(r["session_id"], r["task_id"], r["customer_id"],
                            r["purpose"], r["as_of"], r["current_stage"],
                            r["created_at"], r["updated_at"])

    # ---------------- 阶段流转 ----------------
    def advance(self, session_id: str, to_stage: str, *,
                reason: str | None = None, actor: str | None = None) -> None:
        """推进阶段；非法流转 fail-closed。"""
        sess = self.get_session(session_id)
        if sess is None:
            raise StageTransitionError(f"会话不存在: {session_id}")
        allowed = ALLOWED_TRANSITIONS.get(sess.current_stage, set())
        if to_stage not in allowed:
            raise StageTransitionError(
                f"非法阶段流转 {sess.current_stage} → {to_stage}；"
                f"允许: {sorted(allowed)}")
        tid = f"TRN-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO stage_transitions (transition_id, session_id,"
                " from_stage, to_stage, reason, actor, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (tid, session_id, sess.current_stage, to_stage, reason,
                 actor, now))
            conn.execute(
                "UPDATE stage_sessions SET current_stage=?, updated_at=?"
                " WHERE session_id=?", (to_stage, now, session_id))

    # ---------------- 阶段状态 ----------------
    def record_state(self, session_id: str, stage: str, payload: dict, *,
                     actor: str | None = None) -> str:
        digest = _canonical_digest(payload)
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stage_states (session_id, stage,"
                " payload, payload_digest, actor, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (session_id, stage, json.dumps(payload, ensure_ascii=False),
                 digest, actor, time.time()))
        return digest

    def latest_state(self, session_id: str, stage: str) -> dict | None:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT payload FROM stage_states WHERE session_id=? AND stage=?"
                " ORDER BY created_at DESC LIMIT 1",
                (session_id, stage)).fetchone()
        return json.loads(r["payload"]) if r else None

    # ---------------- P13 证据变更 → 使 P14 确认失效 ----------------
    def record_evidence_change(self, session_id: str, bundle_digest: str, *,
                               actor: str | None = None) -> list[str]:
        """记录 P13 证据变更，并**使既有 P14 确认失效**（§3.3）。

        返回被失效的 confirmation_id 列表。
        """
        now = time.time()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT confirmation_id FROM stage_confirmations"
                " WHERE session_id=? AND is_current=1", (session_id,)).fetchall()
            ids = [r["confirmation_id"] for r in rows]
            if ids:
                conn.execute(
                    "UPDATE stage_confirmations SET is_current=0,"
                    " invalidated_at=?, invalidated_by=?"
                    " WHERE session_id=? AND is_current=1",
                    (now, f"EVIDENCE_CHANGED:{bundle_digest}", session_id))
            conn.execute(
                "INSERT INTO stage_transitions (transition_id, session_id,"
                " from_stage, to_stage, reason, actor, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"TRN-{uuid.uuid4().hex[:12]}", session_id, "P14", "P13",
                 f"证据变更使 {len(ids)} 条确认失效", actor, now))
            conn.execute(
                "UPDATE stage_sessions SET current_stage='P13', updated_at=?"
                " WHERE session_id=?", (now, session_id))
        return ids

    # ---------------- P14 确认 ----------------
    def confirm_package(self, session_id: str, *, package_digest: str,
                        bundle_digest: str, confirmed_by: str,
                        remaining_gaps: list | None = None) -> Confirmation:
        """记录 P14 确认；**要求绑定证据包摘要值**。"""
        if not bundle_digest:
            raise StageTransitionError(
                "P14 确认必须绑定证据包摘要值（bundle_digest 不得为空）")
        cid = f"CNF-{uuid.uuid4().hex[:12]}"
        now = time.time()
        gaps = remaining_gaps or []
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO stage_confirmations (confirmation_id, session_id,"
                " package_digest, bundle_digest, confirmed_by, remaining_gaps,"
                " created_at, is_current) VALUES (?,?,?,?,?,?,?,1)",
                (cid, session_id, package_digest, bundle_digest, confirmed_by,
                 json.dumps(gaps, ensure_ascii=False), now))
        return Confirmation(cid, session_id, package_digest, bundle_digest,
                            confirmed_by, gaps, now, 1)

    def confirmations(self, session_id: str, *,
                      current_only: bool = True) -> list[Confirmation]:
        sql = ("SELECT * FROM stage_confirmations WHERE session_id=?"
               + (" AND is_current=1" if current_only else "")
               + " ORDER BY created_at DESC")
        with self.connect() as conn:
            rows = conn.execute(sql, (session_id,)).fetchall()
        return [Confirmation(
            r["confirmation_id"], r["session_id"], r["package_digest"],
            r["bundle_digest"], r["confirmed_by"],
            json.loads(r["remaining_gaps"] or "[]"), r["created_at"],
            r["is_current"], r["invalidated_at"], r["invalidated_by"],
        ) for r in rows]

    def is_confirmation_valid(self, confirmation_id: str,
                              current_bundle_digest: str) -> tuple[bool, str]:
        """校验某确认是否仍对**当前**证据包有效。

        返回 (是否有效, 原因)。P13 已变更证据而确认未更新 → 无效。
        """
        with self.connect() as conn:
            r = conn.execute(
                "SELECT * FROM stage_confirmations WHERE confirmation_id=?",
                (confirmation_id,)).fetchone()
        if not r:
            return False, "确认不存在"
        if not r["is_current"]:
            return False, (f"已被证据变更失效（{r['invalidated_by']}）")
        if r["bundle_digest"] != current_bundle_digest:
            return False, ("确认绑定的证据包摘要值与当前不一致："
                           f"{r['bundle_digest'][:12]}… != "
                           f"{current_bundle_digest[:12]}…")
        return True, "有效"

    # ---------------- 追溯 ----------------
    def transitions(self, session_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM stage_transitions WHERE session_id=?"
                " ORDER BY created_at", (session_id,)).fetchall()
        return [dict(r) for r in rows]
