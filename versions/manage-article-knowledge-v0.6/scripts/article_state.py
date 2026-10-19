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


def article_package_errors(task_dir: Path) -> list[str]:
    """Return all actionable 30/35 package errors in one pass."""
    task_dir = task_dir.resolve()
    errors: list[str] = []
    material = task_dir / "30_本篇知识库资料.md"
    source_index = task_dir / "35_写作素材来源索引.md"
    prewrite = task_dir / "20_文章前知识审核.md"
    for path in (material, source_index, prewrite):
        if not path.is_file():
            errors.append(f"缺少文件：{path.name}")
    if errors:
        return errors

    errors.extend(validate_task_templates(task_dir))
    material_text = material.read_text(encoding="utf-8-sig")
    material_lines = material_text.splitlines()
    evidence_scope = _evidence_scope(material_lines)
    evidence_lines = {index for index, selected in enumerate(evidence_scope, 1) if selected}
    if not evidence_lines:
        errors.append("30没有可供Faithfulness核验的证据正文")

    for field in (
        "文章ID", "文章版本", "资料视图", "资料版本", "生成日期",
        "目标语言", "对应大纲", "使用对象",
    ):
        if not parse_field(material_text, field):
            errors.append(f"30缺少字段：{field}")
    for heading in (
        "一、可直接用于正文的事实", "二、可直接采用的英文表达",
        "三、可使用的数据表", "四、按大纲使用",
        "五、仅供生成控制（不得写入正文）", "六、缺少资料的章节及建议处理方式",
    ):
        if not re.search(rf"^##\s+{re.escape(heading)}\s*$", material_text, re.MULTILINE):
            errors.append(f"30缺少章节：{heading}")

    source_text = source_index.read_text(encoding="utf-8-sig")
    for field in (
        "文章ID", "文章版本", "索引版本", "生成日期",
        "对应写作素材", "写作素材SHA-256", "用途",
    ):
        if not parse_field(source_text, field):
            errors.append(f"35缺少字段：{field}")
    material_id = parse_field(material_text, "文章ID")
    source_id = parse_field(source_text, "文章ID")
    if material_id and source_id and material_id != source_id:
        errors.append(f"30与35文章ID不一致：30={material_id}，35={source_id}")
    recorded_hash = parse_field(source_text, "写作素材SHA-256").lower()
    actual_hash = hashlib.sha256(material.read_bytes()).hexdigest()
    if recorded_hash and recorded_hash != actual_hash:
        errors.append(f"35记录的30哈希不匹配：记录={recorded_hash}，实际={actual_hash}")

    try:
        project_root = project_root_for_task(task_dir)
    except ValueError as exc:
        errors.append(str(exc))
        return list(dict.fromkeys(errors))
    formal_root = project_root / "03_正式知识"
    claim_marker = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
    claim_ids = {
        match.group(1)
        for path in formal_root.rglob("*.md") if path.is_file()
        for match in claim_marker.finditer(path.read_text(encoding="utf-8-sig"))
    } if formal_root.is_dir() else set()

    mapping_heading = re.search(r"^##\s+写作素材到正式知识映射\s*$", source_text, re.MULTILINE)
    mapping_count = 0
    mapped_evidence_lines: set[int] = set()
    mapped_claim_ids: set[str] = set()
    if not mapping_heading:
        errors.append("35缺少“写作素材到正式知识映射”章节")
    else:
        mapping_body = source_text[mapping_heading.end():]
        next_heading = re.search(r"^##\s+", mapping_body, re.MULTILINE)
        if next_heading:
            mapping_body = mapping_body[:next_heading.start()]
        for row_number, line in enumerate(mapping_body.splitlines(), 1):
            if not line.strip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 7 or not cells[0].isdigit() or not cells[1].isdigit():
                continue
            mapping_count += 1
            start, end = int(cells[0]), int(cells[1])
            label = f"35映射第{row_number}条（30行{start}-{end}）"
            valid_range = 1 <= start <= end <= len(material_lines)
            if not valid_range:
                errors.append(f"{label}超出30实际行数1-{len(material_lines)}")
            elif not all(evidence_scope[start - 1:end]):
                errors.append(f"{label}包含非证据正文行")
            else:
                mapped_evidence_lines.update(range(start, end + 1))
            claim_id = cells[3]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", claim_id):
                errors.append(f"{label}的Claim ID格式无效：{claim_id or '空'}")
            elif claim_id not in claim_ids:
                errors.append(f"{label}引用的正式Claim不存在：{claim_id}")
            else:
                mapped_claim_ids.add(claim_id)
            formal_ref = cells[5]
            if formal_ref.startswith("[[") and formal_ref.endswith("]]" ):
                formal_ref = formal_ref[2:-2]
            formal_ref = formal_ref.split("|", 1)[0].strip()
            if not formal_ref.lower().endswith(".md"):
                errors.append(f"{label}缺少有效正式知识Markdown路径")
            else:
                formal_path = (
                    (source_index.parent / formal_ref).resolve()
                    if formal_ref.startswith(".") else (project_root / formal_ref).resolve()
                )
                if not formal_path.is_file():
                    errors.append(f"{label}引用的正式知识文件不存在：{formal_ref}")
    if mapping_count == 0:
        errors.append("35至少需要一条有效的证据正文到正式Claim映射")
    missing_evidence = sorted(evidence_lines - mapped_evidence_lines)
    if missing_evidence:
        preview = "、".join(str(line) for line in missing_evidence[:12])
        suffix = "等" if len(missing_evidence) > 12 else ""
        errors.append(f"30存在未被35映射的证据正文行：{preview}{suffix}")

    declared_claims = parse_field(prewrite.read_text(encoding="utf-8-sig"), "可用Claim数")
    if not declared_claims.isdigit():
        errors.append(f"20的可用Claim数必须是整数：{declared_claims or '空'}")
    elif int(declared_claims) != len(mapped_claim_ids):
        errors.append(
            f"20与35的可用Claim数不一致：20={declared_claims}，35唯一正式Claim={len(mapped_claim_ids)}"
        )
    return list(dict.fromkeys(errors))


def _article_package_ready(task_dir: Path) -> bool:
    return not article_package_errors(task_dir)


def article_package_ready(task_dir: Path) -> bool:
    """Validate a reusable 30/35 bundle against templates and formal Claims."""
    return _article_package_ready(task_dir.resolve())


def project_root_for_task(task_dir: Path) -> Path:
    task_dir = task_dir.resolve()
    if task_dir.parent.name not in ARTICLE_STATES or task_dir.parent.parent.name != "04_文章任务":
        raise ValueError(f"Article task is not under a canonical state directory: {task_dir}")
    return task_dir.parents[2]


def standard_faithfulness_record_path(article: Path) -> Path:
    """Return the only valid v0.6 Faithfulness record path for an article."""
    return article.resolve().parent / "50_文章知识使用与Faithfulness记录.md"


def require_standard_faithfulness_record_path(article: Path, receipt: Path) -> Path:
    """Reject a caller-selected receipt path before any workflow mutation."""
    expected = standard_faithfulness_record_path(article)
    if receipt.resolve() != expected:
        raise ValueError(
            "--receipt必须是当前文章任务目录中的标准50记录："
            f"{expected}"
        )
    return expected


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
