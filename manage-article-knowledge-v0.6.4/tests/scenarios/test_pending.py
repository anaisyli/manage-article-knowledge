"""S07-S18: offline knowledge gates and same-outline revision scenarios.

Only prepare, record_claim_reuse, the workflow and the writing gate are invoked.
S16/S17 cover the gate side only: finalize is outside the allowed entry points.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Candidate, Claim, Scenario, run
from test_new_article import BATCH, INSERTS, SECTIONS, SIZE, article, listed


class PendingScenarios(unittest.TestCase):
    def setUp(self):
        self.sc = Scenario()
        self.addCleanup(self.sc.close)
        for claim in (SIZE, INSERTS):
            self.sc.add_claim(claim)

    def ready(self, article_id, *, version="v1", recheck=False):
        if recheck:
            gate = self.sc.gate(article_id)
            self.assertEqual(gate.value("writing_gate_status"), "ready", gate.out + gate.err)
        task = self.sc.task(article_id)
        gate = json.loads((task / "writing_gate_result.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["writing_gate_status"], "ready", gate)
        receipt = json.loads((task / "writing_ready.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["article_version"], version)
        self.assertEqual(receipt["knowledge_sha256"], hashlib.sha256(
            (task / "30_本篇知识库资料.md").read_bytes()).hexdigest())
        return task

    def blocked(self, article_id, reason=None):
        gate = self.sc.gate(article_id)
        self.assertEqual(gate.value("writing_gate_status"), "blocked", gate.out + gate.err)
        task = self.sc.task(article_id)
        self.assertFalse((task / "writing_ready.json").exists())
        if reason:
            self.assertRegex(gate.out + gate.err, reason)
        return task

    def prepare(self, art=None, *, evidence="reuse", legacy=False, protocol="PR-2"):
        art = art or article()
        submitted = self.sc.submit(art, BATCH)
        self.assertEqual(submitted.code, 0, submitted.out + submitted.err)
        article_id = submitted.value("article_id")
        if legacy:
            # This is an already registered old task, not a new one-line request.
            path = self.sc.task(article_id) / "10_文章知识需求.md"
            art.outline = "; ".join(art.sections) + "."
            path.write_text(path.read_text(encoding="utf-8").replace(listed(art.sections), art.outline),
                            encoding="utf-8")
        self.evidence(article_id, art, evidence)
        self.sc.write_20(article_id, art)
        if protocol == "PR-1":
            self.make_pr1(article_id)
        self.sc.workflow(BATCH)
        self.ready(article_id)
        return article_id, art

    def evidence(self, article_id, art, mode):
        fresh = art.candidates if mode == "fresh" else art.candidates[:1] if mode == "mixed" else []
        for candidate in fresh:
            candidate.evidence = self.sc.capture(article_id, candidate.claim, "；".join(candidate.sections))
        if fresh:
            self.sc.workflow(BATCH)  # Promote saved, offline evidence through the real workflow.
        for candidate in art.candidates:
            if candidate not in fresh:
                result = self.sc.reuse(BATCH, article_id, candidate.claim)
                self.assertEqual(result.code, 0, result.out + result.err)

    def make_pr1(self, article_id):
        # Materialize the supported legacy layout as fixture data, before starting
        # the revision. The baseline must independently pass the real gate.
        from task_records import legacy_views
        task = self.sc.task(article_id)
        request = task / "10_文章知识需求.md"
        request.write_text(request.read_text(encoding="utf-8").replace(
            "知识准备记录协议：PR-2", "知识准备记录协议：PR-1"), encoding="utf-8")
        retrieval, audit = legacy_views(task)
        retrieval = retrieval.replace("<!-- PR-2 legacy view -->", "")
        audit = audit.replace("<!-- PR-2 legacy view -->", "")
        audit = re.sub(r"\[\[20_文章前知识审核.md#[^\]]+\]\]",
                       "[[15_检索与知识准备记录.md]]", audit)
        (task / "15_检索与知识准备记录.md").write_text(retrieval, encoding="utf-8")
        (task / "20_文章前知识审核.md").write_text(audit, encoding="utf-8")

    def revise(self, article_id, art, mode):
        result = self.sc.submit(art, BATCH, revision_mode=mode, article_id=article_id)
        self.assertEqual(result.code, 0, result.out + result.err)
        self.assertEqual(result.value("article_version"), "v2", result.out)
        return result

    GAP_TOPIC = "食品直接接触内托材料适用哪些公开安全规则？"

    def gap_article(self, extra=(), handling="待外部调研，尚无RES或外部Claim", verdict="未解决"):
        """P-005 food article shape: a registered 待外部调研 gap is the entry of one 部分覆盖 section."""
        art = article(candidates=[
            Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[1]]),
            Candidate("CF-002", INSERTS, ["主问题", SECTIONS[1], SECTIONS[2]]),
            *extra,
        ])
        article_id = self.sc.submit(art, BATCH).value("article_id")
        for candidate in art.candidates:
            self.assertEqual(self.sc.reuse(BATCH, article_id, candidate.claim).code, 0)
        gap = self.sc.gap(article_id, self.GAP_TOPIC)
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        if verdict == "未解决":
            marked = re.sub(rf"\| {re.escape(SECTIONS[2])} \| 已覆盖 \| ([^|]*) \| [^|]*\| 无 \|",
                            lambda m: f"| {SECTIONS[2]} | 部分覆盖 | {m[1]} | 内托选项有客户Claim，食品接触安全规则未覆盖 | {gap} |",
                            text)
            self.assertNotEqual(marked, text, "fixture must point the section at the gap")
        else:
            marked = text  # A closed gap leaves the section 已覆盖; its resolution is in the gap table.
        marked = marked.replace(
            "- 本轮待调研缺口：无（已有有效Claim覆盖）",
            "| GAP ID | 本轮具体公共知识问题 | 与当前大纲关系 | 本轮处理和证据 | 审核结论 |\n|---|---|---|---|---|\n"
            f"| {gap} | {self.GAP_TOPIC} | {SECTIONS[2]}：本节需要回答 | {handling} | {verdict} |",
        ).replace("| 新外部调研 | 未触发 | 已有Claim覆盖 | 无 |", f"| 新外部调研 | 已触发 | {gap}高风险事实首次 | 定向外部调研 |")
        audit.write_text(marked, encoding="utf-8")
        return article_id, gap

    def test_s07_unresolved_public_gap_blocks(self):
        # S07: the current-outline gap check used to run only for outline_refresh (fixed in v0.6.4).
        article_id, gap = self.gap_article()
        receipt = self.sc.workflow(BATCH)
        self.blocked(article_id, f"{gap}仍属于当前大纲")
        self.assertEqual(receipt["next_owner"], "manage-article-knowledge")

    def test_s07b_researched_gap_allows_writing(self):
        # The counterpart: once this gap has RES records and a formal external Claim, writing may start.
        # New-article RES writes 文章知识准备运行ID：不适用 (external-research-contract.md).
        res_id, gap_key = "RES-PT-001", "GAP-PT-001"
        rule = Claim("CLM-EXT-PT-FOOD-001", "食品接触材料须符合适用的公开规则",
                     "Food contact materials must comply with the applicable public safety rules.",
                     subject="Public food safety guidance", obj="Food contact packaging materials",
                     source_type="外部公共来源", url="https://example.test/food-contact-rules/",
                     position="Food contact materials；第1段", folder="20_外部公共知识/50_行业知识与洞察",
                     research=res_id)
        self.sc.add_claim(rule)
        evidence = self.sc.project / f"02_源资料/50_外部调研证据/{res_id}_食品接触规则"
        evidence.mkdir(parents=True)
        record = f"- 调研ID：{res_id}\n- 关联缺口：{gap_key}\n- 文章知识准备运行ID：不适用\n"
        (evidence / "10_来源原文证据.md").write_text(record + "\n## 来源身份\n\n> " + rule.excerpt + "\n", encoding="utf-8")
        (evidence / "20_调研核验记录.md").write_text(record + f"\n## 去向\n\n{rule.claim_id}\n", encoding="utf-8")
        article_id, gap = self.gap_article(
            extra=[Candidate("CF-003", rule, [SECTIONS[2]])],
            handling=f"本轮定向调研：{res_id}；沉淀：{rule.claim_id}", verdict="已解决")
        self.assertEqual(gap, gap_key)
        self.sc.workflow(BATCH)
        self.ready(article_id)

    def rejected_claim(self, changed, reason):
        self.sc.add_claim(changed)
        art = article(candidates=[Candidate("CF-001", changed, ["标题", "主问题", *SECTIONS])])
        article_id = self.sc.submit(art, BATCH).value("article_id")
        reused = self.sc.reuse(BATCH, article_id, changed)
        self.assertNotEqual(reused.code, 0, reused.out + reused.err)
        self.assertIn("回源核验", reused.out + reused.err)
        self.assertRegex(reused.out + reused.err, reason)
        self.sc.write_20(article_id, art)
        self.sc.workflow(BATCH)
        self.blocked(article_id)

    def test_s08_inactive_claim_blocks(self):
        self.rejected_claim(replace(SIZE, state="已失效"), "有效|失效")

    def test_s08_review_required_claim_blocks(self):
        self.rejected_claim(replace(SIZE, review="是；每次使用前回源"), "使用前复核|回源")

    def test_s09_conditional_review_can_be_reused(self):
        conditional = replace(SIZE, review="条件；来源更正、标准更新或使用超范围时回源")
        self.sc.add_claim(conditional)
        self.prepare(article(candidates=[Candidate("CF-001", conditional, ["标题", "主问题", *SECTIONS])]))

    def test_s10_missing_verification_date_blocks(self):
        self.rejected_claim(replace(SIZE, verified=""), "最近核验日期")

    def refresh(self, evidence="fresh", legacy=False):
        article_id, art = self.prepare(legacy=legacy)
        self.revise(article_id, art, "outline_refresh")
        # The current version is prepared from its own evidence, with no 15.
        for candidate in art.candidates:
            candidate.evidence = ""
        self.evidence(article_id, art, evidence)
        self.sc.write_20(article_id, art)
        self.sc.workflow(BATCH)
        task = self.ready(article_id, version="v2")
        self.assertFalse((task / "15_检索与知识准备记录.md").exists())

    def test_s11_refresh_fresh_pr2(self):
        self.refresh()

    def test_s12_outline_change_waits_without_changing_integration_state(self):
        article_id, art = self.prepare()
        task = self.sc.task(article_id)
        before = (task / "10_文章知识需求.md").read_bytes()
        config = self.sc.project / "01_工作台/40_写作与Faithfulness接入配置.md"
        old_state = re.search(r"^- 接入状态：(.*)$", config.read_text(encoding="utf-8"), re.M).group(1)
        art.outline += "\n- H2 A Changed Outline"
        result = self.sc.submit(art, BATCH, revision_mode="outline_refresh", article_id=article_id)
        self.assertNotEqual(result.code, 0)
        self.assertIn("大纲变更", result.out + result.err)
        self.assertEqual((self.sc.task(article_id) / "10_文章知识需求.md").read_bytes(), before)
        updated = config.read_text(encoding="utf-8")
        self.assertIn("大纲变更待确认", updated)
        self.assertEqual(re.search(r"^- 接入状态：(.*)$", updated, re.M).group(1), old_state)

    def rewrite(self, protocol="PR-2", evidence="reuse", legacy=False):
        article_id, art = self.prepare(protocol=protocol, evidence=evidence, legacy=legacy)
        task = self.sc.task(article_id)
        if protocol == "PR-2":
            # Historical packages may lack outline identity; their mapped Claims remain authoritative.
            for name in ("30_本篇知识库资料.md", "35_写作素材来源索引.md"):
                path = task / name
                path.write_text(re.sub(r"^- (?:大纲ID|大纲版本|重写模式)：.*\n", "",
                                       path.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
        self.revise(article_id, art, "knowledge_reuse_rewrite")
        self.sc.workflow(BATCH)
        task = self.ready(article_id, version="v2")
        index = (task / "35_写作素材来源索引.md").read_text(encoding="utf-8")
        mapped = re.findall(r"^\|\s*\d+\s*\|\s*\d+\s*\|[^|]*\|\s*(CLM-[A-Za-z0-9-]+)\s*\|", index, re.M)
        self.assertEqual(sorted(mapped), [SIZE.claim_id, INSERTS.claim_id])
        self.assertFalse((task / "15_检索与知识准备记录.md").exists())
        self.assertIn("知识准备记录协议：PR-2", (task / "20_文章前知识审核.md").read_text(encoding="utf-8"))

    def test_s13_rewrite_legacy_pr2_package(self):
        self.rewrite()

    def old_rule_baseline(self, *, enhanced: bool = False) -> tuple[str, Article]:
        """A permitted v1 whose 20 narrowed an H2 the pre-SK-V064-023 way, then a knowledge-unchanged rewrite."""
        article_id, art = self.prepare()
        audit = self.sc.task(article_id) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith(f"| {SECTIONS[2]} | 已覆盖 |"))
        cells = row.split("|")
        cells[2], cells[4], cells[5] = " 部分覆盖 ", " 内托选项有Claim，材质厚度没有来源 ", " 不构成知识问题：只写已列选项 "
        audit.write_text(text.replace(row, "|".join(cells)), encoding="utf-8")
        # The rewrite request itself may ask for 加强; the rewrite still keeps its locked knowledge.
        result = self.sc.submit(art, BATCH, revision_mode="knowledge_reuse_rewrite", article_id=article_id,
                                request_text="重写这篇场景测试文章" + ("；知识准备：加强" if enhanced else ""))
        self.assertEqual(result.code, 0, result.out + result.err)
        self.sc.workflow(BATCH)
        return article_id, art

    def test_s31_knowledge_reuse_rewrite_keeps_a_baseline_narrowed_under_old_rules(self):
        # SK-V064-023 binds new preparation; a locked-knowledge rewrite cannot register or re-search anything.
        article_id, _ = self.old_rule_baseline()
        task = self.ready(article_id, version="v2")
        missing = (task / "30_本篇知识库资料.md").read_text(encoding="utf-8").split("## 六、", 1)[1]
        self.assertIn(SECTIONS[2], missing)

    def refresh_partial(self, entry: str, *, search: bool = True) -> dict:
        """outline_refresh v2 whose 20 leaves an H2 partly covered (SK-V064-023 applies to refresh too)."""
        article_id, art = self.prepare()
        self.revise(article_id, art, "outline_refresh")
        for candidate in art.candidates:
            candidate.evidence = ""
        self.evidence(article_id, art, "reuse")
        topic, gap_key = "不同内托材料的常见厚度范围是多少？", ""
        if entry == "{gap}":
            gap = run("record_knowledge_gap.py", "--csv", self.sc.project / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv",
                      "--gap-key", "auto", "--topic", topic, "--article-id", article_id,
                      "--article-date", "2026-10-30", "--trigger-basis", "首篇普通缺口")
            self.assertEqual(gap.value("status"), "观察中", gap.out + gap.err)
            entry = gap_key = gap.value("gap_key")
        audit = self.sc.write_20(article_id, art) / "20_文章前知识审核.md"
        text = audit.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith(f"| {SECTIONS[2]} | 已覆盖 |"))
        cells = row.split("|")
        cells[2], cells[4], cells[5] = " 部分覆盖 ", " 内托选项有Claim，材质厚度没有来源 ", f" {entry} "
        text = text.replace(row, "|".join(cells))
        if gap_key:
            text = re.sub(r"(?m)^- 本轮待调研缺口：.*$",
                          "| GAP ID | 本轮具体公共知识问题 | 与当前大纲关系 | 本轮处理和证据 | 审核结论 |\n|---|---|---|---|---|\n"
                          f"| {gap_key} | {topic} | {SECTIONS[2]} | 观察中，尚无RES | 未解决 |", text)
        if search:
            index, src = self.sc.project / "02_源资料", self.sc.root / "src"
            src.mkdir(exist_ok=True)
            self.assertEqual(run("build_source_index.py", "--source-root", src, "--db", index / "source-index.sqlite",
                                 "--ledger", index / "01_源资料台账.md", "--description", index / "源资料搜索索引说明.md").code, 0)
            self.assertEqual(run("search_source_index.py", "--db", index / "source-index.sqlite",
                                 "--query", "insert material thickness").code, 0)
            layer = next(line for line in text.splitlines() if line.startswith("| 客户官网 |"))
            text = text.replace(layer, "| 客户官网 | 已检索未命中 | 读取https://example.test/drawer-box/，没有内托材质厚度说明 | 无 |")
            text = re.sub(r"(?m)^- 官网正文抓取凭证：.*$", "- 官网正文抓取凭证：官网正文抓取凭证.json", text)
        audit.write_text(text, encoding="utf-8")
        receipt = self.sc.workflow(BATCH)
        return {a["article_id"]: a for a in receipt["articles"]}[article_id]

    def test_s32_refresh_applies_the_body_section_rule(self):
        state = self.refresh_partial("不构成知识问题：只写已列选项")
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("缺口列须二选一", state["next_action"])

    def test_s32_refresh_still_researches_an_observed_gap(self):
        # The 观察中 exemption is for new articles; a refresh closes every gap its outline still needs.
        state = self.refresh_partial("{gap}")
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn("必须有本轮RES", state["next_action"])

    def test_s32_refresh_narrowed_to_questions_passes(self):
        state = self.refresh_partial("不构成知识问题：其余只列待确认问题（材质厚度请向供应商确认）")
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))

    def test_s31_enhanced_is_not_applied_to_a_knowledge_reuse_rewrite(self):
        article_id, _ = self.old_rule_baseline(enhanced=True)
        self.ready(article_id, version="v2")

    def test_s14_rewrite_pr1_baseline(self):
        self.rewrite(protocol="PR-1", evidence="fresh")

    def test_s15_missing_locked_claim_blocks_rebuild(self):
        article_id, art = self.prepare()
        path = self.sc.project / "03_正式知识" / INSERTS.folder / f"{INSERTS.claim_id}.md"
        path.unlink()
        result = self.revise(article_id, art, "knowledge_reuse_rewrite")
        self.assertIn(INSERTS.claim_id, "\n".join(result.values("locked_claim_todo")))
        self.sc.workflow(BATCH)
        task = self.blocked(article_id)
        self.assertFalse((task / "30_本篇知识库资料.md").exists())

    def test_s16_line_endings_only_keeps_permission(self):
        article_id, _ = self.prepare()
        material = self.sc.task(article_id) / "30_本篇知识库资料.md"
        permitted = material.read_bytes()
        flipped = permitted.replace(b"\r\n", b"\n") if b"\r\n" in permitted else permitted.replace(b"\n", b"\r\n")
        material.write_bytes(flipped)
        self.ready(article_id, recheck=True)
        self.assertEqual(material.read_bytes(), permitted)

    def test_s17_evidence_edit_is_restored_to_the_permitted_bytes(self):
        # An evidence block has one source of truth (the Formal Claim), so the gate may restore it;
        # the permit stays valid because 30 is byte-identical to what the writer was given.
        article_id, _ = self.prepare()
        material = self.sc.task(article_id) / "30_本篇知识库资料.md"
        original = material.read_bytes()
        changed = original.replace(b"can be tailored", b"must be tailored")
        self.assertNotEqual(changed, original, "fixture needs the source sentence in 30")
        material.write_bytes(changed)
        self.ready(article_id, recheck=True)
        self.assertEqual((self.sc.task(article_id) / "30_本篇知识库资料.md").read_bytes(), original)

    def test_s17_text_change_revokes_permission(self):
        # S17b: text outside the evidence blocks has no source to restore from.  The gate used to
        # re-issue ready bound to the changed bytes without a new article version (fixed in v0.6.4).
        article_id, _ = self.prepare()
        material = self.sc.task(article_id) / "30_本篇知识库资料.md"
        original = material.read_bytes()
        changed = original.replace("仅围绕当前问题已核验的证据写作".encode(), "可以自由扩写".encode(), 1)
        self.assertNotEqual(changed, original, "fixture needs the usage-section text in 30")
        material.write_bytes(changed)
        self.blocked(article_id, "递增文章版本")

    def test_s18_same_key_reuses_one_task(self):
        article_id, art = self.prepare()
        repeated = self.sc.submit(art, BATCH)
        self.assertEqual(repeated.code, 0, repeated.out + repeated.err)
        self.assertEqual(repeated.value("article_id"), article_id)
        self.assertEqual(repeated.value("ledger_action"), "reused")
        tasks = list((self.sc.project / "04_文章任务").glob(f"*/{article_id}_*"))
        self.assertEqual(len(tasks), 1)
        self.ready(article_id)

    def test_s03_fresh_recorded_one_line_outline(self):
        self.prepare(evidence="fresh", legacy=True)

    def test_s04_mixed_recorded_one_line_outline(self):
        self.prepare(evidence="mixed", legacy=True)


def _refresh_case(evidence, legacy):
    def scenario(self):
        self.refresh(evidence=evidence, legacy=legacy)
    return scenario


def _rewrite_case(protocol, evidence, legacy):
    def scenario(self):
        self.rewrite(protocol=protocol, evidence=evidence, legacy=legacy)
    # S14 reuse/mixed: merging a valid PR-1 baseline used to drop 正式Claim复用 pointers and to pin a
    # reused candidate to another Claim's capture on the same page (fixed in v0.6.4).
    return scenario


# One unittest per combination keeps expected failures and counts independent.
# Evidence in knowledge_reuse_rewrite describes the locked baseline; the rewrite
# never invents a fresh source read or adds a Claim.
for _evidence in ("fresh", "reuse", "mixed"):
    for _legacy in (False, True):
        _outline = "legacy_line" if _legacy else "listed"
        if (_evidence, _legacy) != ("fresh", False):
            setattr(PendingScenarios, f"test_s11_refresh_{_evidence}_{_outline}_pr2",
                    _refresh_case(_evidence, _legacy))
        for _protocol, _id, _default in (("PR-2", "s13", "reuse"), ("PR-1", "s14", "fresh")):
            if (_evidence, _legacy) != (_default, False):
                setattr(PendingScenarios, f"test_{_id}_rewrite_{_evidence}_{_outline}_{_protocol.replace('-', '').lower()}",
                        _rewrite_case(_protocol, _evidence, _legacy))


if __name__ == "__main__":
    unittest.main()
