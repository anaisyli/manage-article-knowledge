#!/usr/bin/env python3
"""Load and validate the canonical three-Skill handoff contract."""

from __future__ import annotations

import argparse
import json
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
    required = {"contract_id", "handoff_contract_version", "compatible_versions", "faithfulness_executor", "events"}
    missing = sorted(required - set(value)) if isinstance(value, dict) else sorted(required)
    if missing:
        raise HandoffContractError(f"handoff contract missing fields: {', '.join(missing)}")
    if value["handoff_contract_version"] not in value["compatible_versions"]:
        raise HandoffContractError("current handoff contract version is absent from compatible_versions")
    executor = value.get("faithfulness_executor", {})
    if executor.get("skill_name") != "deepeval-article-audit":
        raise HandoffContractError("faithfulness executor must be deepeval-article-audit")
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
    validate_event(args.event, payload, contract)
    print(f"handoff_event={args.event}\nvalidation=passed")


if __name__ == "__main__":
    main()
