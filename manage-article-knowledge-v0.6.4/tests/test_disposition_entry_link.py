"""SK-V064-025: the default entry links 50 to the item in its human ledger, instead of repeating the key.

P-005-ART-20261029-001's 50 showed "GAP-001-003｜GAP-001-003": SK-V064-014 filled entry with the key,
and 50 renders "<key>｜<entry>".
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_faithfulness import fill_disposition_defaults, ledger_link  # noqa: E402

CUS_PAGE = "05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md"


class DispositionEntryLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        page = self.root / CUS_PAGE
        page.parent.mkdir(parents=True)
        page.write_text("# 待客户补充事项\n\n## 事项详情\n\n### P-T-CUS-001｜抽屉盒质保政策\n\n- 想确认什么：…\n",
                        encoding="utf-8")

    def test_gap_entry_links_to_the_current_gap_section(self):
        self.assertEqual(ledger_link(self.root, "gap", "GAP-001-003"),
                         "[缺口台账](../../../05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md#当前知识缺口)")

    def test_cus_entry_links_to_the_item_heading(self):
        self.assertEqual(ledger_link(self.root, "cus", "P-T-CUS-001"),
                         f"[待客户补充事项](../../../{CUS_PAGE}#P-T-CUS-001｜抽屉盒质保政策)")

    def test_cus_without_a_heading_links_to_the_page(self):
        self.assertEqual(ledger_link(self.root, "cus", "P-T-CUS-009"), f"[待客户补充事项](../../../{CUS_PAGE})")

    def test_default_entry_does_not_repeat_the_key(self):
        group = {"claim_ids": ["C001"], "category": "existing_gap", "issue_key": "GAP-001-003"}
        fill_disposition_defaults(group, 1, self.root)
        self.assertNotEqual(group["entry"], "GAP-001-003")
        self.assertIn("缺口台账", group["entry"])
        self.assertNotIn("GAP-", group["entry"])  # the 50 row already shows the key before it

    def test_written_entry_is_kept(self):
        group = {"claim_ids": ["C001"], "category": "existing_gap", "issue_key": "GAP-001-003", "entry": "见缺口说明"}
        fill_disposition_defaults(group, 1, self.root)
        self.assertEqual(group["entry"], "见缺口说明")


if __name__ == "__main__":
    unittest.main()
