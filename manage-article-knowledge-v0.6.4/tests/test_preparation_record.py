import json
import sys
import tempfile
import unittest
import subprocess
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from preparation_record import (HEADINGS, CANDIDATE_HEADER, MATERIAL_HEADER, MAT_HEADER,
                                counts, table, validation_view, protocol_errors, normalize,
                                sync_derived_counts, rows)
from template_contract import coverage_mapping_errors, website_manifest_errors, WEBSITE_EVIDENCE_HEADER
from run_outline_refresh import check_task, comparison_permitted, package_files, PACKAGE_FILES
from record_knowledge_gap import next_gap_key
import writing_bridge
import template_contract


def record(candidates=None):
    if candidates is None:
        candidates = [['CF-001', 'Packaging services.', 'https://example.com/about paragraph 1',
                       '复用已有Formal Claim', 'CLM-DEMO-001', '本轮正文核验', '客户知识', '复用', '同一服务范围']]
    bodies = {
        HEADINGS[0]: table(('检索层', '当前状态', '结果或未查原因', '下一步'), []) + '\n\n### 官网正文核验\n\n' + table(WEBSITE_EVIDENCE_HEADER, []),
        HEADINGS[1]: table(('大纲章节', '六层检索范围与结果', '命中来源与精确入口', '候选事实ID', '候选事实数', '已沉淀Claim数', '未采用事实/缺口及原因', '下一步'), [['服务', '已查正文', 'URL', 'CF-001' if candidates else '无', str(len(candidates)), str(len(candidates)), '无', '使用']]),
        HEADINGS[2]: table(CANDIDATE_HEADER, candidates),
        HEADINGS[3]: '核验表在集成测试中检查。',
        HEADINGS[4]: '### 本轮待调研缺口复核\n\n' + table(('GAP ID', '当前台账入口与状态', '本轮具体公共知识问题', '与当前大纲关系', '本轮处理和证据'), [['无'] * 5]) + '\n\n### MAT依赖与资料选择\n\n' + table(MAT_HEADER, [['无'] * 9]) + '\n\n### 复杂资料处理与原件核对\n\n' + table(MATERIAL_HEADER, [['无'] * 9]),
    }
    text = '# 检索与知识准备记录\n\n- 知识准备记录协议：PR-1\n'
    for heading in HEADINGS[:-1]:
        text += '\n## ' + heading + '\n\n' + bodies[heading] + '\n'
    return text + '\n## ' + HEADINGS[-1] + '\n\n' + table(('项目', '本轮结果'), [[k, str(v)] for k, v in counts(text).items()] + [['中文结论', '本轮回源核验完成，仅采用确认范围。']]) + '\n'


