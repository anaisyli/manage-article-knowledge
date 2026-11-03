"""PR-2: one merged 20 replaces 15+20 without weakening any existing gate."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import task_records  # noqa: E402
from capture_website_evidence import append_record  # noqa: E402
from task_records import (  # noqa: E402
    AUDIT, RETRIEVAL, governance_rows, is_merged, legacy_views, read_record, record_is_file, structure_errors,
)

RUN = "research-ART-001-v1-test"
URL = "https://example.com/gift-box/"
EXCERPT = "This custom gift box can be customized in size, paper material and insert layout."
REAL_PROJECT = Path(r"D:\Obsidian\企业知识库\P-005_杰睿包装知识库_v0.6")


def evidence(question: str) -> dict:
    normalized = re.sub(r"\s+", " ", EXCERPT).strip()
    return {
        "final_url": URL, "fetched_date": "2026-10-20", "title": "Gift box", "response_sha256": "a" * 64,
        "refresh_run_id": RUN, "question": question, "position": "Description / paragraph 3",
        "excerpt": EXCERPT, "excerpt_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
        "website_id": "PRIMARY-WEBSITE", "source_type": "客户官网", "block_id": "B003", "block_tag": "p",
        "heading_path": ["Gift box"], "block_text": EXCERPT + " More text.",
    }


REQUEST = """# 文章知识需求

- 文章ID：ART-001
- 当前版本：v1
- 知识准备记录协议：PR-2
- 大纲ID：OL-1
- 大纲版本：v1
- 重写模式：not_applicable

## 大纲

- 盒型选择
"""

MERGED = """# 知识准备与文章前审核

- 文章ID：ART-001
- 文章版本：v1
- 模板版本：v0.6-20260907.1
- 知识准备记录协议：PR-2
- 知识准备模式：new_article
- 大纲ID：OL-1
- 大纲版本：v1
- 重写模式：not_applicable
- 基线文章版本：不适用
- 官网正文抓取凭证：官网正文抓取凭证.json
- MAT依赖处理：无
- 审核日期：2026-10-20
- 结论：带明确排除通过
- 明确排除：固定尺寸和交期
- 未解决但不阻塞事项：无
- 计划写作素材：30_本篇知识库资料.md
- 计划写作素材来源索引：35_写作素材来源索引.md
- 本轮知识检索运行ID：research-ART-001-v1-test

## 一、固定检索层状态

| 检索层 | 当前状态 | 结果或未查原因 | 下一步 |
|---|---|---|---|
| 已有正式Claim | 已检索并命中 | CLM-T-001 | 复用 |
| 客户源资料索引 | 已检索未命中 | 无随文原件 | 不新增 |
| 客户官网 | 已检索并命中 | 读取EV-001 | 复用凭证 |
| 已有外部公共Claim | 已检索未命中 | 本篇不需要 | 保持 |
| 新外部调研 | 未触发 | 已覆盖 | 不调研 |

## 二、候选事实

| 候选事实ID | 独立事实摘要 | 来源 | 支持的大纲问题 | 处置结果 | Formal Claim或排除/治理入口 | 当前归类模块 | Claim动作 | 处置依据 |
|---|---|---|---|---|---|---|---|---|
| CF-001 | 指定礼盒可调尺寸、纸材和内托 | EV-001 | 标题、主问题、盒型选择 | 复用已有Formal Claim | CLM-T-001 | 产品介绍 | 复用 | 只限指定产品 |

## 三、大纲逐项覆盖与审核

| 大纲章节 | 覆盖状态 | 候选事实ID | 覆盖说明与边界 | 缺口或治理事项 | 审核结论 | 本篇写法 |
|---|---|---|---|---|---|---|
| 标题 | 已覆盖 | CF-001 | 产品范围有明确边界 | 无 | 有明确边界 | 按Claim范围写 |
| 主问题 | 已覆盖 | CF-001 | 定制选项有证据 | 无 | 有明确边界 | 只写Claim |
| 盒型选择 | 已覆盖 | CF-001 | 支持尺寸与内托 | 无 | 有明确边界 | 样品检查建议 |

## 四、CUS / ANM核验与审核

### 检测结果

| 检测对象 | 分类结论 | 事项入口 | 本篇处理 |
|---|---|---|---|
| CUS候选检测 | 未触发 | 无 | 按证据使用 |
| ANM异常检测 | 未触发 | 无 | 按证据使用 |

### 逐项核验

| 核验ID | 检测对象 | 检测类别 | 核验对象与范围 | 来源指针 | 核对结论 | 判断依据 | 事项入口 | 本篇处理 |
|---|---|---|---|---|---|---|---|---|
| GC-001 | CUS候选检测 | 客户能力 | 指定礼盒定制选项 | EV-001 | 已核验 | 官网连续正文直接陈述 | 无 | 按证据使用指定产品范围 |
| GC-002 | CUS候选检测 | 认证 | 本篇不涉及 | — | 不适用 | 大纲无认证问题 | 无 | 不涉及认证 |
| GC-003 | CUS候选检测 | 规格 | 指定礼盒尺寸可调 | EV-001 | 已核验 | 官网连续正文陈述尺寸可调 | 无 | 按证据使用：不写具体尺寸 |

