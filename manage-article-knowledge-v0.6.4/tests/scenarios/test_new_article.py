"""Scenarios S01-S06: a new article from writing_request to the writing gate.  See MATRIX.md."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Article, Candidate, Claim, Scenario, run  # noqa: E402

BATCH = "B-SC"
SECTIONS = ["H1 Demo Drawer Boxes", "H2 Which Parts Matter?", "H2 How to Compare Inserts?"]
SIZE = Claim("CLM-T-DRAWER-001", "抽屉盒可调整尺寸与内托",
             "This drawer box can be tailored in size, paper material and inner tray layout.")
INSERTS = Claim("CLM-T-DRAWER-002", "抽屉盒内托材料选项", "Insert Options cardboard, EVA, sponge, pulp tray.",
                position="Specification > Insert Options")


def listed(sections: list[str]) -> str:
    return "\n".join(f"- {s}" for s in sections)


def article(outline: str | None = None, candidates: list[Candidate] | None = None, **kw) -> Article:
    return Article("SC-001", "Demo Drawer Boxes", outline if outline is not None else listed(SECTIONS), SECTIONS,
                   candidates if candidates is not None else [
                       Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[1]]),
                       Candidate("CF-002", INSERTS, ["主问题", SECTIONS[1], SECTIONS[2]]),
                   ], **kw)


class NewArticleScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.sc = Scenario()
        self.addCleanup(self.sc.close)
        for claim in (SIZE, INSERTS):
            self.sc.add_claim(claim)

    # --- steps --------------------------------------------------------
    def prepare(self, art: Article) -> str:
        submitted = self.sc.submit(art, BATCH)
        self.assertEqual(submitted.code, 0, submitted.err or submitted.out)
        article_id = submitted.value("article_id")
        for claim in {c.claim.claim_id: c.claim for c in art.candidates}.values():
            reused = self.sc.reuse(BATCH, article_id, claim)
            self.assertEqual(reused.code, 0, reused.err or reused.out)
        self.sc.write_20(article_id, art)
        return article_id

    # --- assertions ---------------------------------------------------
    def assert_ready(self, article_id: str, receipt: dict) -> Path:
        state = {a["article_id"]: a for a in receipt["articles"]}[article_id]
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        task = self.sc.task(article_id)
        ready = json.loads((task / "writing_ready.json").read_text(encoding="utf-8"))
        material = task / "30_本篇知识库资料.md"
        self.assertEqual(ready["knowledge_sha256"], hashlib.sha256(material.read_bytes()).hexdigest())
        self.assertEqual(self.sc.gate(article_id).value("writing_gate_status"), "ready")
        return task

    def mapped_claims(self, task: Path) -> list[str]:
        index = (task / "35_写作素材来源索引.md").read_text(encoding="utf-8-sig")
        return re.findall(r"^\|\s*\d+\s*\|\s*\d+\s*\|[^|]*\|\s*(CLM-[A-Za-z0-9-]+)\s*\|", index, re.M)

    def usage_rows(self, task: Path) -> dict[str, str]:
        text = (task / "30_本篇知识库资料.md").read_text(encoding="utf-8-sig")
        body = text.split("## 四、按大纲使用", 1)[1].split("## 五", 1)[0]
        rows = [line.split("|")[1:3] for line in body.splitlines() if line.startswith("| ") and "---" not in line]
        return {name.strip(): facts.strip() for name, facts in rows[1:]}

    # --- scenarios ----------------------------------------------------
    def test_s01_reused_claims_list_outline(self):
        art = article()
        article_id = self.prepare(art)
        task = self.assert_ready(article_id, self.sc.workflow(BATCH))
        self.assertEqual(sorted(self.mapped_claims(task)), [SIZE.claim_id, INSERTS.claim_id])
        usage = self.usage_rows(task)
        self.assertEqual(list(usage), SECTIONS)
        self.assertIn(INSERTS.title, usage[SECTIONS[2]])

    def test_s02_reused_claims_recorded_one_line_outline(self):
        # A task registered before the list rule keeps the bridge's one-line outline in 10.
        art = article()
        article_id = self.prepare(art)
        request = self.sc.task(article_id) / "10_文章知识需求.md"
        text = request.read_text(encoding="utf-8-sig")
        request.write_text(text.replace(listed(SECTIONS), "; ".join(SECTIONS) + "."), encoding="utf-8")
        task = self.assert_ready(article_id, self.sc.workflow(BATCH))
        self.assertEqual(list(self.usage_rows(task)), SECTIONS)

    def prepare_fresh(self, art: Article, fresh: list[Candidate]) -> str:
        """Read ``fresh`` candidates' pages this run; the workflow promotes them before 20 is written."""
        submitted = self.sc.submit(art, BATCH)
        self.assertEqual(submitted.code, 0, submitted.err or submitted.out)
        article_id = submitted.value("article_id")
        for candidate in fresh:
            candidate.evidence = self.sc.capture(article_id, candidate.claim, "；".join(candidate.sections))
        self.sc.workflow(BATCH)
        ledger = json.loads((self.sc.project / f"04_文章任务/批次运行/{BATCH}.json").read_text(encoding="utf-8-sig"))
        promoted = {row["claim_id"]: row["candidate_id"] for row in ledger["evidence"] if row["disposition"] == "本轮核验通过"}
        self.assertEqual({c.claim.claim_id: c.cf for c in fresh}, promoted, "captures were not promoted to the expected CF ids")
        for candidate in art.candidates:
            if not candidate.evidence:
                reused = self.sc.reuse(BATCH, article_id, candidate.claim)
                self.assertEqual(reused.code, 0, reused.err or reused.out)
        self.sc.write_20(article_id, art)
        return article_id

    def test_s03_fresh_reads_only(self):
        art = article()
        article_id = self.prepare_fresh(art, art.candidates)
        task = self.assert_ready(article_id, self.sc.workflow(BATCH))
        self.assertEqual(sorted(self.mapped_claims(task)), [SIZE.claim_id, INSERTS.claim_id])

    def test_s04_mixed_evidence_and_two_candidates_on_one_claim(self):
        fresh = Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0]])
        art = article(candidates=[
            fresh,
            Candidate("CF-002", INSERTS, ["主问题", SECTIONS[1], SECTIONS[2]]),
            Candidate("CF-003", SIZE, [SECTIONS[1]]),
        ])
        article_id = self.prepare_fresh(art, [fresh])
        task = self.assert_ready(article_id, self.sc.workflow(BATCH))
        # One 35 row per Claim, matching the one 30 block per Claim.
        self.assertEqual(sorted(self.mapped_claims(task)), [SIZE.claim_id, INSERTS.claim_id])

    def test_s05_section_without_claim_blocks(self):
        art = article(candidates=[Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[1]])],
                      gaps={SECTIONS[2]: "内托材料比较没有已核验来源"})
        article_id = self.prepare(art)
        receipt = self.sc.workflow(BATCH)
        state = {a["article_id"]: a for a in receipt["articles"]}[article_id]
        self.assertNotEqual(state["state"], "writing_ready_issued")
        task = self.sc.task(article_id)
        self.assertFalse((task / "writing_ready.json").exists())
        self.assertIn(f"{SECTIONS[2]}的部分/未覆盖项", state["next_action"])

    def test_s06_new_one_line_outline_refused_then_resubmitted(self):
        refused = self.sc.submit(article(outline="; ".join(SECTIONS) + "."), BATCH)
        self.assertNotEqual(refused.code, 0)
        self.assertIn("逐行列表", refused.err + refused.out)
        self.assertEqual(list((self.sc.project / "04_文章任务/10_进行中").iterdir()), [])
        config = (self.sc.project / "01_工作台/40_写作与Faithfulness接入配置.md").read_text(encoding="utf-8-sig")
        self.assertNotIn("接入状态：异常，待重新确认", config)
        self.assertIn("大纲须改为逐行列表", config)

        # The writer fixes only the format in its request record and resubmits under the same key.
        record = self.sc.tasks_entry / "SC-001.md"
        record.write_text(record.read_text(encoding="utf-8").replace("; ".join(SECTIONS) + ".", listed(SECTIONS)),
                          encoding="utf-8")
        article_id = self.prepare(article())
        self.assert_ready(article_id, self.sc.workflow(BATCH))


if __name__ == "__main__":
    unittest.main()
