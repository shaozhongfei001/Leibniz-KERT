"""文档解析、规范化与稳定切片（FR-DOC-001~005、规格 §11.5、§9.2~9.4）。"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import hashing as hashing_mod, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import UsageError
from ..infrastructure import adapters, locks as locks_mod, markdown
from ..infrastructure.fs import WorkspaceWriter
from .jobs import JobController

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|")

DEFAULT_CHUNK_POLICY = "chunk/v1"
DEFAULT_MAX_CHARS = 800


@dataclass
class Segment:
    segment_id: str
    document_id: str
    segment_type: str
    heading_path: list[str]
    page_from: int | None
    page_to: int | None
    sequence: int
    char_start: int
    char_end: int
    content: str
    content_sha256: str
    previous_segment_id: str | None
    next_segment_id: str | None


@dataclass
class ParseDocResult:
    run_id: str
    job_id: str
    document_ids: list[str] = field(default_factory=list)
    segment_count: int = 0
    warnings: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)


def segment_id_for(document_id: str, heading_path: list[str],
                   segment_type: str, content: str) -> str:
    """稳定 segment_id（规格 §9.4 推荐算法）。"""
    raw = f"{document_id}|{'/'.join(heading_path)}|{segment_type}|{content}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    b32 = base64.b32encode(digest).decode("ascii").rstrip("=")
    return "SEG-" + b32[:20]


def document_id_for(batch_id: str, source_path: str) -> str:
    raw = f"{batch_id}|{source_path}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    b32 = base64.b32encode(digest).decode("ascii").rstrip("=")
    return "DOC-" + b32[:8]


class DocumentParserService:
    def __init__(self, workspace: Path, *, owner: str = "svc_parser",
                 dry_run: bool = False):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run

    def parse(self, domain: str, batch_id: str, *,
              chunk_policy: str = DEFAULT_CHUNK_POLICY,
              max_chars: int = DEFAULT_MAX_CHARS,
              idempotency_key: str | None = None) -> ParseDocResult:
        ids.validate_domain(domain)
        ids.validate_id(batch_id, "batch_id")
        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        batch_rel = f"01_raw/{domain}/batch={batch_id}"
        idem_key = idempotency_key or f"{batch_id}:parse"

        if self.dry_run:
            run_id = ids.new_run_id("PARSE")
            base = f"02_work/{domain}/run={run_id}"
            return ParseDocResult(run_id=run_id, job_id="", plan=[
                f"{base}/documents/DOC-XXXX/DOCUMENT.md",
                f"{base}/documents/DOC-XXXX/NORMALIZED.md",
                f"{base}/segments/DOC-XXXX/SEG-XXXX.md",
            ])

        with locks_mod.WorkspaceLock(self.ws, f"domain:{domain}",
                                     job_id=f"JOB-PARSE-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            job = JobController(self.ws, writer, job_type="PARSE_DOC",
                                requested_by=self.owner,
                                idempotency_key=idem_key,
                                component="doc_parser")
            if job.noop:
                return ParseDocResult(run_id="", job_id=job.job_id)
            job.start()
            job.logger.info("PARSE_START", "文档解析开始",
                            domain=domain, batch_id=batch_id)
            try:
                manifest = self._load_manifest(batch_rel)
                doc_files = [f for f in manifest["files"] if f.get("role") == "DOCUMENT"]
                if not doc_files:
                    raise UsageError(f"批次 {batch_id} 中没有 role=DOCUMENT 的文件")
                job.update(progress=15, log_code="PARSE_MANIFEST", log_message="清单校验通过")

                run_id = self._allocate_run_id(domain)
                base = f"02_work/{domain}/run={run_id}"
                all_segments: list[Segment] = []
                doc_ids: list[str] = []
                warnings: list[str] = []
                for idx, df in enumerate(doc_files):
                    src_rel = f"{batch_rel}/{df['path']}"
                    actual = hashing_mod.sha256_file(writer.resolve(src_rel))
                    if actual != df["sha256"]:
                        raise UsageError(f"文件哈希不一致: {df['path']}（G0 门禁失败）")
                    doc_id = document_id_for(batch_id, df["path"])
                    doc_ids.append(doc_id)
                    parsed = self._parse_document(writer.resolve(src_rel),
                                                  df["media_type"], df["path"])
                    warnings.extend(f"{df['path']}: {w}" for w in parsed.warnings)
                    job.logger.info("PARSE_DOC", "文档解析完成",
                                    document_id=doc_id, source=df["path"],
                                    pages=len(parsed.pages))
                    self._write_document_md(doc_id, df, src_rel, parsed,
                                            domain, batch_id, run_id, writer)
                    normalized = self._build_normalized(doc_id, parsed, run_id)
                    writer.write_text(
                        f"{base}/documents/{doc_id}/NORMALIZED.md", normalized)
                    segs = chunk_document(parsed, doc_id, chunk_policy, max_chars)
                    for seg in segs:
                        self._write_segment_md(seg, base, chunk_policy, writer)
                    all_segments.extend(segs)
                    job.update(progress=30 + int(60 * (idx + 1) / len(doc_files)),
                               log_code="PARSE_CHUNK",
                               log_message=f"切片完成 {len(segs)} 段")

                errors = self._verify_segments(all_segments)
                if errors:
                    raise UsageError("切片校验失败: " + "; ".join(errors[:5]))

                self._write_lineage(domain, batch_id, run_id, job, writer, doc_ids)
                out_refs = [{"path": f"{base}/documents/{d}/DOCUMENT.md",
                             "version": "1.0",
                             "content_hash": hashing_mod.sha256_hex(d)}
                            for d in doc_ids]
                job.finish(output_refs=out_refs, input_count=len(doc_files),
                           output_count=len(doc_ids) + len(all_segments),
                           warning_count=len(warnings),
                           quality_summary={"documents": len(doc_ids),
                                            "segments": len(all_segments)})
                return ParseDocResult(run_id=run_id, job_id=job.job_id,
                                      document_ids=doc_ids,
                                      segment_count=len(all_segments),
                                      warnings=warnings)
            except Exception as exc:
                job.fail("PARSE_FAILED", str(exc))
                raise

    # ---------------- 内部 ----------------

    def _allocate_run_id(self, domain: str) -> str:
        now = timeutil.now_utc()
        seq = 1
        while True:
            rid = ids.new_run_id("PARSE", now=now, seq=seq)
            if not (self.ws / f"02_work/{domain}/run={rid}").exists():
                return rid
            seq += 1

    def _load_manifest(self, batch_rel: str) -> dict:
        rel = f"{batch_rel}/MANIFEST.md"
        text = self.ws.joinpath(*rel.split("/")).read_text(encoding="utf-8")
        result = validate_contract(text, specs.MANIFEST_SPEC, path=rel)
        result.raise_if_invalid(rel)
        if result.front_matter["status"] != "CLOSED":
            raise UsageError(f"批次未关闭，不可解析: {result.front_matter['status']}")
        return result.front_matter

    def _parse_document(self, path: Path, media_type: str, source_name: str):
        parser = adapters.pdf_parser.parser_for(media_type, path.suffix.lower())
        return parser.parse(path)

    def _write_document_md(self, doc_id, df, src_rel, parsed, domain, batch_id,
                           run_id, writer) -> None:
        fm = {
            "schema": "document/v1",
            "document_id": doc_id,
            "title": parsed.title or df["path"],
            "document_type": _document_type(df["path"]),
            "language": "zh-CN",
            "source_batch_id": batch_id,
            "source_path": src_rel,
            "source_sha256": df["sha256"],
            "source_media_type": df["media_type"],
            "confidentiality": "INTERNAL",
            "parse_status": "PARSED",
            "parser_id": parsed.parser_id,
            "parser_version": parsed.parser_version,
            "page_count": len(parsed.pages),
            "validation_status": "CANDIDATE",
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (
            f"# {parsed.title or df['path']}\n\n"
            "## 文档摘要\n\n"
            f"由解析器 {parsed.parser_id} v{parsed.parser_version} 解析，"
            f"{len(parsed.pages)} 页。\n\n"
            "## 来源与效力说明\n\n"
            f"来源：{src_rel}（SHA-256 {df['sha256'][:16]}…）\n\n"
            "## 解析说明\n\n"
            + ("；".join(parsed.warnings) if parsed.warnings else "无。")
            + "\n"
        )
        writer.write_text(
            f"02_work/{domain}/run={run_id}/documents/{doc_id}/DOCUMENT.md",
            markdown.render_contract_md(fm, body))

    def _build_normalized(self, doc_id, parsed, run_id) -> str:
        fm = {
            "schema": "normalized_document/v1",
            "document_id": doc_id,
            "source_sha256": hashing_mod.sha256_hex(parsed.title or doc_id),
            "parser_id": parsed.parser_id,
            "parser_version": parsed.parser_version,
            "parse_run_id": run_id,
            "normalization_policy_version": "norm/v1",
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = f"# {parsed.title}\n\n" + parsed.full_text() + "\n"
        return markdown.render_contract_md(fm, body)

    def _write_segment_md(self, seg: Segment, base: str, chunk_policy: str,
                          writer) -> None:
        fm = {
            "schema": "document_segment/v1",
            "segment_id": seg.segment_id,
            "document_id": seg.document_id,
            "segment_type": seg.segment_type,
            "heading_path": seg.heading_path,
            "page_from": seg.page_from,
            "page_to": seg.page_to,
            "sequence": seg.sequence,
            "char_start": seg.char_start,
            "char_end": seg.char_end,
            "content_sha256": seg.content_sha256,
            "chunk_policy_version": chunk_policy,
            "previous_segment_id": seg.previous_segment_id,
            "next_segment_id": seg.next_segment_id,
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (
            f"# {seg.heading_path[-1] if seg.heading_path else seg.segment_type}\n\n"
            "## 原文\n\n"
            f"{seg.content}\n\n"
            "## 解析注记\n\n无。\n"
        )
        writer.write_text(
            f"{base}/segments/{seg.document_id}/{seg.segment_id}.md",
            markdown.render_contract_md(fm, body))

    def _verify_segments(self, segments: list[Segment]) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for seg in segments:
            if seg.segment_id in seen:
                errors.append(f"重复 segment_id: {seg.segment_id}")
            seen.add(seg.segment_id)
            if seg.content_sha256 != hashing_mod.md_semantic_sha256(seg.content):
                errors.append(f"内容哈希不一致: {seg.segment_id}")
            if seg.page_from and seg.page_to and seg.page_to < seg.page_from:
                errors.append(f"页码区间非法: {seg.segment_id}")
        return errors

    def _write_lineage(self, domain, batch_id, run_id, job, writer, doc_ids) -> None:
        lineage_id = ids.new_id("LG")
        fm = {
            "schema": "lineage/v1",
            "lineage_id": lineage_id,
            "process_id": "parse_doc",
            "job_id": job.job_id,
            "inputs": [{"asset_id": batch_id, "version": "1.0",
                        "path": f"01_raw/{domain}/batch={batch_id}",
                        "content_hash": hashing_mod.sha256_hex(batch_id)}],
            "outputs": [{"asset_id": d, "version": run_id,
                         "path": f"02_work/{domain}/run={run_id}/documents/{d}/DOCUMENT.md",
                         "content_hash": hashing_mod.sha256_hex(d)} for d in doc_ids],
            "transformation_id": "parse_normalize_chunk",
            "transformation_version": "1.0.0",
            "code_version": "0.1.0",
            "started_at": timeutil.ts_utc(),
            "finished_at": timeutil.ts_utc(),
            "status": "COMPLETED",
            "version": "1.0",
        }
        writer.write_text(
            f"90_control/lineage/ingest/{lineage_id}.md",
            markdown.render_contract_md(
                fm, "# 血缘记录\n\n## 转换说明\n\n文档解析、规范化与切片。\n\n"
                    "## 输入\n\n见上。\n\n## 输出\n\n见上。\n\n## 已知限制\n\n无。\n"))


def _document_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "REPORT"
    if ext == ".docx":
        return "POLICY"
    if ext in (".html", ".htm"):
        return "WEBPAGE"
    return "MANUAL"


def chunk_document(parsed, document_id: str, chunk_policy: str = DEFAULT_CHUNK_POLICY,
                   max_chars: int = DEFAULT_MAX_CHARS) -> list[Segment]:
    """确定性切片：标题/段落/表格；segment_id 由内容派生（稳定）。"""
    segments: list[Segment] = []
    char_offset = 0
    sequence = 1
    current_page = 1
    heading_path: list[str] = []
    pending: list[str] = []
    pending_page = 1
    pending_start = 0

    def flush_pending():
        nonlocal pending, pending_start, sequence
        if pending:
            content = "\n".join(pending).rstrip()
            seg = Segment(
                segment_id=segment_id_for(document_id, heading_path, "PARAGRAPH", content),
                document_id=document_id, segment_type="PARAGRAPH",
                heading_path=list(heading_path),
                page_from=pending_page, page_to=pending_page, sequence=sequence,
                char_start=pending_start, char_end=pending_start + len(content),
                content_sha256=hashing_mod.md_semantic_sha256(content),
                previous_segment_id=None, next_segment_id=None, content=content,
            )
            segments.append(seg)
            sequence += 1
            pending = []
            pending_start = char_offset

    for page in parsed.pages:
        current_page = page.number
        for line in page.text.splitlines():
            m = HEADING_RE.match(line)
            if m:
                flush_pending()
                level, text = len(m.group(1)), m.group(2).strip()
                while len(heading_path) >= level:
                    heading_path.pop()
                heading_path.append(text)
                seg = Segment(
                    segment_id=segment_id_for(document_id, heading_path, "TITLE", text),
                    document_id=document_id, segment_type="TITLE",
                    heading_path=list(heading_path),
                    page_from=current_page, page_to=current_page, sequence=sequence,
                    char_start=char_offset, char_end=char_offset + len(text),
                    content_sha256=hashing_mod.md_semantic_sha256(text),
                    previous_segment_id=None, next_segment_id=None, content=text,
                )
                segments.append(seg)
                sequence += 1
                char_offset += len(line) + 1
                continue
            if TABLE_ROW_RE.match(line):
                flush_pending()
                content = line.rstrip()
                seg = Segment(
                    segment_id=segment_id_for(document_id, heading_path, "TABLE", content),
                    document_id=document_id, segment_type="TABLE",
                    heading_path=list(heading_path),
                    page_from=current_page, page_to=current_page, sequence=sequence,
                    char_start=char_offset, char_end=char_offset + len(content),
                    content_sha256=hashing_mod.md_semantic_sha256(content),
                    previous_segment_id=None, next_segment_id=None, content=content,
                )
                segments.append(seg)
                sequence += 1
                char_offset += len(line) + 1
                continue
            if not line.strip():
                flush_pending()
                char_offset += 1
                continue
            if not pending:
                pending_start = char_offset
                pending_page = current_page
            pending.append(line.rstrip())
            char_offset += len(line) + 1
    flush_pending()

    for i, seg in enumerate(segments):
        seg.previous_segment_id = segments[i - 1].segment_id if i > 0 else None
        seg.next_segment_id = segments[i + 1].segment_id if i < len(segments) - 1 else None
    return segments
