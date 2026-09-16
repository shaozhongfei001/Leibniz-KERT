"""LightRAG 接入（M7 · D-31）：对**既有 lightRAG server** 的最小客户端。

两个方向，**性质不同**，不得混为一谈：

- **检索（只读）**：:meth:`LightRagClient.query_data` —— 索引在 KERT 工作区**之外**，
  检索**零写入**工作区（ADR-017 判据①）；
- **发布（写）**：:meth:`LightRagClient.publish_text` —— 把 KERT 产物作为**文档**写入外部实例，
  属 ADR-017「**数据出口**」一节登记的**显式**动作（发布什么 / 发布到哪 / 如何撤回），
  不是检索的副作用。

形态选择：**接入外部 server**（不内嵌 `lightrag-hku`、不在工作区落索引）——理由与规范影响
见 `docs/adr/ADR-017-lightrag-retrieval-store.md`。要点：内嵌会把索引变成工作区的
**持久态**，与 §18.5「无隐藏持久化数据库文件」/§6.3「不得把其数据库文件作为持久化事实源」的
冲突面**更大**；接入外部 server 时索引在 KERT 工作区**之外**，工作区仍保持"文件目录为权威源、
投影可重建"。

纪律（fail-closed，与仓内同族处置一致）：

- 连接参数**只走 env**：``KERT_LIGHTRAG_URL`` / ``KERT_LIGHTRAG_API_KEY`` / ``KERT_LIGHTRAG_TIMEOUT``；
- server 不可达 / 超时 ⇒ :class:`LightRagUnavailable`；非 2xx（含鉴权失败）⇒ :class:`LightRagHTTPError`；
  响应结构不符 ⇒ :class:`LightRagResponseInvalid` ⇒ **一律具名抛出**；
- **禁止**静默返回空结果：调用方必须能区分「**检索不到**」与「**检索不可达**」；
- **发布侧同样具名**：重复发布 ⇒ :data:`ALREADY_PUBLISHED`（**先查后写**，不产生重复）；
  出处不可回译 / 等待索引完成超时 ⇒ :class:`LightRagArtifactRefused` / :class:`LightRagPipelineTimeout`；
  发布成功后**等文档可见**再返回（入库为异步 ⇒ 否则紧接的幂等预检会看不到它而重复写入；实测见 :meth:`wait_until_present`）。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib import error as urlerror
from urllib import request as urlrequest

DEFAULT_URL = "http://127.0.0.1:9621"
DEFAULT_TIMEOUT = 30.0
URL_ENV = "KERT_LIGHTRAG_URL"
API_KEY_ENV = "KERT_LIGHTRAG_API_KEY"
TIMEOUT_ENV = "KERT_LIGHTRAG_TIMEOUT"
#: 检索模式（lightRAG 既有取值域；本模块**不自造**新模式）
MODES = ("local", "global", "hybrid", "naive", "mix")
#: 发布结果状态（**本模块自有词汇**，与 lightRAG `InsertResponse.status` 区分）
PUBLISHED = "published"                  # 本次确实写入了
ALREADY_PUBLISHED = "already_published"  # 先查后写命中已有同 file_source ⇒ 幂等，不重复写入
#: 出处标识分隔符：KERT 相对产物路径里的 `/` ⇒ `__`。
#: 原因（**实测**）：lightRAG 对 `file_source` 做 **basename** 规范化
#: （`canonicalize_parser_hinted_basename`），目录会被吃掉 ⇒ 直接送
#: `04_serve/<svc>/version=<v>/ONTOLOGY.md` 时，检索命中的 `file_path` 只剩 `ONTOLOGY.md`，
#: **出处丢失**（违反 ADR-017「数据出口」的出处要求）。
SOURCE_SEP = "__"


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


class LightRagPipelineTimeout(LightRagError):
    """等待索引流水线空闲 / 文档处理完成**超时**（已受理但未在期限内落地）。"""

    code = "LIGHTRAG_PIPELINE_TIMEOUT"


class LightRagArtifactRefused(LightRagError):
    """KERT 侧产物不满足发布前置（路径越界 / 文件不存在 / 出处不可回译）⇒ **拒绝**，不静默。"""

    code = "LIGHTRAG_ARTIFACT_REFUSED"


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


@dataclass(frozen=True)
class LightRagDocument:
    """已发布文档的一行状态（`POST /documents/paginated` 的条目）。"""

    doc_id: str
    file_path: str
    status: str
    chunks_count: int | None = None


@dataclass(frozen=True)
class PublishOutcome:
    """一次发布的结果（:data:`PUBLISHED` 或 :data:`ALREADY_PUBLISHED`；失败一律具名异常）。"""

    file_source: str
    status: str
    track_id: str = ""
    message: str = ""


def artifact_file_source(rel_path: str) -> str:
    """把 KERT 相对产物路径转成**可回译**的发布出处标识（`file_source`）。

    形如 ``04_serve/product_knowledge/version=2026.09.16.1/ONTOLOGY.md``
    ⇒ ``04_serve__product_knowledge__version=2026.09.16.1__ONTOLOGY.md``。
    该串同时是**幂等判据**（同标识 ⇒ 同一文档）与**出处载体**（检索命中的 `filePath` 即回指它）。

    :raises LightRagArtifactRefused: 非相对路径 / 含 `.`·`..` / 任一段含 :data:`SOURCE_SEP`（会破坏回译）。
    """
    rel = PurePosixPath(str(rel_path).strip())
    if rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") for p in rel.parts):
        raise LightRagArtifactRefused(
            f"产物路径必须是**相对**路径且不含 . / ..：{rel_path!r}")
    if any(SOURCE_SEP in part for part in rel.parts):
        raise LightRagArtifactRefused(
            f"产物路径各段不得含 {SOURCE_SEP!r}（会破坏出处回译）：{rel_path!r}")
    return SOURCE_SEP.join(rel.parts)


def parse_artifact_file_source(file_source: str) -> str:
    """:func:`artifact_file_source` 的**逆**：发布标识 ⇒ KERT 相对产物路径。"""
    parts = str(file_source).split(SOURCE_SEP)
    if len(parts) < 2 or any(part == "" for part in parts):
        raise LightRagArtifactRefused(f"出处标识不可回译：{file_source!r}")
    return "/".join(parts)


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
        """探活：**只回答 `GET /health` 是否成功**，不承诺已授权、也不承诺能读全库。

        ⚠ 语义边界（免混用）：它返回 ``False`` 只说明"探活这一步失败"（含不可达与 `/health` 被拒）；
        **可达但未授权**（如 `GET /health` 开放、而 `/documents/*` 需凭据）时它会返回 ``True``，
        此时真正的鉴权失败由 :class:`LightRagHTTPError`（**401/403**）表达 ⇒ 调用方**必须**照样处理该异常，
        不得因 ``available() is True`` 就假定"有权限"。
        """
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

    # ---------------- 发布 / 撤回（写；ADR-017「数据出口」） ----------------

    def publish_text(self, text: str, *, file_source: str,
                     visibility_timeout: float = 30.0) -> PublishOutcome:
        """把一份文档（正文 + **出处标识**）写入外部实例：``POST /documents/text``。

        **幂等由本方法保证（先查后写）**，不依赖服务端：

        1. 先按 `file_path == file_source` 查已发布文档，命中即返回 :data:`ALREADY_PUBLISHED`
           ⇒ **不发写请求**、不产生重复；
        2. 服务端 409（"already contains"）同样映射为 :data:`ALREADY_PUBLISHED`（第二道）。

        ⚠ **实测（2026-09-16）**：服务端的 409 判定发生在 doc_status **落库之后**，而索引是
        **异步**的 ⇒ 紧跟其后的重复插入可能**不被拒**（会生成 `dup-<hash>` 失败条目）
        ⇒ 只靠服务端不足以幂等，故必须有第 1 步。

        :raises LightRagError: 其子类（不可达 / 非 2xx / 形状不符）；**不静默**。
        """
        if not str(file_source).strip():
            raise LightRagArtifactRefused("file_source 不得为空（出处标识必填）")
        existing = self.find_documents(file_source)
        if existing:
            return PublishOutcome(
                file_source=file_source, status=ALREADY_PUBLISHED,
                track_id=existing[0].doc_id,
                message=f"已存在同 file_source 的文档 {len(existing)} 条，未重复写入")
        try:
            _, payload = self._request("POST", "/documents/text",
                                       {"text": text, "file_source": file_source})
        except LightRagHTTPError as exc:
            if "409" in str(exc) and "already contains" in str(exc):
                return PublishOutcome(file_source=file_source, status=ALREADY_PUBLISHED,
                                      message=str(exc)[:280])
            raise
        if not isinstance(payload, dict):
            raise LightRagResponseInvalid(
                f"/documents/text 响应非对象：{type(payload).__name__}")
        server_status = str(payload.get("status") or "")
        if server_status != "success":
            raise LightRagError(
                f"发布未被受理（服务端 status={server_status!r}）：{str(payload)[:200]}")
        # 入库是**异步**的：等它**可见**再返回；否则紧随其后的"先查后写"看不到它 ⇒ 重复写入
        # （**实测 2026-09-16**：POST 返回 200 后 doc_status 条目要过一会儿才出现）。
        self.wait_until_present(file_source, timeout=visibility_timeout)
        return PublishOutcome(file_source=file_source, status=PUBLISHED,
                              track_id=str(payload.get("track_id") or ""),
                              message=str(payload.get("message") or ""))

    def documents(self, *, page_size: int = 200) -> tuple[LightRagDocument, ...]:
        """列出已发布文档（``POST /documents/paginated``；按 `has_next`/`total_pages` 翻全）。"""
        out: list[LightRagDocument] = []
        page = 1
        while True:
            _, payload = self._request("POST", "/documents/paginated",
                                       {"page": page, "page_size": page_size,
                                        "sort_field": "file_path", "sort_direction": "asc"})
            if not isinstance(payload, dict):
                raise LightRagResponseInvalid(
                    f"/documents/paginated 响应非对象：{type(payload).__name__}")
            rows = payload.get("documents")
            if not isinstance(rows, list):
                raise LightRagResponseInvalid("/documents/paginated 缺 documents 列表")
            for row in rows:
                if isinstance(row, dict):
                    out.append(LightRagDocument(
                        doc_id=str(row.get("id") or ""),
                        file_path=str(row.get("file_path") or ""),
                        status=str(row.get("status") or ""),
                        chunks_count=row.get("chunks_count")))
            if not rows:
                return tuple(out)
            info = payload.get("pagination")
            info = info if isinstance(info, dict) else {}
            if info.get("has_next") is True:
                page += 1
                continue
            total_pages = info.get("total_pages")
            if isinstance(total_pages, int) and page < total_pages:
                page += 1
                continue
            return tuple(out)

    def find_documents(self, file_source: str) -> tuple[LightRagDocument, ...]:
        """按出处标识**精确**定位已发布文档（含 `dup-*` 重复条目 ⇒ 撤回时一并清掉）。"""
        return tuple(d for d in self.documents() if d.file_path == file_source)

    def wait_until_present(self, file_source: str, *, timeout: float = 30.0,
                           interval: float = 1.0) -> tuple[LightRagDocument, ...]:
        """等该出处标识**可见**（入库**异步**，紧接 POST 的查询可能还看不到）。

        **实测（2026-09-16）**：`/documents/text` 返回 200 之后，doc_status 条目要过一会儿才出现
        ⇒ 少了这一步，"先查后写"的幂等与撤回都会在竞态窗口内误判（重复写入 / 误报"无可撤回"）。
        超时 ⇒ **具名** :class:`LightRagPipelineTimeout`（不静默放过）。
        """
        deadline = time.monotonic() + float(timeout)
        while True:
            found = self.find_documents(file_source)
            if found:
                return found
            if time.monotonic() >= deadline:
                raise LightRagPipelineTimeout(
                    f"{timeout:.0f}s 内未看到 file_source={file_source!r}（入库为异步）")
            time.sleep(interval)

    def delete_documents(self, doc_ids) -> dict:
        """按 doc id **撤回**（``DELETE /documents/delete_document``；服务端**异步**执行）。"""
        ids = [str(i) for i in doc_ids if str(i)]
        if not ids:
            raise LightRagArtifactRefused("doc_ids 为空 ⇒ 无可撤回对象")
        _, payload = self._request("DELETE", "/documents/delete_document", {"doc_ids": ids})
        if not isinstance(payload, dict):
            raise LightRagResponseInvalid(
                f"/documents/delete_document 响应非对象：{type(payload).__name__}")
        return payload

    def pipeline_busy(self) -> bool:
        """索引流水线是否忙（``GET /documents/pipeline_status``）。"""
        _, payload = self._request("GET", "/documents/pipeline_status")
        if not isinstance(payload, dict):
            raise LightRagResponseInvalid(
                f"/documents/pipeline_status 响应非对象：{type(payload).__name__}")
        return bool(payload.get("busy"))

    def wait_until_idle(self, *, timeout: float = 300.0, interval: float = 3.0) -> None:
        """等索引流水线空闲；**超时 ⇒ 具名** :class:`LightRagPipelineTimeout`（不静默放过）。"""
        deadline = time.monotonic() + float(timeout)
        while True:
            if not self.pipeline_busy():
                return
            if time.monotonic() >= deadline:
                raise LightRagPipelineTimeout(
                    f"{timeout:.0f}s 内流水线仍忙（{self.base_url}）")
            time.sleep(interval)

    def wait_until_absent(self, doc_ids, *, timeout: float = 180.0,
                          interval: float = 3.0) -> None:
        """等**指定 doc id 全部消失**（删除是异步的）；超时 ⇒ 具名超时。"""
        want = {str(i) for i in doc_ids if str(i)}
        if not want:
            return
        deadline = time.monotonic() + float(timeout)
        while True:
            left = {d.doc_id for d in self.documents()} & want
            if not left:
                return
            if time.monotonic() >= deadline:
                raise LightRagPipelineTimeout(
                    f"{timeout:.0f}s 内仍有 {len(left)} 条未撤回（{self.base_url}）")
            time.sleep(interval)
