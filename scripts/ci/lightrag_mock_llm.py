#!/usr/bin/env python3
"""确定性 OpenAI 兼容 mock（LightRAG 检索环 CI 用）：``/v1/chat/completions`` + ``/v1/embeddings``。

**为什么存在**：`lightrag-hku` **没有**"无模型/确定性"后端（binding 只有 openai/ollama/gemini/…），
而 CI 里跑真实模型既不可离线也不可确定（单 job ≤10 分钟）。故本 job 的做法是
**真实 lightrag-server + 假模型**：服务器本体、管线、HTTP 协议、异步语义、存储全部是真的，
只有"模型调用"被本 mock 替换。

设计要点（都是**实测**得出的，不是想当然）：

1. **零外部依赖、零网络、确定性**：只用标准库；同一输入 ⇒ 同一输出（sha256 派生）。
2. **嵌入必须是"词法性"的**（hashing trick：字符 2-gram + 拉丁词，L2 归一）。
   实测教训：用纯随机哈希嵌入时，向量检索会命中**别的文档** ⇒ 检索环用例假红；
   词法性嵌入让"查询与其出处文档"余弦更高，才能稳定命中本篇。
3. **抽取从 prompt 的文档段派生**（模板里由 ``---Input Text---`` 包裹）：
   实体名取文档中的大写专名与中文词，描述取文档头部 ⇒ 查询（含文档内标记如
   ``CUST-CORP-0001``）能在实体/关系面命中**该文档的 chunk**。
4. **关键词从 ``User Query:`` 段派生** ⇒ local/global 检索面向真实查询词。
5. **续抽（gleaning）段不含文档段** ⇒ 回 ``<|COMPLETE|>`` 收敛，不重复抽取。

⚠ **用途边界（不得误读）**：本 mock **不**替代 lightrag 本体，也**不代表**模型质量。
它支撑的 job 验的是**接入口径/管线/异步/出处回指/撤回守卫**；**不验**检索质量与真实模型行为。
真实模型 + 凭据的全量 E2E 仍属 opt-in（见 `docs/adr/ADR-017-lightrag-retrieval-store.md` ⑦-a）。

用法：``python scripts/ci/lightrag_mock_llm.py [port]``（默认 9630；前台运行，日志走 stdout）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: 嵌入维度（与 lightrag 侧 `EMBEDDING_DIM` 必须一致）
DIM = 64
#: lightrag 默认的记录分隔符（`PROMPTS["DEFAULT_TUPLE_DELIMITER"]`）
SEP = "<|#|>"
#: lightrag 默认的完成符
COMPLETE = "<|COMPLETE|>"

_INPUT_TEXT = re.compile(r"---Input Text---\s*```\s*(.*?)\s*```", re.S)
_USER_QUERY = re.compile(r"User Query:\s*(.*?)\s*---Output---", re.S)
_UPPER_TOK = re.compile(r"[A-Z][A-Z0-9_\-]{3,}")
_CJK_TOK = re.compile(r"[\u4e00-\u9fff]{2,}")
_LATIN_TOK = re.compile(r"[A-Za-z0-9_]{2,}")


def _digest(text: str, size: int) -> bytes:
    out = b""
    i = 0
    while len(out) < size:
        out += hashlib.sha256(f"{i}|{text}".encode("utf-8")).digest()
        i += 1
    return out[:size]


def _tokens(text: str) -> list[str]:
    """词法单元：拉丁词（小写）+ 汉字 2-gram（确定性、中英都覆盖）。"""
    toks = [t.lower() for t in _LATIN_TOK.findall(text)]
    cjk = "".join(_CJK_TOK.findall(text))
    toks += [cjk[i:i + 2] for i in range(max(0, len(cjk) - 1))]
    return toks


def embed(text: str) -> list[float]:
    """确定性**词法性**嵌入（hashing trick + L2 归一）⇒ 词面相近 ⇒ 余弦更高。"""
    vec = [0.0] * DIM
    for tok in _tokens(text):
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % DIM
        vec[idx] += 1.0 if h[4] % 2 == 0 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 6) for x in vec]


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _doc_text(prompt: str) -> str:
    """取被抽取的文档正文（lightrag 模板用 ``---Input Text---`` + 代码栅栏包裹）。"""
    m = _INPUT_TEXT.search(prompt)
    if m:
        return m.group(1)
    m = re.search(r"```\s*(.*?)\s*```", prompt, re.S)
    return m.group(1) if m else prompt[-1200:]


def _pick_names(text: str, limit: int = 6) -> list[str]:
    """取文本里的**专名**（大写/连字符词优先，再补中文词）——确定性、按出现顺序。"""
    out: list[str] = []
    for pat in (_UPPER_TOK, _CJK_TOK):
        for tok in pat.findall(text):
            tok = tok.strip()
            if tok and tok not in out:
                out.append(tok)
            if len(out) >= limit:
                return out
    return out or ["KERT-CI-DOC"]


def extraction_records(doc: str) -> str:
    """按 lightrag 默认（分隔符）格式产出确定性抽取结果。"""
    names = _pick_names(doc)
    head = _squeeze(doc)[:300]
    lines = [f"entity{SEP}{name}{SEP}ORGANIZATION{SEP}{head}" for name in names]
    for src, dst in zip(names, names[1:]):
        lines.append(f"relation{SEP}{src}{SEP}{dst}{SEP}related_to{SEP}{_squeeze(doc)[:120]}")
    return "\n".join(lines) + "\n" + COMPLETE


def keywords_json(query: str) -> str:
    """从查询文本派生关键词（高/低层），供 local/global 检索使用。"""
    names = _pick_names(query, limit=5)
    cjk = [t for t in _CJK_TOK.findall(query)][:3]
    low = names[:3] or ["KERT"]
    high = cjk[:3] or low
    return json.dumps({"high_level_keywords": high, "low_level_keywords": low},
                      ensure_ascii=False)


def complete(prompt: str) -> str:
    """按 prompt 形状给出确定性答复（分支顺序即语义，勿调换）。"""
    if "---Input Text---" in prompt:                 # 抽取（含文档段）
        return extraction_records(_doc_text(prompt))
    if SEP in prompt:                                # 续抽/校验段：收敛，不重复抽取
        return COMPLETE
    m = _USER_QUERY.search(prompt)                   # 关键词抽取（含 User Query 段）
    if m:
        return keywords_json(m.group(1))
    if "keywords" in prompt.lower():
        return keywords_json(prompt[-400:])
    return "KERT-RETRIEVAL-CI"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # 静音（日志由 job 侧保留）
        return

    def _send(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                 # noqa: N802 - BaseHTTPRequestHandler 约定
        if self.path.rstrip("/").endswith("/models"):
            self._send({"object": "list", "data": [{"id": "mock", "object": "model"}]})
            return
        self._send({"ok": True})

    def do_POST(self) -> None:                # noqa: N802 - BaseHTTPRequestHandler 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            req = {}
        path = self.path.rstrip("/")
        if path.endswith("/embeddings"):
            items = req.get("input") or [""]
            if isinstance(items, str):
                items = [items]
            self._send({"object": "list",
                        "data": [{"object": "embedding", "index": i,
                                  "embedding": embed(str(t))}
                                 for i, t in enumerate(items)],
                        "model": req.get("model", "mock-embed"),
                        "usage": {"prompt_tokens": 1, "total_tokens": 1}})
            return
        if path.endswith("/chat/completions"):
            prompt = "\n".join(str(m.get("content", "")) for m in (req.get("messages") or []))
            self._send({"id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
                        "model": req.get("model", "mock"),
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": complete(prompt)}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                  "total_tokens": 2}})
            return
        self._send({"detail": f"mock: 未实现 {self.path}"}, code=404)


def main(argv: list[str]) -> int:
    port = int(argv[1]) if len(argv) > 1 else 9630
    print(f"[mock-llm] 确定性 OpenAI 兼容 mock 启动：http://127.0.0.1:{port}/v1 "
          f"(dim={DIM})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), _Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
