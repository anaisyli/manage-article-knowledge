#!/usr/bin/env python3
"""Create and validate the v0.6.1 batch evidence ledger.

This ledger is the single source for deduplicated retrieval and per-article
material rendering. It does not fetch websites or create Formal Claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote


CURRENT_EVIDENCE_REQUIRED = (
    "batch_id", "article_ids", "question_ids", "candidate_id", "claim_id",
    "source_id", "source_type", "source_path_or_url", "exact_location",
    "source_sha256", "original_excerpt", "retrieved_at", "retrieval_run_id", "scope", "disposition",
)
REUSE_EVIDENCE_REQUIRED = (
    "batch_id", "article_ids", "question_ids", "candidate_id", "claim_id",
    "source_id", "source_type", "source_path_or_url", "exact_location", "original_excerpt",
    "verified_target_excerpt", "scope", "disposition", "evidence_origin", "claim_verified_at", "reuse_basis",
)
ALLOWED_DISPOSITIONS = {"本轮核验通过", "复用已有Formal Claim", "进入治理", "排除", "未命中"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_key(item: dict[str, Any]) -> str:
    value = item.get("source_sha256") or item.get("source_path_or_url")
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def validate_evidence(item: dict[str, Any]) -> list[str]:
    disposition = item.get("disposition")
    required = REUSE_EVIDENCE_REQUIRED if disposition == "复用已有Formal Claim" else CURRENT_EVIDENCE_REQUIRED
    errors = [key for key in required if key != "claim_id" and not item.get(key)]
    if not isinstance(item.get("article_ids"), list) or not item["article_ids"]:
        errors.append("article_ids")
    if not isinstance(item.get("question_ids"), list) or not item["question_ids"]:
        errors.append("question_ids")
    if item.get("disposition") not in ALLOWED_DISPOSITIONS:
        errors.append("disposition")
    if disposition == "本轮核验通过":
        if not item.get("verified_target_excerpt"):
            errors.append("verified_target_excerpt (本轮核验通过时必填)")
        if not item.get("claim_id"):
            errors.append("claim_id (本轮核验通过时必填)")
    elif disposition == "复用已有Formal Claim":
        if item.get("evidence_origin") != "Formal Claim":
            errors.append("evidence_origin (复用Claim时必须为Formal Claim)")
        if item.get("retrieved_at") or item.get("retrieval_run_id"):
            errors.append("复用已有Formal Claim不得伪装成本轮来源读取")
        if not item.get("claim_id"):
            errors.append("claim_id (复用Formal Claim时必填)")
    elif item.get("verified_target_excerpt") and not item.get("claim_id"):
        errors.append("verified_target_excerpt requires claim_id")
    if item.get("disposition") in {"排除", "未命中", "进入治理"} and not item.get("disposition_basis"):
        errors.append("disposition_basis (非采用处置须记录具体依据)")
    if item.get("disposition") == "进入治理" and not item.get("governance_entry"):
        errors.append("governance_entry (进入治理须有事项入口)")
    return errors


def fact_key(claim_id: str, excerpt: str) -> tuple[str, str]:
    """One fact: the same Formal Claim and the same continuous source text.

    A Claim may hold several facts, so the Claim ID alone never identifies one; a second read of the
    same text is another verification of that fact, not another candidate.
    """
    return str(claim_id or "").strip(), " ".join(str(excerpt or "").split())


def same_fact_row(evidence: list[Any], article_id: str, claim_id: str, excerpt: str) -> dict[str, Any] | None:
    """The adopted row already holding this fact for this article (P-005-ART-20261030-001 CF-002/003/004)."""
    key = fact_key(claim_id, excerpt)
    for row in evidence:
        if (isinstance(row, dict) and article_id in row.get("article_ids", [])
                and row.get("disposition") in {"本轮核验通过", "复用已有Formal Claim"}
                and fact_key(row.get("claim_id"), row.get("verified_target_excerpt") or row.get("original_excerpt")) == key):
            return row
    return None


def pending_captures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One shared closure rule for the synchronizer and both ledger gates."""
    output = []
    for row in payload.get("capture_inbox", []):
        if not isinstance(row, dict) or row.get("status") == "已由唯一Formal Claim自动闭环":
            continue
        closed = any(
            item.get("candidate_id") == row.get("candidate_id")
            and row.get("article_id") in item.get("article_ids", [])
            and item.get("retrieval_run_id") == row.get("retrieval_run_id")
            and item.get("source_path_or_url") == row.get("source_path_or_url")
            and item.get("original_excerpt") == row.get("original_excerpt")
            and item.get("disposition") in {"排除", "未命中", "进入治理"}
            and row.get("status") == item.get("disposition")
            and not validate_evidence(item)
            for item in payload.get("evidence", []) if isinstance(item, dict)
        )
        if not closed:
            output.append(row)
    return output


