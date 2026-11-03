"""Scenarios C01-C05: the compact merged 20 (SK-V064-011/012).  See MATRIX.md.

The agent writes only candidates, coverage, CUS/ANM rows for categories with a signal, and
exception layer rows; the Skill derives the rest and runs the same gates.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, Candidate, Scenario, run  # noqa: E402
from test_new_article import BATCH, INSERTS, SECTIONS, SIZE, article  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import task_records  # noqa: E402


class CompactRecordScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.sc = Scenario()
        self.addCleanup(self.sc.close)
        for claim in (SIZE, INSERTS):
            self.sc.add_claim(claim)

    def submit(self, art) -> str:
        submitted = self.sc.submit(art, BATCH)
        self.assertEqual(submitted.code, 0, submitted.err or submitted.out)
        return submitted.value("article_id")

    def reuse_all(self, art, article_id: str) -> None:
        for claim in {c.claim.claim_id: c.claim for c in art.candidates if not c.evidence}.values():
            reused = self.sc.reuse(BATCH, article_id, claim)
            self.assertEqual(reused.code, 0, reused.err or reused.out)

    def state(self, article_id: str) -> dict:
        return {a["article_id"]: a for a in self.sc.workflow(BATCH)["articles"]}[article_id]

    def assert_ready(self, article_id: str) -> Path:
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        self.assertEqual(self.sc.gate(article_id).value("writing_gate_status"), "ready")
        return self.sc.task(article_id)

    def test_c01_reused_claims_compact_record_is_ready(self):
        art = article()
        article_id = self.submit(art)
        self.reuse_all(art, article_id)
        self.sc.write_20(article_id, art, compact=True)
        task = self.assert_ready(article_id)  # moved to 20_等待终稿
        retrieval, audit = task_records.legacy_views(task)
        # Derived for the gates: layers, the CUS/ANM summary and the code-recorded not-involved rows.
        self.assertIn("| 客户源资料索引 | 未检索（有效Claim已覆盖全部大纲问题）", retrieval)
        self.assertIn("| CUS候选检测 | 认证 | 本篇不涉及 |", audit)
        self.assertIn("| ANM异常检测 |", audit)
        self.assertIn("| CUS候选检测 | 已逐项核对", audit)

    def test_c02_category_with_a_signal_needs_its_own_row(self):
        art = article()
        article_id = self.submit(art)
        self.reuse_all(art, article_id)
        self.sc.write_20(article_id, art, compact=True, checked=())
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("CUS候选检测/规格有信号", json.dumps(state, ensure_ascii=False))
        self.assertFalse((self.sc.task(article_id) / "writing_ready.json").exists())
        self.sc.write_20(article_id, art, compact=True, checked=("规格",))
        self.assert_ready(article_id)

    def test_c03_fresh_read_needs_a_source_layer_record(self):
        art = article()
        article_id = self.submit(art)
        for candidate in art.candidates:
            candidate.evidence = self.sc.capture(article_id, candidate.claim, "；".join(candidate.sections))
        self.sc.workflow(BATCH)
        self.sc.write_20(article_id, art, compact=True)
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("客户源资料索引没有本轮检索记录", json.dumps(state, ensure_ascii=False))
        # Searching the source index leaves a log entry, and the layer is derived from it.
        index = self.sc.project / "02_源资料"
        built = run("build_source_index.py", "--source-root", self.sc.root / "src", "--db", index / "source-index.sqlite",
                    "--ledger", index / "01_源资料台账.md", "--description", index / "源资料搜索索引说明.md")
        self.assertEqual(built.code, 0, built.err)
        searched = run("search_source_index.py", "--db", index / "source-index.sqlite", "--query", "drawer box insert")
        self.assertEqual(searched.code, 0, searched.err)
        task = self.assert_ready(article_id)
        retrieval, _ = task_records.legacy_views(task)
        self.assertIn("| 客户源资料索引 | 已检索未命中 | 本轮检索1次未采用原件：drawer box insert", retrieval)
        self.assertIn("| 客户官网 | 已检索并命中 | 读取官网正文凭证：EV-001、EV-002", retrieval)

    def test_c04_written_exception_layer_row_is_kept(self):
        fresh = Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0]])
        art = article(candidates=[fresh, Candidate("CF-002", INSERTS, ["主问题", SECTIONS[1], SECTIONS[2]])])
        article_id = self.submit(art)
        fresh.evidence = self.sc.capture(article_id, SIZE, "；".join(fresh.sections))
        self.sc.workflow(BATCH)
        self.reuse_all(art, article_id)
        self.sc.write_20(article_id, art, compact=True, layers=[
            ["客户源资料索引", "不适用（项目没有随文原件）", "源资料目录为空", "无"]])
        task = self.assert_ready(article_id)
        retrieval, _ = task_records.legacy_views(task)
        self.assertIn("| 客户源资料索引 | 不适用（项目没有随文原件） |", retrieval)

    def test_c05_uncovered_item_without_gap_entry_blocks(self):
        art = article(candidates=[Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[1]])],
                      gaps={SECTIONS[2]: "待补充"})
        article_id = self.submit(art)
        self.reuse_all(art, article_id)
        self.sc.write_20(article_id, art, compact=True)
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn(f"{SECTIONS[2]}未覆盖时须写覆盖说明与边界", json.dumps(state, ensure_ascii=False))

    def test_c06_receipt_names_each_cell_left_to_fill(self):
        art = article()
        article_id = self.submit(art)
        self.reuse_all(art, article_id)
        state = self.state(article_id)  # no 20 yet: the entry writes the skeleton
        todo = state["fill_todo"]
        lines = (self.sc.task(article_id) / "20_文章前知识审核.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(todo["count"], len(todo["cells"]))
        for cell in todo["cells"]:
            self.assertIn("待填写", lines[cell["line"] - 1])
        outline = {cell["row"]: cell for cell in todo["cells"] if cell["section"] == task_records.H_OUTLINE.lstrip("# ")}
        self.assertEqual(set(outline), {"标题", "主问题", *SECTIONS})
        self.assertEqual(outline[SECTIONS[0]]["columns"], ["覆盖状态", "候选事实ID", "覆盖说明与边界"])
        self.assertTrue(outline["标题"]["ten"].startswith("10#标题："))
        self.assertTrue(any(cell.get("text", "").startswith("- 结论：待填写") for cell in todo["cells"]))
        # Once filled, the receipt stops listing cells.
        self.sc.write_20(article_id, art, compact=True)
        self.assertNotIn("fill_todo", self.state(article_id))


if __name__ == "__main__":
    unittest.main()
