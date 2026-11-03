"""SK-V064-014: a new CUS/ANM needs only what the item is about; stage, owner and reopen condition default."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_data_sync_regressions import SCRIPTS, governance_project  # noqa: E402
from validate_v06_project import validate_ledgers  # noqa: E402

LEDGER = "05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md"


class GovernanceDefaultTests(unittest.TestCase):
    def test_anm_created_from_its_three_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = governance_project(temp)
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPTS / "record_governance_item.py"), "--project", str(project),
                 "--kind", "ANM", "--set", "发生了什么=客户目录与整理稿的公司人数不同",
                 "--set", "为什么有风险=无法选一方作为当前规模", "--set", "现在怎么处理=本批排除规模数字",
                 "--set", "证据包入口=本页同ID详情", "--date", "2026-10-29"],
                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (project / LEDGER).read_text(encoding="utf-8")
            self.assertIn("｜客户目录与整理稿的公司人数不同", text)  # title defaults to the first human field
            self.assertIn("| 待判断 | Codex |", text)
            self.assertIn("- 重开条件：来源出现新版本或新材料", text)
            errors: list[str] = []
            validate_ledgers(project, errors)
            self.assertEqual([e for e in errors if "孤立详情" not in e], [])


if __name__ == "__main__":
    unittest.main()
