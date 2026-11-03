import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from external_research_links import (FIELDS, GAP_CSV, HEADING, PROTOCOL, RESEARCH_ROOT,
                                    links_for_gap, parse_links, record_link, research_records,
                                    validate_research_links)
from build_coverage_view import build_view, coverage_fingerprint
from record_knowledge_gap import FIELDS as GAP_FIELDS, next_gap_key, read_rows, write_rows


class ResearchLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / GAP_CSV).parent.mkdir(parents=True)
        self.gaps = []
        for number in (1, 2):
            row = {f: "" for f in GAP_FIELDS}
            row.update(gap_key=f"GAP-P005-{number:03d}", gap_topic=f"纸盒材料问题{number}的条件与方法",
                       gap_type="公共知识", status="待外部调研", trigger_basis="核心章节首次",
                       article_ids="ART-001", article_count="1", current_article_ids="ART-001",
                       current_article_count="1", related_governance_ref="无")
            self.gaps.append(row)
        write_rows(self.root / GAP_CSV, self.gaps)
        self.claim = self.root / "03_正式知识/20_外部公共知识/50_行业知识与洞察/纸盒材料.md"
        self.claim.parent.mkdir(parents=True)
        self.claim.write_text("- Claim ID：CLM-EXT-P005-PAPER-001\n", encoding="utf-8")

    def record(self, number, template=False):
        path = self.root / RESEARCH_ROOT / f"RES-P005-20261013-{number:03d}_纸盒材料" / "20_调研核验记录.md"
        path.parent.mkdir(parents=True)
        text = f"# 外部调研核验记录\n\n- 调研ID：RES-P005-20261013-{number:03d}\n- 关联缺口：无\n"
        if template:
            text += PROTOCOL + "\n\n" + HEADING + "\n\n| " + " | ".join(FIELDS) + " |\n|" + "---|" * 6 + "\n"
        text += "\n## 去向\n\n保留原核验内容\n"
        path.write_text(text, encoding="utf-8")
        path.with_name("10_来源原文证据.md").write_text(
            f"- 调研ID：RES-P005-20261013-{number:03d}\n- 关联缺口：无\n\n> Original source quotation.\n", encoding="utf-8")
        return path

    def row(self, key="GAP-P005-001", result="部分解决", remaining="仍缺湿度变化的影响"):
        return dict(zip(FIELDS, (key, "纸盒材料与适用范围", "回答基础材料选择",
                                 remaining, "CLM-EXT-P005-PAPER-001", result)))

    def test_many_to_many_navigation_and_idempotent_updates(self):
        first, second = self.record(1, True), self.record(2)
        record_link(self.root, first, self.row())
        record_link(self.root, first, self.row("GAP-P005-002"))
        record_link(self.root, second, self.row())
        record_link(self.root, first, self.row(remaining="还缺闭合试验范围"))
        rows, errors = parse_links(first.read_text(encoding="utf-8"))
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 2)
        self.assertIn("保留原核验内容", first.read_text(encoding="utf-8"))
        source_text = first.with_name("10_来源原文证据.md").read_text(encoding="utf-8")
        self.assertIn("GAP-P005-001", source_text)
        self.assertIn("GAP-P005-002", source_text)
        self.assertIn("> Original source quotation.", first.with_name("10_来源原文证据.md").read_text(encoding="utf-8"))
        links = links_for_gap(self.gaps[0], research_records(self.root))
        self.assertEqual(len(links), 2)
        errors = []
        validate_research_links(self.root, errors)
        self.assertEqual(errors, [])
        view = build_view(self.root)
        for token in (first.parent.name, second.parent.name, "纸盒材料.md", "CLM-EXT-P005-PAPER-001", "还缺闭合试验范围"):
            self.assertIn(token, view)
        self.assertEqual(read_rows(self.root / GAP_CSV)[0]["status"], "待外部调研")

    def test_legacy_links_are_explicit_and_do_not_invent_scope(self):
        first, unrelated = self.record(1), self.record(2)
        first.write_text(first.read_text(encoding="utf-8").replace("关联缺口：无", "关联缺口：GAP-P005-001"), encoding="utf-8")
        errors = []
        validate_research_links(self.root, errors)
        self.assertEqual(errors, [])
        links = links_for_gap(self.gaps[0], research_records(self.root))
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["record"]["path"], first)
        self.assertIn("历史记录未分项登记", build_view(self.root))
        self.assertNotIn(unrelated.parent.name, build_view(self.root))

    def test_csv_legacy_ref_gives_direct_navigation(self):
        path = self.record(1)
        gaps = read_rows(self.root / GAP_CSV)
        gaps[0]["related_governance_ref"] = "RES-P005-20261013-001;CLM-EXT-P005-PAPER-001"
        write_rows(self.root / GAP_CSV, gaps)
        view = build_view(self.root)
        self.assertIn(path.parent.name, view)
        self.assertIn("纸盒材料.md", view)

    def test_claim_only_review_does_not_change_gap_links(self):
        path = self.record(1)
        record_link(self.root, path, self.row("无", "仅复核", "无"))
        errors = []
        validate_research_links(self.root, errors)
        self.assertEqual(errors, [])
        self.assertEqual(links_for_gap(self.gaps[0], research_records(self.root)), [])
        self.assertEqual(read_rows(self.root / GAP_CSV), self.gaps)

    def test_bad_resolution_and_nonexistent_claim_are_rejected_before_write(self):
        path = self.record(1)
        original = path.read_bytes(), (self.root / GAP_CSV).read_bytes()
        cases = [self.row(result="已解决"), self.row(remaining="无"), self.row("GAP-P005-009")]
        bad = self.row()
        bad[FIELDS[4]] = "CLM-EXT-MISSING-001"
        cases.append(bad)
        for row in cases:
            with self.subTest(row=row), self.assertRaises(ValueError):
                record_link(self.root, path, row)
            self.assertEqual((path.read_bytes(), (self.root / GAP_CSV).read_bytes()), original)

    def test_validator_checks_references_header_protocol_and_claim_existence(self):
        path = self.record(1)
        record_link(self.root, path, self.row())
        original = path.read_text(encoding="utf-8")
        for text in (original.replace("GR-1", "GR-99"), original.replace("- 关联缺口：GAP-P005-001", "- 关联缺口：GAP-P005-002"),
                     original.replace("CLM-EXT-P005-PAPER-001", "CLM-EXT-MISSING-001"), original.replace("缺口主题 |", "主题 |")):
            path.write_text(text, encoding="utf-8")
            errors = []
            validate_research_links(self.root, errors)
            self.assertTrue(errors)
        path.write_text(original, encoding="utf-8")
        gaps = read_rows(self.root / GAP_CSV)
        gaps[0]["related_governance_ref"] = "无"
        write_rows(self.root / GAP_CSV, gaps)
        errors = []
        validate_research_links(self.root, errors)
        self.assertTrue(any("未回链" in e for e in errors))

    def test_missing_or_mismatched_source_pair_is_rejected(self):
        path = self.record(1)
        source = path.with_name("10_来源原文证据.md")
        source.write_text("- 调研ID：RES-OTHER-001\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            record_link(self.root, path, self.row())
        source.unlink()
        with self.assertRaises(ValueError):
            record_link(self.root, path, self.row())

    def test_research_changes_invalidate_coverage_fingerprint(self):
        path = self.record(1)
        before = coverage_fingerprint(self.root)
        record_link(self.root, path, self.row())
        self.assertNotEqual(before, coverage_fingerprint(self.root))

    def test_alias_pipes_round_trip_and_multigap_cell_rejected(self):
        path = self.record(1)
        row = self.row()
        row[FIELDS[4]] += " [[03_正式知识/纸盒材料.md|材料入口]]"
        record_link(self.root, path, row)
        rows, errors = parse_links(path.read_text(encoding="utf-8"))
        self.assertEqual(errors, [])
        self.assertEqual(rows[0][FIELDS[4]], row[FIELDS[4]])
        with self.assertRaises(ValueError):
            record_link(self.root, path, self.row("GAP-P005-001;GAP-P005-002"))

    def test_sequence_follows_legacy_keys(self):
        self.assertEqual(next_gap_key([{"gap_key": k} for k in ("GAP-001-020", "GAP-027", "GAP-P005-RIGID-CONSTRUCTION")], "P-005"), "GAP-P005-028")

    def test_auto_topic_reuses_legacy_key_via_cli(self):
        args = [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "scripts/record_knowledge_gap.py"),
                "--csv", str(self.root / GAP_CSV), "--gap-key", "auto", "--topic", self.gaps[0]["gap_topic"],
                "--article-id", "ART-001", "--article-date", "2026-10-13", "--trigger-basis", "核心章节首次"]
        result = subprocess.run(args, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"gap_key=GAP-P005-001", result.stdout)
        self.assertEqual(len(read_rows(self.root / GAP_CSV)), 2)


if __name__ == "__main__":
    unittest.main()
