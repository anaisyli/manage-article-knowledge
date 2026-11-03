"""Regressions for batch/gate/guard paths that made agents loop or stop early.

Each test reproduces a path observed on a real temporary project: the receipt
must name the actual blocker for the actual article, a blocked permit must not
be reported as issued, and the end-of-turn guard must neither crash on array
checkpoints nor treat finished knowledge work as pending.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import writing_bridge as bridge  # noqa: E402
import template_contract  # noqa: E402
import run_knowledge_workflow as workflow  # noqa: E402
import workflow_guard  # noqa: E402


TEST_ROOT = Path(r"D:\01 测试项目\mak-v063-loop-regressions")
BATCH = "B-LOOP"
OPEN_SHEET = """# 文章前问题与处理单

- 文章ID：{article_id}
- 文章版本：{version}
- 模板版本：v0.6-20260907.1
- 文章标题：测试文章
- 生成日期：2026-10-22
- 当前状态：等待人工处理
- 当前影响：客户资料与官网对交期说法不一致，暂不能交付文章输入
- 需要处理人：内容运营
- 升级顺序：视觉核验类先由Codex调用MinerU并对照原始PDF/PPT；仍不确定或其他文章阻塞先交内容运营；内容运营明确无法处理后退回项目负责人（用户）；仅在用户指定后交AI知识库专员
- 处理完成后：Codex自动复核并从指定步骤继续，不需要回复“继续”
- 文章任务文件：[[10_文章知识需求.md]] | [[15_检索与知识准备记录.md]] | [[20_文章前知识审核.md]] | [[30_本篇知识库资料.md]] | [[35_写作素材来源索引.md]]
- 当前待办：[[../../../01_工作台/20_当前待办.md]]
- 文章前审核：[[20_文章前知识审核.md]]

## 需要处理的问题

| 问题ID | 发生了什么 | 对文章的影响 | Codex已自动处理 | 需要决定或提供什么 | 可选方案与依据 | 证据与关联入口 |
|---|---|---|---|---|---|---|
| Q-001 | 客户资料与官网对交期说法不一致 | 交期事实暂不能写入 | 已核对两处原文 | 请确认交期以哪份资料为准 | 以客户文件为准或删去交期 | 无，并说明为什么只属于文章业务决定：仅涉及本篇是否写交期 |

## 决定与材料记录

- 决定/提供内容：
- 决定人：
- 决定日期：
- 适用范围：

## 自动恢复