def evidence_key(item: dict[str, Any]) -> tuple[str, str]:
    """Deduplicate one candidate fact, while sharing a source read.

    A source can contain many independent facts.  Using only the source hash
    as the row key silently discarded all but the first fact from that source.
    """
    source = (item.get("source_sha256") or item.get("source_path_or_url"), item.get("retrieval_run_id", ""))
    return str(source), str(item.get("candidate_id", ""))


def current_binding_errors(path: Path, payload: dict[str, Any]) -> list[str]:
    from sync_website_evidence import current_tasks, current_run
    tasks = current_tasks(path.parents[2], include_completed=True)
    errors: list[str] = []
    for article in payload.get("articles", []):
        if not isinstance(article, dict):
            continue  # Legacy ledgers are still readable.
        article_id = str(article.get("article_id", ""))
        task = tasks.get(article_id)
        try:
            if task is None:
                if not article.get("article_version"):
                    continue  # Pre-run ledgers without a modern task.
                raise ValueError("没有唯一当前活动任务")
            run_id = current_run(task, article, str(payload.get("batch_id", "")))
            if article.get("revision_mode") == "knowledge_reuse_rewrite":
                continue  # Explicit reuse keeps its archived evidence after identity checks.
            for key in ("evidence", "capture_inbox", "source_reads"):
                for row in payload.get(key, []):
                    if not isinstance(row, dict):
                        continue  # Structural validation reports malformed rows.
                    linked = row.get("article_ids") or [row.get("article_id")]
                    reused_claim = (
                        key == "evidence"
                        and row.get("disposition") == "复用已有Formal Claim"
                        and row.get("evidence_origin") == "Formal Claim"
                    )
                    if article_id in linked and not reused_claim and row.get("retrieval_run_id") != run_id:
                        raise ValueError(f"{key}候选{row.get('candidate_id', '')}未绑定当前运行ID：{run_id}")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"{article_id} 批次运行身份错误：{exc}")
    return errors


def _normalize_source(value: str) -> str:
    value = unquote(str(value or "").strip()).replace("\\", "/")
    match = re.search(r"\]\(([^)]+)\)", value)
    if match:
        value = match.group(1).strip()
    return value.rstrip("/ ").casefold()


def _claim_source(project: Path, claim_id: str) -> str:
    marker = re.compile(
        r"^\s*[-*]\s*Claim ID[：:]\s*" + re.escape(claim_id) + r"\s*$",
        re.MULTILINE,
    )
    field = re.compile(r"^\s*[-*]\s*来源链接[：:]\s*(.*?)\s*$", re.MULTILINE)
    root = project / "03_正式知识"
    if not root.is_dir():
        return ""
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        match = marker.search(text)
        if not match:
            continue
        next_claim = re.search(r"^\s*[-*]\s*Claim ID[：:]", text[match.end():], re.MULTILINE)
        block = text[match.start(): match.end() + next_claim.start() if next_claim else len(text)]
        source = field.search(block)
        return source.group(1).strip() if source else ""
    return ""


def contains_excerpt(text: str, excerpt: str) -> bool:
    """Verbatim match; a multi-line excerpt is stored as "> "-prefixed quote lines, so also match those."""
    quoted = "\n".join(re.sub(r"^\s*>\s?", "", line).strip()
                       for line in text.splitlines() if line.lstrip().startswith(">"))
    return excerpt in text or excerpt in quoted


