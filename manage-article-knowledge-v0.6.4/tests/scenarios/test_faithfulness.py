"""S19-S21, S30, S34: final article -> Faithfulness audit -> import, against deepeval-article-audit v1.10.0.

The writer's final article, the audit judge's verdicts and the disposition JSON are the
only hand-written inputs; finalize, the 50 record, every audit step (prepare to render)
and the import run as the two Skills' real scripts.  See MATRIX.md and audit_harness.py.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_harness import AUDIT_SKILL, AuditRun, Judged  # noqa: E402
from harness import Result, current_version, run  # noqa: E402
import test_new_article as base  # noqa: E402  (module import: base scenarios are not collected twice)
from test_new_article import BATCH, article  # noqa: E402

SIZE_TEXT = "This drawer box can be tailored in size, paper material and inner tray layout."
INSERT_TEXT = "Insert Options cardboard, EVA, sponge, pulp tray."
WARRANTY = "The drawer box ships with a lifetime warranty."
RECYCLING = "Pulp trays are widely recycled through curbside programs."
SUPPORTED = [Judged(SIZE_TEXT, SIZE_TEXT, "证据正文逐字列出尺寸、纸材与内托三项可调"),
             Judged(INSERT_TEXT, INSERT_TEXT, "证据正文逐字列出四种内托材料选项")]


@unittest.skipUnless(AUDIT_SKILL.is_dir(), f"需要本机审核Skill：{AUDIT_SKILL}")
class FaithfulnessScenarios(base.NewArticleScenarios):
    # The parent's S01-S06 already run in test_new_article; only the import scenarios run here.
    test_s01_reused_claims_list_outline = test_s02_reused_claims_recorded_one_line_outline = None
    test_s03_fresh_reads_only = test_s04_mixed_evidence_and_two_candidates_on_one_claim = None
    test_s05_section_without_claim_blocks = test_s06_new_one_line_outline_refused_then_resubmitted = None

    def deliver(self, third_section: str = "", third: Judged | None = None) -> tuple[str, AuditRun, Path]:
        """A permitted article goes through finalize, its 50 record and a real audit; returns the waiting task."""
        article_id = self.prepare(article())
        self.assert_ready(article_id, self.sc.workflow(BATCH))
        body = f"# Demo Drawer Boxes\n\n{SIZE_TEXT}\n\n## Which Parts Matter?\n\n{INSERT_TEXT}\n"
        if third_section:
            body += f"\n## How to Compare Inserts?\n\n{third_section}\n"
        final = self.sc.root / "ws" / "终稿" / "demo-final.md"
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_text(body, encoding="utf-8")
        finalized = run("writing_bridge.py", "finalize", "--handoff-contract-version", current_version(),
                        "--project", self.sc.project, "--final-path", final, "--article-id", article_id)
        self.assertEqual(finalized.value("handoff_event"), "writing_completed", finalized.err or finalized.out)
        task = self.sc.task(article_id)
        request = run("create_faithfulness_record.py", "--article", task / "40_最终文章.md",
                      "--knowledge", task / "30_本篇知识库资料.md", "--source-index", task / "35_写作素材来源索引.md",
                      "--receipt", task / "50_文章知识使用与Faithfulness记录.md",
                      "--result-dir", self.sc.root / "fr" / "P-T" / article_id / "v1",
                      "--handoff-contract-version", current_version())
        self.assertEqual(request.code, 0, request.err or request.out)
        judged = SUPPORTED + ([third or Judged(third_section)] if third_section else [])
        audit = AuditRun(request, judged)
        rendered = json.loads(audit.run().out)
        self.assertEqual(rendered["handoff_event"], "faithfulness_completed")
        task = self.sc.task(article_id)
        self.assertEqual(task.parent.name, "30_等待Faithfulness")
        preflight = run("import_faithfulness.py", "--task-dir", task, "--check-only")
        self.assertEqual(preflight.value("import_preflight"), "ok", preflight.err or preflight.out)
        return article_id, audit, task

    def assert_completed(self, article_id: str, imported: Result) -> None:
        self.assertEqual(imported.code, 0, imported.err or imported.out)
        self.assertEqual(imported.value("handoff_event"), "article_completed")
        self.assertEqual(self.sc.task(article_id).parent.name, "40_已完成")
        verified = run("handoff_contract.py", "--event", "article_completed", "--payload", imported.value("completion_receipt"),
                       "--verify-completion", "--expected-article-id", article_id, "--expected-article-version", "v1")
        self.assertIn("completion_verified=true", verified.out, verified.err or verified.out)

    def disposition(self, article_id: str, group: dict) -> Path:
        path = self.sc.root / "disposition.json"
        path.write_text(json.dumps({"schema_version": "1.1", "article_id": article_id, "groups": [group]},
                                   ensure_ascii=False), encoding="utf-8")
        return path

    def unsupported_ids(self, audit: AuditRun) -> list[str]:
        digest = self.sc.root / "digest.json"
        made = run("faithfulness_unsupported_digest.py", "--result-dir", audit.result_dir, "--output", digest)
        self.assertEqual(made.code, 0, made.err or made.out)
        return [row["id"] for row in json.loads(digest.read_text(encoding="utf-8"))["unsupported"]]

    def test_s19_all_supported_import_completes(self):
        article_id, _audit, task = self.deliver()
        imported = run("import_faithfulness.py", "--task-dir", task)
        self.assertEqual(imported.value("faithfulness"), "100.00%")
        self.assertEqual(imported.value("mapped_formal_claims"), "2")
        self.assert_completed(article_id, imported)

    def test_s20_writer_added_customer_fact_goes_to_cus(self):
        article_id, audit, task = self.deliver(WARRANTY)
        refused = run("import_faithfulness.py", "--task-dir", task)
        self.assertNotEqual(refused.code, 0)
        self.assertIn("--disposition", refused.err + refused.out)
        claim_ids = self.unsupported_ids(audit)
        self.assertEqual(len(claim_ids), 1)
        item = run("record_governance_item.py", "--project", self.sc.project, "--kind", "CUS",
                   "--title", "抽屉盒终身质保是否成立", "--set", "想确认什么=客户是否为该抽屉盒提供终身质保",
                   "--set", "为什么需要=终稿写了终身质保，但知识库没有该客户事实", "--set", "回复前怎么处理=正文不写质保承诺",
                   "--set", "当前阶段=待判断要不要问", "--set", "下一责任人=内容运营",
                   "--set", f"相关文章/Claim入口={article_id}的质保主张",
                   "--detail", "重开条件=客户补充或更正质保信息，或其他文章再次用到时")
        self.assertEqual(item.code, 0, item.err or item.out)
        cus_id = item.value("item_id")
        group = {"group_id": "UG-001", "claim_ids": claim_ids, "topic": "终稿新增的客户质保承诺", "category": "cus",
                 "classification_basis": "写作者新增了客户专属的质保承诺，知识库没有对应Formal Claim",
                 "issue_key": cus_id, "status": "待判断要不要问", "article_impact": "该句不能作为已核验事实保留",
                 "handling": "向客户确认质保政策，确认前正文删去该承诺", "next_owner": "内容运营",
                 "entry": cus_id, "close_condition": "客户确认或否认质保政策后更新文章",
                 "fact_check": {"contains_factual_judgment": True, "reusable_across_articles": False,
                                "knowledge_domains": ["customer_fact"], "why_not_knowledge_issue": ""}}
        imported = run("import_faithfulness.py", "--task-dir", task, "--disposition", self.disposition(article_id, group))
        self.assert_completed(article_id, imported)
        ledger = (self.sc.project / "05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md").read_text(encoding="utf-8")
        self.assertIn(cus_id, ledger)

    def test_s30_workflow_receipt_names_the_import_once_results_arrive(self):
        # P-005-ART-20261029-001: the audit result sat in the 50's result directory, the receipt only said
        # "按交接合同继续审核与导入", and the agent stopped because the batch ledger held no result payload.
        article_id, _audit, task = self.deliver(WARRANTY)
        receipt = self.sc.workflow(BATCH)
        state = {a["article_id"]: a for a in receipt["articles"]}[article_id]
        self.assertEqual(state.get("stage"), "faithfulness_import", state)
        self.assertIn("--check-only", state["next_action"])
        self.assertIn(str(task), state["next_action"])
        self.assertIn("faithfulness_unsupported_digest.py", state["next_action"])
        self.assertIn("尚未导入", receipt["next_action"])

    def test_s34_audit_left_a_claim_unresolved_although_30_has_the_evidence(self):
        # P-005-ART-20261029-002 C009/C011/C012: one pass supported the claim from 30's verbatim evidence,
        # the audit itself left it unknown, and no category fitted, so the import stopped (SK-V064-031).
        text = "The drawer box offers cardboard and EVA inserts."
        article_id, audit, task = self.deliver(text, Judged(text, INSERT_TEXT, "证据列出cardboard与EVA内托", second="unknown"))
        claim_ids = self.unsupported_ids(audit)
        self.assertEqual(len(claim_ids), 1)
        digest = json.loads((self.sc.root / "digest.json").read_text(encoding="utf-8"))
        self.assertTrue(digest["unsupported"][0]["flags"].get("audit_unresolved_candidate"), digest["unsupported"][0])
        group = {"claim_ids": claim_ids, "category": "audit_unresolved", "issue_key": ""}
        imported = run("import_faithfulness.py", "--task-dir", task, "--disposition", self.disposition(article_id, group))
        self.assert_completed(article_id, imported)
        record = (self.sc.task(article_id) / "50_文章知识使用与Faithfulness记录.md").read_text(encoding="utf-8")
        self.assertIn("审核结论未定（30已有证据", record)

    def test_s34_a_claim_both_passes_left_unknown_cannot_be_called_unresolved(self):
        article_id, audit, task = self.deliver(WARRANTY)
        group = {"claim_ids": self.unsupported_ids(audit), "category": "audit_unresolved", "issue_key": ""}
        refused = run("import_faithfulness.py", "--task-dir", task, "--disposition", self.disposition(article_id, group))
        self.assertNotEqual(refused.code, 0)
        self.assertIn("audit_unresolved须有一轮审核判为entailed", refused.err + refused.out)

    def test_s21_short_claim_mapping_names_the_claim_and_minimum(self):
        article_id, audit, task = self.deliver(RECYCLING)
        claim_ids = self.unsupported_ids(audit)
        self.assertEqual(len(claim_ids), 1)
        topic = "纸浆内托在美国路边回收体系中的可回收情况如何？"
        gap = run("record_knowledge_gap.py", "--csv", self.sc.project / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv",
                  "--gap-key", "auto", "--topic", topic, "--article-id", article_id, "--article-date", "2026-10-29",
                  "--trigger-basis", "首篇普通缺口")
        self.assertEqual(gap.code, 0, gap.err or gap.out)
        group = {"group_id": "UG-001", "claim_ids": claim_ids, "topic": "纸浆内托的路边回收情况", "category": "new_public_gap",
                 "classification_basis": "可跨文章复用的包装回收公共知识，当前没有已核验来源",
                 "issue_key": gap.value("gap_key"), "status": gap.value("status"),
                 "article_impact": "该句不能作为已核验事实保留", "handling": "按缺口开展定向外部调研",
                 "next_owner": "Codex", "entry": gap.value("gap_key"), "close_condition": "有RES与外部Claim覆盖后关闭",
                 "scope_review": {"knowledge_question": topic, "claim_matches": {claim_ids[0]: "如何汇集可见包装决定。"}},
                 "fact_check": {"contains_factual_judgment": True, "reusable_across_articles": True,
                                "knowledge_domains": ["method"], "why_not_knowledge_issue": ""}}
        self.assertEqual(len(group["scope_review"]["claim_matches"][claim_ids[0]]), 11)
        refused = run("import_faithfulness.py", "--task-dir", task, "--disposition", self.disposition(article_id, group))
        self.assertNotEqual(refused.code, 0)
        message = refused.err + refused.out
        # SK-V063-075: the refusal names the claim and the 12-character minimum.
        self.assertRegex(message, rf"{claim_ids[0]}[^\n]*12|12[^\n]*{claim_ids[0]}")
        # The fix the message asks for is enough: no other field has to change.
        group["scope_review"]["claim_matches"][claim_ids[0]] = "该主张断言纸浆内托普遍可经路边回收，正属于本问题"
        del group["entry"]  # SK-V064-025: the importer's default links to the ledger, not "GAP｜GAP"
        imported = run("import_faithfulness.py", "--task-dir", task, "--disposition", self.disposition(article_id, group))
        self.assert_completed(article_id, imported)
        record = (self.sc.task(article_id) / "50_文章知识使用与Faithfulness记录.md").read_text(encoding="utf-8")
        key = gap.value("gap_key")
        self.assertIn(f"{key}｜[缺口台账](../../../05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md#当前知识缺口)", record)
        self.assertNotIn(f"{key}｜{key}", record)
        linked = self.sc.task(article_id) / "../../../05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md"
        self.assertTrue(linked.resolve().is_file(), linked)


if __name__ == "__main__":
    unittest.main()
