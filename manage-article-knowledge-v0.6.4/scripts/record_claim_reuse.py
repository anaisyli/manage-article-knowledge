#!/usr/bin/env python3
"""Register an existing, usable Formal Claim as reused evidence in a batch ledger.

When a valid Claim already answers an outline question, the knowledge workflow
reuses it without re-reading the original page or file.  This command writes
that ledger row: every mechanical field (source, location, excerpts, verified
date, scope) is copied from the Claim itself, so the agent only states which
article/Claim and why the Claim applies.  The row is checked with the same
provenance rules the batch gate uses.

Older Claims may predate current requirements.  Each Claim is first checked
against them and reported as one of: ready; "补齐登记" (fields that can be
completed from what the Claim already saved, e.g. EC-1 attribution or a verified
translation of the saved excerpt); or "回源核验" (the saved record cannot prove
the fact any more, e.g. no excerpt, no location, not usable, review triggered).
Only ready Claims are registered; the others are listed with the next step.
A Claim the article needs is never dropped as "unusable": "补齐登记" prints a
draft and ``--complete`` writes it (archive, replace, version bump) and registers
in the same call; "回源核验" names the source-specific re-verification steps.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from batch_knowledge_run import _claim_path, now, same_fact_row, validate_claim_provenance, validate_evidence
from evidence_identity import evidence_digest, field, formal_errors, original_evidence, pre_use_review
from run_knowledge_workflow import resolve_ledger

CLAIM_MARKER = r"^\s*[-*]\s*Claim ID[：:]\s*{}\s*$"
SRC_RE = re.compile(r"(?a:\b)SRC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?a:\b)")


def claim_block(text: str, claim_id: str) -> str:
    match = re.search(CLAIM_MARKER.format(re.escape(claim_id)), text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    following = re.search(r"^\s*[-*]\s*Claim ID[：:]", rest, re.M)
    return text[match.start(): match.end() + (following.start() if following else len(rest))]


def translated_evidence(block: str) -> str:
    match = re.search(r"^###\s+经核验英文严格翻译\s*$", block, re.M)
    if not match:
        return ""
    body = block[match.end():]
    stop = re.search(r"^#{1,3}\s+", body, re.M)
    body = body[:stop.start()] if stop else body
    return "\n".join(re.sub(r"^\s*>\s?", "", line).strip() for line in body.splitlines()
                     if line.lstrip().startswith(">") and re.sub(r"^\s*>\s?", "", line).strip())


SUPPLEMENT_ACTION = ("本篇需要该Claim时在本轮立即补齐，不得以不可用跳过：按claim_complete_draft只依据已存原文与来源记录"
                     "确认或填写其中的字段，存为JSON（{Claim ID: {字段: 值}}）后在同一命令加--complete <JSON>重跑；"
                     "EC-1版本、归属核验日期、核验状态和归属证据SHA-256由脚本计算，知识文件先归档再替换并递增版本，"
                     "随后直接登记。不需要重读原件；主体、对象或指代无法由已存原文唯一确定时改按回源核验处理")
REVERIFY_ACTION = "本篇需要该Claim时在本轮立即回源，不得以不可用跳过；本篇其他可用Claim照常登记，不必整篇重做"

# Fields an agent may write when completing an old Claim; every other EC-1 field is computed.
SEMANTIC_FIELDS = ("证据归属主体", "证据归属对象", "指代解析", "归属核验依据")
FILLABLE_FIELDS = ("适用范围", "来源类型", "使用边界")
TRANSLATION = "经核验英文严格翻译"
UNVERIFIED = {"", "无", "待确认", "未知", "模型判断"}
PRONOUN_RE = re.compile(r"\b(?:this|that|these|those|it|its|they|their|them|we|our|us|you|your)\b|该|此|其|我们|您", re.I)
CUSTOMER_SOURCES = {"客户官网", "客户源文件", "客户关联网站", "客户确认"}
# The words the audit resolves through the EC-1 block (deepeval-article-audit COREFERENCE_PRONOUN, plus us).
# ASCII boundaries: "第一句的we指…" must count as naming "we".
AUDIT_PRONOUN_RE = re.compile(r"(?a:\b)(we|our|ours|us|this|these|they|their)(?a:\b)", re.I)


def unresolved_pronouns(block: str) -> list[str]:
    """Audit-resolved words in the excerpt that 指代解析 does not say what they refer to (SK-V064-030).

    The audit judges the subject of "We can manufacture…" from the EC-1 block; a block that says
    nothing about "we" leaves the subject unresolved however correct the Claim is.
    """
    used = {word.lower() for word in AUDIT_PRONOUN_RE.findall(original_evidence(block))}
    note = field(block, "指代解析")
    named = {word.lower() for word in AUDIT_PRONOUN_RE.findall(note)}
    if "我们" in note:
        named |= {"we", "our", "ours", "us"}
    return sorted(used - named)


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def reverify_steps(block: str) -> str:
    """Concrete re-verification steps for this Claim's own source."""
    source, location = field(block, "来源链接"), field(block, "精确位置")
    steps = []
    status = field(block, "状态")
    if status and status != "可用":
        steps.append(f"当前状态“{status}”是此前的决定，恢复前先读该Claim与知识文件中的暂停或限制说明")
    url = re.search(r"https?://[^\s)\]>]+", source)
    if url:
        steps.append(f"用capture_website_evidence.py重新抓取{url.group(0)}（{location or '原精确位置'}）并保存凭证")
    else:
        steps.append(f"重新打开原件{source or '（来源链接）'}的{location or '原精确位置'}（PDF或扫描件按复杂资料流程逐页核对）")
    steps.append("逐字核对最小原文证据：一致则更新最近核验日期、把状态恢复为可用并写明依据，再用--complete补齐EC-1后登记；"
                 "原文已变则按新原文更新Claim；只有来源不可达或事实不再成立才登记ANM或公共知识缺口，并在20记录")
    return "；".join(steps)


