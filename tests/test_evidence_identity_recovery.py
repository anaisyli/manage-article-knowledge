import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "manage-article-knowledge-v0.6.1" / "scripts"))
from test_evidence_identity import formal_fixture
import test_validation_lifecycle
from evidence_identity import material_contexts
from recover_article_package import RecoveryResult, _rebuild_material_and_index, _render_minimal_material


class EvidenceIdentityRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = test_validation_lifecycle.ValidationLifecycleTests()._write_package_fixture(self.root,
            claim_evidence="We offer paper boxes.\n> Our boxes use paperboard.",
            material_evidence="We offer paper boxes.")
        request = self.task / "10_文章知识需求.md"
        request.write_text(request.read_text(encoding="utf-8-sig") + "- 证据模板版本：EC-1\n", encoding="utf-8")
        formal = self.root / "03_正式知识/10_客户知识/20_产品介绍/formal.md"
        self.formal = formal
        formal.write_text(formal_fixture(), encoding="utf-8")

    def test_missing_30_recovery_restores_context_and_evidence_together(self):
        result = RecoveryResult()
        text = _render_minimal_material(self.task, self.root, result)
        self.assertIsNotNone(text)
        self.assertIn("- 证据模板版本：EC-1", text)
        self.assertNotIn("##### 证据", text)
        self.assertEqual(len(material_contexts(text.splitlines())), 1)
        self.assertIn("> Our boxes use paperboard.", text)

    def test_existing_30_recovery_updates_context_quote_mapping_and_hash(self):
        from article_state import parse_field
        import hashlib
        material = self.task / "30_本篇知识库资料.md"
        material.write_text(material.read_text(encoding="utf-8-sig").replace("- 资料版本：v1", "- 证据模板版本：EC-1"), encoding="utf-8")
        result = RecoveryResult()
        _rebuild_material_and_index(self.task, self.root, result)
        context = material_contexts(material.read_text(encoding="utf-8").splitlines())[0]
        self.assertEqual(context["fields"]["内容提供方"], "Example Company")
        self.assertIn("> Our boxes use paperboard.", material.read_text(encoding="utf-8"))
        index = (self.task / "35_写作素材来源索引.md").read_text(encoding="utf-8-sig")
        self.assertEqual(parse_field(index, "写作素材SHA-256"), hashlib.sha256(material.read_bytes()).hexdigest())
        before = material.read_bytes()
        _rebuild_material_and_index(self.task, self.root, RecoveryResult())
        self.assertEqual(material.read_bytes(), before)

    def test_legacy_claim_without_verified_context_requires_source_recheck(self):
        self.formal.write_text("- Claim ID：CLM-TEST-001\n### 最小原文证据\n> We offer paper boxes.\n", encoding="utf-8")
        before = self.formal.read_bytes()
        result = RecoveryResult()
        self.assertIsNone(_render_minimal_material(self.task, self.root, result))
        self.assertTrue(any("回源核验" in message for message in result.unresolved))
        self.assertEqual(self.formal.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
