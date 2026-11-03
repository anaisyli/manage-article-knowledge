"""New writing_request outlines must keep one section per list item.

P-005-20261028 regression: the writer submitted ``H1 …; opening: …; H2 …`` as one
line, which ``outline_labels`` read as a single outline question.
"""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import writing_bridge as bridge  # noqa: E402
from template_contract import outline_format_errors, outline_labels  # noqa: E402
from update_integration_status import ARTICLE_LEVEL_EVENTS, INTERFACE_FAILURE_EVENTS  # noqa: E402

ONE_LINE = "H1 Demo Title; opening: assess the pack; H2 What Makes a Claim Verifiable?; summary and FAQs."
LISTED = "- H1 Demo Title\n- opening: assess the pack\n- H2 What Makes a Claim Verifiable?\n- summary and FAQs"


class OutlineFormatTests(unittest.TestCase):
    def test_list_outline_passes_and_gives_one_label_per_section(self):
        self.assertEqual(outline_format_errors(LISTED), [])
        self.assertEqual(outline_format_errors("1. 服务范围\n2) 选型建议"), [])
        self.assertEqual(len(outline_labels("## 大纲\n\n" + LISTED + "\n")), 4)

    def test_prose_line_and_joined_item_are_rejected(self):
        self.assertTrue(any("不是列表项" in e for e in outline_format_errors(ONE_LINE)))
        joined = "- H1 Demo Title; H2 Which Parts Matter?"
        self.assertTrue(any("多个章节" in e for e in outline_format_errors(joined)))
        # A semicolon inside one section's own wording is not a second section.
        self.assertEqual(outline_format_errors("- H2 Paper; board and wrap options"), [])

    def test_format_issue_is_article_level_not_an_interface_outage(self):
        self.assertIn("writing_task_outline_format_required", ARTICLE_LEVEL_EVENTS)
        self.assertNotIn("writing_task_outline_format_required", INTERFACE_FAILURE_EVENTS)


class BridgeOutlineFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name) / "P-TEST_知识库"
        self.root.mkdir()
        record = self.root / "request.md"
        record.write_text("# Confirmed writing task\n", encoding="utf-8")
        self.args = argparse.Namespace(
            project=self.root, handoff_contract_version=bridge.current_version(), external_task_key="TASK-1",
            source_path=record, source_locator="task 1", title="Packaging services",
            request_text="写一篇文章", product_or_content_object="包装服务", topic_direction="服务介绍",
            keywords="packaging", outline=ONE_LINE, outline_id="OUT-1", outline_version="v1",
            outline_status="已确认", target_language="English", constraints="无",
            original_writing_requirements="遵守事实边界", current_status="可准备知识", writing_skill="writer",
            revision_mode=None, base_article_version=None, base_outline_id=None, base_outline_version=None,
            article_id=None, date="2026-10-28", batch_id="",
        )

    def tearDown(self) -> None:
        self._temp.cleanup()

    def tasks(self) -> list[Path]:
        return list((self.root / "04_文章任务/10_进行中").glob("*")) if (self.root / "04_文章任务/10_进行中").is_dir() else []

    def test_new_task_with_one_line_outline_is_refused_then_resubmitted_as_list(self):
        with patch.object(bridge, "sync_skill_version"), patch.object(bridge, "update_integration_status"), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(bridge.OutlineFormatRequiresList) as refused:
                bridge.prepare(self.args)
            self.assertIn("逐行列表", str(refused.exception))
            self.assertEqual(self.tasks(), [])

            self.args.outline = LISTED
            bridge.prepare(self.args)
        tasks = self.tasks()
        self.assertEqual(len(tasks), 1)
        request = (tasks[0] / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
        self.assertEqual(len(outline_labels(request)), 4)

    def test_existing_task_with_recorded_one_line_outline_still_resumes(self):
        with patch.object(bridge, "sync_skill_version"), patch.object(bridge, "update_integration_status"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            # A task registered before this rule keeps its one-line outline.
            with patch("template_contract.outline_format_errors", return_value=[]):
                bridge.prepare(self.args)
            bridge.prepare(self.args)
        self.assertIn("ledger_action=reused", out.getvalue())

    def test_cli_failure_records_article_level_event(self):
        argv = ["writing_bridge.py", "prepare"]
        for name, value in vars(self.args).items():
            if value is not None and name not in {"revision_mode"}:
                argv += [f"--{name.replace('_', '-')}", str(value)]
        with patch.object(sys, "argv", argv), patch.object(bridge, "sync_skill_version"), \
                patch.object(bridge, "update_integration_status") as status, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                bridge.main()
        self.assertEqual(status.call_args.args[1], "writing_task_outline_format_required")


if __name__ == "__main__":
    unittest.main()
