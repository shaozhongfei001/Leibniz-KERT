"""SQLite Runtime Store（M2.3，ADR-012/ADR-015）。

职责：持久化**可变运行态**，使幂等、Job 状态、Evidence/Gate 审计在进程重启后可恢复。

严格边界（ADR-012）：
- 知识权威源仍是 ``03_core`` 文件资产；本 Store 不保存知识内容本体。
- 数据库文件默认落在 ``90_control/runtime/``，禁止落入
  ``01_raw`` / ``02_work`` / ``03_core`` / ``04_serve``。
- 仅单机单实例使用；不引入 PostgreSQL / Redis / 外部 MQ。

工程要点：
- 启用 WAL 与 ``synchronous=NORMAL``，配合 ``busy_timeout`` 降低写竞争。
- 显式 ``schema_version`` 表 + 顺序 migration 列表，支持幂等升级。
- 每次操作使用独立连接（``check_same_thread=False`` 并加进程内写锁），
  避免跨线程复用连接。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import ConflictError, IdempotencyConflictError

#: 当前 schema 版本（等于 MIGRATIONS 长度）
SCHEMA_VERSION = 1

#: 禁止承载 Runtime Store 的知识数据目录（ADR-012 边界）
FORBIDDEN_PARENTS = ("01_raw", "02_work", "03_core", "04_serve")

_MIGRATION_001 = (
    """
    CREATE TABLE IF NOT EXISTS idempotency_records (
        scope         TEXT NOT NULL,
        idem_key      TEXT NOT NULL,
        request_hash  TEXT NOT NULL,
        response_json TEXT,
        status        TEXT NOT NULL DEFAULT 'COMPLETED',
        created_at    REAL NOT NULL,
        expires_at    REAL,
        PRIMARY KEY (scope, idem_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id        TEXT PRIMARY KEY,
        job_type      TEXT NOT NULL,
        status        TEXT NOT NULL,
        payload_json  TEXT,
        result_json   TEXT,
        error_message TEXT,
        attempts      INTEGER NOT NULL DEFAULT 0,
        created_at    REAL NOT NULL,
        updated_at    REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, updated_at)",
    """
    CREATE TABLE IF NOT EXISTS evidence_audit (
        audit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        object_id   TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        source_ref  TEXT,
        detail_json TEXT,
        recorded_at REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_evidence_object ON evidence_audit(object_id)",
    """
    CREATE TABLE IF NOT EXISTS gate_audit (
        audit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id TEXT NOT NULL,
        gate        TEXT NOT NULL,
        decision    TEXT NOT NULL,
        decided_by  TEXT NOT NULL,
        reason      TEXT,
        recorded_at REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_gate_customer ON gate_audit(customer_id, gate)",
)

#: 顺序 migration；索引 i 对应 schema_version i+1，只能追加不可修改
MIGRATIONS: tuple[tuple[str, ...], ...] = (_MIGRATION_001,)


@dataclass(frozen=True)
class IdempotencyHit:
    """幂等命中记录。"""

    scope: str
    idem_key: str
    request_hash: str
    status: str
    response: dict | None
    created_at: float


@dataclass(frozen=True)
class JobRecord:
    """Job 运行态记录。"""

    job_id: str
    job_type: str
    status: str
    payload: dict
    result: dict | None
    error_message: str | None
    attempts: int
    created_at: float
    updated_at: float


def _ensure_allowed_path(path: Path) -> None:
    """校验数据库路径未落入知识数据目录。

    Raises:
        ConflictError: 路径任一段命中 :data:`FORBIDDEN_PARENTS`。
    """
    parts = set(Path(path).parts)
    hit = parts.intersection(FORBIDDEN_PARENTS)
    if hit:
        raise ConflictError(
            f"Runtime Store 不得落在知识数据目录 {sorted(hit)} 内（ADR-012 边界）")


class RuntimeStore:
    """SQLite 运行态仓储。

    Args:
        db_path: 数据库文件路径。
        wal: 是否启用 WAL 日志模式。
        busy_timeout_ms: SQLite 忙等超时（毫秒）。
        idempotency_ttl_seconds: 幂等记录默认存活时长（秒）。

    Raises:
        ConflictError: 路径违反 ADR-012 目录边界。
    """

    def __init__(self, db_path: Path, *, wal: bool = True, busy_timeout_ms: int = 5000,
                 idempotency_ttl_seconds: int = 600):
        """初始化连接参数、创建目录并执行 migration。"""
        _ensure_allowed_path(db_path)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._wal = wal
        self._busy_timeout_ms = busy_timeout_ms
        self._ttl = idempotency_ttl_seconds
        self._write_lock = threading.RLock()
        self.migrate()

    # ---------------------------------------------------------------- 连接与迁移

    def connect(self) -> sqlite3.Connection:
        """打开一个已应用 PRAGMA 的连接（调用方负责关闭）。"""
        conn = sqlite3.connect(self.db_path, timeout=self._busy_timeout_ms / 1000.0,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout_ms)}")
        conn.execute("PRAGMA foreign_keys = ON")
        if self._wal:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def journal_mode(self) -> str:
        """返回当前日志模式（用于验证 WAL 已生效）。"""
        conn = self.connect()
        try:
            return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        finally:
            conn.close()

    def schema_version(self) -> int:
        """返回已应用的 schema 版本；未初始化时为 0。"""
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            if row is None:
                return 0
            cur = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            return int(cur["v"] or 0)
        finally:
            conn.close()

    def migrate(self) -> int:
        """幂等执行未应用的 migration，返回最终 schema 版本。"""
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version    INTEGER PRIMARY KEY,
                        applied_at REAL NOT NULL
                    )
                    """
                )
                conn.commit()
                current = int(
                    conn.execute("SELECT MAX(version) AS v FROM schema_version")
                    .fetchone()["v"] or 0)
                for idx in range(current, len(MIGRATIONS)):
                    for stmt in MIGRATIONS[idx]:
                        conn.execute(stmt)
                    conn.execute("INSERT INTO schema_version (version, applied_at) "
                                 "VALUES (?, ?)", (idx + 1, time.time()))
                    conn.commit()
                return len(MIGRATIONS)
            finally:
                conn.close()

    # ---------------------------------------------------------------- 幂等记录

    def remember(self, scope: str, idem_key: str, request_hash: str,
                 response: dict | None = None, *, status: str = "COMPLETED",
                 ttl_seconds: int | None = None) -> IdempotencyHit:
        """写入或复用幂等记录。

        Args:
            scope: 幂等作用域（如 ``skill_execute``）。
            idem_key: 幂等键。
            request_hash: 请求内容摘要，用于检测同键不同内容。
            response: 需要复放的响应体。
            status: 记录状态。
            ttl_seconds: 覆盖默认存活时长；``0`` 表示永不过期，
                负值表示写入即过期（便于测试与强制失效）。

        Returns:
            已存在则返回原记录（供复放），否则返回新写入记录。

        Raises:
            IdempotencyConflictError: 同键但 ``request_hash`` 不同。
        """
        now = time.time()
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        with self._write_lock:
            conn = self.connect()
            try:
                self._purge_expired(conn, now)
                row = conn.execute(
                    "SELECT * FROM idempotency_records WHERE scope=? AND idem_key=?",
                    (scope, idem_key)).fetchone()
                if row is not None:
                    if row["request_hash"] != request_hash:
                        raise IdempotencyConflictError(
                            f"幂等键 {idem_key!r} 已用于不同请求内容",
                            details={"scope": scope})
                    return self._to_hit(row)
                conn.execute(
                    "INSERT INTO idempotency_records (scope, idem_key, request_hash, "
                    "response_json, status, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (scope, idem_key, request_hash,
                     json.dumps(response, ensure_ascii=False) if response is not None else None,
                     status, now, None if ttl == 0 else now + ttl))
                conn.commit()
                return IdempotencyHit(scope=scope, idem_key=idem_key,
                                      request_hash=request_hash, status=status,
                                      response=response, created_at=now)
            finally:
                conn.close()

    def lookup(self, scope: str, idem_key: str) -> IdempotencyHit | None:
        """查询未过期的幂等记录。"""
        now = time.time()
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT * FROM idempotency_records WHERE scope=? AND idem_key=? "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (scope, idem_key, now)).fetchone()
            return self._to_hit(row) if row is not None else None
        finally:
            conn.close()

    def complete(self, scope: str, idem_key: str, response: dict,
                 *, status: str = "COMPLETED") -> None:
        """更新幂等记录的响应与状态。"""
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute(
                    "UPDATE idempotency_records SET response_json=?, status=? "
                    "WHERE scope=? AND idem_key=?",
                    (json.dumps(response, ensure_ascii=False), status, scope, idem_key))
                conn.commit()
            finally:
                conn.close()

    def purge_expired(self) -> int:
        """清理过期幂等记录，返回删除条数。"""
        with self._write_lock:
            conn = self.connect()
            try:
                deleted = self._purge_expired(conn, time.time())
                conn.commit()
                return deleted
            finally:
                conn.close()

    @staticmethod
    def _purge_expired(conn: sqlite3.Connection, now: float) -> int:
        """在给定连接上删除过期记录。"""
        cur = conn.execute(
            "DELETE FROM idempotency_records WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,))
        return cur.rowcount or 0

    @staticmethod
    def _to_hit(row: sqlite3.Row) -> IdempotencyHit:
        """将数据行转为 :class:`IdempotencyHit`。"""
        payload = row["response_json"]
        return IdempotencyHit(
            scope=row["scope"], idem_key=row["idem_key"],
            request_hash=row["request_hash"], status=row["status"],
            response=json.loads(payload) if payload else None,
            created_at=float(row["created_at"]))

    # ---------------------------------------------------------------- Job 状态

    def create_job(self, job_id: str, job_type: str, payload: dict | None = None,
                   *, status: str = "PENDING") -> JobRecord:
        """登记一个 Job；同 ``job_id`` 重复登记返回既有记录。"""
        now = time.time()
        with self._write_lock:
            conn = self.connect()
            try:
                existing = conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                        (job_id,)).fetchone()
                if existing is not None:
                    return self._to_job(existing)
                conn.execute(
                    "INSERT INTO jobs (job_id, job_type, status, payload_json, attempts, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                    (job_id, job_type, status,
                     json.dumps(payload or {}, ensure_ascii=False), now, now))
                conn.commit()
                return JobRecord(job_id=job_id, job_type=job_type, status=status,
                                 payload=payload or {}, result=None, error_message=None,
                                 attempts=0, created_at=now, updated_at=now)
            finally:
                conn.close()

    def update_job(self, job_id: str, *, status: str | None = None,
                   result: dict | None = None, error_message: str | None = None,
                   increment_attempts: bool = False) -> JobRecord | None:
        """更新 Job 状态/结果，返回更新后的记录。"""
        now = time.time()
        with self._write_lock:
            conn = self.connect()
            try:
                row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                if row is None:
                    return None
                new_status = status or row["status"]
                new_result = (json.dumps(result, ensure_ascii=False)
                              if result is not None else row["result_json"])
                new_error = error_message if error_message is not None else row["error_message"]
                attempts = int(row["attempts"]) + (1 if increment_attempts else 0)
                conn.execute(
                    "UPDATE jobs SET status=?, result_json=?, error_message=?, attempts=?, "
                    "updated_at=? WHERE job_id=?",
                    (new_status, new_result, new_error, attempts, now, job_id))
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            finally:
                conn.close()

    def get_job(self, job_id: str) -> JobRecord | None:
        """按 ID 读取 Job 记录。"""
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return self._to_job(row) if row is not None else None
        finally:
            conn.close()

    def list_jobs(self, *, statuses: Iterable[str] | None = None,
                  limit: int = 100) -> list[JobRecord]:
        """列出 Job；可按状态过滤，按更新时间倒序。"""
        conn = self.connect()
        try:
            if statuses:
                status_list = list(statuses)
                marks = ",".join("?" for _ in status_list)
                rows = conn.execute(
                    f"SELECT * FROM jobs WHERE status IN ({marks}) "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (*status_list, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._to_job(r) for r in rows]
        finally:
            conn.close()

    def recover_stale_jobs(self, *, running_status: str = "RUNNING",
                           target_status: str = "PENDING") -> list[str]:
        """进程重启后把残留的运行中 Job 复位为待处理，返回受影响 ID。

        M2.3 仅提供状态复位；原子领取/lease/dead-letter 属 M2.4 范围。
        """
        now = time.time()
        with self._write_lock:
            conn = self.connect()
            try:
                rows = conn.execute("SELECT job_id FROM jobs WHERE status=?",
                                    (running_status,)).fetchall()
                ids = [str(r["job_id"]) for r in rows]
                if ids:
                    conn.execute(
                        "UPDATE jobs SET status=?, updated_at=? WHERE status=?",
                        (target_status, now, running_status))
                    conn.commit()
                return ids
            finally:
                conn.close()

    @staticmethod
    def _to_job(row: sqlite3.Row) -> JobRecord:
        """将数据行转为 :class:`JobRecord`。"""
        return JobRecord(
            job_id=row["job_id"], job_type=row["job_type"], status=row["status"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_message=row["error_message"], attempts=int(row["attempts"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]))

    # ---------------------------------------------------------------- 审计

    def record_evidence(self, object_id: str, evidence_id: str,
                        source_ref: str | None = None,
                        detail: dict | None = None) -> int:
        """追加一条 Evidence 审计记录，返回审计 ID。"""
        with self._write_lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "INSERT INTO evidence_audit (object_id, evidence_id, source_ref, "
                    "detail_json, recorded_at) VALUES (?, ?, ?, ?, ?)",
                    (object_id, evidence_id, source_ref,
                     json.dumps(detail or {}, ensure_ascii=False), time.time()))
                conn.commit()
                return int(cur.lastrowid or 0)
            finally:
                conn.close()

    def list_evidence(self, object_id: str, limit: int = 100) -> list[dict]:
        """按对象 ID 列出 Evidence 审计记录。"""
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM evidence_audit WHERE object_id=? "
                "ORDER BY audit_id DESC LIMIT ?", (object_id, limit)).fetchall()
            return [{"audit_id": int(r["audit_id"]), "object_id": r["object_id"],
                     "evidence_id": r["evidence_id"], "source_ref": r["source_ref"],
                     "detail": json.loads(r["detail_json"]) if r["detail_json"] else {},
                     "recorded_at": float(r["recorded_at"])} for r in rows]
        finally:
            conn.close()

    def record_gate(self, customer_id: str, gate: str, decision: str,
                    decided_by: str, reason: str = "") -> int:
        """追加一条 Gate 决策审计记录（非权威镜像），返回审计 ID。"""
        with self._write_lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "INSERT INTO gate_audit (customer_id, gate, decision, decided_by, "
                    "reason, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (customer_id, gate, decision, decided_by, reason, time.time()))
                conn.commit()
                return int(cur.lastrowid or 0)
            finally:
                conn.close()

    def list_gates(self, customer_id: str, limit: int = 100) -> list[dict]:
        """按客户 ID 列出 Gate 审计记录。"""
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM gate_audit WHERE customer_id=? "
                "ORDER BY audit_id DESC LIMIT ?", (customer_id, limit)).fetchall()
            return [{"audit_id": int(r["audit_id"]), "customer_id": r["customer_id"],
                     "gate": r["gate"], "decision": r["decision"],
                     "decided_by": r["decided_by"], "reason": r["reason"],
                     "recorded_at": float(r["recorded_at"])} for r in rows]
        finally:
            conn.close()

    # ---------------------------------------------------------------- 运维

    def backup_to(self, target: Path) -> Path:
        """使用 SQLite 在线备份 API 生成一致性快照。"""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        src = self.connect()
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target

    def stats(self) -> dict:
        """返回各表行数与 schema 版本，用于健康检查与证据留存。"""
        conn = self.connect()
        try:
            def count(table: str) -> int:
                """统计单表行数。"""
                return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])

            return {
                "schema_version": self.schema_version(),
                "journal_mode": str(
                    conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
                "idempotency_records": count("idempotency_records"),
                "jobs": count("jobs"),
                "evidence_audit": count("evidence_audit"),
                "gate_audit": count("gate_audit"),
            }
        finally:
            conn.close()
