"""S33: a Claim whose excerpt says "We…" must say who "we" is before it enters a new 30.  See MATRIX.md.

P-005-ART-20261029-002: the audit judged "JERL Packaging's customization scope covers…" from "We can
manufacture…" and resolved "we" through the 30's EC-1 block, which comes from the Claim's 指代解析.  An
old Claim whose resolution skips "we" cannot prove a correct fact, so it is rewritten to the current
rule when an article uses it (SK-V064-030).  Permissions already issued are not revoked.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Article, Candidate, Claim, Scenario, run  # noqa: E402
from test_new_article import BATCH, SECTIONS, SIZE, listed  # noqa: E402

SERVICE = Claim("CLM-T-OEM-001", "抽屉盒OEM定制服务",
                "We can manufacture custom drawer boxes according to your required size and logo file.",
                obj="Drawer box OEM customization service", position="OEM Service / paragraph 1",
                coreference="your refers to a prospective customer.")  # written before the rule: no "we"
FIXED = "We refers to Demo Packaging; your refers to a prospective customer."


def article() -> Article:
    return Article("SC-COREF", "Demo Drawer Boxes", listed(SECTIONS), SECTIONS, [
        Candidate("CF-001", SIZE, ["标题", "主问题", SECTIONS[0], SECTIONS[1]]),
        Candidate("CF-002", SERVICE, ["主问题", SECTIONS[2]]),
    ])


class CoreferenceScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.sc = Scenario()
        self.addCleanup(self.sc.close)
        self.sc.add_claim(SIZE)
        self.claim_file = self.sc.add_claim(SERVICE)

    def state(self, article_id: str) -> dict:
        return {a["article_id"]: a for a in self.sc.workflow(BATCH)["articles"]}[article_id]

    def test_s33_reused_claim_is_rewritten_to_name_we(self):
        art = article()
        article_id = self.sc.submit(art, BATCH).value("article_id")
        self.assertEqual(self.sc.reuse(BATCH, article_id, SIZE).code, 0)
        held = self.sc.reuse(BATCH, article_id, SERVICE)
        self.assertNotEqual(held.code, 0)
        self.assertIn("指代解析没有说明原文中的we", held.out)
        draft = json.loads(held.value("claim_complete_draft"))
        self.assertEqual(draft["fields"]["需在指代解析中说明"], "we")
        before = self.claim_file.read_text(encoding="utf-8")
        completion = self.sc.root / "complete.json"
        completion.write_text(json.dumps({SERVICE.claim_id: {"指代解析": FIXED}}, ensure_ascii=False), encoding="utf-8")
        done = run("record_claim_reuse.py", "--project", self.sc.project, "--batch-id", BATCH, "--article-id", article_id,
                   "--claim-id", SERVICE.claim_id, "--complete", completion,
                   "--basis", f"{SERVICE.title}的有效记录覆盖本篇对应问题，范围限于{SERVICE.obj}")
        self.assertEqual(done.code, 0, done.out + done.err)
        after = self.claim_file.read_text(encoding="utf-8")
        self.assertIn(f"- 指代解析：{FIXED}", after)
        self.assertIn("- 知识版本：v2", after)
        # The fact is unchanged: same excerpt, same attribution SHA-256.
        sha = lambda text: next(l for l in text.splitlines() if l.startswith("- 归属证据SHA-256："))
        self.assertEqual(sha(before), sha(after))
        self.sc.write_20(article_id, art)
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))
        material = (self.sc.task(article_id) / "30_本篇知识库资料.md").read_text(encoding="utf-8")
        self.assertIn(FIXED, material)

    def test_s33_wrong_rewrite_is_refused(self):
        art = article()
        article_id = self.sc.submit(art, BATCH).value("article_id")
        completion = self.sc.root / "complete.json"
        completion.write_text(json.dumps({SERVICE.claim_id: {"指代解析": "your refers to a customer."}}), encoding="utf-8")
        refused = run("record_claim_reuse.py", "--project", self.sc.project, "--batch-id", BATCH, "--article-id", article_id,
                      "--claim-id", SERVICE.claim_id, "--complete", completion,
                      "--basis", f"{SERVICE.title}的有效记录覆盖本篇对应问题，范围限于{SERVICE.obj}")
        self.assertNotEqual(refused.code, 0)
        self.assertIn("仍未说明原文中的we", refused.err)

    def test_s33_claim_read_this_run_is_held_until_its_resolution_names_we(self):
        art = article()
        article_id = self.sc.submit(art, BATCH).value("article_id")
        self.assertEqual(self.sc.reuse(BATCH, article_id, SIZE).code, 0)
        art.candidates[1].evidence = self.sc.capture(article_id, SERVICE, SECTIONS[2])
        self.sc.workflow(BATCH)
        self.sc.write_20(article_id, art)
        state = self.state(article_id)
        self.assertNotEqual(state["state"], "writing_ready_issued")
        self.assertIn(f"{SERVICE.claim_id}的指代解析没有说明原文中的we", json.dumps(state, ensure_ascii=False))
        text = self.claim_file.read_text(encoding="utf-8")
        self.claim_file.write_text(text.replace(f"- 指代解析：{SERVICE.coreference}", f"- 指代解析：{FIXED}"),
                                   encoding="utf-8")
        state = self.state(article_id)
        self.assertEqual(state["state"], "writing_ready_issued", state.get("next_action"))


if __name__ == "__main__":
    unittest.main()
