"""The last SKFB detail ends at the next ## section, not at the end of the ledger."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import manage_skill_feedback  # noqa: E402
import validate_v06_project  # noqa: E402

LEDGER = (
    "# Skill反馈台账\n\n## 当前反馈\n\n"
    "| SKFB ID | 提出来源 | 类型 | 通俗说明 | 复现依据 | 当前阶段 | 维护负责人 | 关联项目对象入口 | 最近更新 |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
    "| DEMO-SKFB-001 | 自动 | 工具兼容 | 深层路径失败 | 复现 | 已修复，待项目验证 | 负责人 | [[文件]] | 2026-08-21 |\n\n"
    "## 反馈详情\n\n### DEMO-SKFB-001｜深层路径失败\n\n"
    "- 当前阶段：已修复，待项目验证\n- 下一步由谁做：Codex\n- 关闭条件：自测和项目验证通过\n- 重开条件：原问题再次复现\n"
    "- 最近更新：2026-08-21\n\n"
    "## 最近Skill版本检测\n\n- 检测时间：2026-08-21T00:00:00+08:00\n- 开放反馈：1项（DEMO-SKFB-001）\n"
)


class LastDetailSectionTests(unittest.TestCase):
    def test_closing_the_last_detail_keeps_the_status_block_inside_it(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "01_Skill反馈台账.md"
            path.write_text(LEDGER, encoding="utf-8")
            manage_skill_feedback.transition(path, "DEMO-SKFB-001", "已关闭", "原问题不再复现", "无", "通过", "通过", "2026-08-22")
            text = path.read_text(encoding="utf-8")
        status_at = text.index("#### 自动状态检查")
        trailing_at = text.index("## 最近Skill版本检测")
        self.assertLess(status_at, trailing_at)
        self.assertTrue(text[:trailing_at].endswith("同一事务同步。\n\n"))
        self.assertNotIn("关闭依据", text[trailing_at:])
        _, _, block = manage_skill_feedback.detail_block(text, "DEMO-SKFB-001")
        self.assertIn("- 关闭依据：原问题不再复现", block)
        self.assertNotIn("最近Skill版本检测", block)

    def test_validator_detail_stops_at_the_trailing_section(self):
        misplaced = LEDGER + "\n- 关闭依据：写在文末小节里的依据\n"
        self.assertNotIn("关闭依据", validate_v06_project.detail_block(misplaced, "DEMO-SKFB-001"))
        self.assertNotIn("最近Skill版本检测", manage_skill_feedback.detail_block(misplaced, "DEMO-SKFB-001")[2])


if __name__ == "__main__":
    unittest.main()
