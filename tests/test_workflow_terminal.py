from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_terminal import assert_terminal_event, decide, decision_from_gate_output  # noqa: E402


class WorkflowTerminalTests(unittest.TestCase):
    def test_issue_gate_missing_arguments_emits_recoverable_receipt(self) -> None:
        script = ROOT / "scripts" / "issue_writing_ready.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("terminal=false", result.stdout)
        self.assertIn("writing_gate_status=blocked", result.stdout)

    def test_issue_gate_unknown_task_emits_recoverable_receipt(self) -> None:
        script = ROOT / "scripts" / "issue_writing_ready.py"
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--handoff-contract-version",
                    "MAK-HANDOFF-1.3",
                    "--project",
                    temp,
                    "--article-id",
                    "UNKNOWN-ARTICLE",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("terminal=false", result.stdout)
        self.assertIn("writing_gate_status=blocked", result.stdout)

    def test_issue_gate_missing_article_identity_emits_recoverable_receipt(self) -> None:
        script = ROOT / "scripts" / "issue_writing_ready.py"
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--handoff-contract-version",
                    "MAK-HANDOFF-1.3",
                    "--project",
                    temp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("terminal=false", result.stdout)
        self.assertIn("writing_gate_status=blocked", result.stdout)

    def test_intermediate_states_never_end(self) -> None:
        for reason in (
            "research_required",
            "template_validation_failed",
            "moved_count_zero",
            "tool_retryable_failure",
            "writing_gate_blocked",
            "handoff_waiting_knowledge_fix",
            "knowledge_repair_required",
        ):
            result = decide(reason=reason)
            self.assertFalse(result.terminal)
            self.assertIn("继续", result.next_action)

    def test_only_contract_terminal_events_end(self) -> None:
        for event in ("article_completed", "needs_human", "handoff_error"):
            self.assertTrue(decide(event=event).terminal)
            assert_terminal_event(event)

    def test_unknown_event_is_conservative(self) -> None:
        result = decide(event="writing_ready")
        self.assertFalse(result.terminal)
        with self.assertRaises(ValueError):
            assert_terminal_event("writing_ready")

    def test_terminal_reason_cannot_end_without_terminal_event(self) -> None:
        for reason in ("needs_human", "handoff_error"):
            result = decide(reason=reason)
            self.assertFalse(result.terminal)

    def test_terminal_flag_with_invalid_event_is_conservative(self) -> None:
        result = decision_from_gate_output({
            "terminal": True,
            "event": "writing_ready",
            "reason": "needs_human",
        })
        self.assertFalse(result.terminal)

    def test_structured_blocked_gate_is_recoverable(self) -> None:
        result = decision_from_gate_output({
            "writing_gate_status": "blocked",
            "terminal": False,
            "workflow_state": "writing_ready_pending",
        })
        self.assertFalse(result.terminal)
        self.assertEqual(result.reason, "writing_gate_blocked")

    def test_text_gate_output_does_not_use_exit_code_as_terminal(self) -> None:
        result = decision_from_gate_output(
            "writing_gate_status=blocked\nterminal=false\nworkflow_state=writing_ready_pending"
        )
        self.assertFalse(result.terminal)

    def test_missing_gate_result_is_conservative(self) -> None:
        result = decision_from_gate_output("process exited with code 2")
        self.assertFalse(result.terminal)

    def test_ready_gate_is_non_terminal_but_advances_to_writing(self) -> None:
        result = decision_from_gate_output({
            "writing_gate_status": "ready",
            "terminal": False,
            "workflow_state": "writing_ready_issued",
        })
        self.assertFalse(result.terminal)
        self.assertEqual(result.reason, "writing_ready_issued")
        self.assertIn("开始写作", result.next_action)


if __name__ == "__main__":
    unittest.main()
