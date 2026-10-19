import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "manage-article-knowledge-v0.6.1" / "scripts"))

from template_contract import CLAIM_RECHECK_HEADER  # noqa: E402
from update_integration_status import _replace_field  # noqa: E402


class Feedback009RegressionTests(unittest.TestCase):
    def test_claim_recheck_uses_fifth_column_for_disposition(self) -> None:
        self.assertEqual(CLAIM_RECHECK_HEADER.index("本轮处置"), 4)
        self.assertEqual(CLAIM_RECHECK_HEADER.index("依据"), 5)

    def test_windows_path_is_literal_in_status_replacement(self) -> None:
        text = "- 最近一次文章级恢复：旧值\n"
        value = r"D:\Obsidian\企业知识库\P-005\task\1\current"
        updated, found = _replace_field(text, "最近一次文章级恢复", value)
        self.assertTrue(found)
        self.assertIn(value, updated)
        self.assertEqual(updated.count("最近一次文章级恢复"), 1)


if __name__ == "__main__":
    unittest.main()
