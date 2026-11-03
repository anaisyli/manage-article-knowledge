#!/usr/bin/env python3
"""Session-scoped Stop hook; stores pointers/checkpoints, never a second task queue."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

SCHEMA = "MAK-STOP-GUARD-1"
STATES = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成")
SCOPES = ("knowledge", "article")
PAUSE_KINDS = ("decision", "missing_material", "access", "recovery_exhausted", "user_requested")
VOLATILE = {"started_at", "ended_at", "updated_at", "retrieved_at", "issued_at", "checked_at",
            "timestamp", "retry_count", "retry_limit", "attempts", "guard"}


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("记录必须是JSON对象")
    return value


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temporary names avoid concurrent hook invocations sharing a .tmp.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.stem, suffix=".tmp", delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def registry_path(session_id: str, root: Path | None = None) -> Path:
    if not session_id:
        raise ValueError("缺少当前会话身份；不能绑定其他会话")
    key = hashlib.sha256(session_id.encode()).hexdigest()
    return (root or Path(tempfile.gettempdir()) / "mak-workflow-guard") / (key + ".json")


def identities(ledger: dict) -> list[dict]:
    keys = ("article_id", "article_version", "title", "outline_id", "outline_version",
            "research_run_id", "refresh_run_id", "revision_mode")
    rows = [{key: row.get(key, "") for key in keys}
            for row in ledger.get("articles", []) if isinstance(row, dict)]
    ids = [row["article_id"] for row in rows]
    if not ids or any(not value or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(value)) for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("批次文章身份缺失、重复或格式错误；请从已保存的写作需求恢复登记")
    return sorted(rows, key=lambda row: row["article_id"])


def bind(project: Path, batch_id: str, *, scope: str | None = None,
         session_id: str | None = None, root: Path | None = None) -> dict:
    from run_knowledge_workflow import resolve_ledger, state_path_for
    session_id = session_id or os.environ.get("CODEX_THREAD_ID", "")
    if not session_id:
        return {"bound": False, "human_message": "当前环境没有提供会话身份，结束拦截尚未绑定；仍须按回执连续推进。"}
    project = project.resolve()
    ledger_path = resolve_ledger(project, batch_id).resolve()
    ledger_path.relative_to(project)
    ledger = read(ledger_path)
    if ledger.get("batch_id") != batch_id:
        raise ValueError("批次身份不匹配；不能绑定结束检查")
    members = identities(ledger)
    path = registry_path(session_id, root)
    prior = read(path) if path.exists() else {}
    same = prior.get("project") == str(project) and prior.get("batch_id") == batch_id
    # One current request/project per session; never follow an old project's queue.
    data = prior if same else {}
    changed = data.get("articles") != members
    if changed:
        data.update(pauses={}, completions={}, checks=0, stagnant=0, fingerprint="")
    selected_scope = scope or data.get("scope", "knowledge")
    if selected_scope not in SCOPES:
        raise ValueError("未知工作范围")
    data.update(schema=SCHEMA, session_id=session_id, project=str(project), batch_id=batch_id,
                ledger=str(ledger_path), receipt=str(state_path_for(ledger_path)), articles=members,
                scope=selected_scope, active=True)
    write(path, data)
    return {"bound": True, "scope": selected_scope}


def record_completion(receipt: Path, *, session_id: str | None = None, root: Path | None = None) -> None:
    session_id = session_id or os.environ.get("CODEX_THREAD_ID", "")
    if not session_id:
        return
    path = registry_path(session_id, root)
    if not path.exists():
        return
    data, payload = read(path), read(receipt)
    if not data.get("active"):
        return
    task = Path(str(payload.get("task_dir", ""))).resolve()
    try:
        task.relative_to(Path(data["project"]) / "04_文章任务" / "40_已完成")
    except ValueError:
        return
    member = next((row for row in data["articles"] if row["article_id"] == payload.get("article_id")), None)
    if member and member.get("article_version") == payload.get("article_version"):
        data.setdefault("completions", {})[member["article_id"]] = str(receipt.resolve())
        write(path, data)


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key not in VOLATILE}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def task_for(project: Path, article_id: str) -> Path | None:
    from run_knowledge_workflow import article_id_from_request
    matches = []
    for state in STATES:
        parent = project / "04_文章任务" / state
        parent.resolve().relative_to(project.resolve())
        if parent.is_dir():
            for task in parent.iterdir():
                if task.is_dir() and (task.name == article_id or task.name.startswith(article_id + "_")):
                    task.resolve().relative_to(project.resolve())
                    (task / "10_文章知识需求.md").resolve().relative_to(project.resolve())
                    if article_id_from_request(task / "10_文章知识需求.md") == article_id:
                        matches.append(task)
    if len(matches) > 1:
        raise ValueError(f"文章 {article_id} 有多个当前目录，不能猜测采用哪一份")
    return matches[0] if matches else None


def inspect(data: dict) -> tuple[list[str], list[str], str]:
    """Read only the bound batch and current article files; never rerun a mutating gate."""
    from handoff_contract import current_version, validate_completion_receipt
    from issue_writing_ready import sha256
    from article_state import article_package_errors, line_ending_hashes
    project = Path(data["project"]).resolve()
    Path(data["ledger"]).resolve().relative_to(project)
    Path(data["receipt"]).resolve().relative_to(project)
    ledger = read(Path(data["ledger"]))
    if ledger.get("batch_id") != data["batch_id"] or identities(ledger) != data["articles"]:
        raise ValueError("本轮文章版本或批次身份已变化，请重新提交当前已保存的写作需求以绑定新身份")
    receipt_path = Path(data["receipt"])
    receipt = read(receipt_path) if receipt_path.exists() else {}
    if receipt and (receipt.get("batch_id") != data["batch_id"] or Path(str(receipt.get("project", ""))).resolve() != project):
        raise ValueError("进度回执与当前项目或批次不一致")
    done, pending, parts = [], [], [clean(ledger), clean(receipt)]
    for member in data["articles"]:
        article_id = member["article_id"]
        task = task_for(project, article_id)
        if task is None:
            pending.append(article_id)
            continue
        request = (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
        version_match = re.search(r"(?m)^\s*[-*]\s*当前版本[：:]\s*(\S+)", request)
        if not version_match or version_match.group(1) != member["article_version"]:
            raise ValueError(f"文章 {article_id} 的当前版本与本轮登记不一致")
        # These are current task checkpoints only, not unrelated customer files.
        for file in sorted(task.iterdir()):
            if file.is_file() and (file.suffix == ".json" or re.match(r"^(10|15|20|30|35|40|50)_", file.name)):
                file.resolve().relative_to(project)
                if file.suffix == ".json":
                    # Checkpoints may be arrays (e.g. 官网正文抓取凭证.json);
                    # only the fingerprint is needed here, not an object.
                    parts.append([article_id, file.name, clean(json.loads(file.read_text(encoding="utf-8-sig")))])
                else:
                    parts.append([article_id, file.name, hashlib.sha256(file.read_bytes()).hexdigest()])
        completed = False
        completion_path = data.get("completions", {}).get(article_id)
        if completion_path:
            payload = read(Path(completion_path))
            completed = (payload.get("article_id") == article_id and payload.get("article_version") == member["article_version"]
                         and validate_completion_receipt(payload) == task.resolve())
        if data["scope"] == "knowledge" and task.parent.name in ("30_等待Faithfulness", "40_已完成"):
            # The task only reaches these states after passing the writing gate,
            # so the knowledge-preparation goal for this version is met.
            completed = True
        elif data["scope"] == "knowledge" and task.parent.name == "20_等待终稿":
            permit = read(task / "writing_ready.json") if (task / "writing_ready.json").exists() else {}
            gate = read(task / "writing_gate_result.json") if (task / "writing_gate_result.json").exists() else {}
            completed = (permit.get("article_id") == article_id and permit.get("article_version") == member["article_version"]
                         and permit.get("handoff_contract_version") == current_version()
                         # A CRLF/LF rewrite by an editor is not a change to the permitted material.
                         and permit.get("knowledge_sha256") in line_ending_hashes((task / "30_本篇知识库资料.md").read_bytes())
                         and gate.get("article_id") == article_id and gate.get("article_version") == member["article_version"]
                         and gate.get("writing_gate_status") == "ready" and not article_package_errors(task))
        (done if completed else pending).append(article_id)
    fingerprint = hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return done, pending, fingerprint


def pause_message(data: dict, done: list[str], pending: list[str], problem: str = "") -> str:
    lines = [f"本批共 {len(data['articles'])} 篇，已核验达到本次目标 {len(done)} 篇，尚有 {len(pending)} 篇未完成。"]
    for article_id in pending:
        row = data.get("pauses", {}).get(article_id)
        if row:
            index, member = next((index, member) for index, member in enumerate(data["articles"], 1) if member["article_id"] == article_id)
            label = member.get("title") or f"本批第{index}篇文章"
            lines += [f"{label}：{row['problem']}", f"已经尝试：{row['attempted']}",
                      f"请操作者：{row['operator_action']}", f"恢复方式：{row['resume_condition']}"]
    if problem:
        lines += [problem, "已保留现有资料和进度；请回复“从保存的位置继续，先检查卡住的原因”。"]
    lines += ["这次是暂停，尚未完成的文章不能报告为完成。请直接用上述中文内容向操作者说明，不只展示编号、错误码或文件路径。"]
    return "\n".join(lines)


def check(event: dict, *, root: Path | None = None) -> dict:
    session_id = str(event.get("session_id", ""))
    if not session_id:
        return {}
    path = registry_path(session_id, root)
    if not path.exists():
        return {}
    data = read(path)
    if data.get("session_id") != session_id or not data.get("active"):
        return {}
    if event.get("hook_event_name") == "Interrupt":
        data["active"] = False
        data["interruption"] = {"kind": "platform_interrupt", "evidence": "收到当前会话的Interrupt事件"}
        write(path, data)
        try:
            from workflow_progress import interrupt
            interrupt(Path(data["project"]), data["batch_id"], evidence="收到当前会话的Interrupt事件")
        except (OSError, ValueError, KeyError):
            # The actual interruption still takes effect in this session.
            # Do not invent a missing durable record or restart the task.
            pass
        return {"systemMessage": "已停止自动续跑并保留进度；收到新的继续要求后再恢复。"}
    done, pending = [], [row["article_id"] for row in data["articles"]]
    # A generic (non-hook) pause must also be respected by the optional hook.
    try:
        from workflow_progress import paths, load
        _, _, checkpoint = paths(Path(data["project"]), data["batch_id"])
        if checkpoint.exists():
            _, progress = load(Path(data["project"]), data["batch_id"])
            if progress.get("articles") == data["articles"]:
                data["pauses"] = progress.get("pauses", {})
                data.setdefault("completions", {}).update(progress.get("completions", {}))
                if not progress.get("active", True):
                    data["active"] = False
                    write(path, data)
                    return {"systemMessage": "当前批次已保存中断进度，等待明确继续要求；不能报告完成。"}
        done, pending, fingerprint = inspect(data)
        data["inspection_failures"] = 0
        # An article the batch receipt marks needs_human is waiting on a person;
        # nudging the agent again only repeats an unchanged gate.  Surface the
        # receipt's own question instead of the generic "no progress" pause.
        receipt_path = Path(data["receipt"])
        latest = read(receipt_path) if receipt_path.exists() else {}
        pauses = data.setdefault("pauses", {})
        for step in latest.get("pending_steps", []) if isinstance(latest.get("pending_steps"), list) else []:
            article_id = str(step.get("article_id", ""))
            if step.get("state") == "needs_human" and article_id in pending and article_id not in pauses:
                pauses[article_id] = {
                    "kind": "decision",
                    "problem": str(step.get("human_message") or "；".join(step.get("errors") or [])),
                    "attempted": "知识库已完成可自动处理的步骤并重新运行门禁",
                    "operator_action": "按文章前问题与处理单提供决定或材料",
                    "resume_condition": "处理单更新为“已处理，待自动复核”或“已关闭”后，回复从保存的位置继续",
                }
        runnable = [item for item in pending if item not in pauses]
        data["checks"] = data.get("checks", 0) + 1
        data["stagnant"] = data.get("stagnant", 0) + 1 if data.get("fingerprint") == fingerprint else 0
        data["fingerprint"] = fingerprint
        limit = data["checks"] > 24 or data["stagnant"] >= 3
        if not pending:
            data["active"] = False
            write(path, data)
            return {}
        if runnable and not limit:
            write(path, data)
            receipt_path = Path(data["receipt"])
            receipt = read(receipt_path) if receipt_path.exists() else {}
            action = str(receipt.get("next_action") or "读取当前任务实际进度，完成缺少的知识准备步骤，再运行批次入口")
            if data["scope"] == "article":
                action += "；已取得当前写作许可的文章继续原写作流程，终稿交回知识库审核并导入结果"
            # stop_hook_active is informational, not a bypass: several successful
            # continuation rounds may be needed to finish a real article batch.
            return {"decision": "block", "reason": (
                f"本次文章任务还未完成：已达目标{len(done)}篇，仍可推进{len(runnable)}篇。"
                f"继续处理 {', '.join(runnable)}。下一步：{action}。"
                "先简短报告实际进度，然后执行；不要只反复运行未变化的校验器。"
                "遇到临时失败先合理恢复；需要人工时用workflow_guard.py pause记录具体问题、已尝试办法、操作者动作和恢复条件。"
            )}
        problem = "连续几次续跑没有产生实质进展，或已达到自动续跑次数上限，需要先检查卡点。" if limit and runnable else ""
    except (OSError, ValueError, KeyError) as exc:
        data["inspection_failures"] = data.get("inspection_failures", 0) + 1
        if data["inspection_failures"] <= 2:
            write(path, data)
            return {"decision": "block", "reason": (
                f"当前文章进度尚未核对成功：{exc}。先检查本轮绑定与文件读取，"
                "能根据当前已保存需求确定的问题自行恢复；不得猜项目或版本。"
                "恢复后继续原任务；只有确实需要人工决定或权限时才登记具体暂停说明。"
            )}
        problem = f"结束检查暂时无法可靠核对当前任务：{exc}"
    # A pause is not a successful business terminal event. One final explanatory
    # continuation ensures the operator receives human-readable recovery steps.
    data["active"] = False
    message = pause_message(data, done, pending, problem)
    data["pause_summary"] = message
    write(path, data)
    return {"decision": "block", "reason": message + "\n仅说明暂停与下一步，本次不再自动续跑。"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hook")
    start = sub.add_parser("bind")
    start.add_argument("--project", type=Path, required=True)
    start.add_argument("--batch-id", required=True)
    start.add_argument("--scope", choices=SCOPES, default="knowledge")
    pause = sub.add_parser("pause")
    pause.add_argument("--article-id", required=True)
    pause.add_argument("--kind", choices=PAUSE_KINDS, required=True)
    for field in ("problem", "attempted", "operator-action", "resume-condition"):
        pause.add_argument("--" + field, required=True)
    pause.add_argument("--evidence", default="")
    sub.add_parser("resume")
    sub.add_parser("release")
    args = parser.parse_args()
    if args.command == "hook":
        try:
            result = check(json.load(sys.stdin))
        except (OSError, ValueError, KeyError) as exc:
            result = {"systemMessage": f"文章结束检查运行失败，未核验完成；请检查钩子记录：{exc}"}
    elif args.command == "bind":
        result = bind(args.project, args.batch_id, scope=args.scope)
    else:
        path = registry_path(os.environ.get("CODEX_THREAD_ID", ""))
        data = read(path)
        if args.command == "pause":
            if args.article_id not in {row["article_id"] for row in data["articles"]}:
                parser.error("该文章不属于当前绑定批次")
            row = {field: getattr(args, field) for field in ("kind", "problem", "attempted", "operator_action", "resume_condition")}
            if any(not re.search(r"[\u4e00-\u9fff]", row[field]) for field in ("problem", "attempted", "operator_action", "resume_condition")):
                parser.error("问题、已尝试办法、操作者动作和恢复条件必须用中文说明")
            if args.kind == "user_requested" and not args.evidence.strip():
                parser.error("标记用户中断需要实际取消、停止要求或平台记录；没有记录不能推断")
            data.setdefault("pauses", {})[args.article_id] = row
        elif args.command == "resume":
            data.update(active=True, pauses={}, checks=0, stagnant=0, fingerprint="", inspection_failures=0)
        else:
            data["active"] = False
        write(path, data)
        # Keep the old session commands compatible with the durable base mode.
        from workflow_progress import paths, pause as pause_progress, resume as resume_progress, release as release_progress
        project, batch_id = Path(data["project"]), data["batch_id"]
        if paths(project, batch_id)[2].exists():
            if args.command == "pause":
                pause_progress(project, batch_id, args.article_id, evidence=args.evidence, **row)
            elif args.command == "resume":
                resume_progress(project, batch_id)
            else:
                release_progress(project, batch_id, evidence="当前执行方明确调用release解除本轮接续")
        result = {"saved": True, "active": data["active"]}
    # Hook transport must remain valid JSON even under a non-UTF8 Windows shell.
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
