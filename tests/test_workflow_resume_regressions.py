"""Real temporary-project regressions for bridge identity and package resume."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manage-article-knowledge-v0.6.1" / "scripts"))
import writing_bridge as bridge
import template_contract
import batch_knowledge_run as batch
import run_knowledge_workflow as workflow
from article_state import article_package_errors
from run_outline_refresh import check_task


class BridgeResumeTests(unittest.TestCase):
    def args(self, root):
        record = root / "request.md"
        record.write_text("# Confirmed writing task\n", encoding="utf-8")
        return argparse.Namespace(
            project=root, handoff_contract_version=bridge.current_version(), external_task_key="TASK-1",
            source_path=record, source_locator="task 1", title="Packaging services",
            request_text="写一篇文章", product_or_content_object="包装服务", topic_direction="服务介绍",
            keywords="packaging", outline="- 服务范围", outline_id="OUT-1", outline_version="v1",
            outline_status="已确认", target_language="English", constraints="无",
            original_writing_requirements="遵守事实边界", current_status="可准备知识", writing_skill="writer",
            revision_mode=None, base_article_version=None, base_outline_id=None, base_outline_version=None,
            article_id=None, date="2026-10-15", batch_id="B-NEW",
        )

    def test_real_new_request_refresh_and_mode_omitted_replay(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(bridge, "sync_skill_version"), \
             patch.object(bridge, "update_integration_status"), contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp) / "P-TEST_知识库"
            root.mkdir()
            args = self.args(root)
            bridge.prepare(args)
            new_ledger = workflow.conventional_ledger(root, "B-NEW")
            article = json.loads(new_ledger.read_text(encoding="utf-8"))["articles"][0]
            self.assertEqual(article["article_version"], "v1")
            self.assertEqual(article["revision_mode"], "new_article")
            self.assertTrue(article["research_run_id"].startswith("research-"))
            original = new_ledger.read_bytes()
            bridge.prepare(args)
            article_id = article["article_id"]
            refresh = argparse.Namespace(**vars(args))
            refresh.revision_mode = "outline_refresh"
            refresh.article_id = article_id
            refresh.base_article_version = "v1"
            refresh.base_outline_id = "OUT-1"
            refresh.base_outline_version = "v1"
            refresh.batch_id = "B-REFRESH"
            refresh.request_text = "按原大纲重整知识并重写"
            bridge.prepare(refresh)
            ledger = workflow.conventional_ledger(root, "B-REFRESH")
            row = json.loads(ledger.read_text(encoding="utf-8"))["articles"][0]
            task = bridge.current_task(root, article_id)
            run = json.loads((task / "知识重整运行.json").read_text(encoding="utf-8"))
            self.assertEqual((row["article_version"], row["revision_mode"]), ("v2", "outline_refresh"))
            self.assertEqual(row["refresh_run_id"], run["refresh_run_id"])
            before = (task / "10_文章知识需求.md").read_bytes()
            archives = list((root / "90_归档").rglob("10_文章知识需求.md"))
            ledger.unlink()  # Simulate a crash after task commit, before batch registration.
            bridge.prepare(refresh)
            self.assertEqual(json.loads(ledger.read_text(encoding="utf-8"))["articles"][0], row)
            resume = argparse.Namespace(**vars(refresh))
            resume.revision_mode = None
            resume.base_article_version = resume.base_outline_id = resume.base_outline_version = None
            bridge.prepare(resume)
            self.assertEqual((task / "10_文章知识需求.md").read_bytes(), before)
            self.assertEqual(list((root / "90_归档").rglob("10_文章知识需求.md")), archives)
            self.assertFalse((task / "30_本篇知识库资料.md").exists())
            self.assertFalse((task / "35_写作素材来源索引.md").exists())
            self.assertEqual(json.loads(new_ledger.read_text(encoding="utf-8"))["articles"][0], article)
            self.assertTrue(batch.current_binding_errors(new_ledger, json.loads(new_ledger.read_text(encoding="utf-8"))))
            wrong = argparse.Namespace(**vars(refresh))
            wrong.revision_mode = "new_article"
            with self.assertRaisesRegex(SystemExit, "不能以new_article"):
                bridge.prepare(wrong)
            changed = argparse.Namespace(**vars(refresh))
            changed.title = "Changed scope"
            with self.assertRaisesRegex(SystemExit, "恢复参数变化"):
                bridge.prepare(changed)
            self.assertEqual((task / "10_文章知识需求.md").read_bytes(), before)


class PackageResumeTests(unittest.TestCase):
    def test_new_and_refresh_bootstrap_then_reissue_with_no_new_move(self):
        original = template_contract.validate_task_templates
        checked = []

        def inspect(task):
            errors = original(task)
            path = task / "15_检索与知识准备记录.md"
            if checked or errors or not path.is_file() or "知识准备记录协议：PR-1" not in path.read_text(encoding="utf-8"):
                return errors
            checked.append(True)  # Prevent recursion from the real gates below.
            for mode in ("new_article", "outline_refresh"):
                with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / task.parents[2].name
                    shutil.copytree(task.parents[2], root)
                    current = root / task.relative_to(task.parents[2])
                    req = current / "10_文章知识需求.md"
                    old_hash = hashlib.sha256(req.read_bytes()).hexdigest()
                    archive_entry = ""
                    if mode == "outline_refresh":
                        # Reproduce the reported same-batch v2 -> v3 transition,
                        # with real previous-run checkpoints already in the ledger.
                        for filename in ("10_文章知识需求.md", "15_检索与知识准备记录.md", "20_文章前知识审核.md",
                                         "30_本篇知识库资料.md", "35_写作素材来源索引.md"):
                            p = current / filename
                            p.write_text(p.read_text(encoding="utf-8").replace("- 当前版本：v1", "- 当前版本：v2").replace("- 文章版本：v1", "- 文章版本：v2"), encoding="utf-8")
                        req.write_text(req.read_text(encoding="utf-8").replace("- 批次ID：不适用", "- 批次ID：B-RESUME"), encoding="utf-8")
                        article_id = bridge.field(req.read_text(encoding="utf-8"), "文章ID")
                        previous = {"article_id": article_id, "article_version": "v2", "revision_mode": "new_article",
                                    "research_run_id": "research-self-test-001"}
                        old_evidence = {"article_ids": [article_id], "candidate_id": "CF-001", "retrieval_run_id": "research-self-test-001",
                                        "source_path_or_url": "https://old.example/source", "source_sha256": "old-hash"}
                        ledger = workflow.conventional_ledger(root, "B-RESUME")
                        ledger.parent.mkdir(parents=True, exist_ok=True)
                        ledger.write_text(json.dumps({"batch_id": "B-RESUME", "articles": [previous], "evidence": [old_evidence],
                            "capture_inbox": [{**old_evidence, "article_id": article_id}],
                            "source_reads": [{k: v for k, v in old_evidence.items() if k not in {"article_ids", "candidate_id"}}],
                            "questions": [], "governance": []}), encoding="utf-8")
                        archive = bridge.create_archive(project=root, target=current, kind="article", reason="测试版本基线", replacement_version="v3")
                        archive_entry = archive.relative_to(root).as_posix()
                    text = req.read_text(encoding="utf-8").replace("- 批次ID：不适用", "- 批次ID：B-RESUME").replace("- 目标语言：中文", "- 目标语言：English")
                    if mode == "outline_refresh":
                        text = text.replace("- 任务模式：new_article", "- 任务模式：outline_refresh").replace("- 当前版本：v2", "- 当前版本：v3")
                        text = text.replace("- 基线文章版本：不适用", "- 基线文章版本：v2").replace("- 重写模式：not_applicable", "- 重写模式：same_outline")
                        text = text.replace("- 基线文章ID：不适用", "- 基线文章ID：" + bridge.field(text, "文章ID"))
                        text = text.replace("- 基线大纲ID：不适用", "- 基线大纲ID：" + bridge.field(text, "大纲ID")).replace("- 基线大纲版本：不适用", "- 基线大纲版本：v1")
                        text = text.replace("- 旧版本归档入口：不适用", "- 旧版本归档入口：" + archive_entry)
                    req.write_text(text, encoding="utf-8")
                    article_id = bridge.field(text, "文章ID")
                    run_id = f"{'refresh' if mode == 'outline_refresh' else 'research'}-current-run"
                    version = "v3" if mode == "outline_refresh" else "v1"
                    run = {"article_id": article_id, "article_version": version,
                           ("refresh_run_id" if mode == "outline_refresh" else "research_run_id"): run_id,
                           "workflow_entry": "run_outline_refresh.py"}
                    (current / "知识检索运行.json").unlink()
                    (current / ("知识重整运行.json" if mode == "outline_refresh" else "知识检索运行.json")).write_text(json.dumps(run), encoding="utf-8")
                    for filename in ("15_检索与知识准备记录.md", "20_文章前知识审核.md"):
                        p = current / filename
                        value = p.read_text(encoding="utf-8").replace(old_hash, hashlib.sha256(req.read_bytes()).hexdigest()).replace("research-self-test-001", run_id)
                        if mode == "outline_refresh":
                            value = value.replace("- 文章版本：v2", "- 文章版本：v3").replace("- 知识准备模式：new_article", "- 知识准备模式：outline_refresh").replace("- 基线文章版本：不适用", "- 基线文章版本：v2").replace("- 重写模式：not_applicable", "- 重写模式：same_outline")
                            value = value.replace("\n## ", f"\n- 本轮知识重整运行ID：{run_id}\n- 本轮知识上下文从空白开始；不读取旧包\n\n## ", 1)
                            if filename.startswith("15"):
                                value = value.replace("\n### 官网正文核验", "\n| 客户源资料 | 已检索 | 本测试无原始文件 | 无 |\n| 关联网站 | 未命中 | 无确认关联网站 | 无 |\n| 已有外部公共Claim | 未命中 | 无相关公共Claim | 无 |\n| 新外部调研 | 未触发 | 该服务事实由官网完整覆盖 | 无 |\n\n### 官网正文核验")
                            else:
                                value = value.replace("\n\n## 大纲知识覆盖检查", "\n| 本轮知识准备结论 | [[15_检索与知识准备记录.md#本轮知识准备结论]] | 本轮已核验，候选事实处置完整 | 无 |\n\n## 大纲知识覆盖检查")
                        p.write_text(value, encoding="utf-8")
                    manifest = current / "官网正文抓取凭证.json"
                    records = json.loads(manifest.read_text(encoding="utf-8"))
                    for record in records:
                        record["refresh_run_id"] = run_id
                        record["fetched_at"] = record["fetched_date"] + "T00:00:00+00:00"
                    manifest.write_text(json.dumps(records), encoding="utf-8")
                    bridge.register_batch_request(root, "B-RESUME", bridge.batch_article_from_task(root, article_id))
                    if mode == "outline_refresh":
                        payload = json.loads(ledger.read_text(encoding="utf-8"))
                        self.assertEqual(payload["run_history"][0]["article"]["article_version"], "v2")
                        self.assertEqual(payload["run_history"][0]["evidence"], [old_evidence])
                        for key in ("evidence", "capture_inbox", "source_reads"):
                            self.assertEqual(payload[key], [])
                    for name in ("30_本篇知识库资料.md", "35_写作素材来源索引.md"):
                        (current / name).unlink()
                    if mode == "outline_refresh":
                        manifest.write_text("[]", encoding="utf-8")
                        pending = workflow.run_workflow(root, "B-RESUME")
                        self.assertEqual(pending["workflow_state"], "source_collection", pending)
                        self.assertFalse(pending["terminal"])
                        self.assertEqual(pending["pending_steps"][0]["state"], "source_collection")
                        self.assertFalse((current / "writing_ready.json").exists())
                        manifest.write_text(json.dumps(records), encoding="utf-8")
                    # Exercise real capture sync, ledger checks, staged package
                    # generation, source/EC-1/GC-1 gates and writing permission.
                    result = workflow.run_workflow(root, "B-RESUME")
                    self.assertEqual(result["workflow_state"], "writing_ready_issued", result)
                    waiting = bridge.current_task(root, article_id)
                    self.assertEqual(article_package_errors(waiting), [])
                    self.assertTrue((waiting / "writing_ready.json").is_file())
                    if mode == "outline_refresh":
                        self.assertTrue(check_task(waiting)["ok"], check_task(waiting))
                    receipt = (waiting / "writing_ready.json").read_bytes()
                    again = workflow.run_workflow(root, "B-RESUME")
                    self.assertEqual(again["workflow_state"], "writing_ready_issued", again)
                    self.assertEqual(again["handoff"]["moved"], [])
                    self.assertEqual((waiting / "writing_ready.json").read_bytes(), receipt)
                    # A second, unfinished article cannot hold back this
                    # article or force its successful package to be rebuilt.
                    other = root / "04_文章任务/10_进行中/OTHER_Unfinished"
                    other.mkdir(parents=True)
                    (other / "10_文章知识需求.md").write_text(
                        "- 文章ID：OTHER\n- 当前版本：v1\n- 任务模式：new_article\n- 目标语言：English\n", encoding="utf-8")
                    (other / "知识检索运行.json").write_text(json.dumps({
                        "article_id": "OTHER", "article_version": "v1", "research_run_id": "research-other"}), encoding="utf-8")
                    bridge.register_batch_request(root, "B-RESUME", {
                        **bridge.batch_article_from_task(root, article_id), "article_id": "OTHER", "article_version": "v1",
                        "revision_mode": "new_article", "research_run_id": "research-other", "refresh_run_id": "",
                    })
                    partial = workflow.run_workflow(root, "B-RESUME")
                    self.assertEqual(partial["workflow_state"], "partial_writing_ready", partial)
                    self.assertEqual([item["article_id"] for item in partial["handoff"]["issued"]], [article_id])
                    self.assertFalse((other / "writing_ready.json").exists())
                    self.assertEqual((waiting / "writing_ready.json").read_bytes(), receipt)
            return errors

        with patch.object(template_contract, "validate_task_templates", side_effect=inspect), contextlib.redirect_stdout(io.StringIO()):
            bridge.self_test()
        self.assertEqual(checked, [True])


if __name__ == "__main__":
    unittest.main()
