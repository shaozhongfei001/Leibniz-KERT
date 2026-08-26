"""知识服务层（FR-SRV-003~008、规格 §10.8、§12、§13、§15）。

- 只读取活动发布投影（04_serve/<service>/CURRENT.md → version=*），绝不扫描 Work 候选（FR-SRV-008）；
- 数据查询、实体、图谱、检索、规则、证据溯源；
- 结果可追溯到文档、片段、页码、哈希和版本（FR-SRV-007）。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..domain import ids, timeutil
from ..domain.errors import AssetNotFoundError, ServiceNotReadyError, UsageError
from ..domain.rules import dsl
from ..infrastructure import markdown

DEFAULT_SERVICE = "product_knowledge"

_FULLTEXT_STOP = {"的", "了", "是", "在", "和", "与", "及", "或", "一个", "为", "产品"}


@dataclass
class ServiceResult:
    data: dict
    meta: dict = field(default_factory=dict)


class KnowledgeService:
    def __init__(self, workspace: Path, service_id: str = DEFAULT_SERVICE,
                 service_version: str = "1.0.0"):
        self.ws = Path(workspace)
        self.service_id = service_id
        self.service_version = service_version

    # ---------------- 投影定位 ----------------

    def _active_version(self) -> str:
        cur = self.ws / "04_serve" / self.service_id / "CURRENT.md"
        if not cur.is_file():
            raise ServiceNotReadyError(f"服务 {self.service_id} 无活动投影")
        text = cur.read_text(encoding="utf-8")
        parsed = markdown.parse_contract_md(text, path="CURRENT.md")
        if not parsed.ok:
            raise ServiceNotReadyError(f"服务指针非法: {parsed.errors}")
        return parsed.front_matter["target_version"]

    def _version_dir(self) -> Path:
        return self.ws / "04_serve" / self.service_id / f"version={self._active_version()}"

    def _read_table(self, name: str) -> pa.Table:
        p = self._version_dir() / name
        if not p.is_file():
            raise AssetNotFoundError(f"投影文件不存在: {name}")
        return pq.read_table(p)

    def _meta(self, **extra) -> dict:
        m = {
            "service_version": self.service_version,
            "data_version": self._active_version(),
            "generated_at": timeutil.ts_utc(),
        }
        m.update(extra)
        return m

    # ---------------- 数据查询（FR-SRV-003） ----------------

    def data_query(self, dataset: str, *, select: list[str] | None = None,
                   where: dict | None = None, limit: int = 100) -> ServiceResult:
        if limit > 1000:
            raise UsageError("limit 不能超过 1000")
        table = self._read_table(f"datasets/{dataset}.parquet")
        rows = table.to_pylist()
        if where:
            rows = [r for r in rows if all(
                r.get(k) == v for k, v in where.items())]
        if select:
            rows = [{k: r.get(k) for k in select if k in r} for r in rows]
        rows = rows[:limit]
        return ServiceResult(
            data={"dataset": dataset, "records": rows, "count": len(rows)},
            meta=self._meta(dataset=dataset),
        )

    # ---------------- 实体（FR-SRV-004） ----------------

    def get_entity(self, entity_id: str, *, as_of: str | None = None) -> ServiceResult:
        ents = self._read_table("entities.parquet")
        hits = [r for r in ents.to_pylist() if r["entity_id"] == entity_id]
        if not hits:
            raise AssetNotFoundError(f"实体不存在: {entity_id}")
        entity = hits[0]
        stmts = self._read_table("statements.parquet").to_pylist()
        related = [s for s in stmts if s["subject_id"] == entity_id
                   and (not as_of or _active_on(s, as_of))]
        return ServiceResult(
            data={"entity": entity, "statements": related, "statement_count": len(related)},
            meta=self._meta(entity_id=entity_id),
        )

    # ---------------- 图谱（FR-SRV-004、§15.4） ----------------

    def graph(self, start_entity_ids: list[str], *,
              relation_types: list[str] | None = None,
              direction: str = "OUT", max_depth: int = 1,
              max_nodes: int = 100,
              mode: str = "neighbor") -> ServiceResult:
        """图谱查询（IMP-ADR-011：Kùzu 投影后端，回退内存 BFS）。

        mode: neighbor（多级可达，默认）/ closure（递归闭包，去重）/ paths（路径枚举）。
        """
        if max_depth > 10:
            raise UsageError("max_depth 最大为 10")
        if max_nodes > 1000:
            raise UsageError("max_nodes 最大为 1000")
        if direction not in ("OUT", "IN", "BOTH"):
            raise UsageError(f"非法 direction: {direction!r}")
        if mode not in ("neighbor", "closure", "paths"):
            raise UsageError(f"非法 mode: {mode!r}")
        try:
            from ..infrastructure.graph.kuzu_builder import KuzuGraphBuilder

            builder = KuzuGraphBuilder(self.ws, service_id=self.service_id)
            if builder.graph_available():
                return self._graph_kuzu(builder, start_entity_ids, relation_types,
                                        direction, max_depth, max_nodes, mode)
        except Exception:
            pass  # fail-open：回退内存实现
        return self._graph_memory(start_entity_ids, relation_types, direction,
                                  max_depth, max_nodes, mode)

    def _graph_memory(self, start_entity_ids, relation_types, direction,
                      max_depth, max_nodes, mode="neighbor") -> ServiceResult:
        """内存邻接 BFS（原实现，max_depth 上限放宽到 10；paths 模式返回节点序列）。"""
        ents = {r["entity_id"]: r for r in self._read_table("entities.parquet").to_pylist()}
        rels = self._read_table("relations.parquet").to_pylist()
        adj: dict[str, list[dict]] = {}
        for rel in rels:
            if relation_types and rel["relation_type"] not in relation_types:
                continue
            if direction in ("OUT", "BOTH"):
                adj.setdefault(rel["source_id"], []).append(
                    {"target": rel["target_id"], "relation_type": rel["relation_type"],
                     "relation_id": rel["relation_id"], "statement_id": rel.get("statement_id")})
            if direction in ("IN", "BOTH"):
                adj.setdefault(rel["target_id"], []).append(
                    {"target": rel["source_id"], "relation_type": rel["relation_type"],
                     "relation_id": rel["relation_id"], "statement_id": rel.get("statement_id")})
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        paths: list[list[str]] = []
        queue = [(s, 0, [s]) for s in start_entity_ids]
        visited: set[str] = set()
        while queue and len(nodes) < max_nodes:
            cur, depth, trail = queue.pop(0)
            if cur in visited or cur not in ents:
                continue
            visited.add(cur)
            nodes[cur] = {"entity_id": cur, "name": ents[cur].get("name"),
                          "entity_type": ents[cur].get("entity_type"), "depth": depth}
            if depth >= max_depth:
                continue
            for e in adj.get(cur, []):
                edges.append({"source": cur, "target": e["target"],
                              "relation_type": e["relation_type"],
                              "relation_id": e["relation_id"],
                              "statement_id": e["statement_id"]})
                if mode == "paths":
                    paths.append([n for n in trail + [e["target"]]])
                if e["target"] not in visited:
                    queue.append((e["target"], depth + 1, trail + [e["target"]]))
        data = {"nodes": list(nodes.values()), "edges": edges,
                "node_count": len(nodes), "edge_count": len(edges), "mode": mode}
        if mode == "paths":
            data["paths"] = paths
        return ServiceResult(data=data, meta=self._meta(ranking_policy_version="none"))

    def _graph_kuzu(self, builder, start_entity_ids, relation_types, direction,
                    max_depth, max_nodes, mode) -> ServiceResult:
        """Kùzu Cypher 后端：多级可达 / 闭包 / 路径枚举。"""
        import kuzu

        db = kuzu.Database(str(builder.graph_path()))
        con = kuzu.Connection(db)
        depth = max(max_depth, 1)
        arrow = {"OUT": "->", "IN": "<-", "BOTH": "-"}[direction]
        rel = f"-[:Rel*1..{depth}]{arrow}" if direction != "BOTH" else f"-[:Rel*1..{depth}]-"
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        paths: list[list[str]] = []
        for s in start_entity_ids:
            if mode in ("neighbor", "closure"):
                rows = con.execute(
                    f"MATCH p=(a:Company {{eid:$s}}){rel}(b:Company) "
                    "RETURN b.eid, b.name, b.etype, MIN(length(p)) AS d "
                    "GROUP BY b.eid, b.name, b.etype ORDER BY d LIMIT $n",
                    {"s": s, "n": max_nodes}).get_all()
                for eid, name, etype, d in rows:
                    if eid not in nodes:
                        nodes[eid] = {"entity_id": eid, "name": name,
                                      "entity_type": etype, "depth": d}
                # 单跳边（兼容 edges 字段）
                one = f"-[:Rel]{arrow}" if direction != "BOTH" else "-[:Rel]-"
                edge_rows = con.execute(
                    f"MATCH (a:Company {{eid:$s}})-[r:Rel]{arrow}(b:Company) "
                    "RETURN b.eid, r.relation_type, r.relation_id, r.statement_id",
                    {"s": s}).get_all()
                for eid, rt, rid, sid in edge_rows:
                    edges.append({"source": s, "target": eid, "relation_type": rt,
                                  "relation_id": rid, "statement_id": sid})
            elif mode == "paths":
                # paths 必须方向敏感（BOTH 拆 OUT/IN），避免核心-供应商环路打转
                dirs = ["OUT", "IN"] if direction == "BOTH" else [direction]
                for d in dirs:
                    arrow_p = {"OUT": "->", "IN": "<-"}[d]
                    rows = con.execute(
                        f"MATCH p=(a:Company {{eid:$s}})-[:Rel*1..{depth}]{arrow_p}(b:Company) "
                        "RETURN nodes(p) LIMIT $n",
                        {"s": s, "n": max_nodes}).get_all()
                    for (ns,) in rows:
                        paths.append([{"entity_id": n["eid"], "name": n["name"]} for n in ns])
        db.close()
        if relation_types:
            edges = [e for e in edges if e["relation_type"] in relation_types]
        data = {"nodes": list(nodes.values()), "edges": edges,
                "node_count": len(nodes), "edge_count": len(edges), "mode": mode}
        if mode == "paths":
            data["paths"] = paths
        return ServiceResult(data=data, meta=self._meta(ranking_policy_version="none"))

    # ---------------- 检索（FR-SRV-002、§15） ----------------

    def search(self, query: str, *, mode: str = "FULLTEXT", top_k: int = 10,
               filters: dict | None = None) -> ServiceResult:
        if mode not in ("FULLTEXT", "VECTOR", "HYBRID"):
            raise UsageError(f"非法检索模式: {mode!r}")
        segs = [r for r in self._read_table("segments.parquet").to_pylist()]
        if filters:
            for k, v in filters.items():
                segs = [r for r in segs if r.get(k) == v]
        if mode in ("FULLTEXT", "HYBRID"):
            ft = _fulltext_score(query, segs)
        else:
            ft = []
        if mode in ("VECTOR", "HYBRID"):
            try:
                vec = self._read_table("vectors.parquet").to_pylist()
            except AssetNotFoundError:
                vec = []
            vec_map = {v["segment_id"]: v["embedding"] for v in vec}
            query_vec = _query_vector(query, vec_map)
            vs = []
            if query_vec is not None:
                for v in vec:
                    vs.append((v["segment_id"], _cosine(query_vec, v["embedding"])))
        else:
            vs = []
        if mode == "FULLTEXT":
            hits = ft
        elif mode == "VECTOR":
            hits = vs
        else:
            ft_map = {s: s for s, _ in ft}
            # 归一化融合：0.5 全文 + 0.5 向量（ranking_policy_version 记录）
            merged: dict[str, float] = {}
            max_ft = max((x for _, x in ft), default=1.0) or 1.0
            max_vs = max((x for _, x in vs), default=1.0) or 1.0
            for sid, score in ft:
                merged[sid] = merged.get(sid, 0.0) + 0.5 * (score / max_ft)
            for sid, score in vs:
                merged[sid] = merged.get(sid, 0.0) + 0.5 * (score / max_vs)
            hits = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
        seg_map = {r["segment_id"]: r for r in segs}
        results = []
        for sid, score in hits[:top_k]:
            seg = seg_map.get(sid)
            if not seg:
                continue
            results.append({
                "segment_id": sid,
                "document_id": seg.get("document_id"),
                "content_excerpt": _excerpt(seg.get("content", ""), query),
                "score": round(score, 4),
                "score_type": "HYBRID" if mode == "HYBRID" else mode,
                "page_from": seg.get("page_from"), "page_to": seg.get("page_to"),
                "source_version": seg.get("source_release_id"),
                "evidence_uri": seg.get("source_path"),
            })
        return ServiceResult(
            data={"query": query, "mode": mode, "hits": results,
                  "hit_count": len(results), "degraded": mode == "VECTOR" and not vs},
            meta=self._meta(ranking_policy_version="rank/v1" if mode == "HYBRID" else "none"),
        )

    # ---------------- 客户知识取数（v1.3 数据所有权：按 customerId 读库） ----------------

    def segments(self, document_id: str | None = None) -> list[dict]:
        """返回片段全量行（可选按 document_id 过滤），含 content/heading_path 原文。"""
        rows = self._read_table("segments.parquet").to_pylist()
        if document_id:
            rows = [r for r in rows if r.get("document_id") == document_id]
        return rows

    def entities(self, entity_id: str | None = None) -> list[dict]:
        """返回实体全量行（可选按 entity_id 过滤），含 x_* 扩展字段。"""
        rows = self._read_table("entities.parquet").to_pylist()
        if entity_id:
            rows = [r for r in rows if r.get("entity_id") == entity_id]
        return rows

    def relations(self) -> list[dict]:
        """返回关系全量行。"""
        return self._read_table("relations.parquet").to_pylist()

    # ---------------- 规则评估（FR-SRV-005、§13.5、§14） ----------------

    def evaluate_rule(self, rule_set: str | None = None, *,
                      facts: dict) -> ServiceResult:
        rules = self._read_table("rules.parquet").to_pylist()
        if rule_set:
            rules = [r for r in rules if r["rule_id"] == rule_set]
        matched: list[dict] = []
        outcomes: list[dict] = []
        missing: list[str] = []
        evidence: list[str] = []
        human_required = False
        for rule in sorted(rules, key=lambda r: (-r.get("priority", 0), r["rule_id"])):
            try:
                when = json.loads(rule["when"])
                result = dsl.evaluate(when, facts)
            except (json.JSONDecodeError, UsageError) as exc:
                continue
            is_match = result.value is True
            trace = [t for t in result.trace]
            missing_here = [t for t in trace if t.get("value") == "UNKNOWN"]
            if missing_here:
                missing.append(rule["rule_id"])
                continue
            if not is_match:
                continue
            then = json.loads(rule["then"])
            outcome = dsl.evaluate(then, facts).value
            outcomes.append({"rule_id": rule["rule_id"], "name": rule.get("name"),
                             "outcome": outcome,
                             "execution_mode": rule.get("execution_mode")})
            matched.append({
                "rule_id": rule["rule_id"], "name": rule.get("name"),
                "rule_type": rule.get("rule_type"),
                "priority": rule.get("priority"),
                "execution_mode": rule.get("execution_mode"),
            })
            evidence.append(rule["rule_id"])
            if rule.get("execution_mode") == "HUMAN_CONFIRM_REQUIRED":
                human_required = True
        return ServiceResult(
            data={
                "evaluation_id": f"EVAL-{timeutil.ts_utc()[:19].replace(':', '')}",
                "rule_set_version": self._active_version(),
                "matched_rules": matched,
                "outcomes": outcomes,
                "missing_inputs": sorted(set(missing)),
                "evidence_refs": evidence,
                "human_confirmation_required": human_required,
                "explanation_trace": [{"rule": m["rule_id"], "matched": True}
                                      for m in matched],
            },
            meta=self._meta(),
        )

    # ---------------- 证据溯源（FR-SRV-007、§15.5） ----------------

    def trace(self, object_id: str) -> ServiceResult:
        """服务结果 → 投影记录 → Core MD → 片段 → Raw 批次清单与哈希。"""
        version = self._active_version()
        chain: list[dict] = []
        # 1. 投影层
        chain.append({"layer": "04_serve", "object": object_id,
                      "version": version,
                      "path": f"04_serve/{self.service_id}/version={version}"})
        # 2. Core 层：查找对应 MD
        core = self._find_core_asset(object_id)
        if core is None:
            return ServiceResult(
                data={"object_id": object_id, "chain": chain,
                      "complete": False, "blocker": "Core 资产未找到"},
                meta=self._meta())
        chain.append({"layer": "03_core", "object": object_id,
                      "version": core["version"], "path": core["rel"],
                      "sha256": core["sha256"]})
        # 3. 来源片段/证据
        fm = core["fm"]
        seg_ids = [s for s in (fm.get("source_ids", []) or []) if str(s).startswith("SEG-")]
        if fm.get("source_segment_id"):
            seg_ids.append(fm["source_segment_id"])
        raw_hashes: list[str] = []
        for sid in seg_ids:
            seg = self._find_segment(sid)
            if seg:
                chain.append({"layer": "02_work/01_raw", "object": sid,
                              "document_id": seg.get("document_id"),
                              "path": seg["rel"]})
                raw_hashes.append(self._raw_hash_for_document(seg.get("document_id")))
        # 4. 审核决定
        decisions = self._find_decisions(object_id)
        for d in decisions:
            chain.append({"layer": "90_control", "object": d["decision_id"],
                          "decision": d["decision"], "path": d["rel"]})
        return ServiceResult(
            data={"object_id": object_id, "chain": chain,
                  "complete": not seg_ids or bool(raw_hashes),
                  "raw_hashes": list(set(raw_hashes))[:5]},
            meta=self._meta(),
        )

    # ---------------- 溯源辅助 ----------------

    def _find_core_asset(self, object_id: str) -> dict | None:
        core_dir = self.ws / "03_core"
        for domain_dir in core_dir.glob("*"):
            cur = domain_dir / "CURRENT.md"
            if not cur.is_file():
                continue
            version = _parse_target(cur.read_text(encoding="utf-8"))
            if not version:
                continue
            vdir = domain_dir / f"version={version}"
            for sub in ("entities", "relations", "statements", "rules",
                        "segments", "documents"):
                f = vdir / sub / f"{object_id}.md"
                if f.is_file():
                    text = f.read_text(encoding="utf-8")
                    parsed = markdown.parse_contract_md(text)
                    return {"rel": f.relative_to(self.ws).as_posix(),
                            "version": version, "sha256": _semantic_sha(text),
                            "fm": parsed.front_matter}
        return None

    def _find_segment(self, seg_id: str) -> dict | None:
        for root in ("04_serve", "02_work", "03_core"):
            base = self.ws / root
            if not base.is_dir():
                continue
            hits = list(base.rglob(f"{seg_id}.md"))
            if hits:
                return {"rel": hits[0].relative_to(self.ws).as_posix(),
                        "document_id": markdown.parse_contract_md(
                            hits[0].read_text(encoding="utf-8")
                        ).front_matter.get("document_id")}
        return None

    def _raw_hash_for_document(self, document_id: str) -> str | None:
        if not document_id:
            return None
        hits = list((self.ws / "02_work").rglob(
            f"documents/{document_id}/DOCUMENT.md"))
        if not hits:
            return None
        fm = markdown.parse_contract_md(hits[0].read_text(encoding="utf-8")).front_matter
        return fm.get("source_sha256")

    def _find_decisions(self, object_id: str) -> list[dict]:
        dec_dir = self.ws / "90_control" / "decisions"
        out = []
        if not dec_dir.is_dir():
            return out
        for f in dec_dir.glob("*.md"):
            parsed = markdown.parse_contract_md(f.read_text(encoding="utf-8"))
            if any(object_id in str(r) for r in parsed.front_matter.get("object_refs", [])):
                out.append({"decision_id": f.stem,
                            "decision": parsed.front_matter.get("decision"),
                            "rel": f.relative_to(self.ws).as_posix()})
        return out


# ---------------- 检索辅助 ----------------

def _tokenize(text: str) -> list[str]:
    text = str(text)
    words = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text)
    return [w for w in words if w not in _FULLTEXT_STOP]


def _fulltext_score(query: str, segs: list[dict]) -> list[tuple[str, float]]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    scored = []
    for seg in segs:
        content = str(seg.get("content", ""))
        text_tokens = _tokenize(content)
        if not text_tokens:
            continue
        score = 0.0
        for qt in q_tokens:
            if qt in content:
                score += text_tokens.count(qt) / math.sqrt(len(text_tokens))
        if score > 0:
            scored.append((seg["segment_id"], score))
    return sorted(scored, key=lambda kv: kv[1], reverse=True)


def _query_vector(query: str, vec_map: dict[str, list[float]]) -> list[float] | None:
    """确定性查询向量：由查询文本哈希派生（与嵌入器同构）。"""
    if not vec_map:
        return None
    dim = len(next(iter(vec_map.values())))
    import hashlib as _hl

    digest = _hl.sha256(query.encode("utf-8")).digest()
    return [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(dim)]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _excerpt(content: str, query: str, width: int = 60) -> str:
    idx = content.find(query[:8])
    if idx < 0:
        return content[:width]
    start = max(0, idx - width // 2)
    return content[start:start + width]


def _active_on(row: dict, as_of: str) -> bool:
    eff_from = row.get("effective_from") or "0000-01-01"
    eff_to = row.get("effective_to") or "9999-12-31"
    return str(eff_from) <= as_of <= str(eff_to)


def _parse_target(text: str) -> str | None:
    m = re.search(r"^target_version:\s*\"?([^\n\" ]+)", text, re.M)
    return m.group(1) if m else None


def _semantic_sha(text: str) -> str:
    from ..domain import hashing

    return hashing.md_semantic_sha256(text)
