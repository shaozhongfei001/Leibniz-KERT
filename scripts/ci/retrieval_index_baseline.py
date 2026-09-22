#!/usr/bin/env python3
"""检索环**索引基线**与**索引重建对照**（PC8 · CR-5 第 2/3 项）。

判据来源：`ADR-017`（LightRAG 为**可重建的派生检索层**）与 CR-5 交付物要求
「灌入记录（索引基线）+ 重建对照证据（出处集合 Jaccard）」。

## 两种模式

1. **基线**（默认）：在 **egress 白名单（`03_core`/`04_serve`）内**灌入指定产物集，
   记录可复核的基线：文档数 / 状态分布 / 分块数 / 存储体积 / 图规模（节点·边）/ 固定查询集的出处集合。
2. **重建对照**（`--rebuild-check`）：按 ADR-017 判据执行
   **清空 ⇒ 同集重灌 ⇒ 核对覆盖与出处一致**：
   - 「清空」以**文档数归零**为证（撤回全部 doc id 并等可见性消失）；
   - 「覆盖」= 重灌后每份产物的 `file_source` **都回来且 `processed`**（**缺一即 FAIL**）；
   - 「出处一致」= 固定查询集的引用 **`filePath` 集合 Jaccard**（逐查询给出，取最小值入闸）。

## fail-closed（**不许假绿**）

- 实例不可达 / 未授权 / 响应形状不符 ⇒ 具名错误 + **非 0 退出**（绝不"跳过"或"空结果算通过"）；
- 重建后**任一查询出处集合为空** ⇒ **FAIL**（空结果不得当作"重建成功"）；
- 覆盖率为 100% 且 Jaccard ≥ `--min-jaccard`（默认 0.9）才打印 `RETRIEVAL_INDEX...OK` 标记。

## 用法

```bash
# 基线
KERT_LIGHTRAG_URL=http://127.0.0.1:9621 KERT_LIGHTRAG_API_KEY=... \
python scripts/ci/retrieval_index_baseline.py --workspace /tmp/lr-ws \
  --glob '04_serve/**/PROD-*.json' --out /tmp/index-baseline.json

# 重建对照（清空 ⇒ 同集重灌 ⇒ 出处 Jaccard）
... --glob '04_serve/**/PROD-*.json' --rebuild-check --out /tmp/index-rebuild.json
```
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kert.application.services import KnowledgeService              # noqa: E402
from kert.infrastructure.lightrag_client import (                   # noqa: E402
    LightRagClient,
    artifact_file_source,
)

DEFAULT_QUERIES = (
    "现金池 集团资金归集 资金下拨",
    "流动资金贷款 融资 准入",
    "跨境人民币结算 展业三原则",
)


def _emit(msg: str) -> None:
    print(msg, flush=True)


def _fail(code: str, msg: str) -> "int":
    _emit(f"::error::[{code}] {msg}")
    return 5


def _graph_scale(storage: Path | None) -> dict:
    """图规模：从实例存储的 graphml 计量 **节点/边**（物理事实，非估计）。

    实例未给出存储目录（或文件缺失）⇒ 显式记 `unavailable`（**不**用查询结果冒充规模）。
    """
    if storage is None:
        return {"status": "unavailable", "reason": "未提供 --storage-dir（实例存储目录）"}
    graph = storage / "graph_chunk_entity_relation.graphml"
    if not graph.is_file():
        return {"status": "unavailable", "reason": f"未找到 {graph.name}"}
    text = graph.read_text(encoding="utf-8", errors="ignore")
    return {
        "status": "measured",
        "file": str(graph),
        "bytes": graph.stat().st_size,
        "nodes": text.count("<node "),
        "edges": text.count("<edge "),
    }


def _storage_volume(storage: Path | None) -> dict:
    if storage is None or not storage.is_dir():
        return {"status": "unavailable"}
    files = [p for p in storage.rglob("*") if p.is_file()]
    return {"status": "measured", "files": len(files),
            "bytes": sum(p.stat().st_size for p in files)}


def _publish_all(ws: Path, pattern: str) -> list[dict]:
    svc = KnowledgeService(ws)
    targets = sorted(p.relative_to(ws).as_posix() for p in ws.glob(pattern) if p.is_file())
    if not targets:
        raise SystemExit(f"::error::[NO_TARGET] 未匹配到产物：{pattern}（工作区 {ws}）")
    rows = [svc.egress_publish(t) for t in targets]
    return rows


def _clear(client: LightRagClient) -> int:
    """清空实例文档（撤回全部 doc id 并等可见性消失）；返回清空前的文档数。"""
    docs = client.documents()
    ids = [d.doc_id for d in docs]
    if ids:
        client.delete_documents(ids)
        client.wait_until_absent(ids, timeout=300)
    return len(docs)


def _citations(client: LightRagClient, queries) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for q in queries:
        res = client.query_data(q, mode="hybrid")
        out[q] = sorted({c.file_path for c in res.citations if c.file_path})
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True, help="KERT 工作区（产物须在 03_core|04_serve 内）")
    ap.add_argument("--glob", default="04_serve/**/*.json", help="相对工作区的产物匹配式")
    ap.add_argument("--queries", default=None, help="逗号分隔的固定查询集（缺省用内置 3 条）")
    ap.add_argument("--storage-dir", default=None, help="LightRAG 实例存储目录（量节点/边与体积）")
    ap.add_argument("--rebuild-check", action="store_true", help="执行「清空⇒同集重灌⇒出处对照」")
    ap.add_argument("--min-jaccard", type=float, default=0.9, help="重建对照的 Jaccard 下限")
    ap.add_argument("--out", default=None, help="证据 JSON 落盘路径")
    args = ap.parse_args()

    ws = Path(args.workspace)
    if not ws.is_dir():
        return _fail("WS_NOT_FOUND", f"工作区不存在：{ws}")
    queries = tuple(q.strip() for q in (args.queries.split(",") if args.queries else DEFAULT_QUERIES)
                    if q.strip())
    storage = (Path(args.storage_dir) if args.storage_dir else
               (Path(__import__("os").environ["KERT_LIGHTRAG_STORAGE"])
                if __import__("os").environ.get("KERT_LIGHTRAG_STORAGE") else None))

    client = LightRagClient.from_env()
    if not client.available():
        return _fail("LIGHTRAG_UNAVAILABLE", f"实例不可达：{client.base_url}（fail-closed，不跳过）")
    _emit(f"[index] 实例 = {client.base_url} | 工作区 = {ws} | 匹配式 = {args.glob}")

    evidence: dict = {"schema": "retrieval_index_evidence/v1",
                      "instance": client.base_url, "workspace": str(ws), "glob": args.glob,
                      "queries": list(queries), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    # ── 灌入（白名单内；egress_publish 自带越界与 stale 守卫）────────────────
    rows = _publish_all(ws, args.glob)
    states: dict[str, int] = {}
    for r in rows:
        states[r["state"]] = states.get(r["state"], 0) + 1
    client.wait_until_idle(timeout=900)
    docs = client.documents()
    by_status: dict[str, int] = {}
    for d in docs:
        by_status[d.status] = by_status.get(d.status, 0) + 1
    base = _citations(client, queries)
    evidence["ingest"] = {
        "artifacts": len(rows), "states": states,
        "documents": len(docs), "statusCounts": by_status,
        "chunks": sum(d.chunks_count or 0 for d in docs),
        "storage": _storage_volume(storage), "graph": _graph_scale(storage),
        "citationSets": {q: base[q] for q in base},
        "citationCounts": {q: len(v) for q, v in base.items()},
    }
    _emit(f"[index] 灌入 {len(rows)} 件（states={states}）⇒ 文档 {len(docs)}（{by_status}）")
    g = evidence["ingest"]["graph"]
    if g.get("status") == "measured":
        _emit(f"[index] 图规模：节点 {g['nodes']} · 边 {g['edges']} · {g['bytes']} 字节")
    v = evidence["ingest"]["storage"]
    if v.get("status") == "measured":
        _emit(f"[index] 存储体积：{v['files']} 文件 · {v['bytes']} 字节")
    empty = [q for q, c in base.items() if not c]
    if empty:
        _emit(f"::warning::[EMPTY_CITATION] 基线中以下查询无出处（重建判据将据此判 FAIL）：{empty}")

    # 如实登记「受管集之外的残留文档」：它们会让 Jaccard 出现**流程伪差**（见 rebuild 注释）
    managed = {artifact_file_source(rel) for rel in
               (sorted(p.relative_to(ws).as_posix() for p in ws.glob(args.glob) if p.is_file()))}
    non_managed = sorted({d.file_path for d in docs} - managed)
    evidence["ingest"]["managedCount"] = len(managed)
    evidence["ingest"]["nonManagedDocuments"] = non_managed
    if non_managed:
        _emit(f"::warning::[NON_MANAGED_DOCS] 库内有 {len(non_managed)} 篇不在受管集内："
              f"{non_managed[:2]}……（做重建对照请用 --rebuild-check：它会两次清空，保证同集对同集）")

    if not args.rebuild_check:
        _emit("RETRIEVAL_INDEX_BASELINE_OK "
              f"docs={len(docs)} chunks={sum(d.chunks_count or 0 for d in docs)}")
    else:
        # ── 重建对照（ADR-017）：清空 ⇒ 同集重灌 ⇒ 覆盖 + 出处 Jaccard ────────
        # ⚠ 对照必须"同集对同集"：库内若有**不在受管集内**的旧文档（如历史种子），
        #   第一次取样会把它们算进出处集合，使 Jaccard 出现**流程伪差**
        #   （实测第一次即因残留 1 篇种子文档 ⇒ 7/9 = 0.7778）。
        #   故做**两次「清空⇒同集灌入」**，两次取样都只含受管集 ⇒ 结论只反映重建本身。
        cleared = _clear(client)
        _emit(f"[rebuild] ① 清空完成（清掉 {cleared} 篇；文档数 = 0）")
        if client.documents():
            return _fail("REBUILD_NOT_CLEARED", "清空未生效：仍有文档")

        expected = {artifact_file_source(rel) for rel in
                    (sorted(p.relative_to(ws).as_posix() for p in ws.glob(args.glob) if p.is_file()))}

        # 取样 A（清空后首次同集灌入；用**权威** file_source 生成函数，避免手写格式漂移）
        rows_a = _publish_all(ws, args.glob)
        client.wait_until_idle(timeout=900)
        docs_a = client.documents()
        present_a = {d.file_path for d in docs_a if d.status == "processed"}
        set_a = _citations(client, queries)
        _emit(f"[rebuild] ② 取样 A：灌入 {len(rows_a)} 件 ⇒ 文档 {len(docs_a)}"
              f"（processed {len(present_a)}）｜出处分 {[len(set_a[q]) for q in queries]}")

        # 取样 B（再次清空 ⇒ 同集灌入）
        cleared_b = _clear(client)
        _emit(f"[rebuild] ③ 再次清空完成（清掉 {cleared_b} 篇）")
        if client.documents():
            return _fail("REBUILD_NOT_CLEARED", "第二次清空未生效")
        rows_b = _publish_all(ws, args.glob)
        client.wait_until_idle(timeout=900)
        docs_b = client.documents()
        present_b = {d.file_path for d in docs_b if d.status == "processed"}
        set_b = _citations(client, queries)
        covered = expected <= present_b
        missing = sorted(expected - present_b)
        _emit(f"[rebuild] ④ 取样 B：灌入 {len(rows_b)} 件 ⇒ 文档 {len(docs_b)}"
              f"（processed {len(present_b)}）｜覆盖 {'OK' if covered else f'MISSING {missing[:3]}'}")
        if not covered:
            return _fail("REBUILD_COVERAGE", f"重灌覆盖不全，缺 {len(missing)} 份：{missing[:3]}")

        jac = {q: round(_jaccard(set(set_a[q]), set(set_b[q])), 4) for q in queries}
        empty_b = [q for q, c in set_b.items() if not c]
        evidence["rebuild"] = {
            "clearedBeforeA": cleared, "clearedBeforeB": cleared_b,
            "documentsA": len(docs_a), "documentsB": len(docs_b),
            "coverage": 1.0 if covered else 0.0, "missing": missing,
            "citationSetsA": set_a, "citationSetsB": set_b, "jaccard": jac,
            "jaccardMin": min(jac.values()) if jac else None, "emptyB": empty_b,
        }
        _emit("[rebuild] ⑤ 出处对照（Jaccard A↔B）：" +
              " ".join(f"{q[:12]}…={v}" for q, v in jac.items()))
        if empty_b:
            return _fail("REBUILD_EMPTY_CITATION",
                         f"重建后出现空出处（空结果不得算通过）：{empty_b}")
        if min(jac.values()) < args.min_jaccard:
            return _fail("REBUILD_JACCARD_LOW",
                         f"Jaccard 最小 {min(jac.values())} < {args.min_jaccard}")
        _emit("RETRIEVAL_INDEX_REBUILD_OK "
              f"coverage=1.0 jaccard_min={min(jac.values())} jaccard_all={list(jac.values())}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        _emit(f"[index] 证据已落盘：{args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
