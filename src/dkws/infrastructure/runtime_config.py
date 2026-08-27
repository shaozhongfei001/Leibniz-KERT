"""运行时配置（M2.1/M2.2，ADR-013/ADR-015）。

职责：集中承载 DKWS Python Core 的运行加固配置——profile、API Key 认证、
限流、请求/响应体大小上限、并发上限、SQLite Runtime Store 路径。

来源优先级（后者覆盖前者）：
1. 代码内默认值
2. 配置文件（JSON，路径由 ``DKWS_CONFIG_FILE`` 指定）
3. 环境变量（``DKWS_*``）
4. 构造参数（显式覆盖，供测试使用）

安全约束：
- 密钥只在内存中以 SHA-256 摘要形式保存，不落盘、不进日志。
- 生产 profile 未启用认证或未配置任何密钥时 fail-fast（``ConfigError``）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_DEV = "dev"
PROFILE_PROD = "prod"
VALID_PROFILES = (PROFILE_DEV, PROFILE_PROD)

# 匿名可访问的端点（存活探针）。其余端点在启用认证后一律需要密钥。
DEFAULT_PUBLIC_PATHS: tuple[str, ...] = ("/v1/health", "/api/skill/health")

# 管理/闸门类端点：即使密钥有效，也要求具备 admin 作用域（ADR-013）。
DEFAULT_ADMIN_PATH_PREFIXES: tuple[str, ...] = ("/api/skill/gates/audit",)

SCOPE_ADMIN = "admin"
SCOPE_READ = "read"
SCOPE_EXECUTE = "execute"


class ConfigError(Exception):
    """运行时配置非法（生产 profile fail-fast 时抛出）。"""


def _digest(secret: str) -> str:
    """返回密钥的 SHA-256 十六进制摘要（避免明文常驻内存）。"""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApiKeyRecord:
    """单个 API Key 的元数据（不含明文）。

    Attributes:
        key_id: 密钥标识，用于日志与限流分桶（非机密）。
        digest: 明文密钥的 SHA-256 摘要。
        scopes: 授予的作用域集合。
        active: 是否启用；轮换/吊销时置 False。
    """

    key_id: str
    digest: str
    scopes: frozenset[str]
    active: bool = True

    def has_scope(self, scope: str) -> bool:
        """判断是否具备指定作用域。"""
        return scope in self.scopes


@dataclass(frozen=True)
class AuthConfig:
    """API Key 认证配置。"""

    enabled: bool = False
    header_name: str = "X-API-Key"
    keys: tuple[ApiKeyRecord, ...] = ()
    public_paths: tuple[str, ...] = DEFAULT_PUBLIC_PATHS
    admin_path_prefixes: tuple[str, ...] = DEFAULT_ADMIN_PATH_PREFIXES

    def active_keys(self) -> tuple[ApiKeyRecord, ...]:
        """返回处于启用状态的密钥。"""
        return tuple(k for k in self.keys if k.active)

    def verify(self, presented: str) -> ApiKeyRecord | None:
        """按常量时间比较摘要，命中则返回密钥记录，否则返回 None。"""
        if not presented:
            return None
        want = _digest(presented)
        for record in self.active_keys():
            if hmac.compare_digest(record.digest, want):
                return record
        return None

    def is_public(self, path: str) -> bool:
        """路径是否属于匿名白名单。"""
        return path in self.public_paths

    def requires_admin(self, path: str) -> bool:
        """路径是否要求 admin 作用域。"""
        return any(path.startswith(p) for p in self.admin_path_prefixes)


@dataclass(frozen=True)
class RateLimitConfig:
    """限流配置（令牌桶，按 API Key 优先、否则按客户端 IP 分桶）。"""

    enabled: bool = False
    requests_per_minute: int = 600
    burst: int = 60

    def capacity(self) -> int:
        """令牌桶容量（突发额度，至少 1）。"""
        return max(1, self.burst)

    def refill_per_second(self) -> float:
        """每秒补充的令牌数。"""
        return max(0.0, self.requests_per_minute / 60.0)


@dataclass(frozen=True)
class SizeLimitConfig:
    """请求体/响应体大小上限配置（字节）。"""

    enabled: bool = True
    max_request_bytes: int = 1 * 1024 * 1024
    max_response_bytes: int = 8 * 1024 * 1024


@dataclass(frozen=True)
class ConcurrencyConfig:
    """并发上限配置（进程内在途请求数）。"""

    enabled: bool = False
    max_in_flight: int = 32
    acquire_timeout_seconds: float = 0.0


@dataclass(frozen=True)
class RuntimeStoreConfig:
    """SQLite Runtime Store 配置（ADR-012）。

    Attributes:
        enabled: 是否启用运行态持久化。
        path: 数据库文件路径；``None`` 时由工作区推导为 ``90_control/runtime/runtime.db``。
        wal: 是否启用 WAL 日志模式。
        busy_timeout_ms: SQLite 忙等超时。
        idempotency_ttl_seconds: 幂等记录保留时长。
    """

    enabled: bool = False
    path: Path | None = None
    wal: bool = True
    busy_timeout_ms: int = 5000
    idempotency_ttl_seconds: int = 600

    def resolve_path(self, workspace: Path) -> Path:
        """返回实际数据库路径；不落在 01_raw/02_work/03_core/04_serve 之下。"""
        if self.path is not None:
            return Path(self.path)
        return Path(workspace) / "90_control" / "runtime" / "runtime.db"


@dataclass(frozen=True)
class RuntimeConfig:
    """DKWS 运行时总配置。"""

    profile: str = PROFILE_DEV
    bind_host: str = "127.0.0.1"
    auth: AuthConfig = field(default_factory=AuthConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    size_limit: SizeLimitConfig = field(default_factory=SizeLimitConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    runtime_store: RuntimeStoreConfig = field(default_factory=RuntimeStoreConfig)
    warnings: tuple[str, ...] = ()

    @property
    def is_production(self) -> bool:
        """当前是否生产 profile。"""
        return self.profile == PROFILE_PROD

    def listens_publicly(self) -> bool:
        """是否对外监听（非仅回环地址）。"""
        return self.bind_host not in ("127.0.0.1", "localhost", "::1")


def _env_bool(env: dict[str, str], name: str, default: bool | None) -> bool | None:
    """解析布尔环境变量；未设置返回 default。"""
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(env: dict[str, str], name: str, default: int) -> int:
    """解析整型环境变量；非法值抛 ConfigError。"""
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 需为整数，实际为 {raw!r}") from exc


def _parse_key_spec(spec: str, index: int) -> ApiKeyRecord | None:
    """解析单条密钥声明。

    支持格式：
    - ``secret``
    - ``key_id:secret``
    - ``key_id:secret:scope1|scope2``
    """
    spec = spec.strip()
    if not spec:
        return None
    parts = spec.split(":")
    if len(parts) == 1:
        key_id, secret, scopes = f"key-{index + 1}", parts[0], (SCOPE_READ, SCOPE_EXECUTE)
    elif len(parts) == 2:
        key_id, secret, scopes = parts[0], parts[1], (SCOPE_READ, SCOPE_EXECUTE)
    else:
        key_id, secret = parts[0], parts[1]
        scopes = tuple(s for s in parts[2].replace(",", "|").split("|") if s)
    if not secret:
        raise ConfigError(f"API Key 声明缺少密钥内容：位置 {index + 1}")
    if len(secret) < 16:
        raise ConfigError(f"API Key {key_id!r} 长度不足 16 字符，拒绝使用弱密钥")
    return ApiKeyRecord(key_id=key_id or f"key-{index + 1}", digest=_digest(secret),
                        scopes=frozenset(scopes or (SCOPE_READ,)))


def _keys_from_env(env: dict[str, str]) -> tuple[ApiKeyRecord, ...]:
    """从 ``DKWS_API_KEYS``/``DKWS_API_KEY`` 读取密钥声明。"""
    raw = env.get("DKWS_API_KEYS") or env.get("DKWS_API_KEY") or ""
    records: list[ApiKeyRecord] = []
    for idx, spec in enumerate(raw.split(",")):
        rec = _parse_key_spec(spec, idx)
        if rec is not None:
            records.append(rec)
    return tuple(records)


def _keys_from_file(data: dict) -> tuple[ApiKeyRecord, ...]:
    """从配置文件的 ``auth.keys`` 读取密钥声明。

    条目形式：``{"key_id": "...", "secret": "..."} `` 或
    ``{"key_id": "...", "digest": "...", "scopes": [...], "active": true}``。
    使用 digest 时配置文件不含明文。
    """
    records: list[ApiKeyRecord] = []
    for idx, item in enumerate(data.get("keys") or []):
        if not isinstance(item, dict):
            raise ConfigError("auth.keys 条目须为对象")
        key_id = str(item.get("key_id") or f"key-{idx + 1}")
        scopes = tuple(str(s) for s in (item.get("scopes") or (SCOPE_READ, SCOPE_EXECUTE)))
        active = bool(item.get("active", True))
        digest = item.get("digest")
        if digest:
            records.append(ApiKeyRecord(key_id=key_id, digest=str(digest),
                                        scopes=frozenset(scopes), active=active))
            continue
        secret = item.get("secret")
        if not secret:
            raise ConfigError(f"auth.keys[{idx}] 需提供 secret 或 digest")
        if len(str(secret)) < 16:
            raise ConfigError(f"API Key {key_id!r} 长度不足 16 字符，拒绝使用弱密钥")
        records.append(ApiKeyRecord(key_id=key_id, digest=_digest(str(secret)),
                                    scopes=frozenset(scopes), active=active))
    return tuple(records)


def _load_config_file(env: dict[str, str]) -> dict:
    """读取 JSON 配置文件；未指定则返回空字典。"""
    path = env.get("DKWS_CONFIG_FILE")
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"DKWS_CONFIG_FILE 指向的文件不存在：{path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 解析失败：{path}") from exc
    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点须为对象")
    return data


def load_runtime_config(env: dict[str, str] | None = None,
                        *, strict: bool = True) -> RuntimeConfig:
    """装载运行时配置。

    Args:
        env: 环境变量映射，默认取 ``os.environ``。
        strict: 生产 profile 校验失败时是否抛出 ``ConfigError``；
            置 False 时降级为 ``warnings`` 收集（仅供诊断工具使用）。

    Returns:
        组装完成的 :class:`RuntimeConfig`。

    Raises:
        ConfigError: 配置非法，或生产 profile 缺少必要安全控制。
    """
    env = dict(os.environ if env is None else env)
    file_cfg = _load_config_file(env)
    file_auth = file_cfg.get("auth") or {}
    file_rate = file_cfg.get("rate_limit") or {}
    file_size = file_cfg.get("size_limit") or {}
    file_conc = file_cfg.get("concurrency") or {}
    file_store = file_cfg.get("runtime_store") or {}

    profile = (env.get("DKWS_PROFILE") or file_cfg.get("profile") or PROFILE_DEV).strip().lower()
    if profile not in VALID_PROFILES:
        raise ConfigError(f"DKWS_PROFILE 仅支持 {VALID_PROFILES}，实际为 {profile!r}")
    bind_host = env.get("DKWS_BIND_HOST") or file_cfg.get("bind_host") or "127.0.0.1"

    keys = _keys_from_env(env) or _keys_from_file(file_auth)
    auth_enabled = _env_bool(env, "DKWS_AUTH_ENABLED", None)
    if auth_enabled is None:
        auth_enabled = bool(file_auth.get("enabled", bool(keys)))
    auth = AuthConfig(
        enabled=bool(auth_enabled),
        header_name=(env.get("DKWS_AUTH_HEADER") or file_auth.get("header_name")
                     or "X-API-Key"),
        keys=keys,
        public_paths=tuple(file_auth.get("public_paths") or DEFAULT_PUBLIC_PATHS),
        admin_path_prefixes=tuple(file_auth.get("admin_path_prefixes")
                                  or DEFAULT_ADMIN_PATH_PREFIXES),
    )

    rate_enabled = _env_bool(env, "DKWS_RATE_LIMIT_ENABLED", None)
    if rate_enabled is None:
        rate_enabled = bool(file_rate.get("enabled", False))
    rate_limit = RateLimitConfig(
        enabled=bool(rate_enabled),
        requests_per_minute=_env_int(env, "DKWS_RATE_LIMIT_RPM",
                                     int(file_rate.get("requests_per_minute", 600))),
        burst=_env_int(env, "DKWS_RATE_LIMIT_BURST", int(file_rate.get("burst", 60))),
    )

    size_enabled = _env_bool(env, "DKWS_SIZE_LIMIT_ENABLED", None)
    if size_enabled is None:
        size_enabled = bool(file_size.get("enabled", True))
    size_limit = SizeLimitConfig(
        enabled=bool(size_enabled),
        max_request_bytes=_env_int(env, "DKWS_MAX_REQUEST_BYTES",
                                   int(file_size.get("max_request_bytes", 1048576))),
        max_response_bytes=_env_int(env, "DKWS_MAX_RESPONSE_BYTES",
                                    int(file_size.get("max_response_bytes", 8388608))),
    )

    conc_enabled = _env_bool(env, "DKWS_CONCURRENCY_ENABLED", None)
    if conc_enabled is None:
        conc_enabled = bool(file_conc.get("enabled", False))
    concurrency = ConcurrencyConfig(
        enabled=bool(conc_enabled),
        max_in_flight=_env_int(env, "DKWS_MAX_IN_FLIGHT",
                               int(file_conc.get("max_in_flight", 32))),
        acquire_timeout_seconds=float(
            env.get("DKWS_CONCURRENCY_TIMEOUT")
            or file_conc.get("acquire_timeout_seconds", 0.0)),
    )

    store_enabled = _env_bool(env, "DKWS_RUNTIME_STORE_ENABLED", None)
    if store_enabled is None:
        store_enabled = bool(file_store.get("enabled", False))
    store_path_raw = env.get("DKWS_RUNTIME_STORE_PATH") or file_store.get("path")
    runtime_store = RuntimeStoreConfig(
        enabled=bool(store_enabled),
        path=Path(store_path_raw) if store_path_raw else None,
        wal=bool(_env_bool(env, "DKWS_RUNTIME_STORE_WAL", bool(file_store.get("wal", True)))),
        busy_timeout_ms=_env_int(env, "DKWS_RUNTIME_STORE_BUSY_TIMEOUT_MS",
                                 int(file_store.get("busy_timeout_ms", 5000))),
        idempotency_ttl_seconds=_env_int(
            env, "DKWS_IDEMPOTENCY_TTL_SECONDS",
            int(file_store.get("idempotency_ttl_seconds", 600))),
    )

    cfg = RuntimeConfig(profile=profile, bind_host=bind_host, auth=auth,
                        rate_limit=rate_limit, size_limit=size_limit,
                        concurrency=concurrency, runtime_store=runtime_store)
    problems = validate_runtime_config(cfg)
    if problems and cfg.is_production and strict:
        raise ConfigError("生产 profile 配置校验失败：" + "；".join(problems))
    return RuntimeConfig(profile=cfg.profile, bind_host=cfg.bind_host, auth=cfg.auth,
                         rate_limit=cfg.rate_limit, size_limit=cfg.size_limit,
                         concurrency=cfg.concurrency, runtime_store=cfg.runtime_store,
                         warnings=tuple(problems))


def validate_runtime_config(cfg: RuntimeConfig) -> list[str]:
    """校验配置的安全底线，返回问题清单（空列表表示通过）。

    生产 profile 的强制项（ADR-013/ADR-015）：
    - 必须启用认证且至少有一个启用状态的密钥；
    - 必须启用限流与请求体大小上限；
    - 对外监听时必须启用认证（不得匿名暴露）。
    """
    problems: list[str] = []
    if cfg.auth.enabled and not cfg.auth.active_keys():
        problems.append("已启用认证但未配置任何有效 API Key")
    if cfg.rate_limit.requests_per_minute <= 0:
        problems.append("rate_limit.requests_per_minute 须为正数")
    if cfg.size_limit.max_request_bytes <= 0:
        problems.append("size_limit.max_request_bytes 须为正数")
    if cfg.concurrency.max_in_flight <= 0:
        problems.append("concurrency.max_in_flight 须为正数")
    if not cfg.is_production:
        return problems
    if not cfg.auth.enabled:
        problems.append("生产 profile 必须启用 API Key 认证（DKWS_AUTH_ENABLED=true）")
    if not cfg.rate_limit.enabled:
        problems.append("生产 profile 必须启用限流（DKWS_RATE_LIMIT_ENABLED=true）")
    if not cfg.size_limit.enabled:
        problems.append("生产 profile 必须启用请求体大小限制")
    if cfg.listens_publicly() and not cfg.auth.enabled:
        problems.append(f"生产 profile 对外监听 {cfg.bind_host} 时禁止匿名访问")
    return problems
