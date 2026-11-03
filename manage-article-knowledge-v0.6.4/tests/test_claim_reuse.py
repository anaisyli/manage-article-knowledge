from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch_knowledge_run as batch
from template_contract import WEBSITE_EVIDENCE_HEADER, website_manifest_errors, website_retrieval_errors


class FormalClaimReuseTests(unittest.TestCase):
    claim_id = "CLM-DEMO-001"
    source = "https://example.test/about"
    excerpt = "The company manufactures custom packaging for food brands."

    def row(self) -> dict[str, object]:
        return {
            "batch_id": "BATCH-DEMO",
            "article_ids": ["ARTICLE-DEMO"],
            "question_ids": ["Q-DEMO"],
            "candidate_id": "CF-001",
            "claim_id": self.claim_id,
            "source_id": self.claim_id,
            "source_type": "客户官网",
            "source_path_or_url": self.source,
            "exact_location": "About Us，第2段",
            "original_excerpt": self.excerpt,
            "verified_target_excerpt": self.excerpt,
            "scope": "食品包装客户的定制服务范围",
            "disposition": "复用已有Formal Claim",
            "evidence_origin": "Formal Claim",
            "claim_verified_at": "2026-10-20",
            "reuse_basis": "Claim状态有效，范围覆盖本篇，未触发使用前复核条件。",
        }

    def write_claim(self, root: Path, *, state: str = "有效", review: str = "否") -> Path:
        claim_path = root / "03_正式知识" / "company.md"
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim_path.write_text(
            f"# Company\n\n- 知识状态：{state}\n- 最近核验日期：2026-10-20\n- 使用前复核：{review}\n\n"
            f"### {self.claim_id}｜Custom packaging\n\n"
            f"- Claim ID：{self.claim_id}\n- 来源链接：{self.source}\n"
            "- 精确位置：About Us，第2段\n- 适用范围：食品包装客户的定制服务范围\n"
            "- 状态：可用\n\n### 最小原文证据\n\n"
            f"> {self.excerpt}\n",
            encoding="utf-8",
        )
        return claim_path

    def test_reuse_record_needs_no_current_source_read(self):
        row = self.row()
        self.assertEqual(batch.validate_evidence(row), [])
        self.assertIsNone(row.get("retrieved_at"))
        self.assertIsNone(row.get("retrieval_run_id"))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            self.write_claim(root)
            ledger = root / "04_文章任务" / "批次运行" / "batch.json"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("{}", encoding="utf-8")
            self.assertIsNone(batch.validate_claim_provenance(ledger, row))

    def test_conditional_review_with_its_triggers_is_reusable(self):
        # The template requires "条件" to name its triggers; check and ledger write must agree.
        from record_claim_reuse import classify

        for review, ok in (("条件；来源更正、标准更新或使用超范围时", True), ("条件", True), ("否", True),
                           ("是；每次使用前回源", False), ("待定", False)):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "project"
                claim_path = self.write_claim(root, review=review)
                ledger = root / "04_文章任务" / "批次运行" / "batch.json"
                ledger.parent.mkdir(parents=True)
                ledger.write_text("{}", encoding="utf-8")
                refused = batch.validate_claim_provenance(ledger, self.row())
                verdict = classify(claim_path.read_text(encoding="utf-8"), self.claim_id,
                                   require_ec1=False, target_language="English")
            review_problems = [p for p in verdict["problems"] if "使用前" in p]
            with self.subTest(review=review):
                self.assertEqual(refused is None, ok, refused)
                self.assertEqual(not review_problems, ok, review_problems)
                if review.startswith("是"):
                    self.assertEqual(verdict["status"], "回源核验")

    def test_batch_build_does_not_add_reused_claim_to_current_source_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            self.write_claim(root)
            ledger = root / "04_文章任务" / "批次运行" / "batch.json"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(json.dumps({
                "schema": "MAK-BATCH-1.0",
                "batch_id": "BATCH-DEMO",
                "articles": [{"article_id": "ARTICLE-DEMO"}],
                "questions": [{"question_id": "Q-DEMO"}],
                "evidence": [self.row()],
                "source_reads": [],
                "governance": [],
            }), encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(batch.build(argparse.Namespace(ledger=ledger, batch_id="BATCH-DEMO")), 0)

            result = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "evidence_ready")
            self.assertEqual(result["source_reads"], [])
            self.assertEqual(result["evidence"][0]["disposition"], "复用已有Formal Claim")

    def test_reuse_rejects_claim_marked_for_recheck_or_inactive(self):
        row = self.row()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            self.write_claim(root, review="是")
            ledger = root / "04_文章任务" / "批次运行" / "batch.json"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("{}", encoding="utf-8")
            self.assertIn("使用前必须回源复核", batch.validate_claim_provenance(ledger, row) or "")

            self.write_claim(root, state="已失效", review="否")
            self.assertIn("状态不是有效", batch.validate_claim_provenance(ledger, row) or "")

    def test_reuse_requires_matching_saved_location_and_verification_date(self):
        row = self.row()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            claim_path = self.write_claim(root)
            ledger = root / "04_文章任务" / "批次运行" / "batch.json"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("{}", encoding="utf-8")

            row["exact_location"] = "About Us，第3段"
            self.assertIn("精确位置与Formal Claim不一致", batch.validate_claim_provenance(ledger, row) or "")

            row = self.row()
            claim_path.write_text(
                claim_path.read_text(encoding="utf-8").replace("- 最近核验日期：2026-10-20", "- 最近核验日期："),
                encoding="utf-8",
            )
            self.assertIn("缺少最近核验日期", batch.validate_claim_provenance(ledger, row) or "")

    def test_existing_claim_website_row_does_not_need_current_fetch_manifest(self):
        header = "| " + " | ".join(WEBSITE_EVIDENCE_HEADER) + " |"
        separator = "|---|---|---|---|---|---|---|"
        text = (
            "- 知识准备模式：new_article\n"
            "- 本轮知识检索运行ID：RUN-DEMO\n"
            "- 官网正文抓取凭证：无（本轮复用既有Formal Claim，无需网页抓取）\n\n"
            "## 固定检索层状态\n\n| 检索层 | 当前状态 | 结果或未查原因 | 下一步 |\n"
            "|---|---|---|---|\n"
            "| 客户官网 | 不适用（有效Formal Claim覆盖） | CLM-DEMO-001 | 无需回源 |\n\n"
            "## 官网正文核验\n\n" + header + "\n" + separator + "\n"
            f"| 标题 | {self.claim_id} | 2026-10-20 | {self.source}；About Us，第2段 | {self.excerpt} | CF-001 | 复用有效Formal Claim（未回源）：{self.claim_id} |\n\n"
            "## 来源命中记录\n\n| 知识问题 | 命中Claim/资料名称与入口 | 相关理由 | 处理结果 |\n"
            "|---|---|---|---|\n| 标题 | CLM-DEMO-001 | 直接回答 | 复用 |\n\n"
            "## 候选事实处置明细\n\n| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n"
            "|---|---|---|---|---|\n"
            f"| CF-001 | 定制包装服务 | {self.source}；About Us，第2段 | 复用已有Formal Claim | {self.claim_id} |\n\n"
            "## 大纲逐项检索与候选事实覆盖\n\n| 大纲章节 | 六层检索范围与结果 | 命中来源与精确入口 | 候选事实ID | 候选事实数 | 已沉淀Claim数 | 未采用事实/缺口及原因 | 下一步 |\n"
            "|---|---|---|---|---:|---:|---|---|\n"
            f"| 标题 | 已有Claim完整覆盖；官网层未触发 | CF-001 | CF-001 | 1 | 1 | 无 | 纳入30 |\n"
        )
        self.assertEqual(website_retrieval_errors(text), [])
        with tempfile.TemporaryDirectory() as temp:
            task_dir = Path(temp) / "project" / "04_文章任务" / "10_进行中" / "article"
            task_dir.mkdir(parents=True)
            self.assertEqual(website_manifest_errors(task_dir, text), [])


if __name__ == "__main__":
    unittest.main()
