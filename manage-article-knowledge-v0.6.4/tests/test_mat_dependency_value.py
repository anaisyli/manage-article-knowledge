"""SK-V064-022: the PR-2 view derives MAT依赖处理 from the 五 MAT table when the header holds a description.

P-005-ART-20261029-002 wrote "已处理并核对；仅采用页3、4型号标签…" in the header; delivery accepts only
无/已决定, so a fully decided MAT kept the article from writing_ready.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from task_records import meta_values  # noqa: E402

ROW = "| P-005-MAT-002 | SRC-8F9F4199F530 | 同一目录册两种标签 | {decision} | 页3、4 | 型号标签一致 | Codex | {state} |"


def record(header: str, rows: list[str]) -> str:
    table = ("| MAT ID | 候选SRC ID | 关系/处理问题 | 决定 | 选取或排除范围 | 决定依据 | 决定方 | 当前状态 |\n|---|---|---|---|---|---|---|---|\n"
             + "\n".join(rows)) if rows else "- MAT依赖与资料选择：无"
    return (f"# 知识准备与文章前审核\n\n- 知识准备记录协议：PR-2\n- MAT依赖处理：{header}\n\n"
            f"## 五、缺口与特殊资料\n\n### MAT依赖与资料选择\n\n{table}\n\n## 六、结论说明\n")


class MatDependencyValueTests(unittest.TestCase):
    def value(self, header: str, rows: list[str]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            return meta_values(Path(tmp), record(header, rows))[0]["MAT依赖处理"]

    def test_description_with_decided_rows_is_decided(self):
        rows = [ROW.format(decision="限定范围采用", state="本篇处理完成")]
        self.assertEqual(self.value("已处理并核对；仅采用页3、4型号标签，页6异常范围排除", rows), "已决定")

    def test_any_pending_row_keeps_it_pending(self):
        rows = [ROW.format(decision="限定范围采用", state="本篇处理完成"), ROW.format(decision="待决定", state="待人工确认")]
        self.assertEqual(self.value("已处理", rows), "待决定")

    def test_no_rows_is_none(self):
        self.assertEqual(self.value("", []), "无")

    def test_controlled_value_is_kept(self):
        rows = [ROW.format(decision="限定范围采用", state="本篇处理完成")]
        self.assertEqual(self.value("待决定", rows), "待决定")


if __name__ == "__main__":
    unittest.main()