def readiness(project: Path, claim_id: str, *, require_ec1: bool, target_language: str) -> dict:
    """Classify a Claim against the current reuse requirements."""
    path = _claim_path(project, claim_id)
    if path is None:
        return {"claim_id": claim_id, "status": "回源核验", "problems": ["找不到该Formal Claim"], "action": REVERIFY_ACTION}
    return classify(path.read_text(encoding="utf-8-sig"), claim_id,
                    require_ec1=require_ec1, target_language=target_language)


def classify(text: str, claim_id: str, *, require_ec1: bool, target_language: str) -> dict:
    """Classify one Claim inside a knowledge file's text (current or staged)."""
    block = claim_block(text, claim_id)
    reverify: list[str] = []
    supplement: list[str] = []
    original = original_evidence(block)
    if not original:
        reverify.append("缺少最小原文证据")
    for name in ("来源链接", "精确位置"):
        if not field(block, name):
            reverify.append(f"缺少{name}")
    if field(block, "状态") != "可用":
        reverify.append(f"Claim状态为“{field(block, '状态') or '空'}”，不是可用")
    knowledge_status = field(text, "知识状态")
    if knowledge_status.startswith("有效") and knowledge_status != "有效":
        # A note appended to a valid status is a record-format issue only.
        supplement.append(f"知识状态须只写“有效”，附注“{knowledge_status[2:].lstrip('；;，, ')}”移到其他字段")
    elif knowledge_status and knowledge_status != "有效":
        reverify.append(f"知识文件状态为“{knowledge_status}”")
    review = pre_use_review(text)
    if review == "是":
        reverify.append("标记为使用前必须回源复核")
    elif review not in {"", "否", "条件"}:
        supplement.append(f"使用前复核须以“是/否/条件”开头（条件后写明触发条件），当前为“{field(text, '使用前复核')}”")
    if not field(text, "最近核验日期"):
        reverify.append("知识文件没有最近核验日期，无法确认已核验")
    for name in ("适用范围", "来源类型", "使用边界"):
        if not field(block, name):
            supplement.append(f"缺少{name}")
    if require_ec1 and original:
        if field(block, "证据模板版本") != "EC-1":
            # One line for a Claim written before EC-1, instead of one per field.
            supplement.append("缺少EC-1证据归属记录（证据模板版本及归属主体、对象、指代解析、核验依据、核验日期、核验状态、归属证据SHA-256）")
        else:
            recorded = field(block, "归属证据SHA-256")
            if recorded and recorded != evidence_digest(block):
                # A missing hash is computed from the saved text; a different one means the text changed
                # after attribution was verified, and only a source read can rebind it.
                reverify.append("归属证据SHA-256与当前最小原文证据不一致：原文在归属核验后被改动")
            supplement.extend(error for error in formal_errors(block, required=True)
                              if not (recorded and "SHA-256" in error))
            missing = unresolved_pronouns(block)
            if missing:
                supplement.append(f"指代解析没有说明原文中的{'、'.join(missing)}指谁或指什么（按当前EC-1规则重写指代解析）")
    if (original and contains_chinese(original) and not translated_evidence(block)
            and target_language.strip().lower() not in {"中文", "chinese", "zh"}):
        supplement.append("中文原文缺少经核验英文严格翻译")
    if reverify:
        return {"claim_id": claim_id, "status": "回源核验", "problems": reverify + supplement,
                "action": REVERIFY_ACTION + "：" + reverify_steps(block)}
    if supplement:
        return {"claim_id": claim_id, "status": "补齐登记", "problems": supplement, "action": SUPPLEMENT_ACTION}
    return {"claim_id": claim_id, "status": "可直接复用", "problems": [], "action": ""}


