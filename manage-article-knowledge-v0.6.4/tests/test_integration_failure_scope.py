"""SK-V064-033: one article's failure does not mark the project's integration abnormal.

P-005's run ledger holds 30 such failures (a missing fact_check field, a blocked writing gate, a final
draft whose permit did not match); each set 接入状态 to 异常，待重新确认 with all three entries healthy,
and agents reading the state stopped the next article.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_integration_status import CONFIG_RELATIVE, update  # noqa: E402

ABNORMAL = "- 接入状态：异常，待重新确认"


class IntegrationFailureScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.tasks, self.finals, self.results = self.root / "写作任务", self.root / "终稿", self.root / "结果"
        for path in (self.tasks, self.finals, self.results):
            path.mkdir()
        (self.tasks / "T-1.md").write_text(
            "# 写作需求\n\n- 外部任务唯一键：T-1\n- 标题：Demo\n- 当前状态：已确认选题与简要大纲，提交知识准备\n", encoding="utf-8")
        self.config = self.root / "project" / CONFIG_RELATIVE
        self.config.parent.mkdir(parents=True)
        self.config.write_text(
            "# 写作与Faithfulness接入配置\n\n- 接入状态：已确认\n\n## 自动状态摘要\n\n"
            "- 最近检查时间：待检查\n- 最近一次接入事件：无\n- 最近一次异常：无\n- 最近一次文章级问题：无\n\n"
            f"- 写作任务入口路径：{self.tasks}\n- 可接收状态规则：当前状态=已确认选题与简要大纲，提交知识准备\n"
            f"- 终稿入口路径：{self.finals}\n- Faithfulness结果根目录：{self.results}\n", encoding="utf-8")

    def text(self) -> str:
        return self.config.read_text(encoding="utf-8")

    def fail(self, event: str, error: str, **kw) -> str:
        update(self.config.parents[1], event, article_id="ART-001", article_version="v1", error=error, **kw)
        return self.text()

    def test_article_failures_leave_the_state_and_name_the_article_problem(self):
        for event, error in (("faithfulness_import_failure", "Disposition group is missing fact_check: UG-003"),
                             ("writing_task_failure", "writing_ready门禁阻塞：H2缺口列须二选一"),
                             ("final_received_failure", "writing_ready机器回执与当前文章身份不一致")):
            with self.subTest(event=event):
                text = self.fail(event, error)
                self.assertIn("- 接入状态：已确认", text)
                self.assertIn(error, text.split("- 最近一次文章级问题：")[1])
                self.assertIn("- 最近一次异常：无", text)

    def test_a_missing_entry_marks_the_project_with_the_reason(self):
        for event, entry in (("faithfulness_import_failure", self.results), ("final_received_failure", self.finals)):
            with self.subTest(event=event):
                entry.rmdir()
                text = self.fail(event, "读取失败")
                self.assertIn(ABNORMAL, text)
                self.assertIn(f"入口不存在：{entry}", text)
                entry.mkdir()
                self.config.write_text(self.text().replace(ABNORMAL, "- 接入状态：已确认"), encoding="utf-8")

    def test_a_task_entry_whose_format_drifted_marks_the_project(self):
        (self.tasks / "T-1.md").write_text("# 写作需求\n\n- 随便写的内容\n", encoding="utf-8")
        self.assertIn(ABNORMAL, self.fail("writing_task_failure", "读取失败"))

    def test_a_caller_that_knows_the_entry_is_at_fault_still_marks_it(self):
        text = self.fail("writing_task_failure", "外部任务键重复：T-1", interface_failure=True)
        self.assertIn(ABNORMAL, text)
        self.assertIn("外部任务键重复：T-1", text.split("- 最近一次异常：")[1])


if __name__ == "__main__":
    unittest.main()
