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
SCHEMA_VERSION = 2

#: 禁止承载 Runtime Store 的知识数据目录（ADR-012 边界）
FORBIDDEN_PARENTS = ("01_raw", "02_work", "03_core", "04_serve")

#: 可被 Worker 领取的状态（§11.1：PENDING/RETRYING → RUNNING 均为合法转换）
CLAIMABLE_STATES = ("PENDING", "RETRYING")

#: 默认最大尝试次数（含首次）
DEFAULT_MAX_ATTEMPTS = 3

#: 默认 lease 租约时长（秒）
DEFAULT_LEASE_SECONDS = 30.0

#: 指数退避默认参数
DEFAULT_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_BACKOFF_MAX_SECONDS = 300.0

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

#: migration 002（M2.4）：为 jobs 表补齐 lease/重试/dead-letter 列与调度索引。
#:
#: 设计约束：
#: - 只追加、不修改 001；使用 ``ALTER TABLE ADD COLUMN`` 保证既有数据平滑升级。
#: - 终态命名统一为 ``COMPLETED``（对齐 ``domain/states.py`` §11.1），
#:   同时把 001 时期可能写入的 ``SUCCEEDED`` 数据一次性归一。
#: - dead-letter 用 ``FAILED`` + ``dead_letter=1`` 表达，**不使用 BLOCKED**：
#:   §11.1 的 ``FAILED`` 只允许转向 ``RETRYING``，若改用 BLOCKED 会违反状态机。
_MIGRATION_002 = (
    # lease 租约：持有者、到期时间、心跳时间
    "ALTER TABLE jobs ADD COLUMN lease_owner TEXT",
    "ALTER TABLE jobs ADD COLUMN lease_expires_at REAL",
    "ALTER TABLE jobs ADD COLUMN heartbeat_at REAL",
    # 重试：上限、下一次可领取时间（退避）、失败原因分类
    (f"ALTER TABLE jobs ADD COLUMN max_attempts INTEGER NOT NULL "
     f"DEFAULT {DEFAULT_MAX_ATTEMPTS}"),
    "ALTER TABLE jobs ADD COLUMN next_attempt_at REAL",
    "ALTER TABLE jobs ADD COLUMN error_code TEXT",
    # dead-letter：标记位 + 进入时间 + 原因
    "ALTER TABLE jobs ADD COLUMN dead_letter INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN dead_lettered_at REAL",
    "ALTER TABLE jobs ADD COLUMN dead_letter_reason TEXT",
    # 幂等键：同 job_type + idem_key 只允许一个活跃 Job
    "ALTER TABLE jobs ADD COLUMN idem_key TEXT",
    # 终态命名归一：SUCCEEDED → COMPLETED（对齐 §11.1）
    "UPDATE jobs SET status='COMPLETED' WHERE status='SUCCEEDED'",
    # 调度索引：领取时按 (status, next_attempt_at) 扫描
    ("CREATE INDEX IF NOT EXISTS idx_jobs_claim "
     "ON jobs(status, next_attempt_at, created_at)"),
    # lease 回收索引
    "CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(lease_expires_at)",
    # dead-letter 查询索引
    ("CREATE INDEX IF NOT EXISTS idx_jobs_dead_letter "
     "ON jobs(dead_letter, dead_lettered_at)"),
    # 幂等查询索引
    "CREATE INDEX IF NOT EXISTS idx_jobs_idem ON jobs(job_type, idem_key)",
)

