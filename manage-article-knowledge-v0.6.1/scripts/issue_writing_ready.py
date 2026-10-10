#!/usr/bin/env python3
"""Issue the single machine-checked writing_ready handoff for one article.

This is the only entry point that may authorize the external writing Skill to
start.  Batch evidence_ready and a successful writing_request are deliberately
not treated as article-level readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from article_state import article_package_errors, article_package_ready, parse_field, task_ready_for_delivery, transition_task
from check_integration import project_id_for_root
from check_skill_update import check_project as check_skill_version
from handoff_contract import HandoffContractError, current_version, validate_event, validate_version
from recover_article_package import RecoveryResult, recover_task
from template_contract import validate_task_templates
from update_integration_status import update as update_integration_status
from writing_bridge import locate_task, read_text


RECEIPT_NAME = "writing_ready.json"
GATE_RESULT_NAME = "writing_gate_result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blocked_payload(task: Path, reasons: list[str]) -> dict[str, object]:
    request = task / "10_文章知识需求.md"
    request_text = read_text(request) if request.is_file() else ""
    article_id = parse_field(request_text, "文章ID")
    version = parse_field(request_text, "当前版本") or parse_field(request_text, "文章版本") or "v1"
    if version and not version.lower().startswith("v"):
        version = "v" + version
    return {
        "schema": "MAK-WRITING-GATE-1",
        "writing_gate_status": "blocked",
        "terminal": False,
        "workflow_state": "writing_ready_pending",
        "blocked_step": "writing_ready_gate",
        "next_owner": "manage-article-knowledge",
        "resume_condition": "修复当前文章的知识准备或交付门禁后，使用同一文章ID重新运行本脚本",
        "next_action": "继续知识库内部修复并重新运行 issue_writing_ready.py；不得开始写作",
        "article_task": str(task),
        "article_id": article_id,
        "article_version": version,
        "blocked_reasons": reasons,
        "issued_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "issuer": "issue_writing_ready.py",
    }


def blocked(task: Path, reasons: list[str]) -> int:
    payload = _blocked_payload(task, reasons)
    result_path = task / GATE_RESULT_NAME
    task.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(result_path)
    print("writing_gate_status=blocked")
    print("terminal=false")
    print("workflow_state=writing_ready_pending")
    print("blocked_step=writing_ready_gate")
    print("next_owner=manage-article-knowledge")
    print("resume_condition=修复当前文章的知识准备或交付门禁后，使用同一文章ID重新运行本脚本")
    print(f"article_task={task}")
    print("next_action=继续知识库内部修复并重新运行 issue_writing_ready.py；不得开始写作")
    print(f"writing_gate_result={result_path}")
    print("terminal_source=writing_gate_result.json（不要只根据进程退出码判断是否终止）")
    for reason in reasons:
        print(f"blocked_reason={reason}")
    return 2


def _package_gate_errors(task: Path) -> list[str]:
    """Collect the task-local gate errors after any recovery pass."""
    errors = list(validate_task_templates(task))
    required = (
        "10_文章知识需求.md", "15_检索与知识准备记录.md",
        "20_文章前知识审核.md", "30_本篇知识库资料.md",
        "35_写作素材来源索引.md",
    )
    missing = [name for name in required if not (task / name).is_file()]
    errors.extend(f"缺少文件：{name}" for name in missing)
    if not missing:
        package_errors = article_package_errors(task)
        if package_errors:
            errors.extend(package_errors)
        elif not task_ready_for_delivery(task):
            errors.append("文章级交付门禁未通过（模板、Claim、证据正文、映射、批次或覆盖视图仍有问题）")
    return list(dict.fromkeys(errors))


def _recover_and_recheck(task: Path, errors: list[str]) -> tuple[list[str], RecoveryResult | None]:
    """Run the bounded in-Skill recovery loop before exposing a block."""
    if not errors:
        return [], None
    recovery = recover_task(task, max_passes=2)
    return _package_gate_errors(task), recovery


def _ready_payload(
    project: Path,
    task: Path,
    contract_version: str,
    article_id: str,
    version: str,
) -> dict[str, object]:
    material = task / "30_本篇知识库资料.md"
    return {
        "schema": "MAK-WRITING-READY-1",
        "handoff_contract_version": contract_version,
        "handoff_event": "writing_ready",
        "project_id": project_id_for_root(project),
        "article_id": article_id,
        "article_version": version,
        "knowledge_file": str(material),
        "knowledge_sha256": sha256(material),
        "issued_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "issuer": "issue_writing_ready.py",
    }


def _write_ready_receipt(project: Path, task: Path, payload: dict[str, object]) -> None:
    temporary = task / f".{RECEIPT_NAME}.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(task / RECEIPT_NAME)
    update_integration_status(
        project, "writing_ready", article_id=str(payload["article_id"]),
        article_version=str(payload["article_version"]),
        detail=f"机器回执：{task / RECEIPT_NAME}",
    )


def issue(args: argparse.Namespace) -> int:
    try:
        contract_version = validate_version(args.handoff_contract_version)
    except HandoffContractError as exc:
        raise SystemExit(str(exc)) from exc
    project = args.project.resolve()
    check_skill_version(project)
    task = locate_task(project, args.article_id or "", args.external_task_key or "")
    request_path = task / "10_文章知识需求.md"
    if not request_path.is_file():
        return blocked(task, [f"缺少知识需求文件：{request_path}"])
    request = read_text(request_path)
    article_id = parse_field(request, "文章ID")
    version = parse_field(request, "当前版本") or parse_field(request, "文章版本") or "v1"
    if not version.lower().startswith("v"):
        version = "v" + version
    if args.article_id and article_id != args.article_id:
        return blocked(task, [f"文章ID不匹配：请求={args.article_id}，文件={article_id}"])
    if task.parent.name not in {"10_进行中", "20_等待终稿"}:
        return blocked(task, [f"任务不在知识准备或等待终稿状态：{task.parent.name}"])

    receipt = task / RECEIPT_NAME
    if task.parent.name == "20_等待终稿":
        payload: dict[str, object] = {}
        receipt_error = ""
        if receipt.is_file():
            try:
                loaded = json.loads(receipt.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
                else:
                    receipt_error = "已有写作就绪回执不是JSON对象"
            except (OSError, json.JSONDecodeError) as exc:
                receipt_error = f"已有写作就绪回执无法读取：{exc}"
        else:
            receipt_error = f"等待终稿任务缺少机器写作就绪回执：{receipt}"
        errors = _package_gate_errors(task)
        if receipt_error:
            errors.append(receipt_error)
        elif payload.get("article_id") != article_id or payload.get("article_version") != version:
            errors.append("已有写作就绪回执与当前文章身份或版本不一致")
        elif not (task / "30_本篇知识库资料.md").is_file():
            errors.append("当前任务缺少30，无法核对写作就绪回执")
        elif payload.get("knowledge_sha256") != sha256(task / "30_本篇知识库资料.md"):
            errors.append("已有写作就绪回执与当前30哈希不一致")
        if errors:
            errors, recovery = _recover_and_recheck(task, errors)
            if not errors:
                payload = _ready_payload(project, task, contract_version, article_id, version)
                _write_ready_receipt(project, task, payload)
                print_ready(project, task, payload)
                return 0
            if recovery and recovery.changed_any:
                errors.insert(0, "知识库已自动恢复当前文章包，但仍有未解决门禁问题")
                errors.extend(f"自动恢复：{action}" for action in recovery.actions)
            return blocked(task, list(dict.fromkeys(errors)))
        print_ready(project, task, payload)
        return 0

    errors = _package_gate_errors(task)
    if errors:
        errors, recovery = _recover_and_recheck(task, errors)
    else:
        recovery = None
    if errors:
        update_integration_status(
            project, "writing_task_failure", article_id=article_id,
            article_version=version, external_task_key=args.external_task_key or "",
            error="writing_ready门禁阻塞：" + "；".join(errors[:8]),
        )
        if recovery and recovery.changed_any:
            errors.insert(0, "知识库已自动恢复当前文章包，但仍有未解决门禁问题")
            errors.extend(f"自动恢复：{action}" for action in recovery.actions)
        return blocked(task, errors)

    # transition_task updates the canonical todo entry and rolls back the
    # directory move if that update fails.
    destination = transition_task(
        task,
        "20_等待终稿",
        article_id=article_id,
        human_text=f"{parse_field(request, '标题') or article_id}知识库资料已就绪，等待终稿",
        blocked="否",
        owner="写作Skill收到writing_ready后写作；知识库接收终稿并导入Faithfulness",
        condition="文章要求、客户资料、30或35发生实质变化时归档并递增文章版本",
        updated=datetime.now().date().isoformat(),
        link_file="30_本篇知识库资料.md",
    )
    payload = _ready_payload(project, destination, contract_version, article_id, version)
    _write_ready_receipt(project, destination, payload)
    print_ready(project, destination, payload)
    return 0


def print_ready(project: Path, task: Path, payload: dict[str, object]) -> None:
    config = project / "01_工作台/40_写作与Faithfulness接入配置.md"
    final_target = "按项目接入配置中的终稿入口提交"
    if config.is_file():
        config_text = config.read_text(encoding="utf-8-sig")
        for label in ("终稿入口路径", "终稿路径"):
            match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", config_text, re.MULTILINE)
            if match and match.group(1).strip() not in {"", "待确认", "待扫描"}:
                final_target = match.group(1).strip()
                break
    event = {
        "handoff_event": "writing_ready",
        "handoff_contract_version": payload["handoff_contract_version"],
        "project_id": project_id_for_root(project),
        "article_id": payload["article_id"],
        "article_version": payload["article_version"],
        "knowledge_file": str(task / "30_本篇知识库资料.md"),
        "final_delivery_target": final_target,
        "writing_ready_receipt": str(task / RECEIPT_NAME),
    }
    validate_event("writing_ready", event)
    gate_result = {
        "schema": "MAK-WRITING-GATE-1",
        "writing_gate_status": "ready",
        "terminal": False,
        "workflow_state": "writing_ready_issued",
        "handoff_event": "writing_ready",
        "article_id": payload["article_id"],
        "article_version": payload["article_version"],
        "writing_ready_receipt": str(task / RECEIPT_NAME),
        "next_action": "写作Skill读取并核对writing_ready.json后才能开始写作",
        "issuer": "issue_writing_ready.py",
    }
    result_path = task / GATE_RESULT_NAME
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(gate_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(result_path)
    print("writing_gate_status=ready")
    for key, value in event.items():
        print(f"{key}={value}")
    print(f"writing_ready_receipt={task / RECEIPT_NAME}")
    print(f"writing_gate_result={result_path}")
    print("next=写作Skill现在才可读取当前30并开始原有写作流程")


def _emit_unbound_blocked(args: argparse.Namespace, message: str) -> None:
    """Keep unexpected gate failures recoverable even without a task path.

    A malformed project, stale identity, or filesystem failure can happen
    before the normal ``blocked()`` helper can resolve a task directory.  The
    caller still needs a machine-readable non-terminal result instead of a
    traceback that an outer runner might mistake for completion.
    """
    print("writing_gate_status=blocked")
    print("terminal=false")
    print("workflow_state=writing_ready_pending")
    print("blocked_step=writing_ready_gate")
    print("next_owner=manage-article-knowledge")
    print("resume_condition=修复门禁执行错误或任务身份后，使用同一文章ID重新运行本脚本")
    print("next_action=读取本回执并继续知识库修复；不得开始写作或终止整批")
    print(f"article_id={getattr(args, 'article_id', '') or ''}")
    print(f"blocked_reason=门禁脚本执行异常：{message}")
    print("terminal_source=标准输出回执（不要只根据进程退出码判断是否终止）")


def _recoverable_failure(args: argparse.Namespace, exc: BaseException) -> int:
    message = str(exc) or exc.__class__.__name__
    task: Path | None = None
    try:
        task = locate_task(
            args.project.resolve(),
            args.article_id or "",
            args.external_task_key or "",
        )
    except BaseException:
        task = None
    if task is not None:
        try:
            return blocked(task, [f"门禁脚本执行异常：{message}"])
        except Exception:
            pass
    _emit_unbound_blocked(args, message)
    return 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-contract-version", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--article-id")
    parser.add_argument("--external-task-key")
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        if exc.code in (None, 0):
            raise
        # Even malformed invocation is recoverable from the workflow's point
        # of view.  Emit the same machine-readable non-terminal signal as a
        # task-level gate failure so callers never infer completion from code 2.
        _emit_unbound_blocked(
            argparse.Namespace(article_id=None, external_task_key=None),
            "门禁命令参数不完整或无效",
        )
        raise SystemExit(2) from exc
    if not (args.article_id or args.external_task_key):
        # Keep validation failures on the same machine-readable recovery path
        # as every other gate failure.  Do not let argparse write only stderr
        # and leave an outer orchestrator guessing from exit code 2.
        _emit_unbound_blocked(args, "至少需要 --article-id 或 --external-task-key")
        raise SystemExit(2)
    try:
        raise SystemExit(issue(args))
    except SystemExit as exc:
        # A non-zero gate result is recoverable unless it explicitly came from
        # a successful process exit.  Normalize unexpected SystemExit paths so
        # the outer orchestrator always receives terminal=false evidence.
        # ``issue()`` deliberately returns 2 for a normal, already-recorded
        # gate block.  Do not pass that result through the exception fallback:
        # doing so would overwrite the detailed blocked reasons and recovery
        # actions with a generic "script exception: 2" message.
        if exc.code in (None, 0, 2):
            raise
        raise SystemExit(_recoverable_failure(args, exc)) from exc
    except Exception as exc:
        raise SystemExit(_recoverable_failure(args, exc)) from exc


if __name__ == "__main__":
    main()