def claim_title(text: str, claim_id: str) -> str:
    match = re.search(rf"^#{{2,4}}\s+{re.escape(claim_id)}\s*[｜|]\s*(.+?)\s*$", text, re.M)
    return match.group(1) if match else ""


def usual_subject(project: Path, source_type: str) -> str:
    """The attribution subject verified Claims from the same kind of source already use."""
    family = CUSTOMER_SOURCES if source_type in CUSTOMER_SOURCES else {source_type}
    subjects: Counter[str] = Counter()
    for path in (project / "03_正式知识").rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for claim_id in re.findall(r"^\s*[-*]\s*Claim ID[：:]\s*(\S+)\s*$", text, re.M):
            block = claim_block(text, claim_id)
            if field(block, "证据模板版本") == "EC-1" and field(block, "来源类型") in family:
                subject = field(block, "证据归属主体")
                if subject not in UNVERIFIED:
                    subjects[subject] += 1
    return subjects.most_common(1)[0][0] if subjects else ""


def completion_draft(project: Path, claim_id: str, *, require_ec1: bool, target_language: str) -> dict:
    """What an agent must confirm to complete an old Claim, with suggestions from its saved record."""
    path = _claim_path(project, claim_id)
    text = path.read_text(encoding="utf-8-sig") if path else ""
    block = claim_block(text, claim_id)
    original = original_evidence(block)
    fields: dict[str, str] = {}
    if require_ec1 and original and field(block, "证据模板版本") != "EC-1":
        source_type = field(block, "来源类型")
        fields["证据归属主体"] = usual_subject(project, source_type)
        fields["证据归属对象"] = claim_title(text, claim_id) or field(block, "适用范围")
        fields["指代解析"] = "" if PRONOUN_RE.search(original) else "无"
        fields["归属核验依据"] = (f"{source_type or '来源'}{field(block, '精确位置')}的已存最小原文证据回读，"
                                  "主体与对象由原文唯一确定")
    elif require_ec1 and original and unresolved_pronouns(block):
        # Rewrite only the resolution; it must name every listed word (current text kept as the start).
        fields["指代解析"] = field(block, "指代解析")
        fields["需在指代解析中说明"] = "、".join(unresolved_pronouns(block))
    computed = [name for name in ("归属证据SHA-256", "归属核验日期")
                if require_ec1 and original and field(block, "证据模板版本") == "EC-1" and not field(block, name)]
    for name in FILLABLE_FIELDS:
        if not field(block, name):
            fields[name] = ""
    if (original and contains_chinese(original) and not translated_evidence(block)
            and target_language.strip().lower() not in {"中文", "chinese", "zh"}):
        fields[TRANSLATION] = ""
    draft = {"claim_id": claim_id, "source": f"{field(block, '来源链接')}；{field(block, '精确位置')}",
             "excerpt": original, "fields": fields}
    if computed:
        draft["script_computes"] = computed  # nothing to write for these: {Claim ID: {}} is enough
    return draft


