from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validate_v06_project as validator  # noqa: E402
import import_faithfulness as faithfulness_importer  # noqa: E402
import template_contract  # noqa: E402
from article_state import article_package_errors, retrieval_claim_source_errors  # noqa: E402
from recover_article_package import recover_task  # noqa: E402


class ValidationLifecycleTests(unittest.TestCase):
    def _write_retrieval_source_chain_fixture(self, root: Path, *, candidate_source: str, claim_source: str, claim_id: str = "CLM-WEB-001") -> Path:
        task = root / "04_文章任务/10_进行中/ART-001_Web"
        task.mkdir(parents=True)
        formal = root / "03_正式知识/10_客户知识/20_产品介绍/formal.md"
        formal.parent.mkdir(parents=True)
        formal.write_text(
            "# Formal\n\n- Claim ID：" + claim_id + "\n"
            "- 来源链接：" + claim_source + "\n"
            "- 精确位置：正文第1段\n\n"
            "### 最小原文证据\n> Web evidence text.\n",
            encoding="utf-8-sig",
        )
        (task / "15_检索与知识准备记录.md").write_text(
            "## 官网正文核验\n\n"
            "| 大纲章节/知识问题 | 页面名称与最终具体URL | 获取日期 | 正文位置 | 最小连续原文 | 候选事实ID或未命中 | 处置结果 |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 标题 | Web page；https://example.test/page | 2026-09-29 | 正文第1段 | Web evidence text. | CF-001 | 已读取并复用Formal Claim |\n\n"
            "## 候选事实处置明细\n\n"
            "| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n"
            "|---|---|---|---|---|\n"
            f"| CF-001 | 网页事实 | {candidate_source} | 复用已有Formal Claim | {claim_id} |\n",
            encoding="utf-8-sig",
        )
        return task

    def test_website_candidate_requires_same_claim_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            task = self._write_retrieval_source_chain_fixture(
                Path(temp),
                candidate_source="D:/customer/catalog.pdf 第1页",
                claim_source="D:/customer/catalog.pdf",
            )
            errors = retrieval_claim_source_errors(task)
            self.assertTrue(any("来源未绑定同一URL" in item for item in errors))
            self.assertTrue(any("来源不一致" in item for item in errors))

    def test_website_candidate_same_url_chain_can_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            task = self._write_retrieval_source_chain_fixture(
                Path(temp),
                candidate_source="https://example.test/page 正文第1段",
                claim_source="https://example.test/page",
            )
            self.assertEqual(retrieval_claim_source_errors(task), [])

    def test_completed_legacy_task_uses_identity_compatibility_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / "ART-001_Legacy"
            task.mkdir()
            (task / "10_文章知识需求.md").write_text("# 文章知识需求\n\n- 文章ID：ART-001\n", encoding="utf-8-sig")
            (task / "15_检索与知识准备记录.md").write_text("# 旧版记录\n", encoding="utf-8-sig")
            (task / "40_最终文章.md").write_text(
                "# 旧版终稿\n\n<!-- ARTICLE_BODY_START -->\n正文\n<!-- ARTICLE_BODY_END -->\n",
                encoding="utf-8-sig",
            )
            errors = template_contract.validate_completed_task_compatibility(task)
            self.assertEqual(errors, [])

    def test_completed_legacy_task_still_rejects_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / "ART-001_Legacy"
            task.mkdir()
            (task / "10_文章知识需求.md").write_text("# 文章知识需求\n\n- 文章ID：ART-001\n", encoding="utf-8-sig")
            (task / "40_最终文章.md").write_text(
                "# 旧版终稿\n\n- 文章ID：ART-002\n\n<!-- ARTICLE_BODY_START -->\n正文\n<!-- ARTICLE_BODY_END -->\n",
                encoding="utf-8-sig",
            )
            errors = template_contract.validate_completed_task_compatibility(task)
            self.assertTrue(any("文章ID不一致" in item for item in errors))
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

    def _write_package_fixture(
        self,
        root: Path,
        *,
        theme_key: str = "product:cosmetic-rigid-paper-box",
        request_object: str = "纸质化妆品外盒，用于多 SKU 美妆系列",
        claim_evidence: str = "Application Cosmetic Packaging.",
        material_evidence: str = "Application Cosmetic Packaging.",
        claim_id: str = "CLM-TEST-001",
    ) -> Path:
        task = root / "04_文章任务/10_进行中/ART-001_Cosmetic"
        task.mkdir(parents=True)
        formal = root / "03_正式知识/10_客户知识/20_产品介绍/formal.md"
        formal.parent.mkdir(parents=True)
        formal.write_text(
            f"# Formal\n\n- 稳定实体/主题键：{theme_key}\n\n"
            f"### {claim_id}｜测试\n\n{self.claim_block(claim_id, claim_evidence)}",
            encoding="utf-8-sig",
        )
        (task / "10_文章知识需求.md").write_text(
            "# 文章知识需求\n\n- 标题：Cosmetic Box Design\n"
            f"- 产品或内容对象：{request_object}\n- 选题方向：多 SKU 系列包装\n",
            encoding="utf-8-sig",
        )
        material = (
            "# 本篇写作素材包\n\n- 文章ID：ART-001\n- 文章版本：v1\n"
            "- 资料视图：写作素材包\n- 资料版本：v1\n- 生成日期：2026-09-28\n"
            "- 目标语言：English\n- 对应大纲：[[10_文章知识需求.md#大纲]]\n"
            "- 使用对象：写作流程\n\n## 一、可直接用于正文的事实\n\n"
            "### 测试事实\n\n##### 证据正文（供Faithfulness核验）\n\n"
            f"> {material_evidence}\n\n## 二、可直接采用的英文表达\n\n无\n\n"
            "## 三、可使用的数据表\n\n无\n\n## 四、按大纲使用\n\n无\n\n"
            "## 五、仅供生成控制（不得写入正文）\n\n无\n\n"
            "## 六、缺少资料的章节及建议处理方式\n\n无\n"
        )
        material_path = task / "30_本篇知识库资料.md"
        material_path.write_text(material, encoding="utf-8-sig")
        evidence_line = next(
            index for index, line in enumerate(material.splitlines(), 1) if line.startswith("> ")
        )
        audit = (
            "# 写作素材来源索引\n\n- 文章ID：ART-001\n- 文章版本：v1\n"
            "- 索引版本：v1\n- 生成日期：2026-09-28\n"
            "- 对应写作素材：[[30_本篇知识库资料.md]]\n"
            f"- 写作素材SHA-256：{validator.sha256_file(material_path)}\n- 用途：内部追溯\n\n"
            "## 写作素材到正式知识映射\n\n"
            "| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |\n"
            "|---:|---:|---|---|---|---|---|\n"
            f"| {evidence_line} | {evidence_line} | 测试 | {claim_id} | 测试 | [[03_正式知识/10_客户知识/20_产品介绍/formal.md]] | 测试 |\n\n"
            "## 写作事实输入确认\n\n- 唯一事实输入：[[30_本篇知识库资料.md]]\n"
        )
        (task / "35_写作素材来源索引.md").write_text(audit, encoding="utf-8-sig")
        return task

    def test_article_package_rejects_mismatched_product_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_package_fixture(
                root,
                theme_key="product:packaging-applications-watch",
                claim_evidence="Watch Packaging.",
                material_evidence="Watch Packaging.",
            )
            errors: list[str] = []
            validator.validate_article_knowledge_packages(root, errors, [])
            self.assertTrue(any("主题不匹配" in item for item in errors))

    def test_article_package_allows_mixed_application_claim_for_listed_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_package_fixture(
                root,
                theme_key="product:packaging-applications-watch",
                claim_evidence="Watch Packaging. Cosmetic Packaging. Food Packaging.",
                material_evidence="Watch Packaging. Cosmetic Packaging. Food Packaging.",
            )
            errors: list[str] = []
            validator.validate_article_knowledge_packages(root, errors, [])
            self.assertFalse(any("主题不匹配" in item for item in errors))

    def test_service_theme_is_product_agnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = self._write_package_fixture(
                root,
                theme_key="service:custom-packaging",
                claim_evidence="Custom packaging services.",
                material_evidence="Custom packaging services.",
            )
            errors: list[str] = []
            validator.validate_article_knowledge_packages(root, errors, [])
            self.assertFalse(any("主题不匹配" in item for item in errors))

    def test_article_package_rejects_chinese_in_english_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_package_fixture(
                root,
                claim_evidence="Application Cosmetic Packaging.",
                material_evidence="Application类别原文：Application Cosmetic Packaging.",
            )
            errors: list[str] = []
            validator.validate_article_knowledge_packages(root, errors, [])
            self.assertTrue(any("英文30证据正文不得包含中文" in item for item in errors))

    def test_article_package_requires_complete_formal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_package_fixture(
                root,
                claim_evidence="First sentence. Second sentence.",
                material_evidence="First sentence.",
            )
            errors: list[str] = []
            validator.validate_article_knowledge_packages(root, errors, [])
            self.assertTrue(any("未完整复用Claim" in item for item in errors))

    def test_writing_ready_gate_rejects_the_same_package_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = self._write_package_fixture(
                root,
                theme_key="product:packaging-applications-watch",
                claim_evidence="Watch Packaging.",
                material_evidence="Application类别原文：Watch Packaging.",
            )
            (task / "20_文章前知识审核.md").write_text(
                "# 文章前知识审核\n\n- 可用Claim数：1\n", encoding="utf-8-sig"
            )
            errors = article_package_errors(task)
            self.assertTrue(any("主题不匹配" in item for item in errors))
            self.assertTrue(any("中文管理说明" in item for item in errors))

    def test_recovery_repairs_evidence_mapping_hash_and_claim_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = self._write_package_fixture(root)
            (task / "20_文章前知识审核.md").write_text(
                "# 文章前知识审核\n\n- 可用Claim数：0\n", encoding="utf-8-sig"
            )
            material = task / "30_本篇知识库资料.md"
            material.write_text(
                material.read_text(encoding="utf-8-sig").replace(
                    "> Application Cosmetic Packaging.",
                    "Application Cosmetic Packaging.",
                ),
                encoding="utf-8-sig",
            )
            index = task / "35_写作素材来源索引.md"
            index.write_text(
                index.read_text(encoding="utf-8-sig").replace(
                    "写作素材SHA-256：", "写作素材SHA-256：wrong-"
                ),
                encoding="utf-8-sig",
            )
            result = recover_task(task)
            self.assertTrue(result.changed_any)
            self.assertFalse(any("35记录的30哈希不匹配" in item for item in result.after_errors))
            self.assertFalse(any("30证据正文未逐字" in item for item in result.after_errors))
            self.assertFalse(any("20与35的可用Claim数不一致" in item for item in result.after_errors))
            self.assertIn("> Application Cosmetic Packaging.", material.read_text(encoding="utf-8-sig"))
            self.assertIn("- 可用Claim数：1", (task / "20_文章前知识审核.md").read_text(encoding="utf-8-sig"))
            self.assertNotIn("wrong-", index.read_text(encoding="utf-8-sig"))

    def test_recovery_repairs_unique_website_claim_source_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / "04_文章任务/10_进行中/ART-001_Web"
            task.mkdir(parents=True)
            formal = root / "03_正式知识/10_客户知识/20_产品介绍/formal.md"
            formal.parent.mkdir(parents=True)
            formal.write_text(
                "# Formal\n\n### CLM-WEB-001｜网页事实\n\n"
                "- Claim ID：CLM-WEB-001\n"
                "- Claim：网页事实\n"
                "- 来源链接：https://example.test/page\n"
                "- 精确位置：正文第1段\n\n"
                "### 最小原文证据\n> Web evidence text.\n",
                encoding="utf-8-sig",
            )
            (task / "10_文章知识需求.md").write_text(
                "# 文章知识需求\n\n- 文章ID：ART-001\n- 当前版本：v1\n",
                encoding="utf-8-sig",
            )
            (task / "15_检索与知识准备记录.md").write_text(
                "## 官网正文核验\n\n"
                "| 大纲章节/知识问题 | 页面名称与最终具体URL | 获取日期 | 正文位置 | 最小连续原文 | 候选事实ID或未命中 | 处置结果 |\n"
                "|---|---|---|---|---|---|---|\n"
                "| 网页事实 | Web page；https://example.test/page | 2026-09-29 | 正文第1段 | Web evidence text. | CF-001 | 已读取 |\n\n"
                "## 候选事实处置明细\n\n"
                "| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n"
                "|---|---|---|---|---|\n"
                "| CF-001 | 网页事实 | 旧来源记录 | 复用已有Formal Claim | CLM-WEB-001 |\n",
                encoding="utf-8-sig",
            )
            material = task / "30_本篇知识库资料.md"
            material.write_text(
                "# 本篇写作素材包\n\n- 文章ID：ART-001\n- 文章版本：v1\n"
                "- 资料视图：写作素材包\n- 资料版本：v1\n- 生成日期：2026-09-29\n"
                "- 目标语言：English\n- 对应大纲：[[10_文章知识需求.md]]\n- 使用对象：写作流程\n\n"
                "## 一、可直接用于正文的事实\n\n### 网页事实\n\n"
                "##### 证据正文（供Faithfulness核验）\n\n> Web evidence text.\n\n"
                "- 来源与精确位置：https://example.test/page 正文第1段\n\n"
                "## 二、可直接采用的英文表达\n\n无\n\n## 三、可使用的数据表\n\n无\n\n"
                "## 四、按大纲使用\n\n无\n\n## 五、仅供生成控制（不得写入正文）\n\n无\n\n"
                "## 六、缺少资料的章节及建议处理方式\n\n无\n",
                encoding="utf-8-sig",
            )
            material_line = next(
                index for index, line in enumerate(material.read_text(encoding="utf-8-sig").splitlines(), 1)
                if line.startswith("> Web evidence text.")
            )
            (task / "35_写作素材来源索引.md").write_text(
                "# 写作素材来源索引\n\n- 文章ID：ART-001\n- 文章版本：v1\n"
                "- 索引版本：v1\n- 生成日期：2026-09-29\n- 对应写作素材：[[30_本篇知识库资料.md]]\n"
                "- 写作素材SHA-256：wrong\n- 用途：内部追溯\n\n## 写作素材到正式知识映射\n\n"
                "| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |\n"
                "|---:|---:|---|---|---|---|---|\n"
                f"| {material_line} | {material_line} | 网页事实 | CLM-WEB-001 | 网页事实 | [[03_正式知识/10_客户知识/20_产品介绍/formal.md]] | https://example.test/page |\n\n"
                "## 写作事实输入确认\n\n- 唯一事实输入：[[30_本篇知识库资料.md]]\n",
                encoding="utf-8-sig",
            )

            result = recover_task(task)
            self.assertIn("15_检索与知识准备记录.md", result.changed)
            retrieval = (task / "15_检索与知识准备记录.md").read_text(encoding="utf-8-sig")
            self.assertIn("https://example.test/page；正文第1段", retrieval)

    def test_recovery_keeps_ambiguous_claim_block_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = self._write_package_fixture(root)
            (task / "20_文章前知识审核.md").write_text(
                "# 文章前知识审核\n\n- 可用Claim数：1\n", encoding="utf-8-sig"
            )
            formal = root / "03_正式知识/10_客户知识/20_产品介绍/second.md"
            formal.write_text(
                "# Second\n\n### CLM-TEST-002｜测试\n\n"
                + self.claim_block("CLM-TEST-002", "Application Cosmetic Packaging."),
                encoding="utf-8-sig",
            )
            material = task / "30_本篇知识库资料.md"
            material.write_text(
                material.read_text(encoding="utf-8-sig").replace(
                    "> Application Cosmetic Packaging.",
                    "Application Cosmetic Packaging.",
                ),
                encoding="utf-8-sig",
            )
            result = recover_task(task)
            # v0.6.1 may repair deterministic metadata/hash/mapping fields while
            # preserving the unresolved semantic Claim ambiguity.
            self.assertTrue(result.changed_any)
            self.assertTrue(any("无法唯一对应Formal Claim" in item for item in result.unresolved))
            self.assertTrue(result.after_errors)
            self.assertNotIn("> Application Cosmetic Packaging.", material.read_text(encoding="utf-8-sig"))

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
