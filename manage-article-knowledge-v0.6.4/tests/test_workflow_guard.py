from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(r"D:\01 测试项目\mak-v062-continuation-tests-20261020")
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_guard as guard
from handoff_contract import current_version
from install_workflow_guard import install


class WorkflowGuardTests(unittest.TestCase):
    def setUp(self):
        self.root = TEST_ROOT / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.registry = self.root / "registry"
        self.project = self.root / "P-TEST"
        self.ledger = self.project / "04_文章任务/批次运行/B-1.json"
        self.members = [{"article_id": "ART-001", "article_version": "v1", "research_run_id": "RUN-1"}]
        guard.write(self.ledger, {"batch_id": "B-1", "articles": self.members, "evidence": []})
        self.bind()
        self.event = {"session_id": "test-session", "hook_event_name": "Stop", "stop_hook_active": False}

    def bind(self, scope="knowledge"):
        return guard.bind(self.project, "B-1", scope=scope, session_id="test-session", root=self.registry)

    def state(self):
        return guard.read(guard.registry_path("test-session", self.registry))

    def save(self, data):
        guard.write(guard.registry_path("test-session", self.registry), data)

    def check(self):
        return guard.check(self.event, root=self.registry)

    def task(self, state="20_等待终稿", article_id="ART-001"):
        task = self.project / "04_文章任务" / state / (article_id + "_测试文章")
        task.mkdir(parents=True, exist_ok=True)
        (task / "10_文章知识需求.md").write_text(f"- 文章ID：{article_id}\n- 当前版本：v1\n", encoding="utf-8")
        return task

    def ready(self):
        import hashlib
        task = self.task()
        material = task / "30_本篇知识库资料.md"
        material.write_text("当前事实正文", encoding="utf-8")
        guard.write(task / "writing_ready.json", {
            "article_id": "ART-001", "article_version": "v1",
            "handoff_contract_version": current_version(),
            "knowledge_sha256": hashlib.sha256(material.read_bytes()).hexdigest(),
        })
        guard.write(task / "writing_gate_result.json", {
            "article_id": "ART-001", "article_version": "v1", "writing_gate_status": "ready",
        })
        return task

    def test_unbound_session_and_ordinary_chat_are_not_intercepted(self):
        self.assertEqual(guard.check({"session_id": "other"}, root=self.registry), {})
        self.assertEqual(guard.check({}, root=self.registry), {})

    def test_empty_sources_force_continuation_even_if_already_continued(self):
        self.assertEqual(self.check()["decision"], "block")
        self.event["stop_hook_active"] = True
        self.assertEqual(self.check()["decision"], "block")
        self.assertTrue(self.state()["active"])

    def test_untrusted_terminal_flag_cannot_complete_work(self):
        data = self.state()
        guard.write(Path(data["receipt"]), {
            "project": str(self.project), "batch_id": "B-1", "terminal": True, "event": "article_completed",
        })
        self.assertEqual(self.check()["decision"], "block")

    def test_timestamp_only_changes_do_not_evade_stagnation(self):
        for index in range(4):
            ledger = guard.read(self.ledger)
            ledger["updated_at"] = str(index)
            guard.write(self.ledger, ledger)
            result = self.check()
        self.assertFalse(self.state()["active"])
        self.assertIn("暂停", result["reason"])
        self.assertIn("从保存的位置继续", result["reason"])
        self.assertEqual(self.check(), {})  # explanation continuation can end

    def test_real_evidence_changes_allow_many_continuations(self):
        for index in range(6):
            ledger = guard.read(self.ledger)
            ledger["evidence"].append({"original_excerpt": "新证据" + str(index)})
            guard.write(self.ledger, ledger)
            self.assertEqual(self.check()["decision"], "block")
            self.assertTrue(self.state()["active"])
        self.assertEqual(self.state()["stagnant"], 0)

    def test_one_paused_article_does_not_block_other_article(self):
        ledger = guard.read(self.ledger)
        ledger["articles"].append({"article_id": "ART-002", "article_version": "v1"})
        guard.write(self.ledger, ledger)
        self.bind()
        data = self.state()
        data["pauses"] = {"ART-001": {"problem": "缺少客户确认", "attempted": "已核对资料",
                                       "operator_action": "请确认产品范围", "resume_condition": "回复后接着做"}}
        self.save(data)
        result = self.check()
        self.assertIn("继续处理 ART-002", result["reason"])
        self.assertNotIn("继续处理 ART-001", result["reason"])

    def test_all_paused_articles_get_human_explanation_then_stop(self):
        data = self.state()
        data["pauses"] = {"ART-001": {"problem": "缺少客户确认", "attempted": "已核对客户资料和官网",
                                       "operator_action": "请向客户确认", "resume_condition": "回复确认结果后自动接着做"}}
        self.save(data)
        result = self.check()
        for value in ("缺少客户确认", "已核对客户资料和官网", "请向客户确认", "回复确认结果"):
            self.assertIn(value, result["reason"])
        self.assertFalse(self.state()["active"])
        self.assertEqual(self.check(), {})

    def test_interrupt_saves_progress_and_does_not_restart(self):
        result = guard.check(dict(self.event, hook_event_name="Interrupt"), root=self.registry)
        self.assertIn("保留进度", result["systemMessage"])
        self.assertFalse(self.state()["active"])
        self.assertEqual(self.check(), {})

    def test_version_switch_requires_rebinding(self):
        ledger = guard.read(self.ledger)
        ledger["articles"][0]["article_version"] = "v2"
        guard.write(self.ledger, ledger)
        self.assertIn("身份已变化", self.check()["reason"])
        self.bind()
        self.assertEqual(self.state()["articles"][0]["article_version"], "v2")

    def test_missing_checkpoint_gets_recovery_attempts_before_pause(self):
        self.ledger.unlink()
        for _ in range(2):
            self.assertIn("先检查", self.check()["reason"])
            self.assertTrue(self.state()["active"])
        self.assertIn("暂停", self.check()["reason"])
        self.assertFalse(self.state()["active"])

    def test_ready_permit_finishes_only_knowledge_scope(self):
        self.ready()
        with patch("article_state.article_package_errors", return_value=[]):
            self.assertEqual(self.check(), {})
        self.bind("article")
        self.assertEqual(self.check()["decision"], "block")

    def test_changed_material_invalidates_ready_permit(self):
        task = self.ready()
        (task / "30_本篇知识库资料.md").write_text("已变化的事实", encoding="utf-8")
        with patch("article_state.article_package_errors", return_value=[]):
            self.assertEqual(self.check()["decision"], "block")
        self.assertTrue(self.state()["active"])

    def test_validated_import_receipt_finishes_article_scope(self):
        self.bind("article")
        task = self.task("40_已完成")
        (task / "50_文章知识使用与Faithfulness记录.md").write_text(
            "- 文章ID：ART-001\n- 文章版本：v1\n- Faithfulness导入日期：2026-10-20\n- 导入ID：AUD-1\n", encoding="utf-8")
        receipt = self.root / "audit/article_completed.json"
        guard.write(receipt, {"handoff_event": "article_completed", "handoff_contract_version": current_version(),
                              "issuer": "import_faithfulness.py", "article_id": "ART-001", "article_version": "v1",
                              "task_dir": str(task), "audit_id": "AUD-1", "faithfulness_imported_at": "2026-10-20"})
        guard.record_completion(receipt, session_id="test-session", root=self.registry)
        self.assertEqual(self.check(), {})
        self.assertFalse(self.state()["active"])

    def test_completed_directory_without_import_receipt_cannot_finish(self):
        self.bind("article")
        self.task("40_已完成")
        self.assertEqual(self.check()["decision"], "block")

    def test_repeated_runner_binding_does_not_reset_stagnation(self):
        self.check()
        self.bind()
        self.check()
        self.assertEqual(self.state()["stagnant"], 1)

    def test_install_preserves_other_hooks_and_is_idempotent(self):
        config = self.root / "config"
        guard.write(config / "hooks.json", {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing-check"}]}]}})
        path = install(config)
        first = path.read_bytes()
        self.assertEqual(len(guard.read(path)["hooks"]["Stop"]), 2)
        self.assertIn("existing-check", first.decode())
        install(config)
        self.assertEqual(first, path.read_bytes())
        self.assertEqual(len(list(config.glob("*.mak-backup-*"))), 1)

    def test_actual_hook_process_accepts_event_and_returns_continuation_json(self):
        child_registry = self.root / "mak-workflow-guard"
        guard.write(guard.registry_path("test-session", child_registry), self.state())
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/workflow_guard.py"), "hook"],
            input=json.dumps(self.event).encode("utf-8"), capture_output=True,
            env=dict(os.environ, TEMP=str(self.root), TMP=str(self.root)),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("仍可推进1篇", payload["reason"])


if __name__ == "__main__":
    unittest.main()
