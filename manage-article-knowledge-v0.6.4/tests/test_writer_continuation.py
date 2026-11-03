"""Loop fixes from a real Codex run: lock the writer after submission, keep the
current agent as executor, and register reusable Claims without refetching."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from record_claim_reuse import readiness, record  # noqa: E402
from batch_knowledge_run import ledger_errors  # noqa: E402

REAL_PROJECT = Path(r"D:\Obsidian\企业知识库\P-005_杰睿包装知识库_v0.6")
REAL_BATCH = "P-005-20261022-02-ARTICLES"
EXCERPT = "This custom paper box can be tailored in size, paper material and insert layout."


def claim_file(claim_id: str, *, ec1: bool = True, status: str = "可用", knowledge_status: str = "有效",
               review: str = "否") -> str:
    from evidence_identity import evidence_digest
    block_tail = f"\n### 最小原文证据\n\n> {EXCERPT}\n"
    identity = ""
    if ec1:
        digest = evidence_digest(block_tail)
        identity = (
            "- 证据模板版本：EC-1\n- 证据归属主体：JERL Packaging\n- 证据归属对象：the custom paper box\n"
            "- 指代解析：This box refers to this paper box.\n- 归属核验依据：product page title and body\n"
            "- 归属核验日期：2026-10-13\n- 归属核验状态：已核验\n"
            f"- 归属证据SHA-256：{digest}\n"
        )
    return (
        f"# 纸盒\n\n- 知识状态：{knowledge_status}\n- 最近核验日期：2026-10-13\n- 使用前复核：{review}\n\n"
        f"## 已核验Claim\n\n### {claim_id}｜定制范围\n\n- Claim ID：{claim_id}\n- Claim：可定制尺寸。\n"
        "- 适用范围：该纸盒\n- 来源类型：客户官网\n- 来源链接：https://example.com/box/\n"
        "- 精确位置：B014\n- 使用边界：只限此产品\n" + identity + f"- 状态：{status}\n" + block_tail
    )


class ClaimReuseTests(unittest.TestCase):
    def project(self, root: Path, **claim_options) -> Path:
        project = root / "P-T_测试知识库_v0.6"
        task = project / "04_文章任务/10_进行中/A-1_Test"
        task.mkdir(parents=True)
        (task / "10_文章知识需求.md").write_text(
            "# 文章知识需求\n\n- 文章ID：A-1\n- 证据模板版本：EC-1\n- 目标语言：English\n", encoding="utf-8")
        formal = project / "03_正式知识/10_客户知识/20_产品介绍"
        formal.mkdir(parents=True)
        (formal / "box.md").write_text(claim_file("CLM-T-001", **claim_options), encoding="utf-8")
        ledger = project / "04_文章任务/批次运行/B-1.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({
            "schema": "MAK-BATCH-1.0", "batch_id": "B-1",
            "articles": [{"article_id": "A-1", "batch_id": "B-1"}],
            "questions": [{"question_id": "Q-1", "article_ids": ["A-1"]}],
            "evidence": [], "governance": [],
        }, ensure_ascii=False), encoding="utf-8")
        return project

    def test_valid_claim_is_registered_from_its_own_record(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp))
            rows, held = record(project, "B-1", "A-1", ["CLM-T-001"], "该Claim直接回答定制范围问题，未触发复核")
            self.assertEqual(held, [])
            row = rows[0]
            self.assertEqual((row["candidate_id"], row["disposition"], row["exact_location"]),
                             ("CF-001", "复用已有Formal Claim", "B014"))
            self.assertEqual(row["original_excerpt"], EXCERPT)
            self.assertNotIn("retrieved_at", row)  # reuse never pretends to be a fresh read
            from batch_knowledge_run import validate_claim_provenance, validate_evidence
            ledger = project / "04_文章任务/批次运行/B-1.json"
            self.assertEqual(validate_evidence(row), [])
            self.assertIsNone(validate_claim_provenance(ledger, row))
            # A second run adds no duplicate row.
            record(project, "B-1", "A-1", ["CLM-T-001"], "该Claim直接回答定制范围问题，未触发复核")
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["evidence"]), 1)

    def test_old_claims_are_classified_not_registered(self):
        cases = {
            "补齐登记": dict(ec1=False),
            "回源核验": dict(review="是"),
        }
        for expected, options in cases.items():
            with self.subTest(expected), tempfile.TemporaryDirectory() as temp:
                project = self.project(Path(temp), **options)
                rows, held = record(project, "B-1", "A-1", ["CLM-T-001"], "该Claim直接回答定制范围问题，未触发复核")
                self.assertEqual(rows, [])
                self.assertEqual(held[0]["status"], expected)
                payload = json.loads((project / "04_文章任务/批次运行/B-1.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["evidence"], [])

    def test_status_note_and_unusable_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp), knowledge_status="有效；部分解决GAP-1")
            state = readiness(project, "CLM-T-001", require_ec1=True, target_language="English")
            self.assertEqual(state["status"], "补齐登记")
            self.assertTrue(any("只写“有效”" in p for p in state["problems"]))
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp), status="暂停使用")
            self.assertEqual(readiness(project, "CLM-T-001", require_ec1=True, target_language="English")["status"],
                             "回源核验")

    COMPLETION = {"证据归属主体": "JERL Packaging", "证据归属对象": "the custom paper box",
                  "指代解析": "This box refers to this paper box.", "归属核验依据": "已存产品页正文回读"}

    def test_needed_old_claim_is_completed_and_registered(self):
        # An article that needs an old Claim gets it completed, not dropped as unusable.
        from evidence_identity import evidence_digest, field
        from record_claim_reuse import complete_claims
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp), ec1=False)
            path = project / "03_正式知识/10_客户知识/20_产品介绍/box.md"
            changed = complete_claims(project, {"CLM-T-001": self.COMPLETION}, article_id="A-1",
                                      require_ec1=True, target_language="English")
            self.assertEqual(changed, [path])
            text = path.read_text(encoding="utf-8")
            self.assertEqual(field(text, "归属证据SHA-256"), evidence_digest(text))  # computed, not typed
            self.assertEqual(field(text, "归属核验状态"), "已核验")
            self.assertEqual(readiness(project, "CLM-T-001", require_ec1=True, target_language="English")["status"],
                             "可直接复用")
            archives = project / "05_数据与审核/60_版本归档/10_正式知识历史"
            self.assertEqual(len(list(archives.rglob("box.md"))), 1)
            rows, held = record(project, "B-1", "A-1", ["CLM-T-001"], "该Claim直接回答定制范围问题，未触发复核")
            self.assertEqual((len(rows), held), (1, []))
            # A rerun after a failed registration changes nothing and archives nothing again.
            self.assertEqual(complete_claims(project, {"CLM-T-001": self.COMPLETION}, article_id="A-1",
                                             require_ec1=True, target_language="English"), [])
            self.assertEqual(len(list(archives.rglob("box.md"))), 1)

    def test_completion_refuses_unverified_attribution(self):
        from record_claim_reuse import complete_claims
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp), ec1=False)
            path = project / "03_正式知识/10_客户知识/20_产品介绍/box.md"
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "证据归属主体"):
                complete_claims(project, {"CLM-T-001": dict(self.COMPLETION, 证据归属主体="待确认")},
                                article_id="A-1", require_ec1=True, target_language="English")
            with self.assertRaisesRegex(ValueError, "脚本计算"):
                complete_claims(project, {"CLM-T-001": dict(self.COMPLETION, **{"归属证据SHA-256": "x"})},
                                article_id="A-1", require_ec1=True, target_language="English")
            self.assertEqual(path.read_bytes(), before)

    def test_draft_suggests_from_the_saved_record(self):
        from record_claim_reuse import completion_draft
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp), ec1=False)
            formal = project / "03_正式知识/10_客户知识/20_产品介绍"
            (formal / "other.md").write_text(claim_file("CLM-T-002"), encoding="utf-8")  # a verified sibling
            draft = completion_draft(project, "CLM-T-001", require_ec1=True, target_language="English")
            self.assertEqual(draft["excerpt"], EXCERPT)
            self.assertEqual(draft["fields"]["证据归属主体"], "JERL Packaging")
            self.assertEqual(draft["fields"]["证据归属对象"], "定制范围")
            self.assertEqual(draft["fields"]["指代解析"], "")  # "This …" must be resolved by the agent

    def test_reverify_names_the_source_step(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp), review="是")
            action = readiness(project, "CLM-T-001", require_ec1=True, target_language="English")["action"]
            self.assertIn("不得以不可用跳过", action)
            self.assertIn("capture_website_evidence.py重新抓取https://example.com/box/", action)
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp), status="暂停使用")
            action = readiness(project, "CLM-T-001", require_ec1=True, target_language="English")["action"]
            self.assertIn("暂停或限制说明", action)

    def test_multi_line_excerpt_matches_its_quote_lines(self):
        from batch_knowledge_run import contains_excerpt
        block = "### 最小原文证据\n\n> Velvet Jewelry Box 02-15\n> PU Jewelry Box 16-27\n"
        self.assertTrue(contains_excerpt(block, "Velvet Jewelry Box 02-15\nPU Jewelry Box 16-27"))
        self.assertFalse(contains_excerpt(block, "Velvet Jewelry Box 02-16"))

    def test_basis_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(Path(temp))
            with self.assertRaises(ValueError):
                record(project, "B-1", "A-1", ["CLM-T-001"], "")


class ReceiptRuleTests(unittest.TestCase):
    def test_non_terminal_receipt_carries_executor_and_lock_rules(self):
        from run_knowledge_workflow import persist_receipt
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "r.json"
            persist_receipt(path, {"workflow_state": "source_collection"})
            receipt = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(receipt["terminal"])
            self.assertEqual(receipt["next_owner"], "manage-article-knowledge")
            for key in ("executor_rule", "resume_rule", "writer_lock"):
                self.assertTrue(receipt[key])
            persist_receipt(path, {"workflow_state": "needs_human"})
            receipt = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("writer_lock", receipt)

    def test_prepare_prints_the_rules(self):
        source = (SCRIPTS / "writing_bridge.py").read_text(encoding="utf-8")
        for key in ("writer_lock=", "executor_rule=", "resume_rule=", "next_owner=manage-article-knowledge"):
            self.assertIn(key, source)


def real_batch_is_current() -> bool:
    """The live project still has this batch's articles under it (they move on to later batches)."""
    if not (REAL_PROJECT / "04_文章任务/批次运行" / f"{REAL_BATCH}.json").is_file():
        return False
    requests = [path for path in (REAL_PROJECT / "04_文章任务").glob("*/P-005-ART-20261022-00*/10_文章知识需求.md")]
    return bool(requests) and all(f"- 批次ID：{REAL_BATCH}" in path.read_text(encoding="utf-8-sig") for path in requests)


