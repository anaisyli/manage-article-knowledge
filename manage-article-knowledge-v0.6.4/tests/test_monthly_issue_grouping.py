from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from monthly_issue_grouping import group_errors, render_groups, validate_report_grouping  # noqa: E402


class MonthlyIssueGroupingTests(unittest.TestCase):
    def test_same_root_cause_is_grouped_once(self) -> None:
        errors = [
            "40_已完成/ART-001/10_文章知识需求.md：缺少固定字段：标题",
            "40_已完成/ART-002/10_文章知识需求.md：缺少固定字段：大纲ID",
            "10_进行中/ART-003/15_检索与知识准备记录.md：官网正文核验缺少凭证",
        ]
        groups = group_errors(errors)
        self.assertEqual(sum(item.count for item in groups), 3)
        self.assertEqual(len([item for item in groups if item.root_cause == "模板身份/字段兼容"]), 1)
        self.assertIn("任务状态", render_groups(groups))

    def test_failed_report_requires_grouping_and_ledger_link(self) -> None:
        errors = validate_report_grouping("本次项目校验失败，共516项错误。")
        self.assertEqual(len(errors), 2)
        self.assertEqual(
            validate_report_grouping(
                "本次项目校验失败。\n\n### 本次校验错误归组\n\n"
                "| 任务状态 | 文件类型 | 根因 | 条数 |\n"
                "|---|---|---|---:|\n"
                "| 项目级 | 项目级 | 其他 | 1 |\n\n"
                "条数不是事实错误数。链接KMR-001"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
