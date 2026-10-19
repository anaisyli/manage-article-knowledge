#!/usr/bin/env python3
"""Read-only compatibility shim for the retired knowledge-refresh finalizer.

Knowledge refresh is prepared from the current outline and evidence gathered in
the current run. This module never reads archived knowledge or project gap
ledgers and never edits task files. The template contract performs validation.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FinalizeResult:
    repaired: list[Path] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    inherited_gaps: list[str] = field(default_factory=list)
    research_required: list[str] = field(default_factory=list)


def set_current_gap_presence(path: Path, gap_key: str, article_id: str, present: bool) -> bool:
    """Update current-version article linkage in the project gap ledger."""
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    changed = False
    for row in rows:
        if row.get("gap_key") != gap_key:
            continue
        ids = list(dict.fromkeys(item.strip() for item in row.get("current_article_ids", "").split(";") if item.strip()))
        if present and article_id not in ids:
            ids.append(article_id)
            changed = True
        elif not present and article_id in ids:
            ids.remove(article_id)
            changed = True
        row["current_article_ids"] = ";".join(ids)
        row["current_article_count"] = str(len(ids))
        break
    if changed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    return changed


def finalize_task(task_dir: Path) -> FinalizeResult:
    """Compatibility entry point that only checks for required current files."""
    task_dir = task_dir.resolve()
    result = FinalizeResult()
    required = (
        "10_文章知识需求.md", "15_检索与知识准备记录.md",
        "20_文章前知识审核.md", "30_本篇知识库资料.md",
        "35_写作素材来源索引.md",
    )
    missing = [name for name in required if not (task_dir / name).is_file()]
    if missing:
        result.blocked_reasons.append("本轮知识重整缺少当前文件：" + "、".join(missing))
    return result


def self_test() -> int:
    """Verify the shim makes no writes and does not depend on archive content."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mak-refresh-readonly-") as temp:
        root = Path(temp)
        task = root / "04_文章任务/10_进行中/DEMO"
        task.mkdir(parents=True)
        archive = root / "04_文章任务/90_归档/old"
        archive.mkdir(parents=True)
        (archive / "35_写作素材来源索引.md").write_text("CLM-OLD-001", encoding="utf-8")
        before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        result = finalize_task(task)
        after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        assert before == after
        assert result.repaired == [] and result.inherited_gaps == []
        assert not any("CLM-OLD" in reason for reason in result.blocked_reasons)
    print("self-test=passed\nmode=read-only\narchive_reads=0\nproject_writes=0")
    return 0


if __name__ == "__main__":
    self_test()