@unittest.skipUnless(real_batch_is_current(), "需要本机P-005真实批次，且其文章仍属于该批次")
class RealBatchTests(unittest.TestCase):
    """The batch that looped: reuse moves it past source collection without refetching."""

    def test_reuse_moves_real_batch_to_article_records(self):
        from run_knowledge_workflow import run_workflow
        from workflow_progress import status
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / REAL_PROJECT.name
            shutil.copytree(REAL_PROJECT, project)
            claims = {"P-005-ART-20261022-001": ["CLM-P005-JEWELRYDRAWER-001"],
                      "P-005-ART-20261022-002": ["CLM-P-005-COSMETICPAPER-001", "CLM-P-005-COSMETICPAPER-002"]}
            for article, ids in claims.items():
                rows, held = record(project, REAL_BATCH, article, ids, "已核验Claim直接回答本篇产品问题，未触发复核")
                self.assertEqual(held, [], article)
            receipt = run_workflow(project, REAL_BATCH)
            states = {step["article_id"]: step["state"] for step in receipt["pending_steps"]}
            self.assertTrue(all(state != "source_collection" for state in states.values()), states)
            missing = [e for step in receipt["pending_steps"] for e in step.get("errors", [])]
            self.assertFalse(any("15_检索与知识准备记录.md" in e for e in missing), missing)
            self.assertIn("executor_rule", receipt)
            from workflow_progress import bind
            bind(project, REAL_BATCH, scope="article")  # the saved pointer names the real project path
            progress = status(project, REAL_BATCH)
            self.assertIn("resume_rule", progress)
            self.assertIn("writer_lock", progress)


if __name__ == "__main__":
    unittest.main()
