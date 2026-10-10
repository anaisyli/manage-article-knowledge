#!/usr/bin/env python3
"""Run one v0.6.1 batch knowledge workflow from a single stable entry point.

The individual v0.6.1 scripts deliberately keep narrow responsibilities.  This
module is the orchestration boundary: callers provide only a project and a
batch id, while the coordinator derives the ledger path, validates/rebuilds
the batch, attempts deterministic article-package recovery, and emits a
machine-readable continuation receipt.

This command never treats a missing input, an empty evidence list, a gate
failure, or a retryable exception as a terminal workflow event.  It persists
the state next to the batch ledger so a later invocation can resume without
guessing paths or reusing an archived task.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SCHEMA = "MAK-WORKFLOW-1"
# Only these states may be touched by the knowledge-preparation coordinator.
# Faithfulness and completed archives are historical outputs and must never be
# selected as a recovery target for a new batch run.
CANONICAL_STATES = ("10_进行中", "20_等待终稿")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_batch_id(batch_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(batch_id).strip())
    return value.strip("-") or "batch"


def conventional_ledger(project: Path, batch_id: str) -> Path:
    return project / "04_文章任务" / "批次运行" / f"{safe_batch_id(batch_id)}.json"


def resolve_ledger(project: Path, batch_id: str) -> Path:
    """Resolve a batch ledger without asking the caller for ``--ledger``.

    A conventional path wins.  The small fallback scan supports ledgers created
    before the current naming helper, but only accepts an exact batch id and a
    single match; it never selects a historical or similarly named batch.
    """
    expected = conventional_ledger(project, batch_id)
    if expected.is_file():
        return expected
    root = project / "04_文章任务" / "批次运行"
    matches: list[Path] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and str(payload.get("batch_id", "")) == batch_id:
                matches.append(path)
    if len(matches) == 1:
        return matches[0]
    return expected


def state_path_for(ledger: Path) -> Path:
    return ledger.with_name(ledger.stem + ".workflow.json")


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def persist_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Persist a continuation receipt and run the shared terminal classifier."""
    from workflow_terminal import decide

    decision = decide(reason=str(receipt.get("workflow_state") or "handoff_waiting_knowledge_fix"))
    receipt["terminal"] = decision.terminal
    receipt["terminal_decision"] = {
        "terminal": decision.terminal,
        "reason": decision.reason,
        "next_action": decision.next_action,
    }
    receipt["ended_at"] = now()
    atomic_write(path, receipt)


def parse_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def article_id_from_request(path: Path) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    match = re.search(r"(?m)^\s*[-*]\s*文章ID[：:]\s*(\S+)", text)
    return match.group(1).strip() if match else ""


def find_task(project: Path, article_id: str) -> Path | None:
    """Find only the current canonical task for one article identity."""
    candidates: list[Path] = []
    for state in CANONICAL_STATES:
        root = project / "04_文章任务" / state
        if not root.is_dir():
            continue
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            request_id = article_id_from_request(directory / "10_文章知识需求.md")
            if request_id == article_id or directory.name == article_id or directory.name.startswith(article_id + "_"):
                candidates.append(directory)
    if len(candidates) == 1:
        return candidates[0]
    # Multiple current copies are an identity conflict; do not guess.
    return None


