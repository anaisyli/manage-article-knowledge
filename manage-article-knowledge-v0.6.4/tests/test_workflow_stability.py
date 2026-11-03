from __future__ import annotations

import hashlib
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from advance_ready_tasks import normalize_task_tables  # noqa: E402
from article_state import article_package_errors  # noqa: E402
from handoff_contract import current_version  # noqa: E402
from import_faithfulness import (  # noqa: E402
    load_disposition,
    protocol2_adversarial_error,
    protocol2_reconciliation_error,
    validate_disposition_links,
    write_completion_receipt,
)
from record_knowledge_gap import FIELDS as GAP_FIELDS, set_current_gap_presence  # noqa: E402
from build_coverage_view import knowledge_gaps  # noqa: E402
from template_contract import TEMPLATE_VERSION  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorkflowStabilityTests(unittest.TestCase):
    def test_current_gap_count_changes_without_rewriting_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "10_知识缺口记录.csv"
            row = dict.fromkeys(GAP_FIELDS, "")
            row.update(
                gap_key="GAP-001", gap_topic="包装样品验证需要哪些适用条件",
                gap_type="公共知识", trigger_basis="重复文章",
                article_ids="ART-001;ART-002", article_count="2",
                current_article_ids="ART-001;ART-002", current_article_count="2",
                status="待外部调研", current_impact="影响当前文章事实覆盖",
                next_action="开展定向外部调研", first_seen="2026-09-01",
                last_seen="2026-09-18", related_governance_ref="无",
            )
            with ledger.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=GAP_FIELDS)
                writer.writeheader()
                writer.writerow(row)
            self.assertTrue(set_current_gap_presence(ledger, "GAP-001", "ART-001", False))
            with ledger.open("r", encoding="utf-8-sig", newline="") as stream:
                updated = next(csv.DictReader(stream))
            self.assertEqual(updated["article_ids"], "ART-001;ART-002")
            self.assertEqual(updated["article_count"], "2")
            self.assertEqual(updated["current_article_ids"], "ART-002")
            self.assertEqual(updated["current_article_count"], "1")

    def test_resolved_gap_cannot_absorb_new_article_without_reopening(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
            ledger.parent.mkdir(parents=True)
            row = dict.fromkeys(GAP_FIELDS, "")
            row.update(gap_key="GAP-001", gap_topic="包装材料效率与废弃物影响如何共同评估",
                       gap_type="公共知识", trigger_basis="首篇普通缺口", article_ids="ART-001",
                       article_count="1", status="已解决", current_impact="已覆盖材料效率",
                       next_action="按来源日期复核", first_seen="2026-09-09", last_seen="2026-09-09",
                       related_governance_ref="RES-001")
            with ledger.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=GAP_FIELDS)
                writer.writeheader()
                writer.writerow(row)
            args = [sys.executable, str(SCRIPTS / "record_knowledge_gap.py"), "--csv", str(ledger),
                    "--gap-key", "GAP-001", "--topic", row["gap_topic"], "--article-id", "ART-002",
                    "--article-date", "2026-09-17", "--trigger-basis", "重复文章"]
            rejected = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("重开", rejected.stderr)
            with ledger.open("r", encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(next(csv.DictReader(stream))["article_count"], "1")
            reopened = subprocess.run(args + ["--set-status", "部分解决", "--reopen-reason",
                                             "原有材料效率证据未覆盖本次新增的处置条件",
                                             "--resolution-scope", "现有RES仅回答材料效率与废弃物影响，新增处置条件待补证"], capture_output=True, text=True)
            self.assertEqual(reopened.returncode, 0, reopened.stderr)
            with ledger.open("r", encoding="utf-8-sig", newline="") as stream:
                updated = next(csv.DictReader(stream))
            self.assertEqual((updated["status"], updated["article_count"]), ("部分解决", "2"))
            self.assertIn("重开依据", updated["related_governance_ref"])
            self.assertEqual(knowledge_gaps(root)[0]["status"], "部分解决")

    def test_disposition_requires_per_claim_scope_and_rejects_terminal_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
            ledger.parent.mkdir(parents=True)
            row = dict.fromkeys(GAP_FIELDS, "")
            row.update(gap_key="GAP-001", article_ids="ART-002", status="已解决")
            with ledger.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=GAP_FIELDS)
                writer.writeheader()
                writer.writerow(row)
            group = dict(group_id="UG-001", claim_ids=["C001", "C002"], topic="包装材料效率规则",
                         category="existing_gap", classification_basis="材料效率需要公共证据核验",
                         issue_key="GAP-001", status="待外部调研", article_impact="影响后续知识覆盖",
                         handling="保留本次审核结果", next_owner="Codex", entry="GAP-001",
                         close_condition="取得明确材料效率证据后再解决",
                         fact_check=dict(contains_factual_judgment=True, reusable_across_articles=True,
                                         knowledge_domains=["method"], why_not_knowledge_issue=""))
            disposition = root / "disposition.json"
            disposition.write_text(json.dumps(dict(schema_version="1.1", article_id="ART-002", groups=[group]),
                                              ensure_ascii=False), encoding="utf-8")
            claims = [dict(claim_id=key, verdict="unsupported") for key in ("C001", "C002")]
            with self.assertRaisesRegex(ValueError, "scope_review"):
                load_disposition(disposition, "ART-002", claims)
            # A too-short mapping names the claim and the minimum (P-005 2026-10-28: "如何汇集可见包装决定。", 11 chars).
            group["scope_review"] = dict(knowledge_question="包装材料效率与废弃物影响如何共同评估",
                                         claim_matches={"C001": "该主张说明材料效率的评估条件", "C002": "如何汇集可见包装决定。"})
            disposition.write_text(json.dumps(dict(schema_version="1.1", article_id="ART-002", groups=[group]),
                                              ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"UG-001 \(C002：scope_review.claim_matches 每条至少12个字符"):
                load_disposition(disposition, "ART-002", claims)
            group["scope_review"] = dict(knowledge_question="包装材料效率与废弃物影响如何共同评估",
                                         claim_matches={"C001": "该主张说明材料效率的评估条件",
                                                        "C002": "该主张说明废弃物影响的评估条件"})
            disposition.write_text(json.dumps(dict(schema_version="1.1", article_id="ART-002", groups=[group]),
                                              ensure_ascii=False), encoding="utf-8")
            loaded = load_disposition(disposition, "ART-002", claims)
            with self.assertRaisesRegex(ValueError, "terminal status|已解决"):
                validate_disposition_links(loaded, root, "ART-002")
            row["status"] = "部分解决"
            with ledger.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=GAP_FIELDS)
                writer.writeheader()
                writer.writerow(row)
            loaded[0]["status"] = "部分解决"
            validate_disposition_links(loaded, root, "ART-002")

    def test_public_gap_rejects_customer_fact_and_uses_semantic_scope_review(self) -> None:
        claims = [
            {"claim_id": "C001", "verdict": "unsupported", "claim": "JERL Packaging lists watch packaging."},
            {"claim_id": "C002", "verdict": "unsupported", "claim": "Keep the logo position stable while validating physical samples and purchasing specifications."},
        ]
        customer_group = dict(
            group_id="UG-001", claim_ids=["C001"], topic="客户产品类别", category="new_public_gap",
            classification_basis="这是可复用的公共知识", issue_key="GAP-001", status="观察中",
            article_impact="影响文章", handling="等待处理", next_owner="Codex", entry="GAP-001",
            close_condition="取得证据", fact_check=dict(contains_factual_judgment=True,
                reusable_across_articles=True, knowledge_domains=["method"], why_not_knowledge_issue=""),
            scope_review=dict(knowledge_question="客户包装产品类别如何确认", claim_matches={"C001": "说明类别"}),
        )
        path = Path(tempfile.mktemp(suffix=".json"))
        try:
            path.write_text(json.dumps({"schema_version": "1.1", "article_id": "ART-001", "groups": [customer_group]}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Customer-specific claim"):
                load_disposition(path, "ART-001", claims)
        finally:
            path.unlink(missing_ok=True)

        cross_domain = dict(customer_group)
        cross_domain["claim_ids"] = ["C002"]
        cross_domain["topic"] = "包装批准方法如何统一品牌、样品验证与采购规格"
        cross_domain["scope_review"] = dict(
            knowledge_question="包装批准方法如何统一品牌、样品验证与采购规格",
            claim_matches={"C002": "该主张完整描述同一包装批准方法所需的协调检查范围"},
        )
        cross_domain["fact_check"] = dict(contains_factual_judgment=True, reusable_across_articles=True, knowledge_domains=["method", "procurement_selection"], why_not_knowledge_issue="")
        cross_domain["classification_basis"] = "该主张属于一个可由同组方法证据回答的公共问题"
        path = Path(tempfile.mktemp(suffix=".json"))
        try:
            path.write_text(json.dumps({"schema_version": "1.1", "article_id": "ART-001", "groups": [cross_domain]}, ensure_ascii=False), encoding="utf-8")
            loaded = load_disposition(path, "ART-001", [claims[1]])
            self.assertEqual(loaded[0]["scope_review"]["knowledge_question"], cross_domain["scope_review"]["knowledge_question"])

            malformed = dict(cross_domain)
            malformed["scope_review"] = dict(
                knowledge_question=cross_domain["scope_review"]["knowledge_question"],
                claim_matches={},
            )
            path.write_text(json.dumps({"schema_version": "1.1", "article_id": "ART-001", "groups": [malformed]}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "map every claim_id"):
                load_disposition(path, "ART-001", [claims[1]])
        finally:
            path.unlink(missing_ok=True)

    def test_disposition_status_and_gap_references_must_match_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
            ledger.parent.mkdir(parents=True)
            row = dict.fromkeys(GAP_FIELDS, "")
            row.update(gap_key="GAP-001", gap_topic="包装材料效率如何评估", gap_type="公共知识",
                       trigger_basis="重复文章", article_ids="ART-001", article_count="1",
                       status="待外部调研", current_impact="待处理", next_action="开展外部调研",
                       first_seen="2026-09-18", last_seen="2026-09-18", related_governance_ref="无")
            with ledger.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=GAP_FIELDS); writer.writeheader(); writer.writerow(row)
            group = dict(group_id="UG-001", claim_ids=["C001"], topic="包装材料效率", category="existing_gap",
                         classification_basis="公共知识问题", issue_key="GAP-001", status="已解决",
                         article_impact="影响文章", handling="复用GAP-999的已解决Claim", next_owner="Codex",
                         entry="GAP-001", close_condition="取得证据", fact_check=dict(contains_factual_judgment=True,
                         reusable_across_articles=True, knowledge_domains=["method"], why_not_knowledge_issue=""),
                         scope_review=dict(knowledge_question="包装材料效率如何评估", claim_matches={"C001": "说明效率"}))
            with self.assertRaisesRegex(ValueError, "terminal status|does not match|another gap"):
                validate_disposition_links([group], root, "ART-001")

    def test_protocol2_adversarial_review_is_a_hard_import_gate(self) -> None:
        claims = [{
            "claim_id": "C-001",
            "unit_id": "U001",
            "article_line": 12,
            "article_quote": "JERL offers paper packaging.",
            "claim": "JERL offers paper packaging.",
            "semantic_status": "entailed",
        }]
        self.assertIn(
            "requires an adversarial review artifact",
            protocol2_adversarial_error(None, claims, "ART-001"),
        )
        valid = {
            "schema_version": "1.0",
            "evaluation_protocol_version": "2.0",
            "article_id": "ART-001",
            "review_mode": "independent_adversarial",
            "reconciliation": {
                "gate_version": "1.0",
                "policy": "two_pass_consensus",
                "completed": True,
                "no_human_queue": True,
            },
            "claim_reviews": [{
                "claim_id": "C-001",
                "unit_id": "U001",
                "article_line": 12,
                "article_quote": "JERL offers paper packaging.",
                "claim": "JERL offers paper packaging.",
                "claim_fragment": "paper packaging",
                "semantic_status": "entailed",
                "reconciled_semantic_status": "entailed",
                "challenge_reason": "已独立复核对象、关系、范围和条件，并核对证据片段。",
                "evidence_fragment": "明确证据片段",
            }],
        }
        self.assertIsNone(protocol2_adversarial_error(valid, claims, "ART-001"))
        invalid = dict(valid)
        invalid["claim_reviews"] = []
        self.assertIn(
            "exactly one row for every claim",
            protocol2_adversarial_error(invalid, claims, "ART-001"),
        )
        unknown_claims = [{
            "claim_id": "C-002",
            "unit_id": "U002",
            "article_line": 18,
            "article_quote": "The package may reduce handling damage.",
            "claim": "The package may reduce handling damage.",
            "semantic_status": "unknown",
        }]
        unknown = dict(valid)
        unknown["claim_reviews"] = [{
            "claim_id": "C-002",
            "unit_id": "U002",
            "article_line": 18,
            "article_quote": "The package may reduce handling damage.",
            "claim": "The package may reduce handling damage.",
            "claim_fragment": "handling damage",
            "semantic_status": "unknown",
            "reconciled_semantic_status": "unknown",
            "challenge_reason": "证据不足",
            "evidence_fragment": "",
        }]
        self.assertIsNone(
            protocol2_adversarial_error(unknown, unknown_claims, "ART-001")
        )

    def test_protocol2_adversarial_review_uses_full_proposition_identity(self) -> None:
        claims = [
            {
                "claim_id": "C001", "unit_id": "U001", "article_line": 1,
                "article_quote": "JERL offers paper packaging.",
                "claim": "JERL offers paper packaging.", "semantic_status": "entailed",
            },
            {
                "claim_id": "C002", "unit_id": "U002", "article_line": 2,
                "article_quote": "JERL tests paper packaging before shipment.",
                "claim": "JERL tests paper packaging before shipment.", "semantic_status": "entailed",
            },
        ]
        base_review = {
            "schema_version": "1.0", "evaluation_protocol_version": "2.0",
            "article_id": "ART-001", "review_mode": "independent_adversarial",
            "reconciliation": {
                "gate_version": "1.0", "policy": "two_pass_consensus",
                "completed": True, "no_human_queue": True,
            },
        }
        rows = []
        for claim in claims:
            rows.append({
                **claim,
                "claim_fragment": "paper packaging",
                "reconciled_semantic_status": "entailed",
                "challenge_reason": "已独立核对完整命题身份、适用范围以及对应证据。",
                "evidence_fragment": "JERL offers and tests paper packaging before shipment.",
            })
        valid = {**base_review, "claim_reviews": rows}
        self.assertIsNone(protocol2_adversarial_error(valid, claims, "ART-001"))

        missing_identity = json.loads(json.dumps(valid))
        missing_identity["claim_reviews"][0].pop("article_quote")
        self.assertIn(
            "lacks full proposition identity",
            protocol2_adversarial_error(missing_identity, claims, "ART-001"),
        )

        crossed = json.loads(json.dumps(valid))
        crossed["claim_reviews"][0].update({
            "unit_id": claims[1]["unit_id"],
            "article_line": claims[1]["article_line"],
            "article_quote": claims[1]["article_quote"],
            "claim": claims[1]["claim"],
        })
        self.assertIn(
            "belongs to another proposition",
            protocol2_adversarial_error(crossed, claims, "ART-001"),
        )

        unrelated_fragment = json.loads(json.dumps(valid))
        unrelated_fragment["claim_reviews"][0]["claim_fragment"] = "leather packaging"
        self.assertIn(
            "invalid explanatory claim_fragment",
            protocol2_adversarial_error(unrelated_fragment, claims, "ART-001"),
        )

        misbound_inventory = {
            **valid,
            "claim_inventory": [{
                "unit_id": claims[0]["unit_id"],
                "article_quote": claims[0]["article_quote"],
                "claim": claims[0]["claim"],
                "matched_claim_id": "C002",
            }],
        }
        self.assertIn(
            "matched_claim_id belongs to another proposition",
            protocol2_adversarial_error(misbound_inventory, claims, "ART-001"),
        )

    def test_protocol2_risk_weighted_review_imports_single_and_dual_pass_claims(self) -> None:
        high_claim = {
            "claim_id": "C001", "unit_id": "U001", "article_line": 3,
            "article_quote": "JERL offers custom paper packaging.",
            "claim": "JERL offers custom paper packaging.", "semantic_status": "entailed",
            "review_risk_level": "high",
            "review_risk_categories": ["company_or_customer_capability"],
            "reconciliation": {
                "gate_version": "1.0", "review_depth": "dual_pass",
                "first_pass_semantic_status": "entailed",
                "independent_semantic_status": "entailed",
                "final_semantic_status": "entailed", "action": "retained", "reasons": [],
            },
        }
        standard_claim = {
            "claim_id": "C002", "unit_id": "U002", "article_line": 8,
            "article_quote": "A simpler design can make packaging easier to handle.",
            "claim": "A simpler design can make packaging easier to handle.",
            "semantic_status": "unknown", "review_risk_level": "standard",
            "review_risk_categories": [],
            "reconciliation": {
                "gate_version": "1.0", "review_depth": "single_pass",
                "first_pass_semantic_status": "unknown",
                "independent_semantic_status": "not_reviewed",
                "final_semantic_status": "unknown", "action": "retained", "reasons": [],
            },
        }
        metadata = {
            "gate_version": "1.0", "coverage_gate_version": "1.1",
            "policy": "risk_weighted_v1", "completed": True, "no_human_queue": True,
            "reviewed_high_risk_claim_ids": ["C001"],
            "single_pass_standard_claim_ids": ["C002"],
            "missing_high_risk_review_ids": [],
        }
        claims = [high_claim, standard_claim]
        judgments = {
            "review_policy": "risk_weighted_v1", "claims": claims,
            "reconciliation": metadata,
        }
        adversarial = {
            "schema_version": "1.0", "evaluation_protocol_version": "2.0",
            "article_id": "ART-001", "review_mode": "independent_adversarial",
            "review_policy": "risk_weighted_v1", "reconciliation": metadata,
            "claim_reviews": [{
                "claim_id": "C001", "unit_id": "U001", "article_line": 3,
                "article_quote": high_claim["article_quote"], "claim": high_claim["claim"],
                "claim_fragment": "custom paper packaging", "semantic_status": "entailed",
                "reconciled_semantic_status": "entailed",
                "challenge_reason": "已独立核对公司能力、主张范围和证据覆盖。",
                "evidence_fragment": "明确证据片段",
            }],
        }

        self.assertIsNone(protocol2_reconciliation_error(judgments))
        self.assertIsNone(protocol2_adversarial_error(
            adversarial, claims, "ART-001", expected_review_policy="risk_weighted_v1"
        ))

        missing_high_review = json.loads(json.dumps(adversarial))
        missing_high_review["claim_reviews"] = []
        self.assertIn(
            "exactly one row for every high-risk claim",
            protocol2_adversarial_error(
                missing_high_review, claims, "ART-001", expected_review_policy="risk_weighted_v1"
            ),
        )

        missing_claim = json.loads(json.dumps(high_claim))
        missing_claim["semantic_status"] = "unknown"
        missing_claim["reconciliation"].update({
            "review_depth": "missing_second_pass_review",
            "independent_semantic_status": "unknown",
            "final_semantic_status": "unknown",
            "action": "downgraded_to_unknown",
            "reasons": ["高风险主张缺少有效的第二轮独立证据复核"],
        })
        missing_metadata = {
            **metadata,
            "reviewed_high_risk_claim_ids": [],
            "missing_high_risk_review_ids": ["C001"],
        }
        missing_judgments = {
            "review_policy": "risk_weighted_v1",
            "claims": [missing_claim, standard_claim],
            "reconciliation": missing_metadata,
        }
        missing_adversarial = {
            **adversarial,
            "reconciliation": missing_metadata,
            "claim_reviews": [{
                "claim_id": "C001", "unit_id": "U001", "article_line": 3,
                "article_quote": missing_claim["article_quote"], "claim": missing_claim["claim"],
                "claim_fragment": "custom paper packaging", "semantic_status": "unknown",
                "reconciled_semantic_status": "unknown", "review_status": "missing",
            }],
        }
        self.assertIsNone(protocol2_reconciliation_error(missing_judgments))
        self.assertIsNone(protocol2_adversarial_error(
            missing_adversarial,
            [missing_claim, standard_claim],
            "ART-001",
            expected_review_policy="risk_weighted_v1",
        ))

        missing_claim["semantic_status"] = "entailed"
        missing_claim["reconciliation"]["final_semantic_status"] = "entailed"
        self.assertIn(
            "must remain unknown",
            protocol2_reconciliation_error(missing_judgments),
        )

    def test_create_and_import_reject_nonstandard_50_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / "P-TEST/04_文章任务/20_等待终稿/ART-001_Test"
            task.mkdir(parents=True)
            article = task / "40_最终文章.md"
            knowledge = task / "30_本篇知识库资料.md"
            source_index = task / "35_写作素材来源索引.md"
            article.write_text(
                "# 最终文章\n\n- 文章ID：ART-001\n- 文章版本：v1\n"
                "- 完成日期：2026-09-16\n- 文章标题：Test\n",
                encoding="utf-8",
            )
            knowledge.write_text(
                "# 本篇写作素材包\n\n- 资料视图：写作素材包\n",
                encoding="utf-8",
            )
            source_index.write_text("# 写作素材来源索引\n", encoding="utf-8")
            wrong = root / "outside-50.md"
            common_error = "--receipt必须是当前文章任务目录中的标准50记录"

            created = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "create_faithfulness_record.py"),
                    "--article", str(article),
                    "--knowledge", str(knowledge),
                    "--source-index", str(source_index),
                    "--receipt", str(wrong),
                    "--handoff-contract-version", current_version(),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(created.returncode, 0)
            self.assertIn(common_error, created.stderr + created.stdout)
            self.assertFalse(wrong.exists())

            artifacts = []
            for name in ("prepared.json", "judgments.json", "summary.md"):
                path = root / name
                path.write_text("{}\n", encoding="utf-8")
                artifacts.append(path)
            imported = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "import_faithfulness.py"),
                    "--prepared", str(artifacts[0]),
                    "--judgments", str(artifacts[1]),
                    "--summary", str(artifacts[2]),
                    "--article", str(article),
                    "--knowledge", str(knowledge),
                    "--article-version", "v1",
                    "--article-date", "2026-09-16",
                    "--metrics-csv", str(root / "metrics.csv"),
                    "--support-csv", str(root / "support.csv"),
                    "--receipt", str(wrong),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(imported.returncode, 0)
            self.assertIn(common_error, imported.stderr + imported.stdout)
            self.assertFalse(wrong.exists())

    def test_create_uses_standard_50_and_moves_it_with_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "P-TEST_测试知识库_v0.6"
            task = project / "04_文章任务/20_等待终稿/ART-001_Test"
            task.mkdir(parents=True)
            for state in ("10_进行中", "30_等待Faithfulness", "40_已完成"):
                (project / "04_文章任务" / state).mkdir(parents=True)
            todo = project / "01_工作台/20_当前待办.md"
            todo.parent.mkdir(parents=True)
            todo.write_text(
                "# 当前待办\n\n"
                "| 对象ID | 人能看懂的事项 | 当前阶段 | 是否阻塞 | 下一步由谁做 | 直达链接 | 更新/重开条件 | 最近更新 |\n"
                "|---|---|---|---|---|---|---|---|\n",
                encoding="utf-8",
            )
            article = task / "40_最终文章.md"
            knowledge = task / "30_本篇知识库资料.md"
            source_index = task / "35_写作素材来源索引.md"
            article.write_text(
                "# 最终文章\n\n- 文章ID：ART-001\n- 文章版本：v1\n"
                "- 完成日期：2026-09-16\n- 文章标题：Test\n",
                encoding="utf-8",
            )
            knowledge.write_text(
                "# 本篇写作素材包\n\n- 文章ID：ART-001\n- 文章版本：v1\n"
                "- 资料视图：写作素材包\n",
                encoding="utf-8",
            )
            source_index.write_text(
                "# 写作素材来源索引\n\n- 文章ID：ART-001\n- 文章版本：v1\n",
                encoding="utf-8",
            )
            result_dir = Path(temp) / "results/P-TEST/ART-001/v1"
            receipt = task / "50_文章知识使用与Faithfulness记录.md"
            audit_skill = Path(temp) / "deepeval-article-audit"
            audit_skill.mkdir()
            (audit_skill / "SKILL.md").write_text(
                "---\nname: deepeval-article-audit\ndescription: Test fixture.\n---\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "create_faithfulness_record.py"),
                    "--article", str(article),
                    "--knowledge", str(knowledge),
                    "--source-index", str(source_index),
                    "--receipt", str(receipt),
                    "--result-dir", str(result_dir),
                    "--handoff-contract-version", current_version(),
                    "--faithfulness-skill-path", str(audit_skill),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            moved = project / "04_文章任务/30_等待Faithfulness/ART-001_Test"
            self.assertFalse(task.exists())
            self.assertTrue((moved / receipt.name).is_file())
            self.assertIn(f"receipt={moved / receipt.name}", result.stdout)

    def test_completion_receipt_requires_valid_standard_50(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_dir = root / "result"
            result_dir.mkdir()
            task = root / "04_文章任务/40_已完成/ART-001_Test"
            task.mkdir(parents=True)
            kwargs = dict(
                contract_version=current_version(),
                article_id="ART-001",
                article_version="v1",
                task_dir=str(task),
                audit_id="AUD-001",
                imported_at="2026-09-16T12:00:00+08:00",
            )
            with self.assertRaisesRegex(ValueError, "缺少标准50记录"):
                write_completion_receipt(result_dir, **kwargs)
            self.assertFalse((result_dir / "article_completed.json").exists())

            record = task / "50_文章知识使用与Faithfulness记录.md"
            record.write_text("# 错误记录\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未通过模板门禁"):
                write_completion_receipt(result_dir, **kwargs)
            self.assertFalse((result_dir / "article_completed.json").exists())

    def test_20_table_spacing_repair_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp)
            audit = task / "20_文章前知识审核.md"
            audit.write_text(
                "# 文章前知识审核\n\n## 知识准备充分性复核\n\n"
                "| 大纲章节 | 候选事实数 |\n|---|---:|\n\n| 标题 | 1 |\n",
                encoding="utf-8",
            )
            first = normalize_task_tables(task)
            first_hash = sha256(audit)
            second = normalize_task_tables(task)
            self.assertEqual(first, [audit])
            self.assertEqual(second, [])
            self.assertEqual(first_hash, sha256(audit))
            self.assertNotIn("|---|---:|\n\n| 标题", audit.read_text(encoding="utf-8"))

    def test_package_gate_reports_multiple_errors_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "P-TEST_测试知识库_v0.6"
            task = project / "04_文章任务/10_进行中/ART-001_Test"
            task.mkdir(parents=True)
            (project / "03_正式知识").mkdir()
            (task / "20_文章前知识审核.md").write_text(
                "# 文章前知识审核\n\n- 可用Claim数：2\n",
                encoding="utf-8",
            )
            (task / "30_本篇知识库资料.md").write_text(
                "# 本篇写作素材包\n\n- 文章ID：ART-001\n",
                encoding="utf-8",
            )
            (task / "35_写作素材来源索引.md").write_text(
                "# 写作素材来源索引\n\n- 文章ID：ART-002\n"
                "- 写作素材SHA-256：wrong\n\n## 写作素材到正式知识映射\n\n"
                "| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |\n"
                "|---:|---:|---|---|---|---|---|\n"
                "| 999 | 1000 | 测试 | CLM-MISSING-001 | 测试 | [[03_正式知识/missing.md]] | 无 |\n",
                encoding="utf-8",
            )
            errors = article_package_errors(task)
            joined = "\n".join(errors)
            self.assertGreaterEqual(len(errors), 5)
            self.assertIn("30与35文章ID不一致", joined)
            self.assertIn("30哈希不匹配", joined)
            self.assertIn("超出30实际行数", joined)
            self.assertIn("正式Claim不存在", joined)
            self.assertIn("正式知识文件不存在", joined)


if __name__ == "__main__":
    unittest.main()
