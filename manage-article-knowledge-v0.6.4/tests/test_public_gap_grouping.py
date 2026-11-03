"""SK-V064-032: claim_matches must say something about each claim.

P-005-ART-20261029-002 put 82 claims under one new gap with
"Cxxx属于折叠零售包装选型流程中需要外部通用知识支持的判断，当前知识资料未提供可核验证据。";
every note had the length, so all were accepted.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_faithfulness import load_disposition  # noqa: E402

STAMP = "{}属于折叠纸盒选型流程中需要外部通用知识支持的判断，当前知识资料未提供可核验证据。"


class PublicGapGroupingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        ledger = self.root / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("gap_key,status,article_ids\nGAP-T-001,待外部调研,ART-001\n", encoding="utf-8")

    def load(self, matches: dict):
        group = dict(claim_ids=list(matches), category="existing_gap", issue_key="GAP-T-001",
                     scope_review=dict(knowledge_question="折叠纸盒怎样按产品尺寸确定结构", claim_matches=matches),
                     fact_check=dict(contains_factual_judgment=True, reusable_across_articles=True,
                                     knowledge_domains=["method"], why_not_knowledge_issue=""))
        path = self.root / "disposition.json"
        path.write_text(json.dumps(dict(schema_version="1.1", article_id="ART-001", groups=[group]),
                                   ensure_ascii=False), encoding="utf-8")
        claims = [dict(claim_id=claim_id, verdict="unsupported", semantic_status="unknown",
                       claim=f"A box claim {claim_id}.", evidence=[]) for claim_id in matches]
        return load_disposition(path, "ART-001", claims, self.root, [])

    def test_one_sentence_with_the_id_swapped_is_refused_and_names_what_to_do(self):
        with self.assertRaisesRegex(ValueError, "stamped sentence.*逐条写这条主张说了什么"):
            self.load({f"C00{n}": STAMP.format(f"C00{n}") for n in range(1, 4)})

    def test_two_claims_may_share_a_sentence(self):
        self.assertEqual(len(self.load({f"C00{n}": STAMP.format(f"C00{n}") for n in range(1, 3)})), 1)

    def test_notes_that_differ_pass_however_many_claims_the_question_holds(self):
        matches = {f"C{n:03d}": f"该主张说明第{n}种尺寸条件下的结构选择依据" for n in range(1, 41)}
        self.assertEqual(len(self.load(matches)[0]["claim_ids"]), 40)


if __name__ == "__main__":
    unittest.main()