#: 顺序 migration；索引 i 对应 schema_version i+1，只能追加不可修改
MIGRATIONS: tuple[tuple[str, ...], ...] = (_MIGRATION_001, _MIGRATION_002)


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
    """Job 运行态记录（M2.4 起为 Job 状态的唯一权威表示）。

    字段分三组：
    - 基础：``job_id`` / ``job_type`` / ``status`` / ``payload`` / ``result``
    - lease：``lease_owner`` / ``lease_expires_at`` / ``heartbeat_at``
    - 重试与 dead-letter：``attempts`` / ``max_attempts`` / ``next_attempt_at``
      / ``dead_letter`` / ``dead_letter_reason``
    """

    job_id: str
    job_type: str
    status: str
    payload: dict
    result: dict | None
    error_message: str | None
    attempts: int
    created_at: float
    updated_at: float
    #: 以下为 M2.4（schema v2）新增，读取旧库时取默认值
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    heartbeat_at: float | None = None
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    next_attempt_at: float | None = None
    error_code: str | None = None
    dead_letter: bool = False
    dead_lettered_at: float | None = None
    dead_letter_reason: str | None = None
    idem_key: str | None = None

    @property
    def attempts_remaining(self) -> int:
        """剩余可尝试次数（不小于 0）。"""
        return max(0, self.max_attempts - self.attempts)

    def lease_expired(self, now: float | None = None) -> bool:
        """判断 lease 是否已过期（未持有 lease 视为未过期）。"""
        if self.lease_expires_at is None:
            return False
        return self.lease_expires_at <= (time.time() if now is None else now)


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
                   *, status: str = "PENDING", max_attempts: int | None = None,
                   idem_key: str | None = None,
                   available_at: float | None = None) -> JobRecord:
        """登记一个 Job；同 ``job_id`` 重复登记返回既有记录（幂等）。

        Args:
            job_id: Job 唯一 ID。
            job_type: 业务类型，用于路由到 Handler。
            payload: 执行入参。
            status: 初始状态，默认 ``PENDING``。
            max_attempts: 最大尝试次数（含首次），默认 :data:`DEFAULT_MAX_ATTEMPTS`。
            idem_key: 业务幂等键；同 ``job_type`` + ``idem_key`` 若已有活跃 Job 则冲突。
            available_at: 最早可领取时间（用于延迟执行）；``None`` 表示立即可领。

        Returns:
            新建或既有的 Job 记录。

        Raises:
            ConflictError: 同 ``job_type`` + ``idem_key`` 已存在未进入终态的 Job。
        """
        now = time.time()
        attempts_cap = DEFAULT_MAX_ATTEMPTS if max_attempts is None else int(max_attempts)
        if attempts_cap < 1:
            raise ConflictError(f"max_attempts 必须 >= 1，收到 {attempts_cap}")
        with self._write_lock:
            conn = self.connect()
            try:
                existing = conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                        (job_id,)).fetchone()
                if existing is not None:
                    return self._to_job(existing)
                if idem_key:
                    dup = conn.execute(
                        "SELECT job_id, status FROM jobs WHERE job_type=? AND idem_key=? "
                        "AND status NOT IN ('COMPLETED', 'CANCELLED') AND dead_letter=0",
                        (job_type, idem_key)).fetchone()
                    if dup is not None:
                        raise ConflictError(
                            f"幂等键冲突：{job_type} 的 Job {dup['job_id']} "
                            f"仍处于 {dup['status']}",
                            details={"job_id": str(dup["job_id"]),
                                     "idem_key": idem_key})
                conn.execute(
                    "INSERT INTO jobs (job_id, job_type, status, payload_json, attempts, "
                    "max_attempts, next_attempt_at, idem_key, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
                    (job_id, job_type, status,
                     json.dumps(payload or {}, ensure_ascii=False),
                     attempts_cap, available_at, idem_key, now, now))
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
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

        M2.3 引入的粗粒度复位：**无条件**复位所有 ``RUNNING``，不看 lease。
        M2.4 起推荐使用 :meth:`reclaim_expired_leases`（仅回收 lease 已过期者），
        以便多 Worker 并存时不会误抢正在被其它 Worker 正常处理的 Job。

        本方法保留用于单 Worker 部署下的启动清理，行为与 M2.3 一致。
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
                        "UPDATE jobs SET status=?, lease_owner=NULL, "
                        "lease_expires_at=NULL, updated_at=? WHERE status=?",
                        (target_status, now, running_status))
                    conn.commit()
                return ids
            finally:
                conn.close()

    # ------------------------------------------------------ M2.4 原子领取与 lease

    def claim_job(self, worker_id: str, *, job_types: Iterable[str] | None = None,
                  lease_seconds: float = DEFAULT_LEASE_SECONDS,
                  now: float | None = None) -> JobRecord | None:
        """原子领取一个待执行 Job；无可领取时返回 ``None``。

        原子性保障：在 ``BEGIN IMMEDIATE`` 事务内「选中 + 占用」一次完成，
        并在 UPDATE 的 WHERE 中再次校验 ``status`` 与 ``job_id``（CAS 语义），
        因此多 Worker 并发调用时同一 Job 只会被一个 Worker 领取。

        领取条件（全部满足）：
        - ``status`` ∈ :data:`CLAIMABLE_STATES`（``PENDING`` / ``RETRYING``）
        - 未进入 dead-letter
        - ``next_attempt_at`` 为空或已到期（退避窗口已过）
        - ``attempts < max_attempts``（仍有尝试余额）

        Args:
            worker_id: 领取者标识，写入 ``lease_owner``。
            job_types: 限定可领取的业务类型；``None`` 表示不限。
            lease_seconds: 本次 lease 时长。
            now: 注入当前时间（便于测试）。

        Returns:
            已被本 Worker 占用并置为 ``RUNNING`` 的 Job；无可领取时 ``None``。
        """
        ts = time.time() if now is None else now
        if lease_seconds <= 0:
            raise ConflictError(f"lease_seconds 必须 > 0，收到 {lease_seconds}")
        marks = ",".join("?" for _ in CLAIMABLE_STATES)
        sql = (f"SELECT * FROM jobs WHERE status IN ({marks}) AND dead_letter=0 "
               "AND attempts < max_attempts "
               "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ")
        params: list = [*CLAIMABLE_STATES, ts]
        if job_types is not None:
            type_list = list(job_types)
            if not type_list:
                # 显式传入空集合表示「不接受任何类型」，直接返回而非降级为不限
                return None
            sql += f"AND job_type IN ({','.join('?' for _ in type_list)}) "
            params.extend(type_list)
        # 先到先得：按可领取时间、再按创建时间排序，避免饥饿
        sql += "ORDER BY COALESCE(next_attempt_at, created_at), created_at LIMIT 1"

        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(sql, params).fetchone()
                if row is None:
                    conn.rollback()
                    return None
                job_id = str(row["job_id"])
                # CAS：仅当状态仍未变化时才占用，杜绝竞态覆盖
                cur = conn.execute(
                    "UPDATE jobs SET status='RUNNING', attempts=attempts+1, "
                    "lease_owner=?, lease_expires_at=?, heartbeat_at=?, "
                    "next_attempt_at=NULL, updated_at=? "
                    "WHERE job_id=? AND status=?",
                    (worker_id, ts + lease_seconds, ts, ts, job_id, row["status"]))
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            except sqlite3.OperationalError:
                # 并发下拿不到写锁属正常竞争，交由调用方下一轮重试
                conn.rollback()
                return None
            finally:
                conn.close()

    def heartbeat_job(self, job_id: str, worker_id: str, *,
                      lease_seconds: float = DEFAULT_LEASE_SECONDS,
                      now: float | None = None) -> bool:
        """续约 lease 并刷新心跳；仅 lease 持有者可续约。

        Returns:
            ``True`` 表示续约成功；``False`` 表示 Job 不存在、已非 ``RUNNING``、
            或 lease 已被他人接管（此时调用方应停止处理，避免重复执行）。
        """
        ts = time.time() if now is None else now
        with self._write_lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "UPDATE jobs SET lease_expires_at=?, heartbeat_at=?, updated_at=? "
                    "WHERE job_id=? AND lease_owner=? AND status='RUNNING'",
                    (ts + lease_seconds, ts, ts, job_id, worker_id))
                conn.commit()
                return cur.rowcount == 1
            finally:
                conn.close()

    def complete_job(self, job_id: str, worker_id: str, result: dict | None = None,
                     *, now: float | None = None) -> JobRecord | None:
        """标记 Job 成功完成（终态 ``COMPLETED``），释放 lease。

        仅 lease 持有者可完成；lease 已被接管时返回 ``None``，
        调用方应放弃写回结果以避免与接管者冲突。
        """
        ts = time.time() if now is None else now
        with self._write_lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "UPDATE jobs SET status='COMPLETED', result_json=?, "
                    "lease_owner=NULL, lease_expires_at=NULL, next_attempt_at=NULL, "
                    "updated_at=? WHERE job_id=? AND lease_owner=? AND status='RUNNING'",
                    (json.dumps(result, ensure_ascii=False) if result is not None else None,
                     ts, job_id, worker_id))
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            finally:
                conn.close()

    def fail_job(self, job_id: str, worker_id: str, *, error_message: str,
                 error_code: str | None = None, retryable: bool = True,
                 backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
                 backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
                 backoff_max: float = DEFAULT_BACKOFF_MAX_SECONDS,
                 now: float | None = None) -> JobRecord | None:
        """标记本次尝试失败，按剩余额度决定重试或进入 dead-letter。

        判定顺序：
        1. ``retryable=False`` → 直接 dead-letter（不可重试错误无需消耗额度）
        2. ``attempts >= max_attempts`` → 额度耗尽，dead-letter
        3. 否则 → 置 ``RETRYING``，并按指数退避设置 ``next_attempt_at``

        退避公式：``min(backoff_base * backoff_factor ** (attempts-1), backoff_max)``

        dead-letter 表达为 ``status=FAILED`` + ``dead_letter=1``，
        而非 ``BLOCKED``：§11.1 规定 ``FAILED`` 仅可转向 ``RETRYING``，
        使用 BLOCKED 会破坏状态机合法性。

        Returns:
            更新后的 Job；lease 已被接管或 Job 不存在时返回 ``None``。
        """
        ts = time.time() if now is None else now
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM jobs WHERE job_id=? AND lease_owner=? AND status='RUNNING'",
                    (job_id, worker_id)).fetchone()
                if row is None:
                    conn.rollback()
                    return None
                attempts = int(row["attempts"])
                cap = int(row["max_attempts"])
                exhausted = attempts >= cap
                if not retryable or exhausted:
                    reason = ("不可重试错误" if not retryable
                              else f"重试次数耗尽（{attempts}/{cap}）")
                    conn.execute(
                        "UPDATE jobs SET status='FAILED', error_message=?, error_code=?, "
                        "dead_letter=1, dead_lettered_at=?, dead_letter_reason=?, "
                        "lease_owner=NULL, lease_expires_at=NULL, next_attempt_at=NULL, "
                        "updated_at=? WHERE job_id=?",
                        (error_message, error_code, ts, reason, ts, job_id))
                else:
                    delay = min(backoff_base * (backoff_factor ** max(0, attempts - 1)),
                                backoff_max)
                    conn.execute(
                        "UPDATE jobs SET status='RETRYING', error_message=?, error_code=?, "
                        "next_attempt_at=?, lease_owner=NULL, lease_expires_at=NULL, "
                        "updated_at=? WHERE job_id=?",
                        (error_message, error_code, ts + delay, ts, job_id))
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            finally:
                conn.close()

    def reclaim_expired_leases(self, *, now: float | None = None,
                               backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
                               backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
                               backoff_max: float = DEFAULT_BACKOFF_MAX_SECONDS
                               ) -> list[str]:
        """回收 lease 已过期的 ``RUNNING`` Job，返回受影响 ID。

        这是崩溃恢复的核心：Worker 进程被 ``kill -9`` 后无法释放 lease，
        lease 到期即视为该次尝试失败，由本方法转入 ``RETRYING``（仍有额度）
        或 dead-letter（额度耗尽）。

        与 :meth:`recover_stale_jobs` 的区别：本方法**只动 lease 已过期的**，
        因此可在多 Worker 并存、以及 Worker 运行期间周期性安全调用。
        """
        ts = time.time() if now is None else now
        reclaimed: list[str] = []
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status='RUNNING' "
                    "AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
                    (ts,)).fetchall()
                for row in rows:
                    job_id = str(row["job_id"])
                    attempts = int(row["attempts"])
                    cap = int(row["max_attempts"])
                    owner = row["lease_owner"]
                    message = (f"lease 超时未续约（owner={owner}），"
                               f"判定第 {attempts} 次尝试失败")
                    if attempts >= cap:
                        conn.execute(
                            "UPDATE jobs SET status='FAILED', error_message=?, "
                            "error_code='LEASE_EXPIRED', dead_letter=1, "
                            "dead_lettered_at=?, dead_letter_reason=?, lease_owner=NULL, "
                            "lease_expires_at=NULL, updated_at=? WHERE job_id=?",
                            (message, ts, f"lease 超时且重试次数耗尽（{attempts}/{cap}）",
                             ts, job_id))
                    else:
                        delay = min(backoff_base * (backoff_factor ** max(0, attempts - 1)),
                                    backoff_max)
                        conn.execute(
                            "UPDATE jobs SET status='RETRYING', error_message=?, "
                            "error_code='LEASE_EXPIRED', next_attempt_at=?, "
                            "lease_owner=NULL, lease_expires_at=NULL, updated_at=? "
                            "WHERE job_id=?",
                            (message, ts + delay, ts, job_id))
                    reclaimed.append(job_id)
                conn.commit()
                return reclaimed
            finally:
                conn.close()

    def find_job_by_idem(self, job_type: str, idem_key: str) -> JobRecord | None:
        """按 ``job_type`` + ``idem_key`` 查最近一个 Job（幂等判定用）。

        返回最新创建的一条：若存在活跃 Job 则调用方应判冲突；
        若为终态则调用方可判定 NO_OP。
        """
        if not idem_key:
            return None
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_type=? AND idem_key=? "
                "ORDER BY created_at DESC LIMIT 1", (job_type, idem_key)).fetchone()
            return self._to_job(row) if row is not None else None
        finally:
            conn.close()

    def max_job_seq(self, job_type: str) -> int:
        """返回该类型已用的最大序号（用于生成不撞号的新 Job ID）。

        Job ID 形如 ``JOB-<TYPE>-<YYYYMMDD>-<SEQ>``，此处提取末段 SEQ 的最大值。
        """
        conn = self.connect()
        try:
            rows = conn.execute("SELECT job_id FROM jobs WHERE job_type=?",
                                (job_type,)).fetchall()
        finally:
            conn.close()
        max_seq = 0
        for row in rows:
            tail = str(row["job_id"]).rsplit("-", 1)[-1]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
        return max_seq

    def sync_job_state(self, job_id: str, status: str, *,
                       progress: int | None = None,
                       error_code: str | None = None,
                       error_message: str | None = None,
                       result: dict | None = None,
                       now: float | None = None) -> JobRecord | None:
        """由 :class:`~dkws.application.jobs.JobController` 同步状态到权威表。

        与 :meth:`update_job` 的差别：本方法用于「控制器驱动」的状态推进
        （PENDING→RUNNING→VALIDATING→COMPLETED 等），不涉及 lease，
        并额外落 ``progress``/``error_code``；Worker 侧应使用
        :meth:`claim_job` / :meth:`complete_job` / :meth:`fail_job`。
        """
        ts = time.time() if now is None else now
        with self._write_lock:
            conn = self.connect()
            try:
                row = conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                   (job_id,)).fetchone()
                if row is None:
                    return None
                payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
                if progress is not None:
                    payload["progress"] = progress
                conn.execute(
                    "UPDATE jobs SET status=?, payload_json=?, error_code=?, "
                    "error_message=?, result_json=?, updated_at=? WHERE job_id=?",
                    (status, json.dumps(payload, ensure_ascii=False),
                     error_code if error_code is not None else row["error_code"],
                     error_message if error_message is not None else row["error_message"],
                     (json.dumps(result, ensure_ascii=False)
                      if result is not None else row["result_json"]),
                     ts, job_id))
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            finally:
                conn.close()

    def set_job_payload(self, job_id: str, payload: dict,
                        *, now: float | None = None) -> JobRecord | None:
        """覆盖 Job 的执行入参（入队时补齐 payload）。

        用于「先由控制器登记 Job、再写入执行参数」的两步入队流程；
        执行中（``RUNNING``）的 Job 不允许改入参，避免与正在执行者冲突。
        """
        ts = time.time() if now is None else now
        with self._write_lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "UPDATE jobs SET payload_json=?, updated_at=? "
                    "WHERE job_id=? AND status<>'RUNNING'",
                    (json.dumps(payload, ensure_ascii=False), ts, job_id))
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            finally:
                conn.close()

    def list_dead_letters(self, *, limit: int = 100) -> list[JobRecord]:
        """列出进入 dead-letter 的 Job，按进入时间倒序。"""
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE dead_letter=1 "
                "ORDER BY dead_lettered_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._to_job(r) for r in rows]
        finally:
            conn.close()

    def requeue_dead_letter(self, job_id: str, *, extra_attempts: int = 1,
                            now: float | None = None) -> JobRecord | None:
        """将 dead-letter Job 重新入队（人工干预后重放）。

        追加尝试额度并清除 dead-letter 标记，状态回到 ``RETRYING``
        （§11.1 允许 ``FAILED → RETRYING``）。

        Args:
            job_id: 目标 Job。
            extra_attempts: 追加的尝试额度，须 >= 1。
            now: 注入当前时间（便于测试）。

        Returns:
            更新后的 Job；不存在或不在 dead-letter 时返回 ``None``。
        """
        if extra_attempts < 1:
            raise ConflictError(f"extra_attempts 必须 >= 1，收到 {extra_attempts}")
        ts = time.time() if now is None else now
        with self._write_lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "UPDATE jobs SET status='RETRYING', dead_letter=0, "
                    "dead_lettered_at=NULL, dead_letter_reason=NULL, "
                    "max_attempts=max_attempts+?, next_attempt_at=NULL, "
                    "lease_owner=NULL, lease_expires_at=NULL, updated_at=? "
                    "WHERE job_id=? AND dead_letter=1",
                    (extra_attempts, ts, job_id))
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            finally:
                conn.close()

    def cancel_job(self, job_id: str, *, reason: str = "",
                   now: float | None = None) -> JobRecord | None:
        """取消尚未进入终态的 Job（§11.1 允许多数状态转 ``CANCELLED``）。"""
        ts = time.time() if now is None else now
        with self._write_lock:
            conn = self.connect()
            try:
                cur = conn.execute(
                    "UPDATE jobs SET status='CANCELLED', error_message=?, "
                    "lease_owner=NULL, lease_expires_at=NULL, next_attempt_at=NULL, "
                    "updated_at=? WHERE job_id=? "
                    "AND status NOT IN ('COMPLETED', 'CANCELLED')",
                    (reason or None, ts, job_id))
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
                return self._to_job(conn.execute("SELECT * FROM jobs WHERE job_id=?",
                                                 (job_id,)).fetchone())
            finally:
                conn.close()

    def queue_stats(self, *, now: float | None = None) -> dict:
        """队列概览：各状态计数、dead-letter 数、待领取数、过期 lease 数。"""
        ts = time.time() if now is None else now
        conn = self.connect()
        try:
            by_status = {str(r["status"]): int(r["c"]) for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").fetchall()}
            marks = ",".join("?" for _ in CLAIMABLE_STATES)
            claimable = int(conn.execute(
                f"SELECT COUNT(*) AS c FROM jobs WHERE status IN ({marks}) "
                "AND dead_letter=0 AND attempts < max_attempts "
                "AND (next_attempt_at IS NULL OR next_attempt_at <= ?)",
                (*CLAIMABLE_STATES, ts)).fetchone()["c"])
            return {
                "by_status": by_status,
                "claimable": claimable,
                "dead_letter": int(conn.execute(
                    "SELECT COUNT(*) AS c FROM jobs WHERE dead_letter=1").fetchone()["c"]),
                "expired_leases": int(conn.execute(
                    "SELECT COUNT(*) AS c FROM jobs WHERE status='RUNNING' "
                    "AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
                    (ts,)).fetchone()["c"]),
            }
        finally:
            conn.close()

    @staticmethod
    def _to_job(row: sqlite3.Row) -> JobRecord:
        """将数据行转为 :class:`JobRecord`。

        对 schema v2 新增列采用容错读取：若在旧库（v1）上执行，
        ``row.keys()`` 不含这些列，则回落到默认值。
        """
        keys = set(row.keys())

        def opt(name: str, default=None):
            """读取可选列，缺列或 NULL 时返回默认值。"""
            if name not in keys:
                return default
            value = row[name]
            return default if value is None else value

        return JobRecord(
            job_id=row["job_id"], job_type=row["job_type"], status=row["status"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_message=row["error_message"], attempts=int(row["attempts"]),
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
            lease_owner=opt("lease_owner"),
            lease_expires_at=(float(opt("lease_expires_at"))
                              if opt("lease_expires_at") is not None else None),
            heartbeat_at=(float(opt("heartbeat_at"))
                          if opt("heartbeat_at") is not None else None),
            max_attempts=int(opt("max_attempts", DEFAULT_MAX_ATTEMPTS)),
            next_attempt_at=(float(opt("next_attempt_at"))
                             if opt("next_attempt_at") is not None else None),
            error_code=opt("error_code"),
            dead_letter=bool(int(opt("dead_letter", 0))),
            dead_lettered_at=(float(opt("dead_lettered_at"))
                              if opt("dead_lettered_at") is not None else None),
            dead_letter_reason=opt("dead_letter_reason"),
            idem_key=opt("idem_key"),
        )

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
