from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "manage-article-knowledge-v0.6.1"
SCRIPT = SKILL / "scripts" / "run_knowledge_workflow.py"
sys.path.insert(0, str(SKILL / "scripts"))

import run_knowledge_workflow as workflow  # noqa: E402


class KnowledgeWorkflowTests(unittest.TestCase):
    def write_ledger(self, root: Path, batch_id: str = "B-001") -> Path:
        path = workflow.conventional_ledger(root, batch_id)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "MAK-BATCH-1.0",
                    "batch_id": batch_id,
                    "status": "collecting_requests",
                    "articles": [{"article_id": "ART-001"}],
                    "questions": [],
                    "evidence": [],
                    "governance": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_derives_ledger_and_empty_evidence_is_nonterminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "P-TEST_测试知识库_v0.6"
            ledger = self.write_ledger(project)
            result = workflow.run_workflow(project, "B-001")
            self.assertEqual(result["ledger"], str(ledger))
            self.assertEqual(result["workflow_state"], "source_collection")
            self.assertFalse(result["terminal"])
            self.assertIn("terminal_decision", result)
            saved = json.loads(workflow.state_path_for(ledger).read_text(encoding="utf-8"))
            self.assertFalse(saved["terminal"])
            self.assertIn("批次账本尚未形成证据记录", "\n".join(saved["errors"]))

    def test_legacy_ledger_is_found_only_by_exact_batch_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "P-TEST"
            root = project / "04_文章任务/批次运行"
            root.mkdir(parents=True)
            legacy = root / "legacy-name.json"
            legacy.write_text(json.dumps({"batch_id": "B-LEGACY", "evidence": [], "articles": []}), encoding="utf-8")
            self.assertEqual(workflow.resolve_ledger(project, "B-LEGACY"), legacy)
            self.assertEqual(workflow.resolve_ledger(project, "B-OTHER"), root / "B-OTHER.json")

    def test_cli_never_requires_ledger_and_reports_missing_batch_as_nonterminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "P-TEST"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--project", str(project), "--batch-id", "B-MISSING"],
                capture_output=True,
                text=False,
            )
            self.assertEqual(result.returncode, 0)
            payload = json.loads((result.stdout or b"").decode("utf-8", errors="replace"))
            self.assertFalse(payload["terminal"])
            self.assertEqual(payload["workflow_state"], "tool_retryable_failure")


if __name__ == "__main__":
    unittest.main()
