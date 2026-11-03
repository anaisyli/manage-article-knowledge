#!/usr/bin/env python3
"""Durable batch continuation without a client hook or a session environment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

# Share the existing file/identity/completion checks; importing this module
# neither installs a hook nor requires CODEX_THREAD_ID.
from workflow_guard import identities, inspect, pause_message, read, write, SCOPES

SCHEMA = "MAK-CONTINUATION-1"

# Shown wherever an agent decides what to do next (prepare output, batch
# receipt, status).  They hold for any writing Skill, whatever its own steps.
WRITER_LOCK = (
    "已提交writing_request的文章：选题、标题、关键词、读者与角度、大纲、已做的调研结论和候选配图以外部写作任务记录和10为准，"
    "视为已完成并锁定；续跑、上下文压缩、换会话或等待许可期间都不得重新选题、重做调研、改大纲或重挑配图，"
    "要改只能走重写/版本流程。取得该篇writing_ready之前，写作方的正文、DOCX和配图不开始；"
    "这不是停下：没有另一个执行方在运行时，由当前Agent接着按知识库Skill完成知识准备，拿到writing_ready后继续写作。"
)
EXECUTOR_RULE = (
    "next_owner只表示这一步属于哪个Skill的职责，不表示已有另一个Agent在做。除非平台确实另起了执行方且能确认它正在运行，"
    "否则由当前Agent立即执行next_action；阶段名、账本、Worker或角色标签都不是执行方，"
    "不能以“已交给某方”为由等待，也不能转去做其他阶段的工作。"
)
RESUME_RULE = (
    "中断、换会话或上下文压缩后：先运行workflow_progress.py status读取当前进度，按其中next_action继续，"
    "只读取这一步需要的文件；不要从写作Skill第一步重走，也不要整份重读各Skill说明来判断进度。"
)
PAUSE_KINDS = ("decision", "missing_material", "access", "recovery_exhausted",
               "platform_capability", "user_requested", "interruption_unknown")


def within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def paths(project: Path, batch_id: str) -> tuple[Path, Path, Path]:
    from run_knowledge_workflow import resolve_ledger, state_path_for
    project = project.resolve()
    ledger = within(resolve_ledger(project, batch_id), project)
    checkpoint = within(ledger.with_name(ledger.stem + ".continuation.json"), project)
    return ledger, within(state_path_for(ledger), project), checkpoint


def bind(project: Path, batch_id: str, *, scope: str | None = None) -> Path:
    project = project.resolve()
    ledger_path, receipt, checkpoint = paths(project, batch_id)
    ledger = read(ledger_path)
    if ledger.get("batch_id") != batch_id:
        raise ValueError("批次身份不匹配；请使用当前项目已登记的写作需求")
    members = identities(ledger)
    prior = read(checkpoint) if checkpoint.exists() else {}
    same = (prior.get("project") == str(project) and prior.get("batch_id") == batch_id
            and prior.get("articles") == members)
    data = prior if same else {"pauses": {}, "completions": {}, "active": True}
    selected = scope or data.get("scope", "knowledge")
    if selected not in SCOPES:
        raise ValueError("未知工作范围")
    data.update(schema=SCHEMA, project=str(project), batch_id=batch_id, articles=members,
                ledger=str(ledger_path), receipt=str(receipt), scope=selected)
    write(checkpoint, data)
    return checkpoint


def load(project: Path, batch_id: str) -> tuple[Path, dict]:
    ledger, receipt, checkpoint = paths(project, batch_id)
    data = read(checkpoint)
    if (data.get("schema") != SCHEMA or data.get("project") != str(project.resolve())
            or data.get("batch_id") != batch_id or data.get("ledger") != str(ledger)
            or data.get("receipt") != str(receipt) or data.get("scope") not in SCOPES):
        raise ValueError("保存的进度与当前项目、批次或路径不一致；不能自动选择其他项目")
    # inspect rechecks current article versions/run identities, not timestamps.
    return checkpoint, data


def status(project: Path, batch_id: str) -> dict:
    _, data = load(project, batch_id)
    done, pending, _ = inspect(data)
    runnable = [item for item in pending if item not in data.get("pauses", {})]
    receipt_path = Path(data["receipt"])
    receipt = read(receipt_path) if receipt_path.exists() else {}
    receipt_current = (
        receipt.get("batch_id") == batch_id
        and Path(str(receipt.get("project", ""))).resolve() == Path(data["project"]).resolve()
        and receipt.get("article_identities") == data["articles"]
    )
    complete = not pending
    paused = bool(pending) and (not runnable or not data.get("active", True))
    action = (str(receipt.get("next_action") or "读取当前需求，实际补齐未完成的知识准备，再运行批次入口")
              if receipt_current else "读取当前需求及最近一次有效回执，按未完成步骤继续知识准备")
    owner = str(receipt.get("next_owner") or "knowledge") if receipt_current else "knowledge"
    if data["scope"] == "article" and not complete:
        action += "；已取得当前有效写作许可的文章交写作方，终稿返回后继续审核和导入"
    result = {
        "schema": SCHEMA, "project": data["project"], "batch_id": batch_id,
        "scope": data["scope"], "status": "complete" if complete else "paused" if paused else "continue",
        "terminal": complete, "goal_verified": complete,
        "completed": done, "pending": pending, "runnable": [] if paused else runnable,
        "next_owner": "" if complete or paused else owner,
        "next_action": "本次目标已通过当前文件核验" if complete else action,
        "pauses": data.get("pauses", {}),
        "executor_rule": EXECUTOR_RULE,
        "resume_rule": RESUME_RULE,
        "human_message": (f"本批{len(data['articles'])}篇，已核验达到本次目标{len(done)}篇，"
                          f"尚有{len(pending)}篇未完成。"),
    }
    if data["scope"] == "article" and not complete:
        result["writer_lock"] = WRITER_LOCK
    if paused:
        result["next_action"] = "按暂停说明解决具体问题，收到继续要求后复核当前文件再接着处理"
        problem = ""
        if not data.get("active", True):
            interruption = data.get("interruption", {})
            if interruption.get("kind") == "platform_interrupt" and interruption.get("evidence"):
                problem = "收到平台中断记录，已保留进度，等待新的继续要求。"
            elif interruption.get("kind") == "executor_release" and interruption.get("evidence"):
                problem = "当前执行方已明确解除本轮续接，进度已保留；文章仍未完成。"
            else:
                problem = "中断原因未确认，已保留当前进度，不能推断为用户取消或工具故障。"
        result["human_message"] = pause_message(data, done, pending, problem)
    return result


def pause(project: Path, batch_id: str, article_id: str, *, kind: str, problem: str,
          attempted: str, operator_action: str, resume_condition: str, evidence: str = "") -> None:
    path, data = load(project, batch_id)
    inspect(data)  # Reject changed identities before updating a checkpoint.
    if article_id not in {row["article_id"] for row in data["articles"]} or kind not in PAUSE_KINDS:
        raise ValueError("文章不属于当前批次或暂停类型不适用")
    fields = dict(problem=problem, attempted=attempted, operator_action=operator_action,
                  resume_condition=resume_condition)
    if any(not re.search(r"[\u4e00-\u9fff]", value) for value in fields.values()):
        raise ValueError("暂停原因、尝试结果、操作者动作及恢复条件必须用中文说明")
    if kind == "user_requested" and not evidence.strip():
        raise ValueError("没有实际取消、停止指令或平台记录，不能标记为用户中断；原因不明使用interruption_unknown")
    data.setdefault("pauses", {})[article_id] = dict(kind=kind, evidence=evidence, **fields)
    write(path, data)


def resume(project: Path, batch_id: str, article_id: str | None = None) -> None:
    path, data = load(project, batch_id)
    inspect(data)
    if article_id and article_id not in {row["article_id"] for row in data["articles"]}:
        raise ValueError("文章不属于当前批次")
    # Resuming one affected article must not erase other genuine blockers.
    if article_id:
        data.setdefault("pauses", {}).pop(article_id, None)
    else:
        data["pauses"] = {}
    data["active"] = True
    data.pop("interruption", None)
    write(path, data)


def interrupt(project: Path, batch_id: str, *, evidence: str) -> None:
    if not evidence.strip():
        raise ValueError("缺少实际平台中断记录")
    path, data = load(project, batch_id)
    data.update(active=False, interruption={"kind": "platform_interrupt", "evidence": evidence})
    write(path, data)


def release(project: Path, batch_id: str, *, evidence: str) -> None:
    if not evidence.strip():
        raise ValueError("缺少执行方解除续接记录")
    path, data = load(project, batch_id)
    data.update(active=False, interruption={"kind": "executor_release", "evidence": evidence})
    write(path, data)


def record_completion(receipt: Path) -> None:
    """Called by the importer; derive only the exact task's registered batch."""
    from handoff_contract import validate_completion_receipt
    payload = read(receipt)
    task = validate_completion_receipt(payload)
    project = task.parents[2]
    request_path = within(task / "10_文章知识需求.md", project)
    if not request_path.is_file():
        return
    request = request_path.read_text(encoding="utf-8-sig")
    match = re.search(r"(?m)^\s*[-*]\s*批次ID[：:]\s*(\S+)", request)
    if not match or match.group(1) == "不适用":
        return
    batch_id = match.group(1)
    _, _, checkpoint = paths(project, batch_id)
    if not checkpoint.exists():
        return  # No scanning other batches or resurrecting old requests.
    path, data = load(project, batch_id)
    inspect(data)
    member = next((row for row in data["articles"] if row["article_id"] == payload["article_id"]), None)
    if not member or member["article_version"] != payload["article_version"]:
        raise ValueError("完成回执与本轮文章身份不一致")
    data.setdefault("completions", {})[payload["article_id"]] = str(receipt.resolve())
    write(path, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bind", "status", "pause", "resume"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--scope", choices=SCOPES)
    parser.add_argument("--article-id")
    parser.add_argument("--kind", choices=PAUSE_KINDS)
    for name in ("problem", "attempted", "operator-action", "resume-condition", "evidence"):
        parser.add_argument("--" + name, default="")
    args = parser.parse_args()
    try:
        if args.command == "bind":
            path = bind(args.project, args.batch_id, scope=args.scope)
            result = {"saved": True, "checkpoint": str(path), "hook_required": False}
        else:
            if args.command == "pause":
                if not args.article_id or not args.kind:
                    parser.error("暂停需要指定当前文章和具体问题类型")
                pause(args.project, args.batch_id, args.article_id, kind=args.kind,
                      problem=args.problem, attempted=args.attempted, operator_action=args.operator_action,
                      resume_condition=args.resume_condition, evidence=args.evidence)
            elif args.command == "resume":
                resume(args.project, args.batch_id, args.article_id)
            result = status(args.project, args.batch_id)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"terminal": False, "status": "inspection_error", "error": str(exc),
                          "human_message": "当前进度尚未核对成功，不能报告完成。请检查本次项目身份及文件读取情况；保留已有工作，不重复提交已成功的步骤。"}, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
