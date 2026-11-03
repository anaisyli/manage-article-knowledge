"""Recovery must build 30/35 from reused Formal Claims and one-line bridge outlines.

P-005-20261028 regression: every ledger row was ``复用已有Formal Claim`` and the
writing bridge wrote the outline as one ``;``-joined line, so recovery mapped no
Claim and the writing gate stayed blocked although governance had passed.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import recover_article_package as recovery  # noqa: E402

BATCH = "BATCH-DEMO"
ARTICLE = "ART-DEMO-001"
SECTIONS = ("H1 Demo Title", "opening: assess the pack", "H2 What Makes a Claim Verifiable?")
EXCERPTS = {
    "CLM-DEMO-001": "The drawer box can be tailored in size and insert layout.",
    "CLM-DEMO-002": "Marketers should qualify broad environmental benefit claims.",
}


def candidate_table(rows: list[tuple[str, str]]) -> str:
    return (
        "## 候选事实处置明细\n\n| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n"
        "|---|---|---|---|---|\n"
        + "".join(f"| {cf} | 摘要 | 来源 | 复用已有Formal Claim | {claim} |\n" for cf, claim in rows)
    )


def matrix_table(rows: list[tuple[str, str]]) -> str:
    return (
        "\n## 大纲逐项检索与候选事实覆盖\n\n| 大纲章节 | 六层检索范围与结果 | 命中来源与精确入口 | 候选事实ID | 候选事实数 | 已沉淀Claim数 | 未采用事实/缺口及原因 | 下一步 |\n"
        "|---|---|---|---|---:|---:|---|---|\n"
        + "".join(f"| {label} | 已有Claim | 入口 | {cfs} | 1 | 1 | 无 | 纳入30 |\n" for label, cfs in rows)
    )


class RecoveryClaimReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.project = Path(self._temp.name) / "project"
        self.task = self.project / "04_文章任务/10_进行中" / ARTICLE
        self.task.mkdir(parents=True)
        (self.task / "10_文章知识需求.md").write_text(
            f"# 文章知识需求\n\n- 文章ID：{ARTICLE}\n- 当前版本：v1\n- 批次ID：{BATCH}\n- 目标语言：English\n"
            "- 任务模式：new_article\n- 大纲ID：OUTLINE-DEMO\n- 大纲版本：v1\n\n"
            "## 大纲\n\n" + "; ".join(SECTIONS) + ".\n",
            encoding="utf-8",
        )
        self.claims = {
            claim_id: recovery.ClaimInfo(
                claim_id=claim_id, path=self.project / "03_正式知识" / f"{claim_id}.md", title=f"标题{claim_id[-1]}",
                source="https://example.test", position="第1段", original_lines=[text], translation_lines=[],
            )
            for claim_id, text in EXCERPTS.items()
        }
        self.retrieval = ""

    def tearDown(self) -> None:
        self._temp.cleanup()

    def write_ledger(self, rows: list[tuple[str, str]], disposition: str = "复用已有Formal Claim") -> None:
        ledger = self.project / "04_文章任务/批次运行" / f"{BATCH}.json"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({"evidence": [
            {"article_ids": [ARTICLE], "candidate_id": cf, "claim_id": claim,
             "verified_target_excerpt": EXCERPTS[claim], "disposition": disposition}
            for cf, claim in rows
        ]}, ensure_ascii=False), encoding="utf-8")

    def seed(self) -> recovery.RecoveryResult:
        result = recovery.RecoveryResult()
        with mock.patch("batch_knowledge_run.ledger_errors", return_value=[]), \
                mock.patch("template_contract.validate_file", return_value=[]), \
                mock.patch("preparation_record.validation_view", side_effect=lambda text: text), \
                mock.patch.object(recovery, "record_is_file", return_value=True), \
                mock.patch.object(recovery, "read_record", side_effect=lambda path: self.retrieval), \
                mock.patch.object(recovery, "_claim_infos", return_value=self.claims):
            recovery._seed_index_from_batch(self.task, self.project, result)
            if (self.task / "35_写作素材来源索引.md").is_file():
                self.material = recovery._render_minimal_material(self.task, self.project, result)
        return result

    def mapped_claims(self) -> list[str]:
        index = (self.task / "35_写作素材来源索引.md").read_text(encoding="utf-8")
        return [row["claim_id"] for row in recovery._mapping_rows(index)]

    def test_reused_claims_seed_35_for_one_line_outline(self):
        candidates = [("CF-001", "CLM-DEMO-001"), ("CF-002", "CLM-DEMO-002"), ("CF-003", "CLM-DEMO-001")]
        self.retrieval = candidate_table(candidates) + matrix_table(
            [(SECTIONS[0], "CF-002"), (SECTIONS[1], "CF-001"), (SECTIONS[2], "CF-002、CF-003")])
        self.write_ledger(candidates)

        result = self.seed()

        self.assertEqual(result.unresolved, [])
        # Two candidates on one Claim give one 35 row, matching the one 30 block per Claim.
        self.assertEqual(self.mapped_claims(), ["CLM-DEMO-001", "CLM-DEMO-002"])
        usage = self.material.split("## 四、按大纲使用", 1)[1].split("## 五", 1)[0]
        self.assertIn(f"| {SECTIONS[1]} | 标题1 |", usage)
        self.assertIn(f"| {SECTIONS[2]} | 标题1；标题2 |", usage)
        self.assertNotIn("; ", usage, "combined 10 label must be listed as its 15 sections")

    def test_section_without_claim_still_blocks_seeding(self):
        candidates = [("CF-001", "CLM-DEMO-001")]
        self.retrieval = candidate_table(candidates) + matrix_table(
            [(SECTIONS[0], "CF-001"), (SECTIONS[1], "CF-001"), (SECTIONS[2], "无")])
        self.write_ledger(candidates)

        result = self.seed()

        self.assertFalse((self.task / "35_写作素材来源索引.md").exists())
        self.assertTrue(any("逐问题映射到15" in item for item in result.unresolved))

    def test_unlisted_disposition_is_not_used_as_evidence(self):
        candidates = [("CF-001", "CLM-DEMO-001")]
        self.retrieval = candidate_table(candidates) + matrix_table([(label, "CF-001") for label in SECTIONS])
        self.write_ledger(candidates, disposition="进入治理")

        self.seed()

        self.assertFalse((self.task / "35_写作素材来源索引.md").exists())


if __name__ == "__main__":
    unittest.main()
