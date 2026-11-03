"""Old-package source detection and unfetched Claim reuse in the source chain."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import preparation_record  # noqa: E402
import template_contract  # noqa: E402
from article_state import retrieval_claim_source_errors  # noqa: E402
from preparation_record import OLD_PACKAGE_SOURCE_RE, protocol_errors  # noqa: E402
from test_preparation_record import record  # noqa: E402

RES_DIR = "02_源资料/50_外部调研证据/RES-P005-20261023-001_硬纸盒内托及取放部件"
OLD_TASK = "04_文章任务/40_已完成/ART-001_旧文"


class OldPackageSourceTests(unittest.TestCase):
    def test_external_research_paths_are_not_old_packages(self):
        for source in (
            f"RES:SRC-EXT-P005-20261023-001@[[{RES_DIR}/10_来源原文证据.md#section]]",
            f"RES:SRC-EXT-P005-20261023-001@[[{RES_DIR}/20_调研核验记录.md#section]]",
            f"[[{RES_DIR}/10_来源原文证据.md]]；[[{RES_DIR}/20_调研核验记录.md]]",
            "CLM-EXT-P005-RIGID-006（复用，未回源）",
            "https://example.com/20_gift-box/ 正文第3段",
        ):
            with self.subTest(source=source):
                self.assertIsNone(OLD_PACKAGE_SOURCE_RE.search(source))

    def test_old_package_links_are_caught_in_every_link_form(self):
        for source in (
            "[[04_文章任务/90_归档/ART-001_v1/10_来源原文证据.md]]",
            f"[[{OLD_TASK}/30_本篇知识库资料.md]]",
            f"[[{OLD_TASK}/30_本篇知识库资料]]",
            f"[[{OLD_TASK}/20_文章前知识审核#结论]]",
            f"[[{OLD_TASK}/30_本篇知识库资料.md|旧资料]]",
            f"[[{OLD_TASK}/30_本篇知识库资料\\|旧资料]]",
            f"{OLD_TASK}/30_本篇知识库资料.md；SRC-001@p3",
            f"{OLD_TASK}\\35_写作素材来源索引.md 第2行",
            f"[[{OLD_TASK}/15_检索与知识准备记录]]",
            f"[[{OLD_TASK}/50_文章知识使用与Faithfulness记录.md]]",
            "[[30_本篇知识库资料.md]]",
        ):
            with self.subTest(source=source):
                self.assertIsNotNone(OLD_PACKAGE_SOURCE_RE.search(source))

    def test_both_gates_share_one_pattern(self):
        self.assertIs(template_contract.OLD_PACKAGE_SOURCE_RE, preparation_record.OLD_PACKAGE_SOURCE_RE)

    def test_pr1_record_accepts_res_source_and_rejects_old_package(self):
        def with_source(source):
            return record([["CF-001", "Packaging services.", source, "复用已有Formal Claim", "CLM-DEMO-001",
                            "本轮正文核验", "客户知识", "复用", "同一服务范围"]])

        res = with_source(f"RES:SRC-EXT-P005-20261023-001@[[{RES_DIR}/20_调研核验记录.md#section]]")
        self.assertEqual(protocol_errors(res), [])
        old = with_source(f"[[{OLD_TASK}/20_文章前知识审核#结论]]；SRC-001@p3")
        self.assertIn("CF-001的本轮来源不能是旧资料包", protocol_errors(old))


class UnfetchedClaimReuseTests(unittest.TestCase):
    def make_task(self, root: Path, candidate_source: str) -> Path:
        task = root / "04_文章任务/10_进行中/ART-001_Web"
        task.mkdir(parents=True)
        formal = root / "03_正式知识/10_客户知识/20_产品介绍/formal.md"
        formal.parent.mkdir(parents=True)
        formal.write_text(
            "# Formal\n\n- Claim ID：CLM-WEB-001\n- 来源链接：https://example.test/page\n"
            "- 精确位置：正文第1段\n\n### 最小原文证据\n> Web evidence text.\n",
            encoding="utf-8-sig",
        )
        (task / "15_检索与知识准备记录.md").write_text(
            "## 官网正文核验\n\n"
            "| 大纲章节/知识问题 | 页面名称与URL/Claim入口 | 本轮读取/Claim最近核验日期 | 正文/Claim证据位置 | 本轮连续原文/Claim已存证据 | 候选事实ID或未命中 | 处置结果 |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 标题 | CLM-WEB-001（本轮复用既有Formal Claim，无需网页抓取） | 2026-10-20 | 正文第1段 | Web evidence text. | CF-001 | 复用Formal Claim |\n\n"
            "## 候选事实处置明细\n\n"
            "| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n"
            "|---|---|---|---|---|\n"
            f"| CF-001 | 网页事实 | {candidate_source} | 复用已有Formal Claim | CLM-WEB-001 |\n",
            encoding="utf-8-sig",
        )
        return task

    def errors(self, candidate_source: str, state: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp), candidate_source)
            with patch("governance_source_check.claim_reuse_state", return_value=state) as check:
                result = retrieval_claim_source_errors(task)
            self.calls = check.call_count
            return result

    def test_ready_reuse_pointer_is_not_compared_as_a_url(self):
        result = self.errors("CLM-WEB-001（复用，未回源）", {"status": "可直接复用", "problems": []})
        self.assertEqual(result, [])
        self.assertEqual(self.calls, 1)

    def test_reuse_pointer_to_another_claim_is_rejected(self):
        result = self.errors("CLM-WEB-999（复用，未回源）", {"status": "可直接复用", "problems": []})
        self.assertEqual(result, ["候选事实复用的Claim与本行Claim不一致：CF-001（来源=CLM-WEB-999；Claim=CLM-WEB-001）"])

    def test_not_ready_reuse_reports_status_and_reasons(self):
        result = self.errors("CLM-WEB-001（复用，未回源）",
                             {"status": "回源核验", "problems": ["无最近核验日期", "使用前复核为是"]})
        self.assertEqual(result, ["候选事实复用的Claim不可直接复用：CF-001 -> CLM-WEB-001（回源核验：无最近核验日期；使用前复核为是）"])

    def test_plain_source_still_uses_provenance_comparison(self):
        result = self.errors("D:/customer/catalog.pdf 第1页", {"status": "可直接复用", "problems": []})
        self.assertTrue(any("来源不一致" in item for item in result))
        self.assertEqual(self.calls, 0)


if __name__ == "__main__":
    unittest.main()
