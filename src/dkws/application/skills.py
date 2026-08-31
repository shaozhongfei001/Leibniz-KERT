"""客户经理持续经营 Skill 运行平台（DKWS 工程内能力）。

依据《改造-客户经理持续经营Skill-v2-deepseek-harness端需求详细设计.md》与
《改造-客户经理持续经营Skill-v2-当前项目端需求详细设计.md》实现：
- 两个独立 Skill：外联脚本 / 会面脚本（R1 拜访报告已于 2026-08-21 下线移除）；
- 统一执行契约：requestId / status(ok|skill_error) / data / assemblyTrace / modelCalls；
- 治理：fail-closed、requestId 幂等、日志脱敏、机器事实优先；
- 模型调用走可插拔 LLM 适配器（§6.3），未配置外部模型时确定性适配器端到端（§1.6）；
- DKWS 知识协作：执行前经本平台知识服务检索客户片段，注入知识上下文与证据引用（fail-open）。

技能资产：`skills/customer-engagement/`（SKILL.md 族 + 两个子 skill）。
HTTP 端点：由 `api/server.py` 暴露 `POST /api/skill/execute` 与 `GET /api/skill/health`。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import timeutil
from ..infrastructure.adapters import llm as llm_mod
from ..infrastructure.classification import detect_value_patterns, redact_for_llm

_log = logging.getLogger(__name__)

IDEMPOTENCY_TTL_S = 600
#: Runtime Store 中 Skill 执行幂等记录的作用域（M2.3）
IDEMPOTENCY_SCOPE = "skill_execute"
SKILL_DIR = "skills/customer-engagement"


@dataclass
class SkillInfo:
    skill_id: str
    name: str
    version: str


@dataclass
class SkillExecuteResult:
    request_id: str
    status: str  # ok / skill_error
    data: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    assembly_trace: list = field(default_factory=list)
    model_calls: list = field(default_factory=list)
    skill_id: str = ""

    def as_dict(self) -> dict:
        return {
            "requestId": self.request_id,
            "status": self.status,
            "data": self.data,
            "errors": self.errors,
            "assemblyTrace": self.assembly_trace,
            "modelCalls": self.model_calls,
        }


def _is_external_adapter(adapter) -> bool:
    """判断适配器是否会把提示词发往**外部**服务。

    按类型判定而非字符串比较：``DeterministicLlmAdapter`` 与库内检索不出网，
    对其脱敏只会降低结果质量；仅 OpenAI 兼容适配器需要出站脱敏。
    """
    return isinstance(adapter, llm_mod.OpenAiCompatibleLlmAdapter)


class SkillExecutionService:
    def __init__(self, workspace: Path | None = None,
                 knowledge: object | None = None,
                 skill_packages: Path | str | None = None,
                 customer_knowledge_service_id: str = "customer_knowledge",
                 runtime_store: object | None = None,
                 profile: str | None = None,
                 llm_redaction: bool | None = None):
        """knowledge: 兼容参数（历史 product_knowledge 检索），v1.3 起取数走客户知识库。
        customer_knowledge_service_id: 客户知识服务投影（v1.3 数据所有权：按 customerId 取数）。
        skill_packages: 可选外部 Skill 包根目录（含 <skill>/SKILL.md + references/output-schema.md），
        动态注册为可执行 Skill（通用契约 executor）。
        runtime_store: 可选 SQLite Runtime Store（M2.3）；提供时幂等记录额外持久化，
        使进程重启后仍可按 requestId 复放，内存缓存继续作为一级快路径。
        llm_redaction: 是否在提示词出站前脱敏（M2.9）。缺省读
        ``DKWS_LLM_REDACTION``，**默认开启**——客户数据进入外部模型属重大
        合规风险（独立评审 L659），故采取安全默认；仅对外部适配器生效。
        profile: 运行 profile（``dev``/``prod``）。M2.4 起生产 profile 下
        ``execute_async`` 强制要求启用 Runtime Store，否则拒绝异步执行，
        以免进程崩溃丢任务（Owner 决策 2026-08-27）。缺省时读
        ``DKWS_PROFILE`` 环境变量。"""
        self.workspace = Path(workspace) if workspace else None
        self.knowledge = knowledge
        self._idem: dict[str, tuple[SkillExecuteResult, float]] = {}
        self._store = runtime_store
        self._profile = (profile if profile is not None
                         else os.environ.get("DKWS_PROFILE", "dev")).strip().lower()
        if llm_redaction is None:
            raw = os.environ.get("DKWS_LLM_REDACTION", "").strip().lower()
            # 安全默认：未显式关闭即启用
            llm_redaction = raw not in ("0", "false", "no", "off")
        self._llm_redaction_enabled = bool(llm_redaction)
        self._evidence_ts: dict[str, str] = {}  # customerId -> 最新 evidenceTimestamp（无新证据策略）
        self._packages: dict[str, dict] = {}
        if skill_packages:
            self._load_packages(Path(skill_packages))
        # v1.3：客户知识取数层（GITS 只传 customerId，知识全在 DKWS）
        from ..application.customer_knowledge import CustomerKnowledgeProvider
        from ..application.customer_knowledge import KI_ITEMS as _KI_ITEMS_MOD
        self._KI_ITEMS: list[tuple[str, str]] = _KI_ITEMS_MOD
        self._ckp = CustomerKnowledgeProvider(self.workspace,
                                              service_id=customer_knowledge_service_id)
        self._sp20 = None  # SP-20 执行器（懒加载）
        self._sp21 = None  # SP-21 执行器（懒加载）

    # ---------------- 外部 Skill 包加载（SKILL.md + output-schema.md）----------------

    def _load_packages(self, root: Path) -> None:
        import re as _re

        for skill_dir in sorted(root.iterdir()) if root.is_dir() else []:
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            text = skill_md.read_text(encoding="utf-8")
            fm = _parse_front_matter(text)
            name = str(fm.get("name", skill_dir.name)).strip()
            version = str(fm.get("version", "1.0.0")).strip().lstrip("v")
            description = str(fm.get("description", "")).strip()
            body = _strip_front_matter(text)
            # output-schema 提取 JSON 示例（生成约束）
            schema_md = skill_dir / "references" / "output-schema.md"
            schema_hint = ""
            if schema_md.is_file():
                m = _re.search(r"```json\n([\s\S]*?)\n```", schema_md.read_text(encoding="utf-8"))
                if m:
                    schema_hint = m.group(1)[:2000]
            self._packages[name] = {
                "name": name, "version": version, "description": description,
                "instruction": (body or "")[:3000],
                "schema_hint": schema_hint,
            }

    # ---------------- 注册表 ----------------

    def registry(self) -> list[SkillInfo]:
        base = [
            SkillInfo("skill-customer-outreach-script", "外联脚本", "1.0.0"),
            SkillInfo("skill-customer-meeting-script", "会面脚本", "1.0.0"),
            SkillInfo("skill-customer-previsit-report", "R1 拜访报告", "1.0.0"),
            SkillInfo("SP-20", "对公客户服务建议书生成", "1.0.0"),
            SkillInfo("SP-21", "交互记忆抽取", "1.0.0"),
        ]
        for name, p in self._packages.items():
            base.append(SkillInfo(name, p.get("name", name), p.get("version", "1.0.0")))
        return base

    def _info(self, skill_id: str) -> SkillInfo | None:
        for s in self.registry():
            if s.skill_id == skill_id:
                return s
        return None

    # ---------------- 主流程 ----------------

    def execute(self, skill_id: str, request_id: str | None,
                request: dict | None) -> SkillExecuteResult:
        request = request or {}
        request_id = request_id or f"req-{int(time.time() * 1000)}"
        trace: list[dict] = [
            {"phase": "resolve", "status": "ok",
             "message": f"skillId={skill_id} requestId={request_id}"},
        ]

        # 幂等（D3）：内存快路径 → Runtime Store 持久层（M2.3）
        hit_result = self._idem_lookup(request_id)
        if hit_result is not None:
            trace.append({"phase": "idempotency", "status": "ok", "message": "命中缓存（NO_OP）"})
            return SkillExecuteResult(
                request_id=request_id, status=hit_result.status, data=hit_result.data,
                errors=hit_result.errors, assembly_trace=trace + hit_result.assembly_trace,
                model_calls=hit_result.model_calls, skill_id=hit_result.skill_id)

        info = self._info(skill_id)
        if info is None:
            trace.append({"phase": "resolve", "status": "failed", "message": "未知 skillId"})
            return self._finish(SkillExecuteResult(
                request_id=request_id, status="skill_error",
                errors=[{"code": "UNKNOWN_SKILL", "message": f"未知 skillId: {skill_id}"}],
                assembly_trace=trace, skill_id=skill_id))

        # 无新证据策略（仅 R1，v1.3 保留）：evidenceTimestamp 未传或未更新 → exit_policy_no_new_evidence
        if skill_id == "skill-customer-previsit-report":
            ts = (request or {}).get("evidenceTimestamp")
            customer = (request or {}).get("customerId") or ""
            if not ts:
                trace.append({"phase": "evidence", "status": "blocked",
                              "message": "未提供 evidenceTimestamp，无新证据策略拦截（exit_policy_no_new_evidence）"})
                return self._finish(SkillExecuteResult(
                    request_id=request_id, status="exit_policy_no_new_evidence",
                    assembly_trace=trace, skill_id=skill_id))
            latest = self._evidence_ts.get(customer)
            if latest is not None and str(ts) <= str(latest):
                trace.append({"phase": "evidence", "status": "blocked",
                              "message": "evidenceTimestamp 未更新，无新证据策略拦截（exit_policy_no_new_evidence）"})
                return self._finish(SkillExecuteResult(
                    request_id=request_id, status="exit_policy_no_new_evidence",
                    assembly_trace=trace, skill_id=skill_id))
            self._evidence_ts[customer] = str(ts)

        trace.append({"phase": "validate", "status": "ok", "message": "请求校验通过"})

        # 执行（fail-closed）
        try:
            run = self._executor(skill_id)
            data, model_call = run(request, trace)
            trace.append({"phase": "compose", "status": "ok", "message": "结果组装完成"})
            result = SkillExecuteResult(
                request_id=request_id, status="ok", data=data,
                assembly_trace=trace, model_calls=[model_call], skill_id=skill_id)
        except Exception as exc:
            trace.append({"phase": "compose", "status": "failed",
                          "message": str(exc)})
            result = SkillExecuteResult(
                request_id=request_id, status="skill_error",
                errors=[{"code": "SKILL_EXECUTION_FAILED", "message": str(exc)}],
                assembly_trace=trace, skill_id=skill_id)
        return self._finish(result)

    def get_result(self, request_id: str) -> SkillExecuteResult | None:
        """按 requestId 取回已执行结果（幂等缓存，TTL 内有效），用于报告渲染。

        查找顺序：内存缓存 → Runtime Store（若启用），后者支持跨进程重启复放。
        """
        return self._idem_lookup(request_id)

    def _idem_lookup(self, request_id: str) -> SkillExecuteResult | None:
        """在内存与 Runtime Store 中查找幂等结果。"""
        hit = self._idem.get(request_id)
        if hit:
            return hit[0]
        if self._store is None or not request_id:
            return None
        record = self._store.lookup(IDEMPOTENCY_SCOPE, request_id)
        if record is None or not record.response:
            return None
        restored = self._result_from_payload(request_id, record.response)
        self._idem[request_id] = (restored, time.monotonic())
        return restored

    @staticmethod
    def _result_from_payload(request_id: str, payload: dict) -> SkillExecuteResult:
        """把持久化的响应载荷还原为 :class:`SkillExecuteResult`。"""
        return SkillExecuteResult(
            request_id=request_id,
            status=str(payload.get("status", "ok")),
            data=payload.get("data") or {},
            errors=payload.get("errors") or [],
            assembly_trace=payload.get("assemblyTrace") or [],
            model_calls=payload.get("modelCalls") or [],
            skill_id=str(payload.get("skillId", "")))

    def execute_async(self, skill_id: str, request_id: str | None,
                      request: dict | None) -> str:
        """异步技能作业（SP-20 长任务）：创建 SKILL job 并返回 job_id。

        两种执行模式：

        - **持久化模式（M2.4，生产唯一允许）**：注入 ``runtime_store`` 时仅入队，
          由独立 Worker 进程（``scripts/run_worker.py``）领取执行。
          进程崩溃后 Job 不丢失，可被 lease 回收机制重新调度。
        - **线程模式（仅 dev 兼容）**：未注入 Store 时沿用后台线程立即执行。
          该模式下**进程退出即丢任务**，仅适用于开发环境。

        生产强制约束（Owner 决策 2026-08-27）：
            ``profile=prod`` 且未启用 Runtime Store 时**拒绝异步执行**，
            抛出 :class:`ServiceNotReadyError`（HTTP 503），
            **禁止**回退到线程模式，以免生产环境进程崩溃丢任务。

        Returns:
            job_id；轮询 GET /v1/jobs/{job_id}（完成时含 skill_result）。

        Raises:
            ServiceNotReadyError: 生产 profile 下未启用 Runtime Store。
            ValueError: 未配置工作区。
        """
        import threading

        from ..domain.errors import ServiceNotReadyError
        from ..infrastructure.fs import WorkspaceWriter
        from .jobs import JobController

        if self.workspace is None:
            raise ValueError("异步执行需要工作区（workspace 未配置）")
        if self._store is None and self._profile == "prod":
            raise ServiceNotReadyError(
                "生产 profile 下异步执行必须启用 Runtime Store："
                "线程模式在进程崩溃时会丢任务。请设置 "
                "DKWS_RUNTIME_STORE_ENABLED=true 并启动 Worker "
                "（scripts/run_worker.py），或改用同步执行。",
                details={"profile": self._profile, "runtime_store_enabled": False,
                         "remediation": "DKWS_RUNTIME_STORE_ENABLED=true"})

        writer = WorkspaceWriter(self.workspace)
        idem = request_id or f"req-{int(time.time() * 1000)}"
        job = JobController(self.workspace, writer, job_type="SKILL",
                            requested_by="api", idempotency_key=idem,
                            runtime_store=self._store)

        if self._store is not None:
            # 持久化模式：把执行入参写入权威表，交由独立 Worker 进程领取。
            # Job 保持 PENDING（由 JobController 初始登记），不在此处 start()：
            # 状态推进的所有权归 Worker（claim → RUNNING → COMPLETED/RETRYING）。
            self._store.set_job_payload(job.job_id, {
                "skillId": skill_id,
                "requestId": request_id,
                "request": request or {},
            })
            return job.job_id

        job.start()

        def _run() -> None:
            try:
                result = self.execute(skill_id, request_id, request)
                payload = result.as_dict()
                if isinstance(payload.get("data"), dict):
                    payload["data"].setdefault(
                        "reportUrl", f"/api/skill/report/{payload.get('requestId', '')}")
                res_file = self.workspace / "90_control" / "jobs" / job.job_id / "result.json"
                res_file.parent.mkdir(parents=True, exist_ok=True)
                res_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                job.finish(output_refs=[], input_count=1, output_count=1)
            except Exception as exc:
                job.fail("SKILL_EXECUTION_FAILED", str(exc))

        threading.Thread(target=_run, daemon=True).start()
        return job.job_id

    def _finish(self, result: SkillExecuteResult) -> SkillExecuteResult:
        """写入幂等缓存（内存 + 可选 Runtime Store）并做容量回收。"""
        if result.request_id:
            self._idem[result.request_id] = (result, time.monotonic())
            if len(self._idem) > 500:
                now = time.monotonic()
                for k, (_, ts) in list(self._idem.items()):
                    if now - ts > IDEMPOTENCY_TTL_S:
                        del self._idem[k]
            self._persist_idem(result)
        return result

    def _persist_idem(self, result: SkillExecuteResult) -> None:
        """把结果写入 Runtime Store；持久化失败不影响主流程（best-effort）。"""
        if self._store is None:
            return
        payload = result.as_dict()
        payload["skillId"] = result.skill_id
        digest = hashlib.sha256(
            json.dumps({"skillId": result.skill_id}, sort_keys=True,
                       ensure_ascii=False).encode("utf-8")).hexdigest()
        try:
            existing = self._store.lookup(IDEMPOTENCY_SCOPE, result.request_id)
            if existing is None:
                self._store.remember(IDEMPOTENCY_SCOPE, result.request_id, digest,
                                     response=payload,
                                     ttl_seconds=IDEMPOTENCY_TTL_S)
            else:
                self._store.complete(IDEMPOTENCY_SCOPE, result.request_id, payload)
        except Exception:
            _log.warning("幂等记录写入失败（request_id=%s）", result.request_id, exc_info=True)
            return

    # ---------------- 模型与解析 ----------------

    def _call_model(self, kind: str, system: str, user: str,
                    trace: list[dict]) -> tuple[str, dict]:
        """调用模型适配器；出站前按 M2.9 策略脱敏提示词。

        脱敏在此收口的理由：``_call_model`` 是**唯一**的模型出站点，
        客户数据进入外部模型属重大合规风险（独立评审 L659）。
        脱敏只作用于**发送出去的文本**，内部计算与产物仍用明文，
        因此不影响业务逻辑与既有报告内容。

        仅当适配器为**外部**模型时脱敏：本地/库内适配器（``library`` 等）
        不出网，脱敏反而会降低结果质量。
        """
        adapter = llm_mod.create_llm_adapter(kind)
        outbound_system, outbound_user = system, user
        if self._llm_redaction_enabled and _is_external_adapter(adapter):
            outbound_system = redact_for_llm(system)
            outbound_user = redact_for_llm(user)
            hits = sorted(set(detect_value_patterns(system)
                              + detect_value_patterns(user)))
            if hits:
                trace.append({"phase": "llm_redaction", "status": "ok",
                              "message": f"出站提示词已脱敏：{','.join(hits)}"})
        try:
            res = adapter.complete(outbound_system, outbound_user)
        except Exception as exc:
            trace.append({"phase": "model", "status": "failed", "message": str(exc)})
            raise
        trace.append({"phase": "model", "status": "ok", "message": "模型调用完成"})
        return res.text, {
            "model": res.model_id,
            "inputTokens": res.input_tokens,
            "outputTokens": res.output_tokens,
            "latencyMs": res.latency_ms,
        }

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
    def _as_text(value) -> str:
        """自由文本字段（如 knowledgeContext）归一为字符串：dict/list → JSON，其余按 str。"""
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    # ---------------- v1.3 客户知识取数（数据所有权在 DKWS） ----------------

    def _load_ki(self, customer_id: str, trace: list[dict]) -> dict:
        """按 customerId 从客户知识库取 KI 片段（{kiId: {title, content}}）。

        dkws 阶段反映检索路径是否可用；evidence 的 ok/skipped 只由库里是否取到该 KI 决定。
        """
        if self._ckp is None or not self._ckp.available:
            trace.append({"phase": "dkws", "status": "skipped",
                          "message": "DKWS 客户知识库未接入（skipped）"})
            return {}
        try:
            ki = self._ckp.ki_map(customer_id)
            trace.append({"phase": "dkws", "status": "ok",
                          "message": f"DKWS 客户知识库检索完成（{customer_id} 命中 {len(ki)} 条 KI）"})
            return ki
        except Exception as exc:
            trace.append({"phase": "dkws", "status": "skipped",
                          "message": f"DKWS 客户知识库不可用（fail-open）：{exc}"})
            return {}

    def _ki_context(self, ki: dict, only: list[str] | None = None) -> str:
        """命中的 KI 原文拼接为模型上下文（按契约顺序）。"""
        parts = []
        for kid, title in self._KI_ITEMS:
            if kid not in ki:
                continue
            if only and kid not in only:
                continue
            parts.append(f"【{kid} {title}】\n{ki[kid]['content']}")
        return "\n\n".join(parts)

    def _ki_sections(self, ki: dict) -> list[dict]:
        """每个命中的 KI 出一节（heading 含 KI 编号与稳定标题，content 为库中原文）。"""
        return [{"heading": f"{kid} {ki[kid]['title']}", "content": ki[kid]["content"]}
                for kid, _ in self._KI_ITEMS if kid in ki]

    # ---------------- Skill 执行器 ----------------

    def _executor(self, skill_id: str):
        if skill_id == "SP-20":
            # v1.4：对公客户服务建议书生成（HYBRID：装配 + 逐章生成 + 规则校验 + 双版本过滤）
            return self._run_service_proposal
        if skill_id == "SP-21":
            # Phase 3：交互记忆抽取（LLM + 确定性比对；DKWS 不存记忆）
            return self._run_interaction_memory
        if skill_id in self._packages:
            if skill_id == "bank-front-supply-chain-graph":
                # v1.3：供应链图谱从客户知识库构建（不依赖 GITS 传 markdown）
                return self._run_supply_chain

            pkg = self._packages[skill_id]

            def run_pkg(request: dict, trace: list[dict]) -> tuple[dict, dict]:
                """外部 Skill 包通用执行：SKILL.md 指令 + output-schema 约束 + 请求输入。"""
                instruction = pkg.get("instruction") or "按技能说明执行。"
                schema_hint = pkg.get("schema_hint") or ""
                system = (
                    "你是银行对公客户经理前中台技能助手。执行以下技能指令。\n"
                    "纪律：只使用输入事实，不臆造；输出必须为合法 JSON；"
                    "无依据处如实标注（如'待核实'）。\n"
                    f"【技能指令】\n{instruction[:2500]}\n"
                    + (f"【输出 JSON 结构参考】\n{schema_hint}\n" if schema_hint else "")
                )
                user = json.dumps(request.get("input", request), ensure_ascii=False)
                text, model_call = self._call_model("generic", system, user, trace)
                data = self._parse_json(text)
                if not data:
                    trace.append({"phase": "parse", "status": "failed",
                                  "message": "输出结构校验失败"})
                    raise ValueError("输出结构校验失败（fail-closed）")
                return {"skillId": skill_id, "result": data}, model_call

            return run_pkg
        return {
            "skill-customer-outreach-script": self._run_outreach,
            "skill-customer-meeting-script": self._run_meeting,
            "skill-customer-previsit-report": self._run_previsit,
        }[skill_id]

    # ---------------- 知识组装轨迹（KI 级，供 gits 控制台展示）----------------

    @staticmethod
    def _trace_knowledge_map(trace: list[dict], map_id: str, task: str) -> None:
        """进入知识地图步骤。"""
        trace.append({"phase": "evidence", "status": "ok",
                      "message": f"进入知识地图 {map_id}，任务 {task}"})

    @staticmethod
    def _trace_ki(trace: list[dict], ki_id: str, name: str, ok: bool) -> None:
        """逐知识条目取数步骤；v1.3：ok/skipped 只反映 DKWS 知识库对该客户+KI 是否取到数。"""
        if ok:
            trace.append({
                "phase": "evidence", "status": "ok", "kiId": ki_id,
                "message": f"读取知识条目 {ki_id}（{name}），取数完成：DKWS 知识库命中",
            })
        else:
            trace.append({
                "phase": "evidence", "status": "skipped", "kiId": ki_id,
                "message": f"{ki_id}（{name}）知识库无该客户/KI 数据，标记待核实（skipped）",
            })

    # ---------------- 外联脚本（v1.3：只按 customerId 从平台库取数） ----------------

    def _run_outreach(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        customer_id = request.get("customerId") or ""
        self._trace_knowledge_map(trace, "KM-CORP-RM-OUTREACH", "OUTREACH_PREPARATION")
        ki = self._load_ki(customer_id, trace)
        self._trace_ki(trace, "KI-009", "企业客户基本信息", "KI-009" in ki)
        self._trace_ki(trace, "KI-FRONT-004", "事实承诺事项 / 沟通话术", "KI-FRONT-004" in ki)
        self._trace_ki(trace, "KI-FRONT-006", "产品候选组合", "KI-FRONT-006" in ki)
        context = self._ki_context(ki)
        system = ("你是资深客户经理的外联脚本助手。基于客户知识库取数的客户事实生成外联脚本。"
                  "纪律：只使用知识库事实，不得臆造；输出必须为合法 JSON。"
                  '输出 JSON 结构：{"scriptTitle":"string","sections":[{"heading":"string","content":"string"}],'
                  '"callObjectives":["string"],"keyMessages":["string"]}')
        user = json.dumps({
            "customerId": customer_id,
            "knowledgeBase": context,
            "visitObjective": request.get("visitObjective"),
        }, ensure_ascii=False)
        text, model_call = self._call_model("outreach", system, user, trace)
        data = self._parse_json(text)
        if not data or not isinstance(data.get("sections"), list):
            trace.append({"phase": "parse", "status": "failed", "message": "输出结构校验失败"})
            raise ValueError("输出结构校验失败（fail-closed）")
        return {
            "scriptTitle": data.get("scriptTitle"),
            "sections": data["sections"],
            "callObjectives": data.get("callObjectives", []),
            "keyMessages": data.get("keyMessages", []),
            "evidenceRefs": [{"id": kid, "summary": f"{kid}（DKWS 知识库）"} for kid in ki],
        }, model_call

    # ---------------- 会面脚本（v1.3：只按 customerId 从平台库取数） ----------------

    def _run_meeting(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        customer_id = request.get("customerId") or ""
        self._trace_knowledge_map(trace, "KM-CORP-RM-MEETING", "MEETING_PREPARATION")
        ki = self._load_ki(customer_id, trace)
        self._trace_ki(trace, "KI-009", "企业客户基本信息", "KI-009" in ki)
        self._trace_ki(trace, "KI-FRONT-004", "事实承诺事项 / 沟通话术", "KI-FRONT-004" in ki)
        self._trace_ki(trace, "KI-FRONT-005", "KYC 信息缺口", "KI-FRONT-005" in ki)
        self._trace_ki(trace, "KI-FRONT-006", "产品候选组合", "KI-FRONT-006" in ki)
        context = self._ki_context(ki)
        system = ("你是资深客户经理的会面脚本助手。基于客户知识库取数的客户事实生成会面脚本。"
                  "纪律：敏感点如实呈现，不回避不臆造；输出必须为合法 JSON。"
                  '输出 JSON 结构：{"agenda":[{"time":"string","topic":"string"}],'
                  '"talkingPoints":[{"title":"string","detail":"string"}],'
                  '"sensitivePoints":["string"],"actionItems":["string"]}')
        user = json.dumps({
            "customerId": customer_id,
            "knowledgeBase": context,
            "visitObjective": request.get("visitObjective"),
        }, ensure_ascii=False)
        text, model_call = self._call_model("meeting", system, user, trace)
        data = self._parse_json(text)
        if not data or not isinstance(data.get("agenda"), list):
            trace.append({"phase": "parse", "status": "failed", "message": "输出结构校验失败"})
            raise ValueError("输出结构校验失败（fail-closed）")
        return {
            "agenda": data["agenda"],
            "talkingPoints": data.get("talkingPoints", []),
            "sensitivePoints": data.get("sensitivePoints", []),
            "actionItems": data.get("actionItems", []),
            "evidenceRefs": [{"id": kid, "summary": f"{kid}（DKWS 知识库）"} for kid in ki],
        }, model_call

    # ---------------- R1 访前报告（v1.3：evidence 改源 + sections 按 KI 出章） ----------------

    def _run_previsit(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        customer_id = request.get("customerId") or ""
        self._trace_knowledge_map(trace, "KM-CORP-RM-PREVISIT", "PRE_VISIT_PREPARATION")
        ki = self._load_ki(customer_id, trace)
        for kid, name in self._KI_ITEMS:
            self._trace_ki(trace, kid, name, kid in ki)

        context = self._ki_context(ki)
        system = ("你是资深客户经理的 R1 访前报告助手。基于客户知识库取数生成拜访报告。"
                  "纪律：只使用知识库事实，不臆造；输出必须为合法 JSON。"
                  '输出 JSON 结构：{"reportTitle":"string","executiveSummary":"string",'
                  '"evidenceRefs":[{"id":"string","summary":"string"}]}')
        user = json.dumps({
            "customerId": customer_id,
            "knowledgeBase": context,
            "visitObjective": request.get("visitObjective"),
            "evidenceTimestamp": request.get("evidenceTimestamp"),
        }, ensure_ascii=False)
        text, model_call = self._call_model("previsit", system, user, trace)
        data = self._parse_json(text)
        if not data or not data.get("executiveSummary"):
            trace.append({"phase": "parse", "status": "failed", "message": "输出结构校验失败"})
            raise ValueError("输出结构校验失败（fail-closed）")
        refs = (data.get("evidenceRefs") or []) + \
            [{"id": kid, "summary": f"{ki[kid]['title']}（DKWS 知识库）"} for kid, _ in self._KI_ITEMS if kid in ki]
        return {
            "reportTitle": data.get("reportTitle"),
            "executiveSummary": data["executiveSummary"],
            # 每个命中的 KI 必须有一节：heading 含 KI 编号与稳定标题，content 为库中原文
            "sections": self._ki_sections(ki),
            "evidenceRefs": refs,
        }, model_call

    # ---------------- 供应链图谱（v1.3：只认 customerId，从 DKWS 库构建） ----------------

    def _run_supply_chain(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        customer_id = request.get("customerId") or ""
        ki = self._load_ki(customer_id, trace)
        self._trace_ki(trace, "KI-FRONT-001", "公司供应链图谱", "KI-FRONT-001" in ki)
        self._trace_ki(trace, "KI-FRONT-002", "产业链八维研判", "KI-FRONT-002" in ki)
        self._trace_ki(trace, "KI-FRONT-003", "行内变动行为", "KI-FRONT-003" in ki)

        if self._ckp is None or not self._ckp.available:
            graph = {"nodes": [], "edges": [], "buildStatus": "partial"}
        else:
            graph = self._ckp.supply_chain(customer_id)
        interp = self._ckp.interpretation(customer_id, graph) if self._ckp else {}

        result = {
            "schemaVersion": "1.0",
            "skillId": "SK-FRONT-002",
            "customerId": customer_id,
            "generatedAt": timeutil.ts_utc(),
            "buildStatus": graph.get("buildStatus", "partial"),
            "nodes": graph.get("nodes", []),
            "edges": graph.get("edges", []),
            "interpretation": interp,
        }
        return {"skillId": "bank-front-supply-chain-graph", "result": result}, {
            "model": "library", "inputTokens": 0, "outputTokens": 0, "latencyMs": 0.0,
        }

    # ---------------- SP-20 服务建议书（v1.4） ----------------

    def _run_service_proposal(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        from ..application.service_proposal import ServiceProposalExecutor

        if self._sp20 is None:
            self._sp20 = ServiceProposalExecutor()
        return self._sp20.execute(request, trace)

    def _run_interaction_memory(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        from ..application.interaction_memory import InteractionMemoryExecutor

        if self._sp21 is None:
            self._sp21 = InteractionMemoryExecutor()
        return self._sp21.execute(request, trace)

    def sp20_gate_checklist(self, customer_id: str = "") -> list[dict]:
        """GATE-BIZ-* 闸门清单资产（权威清单在 DKWS 资产，推进权威在 GITS）。"""
        from ..application.service_proposal import ServiceProposalExecutor

        if self._sp20 is None:
            self._sp20 = ServiceProposalExecutor()
        return self._sp20.gate_checklist(customer_id)

    def record_gate_audit(self, customer_id: str, gate: str, decision: str,
                          decided_by: str, reason: str = "") -> dict:
        """业务闸门决策镜像（非权威，权威在 GITS）；追加 90_control/audit/gates.jsonl。

        启用 Runtime Store 时（M2.3）同步写入 ``gate_audit`` 表，便于按客户查询；
        JSONL 仍为可追加审计留痕，二者互为补充，均非业务权威。
        """
        if self.workspace is None:
            raise ValueError("工作区未配置（无法记录审计镜像）")
        rec = {"customerId": customer_id, "gate": gate, "decision": decision,
               "decidedBy": decided_by, "reason": reason,
               "recordedAt": timeutil.ts_utc()}
        d = self.workspace / "90_control" / "audit"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "gates.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if self._store is not None:
            try:
                self._store.record_gate(customer_id, gate, decision, decided_by, reason)
            except Exception:
                _log.warning("门控记录持久化失败（customer=%s, gate=%s）", customer_id, gate, exc_info=True)
                pass
        return {"recorded": True, **rec}


# ---------------- front matter 解析辅助 ----------------

def _parse_front_matter(text: str) -> dict:
    import yaml

    if not text.startswith("---"):
        return {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _strip_front_matter(text: str) -> str:
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    return text[m.end():] if m else text