def capture_stdout(callable_obj: Any, *args: Any, **kwargs: Any) -> tuple[Any, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        return callable_obj(*args, **kwargs), buffer.getvalue()


def run_batch_validation(ledger: Path, batch_id: str, retry_limit: int) -> dict[str, Any]:
    """Normalize a ledger and return validation findings without leaking prints."""
    import argparse as _argparse
    import batch_knowledge_run

    attempts = 0
    output = ""
    last_error = ""
    while attempts <= max(0, retry_limit):
        attempts += 1
        try:
            _, output = capture_stdout(
                batch_knowledge_run.build,
                _argparse.Namespace(ledger=ledger, batch_id=batch_id),
            )
            last_error = ""
            break
        except SystemExit as exc:
            last_error = str(exc)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    payload = parse_json(ledger)
    if payload is None:
        return {
            "ok": False,
            "attempts": attempts,
            "error": last_error or f"批次账本无法读取：{ledger}",
            "payload": None,
            "output": output,
        }
    # A second read-only gate gives the caller the exact provenance errors;
    # build() only raises on its own structural validation path.
    errors = batch_knowledge_run.ledger_errors(ledger, batch_id)
    return {
        "ok": not errors,
        "attempts": attempts,
        "error": last_error,
        "errors": errors,
        "payload": payload,
        "output": output,
    }


def recover_and_gate(project: Path, task: Path, retry_limit: int) -> dict[str, Any]:
    """Run deterministic recovery, then return current package errors."""
    from article_state import article_package_errors
    from recover_article_package import recover_task

    before = article_package_errors(task)
    recovery: dict[str, Any] = {"changed": [], "actions": [], "unresolved": []}
    if before:
        try:
            result = recover_task(task, max_passes=max(1, retry_limit + 1))
            recovery = {
                "changed": list(result.changed),
                "actions": list(result.actions),
                "unresolved": list(result.unresolved),
            }
        except Exception as exc:  # keep the workflow resumable
            recovery["unresolved"] = [f"自动恢复异常：{exc}"]
    try:
        after = article_package_errors(task)
    except Exception as exc:
        after = [f"文章包门禁执行失败：{exc}"]
    return {"before": before, "after": after, "recovery": recovery}


def article_snapshot(project: Path, article: dict[str, Any], retry_limit: int) -> dict[str, Any]:
    article_id = str(article.get("article_id", "")).strip()
    if not article_id:
        return {
            "article_id": "",
            "state": "identity_error",
            "terminal": False,
            "errors": ["批次文章缺少article_id；无法安全定位任务"],
            "next_action": "修复批次文章身份后重新运行本入口",
        }
    task = find_task(project, article_id)
    if task is None:
        return {
            "article_id": article_id,
            "state": "task_initialization",
            "terminal": False,
            "errors": ["当前文章没有唯一的活动任务目录"],
            "next_action": "由writing_bridge.prepare建立本轮10_进行中任务；完成后重新运行本入口",
        }
    package = recover_and_gate(project, task, retry_limit)
    errors = list(package["after"])
    return {
        "article_id": article_id,
        "task": str(task),
        "task_state": task.parent.name,
        "state": "ready_candidate" if not errors else "knowledge_repair_required",
        "terminal": False,
        "errors": errors,
        "recovery": package["recovery"],
        "next_action": (
            "运行advance_ready_tasks.py并逐篇核对issue_writing_ready.py回执"
            if not errors and task.parent.name == "10_进行中"
            else "继续补齐当前文章15/20/30/35或来源闭环后重新运行本入口"
        ),
    }


def advance_and_issue_ready(project: Path, articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Move validated tasks and issue the per-article writing gate in one pass."""
    from advance_ready_tasks import advance_project_detailed
    from handoff_contract import current_version
    from issue_writing_ready import issue

    outcome = advance_project_detailed(project)
    issued: list[dict[str, Any]] = []
    failures: list[str] = []
    article_ids = {
        str(item.get("article_id", "")).strip()
        for item in articles
        if isinstance(item, dict) and item.get("article_id")
    }
    for task in outcome.get("moved", []):
        request = task / "10_文章知识需求.md"
        article_id = article_id_from_request(request)
        if article_ids and article_id not in article_ids:
            continue
        try:
            _, output = capture_stdout(
                issue,
                argparse.Namespace(
                    handoff_contract_version=current_version(),
                    project=project,
                    article_id=article_id,
                    external_task_key=None,
                ),
            )
            issued.append({"article_id": article_id, "task": str(task), "output": output})
        except (SystemExit, OSError, ValueError) as exc:
            failures.append(f"{article_id or task}: {exc}")
    return {
        "moved": [str(path) for path in outcome.get("moved", [])],
        "blocked": [
            {"task": str(task), "errors": list(errors)}
            for task, errors in outcome.get("blocked", [])
        ],
        "issued": issued,
        "errors": failures,
    }


def run_workflow(project: Path, batch_id: str, *, retry_limit: int = 2) -> dict[str, Any]:
    project = project.expanduser().resolve()
    ledger = resolve_ledger(project, batch_id)
    state_path = state_path_for(ledger)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "batch_id": batch_id,
        "project": str(project),
        "ledger": str(ledger),
        "started_at": now(),
        "terminal": False,
        "workflow_state": "batch_discovery",
        "retry_limit": retry_limit,
        "retry_count": 0,
        "articles": [],
        "errors": [],
    }
    if not project.is_dir():
        receipt.update({
            "workflow_state": "tool_retryable_failure",
            "errors": [f"Obsidian项目路径不存在：{project}"],
            "next_action": "确认项目路径可读后重新运行本入口",
        })
        persist_receipt(state_path, receipt)
        return receipt
    payload = parse_json(ledger)
    if payload is None:
        receipt.update({
            "workflow_state": "batch_initialization",
            "errors": [f"批次账本不存在或无法读取：{ledger}"],
            "next_action": "先由writing_bridge.prepare登记本批文章；本入口会在下次运行自动接续",
        })
        persist_receipt(state_path, receipt)
        return receipt
    actual_batch = str(payload.get("batch_id", ""))
    if actual_batch != batch_id:
        receipt.update({
            "workflow_state": "identity_error",
            "errors": [f"批次账本batch_id不匹配：期望={batch_id}，实际={actual_batch}"],
            "next_action": "修复批次身份后重新运行本入口",
        })
        persist_receipt(state_path, receipt)
        return receipt

    validation = run_batch_validation(ledger, batch_id, retry_limit)
    receipt["retry_count"] = int(validation.get("attempts", 0)) - 1
    receipt["batch"] = {
        "status": validation.get("payload", payload).get("status"),
        "evidence_count": len(validation.get("payload", payload).get("evidence", []) or []),
        "validation_errors": validation.get("errors", []),
    }
    if validation.get("error") and not validation.get("payload"):
        receipt.update({
            "workflow_state": "tool_retryable_failure",
            "errors": [str(validation["error"])],
            "next_action": "修复账本读取/参数问题后重新运行本入口；不要根据退出码结束批次",
        })
        persist_receipt(state_path, receipt)
        return receipt

    evidence = validation.get("payload", payload).get("evidence", []) or []
    if not evidence:
        receipt.update({
            "workflow_state": "source_collection",
            "errors": ["批次账本尚未形成证据记录；不能生成30/35或进入写作"],
            "next_action": "按本批问题继续读取来源、沉淀Formal Claim并写入证据账本；完成后重新运行本入口",
        })
    elif validation.get("errors"):
        receipt.update({
            "workflow_state": "claim_resolution",
            "errors": list(validation["errors"]),
            "next_action": "按每条来源/Claim错误修复来源闭环，再重新运行本入口；不得把批次错误当作终点",
        })
    else:
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            articles = []
        receipt["articles"] = [article_snapshot(project, item, retry_limit) for item in articles if isinstance(item, dict)]
        blockers = [
            error
            for article in receipt["articles"]
            for error in article.get("errors", [])
        ]
        if blockers:
            receipt.update({
                "workflow_state": "article_knowledge_preparation",
                "errors": blockers,
                "next_action": "按文章级回执逐篇继续生成或恢复15/20/30/35；一篇阻塞不停止其他文章",
            })
        else:
            try:
                handoff = advance_and_issue_ready(project, receipt["articles"])
            except (OSError, ValueError, RuntimeError) as exc:
                handoff = {"moved": [], "blocked": [], "issued": [], "errors": [str(exc)]}
            receipt["handoff"] = handoff
            if handoff["errors"] or handoff["blocked"]:
                receipt.update({
                    "workflow_state": "writing_ready_pending",
                    "errors": list(handoff["errors"]) + [
                        error
                        for item in handoff["blocked"]
                        for error in item["errors"]
                    ],
                    "next_action": "按文章级writing_gate_result.json继续恢复；只有writing_gate_status=ready才交给写作Skill",
                })
            elif handoff["issued"] or handoff["moved"]:
                receipt.update({
                    "workflow_state": "writing_ready_issued",
                    "errors": [],
                    "next_action": "写作Skill读取并核对每篇writing_ready.json后开始写作；终稿返回后回到知识库",
                })
            else:
                receipt.update({
                    "workflow_state": "writing_ready_pending",
                    "errors": [],
                    "next_action": "没有可迁移文章；读取当前文章级回执并继续知识准备，不得以moved_count=0结束",
                })
    persist_receipt(state_path, receipt)
    return receipt


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mak-workflow-") as temp:
        project = Path(temp) / "P-TEST_测试知识库_v0.6"
        ledger = conventional_ledger(project, "B-SELF")
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({
            "schema": "MAK-BATCH-1.0", "batch_id": "B-SELF",
            "status": "collecting_requests", "articles": [{"article_id": "ART-001"}],
            "questions": [], "evidence": [], "governance": [],
        }, ensure_ascii=False), encoding="utf-8")
        result = run_workflow(project, "B-SELF")
        assert result["terminal"] is False
        assert result["workflow_state"] == "source_collection"
        state = parse_json(state_path_for(ledger))
        assert state and state["terminal"] is False
        # The caller never has to provide --ledger; the stable entry point
        # resolves it from project + batch id.
        assert result["ledger"] == str(ledger)
    print("self-test=passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--batch-id")
    parser.add_argument("--retry-limit", type=int, default=2)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project or not args.batch_id:
        parser.error("需要 --project 和 --batch-id；无需手工提供 --ledger")
    result = run_workflow(args.project, args.batch_id, retry_limit=max(0, args.retry_limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Intermediate and recoverable states intentionally return zero.  The
    # structured terminal=false receipt is the workflow protocol.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
