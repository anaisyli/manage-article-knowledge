"""decisive_recheck_v1: only first-pass entailed/contradicted claims get a second judgment.

Covers the knowledge-side import of that policy, its recording in the metrics CSV,
the 50 record label, the monthly mixed-policy notice, and an end-to-end check that
artifacts produced by the audit Skill's own reconciler are accepted on import.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import import_faithfulness  # noqa: E402
from import_faithfulness import (  # noqa: E402
    DECISIVE_RECHECK_POLICY,
    METRIC_FIELDS,
    PRE_POLICY_METRIC_FIELDS,
    load_csv,
    protocol2_adversarial_error,
    protocol2_reconciliation_error,
    recorded_review_policy,
    review_policy_label,
)
from validate_v06_project import load_metrics  # noqa: E402


def audit_skill_root() -> Path | None:
    """Find the installed audit Skill the same way the handoff contract does."""
    candidates = [
        os.environ.get("DEEPEVAL_ARTICLE_AUDIT", ""),
        str(ROOT.parents[1] / "deepeval-article-audit"),
        str(Path.home() / ".claude/skills/deepeval-article-audit"),
        str(Path.home() / ".codex/skills/deepeval-article-audit"),
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "scripts/reconcile_article_audit.py").is_file():
            return Path(candidate)
    return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_pass_claim(n: int, text: str, status: str) -> dict:
    verdict = {"entailed": ("yes", "supported"), "unknown": ("idk", "unsupported"),
               "contradicted": ("no", "unsupported")}[status]
    return {
        "claim_id": f"C{n:03d}", "unit_id": f"U{n:03d}", "article_line": n,
        "article_quote": text, "claim": text,
        "deepeval_verdict": verdict[0], "semantic_status": status, "verdict": verdict[1],
        "reason": "第一轮按允许证据逐项判断该主张。",
        "evidence": [{"quote": text}] if status == "entailed" else [],
    }


def check(status: str, fragment: str = "") -> dict:
    return {"status": status, "claim_fragment": fragment, "evidence_fragment": fragment,
            "reason": "逐项核对主张和证据中的对应语义成分。"}


def recheck_row(claim: dict) -> dict:
    text = claim["claim"]
    return {
        **{k: claim[k] for k in ("claim_id", "unit_id", "article_line", "article_quote", "claim")},
        "claim_fragment": text, "evidence_fragment": text,
        "independent_semantic_status": "entailed", "semantic_status": "entailed",
        "atomicity_review": {"status": "atomic", "independent_proposition_count": 1,
                             "reason": "该文本只包含一个可独立判断的核心命题。"},
        "entailment_checks": {
            "subject_object": check("covered", "product"),
            "predicate_relation": check("covered", "is IP67 certified"),
            "scope_condition": check("not_applicable"),
            "quantity_time_version": check("covered", "IP67"),
            "causal_effect": check("not_applicable"),
        },
        "challenge_reason": "证据明确陈述同一产品具备IP67认证，未增加对象、范围或效果。",
    }


class DecisiveEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = audit_skill_root()
        if self.audit is None:
            self.skipTest("deepeval-article-audit Skill is not installed next to this Skill")

    def reconcile(self, root: Path) -> tuple[dict, dict]:
        claims = [
            first_pass_claim(1, "The product is IP67 certified.", "entailed"),
            first_pass_claim(2, "The warehouse ships within two days.", "unknown"),
            first_pass_claim(3, "The company guarantees a 30-day lead time.", "entailed"),
        ]
        judgments = {"schema_version": "1.1", "evaluation_protocol_version": "2.0",
                     "article_id": "ART-001", "review_policy": DECISIVE_RECHECK_POLICY, "claims": claims}
        review = {"schema_version": "1.0", "evaluation_protocol_version": "2.0",
                  "article_id": "ART-001", "review_mode": "independent_adversarial",
                  "review_policy": DECISIVE_RECHECK_POLICY, "claim_inventory": [],
                  # C003 was decisive in the first pass but never rechecked.
                  "claim_reviews": [recheck_row(claims[0])]}
        judgments_path = root / "ART-001-judgments.json"
        review_path = root / "ART-001-adversarial-review.json"
        judgments_path.write_text(json.dumps(judgments, ensure_ascii=False), encoding="utf-8")
        review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            [sys.executable, str(self.audit / "scripts/reconcile_article_audit.py"),
             "--judgments", str(judgments_path), "--adversarial-review", str(review_path)],
            check=True, capture_output=True, text=True,
        )
        return (json.loads(judgments_path.read_text(encoding="utf-8")),
                json.loads(review_path.read_text(encoding="utf-8")))

    def test_audit_reconciler_output_is_accepted_and_policy_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            judgments, review = self.reconcile(Path(temp))
        statuses = {c["claim_id"]: c["semantic_status"] for c in judgments["claims"]}
        self.assertEqual(statuses, {"C001": "entailed", "C002": "unknown", "C003": "unknown"})
        self.assertIsNone(protocol2_reconciliation_error(judgments))
        self.assertIsNone(protocol2_adversarial_error(
            review, judgments["claims"], "ART-001", expected_review_policy=judgments["review_policy"]
        ))
        self.assertEqual(recorded_review_policy(judgments, "2.0"), DECISIVE_RECHECK_POLICY)
        self.assertIn("只复核第一轮有结论的主张", review_policy_label(recorded_review_policy(judgments, "2.0")))

    def test_promoting_an_unrechecked_first_pass_unknown_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            judgments, review = self.reconcile(Path(temp))
        claim = next(c for c in judgments["claims"] if c["claim_id"] == "C002")
        claim["semantic_status"] = claim["reconciliation"]["final_semantic_status"] = "entailed"
        self.assertIn("must stay unknown", protocol2_reconciliation_error(judgments))

    def test_policy_mismatch_between_artifacts_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            judgments, review = self.reconcile(Path(temp))
        self.assertIsNotNone(protocol2_adversarial_error(
            review, judgments["claims"], "ART-001", expected_review_policy="risk_weighted_v1"
        ))


class ReviewPolicyRecordingTests(unittest.TestCase):
    def test_old_protocols_record_no_policy(self) -> None:
        judgments = {"reconciliation": {"policy": DECISIVE_RECHECK_POLICY}}
        self.assertEqual(recorded_review_policy(judgments, "1.0"), "")
        self.assertEqual(review_policy_label(""), "未记录（旧协议）")

    def test_pre_policy_metrics_csv_is_migrated_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "10_文章Faithfulness明细.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=PRE_POLICY_METRIC_FIELDS)
                writer.writeheader()
                writer.writerow({field: "x" for field in PRE_POLICY_METRIC_FIELDS})
            rows = load_csv(path, METRIC_FIELDS)
            self.assertEqual(rows[0]["review_policy"], "")
            self.assertEqual(rows[0]["contradicted_claims"], "x")
            errors: list[str] = []
            load_metrics(path, errors)
            self.assertEqual(errors, [])
        self.assertEqual(METRIC_FIELDS[-1], "review_policy")


class MonthlyMixedPolicyTests(unittest.TestCase):
    def run_month(self, policies: list[str]) -> str:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            knowledge = root / "30_本篇知识库资料.md"
            knowledge.write_text("knowledge", encoding="utf-8")
            rows = []
            for n, policy in enumerate(policies, 1):
                article = root / f"article-{n}.md"
                article.write_text(f"article {n}", encoding="utf-8")
                row = {field: "" for field in METRIC_FIELDS}
                row.update(
                    audit_id=f"AUD-{n}", article_id=f"ART-{n:03d}", article_version="v1",
                    article_date="2026-10-05", article_file=str(article), article_sha256=sha256(article),
                    knowledge_files=json.dumps([str(knowledge)]), knowledge_sha256=json.dumps([sha256(knowledge)]),
                    evaluation_mode="Codex reproduction", evaluation_protocol_version="2.0",
                    unknown_claims="1", contradicted_claims="0", primary_metric="strict_support",
                    supported_claims="1", total_claims="2", unsupported_claims="1",
                    faithfulness_percent="50.00", mapped_formal_claims="0", unmapped_supported_claims="0",
                    imported_at="2026-10-05", status="current", review_policy=policy,
                )
                rows.append(row)
            metrics = root / "metrics.csv"
            with metrics.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=METRIC_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            output = root / "monthly.md"
            subprocess.run(
                [sys.executable, str(SCRIPTS / "calculate_monthly_faithfulness.py"),
                 "--metrics-csv", str(metrics), "--month", "2026-10", "--output", str(output)],
                check=True, capture_output=True, text=True,
            )
            return output.read_text(encoding="utf-8")

    def test_single_policy_month_has_no_notice(self) -> None:
        report = self.run_month([DECISIVE_RECHECK_POLICY, DECISIVE_RECHECK_POLICY])
        self.assertIn("复核口径 只复核第一轮有结论的主张", report)
        self.assertNotIn("复核口径提示", report)

    def test_mixed_policy_month_is_flagged(self) -> None:
        report = self.run_month([DECISIVE_RECHECK_POLICY, "risk_weighted_v1"])
        self.assertIn("### 复核口径提示", report)
        self.assertIn("不能直接与单一口径月份比较", report)


if __name__ == "__main__":
    unittest.main()
