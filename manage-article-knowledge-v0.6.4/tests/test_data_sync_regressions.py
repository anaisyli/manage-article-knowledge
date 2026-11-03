"""Regression tests for governance data that used to depend on manual upkeep."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from import_faithfulness import METRIC_FIELDS, SUPPORT_FIELDS, supersede_current_results, write_csv  # noqa: E402
from record_knowledge_gap import FIELDS as GAP_FIELDS  # noqa: E402
from record_project_run import LEDGER_RELATIVE, validate_ledger  # noqa: E402
from update_integration_status import CONFIG_RELATIVE, update  # noqa: E402
from validate_v06_project import validate_articles, validate_feedback_details, validate_ledgers  # noqa: E402
from writing_bridge import request_document  # noqa: E402


ANM_LEDGER = """# 源文与事实异常台账

- 项目ID：P-TEST

## 当前异常

| ANM ID | 发生了什么 | 为什么有风险 | 现在怎么处理 | 原文是否修复 | 当前阶段 | 下一责任人 | 证据包入口 | 最近更新 |
|---|---|---|---|---|---|---|---|---|
| P-TEST-ANM-001 | 目录页码与产品图错配 | 可能外推材料类别 | 本批不采用 | 否 | 待判断 | 内容运营 | 本页同ID详情 | 2026-10-01 |

| P-TEST-ANM-002 | 尺寸标签与图示不同 | 单一尺寸不能唯一确定 | 本批不采用尺寸 | 否 | 待判断 | 内容运营 | 本页同ID详情 | 2026-10-02 |

## 异常详情

### P-TEST-ANM-001｜目录页码错配

- 当前阶段：待判断
- 重开条件：新版本目录到达

### P-TEST-ANM-002｜尺寸标签不一致

- 当前阶段：待判断
- 重开条件：客户提供新尺寸表
"""

SKFB_LEDGER = """# Skill反馈台账

## 当前反馈

| SKFB ID | 提出来源 | 类型 | 通俗说明 | 复现依据 | 当前阶段 | 维护负责人 | 关联项目对象入口 | 最近更新 |
|---|---|---|---|---|---|---|---|---|

## 反馈详情

## 最近Skill版本检测