def validate_claim_provenance(path: Path, item: dict[str, Any]) -> str | None:
    """Reject a passed evidence row whose Claim is absent or from another source."""
    claim_id = str(item.get("claim_id") or "").strip()
    disposition = item.get("disposition")
    if not claim_id or disposition not in {"本轮核验通过", "复用已有Formal Claim"}:
        return None
    project = path.parents[2]
    formal_source = _claim_source(project, claim_id)
    if not formal_source:
        return f"claim_id={claim_id} 没有可读取的Formal Claim文件或来源链接"
    candidate_source = _normalize_source(str(item.get("source_path_or_url") or ""))
    claim_source = _normalize_source(formal_source)
    if candidate_source and claim_source and not (
        candidate_source in claim_source or claim_source in candidate_source
    ):
        return (
            f"claim_id={claim_id} 的候选事实来源与Formal Claim来源不一致："
            f"候选={item.get('source_path_or_url')}；Claim={formal_source}"
        )
    excerpt = str(item.get("verified_target_excerpt") or item.get("original_excerpt") or "").strip()
    if excerpt:
        claim_path = _claim_path(path.parents[2], claim_id)
        if claim_path is None:
            return f"claim_id={claim_id} 没有可读取的Formal Claim文件"
        claim_text = claim_path.read_text(encoding="utf-8-sig") if claim_path else ""
        from evidence_identity import field as identity_field, formal_errors, pre_use_review
        marker = re.search(r"^\s*[-*]\s*Claim ID[：:]\s*" + re.escape(claim_id) + r"\s*$", claim_text, re.M)
        if marker:
            block = claim_text[marker.start():]
            next_marker = re.search(r"^\s*[-*]\s*Claim ID[：:]", block[marker.end() - marker.start():], re.M)
            if next_marker:
                block = block[:marker.end() - marker.start() + next_marker.start()]
            identity_errors = formal_errors(block, item.get("evidence_context_version") == "EC-1")
            if identity_errors:
                return f"claim_id={claim_id}：" + "；".join(identity_errors)
        if not contains_excerpt(claim_text, excerpt):
            return (
                f"claim_id={claim_id} 的核验原文未逐字出现在Formal Claim中："
                f"候选={item.get('candidate_id')}；请先沉淀或修复Claim后再生成30/35"
            )
        if disposition == "复用已有Formal Claim":
            if not marker:
                return f"claim_id={claim_id} 的正式Claim区块无法定位"
            if identity_field(block, "状态") != "可用":
                return f"claim_id={claim_id} 当前不是可用状态，不能直接复用"
            claim_location = identity_field(block, "精确位置").strip()
            reuse_location = str(item.get("exact_location", "")).strip()
            if not claim_location or reuse_location != claim_location:
                return f"claim_id={claim_id} 复用记录的精确位置与Formal Claim不一致"
            knowledge_status = identity_field(claim_text, "知识状态")
            if knowledge_status and knowledge_status != "有效":
                return f"claim_id={claim_id} 知识文件状态不是有效，不能直接复用"
            # "条件" must name its triggers ("条件；来源更正……"), so read the decision word only.
            review = pre_use_review(claim_text)
            if review == "是":
                return f"claim_id={claim_id} 标记为使用前必须回源复核"
            if review not in {"", "否", "条件"}:
                return f"claim_id={claim_id} 的使用前复核字段无效"
            recent_check = identity_field(claim_text, "最近核验日期")
            if not recent_check:
                return f"claim_id={claim_id} 缺少最近核验日期，不能直接复用"
            if item.get("claim_verified_at") != recent_check:
                return f"claim_id={claim_id} 复用记录中的最近核验日期与正式Claim不一致"
            if not contains_excerpt(block, item.get("original_excerpt", "").strip()):
                return f"claim_id={claim_id} 复用记录的原文证据不在该Claim区块中"
            if not contains_excerpt(block, item.get("verified_target_excerpt", "").strip()):
                return f"claim_id={claim_id} 复用记录的目标语言证据不在该Claim区块中"
            if identity_field(block, "证据模板版本") == "EC-1":
                identity_errors = formal_errors(block, required=True)
                if identity_errors:
                    return f"claim_id={claim_id}：" + "；".join(identity_errors)
            if not str(item.get("reuse_basis", "")).strip():
                return f"claim_id={claim_id} 缺少本篇适用性和复核条件判断"
    return None


def _claim_path(project: Path, claim_id: str) -> Path | None:
    marker = re.compile(
        r"^\s*[-*]\s*Claim ID[：:]\s*" + re.escape(claim_id) + r"\s*$", re.MULTILINE
    )
    root = project / "03_正式知识"
    if not root.is_dir():
        return None
    for path in root.rglob("*.md"):
        if marker.search(path.read_text(encoding="utf-8-sig")):
            return path
    return None


