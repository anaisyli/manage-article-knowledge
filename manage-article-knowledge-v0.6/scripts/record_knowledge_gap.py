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


def normalized_topic(value: str) -> str:
    """Return a stable comparison key for the same human-readable knowledge question."""
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def topic_specificity(value: str) -> None:
    """Reject labels that cannot tell an operator what knowledge is missing."""
    text = " ".join(value.split())
    if len(text) < 10:
        raise SystemExit("--topic 必须写成具体知识问题，至少说明对象和缺少的规则/事实")
    if re.search(r"(?:通用说明|相关说明|知识说明|内容说明|待补充)$", text):
        raise SystemExit(
            "--topic 不能使用笼统的‘通用说明/相关说明’结尾；请写明对象、条件、步骤或适用边界"
        )


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
            raise ValueError(f"知识缺口CSV字段不符合v0.6：{path}")
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


def merge_duplicate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Canonicalize legacy duplicate public-gap rows before the next write."""
    merged: dict[str, dict[str, str]] = {}
    status_rank = {"已关闭": 0, "已解决": 1, "观察中": 2, "待外部调研": 3}
    for row in rows:
        topic_key = normalized_topic(row.get("gap_topic", "")) or row.get("gap_key", "")
        current = merged.get(topic_key)
        if current is None:
            current = dict(row)
            merged[topic_key] = current
            continue
        ids = normalized_article_ids(current.get("article_ids", "") + ";" + row.get("article_ids", ""))
        current["article_ids"] = ";".join(ids)
        current["article_count"] = str(len(ids))
        if status_rank.get(row.get("status", ""), 0) > status_rank.get(current.get("status", ""), 0):
            current["status"] = row.get("status", "")
        if row.get("first_seen", "") and (not current.get("first_seen") or row["first_seen"] < current["first_seen"]):
            current["first_seen"] = row["first_seen"]
        if row.get("last_seen", "") > current.get("last_seen", ""):
            current["last_seen"] = row["last_seen"]
        refs = list(dict.fromkeys(
            [item.strip() for item in (current.get("related_governance_ref", "") + ";" + row.get("related_governance_ref", "")).split(";") if item.strip() and item.strip() != "无"]
        ))
        current["related_governance_ref"] = ";".join(refs) if refs else "无"
        if len(row.get("gap_topic", "")) > len(current.get("gap_topic", "")):
            current["gap_topic"] = row["gap_topic"]
        if len(ids) >= 2 and current.get("trigger_basis") == "首篇普通缺口":
            current["trigger_basis"] = "重复文章"
    return list(merged.values())


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
    topic_specificity(args.topic)
    require_human_chinese(args.current_impact, "current_impact")
    if args.next_action.strip():
        require_human_chinese(args.next_action, "next_action")

    rows = merge_duplicate_rows(read_rows(args.csv))
    requested_key = args.gap_key.strip()
    existing = next((row for row in rows if row["gap_key"] == requested_key), None)
    merged_key = ""
    if existing is None:
        # A writer may invent a new key for the same public problem on another
        # article. Reuse the first stable row when the human topic is identical.
        topic_key = normalized_topic(args.topic)
        existing = next(
            (row for row in rows if normalized_topic(row.get("gap_topic", "")) == topic_key),
            None,
        )
        if existing is not None:
            merged_key = existing["gap_key"]
    if existing is None:
        article_ids = [args.article_id.strip()]
        status = args.set_status or lifecycle_status("", args.trigger_basis, len(article_ids))
        row = {
            "gap_key": requested_key,
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
        old_topic = existing.get("gap_topic", "").strip()
        # Prefer a more descriptive wording while preserving the stable key.
        preferred_topic = args.topic.strip() if len(args.topic.strip()) > len(old_topic) else old_topic
        existing.update({
            "gap_topic": preferred_topic,
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
    if merged_key:
        print(f"merged_existing_gap_key={merged_key}")
    print(f"article_count={row['article_count']}")
    print(f"status={row['status']}")


if __name__ == "__main__":
    main()
