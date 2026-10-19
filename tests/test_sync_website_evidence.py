from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "manage-article-knowledge-v0.6.1" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import batch_knowledge_run  # noqa: E402
from run_knowledge_workflow import conventional_ledger  # noqa: E402
from sync_website_evidence import sync  # noqa: E402


class WebsiteEvidenceSyncTests(unittest.TestCase):
    url = "https://example.test/product"
    excerpt = "This paper box can be customized in size and color."

    def fixture(self, root: Path, *, matching_claim: bool = True) -> tuple[Path, Path]:
        project = root / "P-TEST_知识库_v0.6"
        task = project / "04_文章任务/10_进行中/ART-001_Test"
        task.mkdir(parents=True)
        (task / "10_文章知识需求.md").write_text(
            "- 文章ID：ART-001\n- 目标语言：English\n", encoding="utf-8"
        )
        claim_root = project / "03_正式知识/10_客户知识"
        claim_root.mkdir(parents=True)
        if matching_claim:
            (claim_root / "claim.md").write_text(
                "### CLM-001｜产品定制\n"
                "- Claim ID：CLM-001\n"
                f"- 来源链接：{self.url}\n"
                "- 适用范围：本测试纸盒\n- 状态：可用\n\n"
                f"> {self.excerpt}\n",
                encoding="utf-8",
            )
        ledger = conventional_ledger(project, "B-001")
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({
            "schema": "MAK-BATCH-1.0", "batch_id": "B-001", "status": "collecting_requests",
            "articles": [{"article_id": "ART-001", "target_language": "English"}],
            "questions": [{"question_id": "Q-001", "article_ids": ["ART-001"]}],
            "evidence": [], "capture_inbox": [], "governance": [],
        }, ensure_ascii=False), encoding="utf-8")
        credential = [{
            "requested_url": self.url, "final_url": self.url, "title": "Test product",
            "fetched_at": "2026-10-12T10:00:00+08:00", "response_sha256": "resp-sha",
            "refresh_run_id": "B-001", "excerpt": self.excerpt, "excerpt_sha256": "excerpt-sha",
            "website_id": "WEB-1", "source_type": "客户官网", "position": "Product paragraph",
            "heading_path": ["Product"], "block_id": "B014",
        }]
        (task / "官网正文抓取凭证.json").write_text(
            json.dumps(credential, ensure_ascii=False), encoding="utf-8"
        )
        return project, ledger

    def test_exact_current_claim_is_promoted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, ledger = self.fixture(Path(temp))
            first = sync(project, "B-001", ledger)
            second = sync(project, "B-001", ledger)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(first["promoted"], 1)
            self.assertEqual(second["promoted"], 0)
            self.assertEqual(second["unchanged"], 1)
            self.assertEqual(len(payload["evidence"]), 1)
            self.assertEqual(payload["evidence"][0]["claim_id"], "CLM-001")
            self.assertEqual(payload["capture_inbox"], [])

    def test_unmatched_capture_stays_in_inbox_and_blocks_evidence_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, ledger = self.fixture(Path(temp), matching_claim=False)
            result = sync(project, "B-001", ledger)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(result["pending"], 1)
            self.assertEqual(len(payload["evidence"]), 0)
            with self.assertRaisesRegex(SystemExit, "Claim闭环"):
                batch_knowledge_run.build(argparse.Namespace(ledger=ledger, batch_id="B-001"))
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "collecting_requests")

    def test_other_refresh_run_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, ledger = self.fixture(Path(temp))
            task = project / "04_文章任务/10_进行中/ART-001_Test"
            credential_path = task / "官网正文抓取凭证.json"
            credentials = json.loads(credential_path.read_text(encoding="utf-8"))
            credentials[0]["refresh_run_id"] = "OLD-BATCH"
            credential_path.write_text(json.dumps(credentials, ensure_ascii=False), encoding="utf-8")
            result = sync(project, "B-001", ledger)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(result["discovered"], 0)
            self.assertEqual(payload["evidence"], [])
            self.assertEqual(payload["capture_inbox"], [])

    def bind_run(self, project: Path, ledger: Path, mode: str) -> Path:
        task = project / "04_文章任务/10_进行中/ART-001_Test"
        version = "v2" if mode == "outline_refresh" else "v1"
        key = "refresh_run_id" if mode == "outline_refresh" else "research_run_id"
        filename = "知识重整运行.json" if mode == "outline_refresh" else "知识检索运行.json"
        (task / "10_文章知识需求.md").write_text(
            f"- 文章ID：ART-001\n- 目标语言：English\n- 当前版本：{version}\n- 任务模式：{mode}\n", encoding="utf-8")
        (task / filename).write_text(json.dumps({key: "ARTICLE-RUN", "article_id": "ART-001", "article_version": version}), encoding="utf-8")
        data = json.loads(ledger.read_text(encoding="utf-8"))
        data["articles"][0].update(article_version=version, revision_mode=mode, **{key: "ARTICLE-RUN"})
        ledger.write_text(json.dumps(data), encoding="utf-8")
        manifest = task / "官网正文抓取凭证.json"
        captures = json.loads(manifest.read_text(encoding="utf-8"))
        captures[0]["refresh_run_id"] = "ARTICLE-RUN"
        manifest.write_text(json.dumps(captures), encoding="utf-8")
        return manifest

    def test_article_run_ids_work_for_new_and_refresh_and_old_run_is_reported(self):
        for mode in ("new_article", "outline_refresh"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                project, ledger = self.fixture(Path(temp))
                manifest = self.bind_run(project, ledger, mode)
                records = json.loads(manifest.read_text(encoding="utf-8"))
                records.append({**records[0], "refresh_run_id": "OLD-RUN"})
                manifest.write_text(json.dumps(records), encoding="utf-8")
                result = sync(project, "B-001", ledger)
                self.assertEqual(result["promoted"], 1)
                self.assertEqual(result["skipped"], 1)
                self.assertIn("OLD-RUN", str(result["skipped_records"]))
                payload = json.loads(ledger.read_text(encoding="utf-8"))
                self.assertEqual(payload["evidence"][0]["retrieval_run_id"], "ARTICLE-RUN")
                self.assertEqual(payload["evidence"][0]["candidate_id"], "CF-001")

    def test_stale_version_cannot_promote_current_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            project, ledger = self.fixture(Path(temp))
            self.bind_run(project, ledger, "outline_refresh")
            data = json.loads(ledger.read_text(encoding="utf-8"))
            data["articles"][0]["article_version"] = "v1"
            ledger.write_text(json.dumps(data), encoding="utf-8")
            result = sync(project, "B-001", ledger)
            self.assertTrue(result["errors"])
            self.assertEqual(result["promoted"], 0)

    def test_changed_response_hash_does_not_silently_reuse_old_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            project, ledger = self.fixture(Path(temp))
            sync(project, "B-001", ledger)
            manifest = project / "04_文章任务/10_进行中/ART-001_Test/官网正文抓取凭证.json"
            records = json.loads(manifest.read_text(encoding="utf-8"))
            records[0]["response_sha256"] = "changed-response"
            manifest.write_text(json.dumps(records), encoding="utf-8")
            result = sync(project, "B-001", ledger)
            self.assertTrue(result["errors"])
            self.assertEqual(result["promoted"], 0)
            self.assertTrue(batch_knowledge_run.ledger_errors(ledger, "B-001"))

    def test_pending_reads_survive_failed_build_and_exclusion_needs_real_disposition(self):
        with tempfile.TemporaryDirectory() as temp:
            project, ledger = self.fixture(Path(temp), matching_claim=False)
            sync(project, "B-001", ledger)
            with self.assertRaises(SystemExit):
                batch_knowledge_run.build(argparse.Namespace(ledger=ledger, batch_id="B-001"))
            data = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(data["source_reads"]), 1)
            self.assertEqual(data["source_reads"][0]["original_excerpt"], self.excerpt)
            sync(project, "B-001", ledger)
            self.assertEqual(len(json.loads(ledger.read_text(encoding="utf-8"))["source_reads"]), 1)
            data["capture_inbox"][0]["status"] = "排除"
            self.assertTrue(batch_knowledge_run.pending_captures(data), "a label alone cannot close a candidate")
            row = data["capture_inbox"][0]
            data["evidence"] = [{**row, "batch_id": "B-001", "article_ids": ["ART-001"],
                                "source_id": "WEB-1", "source_type": "客户官网", "scope": "本篇",
                                "disposition": "排除", "disposition_basis": "原文不支持当前大纲的定量要求"}]
            ledger.write_text(json.dumps(data), encoding="utf-8")
            batch_knowledge_run.build(argparse.Namespace(ledger=ledger, batch_id="B-001"))
            self.assertEqual(batch_knowledge_run.ledger_errors(ledger, "B-001"), [])

    def test_pending_article_does_not_block_an_independent_article(self):
        with tempfile.TemporaryDirectory() as temp:
            project, ledger = self.fixture(Path(temp))
            sync(project, "B-001", ledger)
            data = json.loads(ledger.read_text(encoding="utf-8"))
            data["articles"].append({"article_id": "ART-002"})
            data["capture_inbox"].append({"article_id": "ART-002", "candidate_id": "CF-001", "status": "待候选事实核验"})
            ledger.write_text(json.dumps(data), encoding="utf-8")
            result = __import__("run_knowledge_workflow").run_batch_validation(ledger, "B-001", 5)
            self.assertEqual(result["attempts"], 1, "unchanged semantic errors must not be retried")
            self.assertTrue(result["errors"])
            self.assertEqual(batch_knowledge_run.ledger_errors(ledger, "B-001", article_id="ART-001"), [])
            self.assertTrue(batch_knowledge_run.ledger_errors(ledger, "B-001", article_id="ART-002"))


if __name__ == "__main__":
    unittest.main()
