#!/usr/bin/env python3
"""Summarize monthly knowledge-attachment support without applying a target score."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from statistics import mean


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_field(text: str, field: str) -> str:
    pattern = re.compile(rf"^\s*[-*]\s*{re.escape(field)}[：:]\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def discover_expected(articles_root: Path, month: str) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}
    if not articles_root.is_dir():
        return expected
    for path in articles_root.rglob("40_最终文章.md"):
        if "90_归档" in path.parts:
            continue
        text = path.read_text(encoding="utf-8-sig")
        article_id = parse_field(text, "文章ID")
        article_date = parse_field(text, "完成日期")
        if article_id and article_date.startswith(month):
            expected[article_id] = {"article_file": str(path.resolve()), "article_date": article_date}
    return expected


def hashes_are_current(row: dict[str, str]) -> tuple[bool, str]:
    article = Path(row["article_file"])
    if not article.is_file():
        return False, "最终文章文件缺失"
    if sha256_file(article) != row["article_sha256"]:
        return False, "正文已修改，等待重审"
    try:
        knowledge_files = [Path(item) for item in json.loads(row["knowledge_files"])]
        knowledge_hashes = list(json.loads(row["knowledge_sha256"]))
    except (json.JSONDecodeError, TypeError):
        return False, "知识资料哈希记录无效"
    if len(knowledge_files) != len(knowledge_hashes):
        return False, "知识资料哈希数量不一致"
    for path, expected_hash in zip(knowledge_files, knowledge_hashes):
        if not path.is_file():
            return False, f"知识资料缺失：{path}"
        if sha256_file(path) != expected_hash:
            return False, "知识资料已修改，等待重审"
    return True, ""


def integer_or_none(row: dict[str, str], field: str) -> int | None:
    value = row.get(field, "").strip()
    try:
        return int(value) if value != "" else None
    except ValueError:
        return None


def display_count(value: int | None) -> str:
    return str(value) if value is not None else "N/A（旧协议未记录）"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-csv", type=Path, required=True)
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--articles-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        date.fromisoformat(args.month + "-01")
    except ValueError as exc:
        raise SystemExit("--month must use YYYY-MM") from exc
    if not args.metrics_csv.is_file():
        rows: list[dict[str, str]] = []
    else:
        with args.metrics_csv.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))

    current = {
        row["article_id"]: row
        for row in rows
        if row.get("status") == "current" and row.get("article_date", "").startswith(args.month)
    }
    expected = (
        discover_expected(args.articles_root, args.month)
        if args.articles_root
        else {
            article_id: {"article_file": row["article_file"], "article_date": row["article_date"]}
            for article_id, row in current.items()
        }
    )

    valid: list[tuple[str, dict[str, str], float]] = []
    incomplete: list[tuple[str, str]] = []
    for article_id in sorted(expected):
        row = current.get(article_id)
        if not row:
            incomplete.append((article_id, "缺少外部Faithfulness结果"))
            continue
        is_current, reason = hashes_are_current(row)
        if not is_current:
            incomplete.append((article_id, reason))
            continue
        try:
            score = float(row["faithfulness_percent"])
        except (TypeError, ValueError):
            incomplete.append((article_id, "Faithfulness为N/A或格式无效"))
            continue
        valid.append((article_id, row, score))

    scores = [item[2] for item in valid]
    expected_count = len(expected)
    valid_count = len(valid)
    completeness = valid_count * 100 / expected_count if expected_count else 100.0
    average = mean(scores) if scores else None
    supported_total = sum(int(item[1]["supported_claims"]) for item in valid)
    unknown_values = [integer_or_none(item[1], "unknown_claims") for item in valid]
    contradicted_values = [integer_or_none(item[1], "contradicted_claims") for item in valid]
    unknown_total = sum(value for value in unknown_values if value is not None) if all(
        value is not None for value in unknown_values
    ) else None
    contradicted_total = sum(value for value in contradicted_values if value is not None) if all(
        value is not None for value in contradicted_values
    ) else None
    mapped_total = sum(int(item[1]["mapped_formal_claims"]) for item in valid)
    unmapped_total = sum(int(item[1]["unmapped_supported_claims"]) for item in valid)

    lines = [
        "## 四、月度文章 Faithfulness",
        "",
        f"- 应审核文章数：{expected_count}",
        f"- 已完成有效审核：{valid_count}",
        f"- 缺失或已失效审核：{len(incomplete)}",
        f"- 审核完整率：{completeness:.2f}%",
        f"- 月平均知识附件明确支撑率：{'暂无结果' if average is None else f'{average:.2f}%'}",
        f"- 明确支持主张总数：{supported_total}",
        f"- 尚未确认主张总数：{display_count(unknown_total)}",
        f"- 明确冲突主张总数：{display_count(contradicted_total)}",
        f"- 正式Claim映射数：{mapped_total}",
        f"- 未映射的明确支持主张数：{unmapped_total}",
        "- 指标说明：本指标没有目标值，不判定达标，不表示文章质量、发布资格或是否需要重写。",
        "- 行动依据：只按具体尚未确认/明确冲突主张的语义归组和事实类型处理，不因单篇或月平均高低触发行动。",
        "",
        "### 各文章结果",
        "",
    ]
    if not valid and not incomplete:
        lines.append("- 本月无应审核文章")
    for article_id, row, score in valid:
        unknown = integer_or_none(row, "unknown_claims")
        contradicted = integer_or_none(row, "contradicted_claims")
        lines.append(
            f"- {article_id}：知识附件明确支撑率 {score:.2f}%；"
            f"明确支持 {row['supported_claims']}；尚未确认 {display_count(unknown)}；"
            f"明确冲突 {display_count(contradicted)}；全部可验证主张 {row['total_claims']}"
        )
    for article_id, reason in incomplete:
        lines.append(f"- {article_id}：未纳入月平均；{reason}")
    lines.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"expected={expected_count}")
    print(f"valid={valid_count}")
    print(f"average={'N/A' if average is None else f'{average:.2f}%'}")
    print(f"output={args.output.resolve()}")


if __name__ == "__main__":
    main()
