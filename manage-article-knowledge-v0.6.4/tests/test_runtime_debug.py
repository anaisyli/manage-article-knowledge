from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
import argparse
import contextlib
import io
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from run_outline_refresh import check_task
from manage_skill_feedback import transition, audit
import advance_ready_tasks
import issue_writing_ready
from handoff_contract import current_version


class RuntimeDebugTests(unittest.TestCase):
    def test_waiting_task_repeated_gate_and_changed_source(self):
        original_advance = advance_ready_tasks.advance_project
        checked = []

        def advance_and_verify(root, **kwargs):
            moved = original_advance(root, **kwargs)
            task = root / '04_文章任务/20_等待终稿/DEMO-ART-001_测试文章'
            args = argparse.Namespace(project=root, article_id='DEMO-ART-001',
                                      external_task_key='', handoff_contract_version=current_version())
            # This fixture has no project onboarding files. Keep the real
            # template, source, evidence, recovery and receipt gates active.
            with patch.object(issue_writing_ready, 'check_skill_version'), \
                 patch.object(issue_writing_ready, 'update_integration_status'), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(issue_writing_ready.issue(args), 0)
                receipt = task / 'writing_ready.json'
                before = receipt.read_bytes()
                self.assertEqual(issue_writing_ready.issue(args), 0)
                self.assertEqual(receipt.read_bytes(), before)
                formal = root / '03_正式知识/10_客户知识/demo.md'
                original = formal.read_bytes()
                formal.write_text(formal.read_text(encoding='utf-8').replace(
                    'Example Company provides custom packaging services.',
                    'Example Company provides unrelated services.'), encoding='utf-8')
                self.assertEqual(issue_writing_ready.issue(args), 2)
                result = json.loads((task / 'writing_gate_result.json').read_text(encoding='utf-8'))
                self.assertEqual(result['writing_gate_status'], 'blocked')
                self.assertIs(result['terminal'], False)
                self.assertFalse(receipt.exists(), 'blocked must revoke an older matching permission')
                formal.write_bytes(original)
                self.assertEqual(issue_writing_ready.issue(args), 0)
                material = task / '30_本篇知识库资料.md'
                material.write_text(material.read_text(encoding='utf-8') + '\n', encoding='utf-8')
                # Deterministic 35/hash drift recovers and reissues permission.
                self.assertEqual(issue_writing_ready.issue(args), 0,
                                 (task / 'writing_gate_result.json').read_text(encoding='utf-8'))
                recovered = json.loads(receipt.read_text(encoding='utf-8'))
                self.assertEqual(recovered['knowledge_sha256'], issue_writing_ready.sha256(material))
                (task / '40_最终文章.md').write_text('# 已写终稿\n', encoding='utf-8')
                material.write_text(material.read_text(encoding='utf-8') + '\nchanged\n', encoding='utf-8')
                self.assertEqual(issue_writing_ready.issue(args), 2)
                self.assertFalse(receipt.exists())
                result = json.loads((task / 'writing_gate_result.json').read_text(encoding='utf-8'))
                self.assertTrue(any('已有终稿' in e for e in result['blocked_reasons']))
            checked.append(True)
            return moved

        with patch.object(advance_ready_tasks, 'advance_project', side_effect=advance_and_verify):
            self.assertEqual(advance_ready_tasks.self_test(), 0)
        self.assertEqual(checked, [True])

    def test_refresh_checks_each_present_file_before_package_is_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp)
            (task / '10_文章知识需求.md').write_text(
                '- 文章ID：ART-001\n- 当前版本：v2\n- 任务模式：outline_refresh\n', encoding='utf-8')
            (task / '知识重整运行.json').write_text(json.dumps({
                'refresh_run_id': 'R1', 'workflow_entry': 'run_outline_refresh.py',
                'article_id': 'ART-001', 'article_version': 'v2',
            }), encoding='utf-8')
            (task / '15_检索与知识准备记录.md').write_text(
                '- 本轮知识重整运行ID：R1\n', encoding='utf-8')
            result = check_task(task)
            self.assertFalse(result['ok'])
            self.assertTrue(any('15_检索与知识准备记录.md' in e for e in result['errors']), result)
            self.assertIs(result['terminal'], False)
            self.assertEqual(result['next_owner'], 'manage-article-knowledge')

    def test_refresh_unknown_task_returns_recoverable_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            for flags in ([], ['--project', temp, '--article-id', 'NO-SUCH-ARTICLE']):
                with self.subTest(flags=flags):
                    p = subprocess.run([sys.executable, str(SCRIPTS / 'run_outline_refresh.py'), *flags],
                                       capture_output=True, text=True, encoding='utf-8')
                    self.assertEqual(p.returncode, 2)
                    result = json.loads(p.stdout)
                    self.assertIs(result['terminal'], False)
                    self.assertEqual(result['next_owner'], 'manage-article-knowledge')
                    self.assertNotIn('Traceback', p.stderr)

    def ledger(self, path):
        path.write_text(
            '# 台账\n\n## 当前反馈\n\n'
            '| SKFB ID | 当前阶段 | 最近更新 |\n|---|---|---|\n'
            '| TEST-001 | 维护中 | 2026-10-10 |\n\n'
            '## 反馈详情\n\n### TEST-001｜测试\n\n'
            '- 当前阶段：维护中\n- 下一步由谁做：负责人\n'
            '- 关闭条件：正式自测和项目验证通过\n- 重开条件：再次复现\n'
            '- 项目验证：待验证\n', encoding='utf-8')

    def test_feedback_latest_pass_supersedes_pending_history_without_erasing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.md'
            self.ledger(path)
            transition(path, 'TEST-001', '已关闭', '正式修复完成', '无',
                       '通过：专项回归', '通过：当前项目回归', '2026-10-10')
            text = path.read_text(encoding='utf-8')
            self.assertIn('- 项目验证：待验证', text)
            current = audit(path)[0]
            self.assertFalse(current['validation_contradiction'])
            self.assertFalse(current['open'])

    def test_feedback_negative_latest_validation_cannot_close(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.md'
            self.ledger(path)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                transition(path, 'TEST-001', '已关闭', '修复', '无',
                           '通过：专项', '不通过：项目失败', '2026-10-10')
            self.assertEqual(path.read_bytes(), original)

    def test_feedback_owner_preserves_literal_windows_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.md'
            self.ledger(path)
            owner = r'Codex D:\manage-article-knowledge\scripts'
            transition(path, 'TEST-001', '维护中', '继续修复', owner, None, None, '2026-10-10')
            self.assertIn(owner, path.read_text(encoding='utf-8'))

    def test_feedback_latest_failure_is_still_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.md'
            self.ledger(path)
            transition(path, 'TEST-001', '已关闭', '已验证', '无', '通过', '通过', '2026-10-10')
            transition(path, 'TEST-001', '维护中', '问题再次复现', 'Codex', '通过', '失败', '2026-10-10')
            self.assertTrue(audit(path)[0]['validation_contradiction'])
            self.assertTrue(audit(path)[0]['open'])


if __name__ == '__main__':
    unittest.main()
