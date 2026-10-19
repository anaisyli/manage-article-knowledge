from __future__ import annotations

import csv
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "manage-article-knowledge-v0.6.1" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import handoff_review  # noqa: E402
import import_faithfulness  # noqa: E402


METRIC_FIELDS = import_faithfulness.METRIC_FIELDS


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FaithfulnessReportingTests(unittest.TestCase):
    def metric_row(self, article: Path, knowledge: Path, **overrides: str) -> dict[str, str]:
        row = {field: "" for field in METRIC_FIELDS}
        row.update(
            audit_id="AUD-001",
            article_id="ART-001",
            article_version="v1",
            article_date="2026-09-10",
            article_file=str(article),
            article_sha256=sha256(article),
            knowledge_files=f'["{str(knowledge).replace(chr(92), chr(92) * 2)}"]',
            knowledge_sha256=f'["{sha256(knowledge)}"]',
            evaluation_mode="Codex reproduction",
            evaluation_protocol_version="2.0",
            deepeval_reproduction_percent="90.00",
            unknown_claims="2",
            contradicted_claims="1",
            primary_metric="strict_support",
            supported_claims="1",
            total_claims="4",
            unsupported_claims="3",
            faithfulness_percent="25.00",
            mapped_formal_claims="1",
            unmapped_supported_claims="0",
            imported_at="2026-09-10",
            status="current",
        )
        row.update(overrides)
        return row

    def write_metrics(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=METRIC_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_monthly_report_shows_three_states_without_target_or_compatibility_rate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            article = root / "40_最终文章.md"
            knowledge = root / "30_本篇知识库资料.md"
            article.write_text("article", encoding="utf-8")
            knowledge.write_text("knowledge", encoding="utf-8")
            metrics = root / "metrics.csv"
            output = root / "monthly.md"
            self.write_metrics(metrics, [self.metric_row(article, knowledge)])
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "calculate_monthly_faithfulness.py"),
                    "--metrics-csv", str(metrics),
                    "--month", "2026-09",
                    "--output", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            report = output.read_text(encoding="utf-8")
            self.assertIn("月平均知识附件明确支撑率：25.00%", report)
            self.assertIn("明确支持主张总数：1", report)
            self.assertIn("尚未确认主张总数：2", report)
            self.assertIn("明确冲突主张总数：1", report)
            self.assertIn("没有目标值", report)
            self.assertNotIn("DeepEval", report)

    def test_handoff_report_reads_current_three_state_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            article = project / "article.md"
            knowledge = project / "knowledge.md"
            article.write_text("article", encoding="utf-8")
            knowledge.write_text("knowledge", encoding="utf-8")
            metrics = project / handoff_review.METRICS_RELATIVE
            self.write_metrics(metrics, [self.metric_row(article, knowledge)])
            waiting = project / "04_文章任务/30_等待Faithfulness/ART-002"
            waiting.mkdir(parents=True)
            record = project / "04_文章任务/40_已完成/ART-003/50_文章知识使用与Faithfulness记录.md"
            record.parent.mkdir(parents=True)
            record.write_text("- 当前状态：已失效，等待重审\n", encoding="utf-8")
            monthly = project / handoff_review.REVIEW_RELATIVE / "2026-09_月度审核.md"
            monthly.parent.mkdir(parents=True)
            monthly.write_text("- 月平均知识附件明确支撑率：25.00%\n", encoding="utf-8")
            report_path = handoff_review.write_review(
                project,
                stage="交付前",
                project_id="DEMO",
                enterprise_name="示例企业",
                original_owner="A",
                new_owner="B",
                package_path="package.zip",
                issues=[],
            )
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("当前有效结果数：1", report)
            self.assertIn("等待结果数：1", report)
            self.assertIn("待重审数：1", report)
            self.assertIn("尚未确认主张总数：2", report)
            self.assertIn("明确冲突主张总数：1", report)
            self.assertIn("最近月度知识附件明确支撑率：25.00%", report)
            self.assertNotIn("DeepEval", report)

    def test_low_percentage_has_no_cus_threshold_hook(self) -> None:
        self.assertFalse(hasattr(import_faithfulness, "CUS_LOW_FAITHFULNESS_THRESHOLD"))
        self.assertFalse(hasattr(import_faithfulness, "mark_low_faithfulness_cus_recheck"))

    def test_serialization_only_article_change_stays_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            article = root / "40_最终文章.md"
            knowledge = root / "30_本篇知识库资料.md"
            prepared = root / "prepared.json"
            article.write_text("# Title\n\n| A | B |\n|---|---|\n| one | two |\n", encoding="utf-8")
            knowledge.write_text("knowledge", encoding="utf-8")
            prepared.write_text(
                '{"article_lines":[{"line":"3","text":"A | B"},{"line":"5","text":"one | two"}]}',
                encoding="utf-8",
            )
            row = self.metric_row(article, knowledge, prepared_file=str(prepared), article_sha256="old-hash")
            monthly = root / "monthly.md"
            metrics = root / "metrics.csv"
            self.write_metrics(metrics, [row])
            subprocess.run(
                [sys.executable, str(SCRIPTS / "calculate_monthly_faithfulness.py"), "--metrics-csv", str(metrics), "--month", "2026-09", "--output", str(monthly)],
                check=True, capture_output=True, text=True,
            )
            report = monthly.read_text(encoding="utf-8")
            self.assertIn("已完成有效审核：1", report)
            self.assertIn("序列化兼容警告", report)

    def test_real_article_change_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            article = root / "40_最终文章.md"
            knowledge = root / "30_本篇知识库资料.md"
            prepared = root / "prepared.json"
            article.write_text("# Title\n\nchanged\n", encoding="utf-8")
            knowledge.write_text("knowledge", encoding="utf-8")
            prepared.write_text('{"article_lines":[{"line":"3","text":"original"}]}', encoding="utf-8")
            row = self.metric_row(article, knowledge, prepared_file=str(prepared), article_sha256="old-hash")
            metrics = root / "metrics.csv"
            monthly = root / "monthly.md"
            self.write_metrics(metrics, [row])
            subprocess.run(
                [sys.executable, str(SCRIPTS / "calculate_monthly_faithfulness.py"), "--metrics-csv", str(metrics), "--month", "2026-09", "--output", str(monthly)],
                check=True, capture_output=True, text=True,
            )
            report = monthly.read_text(encoding="utf-8")
            self.assertIn("已完成有效审核：0", report)
            self.assertIn("正文内容已修改，等待重审", report)


if __name__ == "__main__":
    unittest.main()