def _insert_before_status(block: str, lines: list[str]) -> str:
    if not lines:
        return block
    anchor = (re.search(r"^[ \t]*[-*][ \t]*状态[：:].*$", block, re.M)
              or re.search(r"^###\s+最小原文证据\s*$", block, re.M))
    position = anchor.start() if anchor else len(block)
    return block[:position] + "\n".join(lines) + "\n" + block[position:]


def complete_block(text: str, claim_id: str, values: dict, *, today: str, require_ec1: bool) -> str:
    """Write the agent's confirmed fields and the computed EC-1 fields into one Claim."""
    block = claim_block(text, claim_id)
    if not block:
        raise ValueError(f"找不到Formal Claim：{claim_id}")
    values = {key: value for key, value in values.items() if key != "需在指代解析中说明"}  # draft hint only
    unknown = sorted(set(values) - set(SEMANTIC_FIELDS + FILLABLE_FIELDS + (TRANSLATION,)))
    if unknown:
        raise ValueError(f"{claim_id}：不能补写{'、'.join(unknown)}；其余EC-1字段由脚本计算")
    note = str(values.get("指代解析", "")).strip()
    if field(block, "证据模板版本") == "EC-1" and note and note != field(block, "指代解析"):
        # SK-V064-030: an EC-1 Claim whose resolution misses a word the audit resolves is rewritten to the
        # current rule.  The excerpt is unchanged, so its SHA-256 stays; the attribution date is today.
        rewritten = re.sub(r"^([ \t]*[-*][ \t]*指代解析[：:]).*$", lambda m: m.group(1) + note, block, count=1, flags=re.M)
        rewritten = re.sub(r"^([ \t]*[-*][ \t]*归属核验日期[：:]).*$", lambda m: m.group(1) + today, rewritten,
                           count=1, flags=re.M)
        missing = unresolved_pronouns(rewritten)
        if missing:
            raise ValueError(f"{claim_id}：指代解析仍未说明原文中的{'、'.join(missing)}；按已存原文写明各自指谁，无法唯一确定时改按回源核验处理")
        text, block = text.replace(block, rewritten, 1), rewritten
    lines = [f"- {name}：{str(values[name]).strip()}" for name in FILLABLE_FIELDS
             if str(values.get(name, "")).strip() and not field(block, name)]
    if require_ec1 and original_evidence(block) and field(block, "证据模板版本") != "EC-1":
        ec1 = {name: str(values.get(name, "")).strip() for name in SEMANTIC_FIELDS}
        missing = [name for name in ("证据归属主体", "证据归属对象", "归属核验依据") if ec1[name] in UNVERIFIED]
        if not ec1["指代解析"]:
            missing.append("指代解析")
        if missing:
            raise ValueError(f"{claim_id}：须依据已存原文填写{'、'.join(missing)}；无法唯一确定时改按回源核验处理")
        lines += ["- 证据模板版本：EC-1", *(f"- {name}：{ec1[name]}" for name in SEMANTIC_FIELDS),
                  f"- 归属核验日期：{today}", "- 归属核验状态：已核验", f"- 归属证据SHA-256：{evidence_digest(block)}"]
    if require_ec1 and original_evidence(block) and field(block, "证据模板版本") == "EC-1":
        # P-005-SKFB-020: this hash was only computed while upgrading a pre-EC-1 Claim, so an EC-1 Claim
        # lacking just this line stayed 补齐登记 however often --complete ran.
        if not field(block, "归属证据SHA-256"):
            lines.append(f"- 归属证据SHA-256：{evidence_digest(block)}")
        if not field(block, "归属核验日期"):
            lines.append(f"- 归属核验日期：{today}")
    updated = _insert_before_status(block, lines)
    translation = values.get(TRANSLATION)
    if translation and not translated_evidence(block):
        rows = translation if isinstance(translation, list) else str(translation).splitlines()
        section = "### 经核验英文严格翻译\n\n" + "\n".join(f"> {row.strip()}" for row in rows if str(row).strip()) + "\n\n"
        evidence = re.search(r"^###\s+最小原文证据\s*$", updated, re.M)
        following = re.search(r"^#{1,3}\s+", updated[evidence.end():], re.M) if evidence else None
        position = evidence.end() + following.start() if following else len(updated)
        updated = updated[:position].rstrip("\n") + "\n\n" + section + updated[position:]
    return text.replace(block, updated, 1)


