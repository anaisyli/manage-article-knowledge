#!/usr/bin/env python3
"""Record one normalized public-knowledge gap and maintain its lightweight lifecycle."""

from __future__ import annotations

import argparse
import csv
import tempfile
from datetime import date
from pathlib import Path
import re


FIELDS = (
    "gap_key", "gap_topic", "gap_type", "trigger_basis", "article_ids",
    "article_count", "status", "current_impact", "next_action", "first_seen",
    "last_seen", "related_governance_ref",
)
DIRECT_RESEARCH_BASES = {"核心章节首次", "高风险事实首次", "重复文章"}
STATUSES = {"观察中", "待外部调研", "已解决", "已关闭"}
CHINESE_TEXT_FIELDS = ("topic", "current_impact", "next_action")


def require_human_chinese(value: str, field: str) -> None:
    """管理字段必须包含中文人话，不能把英文命题直接写入人工表。"""
    if not value.strip():
        raise SystemExit(f"--{field.replace('_', '-')} 不能为空")
    if not re.search(r"[\u3400-\u9fff]", value):
        raise SystemExit(f"--{field.replace('_', '-')} 必须包含中文人话说明")


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"知识缺口CSV字段不符合v0.5：{path}")
        return [{field: row.get(field, "") for field in FIELDS} for row in reader]


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="", dir=path.parent, delete=False, suffix=".tmp"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(stream.name)
    temporary.replace(path)


def normalized_article_ids(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.split(";") if item.strip()))


def lifecycle_status(previous: str, trigger_basis: str, article_count: int) -> str:
    if trigger_basis in DIRECT_RESEARCH_BASES or article_count >= 2:
        return "待外部调研"
    if previous in {"已解决", "已关闭"}:
        return "观察中"
    return previous if previous in {"观察中", "待外部调研"} else "观察中"


def default_next_action(status: str) -> str:
    if status == "待外部调研":
        return "按本篇已批准范围开展定向外部调研；若禁止新调研则保留状态并缩小或排除无支持内容"
    if status == "已解决":
        return "已形成可用外部公共Claim；下次相关文章直接复用并按来源日期复核"
    if status == "已关闭":
        return "已确认不再需要或不在允许范围内处理；满足重开条件时重新登记"
    return "同主题第二篇不同文章出现时开展定向外部调研"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--gap-key", required=True, help="Stable normalized question key, not an atomic article claim.")
    parser.add_argument("--topic", required=True, help="Human-readable public knowledge question.")
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--article-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--trigger-basis",
        choices=("首篇普通缺口", "核心章节首次", "高风险事实首次", "重复文章"),
        required=True,
    )
    parser.add_argument("--current-impact", default="不阻塞已完成文章；影响后续同主题事实附件覆盖")
    parser.add_argument("--next-action", default="")
    parser.add_argument("--related-governance-ref", default="无")
    parser.add_argument("--set-status", choices=tuple(sorted(STATUSES)))
    args = parser.parse_args()

    if args.set_status == "已解决" and "RES-" not in (args.related_governance_ref or ""):
        raise SystemExit("--set-status 已解决 必须同时提供包含 RES- 的 --related-governance-ref")

    try:
        date.fromisoformat(args.article_date)
    except ValueError as exc:
        raise SystemExit("--article-date must use YYYY-MM-DD") from exc
    if not args.gap_key.strip() or any(char in args.gap_key for char in "|\r\n"):
        raise SystemExit("--gap-key must be a non-empty stable key without table delimiters")
    if not args.topic.strip():
        raise SystemExit("--topic must be non-empty")
    require_human_chinese(args.topic, "topic")
    require_human_chinese(args.current_impact, "current_impact")
    if args.next_action.strip():
        require_human_chinese(args.next_action, "next_action")

    rows = read_rows(args.csv)
    existing = next((row for row in rows if row["gap_key"] == args.gap_key.strip()), None)
    if existing is None:
        article_ids = [args.article_id.strip()]
        status = args.set_status or lifecycle_status("", args.trigger_basis, len(article_ids))
        row = {
            "gap_key": args.gap_key.strip(),
            "gap_topic": args.topic.strip(),
            "gap_type": "公共知识",
            "trigger_basis": args.trigger_basis,
            "article_ids": ";".join(article_ids),
            "article_count": str(len(article_ids)),
            "status": status,
            "current_impact": args.current_impact.strip(),
            "next_action": args.next_action.strip() or default_next_action(status),
            "first_seen": args.article_date,
            "last_seen": args.article_date,
            "related_governance_ref": args.related_governance_ref.strip() or "无",
        }
        rows.append(row)
    else:
        article_ids = normalized_article_ids(existing["article_ids"])
        if args.article_id.strip() not in article_ids:
            article_ids.append(args.article_id.strip())
        article_count = len(article_ids)
        basis = args.trigger_basis
        if article_count >= 2 and basis == "首篇普通缺口":
            basis = "重复文章"
        status = args.set_status or lifecycle_status(existing["status"], basis, article_count)
        existing.update({
            "gap_topic": args.topic.strip(),
            "trigger_basis": basis,
            "article_ids": ";".join(article_ids),
            "article_count": str(article_count),
            "status": status,
            "current_impact": args.current_impact.strip(),
            "next_action": args.next_action.strip() or default_next_action(status),
            "last_seen": args.article_date,
            "related_governance_ref": args.related_governance_ref.strip() or existing["related_governance_ref"] or "无",
        })
        row = existing
    write_rows(args.csv, rows)
    print(f"gap_key={row['gap_key']}")
    print(f"article_count={row['article_count']}")
    print(f"status={row['status']}")


if __name__ == "__main__":
    main()
