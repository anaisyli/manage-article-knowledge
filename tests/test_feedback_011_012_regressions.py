from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'manage-article-knowledge-v0.6.1' / 'scripts'))
from record_project_run import LEDGER_RELATIVE, append_record, make_record, validate_ledger
from validate_v06_project import extract_source_ids, validate_run_ledger, validate_source_references, validate_version_archives
from archive_project_version import create_archive


class LedgerRegressionTests(unittest.TestCase):
    def test_legacy_read_is_compatible_without_rewriting_but_new_write_is_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = make_record(project_root=root, task='historical run', status='partial')
            record['status'] = 'partial_success'
            path = root / LEDGER_RELATIVE
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(record) + '\n', encoding='utf-8')
            original = path.read_bytes()
            self.assertEqual(validate_ledger(path), [])
            errors = []
            validate_run_ledger(root, errors)
            self.assertEqual(errors, [])
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError):
                append_record(root, record)
            with self.assertRaises(ValueError):
                make_record(project_root=root, task='new run', status='partial_success')
            self.assertEqual(path.read_bytes(), original)

    def test_project_and_dedicated_checks_detect_same_real_errors(self):
        for defect in ['invalid_status', 'missing_field', 'duplicate_id', 'broken_json', 'unknown_schema']:
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                record = make_record(project_root=root, task='run', status='partial')
                if defect == 'invalid_status':
                    record['status'] = 'almost_ok'
                elif defect == 'missing_field':
                    del record['task']
                elif defect == 'unknown_schema':
                    record['schema_version'] = 2
                    record['status'] = 'partial_success'
                raw = json.dumps(record) + '\n'
                if defect == 'duplicate_id':
                    raw += raw
                elif defect == 'broken_json':
                    raw += '{\n'
                path = root / LEDGER_RELATIVE
                path.parent.mkdir(parents=True)
                path.write_text(raw, encoding='utf-8')
                dedicated = validate_ledger(path)
                project = []
                validate_run_ledger(root, project)
                self.assertTrue(dedicated)
                self.assertEqual(project, ['项目运行账本：' + e for e in dedicated])

    def test_no_ledger_is_compatible(self):
        with tempfile.TemporaryDirectory() as temp:
            errors = []
            validate_run_ledger(Path(temp), errors)
            self.assertEqual(errors, [])


class SourceReferenceRegressionTests(unittest.TestCase):
    def setup_index(self, root):
        path = root / '02_源资料/source-index.sqlite'
        path.parent.mkdir(parents=True)
        db = sqlite3.connect(path)
        try:
            db.execute('CREATE TABLE sources(source_id TEXT)')
            db.execute("INSERT INTO sources VALUES ('SRC-CLIENT-001')")
            db.commit()
        finally:
            db.close()

    def test_wildcard_descriptions_are_not_truncated_source_references(self):
        self.assertEqual(extract_source_ids('SRC-EXT-* SRC-* SRC-CLIENT-001, SRC-MISSING-001'),
                         {'SRC-CLIENT-001', 'SRC-MISSING-001'})
        self.assertEqual(extract_source_ids('SRC-EXT-P005-001'), {'SRC-EXT-P005-001'})

    def test_control_snapshot_excluded_current_facts_and_formal_history_still_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.setup_index(root)
            for relative in ['05_数据与审核/60_版本归档/20_控制文件迁移历史/demo.md',
                             '05_数据与审核/60_版本归档/30_机器文件迁移快照/demo.md']:
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_text('历史规则：SRC-EXT-*；当时引用SRC-OLD-001。', encoding='utf-8')
            errors = []
            validate_source_references(root, errors)
            self.assertEqual(errors, [])
            for relative in ['03_正式知识/current.md', '04_文章任务/10_进行中/task/15.md',
                             '05_数据与审核/60_版本归档/10_正式知识历史/demo.md']:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('来源：SRC-MISSING-001', encoding='utf-8')
            errors = []
            validate_source_references(root, errors)
            self.assertEqual(len(errors), 3)
            self.assertTrue(all('SRC-MISSING-001' in e for e in errors))

    def test_missing_external_reference_still_checked_and_valid_res_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.setup_index(root)
            claim = root / '03_正式知识/external.md'
            claim.parent.mkdir(parents=True)
            claim.write_text('来源：SRC-EXT-P005-001', encoding='utf-8')
            errors = []
            validate_source_references(root, errors)
            self.assertEqual(len(errors), 1)
            res = root / '02_源资料/50_外部调研证据/RES-001/10_来源原文证据.md'
            res.parent.mkdir(parents=True)
            res.write_text('来源ID：SRC-EXT-P005-001', encoding='utf-8')
            errors = []
            validate_source_references(root, errors)
            self.assertEqual(errors, [])

    def test_control_archive_integrity_still_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / '01_工作台/10_项目基础信息.md'
            path.parent.mkdir(parents=True)
            path.write_text('# 控制原件\n', encoding='utf-8')
            archive = create_archive(project=root, target=path, kind='control',
                                     reason='integrity regression', replacement_version='new')
            errors = []
            validate_version_archives(root, errors)
            self.assertEqual(errors, [])
            (archive / path.name).write_text('tampered', encoding='utf-8')
            validate_version_archives(root, errors)
            self.assertTrue(any('SHA-256' in e for e in errors))


if __name__ == '__main__':
    unittest.main()
