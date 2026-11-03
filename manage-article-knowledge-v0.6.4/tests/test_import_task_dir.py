from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from handoff_contract import current_version  # noqa: E402
from article_state import check_bound_material  # noqa: E402
from import_faithfulness import fill_from_task_dir  # noqa: E402


UTF8_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def blank_args(**values) -> argparse.Namespace:
    names = ("task_dir", "result_dir", "article", "knowledge", "article_version", "handoff_contract_version",
             "article_date", "metrics_csv", "support_csv", "support_summary", "receipt")
    return argparse.Namespace(**{name: values.get(name) for name in names})


class ImportTaskDirTests(unittest.TestCase):
    def test_task_dir_derives_every_import_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "P-TEST_测试知识库_v0.6"
            task = project / "04_文章任务/30_等待Faithfulness/ART-001_Test"
            task.mkdir(parents=True)
            (task / "40_最终文章.md").write_text(
                "# 最终文章\n\n- 文章ID：ART-001\n- 文章版本：v2\n- 交接合同版本：MAK-HANDOFF-1.4\n"
                "- 完成日期：2026-10-20\n",
                encoding="utf-8",
            )
            (task / "50_文章知识使用与Faithfulness记录.md").write_text(
                "# 文章知识使用与Faithfulness记录\n\n- 终稿接收日期：2026-10-23\n"
                "- 指定审核结果目录：D:\\results\\P-TEST\\ART-001\\v2\n",
                encoding="utf-8",
            )
            args = blank_args(task_dir=task, article_date="2026-10-01")
            fill_from_task_dir(args)
            data = project / "05_数据与审核/10_Faithfulness"
            self.assertEqual(args.article, task / "40_最终文章.md")
            self.assertEqual(args.knowledge, [task / "30_本篇知识库资料.md"])
            self.assertEqual(args.receipt, task / "50_文章知识使用与Faithfulness记录.md")
            self.assertEqual((args.article_version, args.handoff_contract_version), ("v2", "MAK-HANDOFF-1.4"))
            self.assertEqual(args.article_date, "2026-10-01")  # explicit value is kept
            self.assertEqual(args.metrics_csv, data / "10_文章Faithfulness明细.csv")
            self.assertEqual(args.support_csv, data / "20_Claim文章支撑记录.csv")
            self.assertEqual(args.support_summary, data / "30_Claim文章支撑总表.md")
            self.assertEqual(args.result_dir, Path("D:\\results\\P-TEST\\ART-001\\v2"))

    def test_task_dir_without_standard_files_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SystemExit) as raised:
                fill_from_task_dir(blank_args(task_dir=Path(temp)))
            self.assertIn("40_最终文章.md", str(raised.exception))

    def test_missing_arguments_point_to_task_dir(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPTS / "import_faithfulness.py")],
                                capture_output=True, text=True, encoding="utf-8", env=UTF8_ENV)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--task-dir", result.stderr)

    def test_request_rejects_stale_material_hash_before_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / "P-TEST/04_文章任务/20_等待终稿/ART-001_Test"
            task.mkdir(parents=True)
            article = task / "40_最终文章.md"
            knowledge = task / "30_本篇知识库资料.md"
            source_index = task / "35_写作素材来源索引.md"
            article.write_text(
                "# 最终文章\n\n- 文章ID：ART-001\n- 文章版本：v1\n- 完成日期：2026-09-16\n- 文章标题：Test\n",
                encoding="utf-8",
            )
            knowledge.write_text("# 本篇写作素材包\n\n- 资料视图：写作素材包\n", encoding="utf-8")
            source_index.write_text(
                "# 写作素材来源索引\n\n- 文章ID：ART-001\n- 文章版本：v1\n- 写作素材SHA-256：" + "0" * 64 + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "create_faithfulness_record.py"),
                    "--article", str(article), "--knowledge", str(knowledge),
                    "--source-index", str(source_index),
                    "--receipt", str(task / "50_文章知识使用与Faithfulness记录.md"),
                    "--result-dir", str(Path(temp) / "results/P-TEST/ART-001/v1"),
                    "--handoff-contract-version", current_version(),
                ],
                capture_output=True, text=True, encoding="utf-8", env=UTF8_ENV,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("写作素材SHA-256与当前30不一致", result.stderr + result.stdout)
            self.assertFalse((task / "50_文章知识使用与Faithfulness记录.md").exists())



class BoundMaterialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.task = Path(self.temp.name)
        self.material = self.task / "30_本篇知识库资料.md"
        self.bound = "# 本篇写作素材包\r\n\r\n- 资料视图：写作素材包\r\n".encode("utf-8")
        (self.task / "writing_ready.json").write_text(
            json.dumps({"knowledge_sha256": hashlib.sha256(self.bound).hexdigest()}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_line_ending_drift_is_restored_to_the_permitted_bytes(self) -> None:
        self.material.write_bytes(self.bound.replace(b"\r\n", b"\n"))
        self.assertIn("换行符", check_bound_material(self.task))
        self.assertEqual(self.material.read_bytes(), self.bound)
        self.assertEqual(check_bound_material(self.task), "")

    def test_changed_text_is_refused(self) -> None:
        self.material.write_bytes(self.bound + "- 新增事实\r\n".encode("utf-8"))
        with self.assertRaisesRegex(ValueError, "写作者看到的不是当前30"):
            check_bound_material(self.task)

    def test_only_an_exact_hash_match_restores(self) -> None:
        # A BOM, trailing space or table edit cannot reproduce the bound SHA-256, so nothing is restored.
        spaced = self.bound.replace("包\r\n".encode("utf-8"), "包 \n".encode("utf-8"), 1)
        for drifted in (b"\xef\xbb\xbf" + self.bound, spaced):
            self.material.write_bytes(drifted)
            with self.assertRaisesRegex(ValueError, "写作者看到的不是当前30"):
                check_bound_material(self.task)
            self.assertEqual(self.material.read_bytes(), drifted)

    def test_line_ending_hashes_cover_only_line_endings(self) -> None:
        from article_state import line_ending_hashes

        lf = self.bound.replace(b"\r\n", b"\n")
        self.assertIn(hashlib.sha256(self.bound).hexdigest(), line_ending_hashes(lf))
        self.assertNotIn(hashlib.sha256(self.bound).hexdigest(), line_ending_hashes(lf + b"x"))

    def test_task_without_permit_is_left_alone(self) -> None:
        (self.task / "writing_ready.json").unlink()
        self.material.write_bytes(b"anything")
        self.assertEqual(check_bound_material(self.task), "")


if __name__ == "__main__":
    unittest.main()
