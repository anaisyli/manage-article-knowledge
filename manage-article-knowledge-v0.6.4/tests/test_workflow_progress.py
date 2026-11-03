from __future__ import annotations

import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(r"D:\01 测试项目\mak-v062-continuation-tests-20261020")
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_progress as progress
import workflow_guard as guard
import run_knowledge_workflow as workflow
from handoff_contract import current_version


class WorkflowProgressTests(unittest.TestCase):
    def setUp(self):
        self.root = TEST_ROOT / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / "P-TEST"
        self.ledger = self.project / "04_文章任务/批次运行/B-1.json"
        self.members = [{"article_id": "ART-001", "article_version": "v1", "research_run_id": "RUN-1"}]
        progress.write(self.ledger, {"batch_id": "B-1", "articles": self.members, "evidence": []})
        self.checkpoint = progress.bind(self.project, "B-1", scope="article")

    def cli(self, command, *extra):
        env = dict(os.environ)
        env.pop("CODEX_THREAD_ID", None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/workflow_progress.py"), command,
             "--project", str(self.project), "--batch-id", "B-1", *extra],
            capture_output=True, env=env,
        )
        return result, json.loads(result.stdout)

    def task(self, state="10_进行中", article_id="ART-001"):
        task = self.project / "04_文章任务" / state / (article_id + "_测试文章")
        task.mkdir(parents=True, exist_ok=True)
        (task / "10_文章知识需求.md").write_text(
            f"- 文章ID：{article_id}\n- 当前版本：v1\n- 批次ID：B-1\n", encoding="utf-8")
        return task

    def pause(self, article_id="ART-001", **changes):
        kwargs = dict(kind="missing_material", problem="缺少客户产品范围确认",
                      attempted="已核对当前资料，仍无法确认", operator_action="请向客户确认产品范围",
                      resume_condition="回复确认结果后从当前进度继续")
        kwargs.update(changes)
        progress.pause(self.project, "B-1", article_id, **kwargs)

    def receipt(self):
        task = self.task("40_已完成")
        (task / "50_文章知识使用与Faithfulness记录.md").write_text(
            "- 文章ID：ART-001\n- 文章版本：v1\n- Faithfulness导入日期：2026-10-20\n- 导入ID：AUD-1\n", encoding="utf-8")
        receipt = self.root / "audit/article_completed.json"
        progress.write(receipt, {"handoff_event": "article_completed", "handoff_contract_version": current_version(),
                                 "issuer": "import_faithfulness.py", "article_id": "ART-001", "article_version": "v1",
                                 "task_dir": str(task), "audit_id": "AUD-1", "faithfulness_imported_at": "2026-10-20"})
        return task, receipt

    def test_status_survives_new_process_without_codex_or_hook(self):
        result, data = self.cli("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["status"], "continue")
        self.assertFalse(data["terminal"])
        self.assertEqual(data["runnable"], ["ART-001"])
        self.assertTrue(progress.read(self.checkpoint)["active"])

    def test_batch_entry_saves_hook_free_progress_pointer(self):
        env = dict(os.environ)
        env.pop("CODEX_THREAD_ID", None)
        env["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_knowledge_workflow.py"),
             "--project", str(self.project), "--batch-id", "B-1"],
            capture_output=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["continuation"]["saved"])
        self.assertFalse(receipt["continuation"]["hook_required"])
        self.assertTrue(self.checkpoint.is_file())
        self.assertFalse(progress.status(self.project, "B-1")["terminal"])

    def test_rebound_version_does_not_reuse_old_receipt_action(self):
        env = dict(os.environ)
        env.pop("CODEX_THREAD_ID", None)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_knowledge_workflow.py"),
             "--project", str(self.project), "--batch-id", "B-1"],
            check=True, capture_output=True, env=env,
        )
        ledger = progress.read(self.ledger)
        ledger["articles"][0]["article_version"] = "v2"
        progress.write(self.ledger, ledger)
        progress.bind(self.project, "B-1", scope="knowledge")
        state = progress.status(self.project, "B-1")
        self.assertIn("最近一次有效回执", state["next_action"])
        self.assertNotIn("按当前10的大纲继续", state["next_action"])

    def test_repeated_status_is_read_only_and_never_exhausts_retries(self):
        before = self.checkpoint.read_bytes()
        for _ in range(30):
            self.assertEqual(progress.status(self.project, "B-1")["status"], "continue")
        self.assertEqual(before, self.checkpoint.read_bytes())

    def test_resume_preserves_other_article_pause(self):
        ledger = progress.read(self.ledger)
        ledger["articles"].append({"article_id": "ART-002", "article_version": "v1"})
        progress.write(self.ledger, ledger)
        progress.bind(self.project, "B-1")
        self.pause()
        self.assertEqual(progress.status(self.project, "B-1")["runnable"], ["ART-002"])
        self.pause("ART-002")
        self.assertEqual(progress.status(self.project, "B-1")["status"], "paused")
        result, data = self.cli("resume", "--article-id", "ART-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["runnable"], ["ART-001"])
        self.assertIn("ART-002", data["pauses"])

    def test_bind_same_identity_does_not_erase_pause_or_scope(self):
        self.pause()
        progress.bind(self.project, "B-1")
        self.assertEqual(progress.status(self.project, "B-1")["status"], "paused")
        self.assertEqual(progress.read(self.checkpoint)["scope"], "article")

    def test_version_change_is_rejected_until_current_request_rebound(self):
        self.pause()
        ledger = progress.read(self.ledger)
        ledger["articles"][0]["article_version"] = "v2"
        progress.write(self.ledger, ledger)
        result, data = self.cli("status")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(data["terminal"])
        progress.bind(self.project, "B-1", scope="article")
        self.assertEqual(progress.read(self.checkpoint)["pauses"], {})

    def test_terminal_flag_and_completed_directory_do_not_prove_success(self):
        self.task("40_已完成")
        progress.write(workflow.state_path_for(self.ledger), {
            "project": str(self.project), "batch_id": "B-1", "terminal": True, "event": "article_completed"})
        self.assertFalse(progress.status(self.project, "B-1")["goal_verified"])

    def test_real_import_receipt_is_registered_without_session_and_rechecked(self):
        task, receipt = self.receipt()
        progress.record_completion(receipt)
        result, data = self.cli("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(data["goal_verified"])
        self.assertEqual(data["status"], "complete")
        record = task / "50_文章知识使用与Faithfulness记录.md"
        record.write_text("尚未导入", encoding="utf-8")
        result, data = self.cli("status")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(data["terminal"])

    def test_importer_automatically_records_durable_receipt(self):
        import import_faithfulness
        task, receipt = self.receipt()
        # Fixture omits unrelated template rows; real completion validation runs.
        with patch.object(import_faithfulness, "validate_file", return_value=[]):
            import_faithfulness.write_completion_receipt(
                receipt.parent, contract_version=current_version(), article_id="ART-001",
                article_version="v1", task_dir=str(task), audit_id="AUD-1", imported_at="2026-10-20")
        self.assertTrue(progress.status(self.project, "B-1")["goal_verified"])

    def test_user_interruption_requires_actual_evidence(self):
        with self.assertRaises(ValueError):
            self.pause(kind="user_requested")
        self.pause(kind="interruption_unknown", problem="中断原因未确认")
        data = progress.status(self.project, "B-1")
        self.assertIn("中断原因未确认", data["human_message"])
        self.assertNotIn("用户中断", data["human_message"])

    def test_platform_capability_pause_does_not_issue_writing_permit(self):
        task = self.task()
        self.pause(kind="platform_capability", problem="当前平台不能运行规定校验，尚无获准执行方")
        data = progress.status(self.project, "B-1")
        self.assertEqual(data["status"], "paused")
        self.assertFalse(data["goal_verified"])
        self.assertFalse((task / "writing_ready.json").exists())

    def test_unknown_inactive_checkpoint_is_not_attributed_to_user(self):
        data = progress.read(self.checkpoint)
        data["active"] = False
        progress.write(self.checkpoint, data)
        self.assertIn("中断原因未确认", progress.status(self.project, "B-1")["human_message"])

    def test_executor_release_is_not_reported_as_platform_or_user_interruption(self):
        progress.release(self.project, "B-1", evidence="执行方明确解除本轮续接")
        message = progress.status(self.project, "B-1")["human_message"]
        self.assertIn("执行方已明确解除本轮续接", message)
        self.assertNotIn("收到平台中断记录", message)
        self.assertNotIn("用户中断", message)

    def test_optional_guard_release_keeps_generic_reason_distinct(self):
        registry = self.root / "registry"
        guard.bind(self.project, "B-1", scope="article", session_id="test", root=registry)
        registry_file = guard.registry_path("test", registry)
        with (patch.object(guard, "registry_path", return_value=registry_file),
              patch.object(sys, "argv", ["workflow_guard.py", "release"]),
              patch.dict(os.environ, {"CODEX_THREAD_ID": "test"}),
              redirect_stdout(io.StringIO())):
            guard.main()
        message = progress.status(self.project, "B-1")["human_message"]
        self.assertIn("执行方已明确解除本轮续接", message)
        self.assertNotIn("收到平台中断记录", message)

    def test_checkpoint_paths_must_stay_within_selected_project(self):
        other = self.root / "other-client.json"
        other.write_text("not valid JSON: should never be read", encoding="utf-8")
        data = progress.read(self.checkpoint)
        data["receipt"] = str(other)
        progress.write(self.checkpoint, data)
        with self.assertRaisesRegex(ValueError, "路径不一致"):
            progress.status(self.project, "B-1")

    def test_legacy_ledger_resolution_ignores_derived_checkpoints(self):
        legacy = self.ledger.with_name("legacy.json")
        self.ledger.rename(legacy)
        progress.write(workflow.state_path_for(legacy), {"batch_id": "B-1"})
        self.assertEqual(workflow.resolve_ledger(self.project, "B-1"), legacy)

    def test_optional_hook_respects_base_pause_and_actual_interrupt(self):
        registry = self.root / "registry"
        guard.bind(self.project, "B-1", scope="article", session_id="test", root=registry)
        self.pause()
        result = guard.check({"session_id": "test", "hook_event_name": "Stop"}, root=registry)
        self.assertIn("请向客户确认产品范围", result["reason"])
        progress.resume(self.project, "B-1")
        guard.bind(self.project, "B-1", scope="article", session_id="test", root=registry)
        guard.check({"session_id": "test", "hook_event_name": "Interrupt"}, root=registry)
        self.assertEqual(progress.status(self.project, "B-1")["status"], "paused")
        self.assertEqual(progress.read(self.checkpoint)["interruption"]["kind"], "platform_interrupt")


if __name__ == "__main__":
    unittest.main()