- 返回步骤：文章前审核
- 恢复条件：内容运营给出交期依据
- 自动执行方：Codex
- 复核结果：待复核
- 下一产物：[[20_文章前知识审核.md]]
"""


class _IsolatedTemporaryDirectory:
    def __init__(self, *args, **kwargs):
        self.path = TEST_ROOT / uuid.uuid4().hex
        self.path.mkdir(parents=True)
        self.name = str(self.path)

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        self.cleanup()

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)


class LoopRegressionTests(unittest.TestCase):
    """Build one batch project whose article needs 30/35 derived, then copy it per test."""

    base: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TEST_ROOT / ("base-" + uuid.uuid4().hex)
        cls.store.mkdir(parents=True)
        original = template_contract.validate_task_templates
        captured: list[Path] = []

        def capture(task, **kwargs):
            errors = original(task, **kwargs)
            record = task / "15_检索与知识准备记录.md"
            if not captured and not errors and record.is_file() and "知识准备记录协议：PR-1" in record.read_text(encoding="utf-8"):
                target = cls.store / task.parents[2].name
                shutil.copytree(task.parents[2], target)
                captured.append(target / task.relative_to(task.parents[2]))
            return errors

        with patch.object(template_contract, "validate_task_templates", side_effect=capture), \
                patch.object(bridge.tempfile, "TemporaryDirectory", _IsolatedTemporaryDirectory), \
                contextlib.redirect_stdout(io.StringIO()):
            bridge.self_test()
        if not captured:
            raise unittest.SkipTest("writing_bridge自测未生成可用的PR-1样例项目")
        task = captured[0]
        cls.base = task.parents[2]
        request = task / "10_文章知识需求.md"
        old_hash = hashlib.sha256(request.read_bytes()).hexdigest()
        text = request.read_text(encoding="utf-8").replace("- 批次ID：不适用", f"- 批次ID：{BATCH}").replace("- 目标语言：中文", "- 目标语言：English")
        request.write_text(text, encoding="utf-8")
        cls.article_id = bridge.field(text, "文章ID")
        cls.version = bridge.field(text, "当前版本")
        run_id = "research-loop-run"
        (task / "知识检索运行.json").write_text(json.dumps({
            "article_id": cls.article_id, "article_version": cls.version,
            "research_run_id": run_id, "workflow_entry": "run_outline_refresh.py"}), encoding="utf-8")
        for name in ("15_检索与知识准备记录.md", "20_文章前知识审核.md"):
            path = task / name
            path.write_text(path.read_text(encoding="utf-8").replace(old_hash, hashlib.sha256(request.read_bytes()).hexdigest())
                            .replace("research-self-test-001", run_id), encoding="utf-8")
        manifest = task / "官网正文抓取凭证.json"
        records = json.loads(manifest.read_text(encoding="utf-8"))
        for record in records:
            record["refresh_run_id"] = run_id
            record["fetched_at"] = record["fetched_date"] + "T00:00:00+00:00"
        manifest.write_text(json.dumps(records), encoding="utf-8")
        bridge.register_batch_request(cls.base, BATCH, bridge.batch_article_from_task(cls.base, cls.article_id))
        for name in ("30_本篇知识库资料.md", "35_写作素材来源索引.md"):
            (task / name).unlink()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.store, ignore_errors=True)

    def setUp(self) -> None:
        self.work = TEST_ROOT / ("case-" + uuid.uuid4().hex)
        self.root = self.work / self.base.name
        shutil.copytree(self.base, self.root)
        self.addCleanup(shutil.rmtree, self.work, True)

    def run_batch(self) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return workflow.run_workflow(self.root, BATCH)

    def task(self) -> Path:
        return bridge.current_task(self.root, self.article_id)

    def issued_task(self) -> Path:
        result = self.run_batch()
        self.assertEqual(result["workflow_state"], "writing_ready_issued", result)
        task = self.task()
        self.assertEqual(task.parent.name, "20_等待终稿")
        self.assertTrue((task / "writing_ready.json").is_file())
        return task

    def guard_data(self) -> dict:
        ledger = workflow.resolve_ledger(self.root, BATCH)
        return {"project": str(self.root), "batch_id": BATCH, "ledger": str(ledger),
                "receipt": str(workflow.state_path_for(ledger)), "scope": "knowledge", "completions": {},
                "articles": workflow_guard.identities(json.loads(ledger.read_text(encoding="utf-8")))}

    # 1. A blocked writing gate must not be reported as an issued permit.
    def test_blocked_issue_is_not_counted_as_issued(self) -> None:
        task = self.issued_task()
        import issue_writing_ready

        def refuse(args: argparse.Namespace) -> int:
            return issue_writing_ready.blocked(task, ["测试：签发门禁拒绝"])

        with patch.object(issue_writing_ready, "issue", side_effect=refuse), contextlib.redirect_stdout(io.StringIO()):
            handoff = workflow.advance_and_issue_ready(self.root, [{"article_id": self.article_id}])
        self.assertEqual(handoff["issued"], [], handoff)
        self.assertEqual(handoff["blocked"][0]["article_id"], self.article_id)
        self.assertIn("测试：签发门禁拒绝", handoff["blocked"][0]["errors"])
        self.assertFalse((task / "writing_ready.json").exists())

    # 2/3. An open sheet on a permitted task: name it, revoke the permit, pause.
    def test_open_problem_sheet_is_needs_human_and_revokes_permit(self) -> None:
        task = self.issued_task()
        (task / "文章前问题与处理单.md").write_text(
            OPEN_SHEET.format(article_id=self.article_id, version=self.version), encoding="utf-8")
        result = self.run_batch()
        self.assertEqual(result["workflow_state"], "needs_human", result)
        self.assertTrue(result["terminal"], result)
        article = result["articles"][0]
        self.assertEqual(article["state"], "needs_human", article)
        self.assertIn("请确认交期以哪份资料为准", article["human_message"])
        self.assertEqual(result["pending_steps"][0]["article_id"], self.article_id)
        self.assertNotIn("issued", json.dumps(result.get("handoff", {}).get("issued", [])))
        self.assertFalse((task / "writing_ready.json").exists(), "过期写作许可必须撤销")
        gate = json.loads((task / "writing_gate_result.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["writing_gate_status"], "blocked")
        self.assertEqual(gate["handoff_event"], "needs_human")

    # 2. A non-deliverable 20 conclusion must appear on the article itself.
    def test_waiting_conclusion_is_reported_on_the_article(self) -> None:
        audit = next(self.root.rglob("20_文章前知识审核.md"))
        audit.write_text(audit.read_text(encoding="utf-8").replace("- 结论：自动通过", "- 结论：等待内容运营处理"), encoding="utf-8")
        result = self.run_batch()
        self.assertNotIn(result["workflow_state"], {"writing_ready_issued", "needs_human"}, result)
        article = result["articles"][0]
        self.assertNotEqual(article["state"], "ready_candidate", article)
        self.assertTrue(any("文章前审核结论尚不可交付：等待内容运营处理" in error for error in article["errors"]), article)
        self.assertEqual([step["article_id"] for step in result["pending_steps"]], [self.article_id])
        self.assertFalse(any("模板、Claim、证据正文、映射、批次或覆盖视图仍有问题" in error for error in result["errors"]))

    # 4. An article past the writing gate is finished knowledge work, not missing.
    def test_article_after_final_is_not_reported_missing(self) -> None:
        task = self.issued_task()
        target = self.root / "04_文章任务/30_等待Faithfulness" / task.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(task), str(target))
        result = self.run_batch()
        article = result["articles"][0]
        self.assertEqual(article["state"], "beyond_knowledge_stage", article)
        self.assertEqual(article["errors"], [])
        self.assertEqual(result["errors"], [], result)
        self.assertEqual(result["pending_steps"], [])
        self.assertFalse(any("没有唯一当前活动任务" in str(item) for item in result.get("capture_sync", {}).get("errors", [])))

    # 5. The guard must fingerprint array checkpoints such as the capture manifest.
    def test_guard_reads_array_capture_manifest(self) -> None:
        task = self.issued_task()
        self.assertIsInstance(json.loads((task / "官网正文抓取凭证.json").read_text(encoding="utf-8")), list)
        done, pending, _ = workflow_guard.inspect(self.guard_data())
        self.assertEqual((done, pending), ([self.article_id], []))

    # 6. Knowledge scope: a task in 30/40 already met the knowledge goal.
    def test_guard_knowledge_scope_counts_post_final_article_as_done(self) -> None:
        task = self.issued_task()
        target = self.root / "04_文章任务/30_等待Faithfulness" / task.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(task), str(target))
        done, pending, _ = workflow_guard.inspect(self.guard_data())
        self.assertEqual((done, pending), ([self.article_id], []))

    # 3. The guard turns a needs_human receipt into the real question, not "no progress".
    def test_guard_pauses_with_human_question(self) -> None:
        task = self.issued_task()
        (task / "文章前问题与处理单.md").write_text(
            OPEN_SHEET.format(article_id=self.article_id, version=self.version), encoding="utf-8")
        self.run_batch()
        registry = self.work / "guard-registry"
        with contextlib.redirect_stdout(io.StringIO()):
            bound = workflow_guard.bind(self.root, BATCH, scope="knowledge", session_id="loop-test", root=registry)
        self.assertTrue(bound["bound"])
        decision = workflow_guard.check({"session_id": "loop-test", "hook_event_name": "Stop"}, root=registry)
        reason = decision.get("reason", "")
        self.assertIn("请确认交期以哪份资料为准", reason)
        self.assertNotIn("连续几次续跑没有产生实质进展", reason)


if __name__ == "__main__":
    unittest.main()
