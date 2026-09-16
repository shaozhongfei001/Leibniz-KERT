"""Kùzu 知识图谱投影构建器（IMP-ADR-011 受控变更）。

- 从活动投影 `entities.parquet` / `relations.parquet` 构建 Kùzu 图库；
- 位置：`04_serve/<service>/version=*/graph/`（可重建投影层，非权威源）；
- 边保留溯源字段：relation_id / statement_id / effective_from / effective_to；
- 生成 `PROJECTION.json`（builder 版本、来源版本、图指纹）供可重建性比较；
- 删除后仅凭 Core 投影可重建（§18.4）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

from ...domain import hashing, timeutil
from ...domain.errors import ServiceNotReadyError

BUILDER_ID = "kuzu_graph_builder"
BUILDER_VERSION = "1.0.0"
GRAPH_SUBDIR = "graph"


@dataclass
class GraphBuildResult:
    service_id: str
    version: str
    node_count: int = 0
    edge_count: int = 0
    fingerprint: dict = field(default_factory=dict)
    graph_dir: str = ""


class KuzuGraphBuilder:
    def __init__(self, workspace: Path, service_id: str = "product_knowledge"):
        self.ws = Path(workspace)
        self.service_id = service_id

    # ---------------- 构建 ----------------

    def build(self, version: str | None = None) -> GraphBuildResult:
        import kuzu

        version = version or self._active_version()
        if not version:
            raise ServiceNotReadyError(f"服务 {self.service_id} 无活动投影")
        vdir = self.ws / "04_serve" / self.service_id / f"version={version}"
        ents = vdir / "entities.parquet"
        rels = vdir / "relations.parquet"
        if not ents.is_file() or not rels.is_file():
            raise ServiceNotReadyError(
                f"投影缺少 entities/relations: {vdir.relative_to(self.ws)}")

        graph_file = vdir / GRAPH_SUBDIR  # kuzu 0.11 单文件存储
        proj_file = vdir / f"{GRAPH_SUBDIR}.PROJECTION.json"
        # 可重建层：先删旧图再重建（保证确定性）
        if graph_file.exists():
            graph_file.unlink()
        if proj_file.exists():
            proj_file.unlink()

        et = pq.read_table(ents).to_pylist()
        rt = pq.read_table(rels).to_pylist()

        db = kuzu.Database(str(graph_file))
        con = kuzu.Connection(db)
        con.execute("CREATE NODE TABLE Company(eid STRING, name STRING, etype STRING, PRIMARY KEY(eid))")
        con.execute("CREATE REL TABLE Rel(FROM Company TO Company, "
                    "relation_type STRING, relation_id STRING, statement_id STRING, "
                    "effective_from STRING, effective_to STRING)")
        for e in et:
            con.execute("CREATE (:Company {eid:$e, name:$n, etype:$t})",
                        {"e": e["entity_id"], "n": e.get("name", ""), "t": e.get("entity_type", "")})
        for r in rt:
            con.execute(
                "MATCH (a:Company {eid:$s}), (b:Company {eid:$t}) "
                "CREATE (a)-[:Rel {relation_type:$rt, relation_id:$rid, "
                "statement_id:$sid, effective_from:$ef, effective_to:$et}]->(b)",
                {"s": r["source_id"], "t": r["target_id"],
                 "rt": r.get("relation_type", ""), "rid": r.get("relation_id", ""),
                 "sid": r.get("statement_id") or "",
                 "ef": r.get("effective_from") or "", "et": r.get("effective_to") or ""})
        db.close()

        fingerprint = self._fingerprint(et, rt)
        proj = {
            "schema": "graph_projection/v1",
            "service_id": self.service_id,
            "version": version,
            "builder_id": BUILDER_ID,
            "builder_version": BUILDER_VERSION,
            "built_at": timeutil.ts_utc(),
            "node_count": len(et),
            "edge_count": len(rt),
            "fingerprint": fingerprint,
            "status": "ACTIVE",
        }
        proj_file.write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
        return GraphBuildResult(service_id=self.service_id, version=version,
                                node_count=len(et), edge_count=len(rt),
                                fingerprint=fingerprint,
                                graph_dir=str(graph_file.relative_to(self.ws)))

    # ---------------- 指纹与重建 ----------------

    @staticmethod
    def _fingerprint(entities: list[dict], relations: list[dict]) -> dict:
        """图逻辑指纹：固定排序的内容哈希（不依赖 Kùzu 二进制）。"""
        e_sorted = sorted((e["entity_id"], e.get("name", ""), e.get("entity_type", ""))
                          for e in entities)
        r_sorted = sorted((r["source_id"], r.get("relation_type", ""), r["target_id"])
                          for r in relations)
        h = hashing.sha256_hex(json.dumps(
            {"nodes": e_sorted, "edges": r_sorted}, ensure_ascii=False, sort_keys=True))
        return {"nodes": len(entities), "edges": len(relations), "hash": h}

    def fingerprint_of(self, version: str) -> dict | None:
        p = self.ws / "04_serve" / self.service_id / f"version={version}" / f"{GRAPH_SUBDIR}.PROJECTION.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("fingerprint")
        except (json.JSONDecodeError, OSError):
            return None

    # ---------------- 访问 ----------------

    def _active_version(self) -> str | None:
        cur = self.ws / "04_serve" / self.service_id / "CURRENT.md"
        if not cur.is_file():
            return None
        m = re.search(r"^target_version:\s*\"?([^\n\" ]+)",
                      cur.read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else None

    def graph_available(self, version: str | None = None) -> bool:
        version = version or self._active_version()
        if not version:
            return False
        d = self.ws / "04_serve" / self.service_id / f"version={version}" / GRAPH_SUBDIR
        return d.is_file() and (self.ws / "04_serve" / self.service_id
                                / f"version={version}" / f"{GRAPH_SUBDIR}.PROJECTION.json").is_file()

    def graph_path(self, version: str | None = None) -> Path | None:
        version = version or self._active_version()
        if not version:
            return None
        d = self.ws / "04_serve" / self.service_id / f"version={version}" / GRAPH_SUBDIR
        return d if d.is_file() else None
