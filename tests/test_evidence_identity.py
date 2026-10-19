"""EC-1 behavior shared by the knowledge and audit skills."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "manage-article-knowledge-v0.6.1" / "scripts"))
from evidence_identity import (CONTEXT_FIELDS, evidence_digest, formal_context,
    formal_errors, mapping_identity_errors, material_contexts, render_context,
    validate_coreference)


def formal_fixture():
    text = (
        "- Claim ID：CLM-TEST-001\n- 证据模板版本：EC-1\n"
        "- 证据归属主体：Example Company\n- 证据归属对象：Paper boxes\n"
        "- 指代解析：We/our refers to Example Company; this refers to paper boxes.\n"
        "- 归属核验依据：回读官网About页面标题和同段产品上下文\n"
        "- 归属核验日期：2026-10-13\n- 归属核验状态：已核验\n"
        "- 归属证据SHA-256：DIGEST\n\n### 最小原文证据\n\n"
        "> We offer paper boxes.\n> Our boxes use paperboard.\n"
    )
    return text.replace("DIGEST", evidence_digest(text))


def material_fixture(two=False):
    context = formal_context(formal_fixture())
    text = "- 证据模板版本：EC-1\n## 一、可直接用于正文的事实\n### Supply\n"
    text += render_context(context) + "#### 证据正文（供Faithfulness核验）\n> We offer paper boxes.\n"
    if two:
        text += "\n### Material\n" + render_context(context)
        text += "#### 证据正文（供Faithfulness核验）\n> Our boxes use paperboard.\n"
    return text + "\n## 四、按大纲使用\n无\n"


class EvidenceIdentityTests(unittest.TestCase):
    def contexts(self, text=None):
        return material_contexts((text or material_fixture()).splitlines(), str(ROOT / "test30.md"))

    def reference(self, context):
        return {key: context[key] for key in ("source_file", "line_start", "line_end", "quote")} | {
            "reason": "来源中的We/our明确指向已核验的Example Company。"}

    def fact(self, context, quote="We offer paper boxes."):
        return dict(source_file=context["source_file"], line_start=context["evidence_line_start"],
                    line_end=context["evidence_line_end"], quote=quote)

    def test_verified_formal_context_has_exact_four_fields(self):
        self.assertEqual(formal_errors(formal_fixture(), True), [])
        self.assertEqual(tuple(formal_context(formal_fixture())), CONTEXT_FIELDS)

    def test_blank_and_duplicate_formal_fields_are_rejected(self):
        for name in ("证据归属主体", "证据归属对象", "指代解析", "归属核验依据"):
            import re
            text = re.sub(r"(?m)^- " + name + "：.*$", "- " + name + "：", formal_fixture())
            with self.subTest(name=name, case="blank"):
                self.assertTrue(any(name in error for error in formal_errors(text, True)))
            with self.subTest(name=name, case="duplicate"):
                self.assertTrue(formal_errors(formal_fixture() + "\n- " + name + "：重复\n", True))

    def test_duplicate_template_version_cannot_bypass_validation(self):
        self.assertTrue(formal_errors(formal_fixture() + "- 证据模板版本：EC-1\n"))

    def test_changed_original_or_digest_is_rejected(self):
        for text in (formal_fixture().replace("We offer paper boxes.", "We offer wood boxes."),
                     formal_fixture().replace(evidence_digest(formal_fixture()), "0" * 64)):
            self.assertTrue(any("SHA-256" in error for error in formal_errors(text, True)))

    def test_unverified_identity_is_not_returned(self):
        self.assertIsNone(formal_context(formal_fixture().replace("归属核验状态：已核验", "归属核验状态：待确认")))

    def test_legacy_claim_is_readable_but_not_reusable_as_ec1(self):
        legacy = "- Claim ID：CLM-OLD-001\n### 最小原文证据\n> We offer paper boxes.\n"
        self.assertEqual(formal_errors(legacy), [])
        self.assertTrue(formal_errors(legacy, True))
        self.assertIsNone(formal_context(legacy))

    def test_context_does_not_enter_fact_range(self):
        context = self.contexts()[0]
        self.assertLess(context["line_end"], context["evidence_line_start"])
        self.assertEqual(context["fields"], formal_context(formal_fixture()))

    def test_missing_duplicate_or_reordered_context_fields_fail(self):
        source = material_fixture()
        for text in (source.replace("- 对应对象：Paper boxes\n", ""),
                     source.replace("- 对应对象：Paper boxes", "- 内容提供方：Example Company"),
                     source.replace("- 内容提供方：Example Company\n- 对应对象：Paper boxes",
                                    "- 对应对象：Paper boxes\n- 内容提供方：Example Company")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.contexts(text)

    def test_unbound_context_cannot_be_lost_at_section_boundary(self):
        for heading in ("## 二、可直接采用的英文表达", "# Unexpected", "### Another fact"):
            text = material_fixture().replace("#### 证据正文", heading + "\n#### 证据正文", 1)
            with self.subTest(heading=heading), self.assertRaises(ValueError):
                self.contexts(text)

    def test_repeated_context_and_wrong_heading_level_fail(self):
        source = material_fixture()
        context = render_context(formal_context(formal_fixture()))
        for text in (source.replace(context, context + context),
                     source.replace("#### 证据正文", "##### 证据正文"),
                     source.replace("#### 证据归属", "##### 证据归属"),
                     source.replace("#### 证据", "##### 证据")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.contexts(text)

    def test_legacy_material_with_ec1_claim_stays_legacy_compatible(self):
        legacy_material = "## 一、可直接用于正文的事实\n### Supply\n#### 证据正文（供Faithfulness核验）\n> We offer paper boxes.\n"
        start = legacy_material.splitlines().index("#### 证据正文（供Faithfulness核验）") + 2
        self.assertEqual(mapping_identity_errors(legacy_material, start, start, formal_fixture()), [])
    def test_mapping_must_match_persisted_formal_identity(self):
        context = self.contexts()[0]
        start, end = context["evidence_line_start"], context["evidence_line_end"]
        self.assertEqual(mapping_identity_errors(material_fixture(), start, end, formal_fixture(), True), [])
        mismatch = material_fixture().replace("内容提供方：Example Company", "内容提供方：Another Company")
        self.assertTrue(mapping_identity_errors(mismatch, start, end, formal_fixture(), True))

    def test_same_block_coreference_is_accepted(self):
        context = self.contexts()[0]
        validate_coreference(dict(verdict="supported", evidence=[self.fact(context)],
                                 coreference_evidence=[self.reference(context)]), [context])

    def test_context_alone_and_cross_block_use_fail(self):
        contexts = self.contexts(material_fixture(two=True))
        for facts in ([], [self.fact(contexts[1], "Our boxes use paperboard.")]):
            with self.subTest(facts=facts), self.assertRaises(ValueError):
                validate_coreference(dict(verdict="supported", evidence=facts,
                    coreference_evidence=[self.reference(contexts[0])]), contexts)

    def test_each_pronoun_fact_needs_its_own_context_reference(self):
        contexts = self.contexts(material_fixture(two=True))
        claim = dict(verdict="supported", evidence=[self.fact(contexts[0]), self.fact(contexts[1], "Our boxes use paperboard.")],
                     coreference_evidence=[self.reference(contexts[0])])
        with self.assertRaises(ValueError):
            validate_coreference(claim, contexts)
        claim["coreference_evidence"].append(self.reference(contexts[1]))
        validate_coreference(claim, contexts)

    def test_context_quote_and_file_must_match_exactly(self):
        context = self.contexts()[0]
        for key, value in (("quote", "Invented Company"), ("source_file", "another30.md"),
                           ("line_start", context["line_start"] + 1)):
            ref = self.reference(context)
            ref[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_coreference(dict(evidence=[self.fact(context)], coreference_evidence=[ref]), [context])

    def test_unknown_without_coreference_remains_reportable(self):
        context = self.contexts()[0]
        validate_coreference(dict(verdict="unsupported", semantic_status="unknown",
                                 evidence=[self.fact(context)]), [context])

    def test_both_installed_skills_use_identical_parser(self):
        installed = Path.home() / ".codex" / "skills"
        paths = [installed / name / "scripts" / "evidence_identity.py"
                 for name in ("manage-article-knowledge", "deepeval-article-audit")]
        if not all(path.is_file() for path in paths):
            self.skipTest("Both installed skills are required for parity check")
        self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())


if __name__ == "__main__":
    unittest.main()