def unresolved_claim_pronouns(project: Path, item: dict[str, Any]) -> str:
    """SK-V064-030: an EC-1 Claim entering a new 30 must say what its we/our/this… refer to.

    The audit resolves the subject of "We can manufacture…" through the 30's EC-1 block, which is
    copied from the Claim's 指代解析; a resolution that skips "we" leaves a correct fact unprovable.
    """
    claim_id = str(item.get("claim_id") or "").strip()
    if not claim_id:
        return ""
    from record_claim_reuse import _claim_path, claim_block, field, unresolved_pronouns
    claim_path = _claim_path(project, claim_id)
    if claim_path is None:
        return ""
    # Read the Claim itself: rows promoted from this run's captures carry no evidence_context_version.
    block = claim_block(claim_path.read_text(encoding="utf-8-sig"), claim_id)
    if field(block, "证据模板版本") != "EC-1":
        return ""
    missing = unresolved_pronouns(block)
    if not missing:
        return ""
    how = ("运行 record_claim_reuse.py --complete，按claim_complete_draft只改写指代解析"
           if item.get("disposition") == "复用已有Formal Claim"
           else "本轮新沉淀的Claim直接在Claim中改写指代解析（原文不变，归属证据SHA-256不变）")
    return (f"{claim_id}的指代解析没有说明原文中的{'、'.join(missing)}指谁或指什么；审核按30的证据归属判断主体，"
            f"说明缺失时正确的事实也会被判为未确认。{how}，再重跑本入口")


def ledger_errors(path: Path, batch_id: str, *, article_id: str | None = None) -> list[str]:
    """Read-only batch gate used before article material is rendered."""
    if not path.is_file():
        return [f"批次账本不存在：{batch_id}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"批次账本无法读取：{exc}"]
    if payload.get("batch_id") != batch_id:
        return [f"批次账本batch_id不匹配：期望={batch_id}，实际={payload.get('batch_id', '')}"]
    evidence = payload.get("evidence", [])
    if article_id is not None and isinstance(evidence, list):
        evidence = [row for row in evidence if isinstance(row, dict) and article_id in row.get("article_ids", [])]
    binding_payload = {**payload, "evidence": evidence}
    if article_id is not None:
        binding_payload["articles"] = [row for row in payload.get("articles", []) if row.get("article_id") == article_id]
        if not binding_payload["articles"]:
            return [f"文章未登记在批次账本：{article_id}"]
    errors: list[str] = []
    errors.extend(current_binding_errors(path, binding_payload))
    for item in payload.get("capture_sync_errors", []):
        if article_id is not None and any(str(item).startswith(str(row.get("article_id")) + " ") for row in payload.get("articles", []) if row.get("article_id") != article_id):
            continue
        errors.append(f"官网凭证同步失败：{item}")
    referenced_articles = {str(row.get("article_id", "")) for row in payload.get("articles", []) if isinstance(row, dict)}
    referenced_questions = {str(row.get("question_id", "")) for row in payload.get("questions", []) if isinstance(row, dict)}
    unresolved_captures = [row for row in pending_captures(payload) if article_id is None or row.get("article_id") == article_id]
    if unresolved_captures:
        errors.append(
            "批次仍有未闭环官网候选事实："
            + ", ".join(
                f"{row.get('article_id', '?')}/{row.get('candidate_id', '?')}"
                for row in unresolved_captures
            )
        )
    if not isinstance(evidence, list) or not evidence:
        errors.append("批次账本尚未形成证据记录；禁止生成30/35")
        return errors
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    # Only an article still before writing: an issued permission is not revoked by this rule.
    preparing = article_id is not None and any(
        (path.parents[2] / "04_文章任务/10_进行中").glob(f"{article_id}_*"))
    for index, item in enumerate(evidence, 1):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}]不是对象")
            continue
        errors.extend(f"evidence[{index}].{error}" for error in validate_evidence(item))
        provenance = validate_claim_provenance(path, item)
        if provenance:
            errors.append(f"evidence[{index}].{provenance}")
        elif article_id is not None and preparing:
            unresolved = unresolved_claim_pronouns(path.parents[2], item)
            if unresolved:
                errors.append(unresolved)
        if referenced_articles and any(str(value) not in referenced_articles for value in item.get("article_ids", [])):
            errors.append(f"evidence[{index}].article_ids引用未登记文章")
        if referenced_questions and any(str(value) not in referenced_questions for value in item.get("question_ids", [])):
            errors.append(f"evidence[{index}].question_ids引用未登记问题")
        key = evidence_key(item)
        previous = seen.get(key)
        if previous is not None:
            for field in ("original_excerpt", "verified_target_excerpt", "claim_id", "disposition"):
                if previous.get(field) != item.get(field):
                    errors.append(f"evidence[{index}].{field}与重复候选事实冲突：{item.get('candidate_id')}")
        else:
            seen[key] = item
    if article_id is None and payload.get("status") != "evidence_ready":
        errors.append(f"批次证据状态不是evidence_ready：{payload.get('status', '空')}")
    return list(dict.fromkeys(errors))


