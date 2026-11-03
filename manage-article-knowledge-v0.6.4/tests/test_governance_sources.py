from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import governance_source_check as sources
from prewrite_governance import _reference_text, governance_errors


class GovernanceSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.task = self.project / "04_文章任务/10_进行中/ART-001"
        self.task.mkdir(parents=True)
        self.request = self.task / "10_文章知识需求.md"
        self.request.write_text("- 来源核验模板版本：GC-1\n\n## 大纲\n\n- 包装服务\n", encoding="utf-8")
        self.quote = "Company offers custom boxes."
        self.retrieval = self.task / "15_检索与知识准备记录.md"
        self.record = ["GC-001", "CUS候选检测", "客户能力", "定制包装能力", "官网正文", "WEB-001",
                       "https://example.com/boxes", "B001", sources.digest(self.quote.encode()), self.quote, "RUN-1", "核对客户能力"]
        self.capture = {"refresh_run_id": "RUN-1", "website_id": "WEB-001", "final_url": self.record[6],
                        "block_id": "B001", "block_text": self.quote, "excerpt": self.quote,
                        "excerpt_sha256": self.record[8], "response_sha256": sources.digest(b"HTTP response")}
        self.manifest = self.task / "官网正文抓取凭证.json"
        self.save()

    def save(self):
        self.retrieval.write_text("- 本轮知识检索运行ID：RUN-1\n\n" + sources.HEADING + "\n\n| " + " | ".join(sources.HEADER) + " |\n|" + "---|" * len(sources.HEADER) + "\n| " + " | ".join(self.record) + " |\n", encoding="utf-8")
        self.manifest.write_text(json.dumps([self.capture]), encoding="utf-8")

    def check(self, result="已核验", reason="核对客户能力"):
        return sources.record_errors(self.task, self.project, self.record[1], self.record[2],
                                     "[[15_检索与知识准备记录.md#CUS / ANM来源核验记录]] GC-001",
                                     self.record[9], result, self.record[3], reason)

    def test_real_current_capture_passes(self):
        self.assertEqual(self.check(), [])

    def test_stale_run_hash_block_and_identity_fail(self):
        for field in ("refresh_run_id", "website_id", "final_url", "block_id", "excerpt_sha256", "response_sha256", "block_text"):
            with self.subTest(field=field):
                original = self.capture[field]
                self.capture[field] = "wrong"
                self.save()
                self.assertTrue(self.check())
                self.capture[field] = original

    def test_unmanaged_note_is_rejected_even_for_legacy_tasks(self):
        note = self.task / "本轮原件核验现场.md"
        note.write_text(self.quote, encoding="utf-8")
        self.assertIsNone(_reference_text(self.task, self.project, "[[本轮原件核验现场.md]]"))
        self.record[4] = "客户原件"
        self.record[6] = "[[本轮原件核验现场.md]]"
        self.record[8] = sources.digest(note.read_bytes())
        self.save()
        self.assertTrue(self.check())

    def scope_record(self):
        self.record[4:10] = ["需求范围", "不适用", "[[10_文章知识需求.md#大纲]]", "大纲", sources.digest(self.request.read_bytes()), "- 包装服务"]
        self.record[11] = "当前大纲不涉及客户能力承诺，仅说明包装服务主题"
        self.save()

    def test_scope_only_supports_category_specific_not_applicable(self):
        self.scope_record()
        self.assertEqual(self.check("不适用", "本篇不涉及客户能力承诺"), [])
        self.assertTrue(self.check("已核验"))
        self.assertTrue(self.check("安全排除"))
        self.assertTrue(self.check("不适用", "未使用OCR"))

    def test_wrong_category_or_missing_id_fails(self):
        self.record[2] = "规格"
        self.save()
        errors = sources.record_errors(self.task, self.project, "CUS候选检测", "客户能力",
                                       "[[15_检索与知识准备记录.md#CUS / ANM来源核验记录]] GC-001", self.quote, "已核验", self.record[3], "已核对")
        self.assertTrue(any("类别" in e for e in errors))
        self.assertTrue(sources.record_errors(self.task, self.project, "CUS候选检测", "客户能力", "[[15_检索与知识准备记录.md]]", self.quote, "已核验", self.record[3], "已核对"))

    def register(self, path):
        db = self.project / "02_源资料/source-index.sqlite"
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS sources(source_id TEXT, absolute_path TEXT, sha256 TEXT)")
            conn.execute("INSERT INTO sources VALUES (?,?,?)", ("SRC-001", str(path), sources.digest(path.read_bytes())))
            conn.commit()
        finally:
            conn.close()
        self.record[4:9] = ["客户原件", "SRC-001", f"[[{path}]]", "text", sources.digest(path.read_bytes())]
        self.save()

    def test_registered_original_and_changed_original(self):
        path = self.project / "customer.txt"
        path.write_text(self.quote, encoding="utf-8")
        self.register(path)
        self.assertEqual(self.check(), [])
        path.write_text("Changed original", encoding="utf-8")
        self.assertTrue(self.check())

    def test_docx_uses_exact_paragraph_not_plain_file_decoding(self):
        path = self.project / "customer.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="urn:test"><w:body><w:p><w:r><w:t>' + self.quote + '</w:t></w:r></w:p></w:body></w:document>')
        self.register(path)
        self.record[7] = "paragraph 1"
        self.save()
        self.assertEqual(self.check(), [])
        self.record[7] = "paragraph 2"
        self.save()
        self.assertTrue(self.check())

    def test_visual_original_requires_managed_extraction_and_bound_hash(self):
        path = self.project / "image.png"
        path.write_bytes(b"image-fixture")
        self.register(path)
        extracted = self.project / "02_源资料/提取/ocr.md"
        extracted.parent.mkdir()
        extracted.write_text(self.quote, encoding="utf-8")
        self.record[4] = "客户原件视觉"
        self.record[7] = "第1页"
        self.save()
        self.retrieval.write_text(self.retrieval.read_text(encoding="utf-8") +
                                 "\n## 复杂资料处理与原件核对\n\n| 资料ID | 文件名与稳定路径 | 未索引内容/处理原因 | 与本篇关系判断 | 实际处理范围与方法 | MinerU/提取稿入口 | 原件核对位置与结论 | MAT/ANM/CUS入口 | 最终状态 |\n|---|---|---|---|---|---|---|---|---|\n" +
                                 f"| SRC-001 | {path} | 图像 | 相关 | 视觉对照 | [[{extracted}]] | 第1页已对照；提取稿SHA-256：{sources.digest(extracted.read_bytes())} | 无 | 已处理并核对 |\n", encoding="utf-8")
        self.assertEqual(self.check(), [])
        extracted.write_text(self.quote + " changed", encoding="utf-8")
        self.assertTrue(self.check())

    def test_managed_res_source_identity_and_hash(self):
        path = self.project / "02_源资料/50_外部调研证据/RES-001_topic/10_来源原文证据.md"
        path.parent.mkdir(parents=True)
        path.write_text("## 来源身份\n\n| 来源ID | 标题 |\n|---|---|\n| SRC-EXT-001 | Example |\n\n### SRC-EXT-001 原文证据\n\n> " + self.quote, encoding="utf-8")
        (path.parent / "20_调研核验记录.md").write_text("# 核验记录", encoding="utf-8")
        self.record[4:9] = ["外部RES原文", "SRC-EXT-001", f"[[{path}]]", "SRC-EXT-001 原文证据", sources.digest(path.read_bytes())]
        self.save()
        self.assertEqual(self.check(), [])
        self.record[5] = "SRC-EXT-MISSING"
        self.save()
        self.assertTrue(self.check())

    def test_scope_reuse_rebinds_only_when_quote_unchanged(self):
        self.scope_record()
        self.request.write_text(self.request.read_text(encoding="utf-8") + "\n- 当前版本：v2\n", encoding="utf-8")
        self.assertTrue(self.check("不适用", "客户能力不适用"))
        sources.rebind_reused_scope(self.task)
        self.assertEqual(self.check("不适用", "客户能力不适用"), [])
        self.request.write_text("## 大纲\n- 新要求", encoding="utf-8")
        with self.assertRaises(ValueError):
            sources.rebind_reused_scope(self.task)

    def test_trusted_staging_reads_original_registered_source(self):
        path = self.project / "customer.txt"
        path.write_text(self.quote, encoding="utf-8")
        self.register(path)
        staging = self.project / "staging"
        staging.mkdir()
        with sources.original_sources(self.project):
            self.assertEqual(sources.record_errors(
                self.task, staging, self.record[1], self.record[2],
                "[[15_检索与知识准备记录.md#CUS / ANM来源核验记录]] GC-001",
                self.quote, "已核验", self.record[3], "已核对客户能力"), [])
        self.assertTrue(sources.record_errors(
            self.task, staging, self.record[1], self.record[2],
            "[[15_检索与知识准备记录.md#CUS / ANM来源核验记录]] GC-001",
            self.quote, "已核验", self.record[3], "已核对客户能力"))

    def test_real_conflict_requires_both_source_records(self):
        self.record[1:4] = ["ANM异常检测", "来源冲突", "当前包装能力"]
        self.save()
        error = sources.record_errors(
            self.task, self.project, self.record[1], self.record[2],
            "[[15_检索与知识准备记录.md#CUS / ANM来源核验记录]] GC-001",
            self.quote, "事实异常", self.record[3], "双方能力声明冲突")
        self.assertTrue(any("双方" in e for e in error))

    def test_unknown_protocol_cannot_downgrade(self):
        self.request.write_text("- 来源核验模板版本：GC-unknown", encoding="utf-8")
        (self.task / "20_文章前知识审核.md").write_text("# 文章前知识审核", encoding="utf-8")
        self.assertTrue(any("未知来源核验" in e for e in governance_errors(self.task, self.project)))


if __name__ == "__main__":
    unittest.main()
