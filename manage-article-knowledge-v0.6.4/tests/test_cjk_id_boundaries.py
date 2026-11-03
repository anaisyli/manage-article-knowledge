"""IDs written right next to Chinese text must still be found whole (SK-V064-009).

Python's \\b treats CJK characters as word characters: "调研RES-001" had no boundary
before the ID, and "CLM-…-001支持" backtracked to a truncated "CLM-…-".  ID regexes use
the scoped ASCII flag ``(?a:\\b)`` instead.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import task_records  # noqa: E402
from template_contract import researched_gap_evidence  # noqa: E402

BS = chr(92)
LITERAL = re.compile(r"""(?<![A-Za-z0-9_])(?:rf|fr|r)(["'])(.*?)(?<!""" + BS * 2 + r""")\1""")
ID_LIKE = re.compile(r"[A-Z]{2,5}-|\(\?:[A-Z]|B" + BS * 2 + "d|JERL")


class CjkIdBoundaryTests(unittest.TestCase):
    def test_ids_next_to_chinese_are_found_whole(self):
        text = "CLM-EXT-P005-ENVCLAIM-001支持把宣称限定；见EV-002与CF-003处理"
        self.assertEqual(task_records.CLAIM_RE.findall(text), ["CLM-EXT-P005-ENVCLAIM-001"])
        self.assertEqual(task_records.EV_RE.findall(text), ["EV-002"])
        self.assertEqual(task_records.CF_RE.findall(text), ["CF-003"])

    def test_ascii_neighbours_still_do_not_match(self):
        self.assertEqual(task_records.CLAIM_RE.findall("xCLM-A-001 和 CLM-B-002"), ["CLM-B-002"])

    def test_research_handling_written_without_separators(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            evidence = project / "02_源资料/50_外部调研证据/RES-T-001_规则"
            evidence.mkdir(parents=True)
            record = "- 调研ID：RES-T-001\n- 关联缺口：GAP-T-001\n- 文章知识准备运行ID：不适用\n"
            (evidence / "10_来源原文证据.md").write_text(record, encoding="utf-8")
            (evidence / "20_调研核验记录.md").write_text(record + "CLM-EXT-T-001\n", encoding="utf-8")
            formal = project / "03_正式知识/20_外部公共知识/规则.md"
            formal.parent.mkdir(parents=True)
            formal.write_text("CLM-EXT-T-001\n关联调研：RES-T-001\n", encoding="utf-8")
            self.assertTrue(researched_gap_evidence(project, "GAP-T-001", "本轮定向调研RES-T-001，沉淀CLM-EXT-T-001", None))

    def test_no_id_regex_uses_a_bare_word_boundary(self):
        offenders = []
        for path in sorted(SCRIPTS.glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in LITERAL.finditer(line):
                    body = match.group(2).replace("(?a:" + BS + "b)", "")
                    if BS + "b" in body and ID_LIKE.search(body):
                        offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [], "use (?a:\\b) next to IDs so Chinese text counts as a boundary")


if __name__ == "__main__":
    unittest.main()