def build(args: argparse.Namespace) -> int:
    path = Path(args.ledger).resolve()
    payload = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {
        "schema": "MAK-BATCH-1.0", "batch_id": args.batch_id,
        "created_at": now(), "updated_at": now(), "articles": [],
        "questions": [], "evidence": [], "governance": [],
    }
    if payload.get("batch_id") != args.batch_id:
        raise SystemExit("批次账本 batch_id 不匹配")
    binding_errors = current_binding_errors(path, payload)
    if binding_errors:
        raise SystemExit("批次运行身份冲突；未改写账本：\n- " + "\n- ".join(binding_errors))
    errors: list[str] = []
    errors.extend(f"官网凭证同步失败：{item}" for item in payload.get("capture_sync_errors", []))
    by_candidate: dict[tuple[str, str], dict[str, Any]] = {}
    # Reads are checkpoints, not a derived view of accepted Claims. Preserve
    # unresolved source visits and their excerpts across failed validation.
    source_reads: dict[str, dict[str, Any]] = {
        json.dumps(row, ensure_ascii=False, sort_keys=True): row
        for row in payload.get("source_reads", []) if isinstance(row, dict)
    }
    referenced_articles = {
        str(item.get("article_id", ""))
        for item in payload.get("articles", [])
        if isinstance(item, dict)
    }
    referenced_questions = {
        str(item.get("question_id", ""))
        for item in payload.get("questions", [])
        if isinstance(item, dict)
    }
    for index, item in enumerate(payload.get("evidence", []), 1):
        item_errors = validate_evidence(item)
        errors.extend(f"evidence[{index}].{error}" for error in item_errors)
        provenance_error = validate_claim_provenance(path, item)
        if provenance_error:
            errors.append(f"evidence[{index}].{provenance_error}")
        if referenced_articles and any(str(value) not in referenced_articles for value in item.get("article_ids", [])):
            errors.append(f"evidence[{index}].article_ids references an unregistered article")
        if referenced_questions and any(str(value) not in referenced_questions for value in item.get("question_ids", [])):
            errors.append(f"evidence[{index}].question_ids references an unregistered question")
        if item.get("disposition") != "复用已有Formal Claim":
            read = {
                "source_id": item.get("source_id"),
                "source_type": item.get("source_type"),
                "source_path_or_url": item.get("source_path_or_url"),
                "source_sha256": item.get("source_sha256"),
                "retrieved_at": item.get("retrieved_at"),
                "retrieval_run_id": item.get("retrieval_run_id"),
            }
            # Do not add a less detailed duplicate of an already captured visit.
            if not any(all(row.get(key) == read.get(key) for key in ("source_path_or_url", "source_sha256", "retrieval_run_id")) for row in source_reads.values()):
                source_reads.setdefault(source_key(item) + str(item.get("retrieval_run_id", "")), read)
        key = evidence_key(item)
        existing = by_candidate.get(key)
        if existing is None:
            by_candidate[key] = item
            continue
        # Same candidate may be attached to several articles/questions.  Merge
        # those references, but reject conflicting fact text or dispositions.
        for field in ("original_excerpt", "verified_target_excerpt", "claim_id", "disposition"):
            if existing.get(field) != item.get(field):
                errors.append(f"evidence[{index}].{field} conflicts with duplicate candidate {item.get('candidate_id')}")
        existing["article_ids"] = sorted(set(existing.get("article_ids", [])) | set(item.get("article_ids", [])))
        existing["question_ids"] = sorted(set(existing.get("question_ids", [])) | set(item.get("question_ids", [])))
    unresolved_captures = pending_captures(payload)
    if unresolved_captures:
        errors.extend(
            f"官网候选事实尚未完成Claim闭环：{row.get('article_id', '?')}/{row.get('candidate_id', '?')}"
            for row in unresolved_captures
        )
    errors.extend(current_binding_errors(path, payload))
    for article_id in referenced_articles:
        if not any(article_id in row.get("article_ids", []) for row in by_candidate.values()):
            errors.append(f"{article_id} 尚未形成当前批次证据记录")
    payload["evidence"] = list(by_candidate.values())
    payload["source_reads"] = list(source_reads.values())
    payload["status"] = ("evidence_ready" if not errors else "evidence_incomplete") if payload["evidence"] else "collecting_requests"
    payload["validation_errors"] = list(dict.fromkeys(errors))
    payload["updated_at"] = now()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    if errors:
        raise SystemExit("批次证据账本校验失败：\n- " + "\n- ".join(errors))
    print(json.dumps({"ok": True, "batch_id": args.batch_id, "evidence_count": len(payload["evidence"]), "ledger": str(path)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--ledger")
    parser.add_argument("--batch-id")
    args = parser.parse_args()
    if args.self_test:
        with tempfile.TemporaryDirectory() as temp:
            project_root = Path(temp) / "DEMO_测试知识库_v0.6"
            ledger = project_root / "04_文章任务/批次运行/batch.json"
            ledger.parent.mkdir(parents=True)
            formal_root = project_root / "03_正式知识"
            formal_root.mkdir(parents=True)
            evidence_digest = hashlib.sha256("Fact one\nFact two".encode("utf-8")).hexdigest()
            for claim_id in ("CLM-1", "CLM-2"):
                (formal_root / f"{claim_id}.md").write_text(
                    f"- Claim ID：{claim_id}\n- 来源链接：https://example.test\n"
                    "- 证据模板版本：EC-1\n"
                    "- 证据归属主体：Example Company\n"
                    "- 证据归属对象：测试事实\n"
                    "- 指代解析：无\n"
                    "- 归属核验依据：测试官网页面正文\n"
                    "- 归属核验日期：2026-09-01\n"
                    "- 归属核验状态：已核验\n"
                    f"- 归属证据SHA-256：{evidence_digest}\n\n"
                    f"### 最小原文证据\n> Fact one\n> Fact two\n",
                    encoding="utf-8-sig",
                )
            payload = {
                "schema": "MAK-BATCH-1.0",
                "batch_id": "B-SELF",
                "articles": [{"article_id": "A-1"}, {"article_id": "A-2"}],
                "questions": [{"question_id": "Q-1"}, {"question_id": "Q-2"}],
                "evidence": [
                    {
                        "batch_id": "B-SELF", "article_ids": ["A-1"], "question_ids": ["Q-1"],
                        "candidate_id": "C-1", "claim_id": "CLM-1", "source_id": "S-1",
                        "source_type": "官网", "source_path_or_url": "https://example.test",
                        "source_sha256": "abc", "exact_location": "L1", "original_excerpt": "Fact one",
                        "verified_target_excerpt": "Fact one", "retrieved_at": "2026-09-24T00:00:00Z",
                        "retrieval_run_id": "R-1", "scope": "scope", "disposition": "本轮核验通过",
                    },
                    {
                        "batch_id": "B-SELF", "article_ids": ["A-2"], "question_ids": ["Q-2"],
                        "candidate_id": "C-2", "claim_id": "CLM-2", "source_id": "S-1",
                        "source_type": "官网", "source_path_or_url": "https://example.test",
                        "source_sha256": "abc", "exact_location": "L2", "original_excerpt": "Fact two",
                        "verified_target_excerpt": "Fact two", "retrieved_at": "2026-09-24T00:00:00Z",
                        "retrieval_run_id": "R-1", "scope": "scope", "disposition": "本轮核验通过",
                    },
                ],
                "governance": [],
            }
            ledger.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            build(argparse.Namespace(ledger=ledger, batch_id="B-SELF"))
            result = json.loads(ledger.read_text(encoding="utf-8"))
            assert len(result["evidence"]) == 2
            assert len(result["source_reads"]) == 1
            assert result["status"] == "evidence_ready"
        print("self-test=passed")
        return 0
    if not args.ledger or not args.batch_id:
        parser.error("the following arguments are required: --ledger, --batch-id")
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
