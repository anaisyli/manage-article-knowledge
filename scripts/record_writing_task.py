#!/usr/bin/env python3
"""Record one external writing task to article mapping without creating duplicates."""

from __future__ import annotations

import argparse
import csv
import tempfile
from datetime import datetime
from pathlib import Path

from update_integration_status import update as update_integration_status


FIELDS = (
    "external_task_key", "source_path", "source_locator", "source_sha256",
    "article_id", "article_version", "imported_at", "current_status",
)
RELATIVE_LEDGER = Path("05_数据与审核/50_运行记录/10_写作任务接入记录.csv")


def load(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"写作任务接入记录字段不兼容：{path}")
        return list(reader)


def write_atomic(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def record(path: Path, item: dict[str, str]) -> str:
    rows = load(path)
    for row in rows:
        if row["external_task_key"] == item["external_task_key"]:
            if row["article_id"] != item["article_id"]:
                raise ValueError(
                    "同一外部任务唯一键已映射其他文章ID："
                    f"{item['external_task_key']} -> {row['article_id']}"
                )
            row.update(item)
            write_atomic(path, rows)
            return "updated"
        if row["article_id"] == item["article_id"]:
            raise ValueError(
                f"文章ID已映射其他外部任务唯一键：{item['article_id']}"
            )
    rows.append(item)
    write_atomic(path, rows)
    return "created"


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / RELATIVE_LEDGER
        base = {
            "external_task_key": "weekly-001",
            "source_path": "D:/writing/tasks.md",
            "source_locator": "row:1",
            "source_sha256": "a" * 64,
            "article_id": "DEMO-ART-20260831-001",
            "article_version": "1",
            "imported_at": "2026-08-31T12:00:00+08:00",
            "current_status": "已接收",
        }
        if record(path, base) != "created" or record(path, base) != "updated":
            raise SystemExit("self-test failed: create/update")
        conflict = dict(base, article_id="DEMO-ART-20260831-002")
        try:
            record(path, conflict)
        except ValueError:
            pass
        else:
            raise SystemExit("self-test failed: duplicate key accepted")
    print("self-test=passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--external-task-key")
    parser.add_argument("--source-path")
    parser.add_argument("--source-locator", default="未记录")
    parser.add_argument("--source-sha256", default="未记录")
    parser.add_argument("--article-id")
    parser.add_argument("--article-version", default="1")
    parser.add_argument("--status", default="已接收")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    required = {
        "--project": args.project,
        "--external-task-key": args.external_task_key,
        "--source-path": args.source_path,
        "--article-id": args.article_id,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("缺少参数：" + ", ".join(missing))
    ledger = args.project.resolve() / RELATIVE_LEDGER
    item = {
        "external_task_key": args.external_task_key.strip(),
        "source_path": str(Path(args.source_path).resolve()),
        "source_locator": args.source_locator.strip(),
        "source_sha256": args.source_sha256.strip(),
        "article_id": args.article_id.strip(),
        "article_version": args.article_version.strip(),
        "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "current_status": args.status.strip(),
    }
    try:
        action = record(ledger, item)
    except Exception as exc:
        # Keep the configuration's dynamic status useful even when a task is
        # rejected (for example, a duplicate external key).
        update_integration_status(
            args.project,
            "writing_task_failure",
            article_id=item["article_id"],
            article_version=item["article_version"],
            external_task_key=item["external_task_key"],
            error=str(exc),
        )
        raise SystemExit(str(exc)) from exc
    update_integration_status(
        args.project,
        "writing_task_success",
        article_id=item["article_id"],
        article_version=item["article_version"],
        external_task_key=item["external_task_key"],
        detail=f"任务接入记录{action}",
    )
    print(f"action={action}")
    print(f"ledger={ledger}")


if __name__ == "__main__":
    main()
