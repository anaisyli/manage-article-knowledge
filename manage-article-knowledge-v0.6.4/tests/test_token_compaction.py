from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capture_website_evidence as capture  # noqa: E402
import faithfulness_unsupported_digest as digest  # noqa: E402
import reference_section  # noqa: E402
import run_knowledge_workflow as workflow  # noqa: E402


class UnsupportedDigestTests(unittest.TestCase):
    def test_self_test(self) -> None:
        self.assertEqual(digest.self_test(), 0)

    def test_process_limitation_candidate_matches_importer_rule(self) -> None:
        claim = {
            "semantic_status": "unknown",
            "reconciliation": {
                "first_pass_semantic_status": "entailed", "independent_semantic_status": "entailed",
                "final_semantic_status": "unknown", "reasons": ["quantity_time_version未被证据覆盖"],
            },
        }
        self.assertTrue(digest.process_limitation_candidate(claim))
        claim["reconciliation"]["independent_semantic_status"] = "unknown"
        self.assertFalse(digest.process_limitation_candidate(claim))


class CompactReceiptTests(unittest.TestCase):
    def test_compact_drops_constant_rules_and_duplicated_errors(self) -> None:
        receipt = {
            "schema": workflow.SCHEMA, "batch_id": "B-1", "workflow_state": "article_knowledge_preparation",
            "terminal": False, "next_owner": "manage-article-knowledge", "next_action": "逐篇处理",
            "ledger": str(Path("P") / "04_文章任务" / "批次运行" / "B-1.json"),
            "executor_rule": "长规则", "resume_rule": "长规则", "writer_lock": "长规则",
            "errors": ["缺20"], "pending_steps": [{"article_id": "A-1", "errors": ["缺20"]}],
            "articles": [{"article_id": "A-1", "state": "knowledge_repair_required", "errors": ["缺20", "缺35"],
                          "next_action": "只修复本篇以下缺项后重跑本入口：缺20",
                          "recovery": {"changed": [], "actions": ["x"], "unresolved": []}}],
            "continuation": {"saved": True, "checkpoint": "c.json", "hook_required": False},
        }
        compact = workflow.compact_receipt(receipt)
        for key in ("executor_rule", "resume_rule", "writer_lock", "pending_steps", "errors"):
            self.assertNotIn(key, compact)
        self.assertEqual(compact["articles"][0]["errors"], ["缺35"])
        self.assertTrue(compact["receipt_file"].endswith("B-1.workflow.json"))
        self.assertTrue(compact["continuation"]["saved"])

    def test_cli_full_flag_keeps_complete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_knowledge_workflow.py"),
                 "--project", str(Path(temp) / "P"), "--batch-id", "B-X", "--full"],
                capture_output=True,
            )
            payload = json.loads(result.stdout.decode("utf-8", errors="replace"))
            self.assertIn("errors", payload)
            self.assertIn("started_at", payload)


class BrowserCaptureTests(unittest.TestCase):
    def test_browser_capture_records_continuous_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "capture.json"
            source.write_text(json.dumps({
                "url": "https://example.com/p", "title": "Box", "captured_at": "2026-10-23T01:00:00Z",
                "capture_method": "browser DOM paragraph extraction",
                "blocks": [{"section": "Description", "text": "This paper box can be tailored in size and finish."}],
            }), encoding="utf-8")
            page = capture.load_browser_capture(source)
            record = capture.append_record(Path(temp) / "m.json", page, "Q1", "Description; p1",
                                           "This paper box can be tailored in size", "PRIMARY-WEBSITE",
                                           "客户官网", "run-1")
            self.assertEqual(record["evidence_id"], "EV-001")
            self.assertEqual(record["block_tag"], "p")
            self.assertEqual(record["heading_path"], ["Description"])
            self.assertIn("浏览器", record["response_hash_scope"])
            with self.assertRaises(ValueError):
                capture.append_record(Path(temp) / "m.json", page, "Q1", "p", "text that never appeared on the page",
                                      "PRIMARY-WEBSITE", "客户官网", "run-1")

    def test_browser_capture_requires_method_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "capture.json"
            source.write_text(json.dumps({"url": "https://example.com/p", "blocks": [{"text": "x" * 30}]}),
                              encoding="utf-8")
            with self.assertRaises(ValueError):
                capture.load_browser_capture(source)


class ReferenceSectionTests(unittest.TestCase):
    def test_prints_section_until_next_same_level_heading(self) -> None:
        text = "# T\n## 1. 甲\na\n### 1.1 子\nb\n## 2. 乙\nc\n"
        output, missing = reference_section.sections(text, ["甲"])
        self.assertEqual(missing, [])
        self.assertIn("b", output)
        self.assertNotIn("c", output)
        self.assertEqual(reference_section.sections(text, ["丙"])[1], ["丙"])

    def test_skill_section_map_headings_exist(self) -> None:
        checks = {
            "references/runtime-checklist.md": ["文章任务"],
            "references/skill-integration-handoff.md": ["交接合同版本", "0.1", "0.2", "0.3", "3.", "5.", "6.", "7."],
            "references/faithfulness-result-contract.md": ["5.", "6.", "7."],
        }
        for name, headings in checks.items():
            _, missing = reference_section.sections((ROOT / name).read_text(encoding="utf-8-sig"), headings)
            self.assertEqual(missing, [], name)


if __name__ == "__main__":
    unittest.main()