- 检测结果：未变化
"""


def governance_project(temp: str) -> Path:
    project = Path(temp) / "P-TEST_知识库_v0.6"
    anm = project / "05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md"
    skfb = project / "05_数据与审核/30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md"
    for path, text in ((anm, ANM_LEDGER), (skfb, SKFB_LEDGER)):
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
    info = project / "01_工作台/10_项目基础信息.md"
    info.parent.mkdir(parents=True)
    info.write_text("# 项目基础信息\n\n- 项目ID：P-TEST\n", encoding="utf-8")
    return project


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, encoding="utf-8",
    )


class GovernanceItemTests(unittest.TestCase):
    def test_create_repairs_split_table_and_pairs_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = governance_project(temp)
            before: list[str] = []
            validate_ledgers(project, before)
            self.assertTrue(any("孤立详情" in error for error in before))
            result = run_script(
                str(SCRIPTS / "record_governance_item.py"), "--project", str(project), "--kind", "ANM",
                "--title", "客户目录规模口径不一致",
                "--set", "发生了什么=客户目录与整理稿的公司人数不同",
                "--set", "为什么有风险=无法选一方作为当前规模",
                "--set", "现在怎么处理=本批排除规模数字",
                "--set", "原文是否修复=否",
                "--set", "当前阶段=待判断",
                "--set", "下一责任人=内容运营",
                "--set", "证据包入口=本页同ID详情",
                "--detail", "重开条件=客户提供带日期的规模说明",
                "--date", "2026-10-23",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("item_id=P-TEST-ANM-003", result.stdout)
            errors: list[str] = []
            validate_ledgers(project, errors)
            self.assertEqual(errors, [])
            text = (project / "05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md").read_text(encoding="utf-8")
            self.assertIn("### P-TEST-ANM-003｜客户目录规模口径不一致", text)

            duplicate = run_script(
                str(SCRIPTS / "record_governance_item.py"), "--project", str(project), "--kind", "ANM",
                "--title", "重复登记", "--set", "发生了什么=客户目录与整理稿的公司人数不同",
                "--set", "为什么有风险=同上风险", "--set", "现在怎么处理=同上处理", "--set", "原文是否修复=否",
                "--set", "当前阶段=待判断", "--set", "下一责任人=内容运营", "--set", "证据包入口=本页同ID详情",
                "--detail", "重开条件=同上条件",
            )
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("P-TEST-ANM-003", duplicate.stderr)

    def test_update_syncs_stage_and_rejects_invalid_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = governance_project(temp)
            ok = run_script(
                str(SCRIPTS / "record_governance_item.py"), "--project", str(project), "--kind", "ANM",
                "--item-id", "P-TEST-ANM-002", "--set", "当前阶段=已完成处置（原文未修复）",
                "--append-note", "已用替代证据限定边界", "--date", "2026-10-23",
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            text = (project / "05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md").read_text(encoding="utf-8")
            self.assertIn("- 当前阶段：已完成处置（原文未修复）", text)
            self.assertIn("- 2026-10-23补充：已用替代证据限定边界", text)
            bad = run_script(
                str(SCRIPTS / "record_governance_item.py"), "--project", str(project), "--kind", "ANM",
                "--item-id", "P-TEST-ANM-001", "--set", "当前阶段=已处理",
            )
            self.assertNotEqual(bad.returncode, 0)

    def test_skfb_create_is_valid_and_stage_change_is_delegated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = governance_project(temp)
            created = run_script(
                str(SCRIPTS / "record_governance_item.py"), "--project", str(project), "--kind", "SKFB",
                "--title", "运行账本未接入主流程",
                "--set", "提出来源=Codex自动复现", "--set", "类型=数据同步缺口",
                "--set", "通俗说明=文章主流程不写运行账本", "--set", "复现依据=项目账本十月中旬后无文章事件",
                "--set", "当前阶段=自动记录，待维护判断", "--set", "维护负责人=Skill维护负责人",
                "--set", "关联项目对象入口=项目运行账本",
                "--detail", "关闭条件=专项自测与项目验证均通过", "--detail", "重开条件=再次出现漏记",
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            errors: list[str] = []
            validate_ledgers(project, errors)
            validate_feedback_details(project, errors)
            self.assertEqual([error for error in errors if "SKFB" in error], [])
            delegated = run_script(
                str(SCRIPTS / "record_governance_item.py"), "--project", str(project), "--kind", "SKFB",
                "--item-id", "P-TEST-SKFB-001", "--set", "当前阶段=已纳入维护",
            )
            self.assertNotEqual(delegated.returncode, 0)
            self.assertIn("manage_skill_feedback.py", delegated.stderr)


class GapNextActionTests(unittest.TestCase):
    def test_active_research_gap_requires_external_research_wording(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "P-TEST_知识库_v0.6/05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
            ledger.parent.mkdir(parents=True)
            with ledger.open("w", encoding="utf-8-sig", newline="") as stream:
                csv.DictWriter(stream, fieldnames=GAP_FIELDS).writeheader()
            base = [
                str(SCRIPTS / "record_knowledge_gap.py"), "--csv", str(ledger), "--gap-key", "auto",
                "--topic", "包装结构如何按产品取放动作选择内托形式", "--article-id", "ART-001",
                "--article-date", "2026-10-23", "--trigger-basis", "核心章节首次",
            ]
            rejected = run_script(*base, "--next-action", "已加入独立知识维护队列，按本组具体问题调研")
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("外部调研", rejected.stderr)
            with ledger.open("r", encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])


class RunLedgerTests(unittest.TestCase):
    def test_lifecycle_events_append_valid_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            config = project / CONFIG_RELATIVE
            config.parent.mkdir(parents=True)
            config.write_text("# 接入配置\n\n- 接入状态：已接入\n\n## 自动状态摘要\n\n", encoding="utf-8")
            update(project, "writing_ready", article_id="ART-001", article_version="v1")
            self.assertFalse((project / LEDGER_RELATIVE).exists(), "未初始化账本的目录不应被创建账本")
            (project / LEDGER_RELATIVE).parent.mkdir(parents=True)
            (project / LEDGER_RELATIVE).write_text("", encoding="utf-8")
            result = update(project, "final_received_success", article_id="ART-001", article_version="v1")
            self.assertEqual(result["run_ledger"], "appended")
            self.assertEqual(update(project, "check")["run_ledger"], "not_applicable")
            self.assertEqual(
                update(project, "final_received_success", article_id="ART-001", article_version="v1")["run_ledger"],
                "duplicate_skipped",
            )
            update(project, "faithfulness_import_failure", article_id="ART-001", article_version="v1", error="哈希不匹配")
            update(project, "faithfulness_import_failure", article_id="ART-001", article_version="v1", error="哈希不匹配")
            records = [json.loads(line) for line in (project / LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["status"] for r in records], ["success", "failed", "failed"])
            records = records[:1]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["article_ids"], ["ART-001"])
            self.assertEqual(validate_ledger(project / LEDGER_RELATIVE), [])


class SupersedeTests(unittest.TestCase):
    def test_superseded_article_leaves_claim_summary_and_validator_flags_stale_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            data = project / "05_数据与审核/10_Faithfulness"
            data.mkdir(parents=True)
            knowledge = project / "03_正式知识/10_客户知识/20_产品介绍/盒型.md"
            knowledge.parent.mkdir(parents=True)
            knowledge.write_text("# 盒型\n\n### 盒型定制范围\n\n- Claim ID：CLM-T-001\n", encoding="utf-8")
            article = project / "04_文章任务/40_已完成/ART-001_T/40_最终文章.md"
            metrics = [
                {"audit_id": "FTH-A", "article_id": "ART-001", "article_file": str(article), "status": "current", "article_date": "2026-10-01"},
                {"audit_id": "FTH-B", "article_id": "ART-002", "article_file": str(project / "missing.md"), "status": "current", "article_date": "2026-10-02"},
            ]
            support = [
                {"audit_id": "FTH-A", "article_id": "ART-001", "verdict": "supported", "formal_claim_id": "CLM-T-001"},
                {"audit_id": "FTH-B", "article_id": "ART-002", "verdict": "supported", "formal_claim_id": "CLM-T-001"},
            ]
            write_csv(data / "10_文章Faithfulness明细.csv", METRIC_FIELDS, metrics)
            write_csv(data / "20_Claim文章支撑记录.csv", SUPPORT_FIELDS, support)

            errors: list[str] = []
            validate_articles(project, metrics, errors, [])
            self.assertTrue(any("ART-002" in error and "superseded" in error for error in errors))

            self.assertEqual(supersede_current_results(project, "ART-002"), ["FTH-B"])
            self.assertEqual(supersede_current_results(project, "ART-002"), [])
            with (data / "10_文章Faithfulness明细.csv").open(encoding="utf-8-sig", newline="") as stream:
                statuses = {row["audit_id"]: row["status"] for row in csv.DictReader(stream)}
            self.assertEqual(statuses, {"FTH-A": "current", "FTH-B": "superseded"})
            summary = (data / "30_Claim文章支撑总表.md").read_text(encoding="utf-8-sig")
            row = next(line for line in summary.splitlines() if line.startswith("| CLM-T-001"))
            self.assertEqual(row.split("|")[3].strip(), "1")


class AtomicReplaceTests(unittest.TestCase):
    def test_locked_target_retries_then_cleans_up_temporary(self) -> None:
        from unittest import mock

        from atomic_replace import replace_with_retry

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "台账.md"
            target.write_text("old", encoding="utf-8")
            temporary = Path(temp) / "tmp1.tmp"
            temporary.write_text("new", encoding="utf-8")
            real_replace = Path.replace
            calls = {"n": 0}

            def flaky(self, other):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise PermissionError("locked")
                return real_replace(self, other)

            with mock.patch.object(Path, "replace", flaky):
                replace_with_retry(temporary, target, delay=0)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")

            temporary.write_text("newer", encoding="utf-8")
            with mock.patch.object(Path, "replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    replace_with_retry(temporary, target, attempts=2, delay=0)
            self.assertFalse(temporary.exists(), "失败后不得留下tmp残留")
            self.assertEqual(target.read_text(encoding="utf-8"), "new")


CLAIM_FILE = """# 盒型定制

