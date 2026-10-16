import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_faithfulness import load_disposition, source_scope, validate_disposition_links


class EvidenceContextDispositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "30_本篇知识库资料.md"
        self.package.write_text(
            "- 资料视图：写作素材包\n"
            "## 一、可直接用于正文的事实\n"
            "### 产品材料\n"
            "#### 证据正文（供Faithfulness核验）\n"
            "> We offer paper boxes.\n"
            "- 主体归属说明：We refers to JERL.\n"
            "## 四、按大纲使用建议\n"
            "JERL offers paper boxes.\n", encoding="utf-8")
        self.group = dict(
            group_id="UG-001", claim_ids=["C001"], topic="客户供应能力主体归属",
            category="evidence_context_gap", classification_basis="当前证据有供应能力但主体归属不唯一",
            issue_key="", status="待后续资料准备修正", article_impact="保持原尚未确认结果",
            handling="本次保留真实上下文并记录归属问题", next_owner="Codex", entry=str(self.package),
            close_condition="后续资料包包含明确主体的完整证据",
            fact_check=dict(contains_factual_judgment=True, reusable_across_articles=False,
                            knowledge_domains=["customer_fact"], why_not_knowledge_issue=""))

    def load(self, evidence, knowledge=None):
        path = self.root / "disposition.json"
        path.write_text(json.dumps(dict(schema_version="1.1", article_id="ART-001",
                                        groups=[self.group]), ensure_ascii=False), encoding="utf-8")
        claims = [dict(claim_id="C001", verdict="unsupported", semantic_status="unknown",
                       claim="JERL offers paper boxes.", evidence=evidence)]
        return load_disposition(path, "ART-001", claims, self.root,
                                [self.package] if knowledge is None else knowledge)

    def evidence(self, line=5, quote="We offer paper boxes.", source=None):
        return [dict(source_file=str(source or self.package), line_start=line,
                     line_end=line, quote=quote)]

    def test_real_current_evidence_is_accepted_without_rejudging(self):
        groups = self.load(self.evidence())
        self.assertEqual(groups[0]["category"], "evidence_context_gap")

    def test_no_evidence_or_no_current_package_is_rejected(self):
        for evidence, knowledge in [([], None), (self.evidence(), [])]:
            with self.subTest(evidence=evidence, knowledge=knowledge), self.assertRaises(ValueError):
                self.load(evidence, knowledge)

    def test_wrong_quote_line_or_source_is_rejected(self):
        for evidence in [self.evidence(quote="We offer wood boxes."), self.evidence(line=8),
                         self.evidence(source=self.root / "old30.md")]:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.load(evidence)

    def test_subject_metadata_is_not_evidence_even_under_evidence_heading(self):
        with self.assertRaises(ValueError):
            self.load(self.evidence(line=6, quote="We refers to JERL."))
        self.assertFalse(source_scope(self.package.read_text(encoding="utf-8").splitlines(), self.package)[5])

    def test_package_omission_requires_existing_formal_claim(self):
        self.group.update(category="package_omission",
                          classification_basis="已核验正式Claim CLM-TEST-001遗漏进本篇30",
                          entry="CLM-TEST-001")
        groups = self.load([])
        with self.assertRaises(ValueError):
            validate_disposition_links(groups, self.root, "ART-001")
        formal = self.root / "03_正式知识" / "facts.md"
        formal.parent.mkdir()
        formal.write_text("## 纸盒供应能力\n- Claim ID：CLM-TEST-001\n"
                          "JERL offers paper boxes.\n", encoding="utf-8")
        validate_disposition_links(groups, self.root, "ART-001")


if __name__ == "__main__":
    unittest.main()
