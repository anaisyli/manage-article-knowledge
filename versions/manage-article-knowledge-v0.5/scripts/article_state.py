"""Move one article task between the canonical v0.5 state directories."""

from __future__ import annotations

import re
from pathlib import Path


ARTICLE_STATES = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成")
TODO_RELATIVE = Path("01_工作台/20_当前待办.md")
DELIVERABLE_AUDIT_RESULTS = {"自动通过", "带明确排除通过"}


def parse_field(text: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$",
        text,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def project_root_for_task(task_dir: Path) -> Path:
    task_dir = task_dir.resolve()
    if task_dir.parent.name not in ARTICLE_STATES or task_dir.parent.parent.name != "04_文章任务":
        raise ValueError(f"Article task is not under a canonical state directory: {task_dir}")
    return task_dir.parents[2]


def _todo_row(
    *,
    article_id: str,
    human_text: str,
    stage: str,
    blocked: str,
    owner: str,
    link: str,
    condition: str,
    updated: str,
) -> str:
    values = (article_id, human_text, stage, blocked, owner, link, condition, updated)
    return "| " + " | ".join(value.replace("|", "\\|") for value in values) + " |"


def update_current_todo(
    project_root: Path,
    *,
    article_id: str,
    human_text: str,
    stage: str,
    blocked: str,
    owner: str,
    link: str,
    condition: str,
    updated: str,
) -> Path:
    """Upsert the human-readable article row in the single current-todo table."""
    path = project_root / TODO_RELATIVE
    if not path.is_file():
        raise FileNotFoundError(f"Current todo file not found: {path}")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("| 对象ID |")),
        None,
    )
    if header_index is None or header_index + 1 >= len(lines):
        raise ValueError(f"Current todo table is missing its canonical header: {path}")
    row = _todo_row(
        article_id=article_id,
        human_text=human_text,
        stage=stage,
        blocked=blocked,
        owner=owner,
        link=link,
        condition=condition,
        updated=updated,
    )
    found = None
    for index in range(header_index + 2, len(lines)):
        if not lines[index].strip().startswith("|"):
            break
        cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
        if cells and cells[0].replace("\\|", "|") == article_id:
            found = index
            break
    if found is None:
        insert_at = header_index + 2
        while insert_at < len(lines) and lines[insert_at].strip().startswith("|"):
            insert_at += 1
        lines.insert(insert_at, row)
    else:
        lines[found] = row
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def transition_task(
    task_dir: Path,
    target_state: str,
    *,
    article_id: str,
    human_text: str,
    blocked: str,
    owner: str,
    condition: str,
    updated: str,
    link_file: str,
) -> Path:
    if target_state not in ARTICLE_STATES:
        raise ValueError(f"Unknown article state: {target_state}")
    task_dir = task_dir.resolve()
    project_root = project_root_for_task(task_dir)
    current_state = task_dir.parent.name
    if current_state == target_state:
        destination = task_dir
    else:
        destination = project_root / "04_文章任务" / target_state / task_dir.name
        if destination.exists():
            raise FileExistsError(f"Target article task already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        task_dir.rename(destination)
    link = "[[../04_文章任务/" + target_state + "/" + destination.name + "/" + link_file + "]]"
    try:
        update_current_todo(
            project_root,
            article_id=article_id,
            human_text=human_text,
            stage=target_state,
            blocked=blocked,
            owner=owner,
            link=link,
            condition=condition,
            updated=updated,
        )
    except Exception:
        if current_state != target_state and destination.exists() and not task_dir.exists():
            destination.rename(task_dir)
        raise
    return destination


def task_ready_for_delivery(task_dir: Path) -> bool:
    """Return whether an in-progress task has passed the v0.5 delivery gate."""
    task_dir = task_dir.resolve()
    if task_dir.parent.name != "10_进行中":
        return False
    required = (
        "10_文章知识需求.md",
        "15_检索与知识准备记录.md",
        "20_文章前知识审核.md",
        "30_本篇知识库资料.md",
        "35_写作素材来源索引.md",
    )
    if any(not (task_dir / name).is_file() for name in required):
        return False
    retrieval = task_dir / "15_检索与知识准备记录.md"
    retrieval_text = retrieval.read_text(encoding="utf-8-sig")
    mat_dependency = parse_field(retrieval_text, "MAT依赖处理")
    if mat_dependency not in {"无", "已决定"}:
        return False
    if "## MAT依赖与资料选择" not in retrieval_text:
        return False
    selection_section = retrieval_text.split("## MAT依赖与资料选择", 1)[1]
    if re.search(r"\|[^\n]*\|\s*待决定\s*\|", selection_section):
        return False
    if parse_field((task_dir / "20_文章前知识审核.md").read_text(encoding="utf-8-sig"), "结论") not in DELIVERABLE_AUDIT_RESULTS:
        return False
    problem = task_dir / "文章前问题与处理单.md"
    if problem.is_file() and parse_field(problem.read_text(encoding="utf-8-sig"), "当前状态") != "已关闭":
        return False
    return True
