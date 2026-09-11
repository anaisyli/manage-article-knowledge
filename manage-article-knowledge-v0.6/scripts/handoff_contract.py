#!/usr/bin/env python3
"""Load and validate the canonical three-Skill handoff contract."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping


CONTRACT_PATH = Path(__file__).resolve().parents[1] / "references" / "handoff-contract.json"


class HandoffContractError(ValueError):
    """A handoff payload does not satisfy the installed contract."""


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HandoffContractError(f"handoff contract not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HandoffContractError(f"handoff contract is not valid JSON: {path}") from exc
    required = {
        "contract_id", "handoff_contract_version", "compatible_versions",
        "faithfulness_executor", "event_lifecycle", "revision_modes", "events",
    }
    missing = sorted(required - set(value)) if isinstance(value, dict) else sorted(required)
    if missing:
        raise HandoffContractError(f"handoff contract missing fields: {', '.join(missing)}")
    if value["handoff_contract_version"] not in value["compatible_versions"]:
        raise HandoffContractError("current handoff contract version is absent from compatible_versions")
    executor = value.get("faithfulness_executor", {})
    if executor.get("skill_name") != "deepeval-article-audit":
        raise HandoffContractError("faithfulness executor must be deepeval-article-audit")
    lifecycle = value.get("event_lifecycle", {})
    if lifecycle.get("success_terminal_event") != "article_completed":
        raise HandoffContractError("success terminal event must be article_completed")
    non_terminal = set(lifecycle.get("non_terminal_events", []))
    required_non_terminal = {
        "writing_request", "writing_ready", "writing_completed",
        "faithfulness_request", "faithfulness_completed",
    }
    if not required_non_terminal.issubset(non_terminal):
        raise HandoffContractError("handoff lifecycle is missing required non-terminal events")
    revision_modes = value.get("revision_modes", {})
    required_modes = {
        "new_article", "knowledge_refresh_and_rewrite", "article_rewrite_only",
    }
    if not required_modes.issubset(revision_modes):
        raise HandoffContractError("handoff contract is missing required revision modes")
    for mode in required_modes:
        rule = revision_modes.get(mode, {})
        if not isinstance(rule.get("requires_base_article"), bool):
            raise HandoffContractError(f"revision mode {mode} must declare requires_base_article")
        pattern = str(rule.get("base_article_version_pattern") or "")
        if rule["requires_base_article"] and not pattern:
            raise HandoffContractError(
                f"revision mode {mode} must declare base_article_version_pattern"
            )
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise HandoffContractError(
                    f"revision mode {mode} has invalid base version pattern"
                ) from exc
    return value


def current_version(contract: Mapping[str, Any] | None = None) -> str:
    contract = contract or load_contract()
    return str(contract["handoff_contract_version"])


def validate_version(received: str, contract: Mapping[str, Any] | None = None) -> str:
    contract = contract or load_contract()
    received = str(received or "").strip()
    if not received:
        raise HandoffContractError(
            f"missing handoff_contract_version; expected {current_version(contract)}"
        )
    compatible = {str(item) for item in contract.get("compatible_versions", [])}
    if received not in compatible:
        raise HandoffContractError(
            "unsupported_contract_version: "
            f"expected one of {sorted(compatible)}, received {received}"
        )
    return received


def validate_event(event: str, payload: Mapping[str, Any], contract: Mapping[str, Any] | None = None) -> None:
    contract = contract or load_contract()
    events = contract.get("events", {})
    if event not in events:
        raise HandoffContractError(f"unknown handoff_event: {event}")
    if str(payload.get("handoff_event", "")).strip() != event:
        raise HandoffContractError(f"handoff_event must be {event}")
    validate_version(str(payload.get("handoff_contract_version", "")), contract)
    missing = [
        name for name in events[event].get("required_fields", [])
        if payload.get(name) is None or str(payload.get(name)).strip() == ""
    ]
    if missing:
        raise HandoffContractError(
            f"{event} missing required fields: {', '.join(missing)}"
        )
    if event == "writing_request":
        revision_mode = str(payload.get("revision_mode") or "new_article").strip()
        if revision_mode not in contract.get("revision_modes", {}):
            raise HandoffContractError(f"unsupported revision_mode: {revision_mode}")
        mode_contract = contract["revision_modes"][revision_mode]
        if mode_contract.get("requires_base_article"):
            base_article_id = str(payload.get("base_article_id") or "").strip()
            base_article_version = str(payload.get("base_article_version") or "").strip()
            if not base_article_id or not base_article_version:
                raise HandoffContractError(
                    "revision writing_request requires base_article_id and base_article_version"
                )
            version_pattern = str(mode_contract.get("base_article_version_pattern") or r"^v[1-9]\d*$")
            if not re.fullmatch(version_pattern, base_article_version):
                raise HandoffContractError("base_article_version must use vN")
    if event == "article_completed":
        issuer = str(events[event].get("issuer") or "").strip()
        if issuer != "import_faithfulness.py":
            raise HandoffContractError(
                "article_completed issuer must be import_faithfulness.py"
            )
        if str(payload.get("issuer") or "").strip() != issuer:
            raise HandoffContractError(
                "article_completed payload issuer must be import_faithfulness.py"
            )
        task_dir = str(payload.get("task_dir") or "").replace("\\", "/")
        if "/04_文章任务/40_已完成/" not in task_dir:
            raise HandoffContractError(
                "article_completed task_dir must be under 04_文章任务/40_已完成"
            )


def validate_completion_receipt(
    payload: Mapping[str, Any], contract: Mapping[str, Any] | None = None
) -> Path:
    """Validate an article_completed event against the current completed task files."""
    contract = contract or load_contract()
    validate_event("article_completed", payload, contract)
    task_dir = Path(str(payload["task_dir"])).resolve()
    if not task_dir.is_dir() or task_dir.parent.name != "40_已完成":
        raise HandoffContractError(
            "completion receipt task_dir does not exist under 40_已完成"
        )
    receipt = task_dir / "50_文章知识使用与Faithfulness记录.md"
    if not receipt.is_file():
        raise HandoffContractError("completion receipt is missing current 50 record")
    text = receipt.read_text(encoding="utf-8-sig")
    expected = {
        f"- 文章ID：{payload['article_id']}",
        f"- 文章版本：{payload['article_version']}",
        f"- Faithfulness导入日期：{payload['faithfulness_imported_at']}",
        f"- 导入ID：{payload['audit_id']}",
    }
    missing = sorted(item for item in expected if item not in text)
    if missing or "- Faithfulness导入日期：未导入" in text:
        details = "; ".join(missing) or "Faithfulness remains unimported"
        raise HandoffContractError(f"completion receipt does not match current 50: {details}")
    return task_dir


def self_test() -> None:
    contract = load_contract()
    version = current_version(contract)
    payload = {
        "handoff_event": "faithfulness_completed",
        "handoff_contract_version": version,
        "result_dir": "C:/audit/PROJECT/ARTICLE/v1",
        "article_id": "ARTICLE",
        "article_version": "v1",
    }
    validate_event("faithfulness_completed", payload, contract)
    completed_payload = {
        "handoff_event": "article_completed",
        "handoff_contract_version": version,
        "issuer": "import_faithfulness.py",
        "article_id": "ARTICLE",
        "article_version": "v1",
        "task_dir": "C:/knowledge/PROJECT/04_文章任务/40_已完成/ARTICLE_Title",
        "audit_id": "AUDIT-001",
        "faithfulness_imported_at": "2026-09-11T12:00:00+08:00",
    }
    validate_event("article_completed", completed_payload, contract)
    invalid_completed = dict(
        completed_payload,
        task_dir="C:/knowledge/PROJECT/04_文章任务/30_等待Faithfulness/ARTICLE_Title",
    )
    try:
        validate_event("article_completed", invalid_completed, contract)
    except HandoffContractError:
        pass
    else:
        raise AssertionError("article_completed outside 40_已完成 was accepted")
    revision_payload = {
        "handoff_event": "writing_request",
        "handoff_contract_version": version,
        "project": "C:/knowledge/PROJECT",
        "external_task_key": "TASK-001",
        "request_text": "按原大纲重新整理知识并重写",
        "request_record_path": "C:/writing/task.md",
        "request_record_locator": "TASK-001",
        "title_or_topic": "Product guide",
        "product_or_content_object": "Product",
        "topic_direction": "Guide",
        "keywords": "product",
        "outline": "- Main question",
        "outline_status": "已确认",
        "target_language": "English",
        "constraints": "无",
        "original_writing_requirements": "Keep the original workflow",
        "current_status": "可准备知识",
        "writing_skill": "writer",
        "revision_mode": "knowledge_refresh_and_rewrite",
        "base_article_id": "ARTICLE",
        "base_article_version": "v1",
    }
    validate_event("writing_request", revision_payload, contract)
    missing_baseline = dict(revision_payload)
    missing_baseline.pop("base_article_id")
    try:
        validate_event("writing_request", missing_baseline, contract)
    except HandoffContractError:
        pass
    else:
        raise AssertionError("revision request without base article identity was accepted")
    invalid_baseline = dict(revision_payload, base_article_version="2")
    try:
        validate_event("writing_request", invalid_baseline, contract)
    except HandoffContractError:
        pass
    else:
        raise AssertionError("revision request with invalid base version was accepted")
    revision_payload["revision_mode"] = "guess_and_rewrite"
    try:
        validate_event("writing_request", revision_payload, contract)
    except HandoffContractError:
        pass
    else:
        raise AssertionError("unsupported revision mode was accepted")
    try:
        validate_version("MAK-HANDOFF-99.0", contract)
    except HandoffContractError:
        pass
    else:
        raise AssertionError("unsupported version was accepted")
    incomplete_error = {
        "handoff_event": "handoff_error",
        "handoff_contract_version": version,
        "error_code": "faithfulness_skill_not_found",
        "blocked_step": "faithfulness_request",
        "reason": "审核Skill不可用",
        "resume_condition": "安装或提供目录后重试",
    }
    try:
        validate_event("handoff_error", incomplete_error, contract)
    except HandoffContractError:
        pass
    else:
        raise AssertionError("handoff_error without human guidance was accepted")
    with tempfile.TemporaryDirectory() as directory:
        completed_dir = (
            Path(directory)
            / "PROJECT/04_文章任务/40_已完成/ARTICLE_Title"
        )
        completed_dir.mkdir(parents=True)
        completed_dir.joinpath("50_文章知识使用与Faithfulness记录.md").write_text(
            "\n".join(
                [
                    "# 文章知识使用与Faithfulness记录",
                    "",
                    "- 文章ID：ARTICLE",
                    "- 文章版本：v1",
                    "- Faithfulness导入日期：2026-09-11T12:00:00+08:00",
                    "- 导入ID：AUDIT-001",
                ]
            ),
            encoding="utf-8",
        )
        completion_fixture = dict(completed_payload, task_dir=str(completed_dir))
        validate_completion_receipt(completion_fixture, contract)
        wrong_version = dict(completion_fixture, article_version="v2")
        try:
            validate_completion_receipt(wrong_version, contract)
        except HandoffContractError:
            pass
        else:
            raise AssertionError("completion receipt with wrong current version was accepted")
        broken = Path(directory) / "contract.json"
        broken.write_text("{}", encoding="utf-8")
        try:
            load_contract(broken)
        except HandoffContractError:
            pass
        else:
            raise AssertionError("broken contract was accepted")
    print(f"self-test=passed\nhandoff_contract_version={version}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--print-version", action="store_true")
    parser.add_argument("--event")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--verify-completion", action="store_true")
    parser.add_argument("--expected-article-id")
    parser.add_argument("--expected-article-version")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    contract = load_contract(args.contract)
    if args.print_version:
        print(current_version(contract))
        return
    if not args.event or not args.payload:
        parser.error("provide --print-version, --self-test, or both --event and --payload")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    if args.verify_completion:
        if not args.expected_article_id or not args.expected_article_version:
            parser.error(
                "--verify-completion requires --expected-article-id and "
                "--expected-article-version"
            )
        if str(payload.get("article_id")) != args.expected_article_id:
            raise HandoffContractError("completion article_id does not match current chain")
        if str(payload.get("article_version")) != args.expected_article_version:
            raise HandoffContractError("completion article_version does not match current chain")
        task_dir = validate_completion_receipt(payload, contract)
        print(f"handoff_event=article_completed\ncompletion_verified=true\ntask_dir={task_dir}")
        return
    validate_event(args.event, payload, contract)
    print(f"handoff_event={args.event}\nvalidation=passed")


if __name__ == "__main__":
    main()