def next_version(version: str) -> str:
    match = re.fullmatch(r"([vV])(\d+)", version.strip())
    return f"{match.group(1)}{int(match.group(2)) + 1}" if match else ""


def complete_claims(project: Path, completions: dict, *, article_id: str, require_ec1: bool,
                    target_language: str) -> list[Path]:
    """Complete old Claims in their knowledge files: verify staged text, archive, replace, bump the version."""
    from archive_project_version import create_archive

    today = date.today().isoformat()
    by_file: dict[Path, list[str]] = {}
    for claim_id in completions:
        path = _claim_path(project, claim_id)
        if path is None:
            raise ValueError(f"找不到Formal Claim：{claim_id}")
        by_file.setdefault(path, []).append(claim_id)
    staged: dict[Path, tuple[str, bytes]] = {}
    for path, claim_ids in by_file.items():
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
        updated = text
        for claim_id in claim_ids:
            updated = complete_block(updated, claim_id, completions[claim_id], today=today, require_ec1=require_ec1)
        for claim_id in claim_ids:
            state = classify(updated, claim_id, require_ec1=require_ec1, target_language=target_language)
            if state["status"] != "可直接复用":
                raise ValueError(f"{claim_id}补齐后仍不能复用：" + "；".join(state["problems"]))
        if updated == text:
            continue  # already complete (e.g. a rerun after registration failed): no archive, no version bump
        version = field(updated, "知识版本")
        if next_version(version):
            updated = re.sub(r"^(\s*[-*]\s*知识版本[：:]\s*).*$", lambda m: m.group(1) + next_version(version),
                             updated, count=1, flags=re.M)
        # Keep the file's own BOM and line endings; only the completed fields change.
        newline = "\r\n" if b"\r\n" in raw else "\n"
        body = updated.replace("\n", newline).encode("utf-8")
        staged[path] = (version, (b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b"") + body)
    if not staged:
        return []
    for path, (version, content) in staged.items():
        create_archive(project=project, target=path, kind="formal-knowledge",
                       reason="补齐旧Claim的复用记录（EC-1归属、缺失字段或英文严格翻译），不改变Claim事实",
                       replacement_version=next_version(version) or version or "补齐后当前版本")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
    try:
        from build_coverage_view import rebuild_view
        rebuild_view(project)
    except Exception as exc:  # the Claims are written; a stale view is reported, not fatal
        print(f"coverage_view_warning={exc}")
    from record_project_run import append_record, make_record
    append_record(project, make_record(
        project_root=project, task="补齐旧Claim复用记录", status="success", article_ids=[article_id],
        outputs=list(staged), note="补齐：" + "、".join(completions)))
    return list(staged)