class PreparationRecordTests(unittest.TestCase):
    def test_real_package_recovery_repairs_counts_and_keeps_gate_active(self):
        from preparation_record import _update_table
        from recover_article_package import recover_task
        original = template_contract.validate_task_templates
        checked = []
        def inspect(task, **kwargs):
            errors = original(task, **kwargs)
            retrieval = task / '15_检索与知识准备记录.md'
            if not errors and retrieval.is_file() and not checked:
                text = retrieval.read_text(encoding='utf-8')
                if '- 知识准备记录协议：PR-1' in text:
                    checked.append(True)  # Recovery re-enters the real validator.
                    expected = rows(text, '大纲逐项检索与候选事实覆盖')
                    def corrupt(row):
                        if len(row) == 8:
                            row[4:6] = ['99', '99']
                        return row
                    retrieval.write_text(_update_table(text, '大纲逐项检索与候选事实覆盖', corrupt), encoding='utf-8')
                    self.assertTrue(original(task), 'bad counts must fail the real gate')
                    result = recover_task(task)
                    self.assertEqual(result.after_errors, [], result)
                    actual = rows(retrieval.read_text(encoding='utf-8'), '大纲逐项检索与候选事实覆盖')
                    self.assertEqual(actual, expected)
                    self.assertIn(retrieval.name, result.changed)
                    self.assertEqual(original(task), [])
            return errors
        with patch.object(template_contract, 'validate_task_templates', side_effect=inspect), contextlib.redirect_stdout(io.StringIO()):
            writing_bridge.self_test()
        self.assertEqual(checked, [True])

    def count_task(self, task, text):
        (task / '10_文章知识需求.md').write_text('- 知识准备记录协议：PR-1\n', encoding='utf-8')
        (task / '15_检索与知识准备记录.md').write_text(text, encoding='utf-8')
        audit = '## 知识准备充分性复核\n\n' + table(
            ('大纲章节', '候选事实数', '已沉淀Claim数', '计划纳入30的事实块数', '覆盖结论', '未采用事实/缺口及入口'),
            [['服务', '99', '99', '3', '有明确边界', '保留原范围判断']])
        (task / '20_文章前知识审核.md').write_text(audit, encoding='utf-8')

    def test_counts_deduplicate_claims_preserve_judgments_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            candidate = ['CF-001', '服务范围', 'https://example.com/about paragraph 1',
                         '复用已有Formal Claim', 'CLM-DEMO-001', '本轮正文核验', '客户知识', '复用', '同一范围']
            other = candidate[:]
            other[0] = 'CF-002'
            text = record([candidate, other]).replace('| CF-001 | 2 | 2 |', '| CF-001 CF-002 | 99 | 99 |')
            text = text.replace('| 采用事实数 | 2 |', '| 采用事实数 | 99 |')
            self.count_task(task, text)
            self.assertEqual(set(sync_derived_counts(task)), {'15_检索与知识准备记录.md', '20_文章前知识审核.md'})
            retrieval = (task / '15_检索与知识准备记录.md').read_text(encoding='utf-8')
            self.assertEqual(rows(retrieval, '大纲逐项检索与候选事实覆盖')[0][4:6], ['2', '1'])
            self.assertEqual(protocol_errors(retrieval), [])
            audit = (task / '20_文章前知识审核.md').read_text(encoding='utf-8')
            self.assertEqual(rows(audit, '知识准备充分性复核')[0],
                             ['服务', '2', '1', '3', '有明确边界', '保留原范围判断'])
            self.assertEqual(rows(retrieval, '候选事实处置明细'), [candidate, other])
            self.assertEqual(sync_derived_counts(task), [])

    def test_counts_do_not_invent_missing_refs_or_hide_duplicate_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            text = record().replace('| CF-001 | 1 | 1 |', '| CF-099 | 99 | 99 |')
            self.count_task(task, text)
            self.assertEqual(sync_derived_counts(task), [])
            self.assertEqual((task / '15_检索与知识准备记录.md').read_text(encoding='utf-8'), text)
            candidate = rows(record(), '候选事实处置明细')[0]
            duplicate = record([candidate, candidate])
            self.count_task(task, duplicate)
            self.assertEqual(sync_derived_counts(task), [])
            self.assertTrue(protocol_errors(duplicate))

    def test_zero_candidates_syncs_counts_without_changing_unanswered_conclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            self.count_task(task, record([]))
            self.assertEqual(sync_derived_counts(task), ['20_文章前知识审核.md'])
            audit = (task / '20_文章前知识审核.md').read_text(encoding='utf-8')
            self.assertEqual(rows(audit, '知识准备充分性复核')[0][1:],
                             ['0', '0', '3', '有明确边界', '保留原范围判断'])

    def test_real_bridge_pr1_gate_rejects_changed_url_hash_or_missing_receipt(self):
        original = template_contract.validate_task_templates
        checked = []
        def inspect(task, **kwargs):
            errors = original(task, **kwargs)
            path = task / '15_检索与知识准备记录.md'
            if path.exists() and '- 知识准备记录协议：PR-1' in path.read_text(encoding='utf-8') and not checked:
                self.assertEqual(errors, [])
                text = path.read_text(encoding='utf-8')
                self.assertEqual(website_manifest_errors(task, text), [])
                self.assertTrue(website_manifest_errors(task, text.replace('https://example.com/about-us/', 'https://example.com/wrong/')))
                manifest = task / '官网正文抓取凭证.json'
                before = manifest.read_bytes()
                payload = json.loads(before)
                payload[0]['excerpt_sha256'] = 'bad'
                manifest.write_text(json.dumps(payload), encoding='utf-8')
                self.assertTrue(website_manifest_errors(task, text))
                manifest.unlink()
                self.assertTrue(website_manifest_errors(task, text))
                manifest.write_bytes(before)
                checked.append(True)
            return errors
        with patch.object(template_contract, 'validate_task_templates', side_effect=inspect), contextlib.redirect_stdout(io.StringIO()):
            writing_bridge.self_test()
        self.assertEqual(checked, [True])

    def test_gap_cli_auto_and_existing_key_only(self):
        from record_knowledge_gap import read_rows
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'P-005_测试'
            path = root / '05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv'
            path.parent.mkdir(parents=True)
            args = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'scripts/record_knowledge_gap.py'), '--csv', str(path), '--topic', '纸盒湿度条件与耐用性验证方法', '--article-id', 'ART-001', '--article-date', '2026-10-14', '--trigger-basis', '核心章节首次']
            made = subprocess.run(args, capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            self.assertEqual(read_rows(path)[0]['gap_key'], 'GAP-P005-001')
            before = path.read_bytes()
            rejected = subprocess.run(args + ['--gap-key', 'invented-name'], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(before, path.read_bytes())
            updated = subprocess.run(args + ['--gap-key', 'GAP-P005-001'], capture_output=True)
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertEqual(len(read_rows(path)), 1)
    def test_six_sections_and_in_memory_view_are_idempotent(self):
        text = record()
        self.assertEqual(protocol_errors(text), [])
        expanded = validation_view(text)
        self.assertEqual(validation_view(expanded), expanded)
        self.assertNotIn('## 来源命中记录', text)
        self.assertIn('## 来源命中记录', expanded)
        self.assertTrue(protocol_errors(expanded), 'expanded view cannot be persisted')

    def test_zero_candidates_and_complete_no_gap(self):
        self.assertEqual(protocol_errors(record([])), [])
        self.assertNotIn('CF-000', record([]))

    def test_orphan_gap_and_wrong_summary_are_rejected(self):
        self.assertTrue(protocol_errors(record().replace('| 无 | 无 | 无 | 无 | 无 |', '| GAP-P005-028 | 无 | 无 | 不适用 | 无 |')))
        self.assertTrue(protocol_errors(record().replace('| 采用事实数 | 1 |', '| 采用事实数 | 2 |')))

    def test_governance_requires_real_id_and_duplicate_cf_rejected(self):
        self.assertTrue(protocol_errors(record().replace('复用已有Formal Claim', '进入治理').replace('CLM-DEMO-001', '待记录')))
        c = ['CF-001', 'fact', 'https://example.com/p', '排除', '不相关', '本轮已核对', '客户知识', '排除', '不适用当前问题']
        self.assertTrue(protocol_errors(record([c, c])))

    def test_old_package_cannot_be_a_source(self):
        self.assertTrue(protocol_errors(record().replace('https://example.com/about paragraph 1', '90_归档/v1/30_本篇知识库资料.md')))

    def test_coverage_requires_question_specific_claim_and_current35(self):
        audit = '## 大纲知识覆盖检查\n\n' + table(('大纲章节', '知识问题', '覆盖状态', '已有证据/Claim', '缺口或治理事项', '本篇处理'), [['服务', '具体服务', '已覆盖', 'CLM-DEMO-001', '无', '使用']])
        index = '## 写作素材到正式知识映射\n\n' + table(('开始', '结束', '主题', 'Claim'), [['1', '2', '服务', 'CLM-DEMO-001']])
        self.assertEqual(coverage_mapping_errors(record(), audit, index), [])
        self.assertTrue(coverage_mapping_errors(record(), audit.replace('CLM-DEMO-001', 'CLM-DEMO-002'), index))
        self.assertTrue(coverage_mapping_errors(record(), audit, index.replace('CLM-DEMO-001', 'CLM-DEMO-002')))
        partial = audit.replace('已覆盖', '部分覆盖') + '\n## 知识准备充分性复核\n\n' + table(('大纲章节', '候选', 'Claim', '块', '结论', '缺口'), [['服务', '1', '1', '1', '充分', 'GAP-P005-001']])
        self.assertTrue(coverage_mapping_errors(record(), partial, index))

    def test_conversion_preserves_unmerged_source_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            (task / '10_文章知识需求.md').write_text('- 知识准备记录协议：PR-1\n', encoding='utf-8')
            p = task / '15_检索与知识准备记录.md'
            old = record().replace('- 知识准备记录协议：PR-1\n', '')
            old += '\n## 来源命中记录\n\n' + table(('问题', '入口', '理由', '处置'), [['服务', 'https://example.com/about paragraph 1', '独有的未采用资料说明', '不删除']])
            p.write_text(old, encoding='utf-8')
            self.assertFalse(normalize(task))
            self.assertEqual(p.read_text(encoding='utf-8'), old)

    def test_postvalidation_permission_revoked_by_changes_or_failed_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            req = task / '10_文章知识需求.md'
            req.write_text('- 文章ID：ART-001\n- 当前版本：v2\n- 任务模式：outline_refresh\n', encoding='utf-8')
            run = task / '知识重整运行.json'
            run.write_text(json.dumps(dict(refresh_run_id='R1', workflow_entry='run_outline_refresh.py', article_id='ART-001', article_version='v2')), encoding='utf-8')
            for name in PACKAGE_FILES:
                (task / name).write_text('- 本轮知识重整运行ID：R1\n', encoding='utf-8')
            self.assertFalse(comparison_permitted(task))
            with patch('run_outline_refresh.validate_task_templates', return_value=[]), patch('run_outline_refresh.article_package_errors', return_value=[]):
                self.assertTrue(check_task(task)['ok'])
                self.assertTrue(comparison_permitted(task))
                (task / PACKAGE_FILES[0]).write_text('- 本轮知识重整运行ID：R1\nchanged', encoding='utf-8')
                self.assertFalse(comparison_permitted(task))
                check_task(task)
                self.assertTrue(comparison_permitted(task))
                req.write_text(req.read_text(encoding='utf-8') + '- 新要求：已变化\n', encoding='utf-8')
                self.assertFalse(comparison_permitted(task))
            with patch('run_outline_refresh.validate_task_templates', return_value=['bad package']):
                self.assertFalse(check_task(task)['ok'])
                self.assertFalse(comparison_permitted(task))

    def make_refresh_task(self, task, request_protocol='- 知识准备记录协议：PR-2\n'):
        req = task / '10_文章知识需求.md'
        req.write_text('- 文章ID：ART-001\n- 当前版本：v2\n' + request_protocol + '- 任务模式：outline_refresh\n', encoding='utf-8')
        (task / '知识重整运行.json').write_text(json.dumps(dict(refresh_run_id='R1', workflow_entry='run_outline_refresh.py', article_id='ART-001', article_version='v2')), encoding='utf-8')
        return req

    def test_pr2_refresh_passes_with_merged_20_and_no_separate_15(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            self.make_refresh_task(task)
            self.assertEqual(package_files(task), PACKAGE_FILES[1:])
            (task / '20_文章前知识审核.md').write_text('- 知识准备记录协议：PR-2\n- 本轮知识重整运行ID：R1\n', encoding='utf-8')
            for name in PACKAGE_FILES[2:]:
                (task / name).write_text('- 本轮知识重整运行ID：R1\n', encoding='utf-8')
            with patch('run_outline_refresh.validate_task_templates', return_value=[]), patch('run_outline_refresh.article_package_errors', return_value=[]):
                result = check_task(task)
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['state'], 'writing_ready_candidate')
                self.assertEqual(result['present'], list(PACKAGE_FILES[1:]))
                self.assertTrue(comparison_permitted(task))
                receipt = json.loads((task / '知识重整运行.json').read_text(encoding='utf-8'))['current_package_validation']
                self.assertEqual(set(receipt['package_sha256']), set(PACKAGE_FILES[1:]))
                (task / '30_本篇知识库资料.md').write_text('- 本轮知识重整运行ID：R1\nchanged', encoding='utf-8')
                self.assertFalse(comparison_permitted(task))

    def test_pr2_refresh_reports_missing_or_unbound_files_without_asking_for_15(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            self.make_refresh_task(task)
            (task / '20_文章前知识审核.md').write_text('- 知识准备记录协议：PR-2\n- 本轮知识重整运行ID：OLD\n', encoding='utf-8')
            (task / '30_本篇知识库资料.md').write_text('- 本轮知识重整运行ID：R1\n', encoding='utf-8')
            with patch('run_outline_refresh.validate_task_templates', return_value=[]), patch('run_outline_refresh.article_package_errors', return_value=[]):
                result = check_task(task)
            self.assertFalse(result['ok'])
            self.assertEqual(result['state'], 'knowledge_repair_required')
            self.assertIn('20_文章前知识审核.md未绑定本轮运行ID：R1', result['errors'])
            self.assertFalse(any('15_' in error for error in result['errors']))
            self.assertFalse(comparison_permitted(task))

    def test_legacy_pr1_refresh_still_requires_15(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            self.make_refresh_task(task, request_protocol='')
            for name in PACKAGE_FILES[1:]:
                (task / name).write_text('- 本轮知识重整运行ID：R1\n', encoding='utf-8')
            self.assertEqual(package_files(task), PACKAGE_FILES)
            with patch('run_outline_refresh.validate_task_templates', return_value=[]), patch('run_outline_refresh.article_package_errors', return_value=[]):
                self.assertFalse(check_task(task)['ok'])
                (task / PACKAGE_FILES[0]).write_text('- 本轮知识重整运行ID：R1\n', encoding='utf-8')
                self.assertTrue(check_task(task)['ok'])

    def test_gap_auto_continues_historical_suffixes(self):
        self.assertEqual(next_gap_key([{'gap_key': 'GAP-P-005-032'}, {'gap_key': 'legacy-name'}, {'gap_key': 'GAP-P005-002'}], 'P-005'), 'GAP-P005-033')


if __name__ == '__main__':
    unittest.main()
