"""EC-1 identity context: provenance for pronouns, never factual evidence.

The audit skill ships an identical copy; cross-skill regression checks parity.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

VERSION = "EC-1"
CONTEXT_HEADING = "证据归属（仅用于指代解析）"
EVIDENCE_HEADING = "证据正文（供Faithfulness核验）"
SECTIONS = {"一、可直接用于正文的事实", "二、可直接采用的英文表达", "三、可使用的数据表"}
FORMAL_FIELDS = ("证据归属主体", "证据归属对象", "指代解析", "归属核验依据", "归属核验日期", "归属核验状态", "归属证据SHA-256")
CONTEXT_FIELDS = ("内容提供方", "对应对象", "指代关系", "核验状态")


def field(text: str, name: str) -> str:
    values = re.findall(r"^[ \t]*[-*][ \t]*" + re.escape(name) + r"[：:][ \t]*(.*?)[ \t]*$", text, re.M)
    return values[0] if len(values) == 1 else ""


def original_evidence(text: str) -> str:
    match = re.search(r"^###\s+最小原文证据\s*$", text, re.M)
    if not match:
        return ""
    body = text[match.end():]
    stop = re.search(r"^#{1,3}\s+", body, re.M)
    if stop:
        body = body[:stop.start()]
    return "\n".join(re.sub(r"^\s*>\s?", "", line).strip() for line in body.splitlines() if line.lstrip().startswith(">") and re.sub(r"^\s*>\s?", "", line).strip())


def evidence_digest(text: str) -> str:
    return hashlib.sha256(original_evidence(text).encode("utf-8")).hexdigest()


def formal_errors(text: str, required: bool = False) -> list[str]:
    version = field(text, "证据模板版本")
    if not required and not re.search(r"^[ \t]*[-*][ \t]*证据模板版本[：:]", text, re.M):
        return []  # Historical contracts remain readable; no inferred identity.
    errors = []
    if version != VERSION:
        errors.append("Formal Claim缺少EC-1证据归属模板，先回源核验并补齐")
    for name in FORMAL_FIELDS:
        if not field(text, name):
            errors.append(f"Formal Claim缺少或重复归属字段：{name}")
    if field(text, "归属核验状态") != "已核验":
        errors.append("Formal Claim归属尚未核验，不得猜测指代")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", field(text, "归属核验日期")):
        errors.append("Formal Claim归属核验日期必须为YYYY-MM-DD")
    if not original_evidence(text) or field(text, "归属证据SHA-256") != evidence_digest(text):
        errors.append("Formal Claim归属核验未绑定当前最小原文证据SHA-256")
    for name in ("证据归属主体", "证据归属对象", "归属核验依据"):
        if field(text, name) in {"无", "待确认", "未知", "模型判断"}:
            errors.append(f"Formal Claim归属字段不能作为已核验依据：{name}")
    return errors


def formal_context(text: str) -> dict[str, str] | None:
    if field(text, "证据模板版本") != VERSION or formal_errors(text, True):
        return None
    return dict(zip(CONTEXT_FIELDS, (field(text, "证据归属主体"), field(text, "证据归属对象"), field(text, "指代解析"), "已核验")))


def mapping_identity_errors(material_text: str, start: int, end: int, claim_text: str, required: bool = False) -> list[str]:
    required = required or field(material_text, "证据模板版本") == VERSION
    errors = formal_errors(claim_text, required)
    try:
        contexts = material_contexts(material_text.splitlines(), required=required)
    except ValueError as exc:
        return errors + [str(exc)]
    if not required and not contexts:
        return errors
    matches = [context for context in contexts if context["evidence_line_start"] <= start <= end <= context["evidence_line_end"]]
    expected = formal_context(claim_text)
    if len(matches) != 1 or not expected or matches[0]["fields"] != expected:
        errors.append("30证据归属与当前Formal Claim核验记录不一致，须同步重建，不能临时猜主体")
    return errors


def render_context(context: dict[str, str], level: int = 4) -> str:
    return "#" * level + " " + CONTEXT_HEADING + "\n" + "\n".join(f"- {name}：{context[name]}" for name in CONTEXT_FIELDS) + "\n\n"


def material_contexts(lines: list[str], source_file: str = "", required: bool = False) -> list[dict]:
    """Pair a fixed context with its immediately following sibling evidence block."""
    required = required or field("\n".join(lines), "证据模板版本") == VERSION
    output = []
    active = False
    pending = None
    evidence_count = 0
    index = 0
    while index < len(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", lines[index])
        if not match:
            index += 1
            continue
        level, title = len(match[1]), match[2]
        if level <= 2:
            if pending is not None:
                raise ValueError("30归属板块没有对应证据正文，不能跨章节绑定")
            active = title in SECTIONS
        elif active and title == CONTEXT_HEADING:
            if required and level != 4:
                raise ValueError("EC-1归属和证据正文固定使用四级标题")
            end = index + 1
            while end < len(lines) and not re.match(r"^#{1,6}\s+", lines[end]):
                end += 1
            raw = "\n".join(lines[index + 1:end])
            values = {name: field(raw, name) for name in CONTEXT_FIELDS}
            nonblank = [line for line in lines[index + 1:end] if line.strip()]
            if len(nonblank) != len(CONTEXT_FIELDS) or any(not value for value in values.values()) or values["核验状态"] != "已核验":
                raise ValueError("30证据归属必须使用四个固定字段且状态为已核验")
            labels = [re.match(r"^[ \t]*[-*][ \t]*([^：:]+)[：:]", line) for line in nonblank]
            if any(label is None for label in labels) or tuple(label[1] for label in labels) != CONTEXT_FIELDS:
                raise ValueError("30证据归属字段必须按固定模板顺序填写")
            if any(re.search(r"https?://|CLM-[A-Za-z0-9]", value) for value in values.values()):
                raise ValueError("30证据归属不得包含URL或Claim ID")
            if pending is not None:
                raise ValueError("30出现未绑定事实证据的重复归属板块")
            pending = {"source_file": source_file, "line_start": index + 2, "line_end": end, "quote": raw, "fields": values, "level": level}
            index = end
            continue
        elif active and title == EVIDENCE_HEADING:
            if required and level != 4:
                raise ValueError("EC-1归属和证据正文固定使用四级标题")
            evidence_count += 1
            end = index + 1
            while end < len(lines):
                next_heading = re.match(r"^(#{1,6})\s+", lines[end])
                if next_heading and len(next_heading[1]) <= level:
                    break
                end += 1
            body = [i for i in range(index + 1, end) if lines[i].lstrip().startswith(">") and lines[i].lstrip()[1:].strip()]
            if pending is None:
                if required:
                    raise ValueError("EC-1的每个证据正文必须有相邻的固定归属板块")
            else:
                if pending.pop("level") != level or not body:
                    raise ValueError("30归属和证据正文须为同级相邻板块且正文非空")
                pending.update(evidence_line_start=body[0] + 1, evidence_line_end=body[-1] + 1)
                output.append(pending)
                pending = None
            index = end
            continue
        elif active:
            if pending is not None:
                raise ValueError("30归属之后必须紧接同级证据正文，不能跨事实块绑定")
        index += 1
    if pending is not None:
        raise ValueError("30归属板块没有对应证据正文")
    if required and not evidence_count:
        raise ValueError("EC-1资料包没有证据正文")
    return output


def contexts_for_files(paths: list[Path]) -> list[dict]:
    output = []
    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        if CONTEXT_HEADING in text or field(text, "证据模板版本") == VERSION:
            output.extend(material_contexts(text.splitlines(), str(path.resolve()), field(text, "证据模板版本") == VERSION))
    return output


def validate_coreference(claim: dict, contexts: list[dict]) -> None:
    """Validate contextual citations separately; they never replace factual evidence."""
    refs = claim.get("coreference_evidence", [])
    if not isinstance(refs, list):
        raise ValueError("coreference_evidence必须为数组")
    facts = claim.get("evidence", [])
    if not isinstance(facts, list) or any(not isinstance(fact, dict) for fact in facts):
        raise ValueError("evidence必须为证据对象数组")
    verified = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError("coreference_evidence引用必须为对象")
        matches = [context for context in contexts if
            str(Path(str(ref.get("source_file", ""))).resolve()).casefold() == str(Path(context["source_file"]).resolve()).casefold()
            and ref.get("line_start") == context["line_start"] and ref.get("line_end") == context["line_end"]
            and ref.get("quote") == context["quote"]]
        if len(matches) != 1:
            raise ValueError("指代引用必须逐字对应当前30的唯一归属板块")
        context = matches[0]
        if not any(str(Path(str(fact.get("source_file", ""))).resolve()).casefold() == str(Path(context["source_file"]).resolve()).casefold()
            and context["evidence_line_start"] <= fact.get("line_start", 0) <= fact.get("line_end", 0) <= context["evidence_line_end"] for fact in facts):
            raise ValueError("指代归属必须绑定同一事实块的证据引用，不能独立支持或串用")
        if len(str(ref.get("reason", "")).strip()) < 8:
            raise ValueError("指代引用须说明实际解析关系")
        verified.append(context)
    if claim.get("verdict") == "supported":
        for fact in facts:
            if not re.search(r"\b(?:we|our|ours|this|these|they|their)\b", str(fact.get("quote", "")), re.I):
                continue
            bound = [context for context in contexts if
                str(Path(str(fact.get("source_file", ""))).resolve()).casefold() == str(Path(context["source_file"]).resolve()).casefold()
                and context["evidence_line_start"] <= fact.get("line_start", 0) <= fact.get("line_end", 0) <= context["evidence_line_end"]]
            if any(context not in verified for context in bound):
                raise ValueError("每个含指代的支持证据块都须记录同块coreference_evidence")

