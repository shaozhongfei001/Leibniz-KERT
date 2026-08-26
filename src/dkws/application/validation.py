"""知识引用、重复与冲突校验（FR-KNW-004、规格 §11.7、§15.5）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Finding:
    level: str  # BLOCKER/MAJOR/MINOR/NOTE
    code: str
    message: str
    ref: str = ""


def check_dangling_references(entities: dict, relations: list[dict],
                              statements: list[dict]) -> list[Finding]:
    """悬空引用：关系端点、声明主体/客体必须存在实体。"""
    findings: list[Finding] = []
    entity_ids = set(entities)
    for rel in relations:
        for side, key in (("source", "source_id"), ("target", "target_id")):
            ref = rel.get(key)
            if ref and ref not in entity_ids:
                findings.append(Finding(
                    "BLOCKER", "DANGLING_RELATION",
                    f"关系 {rel.get('relation_id')} 的 {side} 实体不存在: {ref}",
                    rel.get("relation_id", "")))
    for st in statements:
        subj = st.get("subject_id")
        if subj and subj not in entity_ids:
            findings.append(Finding(
                "BLOCKER", "DANGLING_STATEMENT_SUBJECT",
                f"声明 {st.get('statement_id')} 的主体实体不存在: {subj}",
                st.get("statement_id", "")))
        if st.get("value_type") == "OBJECT_REF" and st.get("object_id"):
            obj = st["object_id"]
            if obj not in entity_ids:
                findings.append(Finding(
                    "BLOCKER", "DANGLING_STATEMENT_OBJECT",
                    f"声明 {st.get('statement_id')} 的客体实体不存在: {obj}",
                    st.get("statement_id", "")))
    return findings


def check_duplicate_entities(entities: dict) -> list[Finding]:
    """同名异体 / 别名重复检测。"""
    findings: list[Finding] = []
    by_name: dict[str, list[str]] = {}
    alias_owner: dict[str, str] = {}
    for eid, ent in entities.items():
        name = ent.get("name")
        by_name.setdefault(name, []).append(eid)
        for alias in ent.get("aliases", []) or []:
            if alias in alias_owner:
                findings.append(Finding(
                    "MAJOR", "DUPLICATE_ALIAS",
                    f"别名 {alias!r} 被 {alias_owner[alias]} 与 {eid} 共享", eid))
            else:
                alias_owner[alias] = eid
    for name, ids in by_name.items():
        if len(ids) > 1:
            findings.append(Finding(
                "MAJOR", "DUPLICATE_ENTITY_NAME",
                f"实体名称重复（同名异体候选）: {name!r} → {ids}", ids[0]))
    return findings


def check_statement_conflicts(statements: list[dict],
                              entities: dict | None = None) -> list[Finding]:
    """同主体同谓词的互斥声明冲突检测；entities 提供时检测同名异体矛盾（POTENTIAL）。"""
    findings: list[Finding] = []
    groups: dict[tuple, list[dict]] = {}
    for st in statements:
        key = (st.get("subject_id"), st.get("predicate"))
        groups.setdefault(key, []).append(st)
    for (subj, pred), items in groups.items():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if _conflicts(a, b):
                    findings.append(Finding(
                        "MAJOR", "CONFLICTING_STATEMENT",
                        f"同主体同谓词存在矛盾值: {subj} {pred}: "
                        f"{a.get('object_value')} vs {b.get('object_value')}",
                        a.get("statement_id", "")))
    # 同名异体：不同主体实体但名称相同、谓词相同、值矛盾 → POTENTIAL 冲突
    if entities:
        by_name: dict[tuple, list[dict]] = {}
        for st in statements:
            ent = entities.get(st.get("subject_id"))
            name = (ent or {}).get("name")
            if not name:
                continue
            by_name.setdefault((name, st.get("predicate")), []).append(st)
        for (name, pred), items in by_name.items():
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    if a.get("subject_id") == b.get("subject_id"):
                        continue
                    if _conflicts(a, b):
                        findings.append(Finding(
                            "MAJOR", "CONFLICTING_STATEMENT",
                            f"同名异体矛盾声明（POTENTIAL）: {name} {pred}: "
                            f"{a.get('object_value')} vs {b.get('object_value')}",
                            a.get("statement_id", "")))
    return findings


def _conflicts(a: dict, b: dict) -> bool:
    if a.get("polarity") != b.get("polarity"):
        return False
    if a.get("value_type") != b.get("value_type"):
        return False
    av, bv = a.get("object_value"), b.get("object_value")
    if av is None or bv is None or av == bv:
        return False
    return _overlaps(a.get("effective_from"), a.get("effective_to"),
                     b.get("effective_from"), b.get("effective_to"))


def _overlaps(a_from, a_to, b_from, b_to) -> bool:
    a_from = a_from or "0000-01-01"
    a_to = a_to or "9999-12-31"
    b_from = b_from or "0000-01-01"
    b_to = b_to or "9999-12-31"
    return a_from <= b_to and b_from <= a_to
