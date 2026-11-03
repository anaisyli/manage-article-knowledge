#!/usr/bin/env python3
"""Idempotently route current-batch website captures into the batch ledger.

Only captures that exactly match one current Formal Claim source and quote are
promoted to batch evidence. Other captures remain in capture_inbox for the
knowledge workflow to resolve; this module never invents or edits Claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit


CLAIM_MARKER = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)


def normalize_url(value: str) -> str:
    value = unquote(str(value or "").strip())
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return value.rstrip("/ ").casefold()
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), parts.query, ""))


def article_id_from_task(task: Path) -> str:
    path = task / "10_文章知识需求.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8-sig")
    match = re.search(r"(?m)^\s*[-*]\s*文章ID[：:]\s*(\S+)", text)
    return match.group(1).strip() if match else ""


def target_language_from_task(task: Path) -> str:
    path = task / "10_文章知识需求.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8-sig")
    match = re.search(r"(?m)^\s*[-*]\s*目标语言[：:]\s*(.*?)\s*$", text)
    return match.group(1).strip() if match else ""


def current_tasks(project: Path, *, include_completed: bool = False) -> dict[str, Path]:
    found: dict[str, list[Path]] = {}
    states = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成") if include_completed else ("10_进行中", "20_等待终稿")
    for state in states:
        root = project / "04_文章任务" / state
        if not root.is_dir():
            continue
        for task in root.iterdir():
            if task.is_dir():
                article_id = article_id_from_task(task)
                if article_id:
                    found.setdefault(article_id, []).append(task)
    return {article_id: paths[0] for article_id, paths in found.items() if len(paths) == 1}


def question_map(payload: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in payload.get("questions", []):
        if not isinstance(row, dict):
            continue
        question_id = str(row.get("question_id", "")).strip()
        for article_id in row.get("article_ids", []):
            if question_id:
                result.setdefault(str(article_id), []).append(question_id)
    return result


def parse_field(block: str, field: str) -> str:
    match = re.search(r"(?m)^\s*[-*]\s*" + re.escape(field) + r"[：:]\s*(.*?)\s*$", block)
    return match.group(1).strip() if match else ""


def formal_claims(project: Path) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    root = project / "03_正式知识"
    if not root.is_dir():
        return claims
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        matches = list(CLAIM_MARKER.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.start():end]
            claims.append({
                "claim_id": match.group(1),
                "source": parse_field(block, "来源链接"),
                "scope": parse_field(block, "适用范围"),
                "status": parse_field(block, "状态"),
                "block": block,
                "path": str(path),
            })
    return claims


def find_matching_claim(claims: list[dict[str, str]], record: dict[str, Any]) -> tuple[dict[str, str] | None, str]:
    source = normalize_url(str(record.get("final_url") or record.get("requested_url") or ""))
    excerpt = str(record.get("excerpt", "")).strip()
    matches = [claim for claim in claims if normalize_url(claim["source"]) == source and excerpt and excerpt in claim["block"]]
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, "同一来源和原文匹配到多个Formal Claim，需知识库流程核对适用范围"
    return None, "没有来源链接和连续原文均一致的Formal Claim，需完成候选事实核验与Claim沉淀"


def load_records(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"官网正文抓取凭证必须是对象数组：{path}")
    return value


def current_run(task: Path, article: dict[str, Any], batch_id: str) -> str:
    """Bind captures to the committed article run; batch IDs are not run IDs."""
    request = (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
    version = parse_field(request, "当前版本")
    mode = parse_field(request, "任务模式")
    if article.get("article_id") != parse_field(request, "文章ID"):
        raise ValueError("批次文章ID与当前10不一致")
    for key, label in (("batch_id", "批次ID"), ("outline_id", "大纲ID"), ("outline_version", "大纲版本")):
        expected = parse_field(request, label)
        if key == "batch_id":
            if expected and expected != "不适用" and expected != batch_id:
                raise ValueError("批次ID与当前10不一致；请重放已提交的writing_request，不得手改账本身份")
            if article.get(key) and article[key] != batch_id:
                raise ValueError("批次成员batch_id与账本不一致")
        elif expected and article.get(key) != expected:
            raise ValueError(f"批次{key}与当前10不一致")
    normalize = lambda value: str(value).lstrip("vV")
    if version and normalize(article.get("article_version", "")) != normalize(version):
        raise ValueError("批次文章版本与当前10不一致；请用同一writing_request恢复批次登记")
    if mode and article.get("revision_mode") != mode:
        raise ValueError("批次任务模式与当前10不一致；请用同一writing_request恢复批次登记")
    if mode == "knowledge_reuse_rewrite":
        return ""  # No new retrieval run; version/outline/batch still checked.
    filename, key = ("知识重整运行.json", "refresh_run_id") if mode == "outline_refresh" else ("知识检索运行.json", "research_run_id")
    path = task / filename
    if path.is_file():
        run = json.loads(path.read_text(encoding="utf-8-sig"))
        run_id = str(run.get(key, "")).strip()
        if not run_id or run.get("article_id") != article["article_id"] or normalize(run.get("article_version", "")) != normalize(version):
            raise ValueError("当前检索运行记录的文章ID、版本或运行ID不一致")
        if article.get(key) != run_id:
            raise ValueError("批次未绑定当前文章检索运行ID；请用同一writing_request恢复批次登记")
        for field_key, expected in (("batch_id", batch_id), ("outline_id", parse_field(request, "大纲ID")),
                                    ("outline_version", parse_field(request, "大纲版本")), ("revision_mode", mode)):
            if field_key in run and run[field_key] != expected:
                raise ValueError(f"当前检索运行记录的{field_key}与10/批次不一致")
        return run_id
    if mode or version:
        raise ValueError("当前任务缺少本轮检索运行记录，不能使用批次ID替代")
    # Read-only compatibility for pre-run-sidecar ledgers only.
    return batch_id


def sync(project: Path, batch_id: str, ledger: Path) -> dict[str, Any]:
    project = project.resolve()
    payload = json.loads(ledger.read_text(encoding="utf-8-sig"))
    if payload.get("batch_id") != batch_id:
        raise ValueError(f"批次身份不匹配：期望={batch_id}，实际={payload.get('batch_id')}")
    from batch_knowledge_run import current_binding_errors
    identity_errors = current_binding_errors(ledger, payload)
    if identity_errors:
        # A wrong-run ledger is not repaired by syncing new captures into it.
        # Leave its bytes and every checkpoint intact for bridge replay.
        return {"batch_id": batch_id, "discovered": 0, "promoted": 0, "pending": 0,
                "unchanged": 0, "skipped": 0, "skipped_records": [],
                "unresolved_count": 0, "unresolved": [], "errors": identity_errors, "ledger": str(ledger)}
    tasks = current_tasks(project)
    qmap = question_map(payload)
    claims = formal_claims(project)
    evidence = payload.setdefault("evidence", [])
    inbox = payload.setdefault("capture_inbox", [])
    source_reads = payload.setdefault("source_reads", [])
    if not isinstance(evidence, list) or not isinstance(inbox, list) or not isinstance(source_reads, list):
        raise ValueError("批次 evidence/capture_inbox/source_reads 必须为数组")
    evidence_keys = {
        (str(row.get("article_ids", [""])[0]), str(row.get("candidate_id", "")))
        for row in evidence
        if isinstance(row, dict) and isinstance(row.get("article_ids"), list) and row.get("article_ids")
    }
    inbox_by_key = {(str(row.get("article_id", "")), str(row.get("candidate_id", ""))): row for row in inbox if isinstance(row, dict)}
    counts = {"discovered": 0, "promoted": 0, "pending": 0, "unchanged": 0, "skipped": 0}
    errors: list[str] = []
    skipped: list[dict[str, str]] = []
    allocated: dict[str, set[int]] = {}

    for article in payload.get("articles", []):
        if not isinstance(article, dict):
            continue
        article_id = str(article.get("article_id", "")).strip()
        task = tasks.get(article_id)
        if not article_id or task is None:
            errors.append(f"{article_id or '未知文章'} 没有唯一当前活动任务，未同步凭证")
            continue
        if article.get("revision_mode") == "knowledge_reuse_rewrite":
            continue
        try:
            run_id = current_run(task, article, batch_id)
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"{article_id} 运行身份不匹配：{exc}")
            continue
        request_candidates = ""
        if (task / "15_检索与知识准备记录.md").is_file():
            request_candidates = (task / "15_检索与知识准备记录.md").read_text(encoding="utf-8-sig")
        allocated[article_id] = {int(value) for value in re.findall(r"\bCF-(\d{3})\b", request_candidates)}
        for row in [*evidence, *inbox]:
            if row.get("article_id") == article_id or article_id in row.get("article_ids", []):
                match = re.fullmatch(r"CF-(\d{3})", str(row.get("candidate_id", "")))
                if match:
                    allocated[article_id].add(int(match[1]))
        manifest = task / "官网正文抓取凭证.json"
        if not manifest.is_file():
            continue
        try:
            records = load_records(manifest)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{article_id} 凭证读取失败：{exc}")
            continue
        for record in records:
            if str(record.get("refresh_run_id", "")).strip() != run_id:
                counts["skipped"] += 1
                skipped.append({"article_id": article_id, "reason": "凭证不是当前文章运行ID", "actual_run_id": str(record.get("refresh_run_id", "")), "expected_run_id": run_id})
                continue
            counts["discovered"] += 1
            read = {
                "article_ids": [article_id], "source_id": str(record.get("website_id") or "WEBSITE"),
                "source_type": str(record.get("source_type") or "客户官网"),
                "source_path_or_url": str(record.get("final_url") or record.get("requested_url") or ""),
                "source_sha256": str(record.get("response_sha256") or ""),
                "retrieved_at": str(record.get("fetched_at") or ""), "retrieval_run_id": run_id,
                "exact_location": str(record.get("position") or record.get("block_id") or ""),
                "original_excerpt": str(record.get("excerpt") or ""), "status": "已读取",
            }
            if read not in source_reads:
                source_reads.append(read)
            excerpt = str(record.get("excerpt", "")).strip()
            excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            source_url = normalize_url(str(record.get("final_url") or record.get("requested_url") or ""))
            capture_id = hashlib.sha256(f"{article_id}\0{run_id}\0{source_url}\0{excerpt_hash}".encode("utf-8")).hexdigest()
            prior = next((row for row in [*evidence, *inbox] if row.get("capture_id") == capture_id), None)
            candidate_id = str(prior["candidate_id"]) if prior else ""
            if not candidate_id and request_candidates:
                from preparation_record import validation_view
                from template_contract import table_rows
                ids = {cid for row in table_rows(validation_view(request_candidates), "## 官网正文核验")
                       if len(row) == 7 and source_url in normalize_url(row[1].split("；")[-1]) and row[4].strip() == excerpt
                       for cid in re.findall(r"\bCF-\d{3}\b", row[5])}
                if len(ids) == 1:
                    candidate_id = ids.pop()
            if not candidate_id:
                number = max(allocated[article_id], default=0) + 1
                if number > 999:
                    errors.append(f"{article_id} 候选事实流水号已满；未覆盖已有候选事实")
                    continue
                candidate_id = f"CF-{number:03d}"
                allocated[article_id].add(number)
            key = (article_id, candidate_id)
            existing = inbox_by_key.get(key)
            if key in evidence_keys:
                previous = next(row for row in evidence if article_id in row.get("article_ids", []) and row.get("candidate_id") == candidate_id)
                if any(previous.get(field) != value for field, value in (
                    ("source_sha256", read["source_sha256"]), ("original_excerpt", excerpt),
                    ("retrieval_run_id", run_id), ("source_path_or_url", read["source_path_or_url"]),
                )):
                    errors.append(f"{article_id}/{candidate_id} 当前来源指纹或证据变化；未沿用旧核验结果，需重新核验该候选")
                    continue
                counts["unchanged"] += 1
                continue
            claim, reason = find_matching_claim(claims, record)
            from evidence_identity import formal_errors, field as identity_field
            request_text = (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
            if claim:
                identity_errors = formal_errors(claim["block"], identity_field(request_text, "证据模板版本") == "EC-1")
                if identity_errors:
                    claim = None
                    reason = "；".join(identity_errors)
            questions = sorted(set(qmap.get(article_id, [])))
            if len(questions) != 1:
                claim = None
                reason = f"文章关联的问题数为{len(questions)}，无法唯一登记此凭证的问题映射"
            target_language = str(article.get("target_language") or target_language_from_task(task)).casefold()
            if claim and target_language not in {"english", "en", "英文"}:
                claim = None
                reason = "目标语言缺失或与当前原文不同；需要核验目标语言表达"
            if claim and claim["status"] != "可用":
                claim = None
                reason = "匹配Claim没有明确标记为可用；需要完成当前Claim状态核验"
            if claim:
                row = {
                    "batch_id": batch_id,
                    "article_ids": [article_id],
                    "question_ids": questions,
                    "candidate_id": candidate_id,
                    "capture_id": capture_id,
                    "claim_id": claim["claim_id"],
                    "source_id": str(record.get("website_id") or "WEBSITE"),
                    "source_type": str(record.get("source_type") or "客户官网"),
                    "source_path_or_url": str(record.get("final_url") or record.get("requested_url") or ""),
                    "source_sha256": str(record.get("response_sha256") or ""),
                    "exact_location": f"{record.get('title', '')} / {' > '.join(record.get('heading_path', []))} / {record.get('block_id', '')} / {record.get('position', '')}",
                    "original_excerpt": excerpt,
                    "verified_target_excerpt": excerpt,
                    "retrieved_at": str(record.get("fetched_at") or ""),
                    "retrieval_run_id": run_id,
                    "scope": claim["scope"] or "按当前Formal Claim适用范围",
                    "disposition": "本轮核验通过",
                }
                evidence.append(row)
                evidence_keys.add(key)
                if existing:
                    existing["status"] = "已由唯一Formal Claim自动闭环"
                counts["promoted"] += 1
            else:
                inbox_row = {
                    "article_id": article_id,
                    "candidate_id": candidate_id,
                    "capture_id": capture_id,
                    "question_ids": questions,
                    "source_path_or_url": str(record.get("final_url") or record.get("requested_url") or ""),
                    "source_sha256": str(record.get("response_sha256") or ""),
                    "exact_location": f"{record.get('title', '')} / {' > '.join(record.get('heading_path', []))} / {record.get('block_id', '')} / {record.get('position', '')}",
                    "original_excerpt": excerpt,
                    "retrieved_at": str(record.get("fetched_at") or ""),
                    "retrieval_run_id": run_id,
                    "status": "待候选事实核验",
                    "reason": reason,
                }
                immutable = ("article_id", "candidate_id", "source_path_or_url", "source_sha256", "original_excerpt", "retrieval_run_id")
                if existing and any(existing.get(field) != inbox_row.get(field) for field in immutable):
                    errors.append(f"{article_id}/{candidate_id} 已有待处理凭证与当前内容冲突；未覆盖旧记录")
                elif existing:
                    existing.update(inbox_row)
                    counts["unchanged"] += 1
                elif not existing:
                    inbox.append(inbox_row)
                    inbox_by_key[key] = inbox_row
                    counts["pending"] += 1

    if errors:
        payload["capture_sync_errors"] = errors
    else:
        payload.pop("capture_sync_errors", None)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = ledger.with_name(ledger.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ledger)
    from batch_knowledge_run import pending_captures
    unresolved = pending_captures(payload)
    return {"batch_id": batch_id, **counts, "skipped_records": skipped, "unresolved_count": len(unresolved), "unresolved": unresolved, "errors": errors, "ledger": str(ledger)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = sync(args.project, args.batch_id, args.ledger)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "terminal": False, "error": str(exc)}, ensure_ascii=False))
        return 0
    print(json.dumps({"ok": not result["errors"], "terminal": False, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
