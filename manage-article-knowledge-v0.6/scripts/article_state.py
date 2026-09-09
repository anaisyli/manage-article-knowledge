"""Move one article task between the canonical v0.6 state directories."""

from __future__ import annotations

import re
import hashlib
from pathlib import Path

from template_contract import validate_task_templates


ARTICLE_STATES = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成")
TODO_RELATIVE = Path("01_工作台/20_当前待办.md")
DELIVERABLE_AUDIT_RESULTS = {"自动通过", "带明确排除通过"}


def _evidence_scope(lines: list[str]) -> list[bool]:
    selected = [False] * len(lines)
    in_supported_section = False
    evidence_level: int | None = None
    for index, line in enumerate(lines):
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            if level == 2:
                in_supported_section = title in {
                    "一、可直接用于正文的事实",
                    "二、可直接采用的英文表达",
                    "三、可使用的数据表",
                }
                evidence_level = None
            elif evidence_level is not None and level <= evidence_level:
                evidence_level = None
            if in_supported_section and re.fullmatch(r"证据正文(?:（供Faithfulness核验）)?", title):
                evidence_level = level
            continue
        if evidence_level is not None and line.strip():
            selected[index] = True
    return selected


def parse_field(text: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$",
        text,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def _article_package_ready(task_dir: Path) -> bool:
    """Require a coherent 30/35 pair before an in-progress task can advance."""
    material = task_dir / "30_本篇知识库资料.md"
    audit = task_dir / "35_写作素材来源索引.md"
    if not material.is_file() or not audit.is_file():
        return False
    # The delivery gate must use the same complete contracts as project validation;
    # presence of files alone is not evidence that the package was reviewed.
    if validate_task_templates(task_dir):
        return False
    material_text = material.read_text(encoding="utf-8-sig")
    material_lines = material_text.splitlines()
    evidence_scope = _evidence_scope(material_lines)
    evidence_lines = {index for index, selected in enumerate(evidence_scope, 1) if selected}
    if not evidence_lines:
        return False
    audit_text = audit.read_text(encoding="utf-8-sig")
    metadata = {
        "文章ID": None,
        "文章版本": None,
        "资料视图": "写作素材包",
        "资料版本": None,
        "生成日期": None,
        "目标语言": None,
        "对应大纲": None,
        "使用对象": None,
    }
    if any(not parse_field(material_text, field) for field in metadata):
        return False
    if any(
        not re.search(rf"^##\s+{re.escape(heading)}\s*$", material_text, re.MULTILINE)
        for heading in (
            "一、可直接用于正文的事实",
            "二、可直接采用的英文表达",
            "三、可使用的数据表",
            "四、按大纲使用",
            "五、仅供生成控制（不得写入正文）",
            "六、缺少资料的章节及建议处理方式",
        )
    ):
        return False
    for field in ("文章ID", "文章版本", "索引版本", "生成日期", "对应写作素材", "写作素材SHA-256", "用途"):
        if not parse_field(audit_text, field):
            return False
    if parse_field(material_text, "文章ID") != parse_field(audit_text, "文章ID"):
        return False
    recorded_hash = parse_field(audit_text, "写作素材SHA-256").lower()
    actual_hash = hashlib.sha256(material.read_bytes()).hexdigest()
    if recorded_hash != actual_hash:
        return False

    project_root = project_root_for_task(task_dir)
    claim_marker = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
    claim_ids = {
        match.group(1)
        for path in (project_root / "03_正式知识").rglob("*.md")
        if path.is_file()
        for match in claim_marker.finditer(path.read_text(encoding="utf-8-sig"))
    }
    mapping_heading = re.search(r"^##\s+写作素材到正式知识映射\s*$", audit_text, re.MULTILINE)
    mapping_count = 0
    mapped_evidence_lines: set[int] = set()
    mapped_claim_ids: set[str] = set()
    if mapping_heading:
        mapping_body = audit_text[mapping_heading.end():]
        next_heading = re.search(r"^##\s+", mapping_body, re.MULTILINE)
        if next_heading:
            mapping_body = mapping_body[:next_heading.start()]
        for line in mapping_body.splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 7 or not cells[0].isdigit() or not cells[1].isdigit():
                continue
            mapping_count += 1
            start, end = int(cells[0]), int(cells[1])
            if start < 1 or end < start or end > len(material_lines):
                return False
            if not all(evidence_scope[start - 1:end]):
                return False
            mapped_evidence_lines.update(range(start, end + 1))
            claim_id = cells[3]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", claim_id) or claim_id not in claim_ids:
                return False
            mapped_claim_ids.add(claim_id)
            formal_ref = cells[5]
            if formal_ref.startswith("[[") and formal_ref.endswith("]]" ):
                formal_ref = formal_ref[2:-2]
            formal_ref = formal_ref.split("|", 1)[0].strip()
            if not formal_ref.lower().endswith(".md"):
                return False
            formal_path = (audit.parent / formal_ref).resolve() if formal_ref.startswith(".") else (project_root / formal_ref).resolve()
            if not formal_path.is_file():
                return False
    prewrite = task_dir / "20_文章前知识审核.md"
    if not prewrite.is_file():
        return False
    declared_claims = parse_field(prewrite.read_text(encoding="utf-8-sig"), "可用Claim数")
    if not declared_claims.isdigit() or int(declared_claims) != len(mapped_claim_ids):
        return False
    return mapping_count > 0 and evidence_lines <= mapped_evidence_lines


def article_package_ready(task_dir: Path) -> bool:
    """Validate a reusable 30/35 bundle against templates and formal Claims."""
    return _article_package_ready(task_dir.resolve())


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


def validate_transition_inputs(task_dir: Path, target_state: str) -> None:
    """Check all filesystem inputs before a workflow transaction writes outputs."""
    if target_state not in ARTICLE_STATES:
        raise ValueError(f"Unknown article state: {target_state}")
    task_dir = task_dir.resolve()
    project_root = project_root_for_task(task_dir)
    current_state = task_dir.parent.name
    if current_state != target_state:
        destination = project_root / "04_文章任务" / target_state / task_dir.name
        if destination.exists():
            raise FileExistsError(f"Target article task already exists: {destination}")
    todo = project_root / TODO_RELATIVE
    if not todo.is_file():
        raise FileNotFoundError(f"Current todo file not found: {todo}")
    lines = todo.read_text(encoding="utf-8-sig").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("| 对象ID |")),
        None,
    )
    if header_index is None or header_index + 1 >= len(lines):
        raise ValueError(f"Current todo table is missing its canonical header: {todo}")


