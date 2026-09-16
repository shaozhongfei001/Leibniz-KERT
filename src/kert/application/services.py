"""知识服务层（FR-SRV-003~008、规格 §10.8、§12、§13、§15）。

- 只读取活动发布投影（04_serve/<service>/CURRENT.md → version=*），绝不扫描 Work 候选（FR-SRV-008）；
- 数据查询、实体、图谱、检索、规则、证据溯源；
- 结果可追溯到文档、片段、页码、哈希和版本（FR-SRV-007）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq

from ..domain import timeutil
from ..domain.errors import AssetNotFoundError, ServiceNotReadyError, UsageError
from ..domain.ontology_reference import check_lineage_ontology, lineage_ontology_fields
from ..domain.query_modes import (
    DIRECTION_BOTH,
    DIRECTION_IN,
    DIRECTION_OUT,
    GRAPH_CYPHER_ARROWS,
    GRAPH_DIRECTIONS,
    GRAPH_MODE_CLOSURE,
    GRAPH_MODE_NEIGHBOR,
    GRAPH_MODE_PATHS,
    GRAPH_MODES,
    SEARCH_MODE_FULLTEXT,
    SEARCH_MODE_HYBRID,
    SEARCH_MODE_VECTOR,
    SEARCH_MODES,
)
from ..domain.rules import dsl
from ..infrastructure import markdown
from ..infrastructure.parquet import build_filter

DEFAULT_SERVICE = "product_knowledge"

_FULLTEXT_STOP = {"的", "了", "是", "在", "和", "与", "及", "或", "一个", "为", "产品"}

#: 允许发布到外部检索服务的**工作区产物根**（数据出口白名单；ADR-017「数据出口」）。
#: 只有 `03_core/**`（知识资产）与 `04_serve/**`（发布投影/本体物化产物）可出区；
#: `01_raw`/`02_work`/`90_control`（可能含凭据/草案）**不在**其列。
EGRESS_ROOTS = ("03_core", "04_serve")

#: 出处头里的**摘要行**前缀（`publish` 写入 / `retract` 归属校验 / `egress_state` 判据
#: **三处共用** ⇒ 判据单点、不分叉；行序要求见 :meth:`KnowledgeService.publish_artifact`）。
EGRESS_SHA_PREFIX = "- sha256: "

#: 数据出口状态（`egress_state` 的分类；`egress_publish` 的动作依据）
EGRESS_MISSING = "missing"    # 实例上**无**该出处
EGRESS_CURRENT = "current"    # 实例正文摘要 == 本地产物**当前**摘要
EGRESS_STALE = "stale"        # 实例上有，但正文摘要 != 本地当前摘要（**具名**，不静默当成功）
#: `egress_publish` 的动作结果（state 的第二维：做了什么）
EGRESS_STATE_PUBLISHED = "published"    # 本次写入
EGRESS_STATE_REFRESHED = "refreshed"    # 撤回（**经归属校验**）后重发


def sha_marker(digest: str) -> str:
    """出处头里的摘要标记（**唯一判据载体**：写入 / 校验 / 查询三处共用）。"""
    return f"{EGRESS_SHA_PREFIX}{digest}"


def _egress_rel(rel_path: str) -> str:
    """校验发布对象是**工作区内的 03_core/04_serve 相对路径**；越界 ⇒ 具名拒绝。"""
    from ..infrastructure.lightrag_client import LightRagArtifactRefused

    rel = PurePosixPath(str(rel_path).strip())
    if rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") for p in rel.parts):
        raise LightRagArtifactRefused(f"必须是非空**相对**路径：{rel_path!r}")
    if rel.parts[0] not in EGRESS_ROOTS:
        raise LightRagArtifactRefused(
            f"只允许发布工作区产物（{'/'.join(EGRESS_ROOTS)}）：{rel_path!r}")
    return rel.as_posix()


def _lightrag_client():
    """按 env 构造实例客户端（连接参数只走 env；见 lightrag_client 模块 docstring）。"""
    from ..infrastructure.lightrag_client import LightRagClient

    return LightRagClient.from_env()


#: 全链关联 ID 的两个既有字段名（**取自计划本身**，不新造）：
#: 计划 / 物化血缘（``PLAN_LINEAGE.json``=``plan.to_dict()``）/ 发布结果 / 检索引用
#: 四处一律用这两个键承载同一条链的身份。
PLAN_ID_KEY = "planId"
PLAN_HASH_KEY = "planHash"
#: 物化血缘文件名（`ProjectionBuilder` 产物版本目录旁；见 `materialize_from_plan`）
PLAN_LINEAGE_NAME = "PLAN_LINEAGE.json"


def plan_identity_for_artifact(ws: Path, rel_path: str) -> dict | None:
    """**全链关联 ID 的唯一取 ID 入口**：由产物路径取同版本目录旁的**计划身份**。

    一次业务动作的链 = 计划 → 物化 → 发布 → 检索；四处共用**同一对** ``planId``/``planHash``
    （键名取自计划自身，**不新造字段名**）。取法：产物形如
    ``04_serve/<svc>/version=<v>/<name>`` ⇒ 读**同目录**的 :data:`PLAN_LINEAGE_NAME`
    （= ``plan.to_dict()`` 原样照抄，由 :meth:`KnowledgeService.materialize_from_plan` 写入）
    ⇒ 返回其 ``planId``/``planHash``。

    - 无该产物形态 / 无血缘文件（如 ``03_core`` 资产）⇒ 返回 ``None``：
      **不伪造占位 ID**（调用方据此**省略**字段，而不是写空串）；
    - 血缘文件存在但**不可用**（坏 JSON / 缺 ID）⇒ **具名** :class:`UsageError`（fail-closed）：
      "关联 ID 静默消失"正是这条链最该防的失效。
    """
    rel = PurePosixPath(str(rel_path).strip())
    parts = rel.parts
    if len(parts) < 4 or parts[0] != "04_serve" or not parts[2].startswith("version="):
        return None
    lineage = ws / parts[0] / parts[1] / parts[2] / PLAN_LINEAGE_NAME
    if not lineage.is_file():
        return None
    try:
        doc = json.loads(lineage.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"物化血缘不可读（{lineage.relative_to(ws).as_posix()}）：{exc}") from exc
    if not isinstance(doc, dict):
        raise UsageError(f"物化血缘非对象：{lineage.relative_to(ws).as_posix()}")
    plan_id = doc.get(PLAN_ID_KEY)
    plan_hash = doc.get(PLAN_HASH_KEY)
    if not (isinstance(plan_id, str) and plan_id.strip()):
        raise UsageError(f"物化血缘缺 {PLAN_ID_KEY}：{lineage.relative_to(ws).as_posix()}")
    if not (isinstance(plan_hash, str) and plan_hash.strip()):
        raise UsageError(f"物化血缘缺 {PLAN_HASH_KEY}：{lineage.relative_to(ws).as_posix()}")
    return {PLAN_ID_KEY: plan_id, PLAN_HASH_KEY: plan_hash,
            "lineagePath": lineage.relative_to(ws).as_posix()}


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

    def _read_table(self, name: str, *,
                     filters: dict | list | None = None) -> pa.Table:
        """读取投影 Parquet 文件，支持谓词下推。"""
        p = self._version_dir() / name
        if not p.is_file():
            raise AssetNotFoundError(f"投影文件不存在: {name}")
        filter_expr = build_filter(filters) if filters else None
        if filter_expr is not None:
            return pq.read_table(p, filters=filter_expr)
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
        table = self._read_table(f"datasets/{dataset}.parquet", filters=where)
        rows = table.to_pylist()
        if select:
            rows = [{k: r.get(k) for k in select if k in r} for r in rows]
        rows = rows[:limit]
        return ServiceResult(
            data={"dataset": dataset, "records": rows, "count": len(rows)},
            meta=self._meta(dataset=dataset),
        )

    # ---------------- 实体（FR-SRV-004） ----------------

    def get_entity(self, entity_id: str, *, as_of: str | None = None) -> ServiceResult:
        ents = self._read_table("entities.parquet", filters={"entity_id": entity_id})
        hits = ents.to_pylist()
        if not hits:
            raise AssetNotFoundError(f"实体不存在: {entity_id}")
        entity = hits[0]
        stmts = self._read_table("statements.parquet",
                                  filters={"subject_id": entity_id}).to_pylist()
        if as_of:
            stmts = [s for s in stmts if _active_on(s, as_of)]
        return ServiceResult(
            data={"entity": entity, "statements": stmts, "statement_count": len(stmts)},
            meta=self._meta(entity_id=entity_id),
        )

    # ---------------- 图谱（FR-SRV-004、§15.4） ----------------

    def graph(self, start_entity_ids: list[str], *,
              relation_types: list[str] | None = None,
              direction: str = DIRECTION_OUT, max_depth: int = 1,
              max_nodes: int = 100,
              mode: str = GRAPH_MODE_NEIGHBOR) -> ServiceResult:
        """图谱查询（IMP-ADR-011：Kùzu 投影后端，回退内存 BFS）。

        mode: neighbor（多级可达，默认）/ closure（递归闭包，去重）/ paths（路径枚举）。
        """
        if max_depth > 10:
            raise UsageError("max_depth 最大为 10")
        if max_nodes > 1000:
            raise UsageError("max_nodes 最大为 1000")
        if direction not in GRAPH_DIRECTIONS:
            raise UsageError(f"非法 direction: {direction!r}")
        if mode not in GRAPH_MODES:
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
                      max_depth, max_nodes, mode=GRAPH_MODE_NEIGHBOR) -> ServiceResult:
        """内存邻接 BFS（原实现，max_depth 上限放宽到 10；paths 模式返回节点序列）。"""
        ents = {r["entity_id"]: r for r in self._read_table("entities.parquet").to_pylist()}
        rels = self._read_table("relations.parquet").to_pylist()
        adj: dict[str, list[dict]] = {}
        for rel in rels:
            if relation_types and rel["relation_type"] not in relation_types:
                continue
            if direction in (DIRECTION_OUT, DIRECTION_BOTH):
                adj.setdefault(rel["source_id"], []).append(
                    {"target": rel["target_id"], "relation_type": rel["relation_type"],
                     "relation_id": rel["relation_id"], "statement_id": rel.get("statement_id")})
            if direction in (DIRECTION_IN, DIRECTION_BOTH):
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
                if mode == GRAPH_MODE_PATHS:
                    paths.append([n for n in trail + [e["target"]]])
                if e["target"] not in visited:
                    queue.append((e["target"], depth + 1, trail + [e["target"]]))
        data = {"nodes": list(nodes.values()), "edges": edges,
                "node_count": len(nodes), "edge_count": len(edges), "mode": mode}
        if mode == GRAPH_MODE_PATHS:
            data["paths"] = paths
        return ServiceResult(data=data, meta=self._meta(ranking_policy_version="none"))

    def _graph_kuzu(self, builder, start_entity_ids, relation_types, direction,
                    max_depth, max_nodes, mode) -> ServiceResult:
        """Kùzu Cypher 后端：多级可达 / 闭包 / 路径枚举。"""
        import kuzu

        db = kuzu.Database(str(builder.graph_path()))
        con = kuzu.Connection(db)
        depth = max(max_depth, 1)
        arrow = GRAPH_CYPHER_ARROWS[direction]
        rel = (f"-[:Rel*1..{depth}]{arrow}" if direction != DIRECTION_BOTH
               else f"-[:Rel*1..{depth}]{GRAPH_CYPHER_ARROWS[DIRECTION_BOTH]}")
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        paths: list[list[str]] = []
        for s in start_entity_ids:
            if mode in (GRAPH_MODE_NEIGHBOR, GRAPH_MODE_CLOSURE):
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
                edge_rows = con.execute(
                    f"MATCH (a:Company {{eid:$s}})-[r:Rel]{arrow}(b:Company) "
                    "RETURN b.eid, r.relation_type, r.relation_id, r.statement_id",
                    {"s": s}).get_all()
                for eid, rt, rid, sid in edge_rows:
                    edges.append({"source": s, "target": eid, "relation_type": rt,
                                  "relation_id": rid, "statement_id": sid})
            elif mode == GRAPH_MODE_PATHS:
                # paths 必须方向敏感（BOTH 拆 OUT/IN），避免核心-供应商环路打转
                dirs = ([DIRECTION_OUT, DIRECTION_IN] if direction == DIRECTION_BOTH
                        else [direction])
                for d in dirs:
                    arrow_p = GRAPH_CYPHER_ARROWS[d]
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
        if mode == GRAPH_MODE_PATHS:
            data["paths"] = paths
        return ServiceResult(data=data, meta=self._meta(ranking_policy_version="none"))

    # ---------------- 检索（FR-SRV-002、§15） ----------------

    def search(self, query: str, *, mode: str = SEARCH_MODE_FULLTEXT, top_k: int = 10,
               filters: dict | None = None) -> ServiceResult:
        if mode not in SEARCH_MODES:
            raise UsageError(f"非法检索模式: {mode!r}")
        segs = self._read_table("segments.parquet", filters=filters).to_pylist()
        if mode in (SEARCH_MODE_FULLTEXT, SEARCH_MODE_HYBRID):
            ft = _fulltext_score(query, segs)
        else:
            ft = []
        if mode in (SEARCH_MODE_VECTOR, SEARCH_MODE_HYBRID):
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
        if mode == SEARCH_MODE_FULLTEXT:
            hits = ft
        elif mode == SEARCH_MODE_VECTOR:
            hits = vs
        else:
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
                "score_type": (SEARCH_MODE_HYBRID if mode == SEARCH_MODE_HYBRID else mode),
                "page_from": seg.get("page_from"), "page_to": seg.get("page_to"),
                "source_version": seg.get("source_release_id"),
                "evidence_uri": seg.get("source_path"),
            })
        return ServiceResult(
            data={"query": query, "mode": mode, "hits": results,
                  "hit_count": len(results),
                  "degraded": mode == SEARCH_MODE_VECTOR and not vs},
            meta=self._meta(ranking_policy_version=(
                "rank/v1" if mode == SEARCH_MODE_HYBRID else "none")),
        )

    # ---------------- 客户知识取数（v1.3 数据所有权：按 customerId 读库） ----------------

    def segments(self, document_id: str | None = None) -> list[dict]:
        """返回片段全量行（可选按 document_id 过滤），含 content/heading_path 原文。"""
        filters = {"document_id": document_id} if document_id else None
        return self._read_table("segments.parquet", filters=filters).to_pylist()

    def entities(self, entity_id: str | None = None) -> list[dict]:
        """返回实体全量行（可选按 entity_id 过滤），含 x_* 扩展字段。"""
        filters = {"entity_id": entity_id} if entity_id else None
        return self._read_table("entities.parquet", filters=filters).to_pylist()

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
            except (json.JSONDecodeError, UsageError):
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

    # ---------------- 计划驱动的物化（T1：把「计划/技能」与「投影」接通） ----------------

    def materialize_from_plan(self, task_type: str, *, domain: str,
                              subject_id: str | None = None,
                              service_id: str | None = None,
                              include_vectors: bool = True) -> dict:
        """**由激活计划驱动**的服务投影物化（产物与既有投影**同形**）。

        约束（Owner 2026-09-16 直接指令）：

        - **不另起一套投影实现**：复用既有
          :class:`~kert.application.projection.ProjectionBuilder`（含其 G4 门禁与 Kùzu 图谱分支），
          本方法只做「计划门禁 → 调用既有 builder → 写血缘」；
        - **计划身份 + 本体引用写入产物元数据（血缘）**：血缘 = ``plan.to_dict()`` **原样照抄**
          （``planId`` / ``planHash`` / ``versions.ontology`` …，含计划身份与 planHash），
          **追加**一个**顶层** ``ontology`` 子块**= 既有 helper
          :func:`~kert.domain.ontology_reference.lineage_ontology_fields` 的输出**
          （5 键，键名全部取自既有声明与计划，**不新造字段**、**不自行反解** ``versions.ontology``
          字符串）；计划未放行时该 helper 返回 ``None`` ⇒ **不写占位串**；
        - **fail-closed**：计划未放行（路由未放行 / 本体引用缺失或非法）⇒ 直接抛出；
          **血缘本体面与计划不一致** ⇒ 同样抛出，**两种情况都不产出任何投影产物**
          （校验**先于**调用 projection builder，与计划构建器「没有第三态」的口径一致）。

        :param task_type: 计划任务类型（如 ``OUTREACH_PREPARATION``）。
        :param domain: ``03_core`` 下的域（投影输入）。
        :param subject_id: 计划主体（如 customerId）；仅记录、不入 plan hash。
        :param service_id: 目标 service_id；缺省用本实例的 ``service_id``。
        :param include_vectors: 是否产出 ``vectors.parquet``（透传既有 builder）。
        :returns: ``service_id`` / ``projection_version`` / ``job_id`` / ``files`` /
                  ``lineage_path`` / ``plan``（计划原文）**＋全链关联 ID**：``planId`` /
                  ``planHash``（键名取自计划自身 ⇒ 与血缘、发布结果、检索引用**同字段名、同值**）。
        """
        from ..domain.activation_plan import ActivationPlanBuilder
        from .projection import ProjectionBuilder

        # **同一实例**同时供门禁与血缘取值 ⇒ 本体输入面与计划门禁同源，不留时间窗口
        builder = ActivationPlanBuilder.load(self.ws)
        plan = builder.build(task_type, subject_id=subject_id)
        if not plan.allowed:
            raise UsageError(f"计划未放行 ⇒ 不物化（{plan.code}）：{plan.reason}")
        resolution = builder.ontology_resolution()
        ontology_block = lineage_ontology_fields(resolution)
        if ontology_block is None:
            raise UsageError(
                f"计划本体引用未放行 ⇒ 不物化（{resolution.code}）：{resolution.reason}")

        lineage = plan.to_dict()
        lineage["ontology"] = dict(ontology_block)
        # 校验先于产出：不一致 ⇒ 不产出投影（血缘是下游唯一可追溯凭证）
        check = check_lineage_ontology(resolution, lineage)
        if not check.allowed:
            raise UsageError(
                f"血缘本体引用与计划不一致 ⇒ 不物化（{check.code}）：{check.reason}")

        target_service = service_id or self.service_id
        result = ProjectionBuilder(self.ws, owner="plan_materializer").build(
            domain, service_id=target_service, include_vectors=include_vectors,
            idempotency_key=f"plan:{plan.plan_hash}")

        lineage_rel = (f"04_serve/{target_service}/version={result.projection_version}"
                       f"/PLAN_LINEAGE.json")
        (self.ws / lineage_rel).write_text(
            json.dumps(lineage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"service_id": result.service_id,
                "projection_version": result.projection_version,
                "job_id": result.job_id,
                "files": list(result.files),
                "lineage_path": lineage_rel,
                PLAN_ID_KEY: lineage[PLAN_ID_KEY],
                PLAN_HASH_KEY: lineage[PLAN_HASH_KEY],
                "plan": lineage}

    # ---------------- LightRAG 检索（M7 · D-31：接入外部 server） ----------------

    def retrieve_via_lightrag(self, query: str, *, mode: str = "hybrid",
                              client=None) -> dict:
        """经 **LightRAG**（外部 server）做一次检索，返回**实体 + 关系 + 出处**。

        接入层见 :mod:`kert.infrastructure.lightrag_client`（连接参数只走 env：
        ``KERT_LIGHTRAG_URL`` / ``KERT_LIGHTRAG_API_KEY`` / ``KERT_LIGHTRAG_TIMEOUT``）。

        **fail-closed**：server 不可达 / 鉴权失败 / 响应形状不符 ⇒ 由接入层抛**具名**异常向上传递，
        本方法**不**吞错、**不**返回空结果 ⇒ 调用方必须能区分「检索不到」与「检索不可达」。

        ⚠ 本方法**不**读写工作区：LightRAG 的索引在 KERT 工作区**之外**（见
        `docs/adr/ADR-017-lightrag-retrieval-store.md`），故不影响 §18.5/§6.3 的
        "工作区内无隐藏持久化数据库"口径。

        **全链关联 ID（⑧）**：每条出处按 `filePath`（= 发布标识，可回译）反解出产物路径
        ⇒ 取其**计划身份** ⇒ 出处上追加 ``artifact`` / ``planId`` / ``planHash``
        （与计划、物化血缘、发布结果**同名同值**）。反解不出（如被实例名规范化吃掉目录）
        或该产物无计划血缘 ⇒ **省略**这些键（不伪造）。

        :param query: 检索语句。
        :param mode: lightRAG 既有模式（``local``/``global``/``hybrid``/``naive``/``mix``）。
        :param client: 注入的 :class:`~kert.infrastructure.lightrag_client.LightRagClient`
            （缺省按 env 构造；测试用）。
        """
        from ..infrastructure.lightrag_client import LightRagClient

        client = client or LightRagClient.from_env()
        result = client.query_data(query, mode=mode)
        return {"query": result.query, "mode": result.mode, "endpoint": result.endpoint,
                "entities": list(result.entities), "relations": list(result.relations),
                "citations": [self._citation_with_chain(c) for c in result.citations]}

    def _citation_with_chain(self, citation) -> dict:
        """检索引用 → 链身份（不可回译 / 无血缘 ⇒ **省略**键，不伪造）。"""
        from ..infrastructure.lightrag_client import (
            LightRagArtifactRefused,
            parse_artifact_file_source,
        )

        out = {"referenceId": citation.reference_id, "filePath": citation.file_path,
               "content": citation.content}
        try:
            rel = parse_artifact_file_source(citation.file_path)
        except LightRagArtifactRefused:
            return out
        out["artifact"] = rel
        identity = plan_identity_for_artifact(self.ws, rel)
        if identity is not None:
            out[PLAN_ID_KEY] = identity[PLAN_ID_KEY]
            out[PLAN_HASH_KEY] = identity[PLAN_HASH_KEY]
        return out

    # ---------------- LightRAG 发布 / 撤回（M7 · P-1：数据出口，ADR-017） ----------------

    def publish_artifact(self, rel_path: str, *, client=None) -> dict:
        """把工作区内的一件**产物**作为文档发布到外部 LightRAG（**数据出口**）。

        发布面 = :data:`EGRESS_ROOTS`（``03_core/**`` 知识资产、``04_serve/**`` 投影/本体物化产物）；
        其余（`01_raw`/`02_work`/`90_control`——可能含草案与凭据）**拒绝**。

        纪律（ADR-017「数据出口」一节）：

        - **只读工作区**：本方法只读文件，不修改任何 KERT 文件（测试机械断言）；
        - **出处**：`file_source` = :func:`~kert.infrastructure.lightrag_client.artifact_file_source`
          （可回译的 ``04_serve__<svc>__version=<v>__<name>``）⇒ 检索命中的 `filePath` **回指产物路径 + 版本**；
          正文再前置**出处头**（相对路径 + sha256）⇒ 只看引用片段也能回溯；
        - **幂等**：同 `file_source` 已存在 ⇒ `already_published`（先查后写，不重复写入）；
        - **全链关联 ID（⑧）**：产物若有**计划血缘**（同版本目录的
          :data:`PLAN_LINEAGE_NAME`）⇒ 出处头**追加**计划标识行（在摘要行**之后**，
          故 D-34 的摘要判据不变）、返回里带上**同名同值**的 ``planId``/``planHash``
          ⇒ 检索命中的引用文本与发布结果**共享同一条链的 ID**；无血缘则**省略**
          （不伪造占位），`03_core` 资产属此类；
        - 失败一律**具名**抛出（越界 / 文件缺失 / 不可达 / 超时），**不静默**。

        :returns: ``{artifact, file_source, sha256, bytes, status, track_id, endpoint}``，
            有计划血缘时**追加** ``planId`` / ``planHash``。
        """
        from ..infrastructure.lightrag_client import (
            LightRagClient,
            artifact_file_source,
        )

        rel = _egress_rel(rel_path)
        path = self.ws / rel
        if not path.is_file():
            raise AssetNotFoundError(f"产物不存在: {rel}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        source = artifact_file_source(rel)
        identity = plan_identity_for_artifact(self.ws, rel)   # 无血缘 ⇒ None（不伪造）
        # ⚠ 行序是**语义**的：撤回前的归属校验靠实例返回的 `content_summary`（正文**头部窗口**）
        # 读到本行 ⇒ `sha256` 必须尽量靠前，否则长路径会把摘要窗口挤出 digest 而令校验恒失效（D-34）。
        # ⇒ 计划标识行只能**排在摘要行之后**（不得插到它前面）。
        chain_lines = "" if identity is None else (
            f"- 计划标识: {identity[PLAN_ID_KEY]}\n"
            f"- 计划哈希: {identity[PLAN_HASH_KEY]}\n")
        header = ("# KERT 产物出处（数据出口；登记见 ADR-017）\n"
                  f"{sha_marker(digest)}\n"
                  f"- 产物路径: {rel}\n"
                  f"- 发布标识: {source}\n"
                  f"{chain_lines}\n")
        client = client or LightRagClient.from_env()
        outcome = client.publish_text(header + raw.decode("utf-8", errors="replace"),
                                      file_source=source)
        out = {"workspace": str(self.ws), "artifact": rel, "file_source": source,
               "sha256": digest, "bytes": len(raw), "status": outcome.status,
               "track_id": outcome.track_id, "endpoint": "/documents/text"}
        if identity is not None:
            out[PLAN_ID_KEY] = identity[PLAN_ID_KEY]
            out[PLAN_HASH_KEY] = identity[PLAN_HASH_KEY]
        return out

    def retract_artifact(self, rel_path: str, *, timeout: float = 180.0,
                         visibility_timeout: float = 20.0, force: bool = False,
                         client=None) -> dict:
        """**撤回**该产物在外部实例上的发布（ADR-017「如何撤回」的机械实现）。

        按 `file_source` 找出**全部**条目（含 `dup-*` 重复残留）⇒ `DELETE /documents/delete_document`
        ⇒ 等到全部消失（删除是**异步**的）。无已发布记录 ⇒ 返回 ``removed=[]``（**不报错**，
        因为"本就没发布"与"撤回失败"必须可区分）。

        **归属校验（D-34，2026-09-16 起默认开启）**：`file_source` 由**确定性规则**派生、
        与"谁发布的"无关 ⇒ 撞名时按出处撤回会**删掉他人的合法文档**（本轮实测事故：
        实例文档 5→4、图 78/86→61/62）。⇒ 删除前逐条证明"实例上这份正文 == 本工作区该产物的**当前正文**"：
        比对实例返回的 `content_summary`（正文**头部窗口**）里我们自写的 `- sha256: <当前摘要>`
        （出处头的行序即为此而设，见 :meth:`publish_artifact`）；
        **任一条不匹配 ⇒ 具名拒绝且一份都不删**（fail-closed）。

        :param force: **显式**跳过归属校验（用于"明知是旧版本 / 来源已变、仍要清理"的场景）；
            跳过时返回值里 ``verified=False`` 留痕，**绝不静默**。
        :raises LightRagRetractRefused: 归属校验失败，或（非 force 时）本地产物不存在而无从校验。
        :param visibility_timeout: 判定"未发布过"前的**可见性窗口** —— 入库是异步的，
            刚发布完就撤回时条目可能尚未出现（实测竞态）⇒ 先等一会儿再下结论。
        """
        from ..infrastructure.lightrag_client import (
            LightRagClient,
            LightRagPipelineTimeout,
            LightRagRetractRefused,
            artifact_file_source,
        )

        rel = _egress_rel(rel_path)
        path = self.ws / rel
        source = artifact_file_source(rel)
        digest = ""
        if not force:
            if not path.is_file():
                raise LightRagRetractRefused(
                    f"撤回需归属校验，但本地产物不存在（无从比对内容摘要）：{rel}"
                    f"（确认要清理请显式 force=True）")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        client = client or LightRagClient.from_env()
        try:
            found = client.wait_until_present(source, timeout=visibility_timeout)
        except LightRagPipelineTimeout:
            found = ()
        if not found:
            return {"artifact": rel, "file_source": source, "removed": [],
                    "verified": not force, "sha256": digest,
                    "status": "nothing_to_retract"}
        if not force:
            marker = sha_marker(digest)
            foreign = [d.doc_id for d in found if marker not in (d.content_summary or "")]
            if foreign:
                raise LightRagRetractRefused(
                    f"撤回拒绝（归属校验失败）：{source!r} 下 {len(foreign)}/{len(found)} 条文档的正文"
                    f"出处头不含本工作区该产物的当前摘要 {digest[:16]}… ⇒ 疑似他人的合法文档；"
                    f"**一份都未删除**。doc_ids={foreign}（确认要清理请显式 force=True）")
        ids = [d.doc_id for d in found]
        payload = client.delete_documents(ids)
        client.wait_until_absent(ids, timeout=timeout)
        return {"artifact": rel, "file_source": source, "removed": ids,
                "verified": not force, "sha256": digest,
                "status": str(payload.get("status") or ""),
                "message": str(payload.get("message") or "")}

    def egress_state(self, rel_path: str, *, client=None, documents=None) -> dict:
        """**内容变更检测**（运维面）：实例上该出处的正文摘要 vs 本地产物**当前**摘要。

        判据 = 实例返回的 ``content_summary``（正文**头部窗口**）里我们自写的
        :func:`sha_marker`（出处头行序见 :meth:`publish_artifact`，摘要必须落在窗口内）。
        这是该实例 API 下**唯一可用**的判据：无"读正文"端点、不支持自定义 metadata
        （ADR-017「数据出口」）⇒ **不另找判据**。

        **口径与撤回一致**：``current`` 要求**全部**条目（含 `dup-*` 残留）的摘要都等于本地
        当前摘要 —— 与 :meth:`retract_artifact` 的归属校验同一条判据 ⇒
        ``state == current`` ⟺ 带校验的撤回可放行（**不产生"能撤回但不 current"的第二态**）。

        :param documents: 已取的实例文档全量（省一次全表扫；多产物批查时复用）；缺省按 client 取。
        :returns: ``{workspace, artifact, file_source, sha256, bytes, state, documents}``，
            ``state ∈ {missing, current, stale}``；``documents`` 逐条标注摘要是否命中。
        :raises AssetNotFoundError: 本地产物不存在（**无从比对**，不静默）。
        """
        from ..infrastructure.lightrag_client import artifact_file_source

        rel = _egress_rel(rel_path)
        path = self.ws / rel
        if not path.is_file():
            raise AssetNotFoundError(f"产物不存在: {rel}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        source = artifact_file_source(rel)
        if documents is None:
            client = client or _lightrag_client()
            documents = client.documents()
        hits = [d for d in documents if getattr(d, "file_path", "") == source]
        marker = sha_marker(digest)
        if not hits:
            state = EGRESS_MISSING
        elif all(marker in (getattr(d, "content_summary", "") or "") for d in hits):
            state = EGRESS_CURRENT
        else:
            state = EGRESS_STALE
        return {
            "workspace": str(self.ws), "artifact": rel, "file_source": source,
            "sha256": digest, "bytes": len(raw), "state": state,
            "documents": [
                {"doc_id": d.doc_id, "status": d.status, "chunks_count": d.chunks_count,
                 "marker_hit": marker in (getattr(d, "content_summary", "") or "")}
                for d in hits
            ],
        }

    def egress_publish(self, rel_path: str, *, refresh: bool = False, client=None) -> dict:
        """**运维面发布**：默认**安全**（同出处已有内容 ⇒ 不写不删）；``refresh`` 才"撤回→重发"。

        动作全部由 :meth:`egress_state` 的**同一判据**决定（不存在第二套比较）：

        - ``missing`` ⇒ 发布（``state=published``）；
        - ``current`` 且非 ``refresh`` ⇒ **不发写请求**（幂等，``status=already_published``）；
        - ``stale`` 且非 ``refresh`` ⇒ **具名** ``stale``、**不写不删**、**绝不静默当作成功**：
          这正是旧行为的缺口（同 `file_source` 已存在即回 ``already_published`` ⇒
          产物内容变了而知识库永远停在旧内容）；
        - ``refresh`` ⇒ 先 :meth:`retract_artifact`（**归属校验默认开启，不因 refresh 而放宽**）：
          只有"实例上那份正文 == 本工作区该产物**当前**正文"才允许删（D-34）⇒ 然后重发。
          ⚠ 故 ``stale`` + ``refresh`` **会具名拒绝**（此时"实例上那份"与"他人的合法文档"
          在摘要窗口内**不可区分**，删它就是把 D-34 的事故重演一遍）—— 拒绝时**一份都不删**。
          确需清理**来源已变**的条目，是操作员的**显式**动作：``retract_artifact(force=True)``。

        :returns: ``{workspace, artifact, file_source, sha256, bytes, prior_state, state,
            status, published, refresh, removed, documents, track_id, endpoint}``
        :raises AssetNotFoundError: 本地产物不存在。
        :raises LightRagRetractRefused: ``refresh`` 的归属校验失败（fail-closed）。
        """
        from ..infrastructure.lightrag_client import ALREADY_PUBLISHED

        rel = _egress_rel(rel_path)
        state_info = self.egress_state(rel, client=client)
        prior = state_info["state"]
        result = {
            "workspace": state_info["workspace"], "artifact": rel,
            "file_source": state_info["file_source"], "sha256": state_info["sha256"],
            "bytes": state_info["bytes"], "prior_state": prior,
            "refresh": bool(refresh), "published": False, "removed": [],
            "documents": state_info["documents"],
        }
        if prior == EGRESS_CURRENT and not refresh:
            result.update(state=EGRESS_CURRENT, status=ALREADY_PUBLISHED)
            return result
        if prior == EGRESS_STALE and not refresh:
            result.update(state=EGRESS_STALE, status=EGRESS_STALE)
            return result
        if refresh and prior != EGRESS_MISSING:
            # force **不传** ⇒ 归属校验生效（refresh 不是绕过 D-34 的开关）
            removed = self.retract_artifact(rel, client=client)
            result["removed"] = list(removed.get("removed") or [])
        out = self.publish_artifact(rel, client=client)
        result.update(state=EGRESS_STATE_REFRESHED if prior != EGRESS_MISSING
                      else EGRESS_STATE_PUBLISHED,
                      status=out["status"], published=True,
                      track_id=out.get("track_id"), endpoint=out.get("endpoint"))
        # 全链关联 ID（⑧）：发布结果与计划/血缘/检索引用**同名同值**（无血缘则省略）
        result.update({k: out[k] for k in (PLAN_ID_KEY, PLAN_HASH_KEY) if k in out})
        return result

    # ---------------- 证据溯源（FR-SRV-007、§15.5） ----------------

    def trace(self, object_id: str) -> ServiceResult:
        """服务结果 → 投影记录 → Core MD → 片段 → Raw 批次清单与哈希。

        **全链关联 ID（⑧）—— 同一条链也能经本方法取回**：当 ``object_id`` 命中某次物化血缘的
        ``planId`` / ``planHash`` 时，改走 :meth:`_plan_chain`（计划 → 物化 → 数据出口锚点），
        返回值**只使用合同已声明的 ``data`` 键**（``object_id`` / ``chain`` / ``complete``），
        链身份放在 ``chain[]`` 条目里（条目为**开集**，见 ``specs/kert-openapi-v1.yaml``
        ``EvidenceResponse``）⇒ 既有 ``/v1/evidence/{object_id}`` 路径即可取回，**无需新增端点或字段**。
        """
        version = self._active_version()
        plan_chain = self._plan_chain(object_id)
        if plan_chain is not None:
            return ServiceResult(data=plan_chain,
                                 meta=self._meta(chain=f"plan:{object_id}"))
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

    def _plan_chain(self, chain_id: str) -> dict | None:
        """按**计划身份**取回全链的**本地可得部分**（计划 → 物化 → 数据出口锚点）。

        - ``chain_id`` 命中某次物化血缘的 ``planId`` 或 ``planHash`` 时返回链；否则 ``None``
          （调用方落到既有"资产溯源"路径 ⇒ 既有语义不变）；
        - 返回值**只含合同已声明的** ``data`` 键（``object_id`` / ``chain`` / ``complete``）；
          身份键（``planId``/``planHash``/``file_source``）放在 ``chain[]`` 条目内（开集）；
        - ``complete`` 的**局部口径**（不得外推）：本地可得的链都已取到 =
          血缘 + 版本目录 + **至少一个**可出区产物（``EGRESS_ROOTS`` 下的确定性 ``file_source``）；
          ⚠ **发布/检索的"状态"不在本地留痕**（数据出口只读工作区，ADR-017 ⑥）⇒ 这里给出的是
          与发布结果、检索引用**同名同值**的**锚点**（``file_source``），用 ``kert egress status``
          或检索命中的 ``filePath`` 即可对上，**不声称**"已发布/已检索到"。
        """
        from ..infrastructure.lightrag_client import (
            LightRagArtifactRefused,
            artifact_file_source,
        )

        base = self.ws / "04_serve"
        if not base.is_dir():
            return None
        for lineage in sorted(base.glob(f"*/version=*/{PLAN_LINEAGE_NAME}")):
            try:
                doc = json.loads(lineage.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(doc, dict):
                continue
            if chain_id not in (doc.get(PLAN_ID_KEY), doc.get(PLAN_HASH_KEY)):
                continue
            vdir = lineage.parent
            entries = [{
                "layer": "plan", "object": doc.get(PLAN_ID_KEY),
                PLAN_ID_KEY: doc.get(PLAN_ID_KEY), PLAN_HASH_KEY: doc.get(PLAN_HASH_KEY),
                "taskType": doc.get("taskType"), "subjectId": doc.get("subjectId"),
                "path": lineage.relative_to(self.ws).as_posix(),
            }]
            entries.append({"layer": "04_serve", "object": vdir.name,
                            "path": vdir.relative_to(self.ws).as_posix(),
                            "files": sorted(p.name for p in vdir.iterdir() if p.is_file())})
            anchors = 0
            for p in sorted(vdir.iterdir()):
                if not p.is_file():
                    continue
                rel = p.relative_to(self.ws).as_posix()
                try:
                    source = artifact_file_source(rel)
                except LightRagArtifactRefused:
                    continue
                anchors += 1
                entries.append({"layer": "04_serve/egress", "object": source,
                                "artifact": rel, "file_source": source,
                                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
            return {"object_id": chain_id, "chain": entries, "complete": anchors > 0}
        return None

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
