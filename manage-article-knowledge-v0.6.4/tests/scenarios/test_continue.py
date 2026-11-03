"""S22-S29, R04-R05: what P-005-20261029-NEW-ARTICLES-01 stopped or looped on.  See MATRIX.md.

The agent stopped at an undefined integration state and a synced version entry, hand-wrote 20s
that failed on structure, followed legacy table names into the wrong section, and once the 20s
passed, recovery refused 30/35 because sections marked 无需事实支持 had no Claim.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Article, Candidate, Scenario, run  # noqa: E402
from test_new_article import BATCH, INSERTS, SIZE  # noqa: E402

# The P-005 outline shape: H1, an opening, H2s, a summary, a CTA placement line with percentages, FAQs.
SECTIONS = [
    "H1: Demo Drawer Boxes for Wholesale Brands",
    "Opening: connect a product range with packaging decisions buyers can specify.",
    "H2: Build the Visual System — compare logo and finish options.",
    "H2: Match the Insert to the Product Set — use only the listed insert options.",
    "Summary: state what to confirm before approving the sample.",
    "Two image CTAs: a related-product link near 30% and a packaging-solution link near 70%.",
    "H2: FAQs — five unnumbered H3 questions on box design.",
]
NESTED = "- " + SECTIONS[0] + "\n" + "\n".join("  - " + s for s in SECTIONS[1:])


def article(**kw) -> Article:
    return Article("SC-CONT", "Demo Drawer Boxes for Wholesale Brands", NESTED, SECTIONS, [
        Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[2], SECTIONS[4], SECTIONS[6]]),
        Candidate("CF-002", INSERTS, ["主问题", SECTIONS[3], SECTIONS[6]]),
    ], no_facts=[SECTIONS[1], SECTIONS[5]], **kw)


class ContinueScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.sc = Scenario()
        self.addCleanup(self.sc.close)
        for claim in (SIZE, INSERTS):
            self.sc.add_claim(claim)

    def submit_and_reuse(self, art: Article) -> str:
        submitted = self.sc.submit(art, BATCH)
        self.assertEqual(submitted.code, 0, submitted.err or submitted.out)
        article_id = submitted.value("article_id")
        for claim in (SIZE, INSERTS):
            self.assertEqual(self.sc.reuse(BATCH, article_id, claim).code, 0)
        return article_id

    def state(self, receipt: dict, article_id: str) -> dict:
        return {a["article_id"]: a for a in receipt["articles"]}[article_id]

    def test_s22_sections_needing_no_facts_do_not_block_30_35(self):
        art = article()
        article_id = self.submit_and_reuse(art)
        self.sc.write_20(article_id, art)
        state = self.state(self.sc.workflow(BATCH), article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        task = self.sc.task(article_id)
        usage = (task / "30_本篇知识库资料.md").read_text(encoding="utf-8").split("## 四、按大纲使用", 1)[1].split("## 五", 1)[0]
        self.assertIn(SECTIONS[5], usage)  # listed, with no facts

    def test_s23_workflow_writes_a_20_skeleton_and_never_overwrites_it(self):
        article_id = self.submit_and_reuse(article())
        state = self.state(self.sc.workflow(BATCH), article_id)
        self.assertIn("20骨架", state["next_action"])
        audit = self.sc.task(article_id) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        for label in ("标题", "主问题", *SECTIONS):
            self.assertIn(f"| {label} |", text)
        self.assertIn(f"| CF-001 | {SIZE.title} | CLM-T-DRAWER-001（复用，未回源） |", text)  # the Claim's own words
        self.assertNotIn("（通常留空", text)  # how to fill it travels in the receipt, not in the record
        categories = re.findall(r"^\| GC-\d+ \| (CUS候选检测|ANM异常检测) \| ([^|]+) \|", text, re.M)
        self.assertTrue(categories)
        from prewrite_governance import CATEGORIES
        self.assertTrue(all(category.strip() in CATEGORIES[detector] for detector, category in categories), categories)
        # Unfilled cells keep the gate closed, and a second run leaves the agent's file alone.
        self.assertIn("待填写", self.state(self.sc.workflow(BATCH), article_id)["next_action"])
        self.assertEqual(audit.read_text(encoding="utf-8"), text)
        self.assertFalse((self.sc.task(article_id) / "writing_ready.json").exists())

    def test_s24_undefined_integration_state_is_recovered_not_a_stop(self):
        config = self.sc.project / "01_工作台/40_写作与Faithfulness接入配置.md"
        config.write_text(re.sub(r"(?m)^- 接入状态：.*$", "- 接入状态：待重新确认", config.read_text(encoding="utf-8")),
                          encoding="utf-8")
        checked = run("check_integration.py", "--project", self.sc.project).json()
        self.assertIn(checked["integration_state"], {"待写作流程建立", "部分接入", "已确认", "异常，待重新确认"})
        self.assertTrue(any("待重新确认" in item for item in checked["repaired_fields"]), checked)
        self.assertIn("继续", checked["next_action"])
        self.assertNotIn("接入状态：待重新确认", config.read_text(encoding="utf-8"))

    def test_s25_version_change_says_continue(self):
        entry = self.sc.project / "01_工作台/30_版本与变更入口.md"
        entry.write_text(re.sub(r"(?m)^(- Skill文件SHA-256：).*$", r"\g<1>" + "0" * 64, entry.read_text(encoding="utf-8")),
                         encoding="utf-8")
        checked = run("check_skill_update.py", "--project", self.sc.project).json()
        self.assertTrue(checked["changed"])
        self.assertTrue(checked["next_action"].startswith("继续当前任务"), checked)
        self.assertEqual(run("check_skill_update.py", "--project", self.sc.project).json()["next_action"], "继续当前任务")

    def index(self, *args: object):
        return run("build_source_index.py", *args)

    def test_s26_source_index_rebuild_uses_the_declared_root_and_keeps_cited_ids(self):
        # P-005 2026-10-29: “重建一次来源索引” with only the project path; the agent passed the
        # knowledge base's own 02_源资料 as root and the customer originals left the index.
        brochure = self.sc.root / "src" / "Catalog 2025.md"
        brochure.write_text("# Catalog\n\nDrawer boxes can be tailored in size.\n", encoding="utf-8")
        built = self.index("--project", self.sc.project)
        self.assertEqual(built.code, 0, built.err or built.out)
        self.assertEqual(built.value("indexed_files"), "1")
        import hashlib
        source_id = "SRC-" + hashlib.sha1("catalog 2025.md".encode()).hexdigest()[:12].upper()
        db = self.sc.project / "02_源资料/source-index.sqlite"
        before = db.read_bytes()

        # The knowledge base's own folder is refused before the index is touched.
        wrong = self.index("--source-root", self.sc.project / "02_源资料", "--db", db,
                           "--ledger", self.sc.project / "02_源资料/源资料与可检索性台账.md",
                           "--description", self.sc.project / "02_源资料/源资料搜索索引说明.md")
        self.assertNotEqual(wrong.code, 0)
        self.assertIn("不能在知识库项目内部", wrong.err + wrong.out)
        other = self.sc.root / "elsewhere"
        other.mkdir()
        mismatched = self.index("--project", self.sc.project, "--source-root", other)
        self.assertIn("不一致", mismatched.err + mismatched.out)
        self.assertEqual(db.read_bytes(), before)

        # A source a current Claim cites cannot silently leave the index.
        claim = self.sc.add_claim(SIZE)
        claim.write_text(claim.read_text(encoding="utf-8") + f"\n来源：{source_id}@paragraph 1\n", encoding="utf-8")
        brochure.unlink()
        refused = self.index("--project", self.sc.project)
        self.assertNotEqual(refused.code, 0)
        self.assertIn(source_id, refused.err + refused.out)
        self.assertEqual(db.read_bytes(), before)
        allowed = self.index("--project", self.sc.project, "--allow-removed")
        self.assertEqual(allowed.code, 0, allowed.err or allowed.out)
        self.assertIn(source_id, allowed.value("removed_source_ids"))
        backup = Path(allowed.value("index_backup"))
        self.assertTrue((backup / "source-index.sqlite").is_file())

    def searched(self, audit: Path) -> None:
        """Search the source index (the script logs it) and record the website page read without a usable fact."""
        index, src = self.sc.project / "02_源资料", self.sc.root / "src"
        src.mkdir(exist_ok=True)
        built = run("build_source_index.py", "--source-root", src, "--db", index / "source-index.sqlite",
                    "--ledger", index / "01_源资料台账.md", "--description", index / "源资料搜索索引说明.md")
        self.assertEqual(built.code, 0, built.err)
        searched = run("search_source_index.py", "--db", index / "source-index.sqlite", "--query", "insert material thickness")
        self.assertEqual(searched.code, 0, searched.err)
        text = audit.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| 客户官网 |"))
        text = text.replace(row, "| 客户官网 | 已检索未命中 | 读取https://example.test/drawer-box/，没有内托材质厚度说明 | 无 |")
        audit.write_text(re.sub(r"(?m)^- 官网正文抓取凭证：.*$", "- 官网正文抓取凭证：官网正文抓取凭证.json", text), encoding="utf-8")

    def partial(self, entry: str, *, enhanced: bool = False, search: bool = True) -> tuple[str, dict]:
        """SECTIONS[3] (an H2) partly covered: insert options have a Claim, their material thickness has none."""
        art = article()
        article_id = self.submit_and_reuse(art)
        if enhanced:
            request = self.sc.task(article_id) / "10_文章知识需求.md"
            text = request.read_text(encoding="utf-8")
            request.write_text(re.sub(r"(?m)^(- 原始写作请求：.*)$", r"\1；知识准备：加强", text, count=1), encoding="utf-8")
        topic, gap_key = "不同内托材料的常见厚度范围是多少？", ""
        if "{gap}" in entry:
            gap = run("record_knowledge_gap.py", "--csv", self.sc.project / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv",
                      "--gap-key", "auto", "--topic", topic, "--article-id", article_id,
                      "--article-date", "2026-10-30", "--trigger-basis", "首篇普通缺口")
            self.assertEqual(gap.code, 0, gap.err or gap.out)
            self.assertEqual(gap.value("status"), "观察中")
            gap_key = gap.value("gap_key")
            entry = entry.replace("{gap}", gap_key)
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        if gap_key:
            text = re.sub(r"(?m)^- 本轮待调研缺口：.*$",
                          f"| GAP ID | 本轮具体公共知识问题 | 与当前大纲关系 | 本轮处理和证据 | 审核结论 |\n|---|---|---|---|---|\n"
                          f"| {gap_key} | {topic} | {SECTIONS[3]} | 观察中：首篇普通缺口，本篇不写内托厚度 | 未解决 |", text)
        row = next(line for line in text.splitlines() if line.startswith(f"| {SECTIONS[3]} | 已覆盖 |"))
        cells = row.split("|")
        cells[2], cells[4], cells[5] = " 部分覆盖 ", " 内托选项有Claim，各内托的材质厚度没有来源 ", f" {entry} "
        audit.write_text(text.replace(row, "|".join(cells)), encoding="utf-8")
        if search:
            self.searched(audit)
        return article_id, self.state(self.sc.workflow(BATCH), article_id)

    def test_s27_default_depth_refuses_narrowing_a_body_section_that_will_state_method(self):
        # SK-V064-023, P-005-ART-20261029-001: "不构成知识问题" on five H2s, method then written as fact.
        _, state = self.partial("不构成知识问题：只写已列选项")
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("缺口列须二选一", state["next_action"])

    def test_s27_default_depth_narrowed_to_questions_passes_and_30_says_so(self):
        article_id, state = self.partial("不构成知识问题：其余只列待确认问题（材质厚度请向供应商确认）")
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        missing = (self.sc.task(article_id) / "30_本篇知识库资料.md").read_text(encoding="utf-8").split("## 六、", 1)[1]
        self.assertIn(SECTIONS[3], missing)
        self.assertIn("其余只写成请读者或供应商确认的问题", missing)

    def test_s27_default_depth_registered_gap_passes_without_research(self):
        # A first ordinary gap is 观察中: recorded in 三 only, no external research forced.
        _, state = self.partial("{gap}")
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))

    def test_s27_invented_gap_id_is_refused(self):
        _, state = self.partial("GAP-T-999")
        self.assertIn("GAP-T-999不在项目台账中", state["next_action"])

    def test_s27_written_search_rows_need_a_trace_when_a_body_section_is_open(self):
        # 001 wrote 已检索 for the source index with no search logged, and “复用Claim” for the website.
        _, state = self.partial("不构成知识问题：其余只列待确认问题（材质厚度请向供应商确认）", search=False)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("客户源资料索引写了", state["next_action"])
        self.assertIn("客户官网写了", state["next_action"])

    def test_s27_enhanced_depth_needs_cus_or_gap_for_a_partial_section(self):
        _, state = self.partial("不构成知识问题：只写已列选项", enhanced=True)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("须写CUS/GAP/MAT/ANM编号（本篇为“知识准备：加强”）", state["next_action"])

    def test_s28_fresh_read_does_not_ask_a_url_for_sections_without_website_facts(self):
        # P-005-ART-20261029-002: one page read this run; the opening, CTA and reused-Claim sections took no
        # website fact, yet the legacy view asked each of them for a final URL and the 20 could not pass.
        art = article()
        submitted = self.sc.submit(art, BATCH)
        self.assertEqual(submitted.code, 0, submitted.err or submitted.out)
        article_id = submitted.value("article_id")
        fresh = art.candidates[0]
        fresh.evidence = self.sc.capture(article_id, fresh.claim, "；".join(fresh.sections))
        self.sc.workflow(BATCH)
        self.assertEqual(self.sc.reuse(BATCH, article_id, INSERTS).code, 0)
        self.sc.write_20(article_id, art)
        state = self.state(self.sc.workflow(BATCH), article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))

    def test_s29_uncovered_section_narrowed_by_the_20_gets_30_and_is_named_in_its_sixth_part(self):
        # P-005-ART-20261029-002: an H2 the 20 marked 未覆盖 ("不构成知识问题：只列采购前待确认问题") made
        # recovery refuse 30/35 because the section mapped no Claim.
        art = article()
        article_id = self.submit_and_reuse(art)
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith(f"| {SECTIONS[3]} | 已覆盖 |"))
        boundary = "不陈述内托能力，只作询问供应商的核对项"
        cells = ["", f" {SECTIONS[3]} ", " 未覆盖 ", " 无 ", f" {boundary} ", " 不构成知识问题：只列采购前待确认问题 ",
                 " 有明确边界 ", " 不写该节事实 ", ""]
        audit.write_text(text.replace(row, "|".join(cells)), encoding="utf-8")
        self.searched(audit)
        state = self.state(self.sc.workflow(BATCH), article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        material = (self.sc.task(article_id) / "30_本篇知识库资料.md").read_text(encoding="utf-8")
        missing = material.split("## 六、", 1)[1]
        self.assertIn(SECTIONS[3], missing)
        self.assertIn(boundary, missing)

    def test_r04_missing_outline_row_names_the_pr2_section_once(self):
        art = article()
        article_id = self.submit_and_reuse(art)
        missing = SECTIONS[1]
        written = Article(art.key, art.title, art.outline, [s for s in SECTIONS if s != missing], art.candidates,
                          no_facts=[SECTIONS[5]])
        self.sc.write_20(article_id, written)
        action = self.state(self.sc.workflow(BATCH), article_id)["next_action"]
        self.assertEqual(action.count(f"三、大纲逐项覆盖与审核未逐项对应10中的“{missing}”"), 1, action[-900:])
        for legacy in ("大纲逐项检索与候选事实覆盖", "大纲知识覆盖检查", "知识准备充分性复核"):
            self.assertNotIn(legacy, action)

    def test_r05_invented_category_lists_the_standard_names(self):
        art = article()
        article_id = self.submit_and_reuse(art)
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        audit.write_text(text.replace("| CUS候选检测 | 客户能力 |", "| CUS候选检测 | 规格/材料/内托 |", 1), encoding="utf-8")
        action = self.state(self.sc.workflow(BATCH), article_id)["next_action"]
        self.assertIn("未知检测类别：CUS候选检测/规格/材料/内托", action)
        self.assertIn("客户能力、规格、认证、案例、商业条件、公开授权", action)


if __name__ == "__main__":
    unittest.main()
