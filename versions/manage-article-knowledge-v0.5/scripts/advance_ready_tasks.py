#!/usr/bin/env python3
"""Move all unblocked, delivery-ready v0.5 article tasks to 20_等待终稿."""

from __future__ import annotations

import argparse
import tempfile
from datetime import date
from pathlib import Path

from article_state import parse_field, task_ready_for_delivery, transition_task
from build_coverage_view import OUTPUT_RELATIVE, build_view


def rebuild_coverage(project: Path) -> Path:
    """Refresh coverage after article state changes, using the same atomic write contract."""
    output = project / OUTPUT_RELATIVE
    output.parent.mkdir(parents=True, exist_ok=True)
    text = build_view(project)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(output)
    return output


def advance_project(project: Path, *, updated: str | None = None) -> list[Path]:
    project = project.resolve()
    source_root = project / "04_文章任务/10_进行中"
    if not source_root.is_dir():
        return []
    moved: list[Path] = []
    updated = updated or date.today().isoformat()
    for task_dir in sorted(path for path in source_root.iterdir() if path.is_dir()):
        if not task_ready_for_delivery(task_dir):
            continue
        request = task_dir / "10_文章知识需求.md"
        text = request.read_text(encoding="utf-8-sig")
        article_id = parse_field(text, "文章ID")
        if not article_id:
            raise ValueError(f"交付就绪文章缺少文章ID：{request}")
        title = parse_field(text, "文章标题") or task_dir.name
        moved.append(
            transition_task(
                task_dir,
                "20_等待终稿",
                article_id=article_id,
                human_text=f"{title}知识库资料已就绪，等待终稿",
                blocked="否",
                owner="内容运营负责人提交终稿；Codex接收后导入Faithfulness",
                condition="文章要求、客户资料、30或35发生实质变化时归档并递增文章版本",
                updated=updated,
                link_file="30_本篇知识库资料.md",
            )
        )
    if moved:
        rebuild_coverage(project)
    return moved


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v05-advance-ready-") as temp:
        root = Path(temp) / "DEMO_测试知识库_v0.5"
        task = root / "04_文章任务/10_进行中/DEMO-ART-001_测试文章"
        (root / "01_工作台").mkdir(parents=True)
        for state in ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"):
            (root / "04_文章任务" / state).mkdir(parents=True, exist_ok=True)
        task.mkdir()
        (root / "01_工作台/20_当前待办.md").write_text(
            "# 当前待办\n\n| 对象ID | 人能看懂的事项 | 当前阶段 | 是否阻塞 | 下一步由谁做 | 直达链接 | 更新/重开条件 | 最近更新 |\n"
            "|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
        files = {
            "10_文章知识需求.md": "# 文章知识需求\n\n- 文章ID：DEMO-ART-001\n- 文章标题：测试文章\n",
            "15_检索与知识准备记录.md": (
                "# 检索与知识准备记录\n\n"
                "- MAT依赖处理：无\n\n"
                "## MAT依赖与资料选择\n\n"
                "| MAT ID | 候选SRC ID | 文件名与稳定路径 | 关系/处理问题 | 决定 | 选取或排除范围 | 决定依据 | 决定方 | 当前状态 |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 无 | 无 | 无 | 无 | 无 | 无 | 无 | Codex自动处理 | 不适用 |\n"
            ),
            "20_文章前知识审核.md": "# 文章前知识审核\n\n- 结论：自动通过\n",
            "30_本篇知识库资料.md": "# 本篇写作素材包\n",
            "35_写作素材来源索引.md": "# 写作素材来源索引\n",
        }
        for name, content in files.items():
            (task / name).write_text(content, encoding="utf-8")
        moved = advance_project(root, updated="2026-08-25")
        if len(moved) != 1 or not (root / "04_文章任务/20_等待终稿/DEMO-ART-001_测试文章").is_dir():
            raise AssertionError("delivery-ready task was not moved")
        coverage = root / OUTPUT_RELATIVE
        if not coverage.is_file() or "覆盖数据指纹：" not in coverage.read_text(encoding="utf-8"):
            raise AssertionError("coverage view was not rebuilt after migration")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--updated")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if not args.project:
        raise SystemExit("--project is required unless --self-test is used")
    moved = advance_project(args.project, updated=args.updated)
    for path in moved:
        print(f"moved={path}")
    print(f"moved_count={len(moved)}")


if __name__ == "__main__":
    main()
