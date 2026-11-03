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
# Article states whose next step is "fix the named records, then rerun this entry".
RERUN_STATES = {"article_records_required", "knowledge_repair_required", "claim_resolution"}


def rerun_command(project: Path, batch_id: str) -> str:
    """The exact command an agent runs next, so it never has to rebuild arguments from help text."""
    return f'python -X utf8 "{SCRIPT_DIR / "run_knowledge_workflow.py"}" --project "{project}" --batch-id {batch_id}'


def post_writing_action(task: Path, article_id: str) -> tuple[str, str]:
    """(stage, next_action) for a task past the knowledge stage.

    P-005-ART-20261029-001: the audit result was in the 50's result directory, but this
    receipt only said "按交接合同继续审核与导入"; the agent looked for the result in the
    batch ledger, did not find it and stopped without importing.
    """
    if task.parent.name == "40_已完成":
        return "completed", "本篇已完成导入，无需操作"
    record = task / "50_文章知识使用与Faithfulness记录.md"
    text = record.read_text(encoding="utf-8-sig") if record.is_file() else ""
    match = re.search(r"(?m)^\s*[-*]\s*指定审核结果目录[：:]\s*(.*?)\s*$", text)
    result_dir = Path(match.group(1)) if match and match.group(1) not in {"", "不适用", "未导入"} else None
    if result_dir is None or not (result_dir / f"{article_id}-judgments.json").is_file():
        where = f"结果目录{result_dir}" if result_dir else "50指定的结果目录"
        return "awaiting_faithfulness", (f"本篇终稿已交审核，{where}尚无审核结果；由审核Skill按faithfulness_request执行，"
                                         "结果写入后重跑本入口，不要重跑知识准备")
    importer, digest = SCRIPT_DIR / "import_faithfulness.py", SCRIPT_DIR / "faithfulness_unsupported_digest.py"
    return "faithfulness_import", (
        f"审核结果已在{result_dir}（结果以50指定的结果目录为准，不在批次账本里），本篇尚未导入，由知识库立即导入，不要等待或停下："
        f'①预检 python -X utf8 "{importer}" --task-dir "{task}" --check-only；'
        "②无unsupported时去掉--check-only重跑；"
        f'③有unsupported时运行 python -X utf8 "{digest}" --result-dir "{result_dir}" --output "{result_dir / "unsupported-digest.json"}"，'
        "按references/faithfulness-import-card.md第2–3节把每条主张归组写处置JSON（需要时先登记缺口、CUS或ANM），"
        f'再运行 python -X utf8 "{importer}" --task-dir "{task}" --disposition <处置JSON>；'
        "只有某条主张需要客户回答或业务决定且不能写成CUS待问时，才暂停本篇")


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
            if path.name.endswith((".workflow.json", ".continuation.json")):
                continue  # Derived checkpoints cannot become alternate ledgers.
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

    state = str(receipt.get("workflow_state") or "handoff_waiting_knowledge_fix")
    # needs_human is a contract pause event; every other state is a reason to
    # keep working and can never end the chain.
    decision = decide(event=state) if state == "needs_human" else decide(reason=state)
    receipt["terminal"] = decision.terminal
    if not decision.terminal:
        from workflow_progress import EXECUTOR_RULE, RESUME_RULE, WRITER_LOCK
        receipt.setdefault("next_owner", "writer" if state == "writing_ready_issued" else "manage-article-knowledge")
        receipt["executor_rule"] = EXECUTOR_RULE
        receipt["resume_rule"] = RESUME_RULE
        receipt["writer_lock"] = WRITER_LOCK
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
    # Retrying unchanged validation data cannot repair it. Only transient IO
    # failures are retried; semantic blockers produce one actionable receipt.
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
            break
        except OSError as exc:
            last_error = str(exc)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            break
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
        "ok": not errors and not last_error,
        "attempts": attempts,
        "error": last_error,
        "errors": errors,
        "payload": payload,
        "output": output,
    }


