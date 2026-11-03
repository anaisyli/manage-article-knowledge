from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
import uuid
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(r"D:\01 测试项目\mak-v062-continuation-tests-20261020")
SCRIPT = ROOT / "scripts" / "run_knowledge_workflow.py"
sys.path.insert(0, str(ROOT / "scripts"))

import run_knowledge_workflow as workflow  # noqa: E402


@contextlib.contextmanager
def isolated_test_directory():
    path = TEST_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


class KnowledgeWorkflowTests(unittest.TestCase):
    def test_missing_package_receipt_requests_semantic_15_20_work_before_rerun(self):
        with isolated_test_directory() as temp:
            project = Path(temp) / 'P-TEST'
            task = project / '04_文章任务' / '10_进行中' / 'ART-001_测试文章'
            task.mkdir(parents=True)
            (task / '10_文章知识需求.md').write_text(
                '# 文章需求\n- 文章ID：ART-001\n- 当前版本：v1\n- 批次ID：B-001\n'
                '- 大纲状态：已确认\n- 简要大纲：问题一；问题二\n', encoding='utf-8')
            # Existing but skeletal records model the reported state: current
            # batch evidence exists, while the article-specific package has
            # not been semantically prepared.
            (task / '15_检索与知识准备记录.md').write_text('# 检索记录\n', encoding='utf-8')
            (task / '20_文章前知识审核.md').write_text('# 前置审核\n', encoding='utf-8')
            errors = [
                '15_检索与知识准备记录.md：大纲逐项覆盖记录尚未完成',
                '20_文章前知识审核.md：CUS / ANM复核仍待核对',
                '缺少文件：30_本篇知识库资料.md',
                '缺少文件：35_写作素材来源索引.md',
            ]
            with patch.object(workflow, 'recover_and_gate', return_value={
                'before': errors, 'after': errors,
                'recovery': {'changed': [], 'actions': [], 'unresolved': []},
            }):
                result = workflow.article_snapshot(project, {'article_id': 'ART-001'}, 2)

            self.assertEqual(result['state'], 'article_records_required')
            self.assertFalse(result['terminal'])
            action = result['next_action']
            self.assertIn('已确认大纲', action)
            self.assertIn('15', action)
            self.assertIn('20', action)
            self.assertIn('复用当前批次账本、source_reads和已核验Claim', action)
            self.assertIn('只有某个大纲问题确实没有答案', action)
            self.assertNotIn('补齐六层检索结果', action)
            self.assertNotIn('重做检索', action)
            self.assertIn('不得让恢复器猜', action)
            self.assertIn('不要空跑本入口', action)

    def test_saved_capture_without_evidence_resumes_claim_not_source_collection(self):
        with isolated_test_directory() as temp:
            project = Path(temp) / 'P-TEST'
            ledger = self.write_ledger(project)
            payload = json.loads(ledger.read_text(encoding='utf-8'))
            payload['articles'].append({'article_id': 'ART-002'})
            ledger.write_text(json.dumps(payload), encoding='utf-8')
            sync = {'errors': [], 'unresolved': [{'article_id': 'ART-001', 'candidate_id': 'CF-001',
                                                 'reason': '已保存正文；尚无唯一Formal Claim'}]}
            with patch.object(workflow, 'sync_current_website_captures', return_value=sync), \
                 patch.object(workflow, 'run_batch_validation', return_value={'payload': payload, 'errors': [], 'attempts': 1}):
                result = workflow.run_workflow(project, 'B-001')
            self.assertEqual(result['workflow_state'], 'claim_resolution')
            first, second = result['pending_steps']
            self.assertEqual(first['state'], 'claim_resolution')
            self.assertIn('CF-001', first['errors'][0])
            self.assertIn('复用当前来源凭证', first['next_action'])
            self.assertEqual(second['state'], 'source_collection')
            self.assertFalse(result['terminal'])
            saved = json.loads(workflow.state_path_for(ledger).read_text(encoding='utf-8'))
            self.assertEqual(saved['pending_steps'], result['pending_steps'])

    def test_empty_evidence_preserves_actual_capture_sync_error(self):
        with isolated_test_directory() as temp:
            project = Path(temp) / 'P-TEST'
            self.write_ledger(project)
            with patch.object(workflow, 'sync_current_website_captures',
                              return_value={'errors': ['ART-001凭证URL与Claim来源不一致'], 'unresolved': []}):
                result = workflow.run_workflow(project, 'B-001')
            pending = result['pending_steps'][0]
            self.assertIn('ART-001凭证URL与Claim来源不一致', pending['errors'])
            self.assertIn('先修复下列凭证同步错误', pending['next_action'])
            self.assertFalse(result['terminal'])

    def write_ledger(self, root: Path, batch_id: str = "B-001") -> Path:
        path = workflow.conventional_ledger(root, batch_id)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "MAK-BATCH-1.0",
                    "batch_id": batch_id,
                    "status": "collecting_requests",
                    "articles": [{"article_id": "ART-001"}],
                    "questions": [],
                    "evidence": [],
                    "governance": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_derives_ledger_and_empty_evidence_is_nonterminal(self) -> None:
        with isolated_test_directory() as temp:
            project = Path(temp) / "P-TEST_测试知识库_v0.6"
            ledger = self.write_ledger(project)
            result = workflow.run_workflow(project, "B-001")
            self.assertEqual(result["ledger"], str(ledger))
            self.assertEqual(result["workflow_state"], "source_collection")
            self.assertFalse(result["terminal"])
            self.assertIn("terminal_decision", result)
            saved = json.loads(workflow.state_path_for(ledger).read_text(encoding="utf-8"))
            self.assertFalse(saved["terminal"])
            self.assertIn("批次账本尚未形成证据记录", "\n".join(saved["errors"]))

    def test_legacy_ledger_is_found_only_by_exact_batch_id(self) -> None:
        with isolated_test_directory() as temp:
            project = Path(temp) / "P-TEST"
            root = project / "04_文章任务/批次运行"
            root.mkdir(parents=True)
            legacy = root / "legacy-name.json"
            legacy.write_text(json.dumps({"batch_id": "B-LEGACY", "evidence": [], "articles": []}), encoding="utf-8")
            self.assertEqual(workflow.resolve_ledger(project, "B-LEGACY"), legacy)
            self.assertEqual(workflow.resolve_ledger(project, "B-OTHER"), root / "B-OTHER.json")

    def test_cli_never_requires_ledger_and_reports_missing_batch_as_nonterminal(self) -> None:
        with isolated_test_directory() as temp:
            project = Path(temp) / "P-TEST"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--project", str(project), "--batch-id", "B-MISSING"],
                capture_output=True,
                text=False,
            )
            self.assertEqual(result.returncode, 0)
            payload = json.loads((result.stdout or b"").decode("utf-8", errors="replace"))
            self.assertFalse(payload["terminal"])
            self.assertEqual(payload["workflow_state"], "tool_retryable_failure")


if __name__ == "__main__":
    unittest.main()
