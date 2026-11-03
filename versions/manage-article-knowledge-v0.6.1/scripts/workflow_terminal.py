#!/usr/bin/env python3
"""Decide whether an article workflow may end for a human-facing run."""

from __future__ import annotations

from dataclasses import dataclass
import json
import argparse
from pathlib import Path


NON_TERMINAL_REASONS = {
    "writing_request_received",
    "writing_ready_pending",
    "research_required",
    "template_validation_failed",
    "delivery_gate_failed",
    "moved_count_zero",
    "tool_retryable_failure",
    "writing_gate_blocked",
    "writing_ready_issued",
    "handoff_waiting_knowledge_fix",
    "knowledge_repair_required",
}
TERMINAL_EVENTS = {"article_completed", "needs_human", "handoff_error"}


@dataclass(frozen=True)
class WorkflowDecision:
    terminal: bool
    next_action: str
    reason: str


def decision_from_gate_output(output: str | bytes | dict[str, object]) -> WorkflowDecision:
    """Consume a writing gate result without treating exit code 2 as terminal.

    Gate scripts may return a non-zero process status because the article is not
    ready.  The structured ``terminal`` field is the source of truth; a
    recoverable blocked result always returns a non-terminal decision.
    """
    if isinstance(output, dict):
        payload = output
    else:
        text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            payload = {}
            for line in str(text).splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    payload[key.strip()] = value.strip()
    if payload.get("terminal") is False or str(payload.get("terminal", "")).lower() == "false":
        if str(payload.get("writing_gate_status", "")).lower() == "ready":
            return WorkflowDecision(
                False,
                "写作Skill读取并核对writing_ready.json后开始写作；终稿返回后回到知识库",
                "writing_ready_issued",
            )
        reason = str(payload.get("writing_gate_status") or payload.get("workflow_state") or "writing_gate_blocked")
        return decide(reason=reason if reason in NON_TERMINAL_REASONS else "writing_gate_blocked")
    if payload.get("terminal") is True or str(payload.get("terminal", "")).lower() == "true":
        event = str(payload.get("handoff_event") or payload.get("event") or "")
        # A terminal flag is only actionable when it carries one of the
        # contract's explicit terminal events.  A stale/malformed ``reason``
        # must never upgrade an intermediate result into a stop signal.
        if event in TERMINAL_EVENTS:
            return decide(event=event)
        return decide(reason="handoff_waiting_knowledge_fix")
    # Missing or malformed machine output is not proof of completion.
    return decide(reason="handoff_waiting_knowledge_fix")


def decide(*, event: str | None = None, reason: str | None = None) -> WorkflowDecision:
    """Return a conservative continuation decision.

    A missing or intermediate event is never treated as completion.  This is
    intentionally independent of article content so callers cannot turn a
    template or research error into a successful terminal response.
    """
    # ``reason`` is descriptive only.  It is intentionally not a second
    # terminal channel: only an explicit contract event may end the chain.
    if event in TERMINAL_EVENTS:
        return WorkflowDecision(True, "结束当前文章链路", event)
    continuation_reason = reason if reason in NON_TERMINAL_REASONS else event
    return WorkflowDecision(
        False,
        "从当前记录的阻塞步骤继续；完成后重新运行推进检查",
        continuation_reason or "未签发终点事件",
    )


def assert_terminal_event(event: str) -> None:
    """Raise when a caller tries to finish on an intermediate event."""
    if event not in TERMINAL_EVENTS:
        raise ValueError(
            f"{event}不是终止事件；只有article_completed、needs_human或handoff_error允许结束"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consume a machine gate result without using process exit code as terminal state")
    parser.add_argument("--gate-result", type=Path)
    parser.add_argument("--text")
    args = parser.parse_args()
    if args.gate_result:
        decision = decision_from_gate_output(args.gate_result.read_text(encoding="utf-8-sig"))
        print(json.dumps({"terminal": decision.terminal, "next_action": decision.next_action, "reason": decision.reason}, ensure_ascii=False))
    elif args.text:
        decision = decision_from_gate_output(args.text)
        print(json.dumps({"terminal": decision.terminal, "next_action": decision.next_action, "reason": decision.reason}, ensure_ascii=False))
    else:
        for sample in ("research_required", "template_validation_failed", "article_completed"):
            result = decide(reason=sample)
            print(f"reason={sample}\nterminal={str(result.terminal).lower()}\nnext_action={result.next_action}")
