"""LightRAG 检索接入（M7 · D-31）：对**既有 lightRAG server** 的最小只读客户端。

形态选择：**接入外部 server**（不内嵌 `lightrag-hku`、不在工作区落索引）——理由与规范影响
见 `docs/adr/ADR-017-lightrag-retrieval-store.md`。要点：内嵌会把索引变成工作区的
**持久态**，与 §18.5「无隐藏持久化数据库文件」/§6.3「不得把其数据库文件作为持久化事实源」的
冲突面**更大**；接入外部 server 时索引在 KERT 工作区**之外**，工作区仍保持"文件目录为权威源、
投影可重建"。

纪律（fail-closed，与仓内同族处置一致）：

- 连接参数**只走 env**：``KERT_LIGHTRAG_URL`` / ``KERT_LIGHTRAG_API_KEY`` / ``KERT_LIGHTRAG_TIMEOUT``；
- server 不可达 / 超时 ⇒ :class:`LightRagUnavailable`；非 2xx（含鉴权失败）⇒ :class:`LightRagHTTPError`；
  响应结构不符 ⇒ :class:`LightRagResponseInvalid` ⇒ **一律具名抛出**；
- **禁止**静默返回空结果：调用方必须能区分「**检索不到**」与「**检索不可达**」。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from urllib import error as urlerror
from urllib import request as urlrequest

DEFAULT_URL = "http://127.0.0.1:9621"
DEFAULT_TIMEOUT = 30.0
URL_ENV = "KERT_LIGHTRAG_URL"
API_KEY_ENV = "KERT_LIGHTRAG_API_KEY"
TIMEOUT_ENV = "KERT_LIGHTRAG_TIMEOUT"
#: 检索模式（lightRAG 既有取值域；本模块**不自造**新模式）
MODES = ("local", "global", "hybrid", "naive", "mix")


class LightRagError(RuntimeError):
    """LightRAG 接入层错误基类（具名；调用方必须显式处理，不得吞成空结果）。"""

    code = "LIGHTRAG_ERROR"


class LightRagUnavailable(LightRagError):
    """server 不可达 / 超时（连接层失败）。"""

    code = "LIGHTRAG_UNAVAILABLE"


class LightRagHTTPError(LightRagError):
    """非 2xx（含鉴权失败 401/403、端点不存在 404）。"""

    code = "LIGHTRAG_HTTP_ERROR"


class LightRagResponseInvalid(LightRagError):
    """响应不是预期结构（形状校验失败）。"""

    code = "LIGHTRAG_RESPONSE_INVALID"


@dataclass(frozen=True)
class LightRagCitation:
    """一处**出处**（lightRAG 的 reference）。"""

    reference_id: str
    file_path: str = ""
    content: str = ""


@dataclass(frozen=True)
class LightRagResult:
    """一次检索的规范化结果（实体 / 关系 / 出处）。"""

    query: str
    mode: str
    endpoint: str
    entities: tuple[dict, ...] = ()
    relations: tuple[dict, ...] = ()
    citations: tuple[LightRagCitation, ...] = ()
    raw: dict = field(default_factory=dict)


class LightRagClient:
    """对 lightRAG server 的只读客户端（连接参数只走 env，见模块 docstring）。"""

    def __init__(self, base_url: str = DEFAULT_URL, api_key: str = "",
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.api_key = api_key or ""
        self.timeout = float(timeout)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "LightRagClient":
        """从环境变量构造（缺省值：``http://127.0.0.1:9621`` / 无 key / 30s）。"""
        e = os.environ if env is None else env
        raw_timeout = str(e.get(TIMEOUT_ENV, "") or "").strip()
        try:
            timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT
        except ValueError:
            raise LightRagError(
                f"{TIMEOUT_ENV} 非法（须为秒数）: {raw_timeout!r}") from None
        return cls(base_url=str(e.get(URL_ENV, "") or DEFAULT_URL),
                   api_key=str(e.get(API_KEY_ENV, "") or ""), timeout=timeout)

    # ---------------- 连接层 ----------------

    def _request(self, method: str, path: str, payload: dict | None = None,
                 timeout: float | None = None) -> tuple[int, object]:
        url = f"{self.base_url}{path}"
        data = None if payload is None else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)
        try:
            with urlrequest.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = resp.status
        except urlerror.HTTPError as exc:                    # 非 2xx
            body = exc.read().decode("utf-8", errors="replace")
            raise LightRagHTTPError(
                f"LightRAG 返回 {exc.code}（{url}）：{body[:200]}") from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:   # 连接层
            raise LightRagUnavailable(
                f"LightRAG 不可达（{url}）：{exc}") from exc
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LightRagResponseInvalid(
                f"LightRAG 响应非 JSON（{url}）：{raw[:200]}") from exc

    def available(self) -> bool:
        """探活（只回答是否可达；**不吞**异常语义，仅返回布尔，供调用方分流）。"""
        try:
            status, _ = self._request("GET", "/health",
                                      timeout=min(self.timeout, 5.0))
        except LightRagError:
            return False
        return 200 <= status < 300

    # ---------------- 检索 ----------------

    def query_data(self, query: str, *, mode: str = "hybrid") -> LightRagResult:
        """数据式检索：返回**实体 + 关系 + 出处**。

        端点：lightRAG server 的 ``POST /query/data``（数据块而非纯文本答复）；
        端点不存在（404/405）时**抛具名错误**，不做静默降级 —— 降级会掩盖"接入口径变了"。

        :raises LightRagError: 其子类（不可达 / 非 2xx / 形状不符）；**不返回空结果**。
        """
        if mode not in MODES:
            raise LightRagError(f"非法 mode: {mode!r}（既有取值域 {MODES}）")
        _, payload = self._request("POST", "/query/data",
                                   {"query": query, "mode": mode})
        if not isinstance(payload, dict):
            raise LightRagResponseInvalid(
                f"/query/data 响应非对象：{type(payload).__name__}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise LightRagResponseInvalid(
                f"/query/data 缺 data 对象（实为 {type(data).__name__}）："
                f"{str(payload)[:200]}")
        citations = tuple(
            LightRagCitation(
                reference_id=str(r.get("reference_id", "")),
                file_path=str(r.get("file_path", "")),
                content=str(r.get("content", ""))[:280],
            )
            for r in (data.get("references") or ()) if isinstance(r, dict))
        return LightRagResult(
            query=query, mode=mode, endpoint="/query/data",
            entities=tuple(e for e in (data.get("entities") or ()) if isinstance(e, dict)),
            relations=tuple(r for r in (data.get("relationships") or ())
                            if isinstance(r, dict)),
            citations=citations, raw=payload)
