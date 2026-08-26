"""SP-20 对公客户服务建议书生成（Phase 1）。

- 输入：request.context（ContextPackage）或 request 顶层字段；
- 逐章生成（并行 ≤3 路 LLM），每章输出结构化 {content, claims[], unknowns[]}；
- 确定性装配：行业框架（按 industry 映射）+ 财务框架 + 章节模板；
- 生成后规则校验（proposal_rules，6 条 BLOCKING）；
- 确定性对客版过滤（段落级：仅含 F/A 或无 claim 的段落保留）+ filteringNotes；
- 输出 ServiceResult 兼容结构（附录 A ServiceResult）。
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
from pathlib import Path

from ..domain import timeutil
from ..infrastructure.adapters import llm as llm_mod
from . import proposal_rules

PROPOSAL_SKILL_ID = "SP-20"
ASSETS_DIR = Path(__file__).resolve().parents[3] / "skills" / "service-proposal"
MAX_PARALLEL_CHAPTERS = 3
RUN_ID_PREFIX = "RUN-PROPOSAL"

GATES = ["G0", "G1", "G2", "G3", "G4", "G5"]
GATE_NAMES = {"G0": "证据准备", "G1": "客户核验", "G2": "专家设计",
              "G3": "内部审批", "G4": "对客确认", "G5": "实施复盘"}


def _load_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    fm = {}
    if m:
        try:
            import yaml
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
    return {"front": fm, "body": text}


def _extract_list(body: str, heading: str) -> list[str]:
    """从资产正文提取「## 标题」下的列表项。"""
    out = []
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].strip().lstrip("# ").strip() == heading:
            i += 1
            while i < len(lines) and lines[i].strip():
                s = lines[i].strip()
                if s.startswith("- "):
                    out.append(s[2:].strip())
                i += 1
            break
        i += 1
    return out


