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


REQUIRED_EVIDENCE = (
    "batch_id", "article_ids", "question_ids", "candidate_id", "claim_id",
    "source_id", "source_type", "source_path_or_url", "exact_location",
    "source_sha256", "original_excerpt", "retrieved_at", "retrieval_run_id", "scope", "disposition",
)
ALLOWED_DISPOSITIONS = {"本轮核验通过", "进入治理", "排除", "未命中"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_key(item: dict[str, Any]) -> str:
    value = item.get("source_sha256") or item.get("source_path_or_url")
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def validate_evidence(item: dict[str, Any]) -> list[str]:
    errors = [key for key in REQUIRED_EVIDENCE if not item.get(key)]
    if not isinstance(item.get("article_ids"), list) or not item["article_ids"]:
        errors.append("article_ids")
    if not isinstance(item.get("question_ids"), list) or not item["question_ids"]:
        errors.append("question_ids")
    if item.get("disposition") not in ALLOWED_DISPOSITIONS:
        errors.append("disposition")
    if item.get("disposition") == "本轮核验通过":
        if not item.get("verified_target_excerpt"):
            errors.append("verified_target_excerpt (本轮核验通过时必填)")
        if not item.get("claim_id"):
            errors.append("claim_id (本轮核验通过时必填)")
    elif item.get("verified_target_excerpt") and not item.get("claim_id"):
        errors.append("verified_target_excerpt requires claim_id")
    return errors


def evidence_key(item: dict[str, Any]) -> tuple[str, str]:
    """Deduplicate one candidate fact, while sharing a source read.

    A source can contain many independent facts.  Using only the source hash
    as the row key silently discarded all but the first fact from that source.
    """
    source = item.get("source_sha256") or item.get("source_path_or_url")
    return str(source), str(item.get("candidate_id", ""))


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


def validate_claim_provenance(path: Path, item: dict[str, Any]) -> str | None:
    """Reject a passed evidence row whose Claim is absent or from another source."""
    claim_id = str(item.get("claim_id") or "").strip()
    if not claim_id or item.get("disposition") != "本轮核验通过":
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
        claim_text = claim_path.read_text(encoding="utf-8-sig") if claim_path else ""
        if excerpt not in claim_text:
            return (
                f"claim_id={claim_id} 的核验原文未逐字出现在Formal Claim中："
                f"候选={item.get('candidate_id')}；请先沉淀或修复Claim后再生成30/35"
            )
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


def ledger_errors(path: Path, batch_id: str) -> list[str]:
    """Read-only batch gate used before article material is rendered."""
    if not path.is_file():
        return [f"批次账本不存在：{batch_id}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"批次账本无法读取：{exc}"]
    if payload.get("batch_id") != batch_id:
        return [f"批次账本batch_id不匹配：期望={batch_id}，实际={payload.get('batch_id', '')}"]
    errors: list[str] = []
    referenced_articles = {str(row.get("article_id", "")) for row in payload.get("articles", []) if isinstance(row, dict)}
    referenced_questions = {str(row.get("question_id", "")) for row in payload.get("questions", []) if isinstance(row, dict)}
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        errors.append("批次账本尚未形成证据记录；禁止生成30/35")
        return errors
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for index, item in enumerate(evidence, 1):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}]不是对象")
            continue
        errors.extend(f"evidence[{index}].{error}" for error in validate_evidence(item))
        provenance = validate_claim_provenance(path, item)
        if provenance:
            errors.append(f"evidence[{index}].{provenance}")
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
    if payload.get("status") != "evidence_ready":
        errors.append(f"批次证据状态不是evidence_ready：{payload.get('status', '空')}")
    return list(dict.fromkeys(errors))


def build(args: argparse.Namespace) -> int:
    path = Path(args.ledger).resolve()
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "schema": "MAK-BATCH-1.0", "batch_id": args.batch_id,
        "created_at": now(), "updated_at": now(), "articles": [],
        "questions": [], "evidence": [], "governance": [],
    }
    if payload.get("batch_id") != args.batch_id:
        raise SystemExit("批次账本 batch_id 不匹配")
    errors: list[str] = []
    by_candidate: dict[tuple[str, str], dict[str, Any]] = {}
    source_reads: dict[str, dict[str, Any]] = {}
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
        source_reads.setdefault(source_key(item), {
            "source_id": item.get("source_id"),
            "source_type": item.get("source_type"),
            "source_path_or_url": item.get("source_path_or_url"),
            "source_sha256": item.get("source_sha256"),
            "retrieved_at": item.get("retrieved_at"),
            "retrieval_run_id": item.get("retrieval_run_id"),
        })
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
    if errors:
        raise SystemExit("批次证据账本校验失败：\n- " + "\n- ".join(errors))
    payload["evidence"] = list(by_candidate.values())
    payload["source_reads"] = list(source_reads.values())
    if payload["evidence"]:
        payload["status"] = "evidence_ready"
    payload["updated_at"] = now()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
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
            for claim_id in ("CLM-1", "CLM-2"):
                (formal_root / f"{claim_id}.md").write_text(
                    f"- Claim ID：{claim_id}\n- 来源链接：https://example.test\n\n"
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