- 知识状态：有效
- 使用前复核：{review}
- 最近核验日期：2026-10-01

### 盒型定制范围

- Claim ID：CLM-T-001
- 状态：可用
- 来源类型：客户官网
- 来源链接：https://example.com/box
- 精确位置：产品页正文第1段
- 适用范围：该盒型
- 使用边界：不外推到其他盒型

### 最小原文证据

> The box size and insert can be customized.
"""


class ClaimReusePointerTests(unittest.TestCase):
    def _project(self, temp: str, review: str) -> tuple[Path, Path]:
        project = Path(temp) / "P-TEST_知识库_v0.6"
        claim = project / "03_正式知识/10_客户知识/20_产品介绍/盒型定制.md"
        claim.parent.mkdir(parents=True)
        claim.write_text(CLAIM_FILE.format(review=review), encoding="utf-8")
        task = project / "04_文章任务/10_进行中/ART-001_T"
        task.mkdir(parents=True)
        (task / "10_文章知识需求.md").write_text("# 文章知识需求\n\n- 目标语言：中文\n", encoding="utf-8")
        return project, task

    def test_ready_claim_resolves_and_verifies_saved_evidence(self) -> None:
        from unittest import mock

        import governance_source_check
        from task_records import pointer_rows

        with tempfile.TemporaryDirectory() as temp:
            project, task = self._project(temp, "否")
            row = ["GC-001", "CUS候选检测", "客户能力", "该盒型定制范围", "CLM-T-001（复用，未回源）", "已核验", "复用说明"]
            [(legacy, error)] = pointer_rows(task, row, "RUN-1")
            self.assertEqual(error, "")
            self.assertEqual(legacy[4], "正式Claim复用")
            self.assertIn("customized", legacy[9])
            with mock.patch.object(governance_source_check, "current_run", return_value="RUN-1"):
                evidence = governance_source_check.source_excerpt(task, project, legacy)
            self.assertIn("The box size and insert can be customized.", evidence)

    def test_claim_needing_review_is_rejected(self) -> None:
        from task_records import pointer_rows

        with tempfile.TemporaryDirectory() as temp:
            project, task = self._project(temp, "是")
            row = ["GC-001", "CUS候选检测", "客户能力", "该盒型定制范围", "CLM-T-001（复用，未回源）", "已核验", "复用说明"]
            [(_, error)] = pointer_rows(task, row, "RUN-1")
            self.assertIn("不能作为未回源复用依据", error)
            [(_, bare)] = pointer_rows(task, row[:4] + ["CLM-T-001"] + row[5:], "RUN-1")
            self.assertIn("CLM-ID（复用，未回源）", bare)


class CustomerMarkerTests(unittest.TestCase):
    def test_generic_marker_requires_word_boundary(self) -> None:
        from import_faithfulness import CUSTOMER_MARKER_RE

        self.assertIsNone(CUSTOMER_MARKER_RE.search(
            "Treat that arrangement as a proposal to review with your products, rather than a layout."
        ))
        self.assertIsNone(CUSTOMER_MARKER_RE.search("Compare your services with the brief."))
        for text in ("We tailor our products to each brand.", "Our services include sampling.", "JERL offers drawers.", "杰睿包装提供打样"):
            self.assertIsNotNone(CUSTOMER_MARKER_RE.search(text), text)


class RequestTemplateTests(unittest.TestCase):
    def test_new_request_inherits_competitor_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(
                batch_id="", keywords="盒型", target_language="英文", constraints="", outline_status="已确认",
                request_text="写一篇", product_or_content_object="纸盒", topic_direction="选型",
                original_writing_requirements="无", current_status="可准备知识", writing_skill="writer",
                outline_id="O-1", outline_version="v1", external_task_key="K-1", source_locator="全文",
                outline="- 标题\n- 主问题",
            )
            text = request_document(
                args, article_id="ART-001", article_version="v1", contract_version="MAK-HANDOFF-1.4",
                source=Path(temp) / "task.md", title="纸盒选型",
            )
            self.assertIn("- 竞品信息限制：继承项目级禁止（不可放宽）", text)


if __name__ == "__main__":
    unittest.main()