def sync_current_website_captures(project: Path, ledger: Path, batch_id: str) -> dict[str, Any]:
    """Route current task capture manifests before validating the ledger.

    Website capture is an input step, not a human handoff.  The synchronizer
    is deliberately conservative: it promotes only an exact source plus
    continuous excerpt match to an existing Claim and leaves ambiguous facts
    in ``capture_inbox`` for normal Claim resolution.
    """
    import sync_website_evidence

    try:
        return sync_website_evidence.sync(project, batch_id, ledger)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "batch_id": batch_id,
            "discovered": 0,
            "promoted": 0,
            "pending": 0,
            "unchanged": 0,
            "unresolved_count": 0,
            "unresolved": [],
            "errors": [f"官网凭证同步失败：{exc}"],
            "ledger": str(ledger),
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


def revoke_stale_permit(task: Path, errors: list[str]) -> None:
    """Withdraw an earlier writing permit once its task fails the gate again.

    A writer only reads writing_ready.json; leaving it in place while the batch
    receipt says the article is blocked lets writing start on a stale package.
    """
    if not (task / "writing_ready.json").is_file():
        return
    from issue_writing_ready import blocked
    capture_stdout(blocked, task, list(errors))


def gate_outcome(task: Path) -> tuple[bool, list[str], str]:
    """Read the writing gate result file written by issue_writing_ready."""
    result = parse_json(task / "writing_gate_result.json") or {}
    ready = result.get("writing_gate_status") == "ready" and (task / "writing_ready.json").is_file()
    reasons = [str(item) for item in result.get("blocked_reasons", []) if str(item).strip()]
    return ready, reasons, str(result.get("human_message", ""))


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
    # A PR-2 task without a 20 gets the mechanical skeleton first, so the agent fills judgments
    # instead of typing six sections, headers, outline rows and category names by hand.
    from scaffold_preparation_record import (_ledger_rows, append_new_candidates, normalize_table_pipes, scaffold,
                                             strip_template_notes)
    from task_records import PROTOCOL, REQUEST, _field, _read
    preparing = task.parent.name == "10_进行中" and _field(_read(task / REQUEST), "知识准备记录协议") == PROTOCOL
    # A 20 written before the evidence is in only gets rewritten: wait for this article's facts.
    scaffolded = preparing and bool(_ledger_rows(task, _read(task / REQUEST))) and scaffold(task)[1]
    if preparing and not scaffolded:
        # Facts added after the 20 was written are listed for a decision, never mapped by a script.
        append_new_candidates(task)
        normalize_table_pipes(task)
        strip_template_notes(task)
    package = recover_and_gate(project, task, retry_limit)
    errors = list(package["after"])
    if not errors:
        # The package gate alone is not the delivery gate: MAT choices, the 20
        # conclusion and open problem sheets are checked by the same shared
        # readiness gate that advance and issue_writing_ready use.  Reporting
        # them here keeps a blocked article from looking "ready".
        from article_state import delivery_readiness_errors
        errors = delivery_readiness_errors(task)
    if errors and task.parent.name == "20_等待终稿":
        revoke_stale_permit(task, errors)
    from article_state import human_wait_reason
    human = human_wait_reason(task) if errors else ""
    if human:
        return {
            "article_id": article_id,
            "task": str(task),
            "task_state": task.parent.name,
            "state": "needs_human",
            "terminal": False,
            "errors": errors,
            "human_message": human,
            "recovery": package["recovery"],
            "next_action": (
                "暂停本篇，用中文把以下问题告诉操作者并用workflow_progress.py pause记录；同批其他文章继续。"
                "处理单更新为“已处理，待自动复核”或“已关闭”后重跑本入口：" + human
            ),
        }
    # A deterministic package repairer cannot decide outline coverage or
    # perform the CUS/ANM review.  When 30/35 are absent or the package gate
    # reports incomplete 15/20 semantics, direct the agent to the specific
    # article records and reuse the already validated batch evidence.  Do not
    # send the agent back through all six source layers by default.
    needs_materialization = any(
        name in error
        for error in errors
        for name in ("15_检索与知识准备记录.md", "20_文章前知识审核.md",
                     "30_本篇知识库资料.md", "35_写作素材来源索引.md")
    )
    if errors and needs_materialization:
        record_errors = [
            error for error in errors
            if "15_检索与知识准备记录.md" in error or "20_文章前知识审核.md" in error
        ]
        derived_errors = [
            error for error in errors
            if "30_本篇知识库资料.md" in error or "35_写作素材来源索引.md" in error
        ]
        if record_errors:
            record_action = (
                "仅修复回执列出的文章记录（PR-2任务只改合并后的20，来源写EV-/SRC@/10#指针，不抄URL、原文和指纹；旧任务改15/20）："
                "以10中已确认大纲逐项写覆盖结论及CF→Claim引用，"
                "并完成20要求的覆盖复核和CUS/ANM判断。先复用当前批次账本、source_reads和已核验Claim；"
                "只有某个大纲问题确实没有答案、来源不完整或发生冲突时，才补查该问题所需来源。"
            )
        else:
            record_action = "15/20已通过语义检查，不要重做检索或审核；"
        derived_action = (
            "记录修复后运行本入口，让恢复器从现有有效记录生成并校验30/35，再签发writing_ready。"
            if derived_errors else "完成记录修复后重跑本入口复核。"
        )
        next_action = (
            ("已按当前10和批次账本写好20骨架（章节、表头、大纲行、有信号的检测类别都已就位）："
             "只填其中“待填写”的单元格，不增删章节和表格、不改大纲章节与检测类别名。" if scaffolded else "")
            + "不要空跑本入口。" + record_action + derived_action
            + "不得让恢复器猜测语义结论，也不要把已闭环来源重新检索一遍。"
            "当前门禁缺项：" + "；".join(errors)
        )
        state = "article_records_required"
    else:
        next_action = (
            "运行advance_ready_tasks.py并逐篇核对issue_writing_ready.py回执"
            if not errors and task.parent.name == "10_进行中"
            else "只修复本篇以下缺项后重跑本入口；保留当前身份、已核验来源和无关文件：" + "；".join(errors)
            if errors else "核对当前文章写作许可并交给写作方继续"
        )
        state = "ready_candidate" if not errors else "knowledge_repair_required"
    snapshot = {
        "article_id": article_id,
        "task": str(task),
        "task_state": task.parent.name,
        "state": state,
        "terminal": False,
        "errors": errors,
        "recovery": package["recovery"],
        "next_action": next_action,
    }
    if errors:
        # Name each 待填写 cell (line, table, row, column) so the agent edits those cells
        # instead of rereading 10 and 20 to find them.
        from scaffold_preparation_record import fill_todo
        todo = fill_todo(task)
        if todo:
            snapshot["fill_todo"] = todo
    return snapshot


