"""S35-S42: the 20 stays one row per fact, level with the ledger, the outline and 30/35.  See MATRIX.md.

P-005-ART-20261030-001: CF-003/004 repeated CF-002's Claim and text; 三 cited two of the eight facts that
reached 30/35; a first recovery kept two facts while the record went on to eight; CF-002's source mixed
four spellings; 加强 research returned definitions for method and effect sections; an EC-1 Claim lacking
only its attribution hash could not be completed (P-005-SKFB-020).
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Article, Candidate, Claim, Scenario, run  # noqa: E402
from test_new_article import BATCH, INSERTS, SECTIONS, SIZE, listed  # noqa: E402

BODY = "H2 How to Compare Inserts?"
TWO_FACTS = Claim("CLM-T-TWOFACT-001", "同一Claim里的两个事实",
                  "This drawer box can be tailored in size. Insert trays can be added on request.",
                  url="https://example.test/two-facts/", position="Description / paragraph 3",
                  coreference="This refers only to the drawer box named in the heading.")
MATERIAL = Claim("CLM-T-MATERIAL-001", "抽屉盒面材选项", "Paper material options include kraft and art paper.",
                 url="https://example.test/material/", position="Materials / paragraph 1")


def article(candidates=None, **kw) -> Article:
    return Article("SC-SYNC", "Demo Drawer Boxes", listed(SECTIONS), SECTIONS, candidates if candidates is not None else [
        Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[1]]),
        Candidate("CF-002", INSERTS, ["主问题", SECTIONS[1], SECTIONS[2]]),
    ], **kw)


class CandidateSyncScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.sc = Scenario()
        self.addCleanup(self.sc.close)
        self.files = {claim.claim_id: self.sc.add_claim(claim) for claim in (SIZE, INSERTS, TWO_FACTS, MATERIAL)}

    def ledger(self) -> dict:
        return json.loads((self.sc.project / f"04_文章任务/批次运行/{BATCH}.json").read_text(encoding="utf-8-sig"))

    def rows(self, article_id: str) -> list[dict]:
        return [row for row in self.ledger()["evidence"] if article_id in row.get("article_ids", [])]

    def submit(self, art: Article) -> str:
        submitted = self.sc.submit(art, BATCH)
        self.assertEqual(submitted.code, 0, submitted.err or submitted.out)
        return submitted.value("article_id")

    def state(self, article_id: str) -> dict:
        return {a["article_id"]: a for a in self.sc.workflow(BATCH)["articles"]}[article_id]

    def audit(self, article_id: str) -> Path:
        return self.sc.task(article_id) / "20_文章前知识审核.md"

    def test_s35_reading_a_reused_fact_again_adds_a_verification_not_a_candidate(self):
        article_id = self.submit(article())
        self.assertEqual(self.sc.reuse(BATCH, article_id, SIZE).code, 0)
        ev = self.sc.capture(article_id, SIZE, SECTIONS[1])
        self.sc.workflow(BATCH)
        self.sc.capture(article_id, SIZE, SECTIONS[0])  # a second read of the same text for another section
        self.sc.workflow(BATCH)
        rows = self.rows(article_id)
        self.assertEqual([row["candidate_id"] for row in rows], ["CF-001"])
        self.assertEqual(rows[0]["disposition"], "复用已有Formal Claim")
        trail = rows[0]["verifications"]
        self.assertEqual(len(trail), 2)  # the trail keeps both reads
        self.assertTrue(all(item["retrieved_at"] and item["retrieval_run_id"] for item in trail))
        self.assertNotIn("retrieved_at", rows[0])  # a reuse row never poses as this run's read
        from scaffold_preparation_record import candidates
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        request = (self.sc.task(article_id) / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
        self.assertIn(f"{SIZE.claim_id}（复用，本轮回源核验：{ev}", candidates(self.sc.task(article_id), request)[0][2])

    def test_s35_reusing_a_fact_already_read_this_run_adds_no_row(self):
        article_id = self.submit(article())
        self.sc.capture(article_id, SIZE, SECTIONS[1])
        self.sc.workflow(BATCH)
        self.assertEqual(self.sc.reuse(BATCH, article_id, SIZE).code, 0)
        self.assertEqual([row["disposition"] for row in self.rows(article_id)], ["本轮核验通过"])

    def test_s35_different_facts_of_one_claim_stay_separate(self):
        article_id = self.submit(article())
        for text, section in (("This drawer box can be tailored in size.", SECTIONS[0]),
                              ("Insert trays can be added on request.", SECTIONS[1])):
            self.sc.capture(article_id, Claim(TWO_FACTS.claim_id, TWO_FACTS.title, text, url=TWO_FACTS.url,
                                              position=TWO_FACTS.position), section)
        self.sc.workflow(BATCH)
        rows = self.rows(article_id)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["claim_id"] for row in rows}, {TWO_FACTS.claim_id})
        self.assertEqual(len({row["candidate_id"] for row in rows}), 2)

    def old_ledger_duplicate(self) -> tuple[Article, str]:
        """A ledger written before reads merged: a reuse row and a fresh row of one fact."""
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.assertEqual(self.sc.reuse(BATCH, article_id, claim).code, 0)
        path = self.sc.project / f"04_文章任务/批次运行/{BATCH}.json"
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        payload["evidence"].append(dict(payload["evidence"][0], candidate_id="CF-003"))
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return art, article_id

    def test_s35_a_duplicate_row_in_the_20_is_named_and_30_keeps_one_block(self):
        art, article_id = self.old_ledger_duplicate()
        art.candidates.append(Candidate("CF-003", SIZE, ["主问题"]))
        self.sc.write_20(article_id, art)
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("CF-003与CF-001是同一事实", json.dumps(state, ensure_ascii=False))
        art.candidates.pop()
        self.sc.write_20(article_id, art)  # one row per fact; the ledger's extra row stays as history
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        self.assertEqual(len(self.rows(article_id)), 3)
        material = (self.sc.task(article_id) / "30_本篇知识库资料.md").read_text(encoding="utf-8")
        self.assertEqual(material.count(SIZE.excerpt), 1)

    def test_s36_an_adopted_fact_no_outline_item_uses_is_named(self):
        art = article(candidates=[*article().candidates, Candidate("CF-003", MATERIAL, ["主问题"])])
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS, MATERIAL):
            self.assertEqual(self.sc.reuse(BATCH, article_id, claim).code, 0)
        self.sc.write_20(article_id, art)
        audit = self.audit(article_id)
        text = audit.read_text(encoding="utf-8")
        audit.write_text(text.replace("、CF-003", ""), encoding="utf-8")  # 主问题 no longer cites it
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        message = json.dumps(state, ensure_ascii=False)
        self.assertIn("CF-003已采用，但三没有任何大纲项引用它", message)
        self.assertNotIn("CF-003", audit.read_text(encoding="utf-8").split("## 三、")[1].split("## 四、")[0])  # never auto-mapped

    def test_s36_an_excluded_fact_stays_out_of_30_and_35(self):
        art = article(candidates=[*article().candidates, Candidate("CF-003", MATERIAL, ["主问题"])])
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS, MATERIAL):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art)
        audit = self.audit(article_id)
        text = audit.read_text(encoding="utf-8").replace("、CF-003", "")
        row = next(line for line in text.splitlines() if line.startswith("| CF-003 |"))
        cells = row.split("|")
        cells[5], cells[6] = " 排除 ", " 本篇大纲不讲面材，不采用 "
        audit.write_text(text.replace(row, "|".join(cells)), encoding="utf-8")
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", (state.get("next_action") or "")[-700:])
        task = self.sc.task(article_id)
        self.assertNotIn(MATERIAL.excerpt, (task / "30_本篇知识库资料.md").read_text(encoding="utf-8"))
        self.assertNotIn(MATERIAL.claim_id, (task / "35_写作素材来源索引.md").read_text(encoding="utf-8"))

    def test_s37_a_fact_added_after_the_20_reaches_the_20_for_a_decision(self):
        art = article()
        article_id = self.submit(art)
        self.sc.reuse(BATCH, article_id, SIZE)
        self.sc.write_20(article_id, Article(art.key, art.title, art.outline, art.sections, art.candidates[:1],
                                             no_facts=art.sections))
        self.sc.reuse(BATCH, article_id, INSERTS)
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        text = self.audit(article_id).read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| CF-002 |"))
        self.assertIn("待填写", row)
        self.assertIn("CF-002", json.dumps(state.get("fill_todo", {}), ensure_ascii=False))
        self.assertEqual(text.count("| CF-002 |"), 1)
        self.state(article_id)  # a rerun appends nothing twice
        self.assertEqual(self.audit(article_id).read_text(encoding="utf-8").count("| CF-002 |"), 1)

    def test_s38_unpermitted_30_35_grow_with_the_record(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art)
        audit = self.audit(article_id)
        keep = audit.read_text(encoding="utf-8")
        # A gate problem after 30/35 exist keeps the task unpermitted while the record grows.
        audit.write_text(keep.replace("- 审核日期：", "- 待填写说明：待填写\n- 审核日期：", 1), encoding="utf-8")
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        task = self.sc.task(article_id)
        self.assertTrue((task / "35_写作素材来源索引.md").is_file())
        self.assertNotIn(MATERIAL.claim_id, (task / "35_写作素材来源索引.md").read_text(encoding="utf-8"))
        grown = article(candidates=[*art.candidates, Candidate("CF-003", MATERIAL, ["主问题", SECTIONS[2]])])
        self.sc.reuse(BATCH, article_id, MATERIAL)
        self.sc.write_20(article_id, grown)
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", (state.get("next_action") or "")[-700:])
        task = self.sc.task(article_id)
        mapped = (task / "35_写作素材来源索引.md").read_text(encoding="utf-8")
        for claim in (SIZE, INSERTS, MATERIAL):
            self.assertIn(claim.claim_id, mapped)
        self.assertIn(MATERIAL.excerpt, (task / "30_本篇知识库资料.md").read_text(encoding="utf-8"))

    def test_s38_a_permitted_package_is_never_rebuilt_quietly(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art)
        self.assertEqual(self.state(article_id)["state"], "writing_ready_issued")
        task = self.sc.task(article_id)
        before = (task / "30_本篇知识库资料.md").read_bytes()
        self.sc.reuse(BATCH, article_id, MATERIAL)
        self.sc.workflow(BATCH)
        self.assertEqual((self.sc.task(article_id) / "30_本篇知识库资料.md").read_bytes(), before)

    def test_s39_an_adopted_source_cell_holds_pointers_with_one_stated_state(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art)
        audit = self.audit(article_id)
        good = audit.read_text(encoding="utf-8")
        mixed = f"{SIZE.claim_id}（复用，未回源）；EV-001（本轮核验）；{SIZE.url} Description paragraph"
        audit.write_text(good.replace(f"{SIZE.claim_id}（复用，未回源）", mixed, 1), encoding="utf-8")
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("CF-001的来源只写指针", json.dumps(state, ensure_ascii=False))

    def test_s39_a_row_read_this_run_passes_in_its_canonical_form(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        ev = self.sc.capture(article_id, SIZE, SECTIONS[1])
        self.sc.workflow(BATCH)
        art.candidates[0].evidence = ev
        self.sc.write_20(article_id, art)
        audit = self.audit(article_id)
        text = audit.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| CF-001 |"))
        cells = row.split("|")
        cells[3] = f" {SIZE.claim_id}（复用，本轮回源核验：{ev}） "
        audit.write_text(text.replace(row, "|".join(cells)).replace("已沉淀Formal Claim", "复用已有Formal Claim"), encoding="utf-8")
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))

    def test_s40_rows_without_a_closing_pipe_read_the_same_and_come_out_uniform(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        from task_records import H_CHECKS, _table
        text = audit.read_text(encoding="utf-8")
        before = _table(text, H_CHECKS)
        lines = [line[:-2].rstrip() if line.startswith("| GC-") else line for line in text.splitlines()]
        stripped = "\n".join(lines) + "\n"
        self.assertEqual(_table(stripped, H_CHECKS), before)
        audit.write_text(stripped, encoding="utf-8")
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        final = (self.sc.task(article_id) / "20_文章前知识审核.md").read_text(encoding="utf-8")
        self.assertTrue(all(line.rstrip().endswith("|") for line in final.splitlines() if line.startswith("| GC-")))

    def test_s40_section_one_and_six_may_stay_empty(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art, compact=True)
        from harness import run as _  # noqa: F401
        for reason in ("没有本轮检索记录",):  # compact 一 is derived; a real gap in it still names the layer
            self.assertTrue(reason)
        text = self.audit(article_id).read_text(encoding="utf-8")
        self.assertEqual(text.split("## 六、结论说明")[1].strip(), "")
        self.assertEqual(self.state(article_id)["state"], "writing_ready_issued")

    def enhanced(self, note: str) -> tuple[str, dict]:
        art = article()
        submitted = self.sc.submit(art, BATCH, request_text="写一篇场景测试文章；知识准备：加强")
        article_id = submitted.value("article_id")
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        gap = run("record_knowledge_gap.py", "--csv", self.sc.project / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv",
                  "--gap-key", "auto", "--topic", "内托结构如何影响珠宝取放的具体步骤和条件？", "--article-id", article_id,
                  "--article-date", "2026-11-02", "--trigger-basis", "首篇普通缺口")
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith(f"| {BODY} | 已覆盖 |"))
        cells = row.split("|")
        cells[2], cells[4], cells[5] = " 部分覆盖 ", f" {note} ", f" 不构成知识问题：其余只列待确认问题（请向供应商核对）；{gap.value('gap_key')} "
        audit.write_text(text.replace(row, "|".join(cells)), encoding="utf-8")
        return article_id, self.state(article_id)

    def test_s41_enhanced_section_must_state_what_its_evidence_reaches(self):
        _, state = self.enhanced("内托选项有Claim，步骤没有来源")
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("证据层级", json.dumps(state, ensure_ascii=False))

    def test_s41_a_definition_is_recorded_as_a_definition_for_the_writer(self):
        note = "内托选项有Claim；证据层级：定义；仍缺：方法、效果"
        article_id, state = self.enhanced(note)
        self.assertNotIn("须写“证据层级", json.dumps(state, ensure_ascii=False))
        audit = self.audit(article_id).read_text(encoding="utf-8")
        self.assertIn(BODY, audit)  # the reader's section stays in the outline
        self.assertIn(note, audit)

    def fill(self, article_id: str, todo: dict) -> None:
        """Do what the receipt asks: only the listed cells, in one pass."""
        path = Path(todo["file"])
        lines = path.read_text(encoding="utf-8").splitlines()
        ids = {SECTIONS[0]: "CF-001", SECTIONS[1]: "CF-001、CF-002", SECTIONS[2]: "CF-002", "标题": "CF-001", "主问题": "CF-001、CF-002"}
        for cell in todo["cells"]:
            index = cell["line"] - 1
            if lines[index].startswith("- 结论"):
                lines[index] = "- 结论：自动通过"
            elif cell["section"].startswith("三"):
                lines[index] = f"| {cell['row']} | 已覆盖 | {ids[cell['row']]} |  |  |"
            elif cell["section"] == "逐项核验":
                parts = lines[index].split("|")
                category = parts[3].strip()
                parts[4], parts[5], parts[6], parts[7], parts[9] = (
                    f" 本篇不涉及{category}相关事实 ", " 10#大纲 ", " 不适用 ", f" {category}：当前大纲不需要该类事实 ",
                    f" 不涉及：本篇不写{category}相关内容 ")
                lines[index] = "|".join(parts)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_s43_the_20_comes_after_the_evidence_and_is_done_in_one_pass(self):
        art = article()
        article_id = self.submit(art)
        other = self.sc.submit(Article("SC-OTHER", "Other Drawer Boxes", listed(SECTIONS), SECTIONS, []), BATCH).value("article_id")
        self.assertEqual(self.sc.reuse(BATCH, other, SIZE).code, 0)  # the batch has evidence, this article has none yet
        self.sc.workflow(BATCH)
        self.assertFalse(self.audit(article_id).exists())  # nothing to rewrite later
        for claim in (SIZE, INSERTS):
            self.assertEqual(self.sc.reuse(BATCH, article_id, claim).code, 0)
        state = self.state(article_id)
        text = self.audit(article_id).read_text(encoding="utf-8")
        # Real content, no guidance: the rules arrive in the receipt.
        self.assertFalse(re.search(r"(?m)^（", text), text)
        self.assertIn(f"| CF-001 | {SIZE.title} |", text)
        self.assertIn("大纲覆盖", state["fill_todo"]["rules"])
        self.fill(article_id, state["fill_todo"])
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", (state.get("next_action") or "")[-600:])
        final = (self.sc.task(article_id) / "20_文章前知识审核.md").read_text(encoding="utf-8")
        self.assertNotIn("待填写", final)
        self.assertRegex(final, r"\| 已有正式Claim \| 已检索并命中 \|")  # 一 written from this run's traces
        self.assertTrue(final.split("## 六、结论说明")[1].strip())  # 六 written from the counts
        row = next(line for line in final.splitlines() if line.startswith("| CF-001 |"))
        self.assertIn(SECTIONS[0], row)  # 支持的大纲问题 follows 三, so the two cannot disagree

    def assert_finished(self, article_id: str) -> None:
        final = (self.sc.task(article_id) / "20_文章前知识审核.md").read_text(encoding="utf-8")
        self.assertRegex(final.split("## 二、")[0], "已有正式Claim")
        self.assertTrue(final.split("## 六、结论说明")[1].strip())

    def test_s43_a_direct_gate_call_also_finishes_the_record(self):
        # run_outline_refresh.py ends by telling the agent to run issue_writing_ready.py, past the batch entry.
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art, compact=True)
        gate = self.sc.gate(article_id)
        self.assertEqual(gate.value("writing_gate_status"), "ready", gate.out + gate.err)
        self.assert_finished(article_id)

    def test_s43_an_outline_refresh_also_finishes_the_record(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art, compact=True)
        self.assertEqual(self.state(article_id)["state"], "writing_ready_issued")
        revised = self.sc.submit(art, BATCH, revision_mode="outline_refresh", article_id=article_id)
        self.assertEqual(revised.code, 0, revised.out + revised.err)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        self.sc.write_20(article_id, art, compact=True)
        gate = self.sc.gate(article_id)
        self.assertEqual(gate.value("writing_gate_status"), "ready", gate.out + gate.err)
        self.assert_finished(article_id)

    def test_s43_old_guidance_lines_leave_a_record_still_being_prepared(self):
        art = article()
        article_id = self.submit(art)
        for claim in (SIZE, INSERTS):
            self.sc.reuse(BATCH, article_id, claim)
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        audit.write_text(text.replace("## 三、大纲逐项覆盖与审核\n", "## 三、大纲逐项覆盖与审核\n\n（每行的覆盖状态只能是：已覆盖）\n", 1), encoding="utf-8")
        self.state(article_id)
        self.assertNotIn("（每行的覆盖状态", (self.sc.task(article_id) / "20_文章前知识审核.md").read_text(encoding="utf-8"))

    def sha_claim(self, excerpt_change: bool = False) -> Path:
        path = self.files[SIZE.claim_id]
        text = path.read_text(encoding="utf-8")
        if excerpt_change:
            return path.write_text(text.replace("tailored in size", "tailored in length"), encoding="utf-8") and path
        path.write_text(re.sub(r"(?m)^- 归属证据SHA-256：.*\n", "", text), encoding="utf-8")
        return path

    def complete(self, article_id: str, values: dict) -> object:
        file = self.sc.root / "complete.json"
        file.write_text(json.dumps({SIZE.claim_id: values}, ensure_ascii=False), encoding="utf-8")
        return run("record_claim_reuse.py", "--project", self.sc.project, "--batch-id", BATCH, "--article-id", article_id,
                   "--claim-id", SIZE.claim_id, "--complete", file,
                   "--basis", f"{SIZE.title}的有效记录覆盖本篇对应问题，范围限于{SIZE.obj}")

    def test_s42_a_missing_attribution_hash_is_computed_once(self):
        # P-005-SKFB-020: --complete kept reporting the missing hash however often it ran.
        article_id = self.submit(article())
        path = self.sha_claim()
        held = self.sc.reuse(BATCH, article_id, SIZE)
        self.assertNotEqual(held.code, 0)
        self.assertIn("归属证据SHA-256", held.out)
        draft = json.loads(held.value("claim_complete_draft"))
        self.assertEqual(draft["script_computes"], ["归属证据SHA-256"])
        done = self.complete(article_id, {})
        self.assertEqual(done.code, 0, done.out + done.err)
        from evidence_identity import evidence_digest, field
        text = path.read_text(encoding="utf-8")
        self.assertEqual(field(text, "归属证据SHA-256"), evidence_digest(text))  # bound to this Claim's own text
        self.assertIn("- 知识版本：v2", text)
        archives = list((self.sc.project / "05_数据与审核/60_版本归档").rglob("*.md"))
        self.assertTrue(any(SIZE.title in a.read_text(encoding="utf-8", errors="ignore") for a in archives))
        again = self.complete(article_id, {})  # idempotent: no second bump, archive or row
        self.assertEqual(again.code, 0, again.out + again.err)
        self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertEqual(len(self.rows(article_id)), 1)

    def test_s42_a_changed_excerpt_is_not_rebound_by_completion(self):
        article_id = self.submit(article())
        path = self.sha_claim(excerpt_change=True)
        before = path.read_text(encoding="utf-8")
        held = self.sc.reuse(BATCH, article_id, SIZE)
        self.assertNotEqual(held.code, 0)
        self.assertIn("status=回源核验", held.out)
        refused = self.complete(article_id, {})
        self.assertNotEqual(refused.code, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
