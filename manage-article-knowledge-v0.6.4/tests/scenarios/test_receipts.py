"""R01-R03: receipts must not steer an agent into the wrong action.  See MATRIX.md.

Each one reproduces a loop from the P-005-20261028 run; all three were fixed in
v0.6.4 (SK-V064-006 to 008) and now guard against the loop coming back.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Candidate, Scenario, run  # noqa: E402
from handoff_contract import current_version  # noqa: E402
from test_new_article import BATCH, INSERTS, SECTIONS, SIZE, article  # noqa: E402


class ReceiptScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.sc = Scenario()
        self.addCleanup(self.sc.close)
        for claim in (SIZE, INSERTS):
            self.sc.add_claim(claim)

    def blocked_article(self) -> tuple[str, dict]:
        """20 is written but one section has no Claim, so 30/35 cannot be generated."""
        art = article(candidates=[Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[1]])],
                      gaps={SECTIONS[2]: "内托材料比较没有已核验来源"})
        article_id = self.sc.submit(art, BATCH).value("article_id")
        self.sc.reuse(BATCH, article_id, SIZE)
        self.sc.write_20(article_id, art)
        receipt = self.sc.workflow(BATCH)
        return article_id, {a["article_id"]: a for a in receipt["articles"]}[article_id]

    def test_r01_missing_35_is_reported_once_not_per_section(self):
        # Seen: one "已覆盖但Claim未完整进入当前35" per section while 35 did not exist; the agent
        # then downgraded six sections to 部分覆盖 to make the errors go away.
        # 35 stays missing because the 20 cites a Claim never registered for this article (a 未覆盖
        # section no longer keeps 35 from being generated, SK-V064-022).
        art = article()
        article_id = self.sc.submit(art, BATCH).value("article_id")
        self.sc.reuse(BATCH, article_id, SIZE)
        self.sc.write_20(article_id, art)
        state = {a["article_id"]: a for a in self.sc.workflow(BATCH)["articles"]}[article_id]
        self.assertIn("缺少文件：35_写作素材来源索引.md", state["next_action"])
        self.assertNotIn("Claim未完整进入当前35", state["next_action"])

    def test_r02_section_name_as_question_id_explains_where_mapping_goes(self):
        # Seen: five record_claim_reuse calls with section names as --question-id, all refused.
        article_id = self.sc.submit(article(), BATCH).value("article_id")
        refused = run("record_claim_reuse.py", "--project", self.sc.project, "--batch-id", BATCH,
                      "--article-id", article_id, "--claim-id", SIZE.claim_id,
                      "--question-id", SECTIONS[1],
                      "--basis", f"{SIZE.title}的有效记录覆盖本篇对应问题，范围限于{SIZE.obj}")
        message = refused.out + refused.err
        self.assertIn("问题ID无效", message)
        self.assertIn("按文章登记", message)
        self.assertIn("省略--question-id", message)
        self.assertIn("20", message)

    def test_r03_blocked_receipt_names_the_next_command(self):
        # Seen: eight bare reruns of run_knowledge_workflow.py and a gate call with the wrong contract version.
        article_id, state = self.blocked_article()
        command = re.search(r'python\S*\s+(?:-X utf8\s+)?"?\S*run_knowledge_workflow\.py"?\s+(--.*)$', state["next_action"])
        self.assertIsNotNone(command, state["next_action"][-300:])
        self.assertIn(f'--project "{self.sc.project}"', command.group(1))
        self.assertIn(f"--batch-id {BATCH}", command.group(1))
        gate = self.sc.gate(article_id)
        self.assertEqual(gate.value("writing_gate_status"), "blocked")
        self.assertRegex(gate.value("next_action"),
                         rf'issue_writing_ready\.py"?\s+--handoff-contract-version {re.escape(current_version())}\s'
                         rf'.*--article-id {re.escape(article_id)}')


    def test_r07_source_collection_tells_the_current_agent_to_keep_going(self):
        # Seen (P-005-ART-20261030-001): next_owner=manage-article-knowledge with the executor rule cut from the
        # printed receipt; the writing agent reported "知识准备尚未完成" and stopped at source_collection.
        submitted = self.sc.submit(article(), BATCH)
        self.assertIn("这不是停下", submitted.value("writer_lock"))
        receipt = self.sc.workflow(BATCH)
        self.assertEqual(receipt["workflow_state"], "source_collection")
        self.assertFalse(receipt["terminal"])
        self.assertIn("由当前Agent立即执行next_action", receipt["executor"])
        self.assertIn("record_claim_reuse.py", receipt["next_action"])

    def test_r06_finalize_names_the_request_command_and_a_wrong_index_is_explained(self):
        # Seen (P-005-ART-20261029-002): 02_源资料/source-index.sqlite passed as --source-index, refused only
        # with "Cannot decode text file".  finalize now prints the whole --task-dir command.
        art = article()
        article_id = self.sc.submit(art, BATCH).value("article_id")
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art)
        self.sc.workflow(BATCH)
        final = self.sc.root / "ws" / "终稿" / "demo-final.md"
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_text("# Demo Drawer Boxes\n\nThis drawer box can be tailored in size.\n", encoding="utf-8")
        finalized = run("writing_bridge.py", "finalize", "--handoff-contract-version", current_version(),
                        "--project", self.sc.project, "--final-path", final, "--article-id", article_id)
        self.assertEqual(finalized.value("handoff_event"), "writing_completed", finalized.err or finalized.out)
        task = self.sc.task(article_id)
        self.assertIn(f'create_faithfulness_record.py" --task-dir "{task}" --handoff-contract-version {current_version()}',
                      finalized.value("next"))
        sqlite = self.sc.project / "02_源资料" / "source-index.sqlite"
        sqlite.write_bytes(b"SQLite format 3\x00" + bytes(range(256)))
        wrong = run("create_faithfulness_record.py", "--article", task / "40_最终文章.md",
                    "--knowledge", task / "30_本篇知识库资料.md", "--source-index", sqlite,
                    "--receipt", task / "50_文章知识使用与Faithfulness记录.md",
                    "--handoff-contract-version", current_version())
        self.assertNotEqual(wrong.code, 0)
        self.assertIn("35_写作素材来源索引.md", wrong.out + wrong.err)
        self.assertIn("--task-dir", wrong.out + wrong.err)
        # The fixture project configures no result root (P-005 does, and --task-dir then derives it).
        made = run("create_faithfulness_record.py", "--task-dir", task, "--handoff-contract-version", current_version(),
                   "--result-dir", self.sc.root / "fr" / "P-T" / article_id / "v1")
        self.assertEqual(made.code, 0, made.err or made.out)
        self.assertEqual(self.sc.task(article_id).parent.name, "30_等待Faithfulness")
        self.assertTrue((self.sc.task(article_id) / "50_文章知识使用与Faithfulness记录.md").is_file())

if __name__ == "__main__":
    unittest.main()