def request_fields(project: Path, article_id: str) -> tuple[bool, str]:
    task = task_dir(project, article_id)
    request = (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig") if task else ""
    return field(request, "证据模板版本") == "EC-1", field(request, "目标语言") or "English"


def task_dir(project: Path, article_id: str) -> Path | None:
    root = project / "04_文章任务"
    for state in ("10_进行中", "20_等待终稿"):
        matches = sorted((root / state).glob(f"{article_id}_*")) + sorted((root / state).glob(article_id))
        if matches:
            return matches[0]
    return None


def used_candidates(payload: dict, project: Path, article_id: str) -> set[int]:
    numbers: set[int] = set()
    for key in ("evidence", "capture_inbox"):
        for row in payload.get(key, []):
            if isinstance(row, dict) and (article_id in row.get("article_ids", []) or row.get("article_id") == article_id):
                numbers.update(int(n) for n in re.findall(r"(?a:\b)CF-(\d{3})(?a:\b)", str(row.get("candidate_id", ""))))
    task = task_dir(project, article_id)
    if task:
        from task_records import read_record, record_is_file
        record = task / "15_检索与知识准备记录.md"
        if record_is_file(record):
            numbers.update(int(n) for n in re.findall(r"(?a:\b)CF-(\d{3})(?a:\b)", read_record(record)))
    return numbers


def build_row(project: Path, payload: dict, *, article_id: str, claim_id: str,
              question_ids: list[str], basis: str) -> dict:
    path = _claim_path(project, claim_id)
    if path is None:
        raise ValueError(f"找不到Formal Claim：{claim_id}")
    text = path.read_text(encoding="utf-8-sig")
    block = claim_block(text, claim_id)
    original = original_evidence(block)
    if not original:
        raise ValueError(f"{claim_id}没有“最小原文证据”，不能直接复用；先修复Claim")
    source = field(block, "来源链接")
    source_id = (SRC_RE.findall(source) or [field(block, "来源类型") or "Formal Claim"])[0]
    row = {
        "batch_id": payload.get("batch_id"),
        "article_ids": [article_id],
        "question_ids": question_ids,
        "candidate_id": "",
        "claim_id": claim_id,
        "source_id": source_id,
        "source_type": field(block, "来源类型"),
        "source_path_or_url": source,
        "exact_location": field(block, "精确位置"),
        "original_excerpt": original,
        "verified_target_excerpt": translated_evidence(block) or original,
        "scope": field(block, "适用范围"),
        "disposition": "复用已有Formal Claim",
        "evidence_origin": "Formal Claim",
        "claim_verified_at": field(text, "最近核验日期"),
        "reuse_basis": basis.strip(),
        "recorded_at": now(),
    }
    if field(block, "证据模板版本") == "EC-1":
        row["evidence_context_version"] = "EC-1"
    return row


def record(project: Path, batch_id: str, article_id: str, claim_ids: list[str],
           basis: str, question_ids: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    if len(basis.strip()) < 8:
        raise ValueError("--basis须用一句话写明该Claim为什么覆盖本篇问题、为何未触发回源复核")
    ledger = resolve_ledger(project, batch_id)
    if not ledger.is_file():
        raise ValueError(f"批次账本不存在：{batch_id}；先由writing_bridge.py prepare登记本批文章")
    payload = json.loads(ledger.read_text(encoding="utf-8-sig"))
    articles = {str(a.get("article_id")) for a in payload.get("articles", []) if isinstance(a, dict)}
    if article_id not in articles:
        raise ValueError(f"文章未登记在批次账本：{article_id}")
    linked = [str(q.get("question_id")) for q in payload.get("questions", [])
              if isinstance(q, dict) and article_id in q.get("article_ids", [])]
    questions = question_ids or linked
    unknown = sorted(set(questions) - set(linked))
    if not questions or unknown:
        # Agents pass section names here; say where the per-section mapping actually lives.
        raise ValueError(
            f"问题ID无效或未关联本篇：{'、'.join(unknown) or '本篇没有登记问题'}。"
            f"批次问题按文章登记，本篇问题ID为{'、'.join(linked) or '无'}，省略--question-id即默认关联；"
            "不要传章节名。章节与Claim的对应写在20：候选事实表的“支持的大纲问题”和大纲逐项覆盖表的“候选事实ID”"
        )
    evidence = payload.setdefault("evidence", [])
    used = used_candidates(payload, project, article_id)
    require_ec1, language = request_fields(project, article_id)
    written: list[dict] = []
    held: list[dict] = []
    for claim_id in claim_ids:
        state = readiness(project, claim_id, require_ec1=require_ec1, target_language=language)
        if state["status"] != "可直接复用":
            held.append(state)
            continue
        row = build_row(project, payload, article_id=article_id, claim_id=claim_id,
                        question_ids=sorted(set(questions)), basis=basis)
        existing = next((item for item in evidence if isinstance(item, dict)
                         and item.get("claim_id") == claim_id
                         and item.get("disposition") == "复用已有Formal Claim"
                         and article_id in item.get("article_ids", [])), None)
        # The same fact read this run needs no reuse row beside it (one Claim's other facts still may).
        existing = existing or same_fact_row(evidence, article_id, claim_id,
                                             row.get("verified_target_excerpt") or row.get("original_excerpt"))
        if existing:
            # Idempotent: a re-run only widens the linked questions.
            existing["question_ids"] = sorted(set(existing.get("question_ids", [])) | set(row["question_ids"]))
            written.append(existing)
            continue
        number = max(used | {0}) + 1
        used.add(number)
        row["candidate_id"] = f"CF-{number:03d}"
        problems = validate_evidence(row)
        provenance = validate_claim_provenance(ledger, row)
        if problems or provenance:
            raise ValueError(f"{claim_id}不能按复用登记：" + "；".join(problems + ([provenance] if provenance else []))
                             + "。需要回源或更新Claim时按正常检索流程处理")
        evidence.append(row)
        written.append(row)
    if written:
        tmp = ledger.with_suffix(ledger.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(ledger)
    return written, held


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--claim-id", action="append", required=True, help="可重复；每个Claim登记一条复用记录")
    parser.add_argument("--question-id", action="append", help="默认关联本篇全部已登记问题")
    parser.add_argument("--basis", default="", help="该Claim为何覆盖本篇问题、为何未触发回源复核（登记时必填）")
    parser.add_argument("--check", action="store_true", help="只检查这些Claim是否满足当前复用要求，不写账本")
    parser.add_argument("--complete", type=Path,
                        help="补齐登记：JSON {Claim ID: {字段: 值}}，按claim_complete_draft确认后提交；补齐后在同一命令登记")
    args = parser.parse_args()
    project = args.project.resolve()
    require_ec1, language = request_fields(project, args.article_id)
    try:
        if args.check:
            held = [readiness(project, c, require_ec1=require_ec1, target_language=language) for c in args.claim_id]
            rows: list[dict] = []
        else:
            if args.complete:
                completions = json.loads(args.complete.read_text(encoding="utf-8-sig"))
                if not isinstance(completions, dict) or not all(isinstance(v, dict) for v in completions.values()):
                    raise ValueError("--complete须为JSON对象：{Claim ID: {字段: 值}}")
                for path in complete_claims(project, completions, article_id=args.article_id,
                                            require_ec1=require_ec1, target_language=language):
                    print(f"completed={path.relative_to(project).as_posix()}")
            rows, held = record(project, args.batch_id, args.article_id, args.claim_id, args.basis, args.question_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"claim_reuse_error={exc}", file=sys.stderr)
        return 1
    for row in rows:
        print(f"recorded={row['candidate_id']} {row['claim_id']} disposition={row['disposition']}")
    for state in held:
        detail = "；".join(state["problems"]) or "满足当前复用要求"
        print(f"claim={state['claim_id']} status={state['status']} problems={detail}")
        if state["action"]:
            print(f"claim_next={state['action']}")
        if state["status"] == "补齐登记":
            draft = completion_draft(project, state["claim_id"], require_ec1=require_ec1, target_language=language)
            print("claim_complete_draft=" + json.dumps(draft, ensure_ascii=False))
    if rows:
        print("next=重新运行run_knowledge_workflow.py；已登记的复用不需要再抓取网页或重读原件")
    return 3 if any(state["status"] != "可直接复用" for state in held) else 0


if __name__ == "__main__":
    raise SystemExit(main())