## 五、缺口与特殊资料

### 本轮待调研缺口

- 本轮待调研缺口：无（客户Claim已覆盖）

### MAT依赖与资料选择

- MAT依赖与资料选择：无（本篇无版本候选）

### 复杂资料处理与原件核对

- 复杂资料处理与原件核对：无（本篇没有可能相关复杂资料）

## 六、结论说明

指定礼盒的定制选项可用，不写固定尺寸和交期。
"""


class MergedRecordTests(unittest.TestCase):
    def make_task(self, root: Path, merged: str = MERGED) -> Path:
        task = root / "P-T" / "04_文章任务" / "10_进行中" / "ART-001_Test"
        task.mkdir(parents=True)
        (task / "10_文章知识需求.md").write_text(REQUEST, encoding="utf-8")
        (task / AUDIT).write_text(merged, encoding="utf-8")
        manifest = [evidence("标题与主问题"), evidence("盒型选择")]
        (task / "官网正文抓取凭证.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return task

    def test_detection_follows_the_files(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp))
            self.assertTrue(is_merged(task))
            self.assertTrue(record_is_file(task / RETRIEVAL))
            (task / AUDIT).write_text("# 文章前知识审核\n", encoding="utf-8")
            (task / RETRIEVAL).write_text("# 检索与知识准备记录\n", encoding="utf-8")
            # 10 says PR-2 but the records were written as 15+20: legacy rules apply.
            self.assertFalse(is_merged(task))
            self.assertEqual(read_record(task / RETRIEVAL), "# 检索与知识准备记录\n")

    def test_clean_merged_record_passes_structure_and_governance(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp))
            self.assertEqual(structure_errors(task), [])
            self.assertEqual([errs for _row, errs in governance_rows(task) if errs], [])

    def test_views_fill_mechanical_fields_from_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp))
            retrieval, audit = legacy_views(task)
            # URL, date, block and excerpt come from the manifest, not the record.
            self.assertIn(URL, retrieval)
            self.assertIn(EXCERPT, retrieval)
            self.assertIn("2026-10-20", retrieval)
            self.assertIn("同一候选事实明确支持多个问题", retrieval)
            self.assertRegex(retrieval, r"\| 盒型选择 \| 支持尺寸与内托 \| CF-001 \| CF-001 \| 1 \| 1 \|")
            self.assertIn("- 可用Claim数：1", audit)
            self.assertNotIn(task_records.VIEW_MARKER, (task / AUDIT).read_text(encoding="utf-8"))

    def test_outline_refresh_declaration_in_section_one_reaches_the_view(self):
        # P-005-20261026: the declaration sat under 一 as prose, the view kept only 一's table,
        # and the legacy gate reported "固定大纲重写必须声明知识输入……" although 20 had it.
        declaration = "本轮知识上下文从空白开始，仅使用当前已确认大纲、当前批次证据账本和当前可用 Formal Claim。"
        refresh = MERGED.replace("- 知识准备模式：new_article", "- 知识准备模式：outline_refresh")
        in_prose = refresh.replace("## 二、候选事实", declaration + "\n\n## 二、候选事实")
        in_cell = refresh.replace("| 新外部调研 | 未触发 | 已覆盖 | 不调研 |",
                                  f"| 新外部调研 | 未触发 | {declaration} | 不调研 |")
        for merged in (in_prose, in_cell):
            with tempfile.TemporaryDirectory() as temp:
                retrieval, _ = legacy_views(self.make_task(Path(temp), merged))
            self.assertIn(declaration, retrieval)
            self.assertNotIn(f"| {declaration}", retrieval.split("## 本轮知识准备结论", 1)[1])
        with tempfile.TemporaryDirectory() as temp:
            retrieval, _ = legacy_views(self.make_task(Path(temp), refresh))
        self.assertNotIn(task_records.FRESH_CONTEXT, retrieval)  # no declaration anywhere: the gate still fires

    def test_structure_errors_catch_shape_and_value_defects(self):
        cases = {
            "缺少小节": MERGED.replace("### MAT依赖与资料选择\n\n- MAT依赖与资料选择：无（本篇无版本候选）\n", ""),
            "没有记录时写“无”": MERGED.replace("- 本轮待调研缺口：无（客户Claim已覆盖）", "- 本轮待调研缺口：没有"),
            "覆盖状态须为": MERGED.replace("| 盒型选择 | 已覆盖 |", "| 盒型选择 | 差不多 |"),
            "不在当前官网正文抓取凭证中": MERGED.replace("| EV-001 | 标题、主问题", "| EV-009 | 标题、主问题"),
            "不存在的候选事实": MERGED.replace("| 盒型选择 | 已覆盖 | CF-001 |", "| 盒型选择 | 已覆盖 | CF-007 |"),
        }
        for expected, text in cases.items():
            with self.subTest(expected), tempfile.TemporaryDirectory() as temp:
                task = self.make_task(Path(temp), text)
                self.assertTrue(any(expected in e for e in structure_errors(task)), structure_errors(task))

    def test_separate_15_and_saved_view_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp))
            (task / AUDIT).write_text(MERGED + "\n" + task_records.VIEW_MARKER + "\n", encoding="utf-8")
            self.assertTrue(any("兼容校验视图" in e for e in structure_errors(task)))

    def test_gc_pointer_rules(self):
        cases = {
            "需求范围只能支持不适用": "| GC-002 | CUS候选检测 | 认证 | 认证范围 | 10#大纲 | 已核验 | 大纲无认证问题 | 无 | 不涉及认证 |",
            "才可不写来源指针": "| GC-002 | CUS候选检测 | 认证 | 认证范围 | — | 不适用 | 大纲无认证问题 | 无 | 不涉及认证 |",
            "无法识别的来源指针": "| GC-002 | CUS候选检测 | 认证 | 认证范围 | 官网凭证 | 不适用 | 大纲无认证问题 | 无 | 不涉及认证 |",
            "不在当前官网正文抓取凭证中": "| GC-002 | CUS候选检测 | 认证 | 认证范围 | EV-007 | 不适用 | 大纲无认证问题 | 无 | 不涉及认证 |",
            "不适用须说明该类别": "| GC-002 | CUS候选检测 | 认证 | 本篇不涉及 | — | 不适用 | 大纲无此问题 | 无 | 不涉及 |",
        }
        original = "| GC-002 | CUS候选检测 | 认证 | 本篇不涉及 | — | 不适用 | 大纲无认证问题 | 无 | 不涉及认证 |"
        for expected, row in cases.items():
            with self.subTest(expected), tempfile.TemporaryDirectory() as temp:
                task = self.make_task(Path(temp), MERGED.replace(original, row))
                errors = [e for _row, errs in governance_rows(task) for e in errs]
                self.assertTrue(any(expected in e for e in errors), errors)

    def test_changed_evidence_fails_the_pointer_check(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp))
            manifest = json.loads((task / "官网正文抓取凭证.json").read_text(encoding="utf-8"))
            manifest[0]["excerpt"] = "Tampered excerpt that no longer matches the hash."
            (task / "官网正文抓取凭证.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            errors = [e for _row, errs in governance_rows(task) for e in errs]
            self.assertTrue(any("GC-001" in e and "指纹" in e for e in errors), errors)

    def test_request_pointer_to_existing_section_resolves(self):
        row = "| GC-002 | CUS候选检测 | 认证 | 认证范围 | 10#大纲 | 不适用 | 大纲无认证问题 | 无 | 不涉及认证 |"
        original = "| GC-002 | CUS候选检测 | 认证 | 本篇不涉及 | — | 不适用 | 大纲无认证问题 | 无 | 不涉及认证 |"
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp), MERGED.replace(original, row))
            self.assertEqual([e for _row, errs in governance_rows(task) for e in errs], [])

    def test_capture_assigns_evidence_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "官网正文抓取凭证.json"
            page = {"final_url": URL, "fetched_date": "2026-10-20", "response_sha256": "a" * 64,
                    "blocks": [{"order": 3, "tag": "p", "text": EXCERPT, "heading_path": ["Gift box"]}]}
            first = append_record(manifest, page, "标题", "正文", EXCERPT, "PRIMARY-WEBSITE", "客户官网", RUN)
            second = append_record(manifest, page, "主问题", "正文", EXCERPT, "PRIMARY-WEBSITE", "客户官网", RUN)
            self.assertEqual((first["evidence_id"], second["evidence_id"]), ("EV-001", "EV-002"))

    def test_new_tasks_declare_pr2(self):
        source = (SCRIPTS / "writing_bridge.py").read_text(encoding="utf-8")
        self.assertIn('"- 知识准备记录协议：PR-2"', source)


@unittest.skipUnless(REAL_PROJECT.is_dir(), "需要本机P-005真实项目")
class RealProjectRoundTripTests(unittest.TestCase):
    """Converting real PR-1 articles must not add a gate error or recreate 15."""

    def test_real_pr1_articles_convert_without_new_errors(self):
        from article_state import article_package_errors
        from merge_preparation_record import merge_task
        from preparation_record import compact
        from recover_article_package import recover_task

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / REAL_PROJECT.name
            shutil.copytree(REAL_PROJECT, project)
            converted = 0
            for task in sorted((project / "04_文章任务/40_已完成").glob("*")):
                retrieval = task / RETRIEVAL
                if not retrieval.is_file() or not compact(retrieval.read_text(encoding="utf-8-sig")):
                    continue
                legacy_size = retrieval.stat().st_size + (task / AUDIT).stat().st_size
                before = set(article_package_errors(task))
                merge_task(task)
                converted += 1
                after = {e.replace(f"{AUDIT}（PR-2合并记录）：", f"{RETRIEVAL}：") for e in article_package_errors(task)}
                self.assertEqual(after - before, set(), task.name)
                self.assertLess((task / AUDIT).stat().st_size, legacy_size)
                recover_task(task)
                self.assertFalse((task / RETRIEVAL).exists())
            self.assertGreater(converted, 0)


if __name__ == "__main__":
    unittest.main()