def task_ready_for_delivery(task_dir: Path) -> bool:
    """Return whether an in-progress task has passed the v0.6 delivery gate."""
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
    if validate_task_templates(task_dir):
        return False
    retrieval = task_dir / "15_检索与知识准备记录.md"
    retrieval_text = retrieval.read_text(encoding="utf-8-sig")
    mat_dependency = parse_field(retrieval_text, "MAT依赖处理")
    if mat_dependency not in {"无", "已决定"}:
        return False
    if "## MAT依赖与资料选择" not in retrieval_text:
        return False
    if "## 复杂资料处理与原件核对" not in retrieval_text:
        return False
    selection_section = retrieval_text.split("## MAT依赖与资料选择", 1)[1]
    if re.search(r"\|[^\n]*\|\s*待决定\s*\|", selection_section):
        return False
    complex_section = retrieval_text.split("## 复杂资料处理与原件核对", 1)[1]
    if re.search(r"\|[^\n]*\|\s*(?:等待材料或工具|待知识库专员判断)\s*\|", complex_section):
        return False
    if parse_field((task_dir / "20_文章前知识审核.md").read_text(encoding="utf-8-sig"), "结论") not in DELIVERABLE_AUDIT_RESULTS:
        return False
    problem = task_dir / "文章前问题与处理单.md"
    if problem.is_file() and parse_field(problem.read_text(encoding="utf-8-sig"), "当前状态") != "已关闭":
        return False
    return _article_package_ready(task_dir)