def advance_and_issue_ready(project: Path, articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Move validated tasks and issue the per-article writing gate in one pass."""
    from advance_ready_tasks import advance_project_detailed
    from handoff_contract import current_version
    from issue_writing_ready import issue

    issued: list[dict[str, Any]] = []
    failures: list[str] = []
    per_article: dict[str, dict[str, Any]] = {}
    article_ids = {
        str(item.get("article_id", "")).strip()
        for item in articles
        if isinstance(item, dict) and item.get("article_id")
    }
    outcome = advance_project_detailed(project, article_ids=article_ids)
    for task, errors in outcome.get("blocked", []):
        article_id = article_id_from_request(Path(task) / "10_文章知识需求.md") or Path(task).name
        per_article[article_id] = {"errors": list(errors), "human_message": ""}
    # A previous call may have moved a task before issuing its permit. Resume
    # both newly moved and already waiting tasks; moved_count=0 is not a gate.
    tasks = [find_task(project, article_id) for article_id in sorted(article_ids)]
    for task in tasks:
        if task is None or task.parent.name != "20_等待终稿":
            continue
        request = task / "10_文章知识需求.md"
        article_id = article_id_from_request(request)
        if article_ids and article_id not in article_ids:
            continue
        try:
            code, output = capture_stdout(
                issue,
                argparse.Namespace(
                    handoff_contract_version=current_version(),
                    project=project,
                    article_id=article_id,
                    external_task_key=None,
                ),
            )
        except (SystemExit, OSError, ValueError) as exc:
            failures.append(f"{article_id or task}: {exc}")
            per_article[article_id] = {"errors": [str(exc)], "human_message": ""}
            continue
        # issue() reports a block by return code and gate file, not by raising.
        ready, reasons, human = gate_outcome(task)
        if code == 0 and ready:
            issued.append({"article_id": article_id, "task": str(task), "output": output})
        else:
            per_article[article_id] = {
                "errors": reasons or [f"写作许可未签发（issue_writing_ready返回{code}）"],
                "human_message": human,
            }
    return {
        "moved": [str(path) for path in outcome.get("moved", [])],
        "blocked": [
            {"article_id": article_id, "errors": item["errors"], "human_message": item["human_message"]}
            for article_id, item in sorted(per_article.items())
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

    from batch_knowledge_run import current_binding_errors
    binding_errors = current_binding_errors(ledger, payload)
    if binding_errors:
        receipt.update({"workflow_state": "identity_error", "errors": binding_errors,
                        "next_action": "重放当前已提交的writing_request以完成批次登记及旧运行隔离；不得清空证据或手改运行ID"})
        persist_receipt(state_path, receipt)
        return receipt

    capture_sync = sync_current_website_captures(project, ledger, batch_id)
    receipt["capture_sync"] = capture_sync
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
    unresolved_captures = capture_sync.get("unresolved", [])
    if capture_sync.get("errors"):
        receipt.update({
            "workflow_state": "source_collection",
            "errors": list(dict.fromkeys(list(capture_sync["errors"]) + list(validation.get("errors", [])))),
            "next_action": "修复当前批次官网凭证同步问题后重新运行本入口；不要把抓取成功当作证据已核验",
        })
    elif unresolved_captures:
        receipt.update({
            "workflow_state": "claim_resolution",
            "errors": [
                f"{row.get('article_id')} / {row.get('candidate_id')}：{row.get('reason', '候选事实尚未完成Claim闭环')}"
                for row in unresolved_captures
            ],
            "next_action": "继续处理capture_inbox中的候选事实；可唯一确定的文章继续生成本篇资料包（PR-2为20/30/35，已有15的旧任务为15/20/30/35），冲突或范围不明的事项保留文章级terminal=false",
        })
    elif not evidence:
        receipt.update({
            "workflow_state": "source_collection",
            "errors": ["批次账本尚未形成证据记录；不能生成30/35或进入写作"],
            "next_action": "知识准备进行中，继续做：能用已有Formal Claim回答的问题先用record_claim_reuse.py登记，其余读取来源、沉淀Formal Claim并写入证据账本；完成后重新运行本入口",
        })
    elif validation.get("errors"):
        receipt.update({
            "workflow_state": "claim_resolution",
            "errors": list(validation["errors"]),
            "next_action": "按每条来源/Claim错误修复来源闭环，再重新运行本入口；不得把批次错误当作终点",
        })
    # Always evaluate independent articles. Global evidence_incomplete describes
    # the batch; it is not a reason to withhold a ready article's permission.
    if evidence:
        from batch_knowledge_run import ledger_errors
        from sync_website_evidence import BEYOND_KNOWLEDGE_STATES, current_tasks
        all_tasks = current_tasks(project, include_completed=True)
        articles = validation.get("payload", payload).get("articles", [])
        snapshots: list[dict[str, Any]] = []
        for item in articles if isinstance(articles, list) else []:
            if not isinstance(item, dict):
                continue
            article_id = str(item.get("article_id", ""))
            staged = all_tasks.get(article_id)
            if staged is not None and staged.parent.name in BEYOND_KNOWLEDGE_STATES:
                # Knowledge preparation for this version already passed the
                # writing gate; it is neither missing nor blocked.
                stage, action = post_writing_action(staged, article_id)
                snapshots.append({
                    "article_id": article_id, "task": str(staged), "task_state": staged.parent.name,
                    "state": "beyond_knowledge_stage", "stage": stage, "terminal": False, "errors": [],
                    "next_action": action,
                })
                continue
            source_errors = ledger_errors(ledger, batch_id, article_id=article_id)
            if source_errors:
                snapshots.append({"article_id": article_id, "state": "claim_resolution", "terminal": False,
                                  "errors": source_errors, "next_action": "只处理本篇未闭环候选或来源；已读取的当前来源不重复抓取"})
            else:
                snapshots.append(article_snapshot(project, item, retry_limit))
        for item in snapshots:
            if item.get("state") in RERUN_STATES:
                text = str(item.get("next_action", "")).rstrip("；。")
                item["next_action"] = f"{text}。修复后运行：{rerun_command(project, batch_id)}"
        receipt["articles"] = snapshots
        ready = [item for item in snapshots if item.get("state") == "ready_candidate"]
        handoff = {"moved": [], "blocked": [], "issued": [], "errors": []}
        if ready:
            try:
                handoff = advance_and_issue_ready(project, ready)
            except (OSError, ValueError, RuntimeError) as exc:
                handoff = {"moved": [], "blocked": [], "issued": [], "errors": [str(exc)]}
            receipt["handoff"] = handoff
            # Fold delivery/issue blocks back into each article's own receipt so
            # pending_steps always names the article and its real reasons.
            by_id = {item["article_id"]: item for item in snapshots}
            for blocked_item in handoff["blocked"]:
                snapshot = by_id.get(blocked_item["article_id"])
                if snapshot is None:
                    continue
                snapshot["errors"] = list(blocked_item["errors"])
                if blocked_item.get("human_message"):
                    snapshot.update(state="needs_human", human_message=blocked_item["human_message"],
                                    next_action="暂停本篇，用中文把以下问题告诉操作者并用workflow_progress.py pause记录；同批其他文章继续："
                                    + blocked_item["human_message"])
                else:
                    snapshot.update(state="knowledge_repair_required",
                                    next_action="只修复本篇以下缺项后重跑本入口；保留当前身份、已核验来源和无关文件："
                                    + "；".join(blocked_item["errors"]))
            issued_ids = {row["article_id"] for row in handoff["issued"]}
            for snapshot in snapshots:
                if snapshot["article_id"] in issued_ids:
                    snapshot.update(state="writing_ready_issued", errors=[],
                                    next_action="写作Skill读取并核对writing_ready.json后开始写作；终稿返回后回到知识库")
        blockers = [error for item in snapshots for error in item.get("errors", [])] + list(handoff["errors"])
        human = [item for item in snapshots if item.get("state") == "needs_human"]
        runnable = [item for item in snapshots if item.get("errors") and item.get("state") != "needs_human"]
        if human and not runnable and not handoff["errors"]:
            # Every remaining article waits on a person; repeating the knowledge
            # loop cannot change that. This is the contract's needs_human pause.
            receipt.update({
                "workflow_state": "needs_human",
                "errors": blockers,
                "human_message": "；".join(f"{item['article_id']}：{item['human_message']}" for item in human),
                "next_action": "暂停并用中文向操作者说明各篇待处理问题；已签发许可的文章继续写作。处理单更新后重跑本入口",
            })
        elif blockers:
            receipt.update({
                "workflow_state": "partial_writing_ready" if handoff["issued"] else "article_knowledge_preparation",
                "errors": blockers,
                "next_action": ("已签发许可的文章交给写作Skill；" if handoff["issued"] else "")
                + "其余逐篇按pending_steps中的本篇回执处理，不重建已通过文章；来源/Claim未变化时不要反复运行同一校验",
            })
        elif handoff["issued"] or handoff["moved"]:
            receipt.update({
                "workflow_state": "writing_ready_issued",
                "errors": [],
                "next_action": "写作Skill读取并核对每篇writing_ready.json后开始写作；终稿返回后回到知识库",
            })
        elif snapshots and all(item.get("state") == "beyond_knowledge_stage" for item in snapshots):
            receipt.update({
                "workflow_state": "writing_ready_issued",
                "errors": [],
                "next_action": "本批文章均已完成知识准备并交稿；"
                + ("；".join(f"{item['article_id']}：{item['next_action']}" for item in snapshots
                            if item.get("stage") == "faithfulness_import")
                   or "等待审核结果，结果写入后重跑本入口"),
            })
        else:
            receipt.update({
                "workflow_state": "writing_ready_pending",
                "errors": [],
                "next_action": "没有可迁移文章；读取当前文章级回执并继续知识准备，不得以moved_count=0结束",
            })
    imports = [item["article_id"] for item in receipt.get("articles", []) if item.get("stage") == "faithfulness_import"]
    if imports and "尚未导入" not in str(receipt.get("next_action", "")):
        receipt["next_action"] = (str(receipt.get("next_action", "")).rstrip("；。")
                                  + f"；{'、'.join(imports)}的审核结果已交付、尚未导入，按该篇next_action立即导入")
    receipt["pending_steps"] = [
        {key: item.get(key) for key in ("article_id", "state", "errors", "next_action", "human_message") if key != "human_message" or item.get(key)}
        for item in receipt["articles"] if item.get("errors") or item.get("stage") == "faithfulness_import"
    ]
    if not evidence:
        pending = []
        for item in payload.get("articles", []):
            if not isinstance(item, dict):
                continue
            article_id = item.get("article_id")
            captures = [row for row in unresolved_captures if row.get("article_id") == article_id]
            errors = [f"{row.get('candidate_id')}：{row.get('reason', '候选事实尚未完成Claim闭环')}" for row in captures]
            state = "claim_resolution" if captures else "source_collection"
            action = ("只处理下列已保存候选的Claim核验、沉淀或治理；复用当前来源凭证，不重新采集：" + "；".join(errors)
                      if captures else
                      "已有可用Formal Claim能回答的大纲问题，先用record_claim_reuse.py登记复用（不抓网页、不重读原件；"
                      "它会列出不满足当前要求的旧Claim：可由已存记录补齐的先补齐再登记，需回源的按正常检索核验后更新Claim）；"
                      "只有Claim覆盖不了、范围不足或触发复核的问题，才读取来源并保存凭证。完成后重跑本入口")
            if capture_sync.get("errors"):
                errors = list(capture_sync["errors"]) + errors
                action = "先修复下列凭证同步错误，保留已保存来源及候选，再重跑本入口：" + "；".join(errors)
            elif not unresolved_captures and receipt["workflow_state"] == "claim_resolution":
                state, errors, action = "claim_resolution", list(receipt["errors"]), receipt["next_action"]
            pending.append({"article_id": article_id, "state": state, "errors": errors, "next_action": action})
        receipt["pending_steps"] = pending
    identity_keys = ("article_id", "article_version", "title", "outline_id", "outline_version",
                     "research_run_id", "refresh_run_id", "revision_mode")
    receipt["article_identities"] = [
        {key: item.get(key, "") for key in identity_keys}
        for item in sorted(
            (row for row in validation.get("payload", payload).get("articles", []) if isinstance(row, dict)),
            key=lambda row: str(row.get("article_id", "")),
        )
    ]
    persist_receipt(state_path, receipt)
    return receipt


def compact_receipt(result: dict[str, Any]) -> dict[str, Any]:
    """Return the part of a receipt the agent acts on; the full one stays on disk.

    The persisted ``.workflow.json`` keeps every field.  Printing all of it on
    each run repeated the constant executor/resume/writer rules, captured
    ``issue_writing_ready`` output, recovery actions and every article error
    three times (receipt errors, article errors, pending_steps).
    """
    compact: dict[str, Any] = {
        key: result[key]
        for key in ("schema", "batch_id", "workflow_state", "terminal", "next_owner",
                    "next_action", "human_message", "retry_count")
        if key in result and result[key] not in (None, "")
    }
    # The long rule stays in the receipt file, but this line must print: P-005-ART-20261030-001's writing agent
    # saw next_owner=manage-article-knowledge with no rule beside it and stopped at source_collection.
    if not result.get("terminal") and result.get("next_owner") == "manage-article-knowledge":
        compact["executor"] = "没有另一个实际运行的执行方时，由当前Agent立即执行next_action；这不是阻塞，不要停下等待"
    compact["receipt_file"] = str(state_path_for(Path(str(result.get("ledger", "")))))
    batch = result.get("batch") or {}
    if batch:
        compact["batch"] = {"status": batch.get("status"), "evidence_count": batch.get("evidence_count")}
    sync = result.get("capture_sync") or {}
    if sync:
        compact["capture_sync"] = {
            key: sync.get(key) for key in ("discovered", "promoted", "pending", "unresolved_count")
            if key in sync
        }
        if sync.get("errors"):
            compact["capture_sync"]["errors"] = list(sync["errors"])
    articles = []
    for item in result.get("articles") or []:
        row = {key: item[key] for key in ("article_id", "task_state", "state", "stage", "next_action", "human_message",
                                          "fill_todo")
               if item.get(key)}
        errors = [str(error) for error in item.get("errors") or []]
        action = str(item.get("next_action", ""))
        # Most next_action texts already end with the joined errors.
        missing = [error for error in errors if error not in action]
        if missing:
            row["errors"] = missing
        unresolved = (item.get("recovery") or {}).get("unresolved") or []
        if unresolved:
            row["recovery_unresolved"] = list(unresolved)
        articles.append(row)
    if articles:
        compact["articles"] = articles
    elif result.get("pending_steps"):
        compact["pending_steps"] = result["pending_steps"]
    if not articles and result.get("errors"):
        compact["errors"] = list(result["errors"])
    handoff = result.get("handoff") or {}
    if handoff:
        compact["handoff"] = {
            "moved": len(handoff.get("moved") or []),
            "issued": [row.get("article_id") for row in handoff.get("issued") or []],
        }
        if handoff.get("errors"):
            compact["handoff"]["errors"] = list(handoff["errors"])
    for key in ("continuation", "guard"):
        value = result.get(key)
        if isinstance(value, dict):
            compact[key] = {
                name: value[name] for name in ("saved", "bound", "scope", "hook_required", "checkpoint", "human_message")
                if name in value
            }
    return compact


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
    parser.add_argument("--guard-scope", choices=("knowledge", "article"), default=None,
                        help="结束检查范围：仅知识准备或完整文章链路；省略时沿用本会话绑定")
    parser.add_argument("--full", action="store_true",
                        help="打印完整回执；默认只打印需执行的字段，完整回执始终保存在receipt_file")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project or not args.batch_id:
        parser.error("需要 --project 和 --batch-id；无需手工提供 --ledger")
    result = run_workflow(args.project, args.batch_id, retry_limit=max(0, args.retry_limit))
    from workflow_progress import bind as bind_progress
    try:
        checkpoint = bind_progress(args.project, args.batch_id, scope=args.guard_scope)
        result["continuation"] = {"saved": True, "checkpoint": str(checkpoint), "hook_required": False}
    except (OSError, ValueError) as exc:
        result["continuation"] = {"saved": False, "human_message": f"当前批次进度指针尚未保存：{exc}；保留原回执，先恢复本轮登记或读取。"}
    from workflow_guard import bind
    try:
        result["guard"] = bind(args.project, args.batch_id, scope=args.guard_scope)
    except (OSError, ValueError) as exc:
        result["guard"] = {"bound": False, "human_message": f"结束检查尚未绑定：{exc}；按当前回执继续恢复。"}
    # CLI output is a machine receipt.  ASCII escaping keeps it valid when a
    # Windows host starts Python with a legacy stdout code page; under UTF-8
    # stdout (python -X utf8) Chinese is printed directly instead of \uXXXX.
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    payload = result if args.full else compact_receipt(result)
    print(json.dumps(payload, ensure_ascii=not encoding.startswith("utf"),
                     indent=2 if args.full else None, separators=None if args.full else (",", ":")))
    # Intermediate and recoverable states intentionally return zero.  The
    # structured terminal=false receipt is the workflow protocol.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
