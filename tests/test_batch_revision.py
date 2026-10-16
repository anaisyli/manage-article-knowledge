"""Isolated regressions for batch run retirement and read-only identity guards."""
from __future__ import annotations

from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from batch_revision import retire_previous_run
import batch_knowledge_run as batch
import writing_bridge as bridge
import sync_website_evidence as captures
import run_knowledge_workflow as workflow
from run_outline_refresh import check_task, comparison_permitted
from archive_project_version import create_archive


class RetirementTests(unittest.TestCase):
    def payload(self):
        old = {"article_id": "A", "article_version": "v2", "revision_mode": "outline_refresh", "refresh_run_id": "old-run"}
        other = {**old, "article_id": "B"}
        evidence = {"article_ids": ["A", "B"], "candidate_id": "CF-001", "retrieval_run_id": "old-run",
                    "source_path_or_url": "https://example.com/source", "source_sha256": "old-sha"}
        read = {key: value for key, value in evidence.items() if key not in {"article_ids", "candidate_id"}}
        payload = {"batch_id": "BATCH", "articles": [old, other], "evidence": [evidence],
                   "capture_inbox": [{**evidence, "article_ids": ["A"], "article_id": "A"}],
                   "source_reads": [read], "questions": [{"question_id": "Q", "article_ids": ["A", "B"]}],
                   "governance": [{"entry": "existing-governance"}]}
        return payload, {**old, "article_version": "v3", "refresh_run_id": "new-run"}

    def test_shared_rows_retire_only_revised_article_and_preserve_current_checkpoint(self):
        payload, request = self.payload()
        original = deepcopy(payload)
        current = {**payload["evidence"][0], "article_ids": ["A"], "retrieval_run_id": "new-run"}
        payload["evidence"].append(current)
        self.assertTrue(retire_previous_run(payload, request))
        history = payload["run_history"][0]
        self.assertEqual(history["article"], original["articles"][0])
        self.assertEqual(history["evidence"], original["evidence"])
        self.assertEqual(history["source_reads"], original["source_reads"])
        self.assertEqual(payload["evidence"][0]["article_ids"], ["B"])
        self.assertEqual(payload["source_reads"][0]["article_ids"], ["B"])
        self.assertEqual(payload["questions"][0]["article_ids"], ["B"])
        self.assertEqual(payload["evidence"][1], current)
        self.assertEqual(payload["capture_inbox"], [])
        self.assertEqual(payload["governance"], original["governance"])
        payload["articles"][0] = request
        after = deepcopy(payload)
        self.assertFalse(retire_previous_run(payload, request))
        self.assertEqual(payload, after)

    def test_replay_repairs_already_switched_member_with_legacy_batch_run_evidence(self):
        payload, request = self.payload()
        payload["articles"][0] = request
        for key in ("evidence", "capture_inbox", "source_reads"):
            payload[key][0]["retrieval_run_id"] = "BATCH"
        self.assertTrue(retire_previous_run(payload, request))
        self.assertEqual(payload["run_history"][0]["retired_run_ids"], ["BATCH"])
        self.assertEqual(payload["evidence"][0]["article_ids"], ["B"])
        self.assertEqual(payload["source_reads"][0]["article_ids"], ["B"])
        self.assertFalse(retire_previous_run(payload, request))

    def test_ambiguous_ownerless_read_rejects_without_partial_mutation(self):
        payload, request = self.payload()
        payload["source_reads"][0]["source_sha256"] = "unmatched"
        before = deepcopy(payload)
        with self.assertRaisesRegex(ValueError, "无法唯一归属"):
            retire_previous_run(payload, request)
        self.assertEqual(payload, before)

    def test_explicit_knowledge_reuse_preserves_evidence(self):
        payload, request = self.payload()
        request["revision_mode"] = "knowledge_reuse_rewrite"
        before = deepcopy(payload)
        self.assertFalse(retire_previous_run(payload, request))
        self.assertEqual(payload, before)


class IdentityGuardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "P-TEST_知识库"
        self.task = self.root / "04_文章任务/10_进行中/A_Test"
        self.task.mkdir(parents=True)
        (self.task / "10_文章知识需求.md").write_text(
            "- 文章ID：A\n- 当前版本：v3\n- 任务模式：outline_refresh\n- 批次ID：BATCH\n"
            "- 大纲ID：OUT-1\n- 大纲版本：v1\n\n## 大纲\n- Packaging\n\n## 随文章提交文件分类\n", encoding="utf-8")
        self.run = {"article_id": "A", "article_version": "v3", "refresh_run_id": "new-run", "workflow_entry": "run_outline_refresh.py",
                    "batch_id": "BATCH", "outline_id": "OUT-1", "outline_version": "v1", "revision_mode": "outline_refresh"}
        self.sidecar = self.task / "知识重整运行.json"
        self.sidecar.write_text(json.dumps(self.run), encoding="utf-8")
        self.member = bridge.batch_article_from_task(self.root, "A")
        self.ledger = bridge.register_batch_request(self.root, "BATCH", self.member)

    def test_downgrade_or_wrong_binding_registration_leaves_ledger_unchanged(self):
        before = self.ledger.read_bytes()
        for fields in ({"article_version": "v2"}, {"revision_mode": "new_article"}, {"batch_id": "OTHER"},
                       {"outline_id": "OTHER"}, {"outline_version": "v2"}, {"refresh_run_id": "old-run"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                bridge.register_batch_request(self.root, "BATCH", {**self.member, **fields})
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_all_entrypoints_reject_stale_evidence_without_rewriting_checkpoints(self):
        payload = json.loads(self.ledger.read_text(encoding="utf-8"))
        payload["evidence"] = [{"article_ids": ["A"], "candidate_id": "CF-001", "retrieval_run_id": "BATCH"}]
        self.ledger.write_text(json.dumps(payload), encoding="utf-8")
        before = self.ledger.read_bytes()
        run_before = self.sidecar.read_bytes()
        self.assertTrue(captures.sync(self.root, "BATCH", self.ledger)["errors"])
        with self.assertRaises(SystemExit):
            batch.build(argparse.Namespace(ledger=self.ledger, batch_id="BATCH"))
        result = workflow.run_workflow(self.root, "BATCH")
        self.assertEqual(result["workflow_state"], "identity_error")
        self.assertFalse(result["terminal"])
        self.assertEqual(check_task(self.task)["state"], "identity_error")
        self.assertFalse(comparison_permitted(self.task))
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.sidecar.read_bytes(), run_before)
        # Replay fixes the actual broken state even if articles already says v3.
        bridge.register_batch_request(self.root, "BATCH", self.member)
        repaired = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(repaired["evidence"], [])
        self.assertEqual(repaired["run_history"][0]["evidence"], payload["evidence"])
        self.assertEqual(batch.current_binding_errors(self.ledger, repaired), [])

    def test_sidecar_wrong_batch_or_outline_cannot_pass_current_run(self):
        for key in ("batch_id", "outline_id", "outline_version", "revision_mode"):
            with self.subTest(key=key):
                self.sidecar.write_text(json.dumps({**self.run, key: "WRONG"}), encoding="utf-8")
                self.assertTrue(batch.current_binding_errors(self.ledger, {"batch_id": "BATCH", "articles": [self.member]}))

    def test_stale_inbox_or_read_cannot_participate_in_current_gate(self):
        for key in ("capture_inbox", "source_reads"):
            payload = {"batch_id": "BATCH", "articles": [self.member], key: [
                {"article_id": "A", "retrieval_run_id": "old-run", "candidate_id": "CF-001"}]}
            with self.subTest(key=key):
                self.assertTrue(batch.current_binding_errors(self.ledger, payload))

    def test_existing_comparison_permission_expires_on_batch_identity_drift(self):
        from run_outline_refresh import PACKAGE_FILES, package_fingerprints
        for name in PACKAGE_FILES:
            (self.task / name).write_text("current package", encoding="utf-8")
        run = {**self.run, "current_package_validation": {
            "comparison_permitted": True, "package_sha256": package_fingerprints(self.task),
            "request_sha256": hashlib.sha256((self.task / "10_文章知识需求.md").read_bytes()).hexdigest()}}
        self.sidecar.write_text(json.dumps(run), encoding="utf-8")
        self.assertTrue(comparison_permitted(self.task))
        payload = json.loads(self.ledger.read_text(encoding="utf-8"))
        payload["articles"][0]["article_version"] = "v2"
        self.ledger.write_text(json.dumps(payload), encoding="utf-8")
        self.assertFalse(comparison_permitted(self.task))
        self.assertEqual(json.loads(self.sidecar.read_text(encoding="utf-8")), run)

    def test_explicit_reuse_checks_identity_without_requiring_new_retrieval(self):
        req = self.task / "10_文章知识需求.md"
        req.write_text(req.read_text(encoding="utf-8").replace("outline_refresh", "knowledge_reuse_rewrite"), encoding="utf-8")
        reuse = {**self.member, "revision_mode": "knowledge_reuse_rewrite"}
        payload = {"batch_id": "BATCH", "articles": [reuse], "evidence": [
            {"article_ids": ["A"], "retrieval_run_id": "previous-verified-run"}]}
        self.assertEqual(batch.current_binding_errors(self.ledger, payload), [])
        payload["articles"][0] = {**reuse, "article_version": "v2"}
        self.assertTrue(batch.current_binding_errors(self.ledger, payload))

    def test_archive_records_actual_skill_and_preserves_snapshot_bytes(self):
        req = self.task / "10_文章知识需求.md"
        before = req.read_bytes()
        archive = create_archive(project=self.root, target=self.task, kind="article", reason="isolated regression", replacement_version="v4")
        note = (archive / "00_版本说明.md").read_text(encoding="utf-8")
        skill = Path(bridge.__file__).resolve().parents[1] / "SKILL.md"
        self.assertIn("- 执行Skill：manage-article-knowledge v0.6.1", note)
        self.assertIn(hashlib.sha256(skill.read_bytes()).hexdigest(), note)
        self.assertIn(hashlib.sha256(before).hexdigest(), note)
        self.assertIn(str(skill), note)
        self.assertEqual((archive / req.name).read_bytes(), before)
        self.assertEqual(req.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