class ServiceProposalExecutor:
    def __init__(self, assets_dir: Path = ASSETS_DIR):
        self.assets_dir = Path(assets_dir)
        self.chapters: list[dict] = []      # {id,name,label,sources,instr}
        self.appendix: list[dict] = []      # {id,name,cols,instr}
        self.industry: dict[str, str] = {}  # code -> framework body
        self.taxonomy = ""
        self.financial = ""
        self.gates: dict[str, dict] = {}    # GATE-BIZ-* 清单资产（Phase 2）
        self._load_assets()

    def _load_assets(self) -> None:
        tpl = self.assets_dir / "templates"
        for f in sorted((tpl / "ch*.md").parent.glob("ch0*.md")):
            doc = _load_md(f)
            fm = doc["front"]
            self.chapters.append({
                "id": fm.get("chapterId") or f.stem,
                "name": fm.get("name") or f.stem,
                "label": fm.get("requiredFactLabel", "C"),
                "sources": fm.get("dataSources") or [],
                "instr": doc["body"],
            })
        self.chapters.sort(key=lambda c: c["id"])
        for f in sorted((tpl / "apx*.md").parent.glob("apx-*.md")):
            doc = _load_md(f)
            fm = doc["front"]
            self.appendix.append({
                "id": fm.get("appendixId") or f.stem,
                "name": fm.get("name") or f.stem,
                "instr": doc["body"],
            })
        self.appendix.sort(key=lambda a: a["id"])
        for f in (self.assets_dir / "industry-frameworks").glob("INDUSTRY-*.md"):
            if f.stem == "INDUSTRY-TAXONOMY":
                self.taxonomy = f.read_text(encoding="utf-8")
            else:
                fm = _load_md(f)["front"]
                code = fm.get("industryCode", f.stem.removeprefix("INDUSTRY-"))
                self.industry[code] = f.read_text(encoding="utf-8")
        ff = self.assets_dir / "financial-framework.md"
        if ff.is_file():
            self.financial = ff.read_text(encoding="utf-8")
        # Phase 2：业务闸门清单资产（GATE-BIZ-*，权威清单在 DKWS 资产，GITS 只读展示/推进）
        for f in sorted((self.assets_dir / "gates").glob("GATE-BIZ-*.md")):
            doc = _load_md(f)
            fm = doc["front"]
            gate_id = fm.get("gateId", f.stem)
            body = doc["body"]
            must = _extract_list(body, "必须完成")
            forbidden = _extract_list(body, "禁止事项")
            self.gates[gate_id] = {"gateId": gate_id, "name": fm.get("name", gate_id),
                                   "sequence": fm.get("sequence", 0),
                                   "must": must, "forbidden": forbidden,
                                   "assetPath": f"skills/service-proposal/gates/{f.name}"}

    def gate_checklist(self, customer_id: str | None = None) -> list[dict]:
        """闸门清单资产（GATE-BIZ-*），供 GITS 渲染/推进参考（权威推进在 GITS）。"""
        return [self.gates[gid] for gid in sorted(self.gates,
                                                  key=lambda g: self.gates[g].get("sequence", 0))]

    # ---------------- 主入口 ----------------

    def execute(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        ctx = request.get("context") or request
        trace.append({"phase": "resolve", "status": "ok",
                      "message": f"SP-20 启动 customerId={ctx.get('customerId')}"})

        missing = [k for k in ("customerId", "customerName", "industry") if not ctx.get(k)]
        if missing:
            trace.append({"phase": "validate", "status": "failed",
                          "message": f"ContextPackage 缺失字段: {missing}"})
            raise ValueError(f"ContextPackage 缺失字段: {missing}")
        if not isinstance(ctx.get("enterpriseData"), dict):
            trace.append({"phase": "validate", "status": "failed", "message": "enterpriseData 缺失"})
            raise ValueError("enterpriseData 缺失")
        trace.append({"phase": "validate", "status": "ok", "message": "ContextPackage 校验通过"})

        industry_code = self._map_industry(ctx.get("industry", ""))
        framework = self.industry.get(industry_code, "")
        trace.append({"phase": "assets", "status": "ok",
                      "message": f"装配资产：行业框架={industry_code or 'OTHER'}，章节 {len(self.chapters)} 个"})

        run_id = f"{RUN_ID_PREFIX}-{timeutil.ts_utc()[:19].replace('-', '').replace('T', '').replace(':', '')}"
        proposal_type = ctx.get("proposalContext", {}).get("proposalType") or "INITIAL"
        phase = ctx.get("engagementPhase") or "FIRST_CONTACT"
        gate_state = self._gate_state(ctx)
        # 路由模式（Phase 2）：首次 ONTOLOGY_THEN_MAP；更新/持续经营 MAP_FIRST
        route_mode = "MAP_FIRST" if proposal_type == "UPDATE" else "ONTOLOGY_THEN_MAP"
        trace.append({"phase": "route", "status": "ok",
                      "message": f"路由模式 {route_mode}（proposalType={proposal_type}, phase={phase}）"})

        # 1) 逐章并行生成
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHAPTERS) as ex:
            futures = {ex.submit(self._gen_chapter, ch, ctx, framework, industry_code,
                                 route_mode): ch for ch in self.chapters}
            chapters_out = [f.result() for f in futures]
        chapters_out.sort(key=lambda c: c["chapterId"])
        for ch in chapters_out:
            trace.append({"phase": "model", "status": "ok",
                          "message": f"章节 {ch['chapterId']} 生成完成（claims {len(ch.get('claims', []))}）"})

        model_calls = [c for ch in chapters_out for c in ch.pop("_model_calls", [])]
        # 2) 合并文档
        merged = self._merge(chapters_out, ctx, run_id, proposal_type, phase)
        # 3) 规则校验
        rule_result = proposal_rules.evaluate(chapters_out, merged["customerVersion"], gate_state)
        merged["ruleViolations"] = rule_result["violations"]
        status = "SUCCESS" if not rule_result["blocking"] else "PARTIAL"
        merged["status"] = status
        trace.append({"phase": "compose", "status": "ok" if status == "SUCCESS" else "failed",
                      "message": f"规则校验：违规 {len(rule_result['violations'])} 条（{status}）"})

        model_call = self._aggregate(model_calls)
        result = {
            "schemaVersion": "1.0.0", "skillId": PROPOSAL_SKILL_ID, "runId": run_id,
            "status": status, "timestamp": timeutil.ts_utc(),
            "content": merged["content"], "citations": merged["citations"],
            "unknowns": merged["unknowns"], "limitations": merged["limitations"],
            "gateRecommendations": merged["gateRecommendations"],
            "ruleViolations": rule_result["violations"],
        }
        return {"skillId": PROPOSAL_SKILL_ID, "result": result}, model_call

    # ---------------- 章节生成 ----------------

    def _gen_chapter(self, ch: dict, ctx: dict, framework: str,
                     industry_code: str, route_mode: str = "ONTOLOGY_THEN_MAP") -> dict:
        context = self._chapter_context(ch, ctx, framework, industry_code, route_mode)
        system = ch["instr"]
        user = json.dumps({
            "skill": PROPOSAL_SKILL_ID, "chapterId": ch["id"], "chapterName": ch["name"],
            "customerId": ctx.get("customerId"), "customerName": ctx.get("customerName"),
            "industry": ctx.get("industry"), "industryCode": industry_code,
            "chapterContext": context,
        }, ensure_ascii=False)
        t0 = time.monotonic()
        try:
            adapter = llm_mod.create_llm_adapter("proposal")
            res = adapter.complete(system, user)
            model_call = {"model": res.model_id, "inputTokens": res.input_tokens,
                          "outputTokens": res.output_tokens,
                          "latencyMs": res.latency_ms}
        except Exception as exc:
            model_call = {"model": "error", "inputTokens": 0, "outputTokens": 0,
                          "latencyMs": round((time.monotonic() - t0) * 1000, 1)}
            return {"chapterId": ch["id"], "chapterName": ch["name"], "content": "",
                    "claims": [], "unknowns": [{"description": f"章节生成失败: {exc}",
                                                "suggestedAction": "重试"}],
                    "_model_calls": [model_call]}
        data = self._parse_json(res.text) or {}
        data.setdefault("chapterId", ch["id"])
        data.setdefault("content", "")
        data.setdefault("claims", [])
        data.setdefault("unknowns", [])
        data["_model_calls"] = [model_call]
        return data

    def _chapter_context(self, ch: dict, ctx: dict, framework: str, industry_code: str,
                         route_mode: str = "ONTOLOGY_THEN_MAP") -> dict:
        ed = ctx.get("enterpriseData") or {}
        pd = ctx.get("publicData") or {}
        pc = ctx.get("proposalContext") or {}
        base = {
            "customerId": ctx.get("customerId"),
            "customerName": ctx.get("customerName"),
            "industry": ctx.get("industry"),
            "industryCode": industry_code,
            "routeMode": route_mode,
            "basicInfo": ed.get("basicInfo"),
            "financialSummary": ed.get("financialSummary"),
            "creditFacility": ed.get("creditFacility"),
            "transactionSummary": ed.get("transactionSummary"),
            "industryReports": pd.get("industryReports", [])[:5],
            "newsEvents": pd.get("newsEvents", [])[:5],
            "regulatoryChanges": pd.get("regulatoryChanges", [])[:5],
            "interactionHistory": (ctx.get("interactionHistory") or [])[-5:],
            "interactionMemory": (ctx.get("interactionMemory") or [])[:20],
            "previousVersion": pc.get("previousVersion"),
        }
        if ch["id"] == "CH02":
            base["industryFramework"] = framework
        if ch["id"] == "CH03":
            base["financialFramework"] = self.financial
        return base

    # ---------------- 合并与过滤 ----------------

    def _merge(self, chapters: list[dict], ctx: dict, run_id: str,
               proposal_type: str, phase: str) -> dict:
        title = f"{ctx.get('customerName')}综合金融服务建议书"
        parts = [f"# {title}\n", f"> 类型：{proposal_type} ｜ 阶段：{phase} ｜ runId：{run_id}\n"]
        for ch in chapters:
            cid = ch.get("chapterId", "")
            if ch.get("content"):
                parts.append(ch["content"].strip() if ch["content"].strip().startswith("#")
                             else f"\n## {cid} {ch.get('chapterName', '')}\n\n{ch['content'].strip()}")
        draft = "\n\n".join(parts)

        claims = []
        for ch in chapters:
            for c in ch.get("claims", []):
                if isinstance(c, dict) and c.get("claim"):
                    claims.append({**c, "chapterRef": ch.get("chapterId", "")})
        citations = [{"id": f"CIT-{i:04d}", "claim": c["claim"], "source": c.get("source", ""),
                      "date": c.get("date", ""), "factLabel": c.get("factLabel", ""),
                      "chapterRef": c.get("chapterRef", "")}
                     for i, c in enumerate(claims, 1)]
        fact_labels = {c["claim"]: c.get("factLabel", "") for c in claims}
        unknowns = [{"id": f"UNK-{i:04d}", "description": u.get("description", ""),
                     "suggestedAction": u.get("suggestedAction", ""),
                     "relatedChapter": u.get("chapterRef", "")}
                    for i, u in enumerate(
                        [dict(unk, chapterRef=ch.get("chapterId", ""))
                         for ch in chapters for unk in ch.get("unknowns", []) if unk], 1)]

        internal_extra = self._internal_sections(claims)
        internal_content = draft + "\n" + internal_extra
        customer = self._filter_customer(draft, claims)
        release_blocked = [g for g in ("G1", "G2", "G3")
                           if g not in (ctx.get("proposalContext", {}).get("gateState", {}).get("passed") or [])]

        customer_version = None
        if customer["content"]:
            customer_version = {
                "content": customer["content"],
                "filteringNotes": customer["notes"],
                "includes": ["F", "A"],
                "excludes": ["C", "B", "H", "P"],
                "releaseBlockedUntil": release_blocked,
            }
        customer_note = ("对客版已生成（仅 F/A 内容），等待 G1/G2/G3 闸门通过后由 GITS 放行。"
                         if customer_version else "对客版未生成（无 F/A 内容）。")

        gate_rec = self._gate_recommendations(ctx, len(unknowns), customer_version)
        return {
            "content": {
                "proposalDraft": draft,
                "internalVersion": {"content": internal_content, "factLabels": fact_labels},
                "customerVersion": customer_version,
                "customerVersionNote": customer_note,
            },
            "citations": citations,
            "unknowns": unknowns,
            "limitations": ["ContextPackage 50KB 上限；行业框架为演示粒度；交互记忆 Top-N 裁剪。"],
            "gateRecommendations": gate_rec,
            "customerVersion": customer_version,
        }

    def _internal_sections(self, claims: list[dict]) -> str:
        risk = [c for c in claims if c.get("factLabel") in ("C", "B")]
        pending = [c for c in claims if c.get("factLabel") == "P"]
        parts = ["\n## 内部判断（不进对客版）\n"]
        parts.append("\n".join(f"- [{c.get('factLabel')}] {c['claim']}（{c.get('chapterRef')}）"
                               for c in risk) or "- 无风险红旗")
        parts.append("\n## 待审批事项（G3 前不得承诺）\n")
        parts.append("\n".join(f"- {c['claim']}" for c in pending) or "- 无")
        return "\n".join(parts)

    def _filter_customer(self, draft: str, claims: list[dict]) -> dict:
        """段落级确定性过滤：段落含任何非 F/A claim 则移除，其余保留。"""
        para_map = {}
        for c in claims:
            for para in draft.split("\n\n"):
                if c.get("claim") and c["claim"] in para:
                    para_map.setdefault(para, []).append(c)
        kept, notes = [], []
        for para in draft.split("\n\n"):
            cs = para_map.get(para, [])
            if any(c.get("factLabel") not in ("F", "A") for c in cs):
                if cs:
                    notes.append(f"移除段落（含非 F/A 断言：{[c.get('factLabel') for c in cs]}）：{para[:40]}…")
                continue
            kept.append(para)
        return {"content": "\n\n".join(kept).strip(), "notes": notes[:20]}

    def _gate_recommendations(self, ctx: dict, unknowns: int,
                              customer_version: dict | None) -> dict:
        gs = ctx.get("proposalContext", {}).get("gateState") or {"passed": ["G0"], "current": "G1"}
        passed = gs.get("passed") or ["G0"]
        current = gs.get("current") or "G1"
        ready = unknowns == 0
        checklist = []
        for g in GATES:
            asset = self.gates.get(f"GATE-BIZ-{g}", {})
            if g in passed:
                checklist.append({"gate": g, "state": "PASSED",
                                  "name": GATE_NAMES.get(g, g)})
            elif g == current:
                # 就绪度：G1 需对客版证据就绪（customer_version 存在）；其余看 unknown 收敛
                blocked = (g == "G1" and customer_version is None)
                state = "BLOCKED" if (blocked or not ready) else "READY_FOR_REVIEW"
                checklist.append({"gate": g, "state": state,
                                  "name": GATE_NAMES.get(g, g),
                                  "checklist": {"must": asset.get("must", []),
                                                "forbidden": asset.get("forbidden", [])}})
            else:
                checklist.append({"gate": g, "state": "PENDING",
                                  "name": GATE_NAMES.get(g, g)})
        return {"currentGate": current, "passedGates": passed,
                "overallReadiness": "READY" if ready else "BLOCKED",
                "checklist": checklist,
                "nextGatePrerequisites": self.gates.get(f"GATE-BIZ-{current}", {}).get("must", [])}

    def _gate_state(self, ctx: dict) -> dict:
        return ctx.get("proposalContext", {}).get("gateState") or {"passed": ["G0"], "current": "G1"}

    def _map_industry(self, industry: str) -> str:
        """"一级-二级" → 行业代码（INDUSTRY-TAXONOMY 映射）。"""
        mapping = {
            "制造业": "MANUFACTURING", "装备制造": "EQUIPMENT", "汽车": "AUTOMOTIVE",
            "能源": "ENERGY", "化工": "ENERGY", "信息技术": "TECHNOLOGY", "软件": "TECHNOLOGY",
            "房地产": "REAL_ESTATE", "基础设施": "INFRA", "建筑": "INFRA",
            "批发零售": "TRADE", "贸易": "TRADE", "物流": "LOGISTICS", "运输": "LOGISTICS",
            "农林牧渔": "AGRICULTURE", "医药": "HEALTHCARE", "健康": "HEALTHCARE",
            "消费": "CONSUMER", "金融": "FINANCE", "公共服务": "PUBLIC", "采矿": "MINING",
        }
        for key, code in mapping.items():
            if key in (industry or ""):
                return code
        return "OTHER"

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        m = re.search(r"\{[\s\S]*\}", text or "")
        candidate = m.group(0) if m else (text or "").strip()
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _aggregate(calls: list[dict]) -> dict:
        return {
            "model": calls[0]["model"] if calls else "library",
            "inputTokens": sum(c.get("inputTokens", 0) for c in calls),
            "outputTokens": sum(c.get("outputTokens", 0) for c in calls),
            "latencyMs": round(sum(c.get("latencyMs", 0) for c in calls), 1),
        }
