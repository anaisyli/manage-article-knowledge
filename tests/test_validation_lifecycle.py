from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "manage-article-knowledge-v0.6" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validate_v06_project as validator  # noqa: E402
import import_faithfulness as faithfulness_importer  # noqa: E402


class ValidationLifecycleTests(unittest.TestCase):
    def write_gap(self, root: Path, *, status: str, related: str = "无") -> Path:
        path = root / "gaps.csv"
        row = dict.fromkeys(validator.KNOWLEDGE_GAP_FIELDS, "")
        row.update(
            gap_key="GAP-001", gap_topic="包装样品验证的适用条件", gap_type="公共知识",
            trigger_basis="重复文章", article_ids="ART-001;ART-002", article_count="2",
            current_article_ids="ART-001;ART-002", current_article_count="2", status=status,
            current_impact="影响后续知识准备", next_action="开展定向外部调研", first_seen="2026-09-20",
            last_seen="2026-09-20", related_governance_ref=related,
        )
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=validator.KNOWLEDGE_GAP_FIELDS)
            writer.writeheader()
            writer.writerow(row)
        return path

    def test_open_research_gap_without_res_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            errors: list[str] = []
            validator.validate_knowledge_gaps(self.write_gap(Path(temp), status="待外部调研"), errors)
            self.assertEqual(errors, [])

    def test_resolved_gap_still_requires_res(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            errors: list[str] = []
            validator.validate_knowledge_gaps(self.write_gap(Path(temp), status="已解决"), errors)
            self.assertTrue(any("必须关联RES" in item for item in errors))

    def test_hyphenated_source_id_is_one_complete_token(self) -> None:
        self.assertEqual(
            validator.extract_source_ids("来源 SRC-EXT-P005-001 与 SRC-ABC123"),
            {"SRC-EXT-P005-001", "SRC-ABC123"},
        )

    def create_source_index(self, root: Path) -> None:
        database = root / "02_源资料/source-index.sqlite"
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE sources (source_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO sources(source_id) VALUES (?)", ("SRC-CUSTOMER-001",))
        connection.commit()
        connection.close()

    def test_external_source_registered_in_res_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.create_source_index(root)
            evidence = root / "02_源资料/50_外部调研证据/RES-TEST-001/10_来源原文证据.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                "# 外部来源原文证据\n\n"
                "| 来源ID | 页面/文件标题 |\n|---|---|\n"
                "| SRC-EXT-TEST-001 | 测试来源 |\n",
                encoding="utf-8-sig",
            )
            claim = root / "03_正式知识/20_外部公共知识/50_行业知识与洞察/test.md"
            claim.parent.mkdir(parents=True)
            claim.write_text("来源：SRC-EXT-TEST-001\n", encoding="utf-8-sig")
            errors: list[str] = []
            validator.validate_source_references(root, errors)
            self.assertEqual(errors, [])

    def test_missing_external_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.create_source_index(root)
            claim = root / "03_正式知识/20_外部公共知识/50_行业知识与洞察/test.md"
            claim.parent.mkdir(parents=True)
            claim.write_text("来源：SRC-EXT-MISSING-001\n", encoding="utf-8-sig")
            errors: list[str] = []
            validator.validate_source_references(root, errors)
            self.assertTrue(any("SRC-EXT-MISSING-001" in item for item in errors))

    def test_importer_excludes_both_markdown_image_forms(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            article = Path(temp) / "40_最终文章.md"
            article.write_text(
                "# 最终正文\n"
                "![Bare image alt text]\n"
                "![Linked image alt text](images/reference.jpg)\n"
                "See [the packaging guide](https://example.test/guide).\n",
                encoding="utf-8-sig",
            )
            self.assertEqual(
                faithfulness_importer.extract_article_lines(article),
                [{"line": 4, "text": "See the packaging guide."}],
            )

    def claim_block(self, claim_id: str, evidence: str = "English source evidence.") -> str:
        return f'''- Claim ID：{claim_id}
- Claim：A test fact.
- 适用范围：测试范围
- 来源类型：外部资料
- 来源链接：https://example.test
- 精确位置：section 1
- 日期或版本：2026-09-20
- 使用边界：仅供测试
- 状态：可用

### 最小原文证据
> {evidence}
'''

    def test_english_evidence_does_not_require_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "03_正式知识/10_客户知识/70_其他/claim.md"
            path.parent.mkdir(parents=True)
            path.write_text(self.claim_block("CLM-TEST-001"), encoding="utf-8-sig")
            errors: list[str] = []
            warnings: list[str] = []
            validator.validate_claims(root, errors, warnings)
            self.assertFalse(any("英文严格翻译" in item for item in errors))

    def test_unused_legacy_external_claim_is_migration_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "03_正式知识/20_外部公共知识/50_行业知识与洞察/claim.md"
            path.parent.mkdir(parents=True)
            text = self.claim_block("CLM-EXT-TEST-001").replace("- 使用边界：仅供测试\n", "")
            path.write_text(text, encoding="utf-8-sig")
            errors: list[str] = []
            warnings: list[str] = []
            validator.validate_claims(root, errors, warnings)
            validator.validate_external_claim_links(root, errors, warnings)
            self.assertFalse(any("使用边界" in item for item in errors))
            self.assertTrue(any("历史Claim待迁移" in item for item in warnings))
            self.assertTrue(any("历史外部Claim待迁移" in item for item in warnings))

    def test_current_task_cannot_use_incomplete_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "03_正式知识/20_外部公共知识/50_行业知识与洞察/claim.md"
            path.parent.mkdir(parents=True)
            text = self.claim_block("CLM-EXT-TEST-001").replace("- 使用边界：仅供测试\n", "")
            path.write_text(text, encoding="utf-8-sig")
            mapping = root / "04_文章任务/20_等待终稿/ART-001/35_写作素材来源索引.md"
            mapping.parent.mkdir(parents=True)
            mapping.write_text("CLM-EXT-TEST-001", encoding="utf-8-sig")
            errors: list[str] = []
            warnings: list[str] = []
            validator.validate_claims(root, errors, warnings)
            validator.validate_external_claim_links(root, errors, warnings)
            self.assertTrue(any("使用边界" in item for item in errors))
            self.assertTrue(any("缺少RES" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
