"""Move one article task between the canonical v0.6 state directories."""

from __future__ import annotations

import re
import hashlib
from urllib.parse import unquote, urlparse
from pathlib import Path

from template_contract import validate_task_templates
from validate_v06_project import (
    contains_chinese,
    formal_claim_theme_mismatch,
    is_english_target,
    markdown_section,
    normalized_evidence_text,
)
from prewrite_governance import governance_errors


ARTICLE_STATES = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成")
TODO_RELATIVE = Path("01_工作台/20_当前待办.md")
DELIVERABLE_AUDIT_RESULTS = {"自动通过", "带明确排除通过"}
_EVIDENCE_METADATA_RE = re.compile(
    r"^\s*[-*]\s*(?:来源(?:链接|类型|与精确位置)?|原始来源|精确位置|"
    r"source(?:\s+url|\s+type|\s+and\s+location)?|location)\s*[：:]?",
    re.IGNORECASE,
)


def _is_evidence_metadata_line(line: str) -> bool:
    """Return whether a line is source metadata rather than evidence text."""
    return bool(_EVIDENCE_METADATA_RE.match(line))


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
        if evidence_level is not None and line.strip() and not _is_evidence_metadata_line(line):
            selected[index] = True
    return selected


def parse_field(text: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$",
        text,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def _claim_block(formal_text: str, claim_id: str) -> str:
    marker = re.compile(
        r"^\s*[-*]\s*Claim ID[：:]\s*" + re.escape(claim_id) + r"\s*$",
        re.MULTILINE,
    )
    match = marker.search(formal_text)
    if not match:
        return ""
    next_claim = re.search(r"^\s*[-*]\s*Claim ID[：:]", formal_text[match.end():], re.MULTILINE)
    end = match.end() + next_claim.start() if next_claim else len(formal_text)
    return formal_text[match.start():end]


def _table_rows(text: str, heading: str) -> list[list[str]]:
    """Read data rows from one fixed Markdown table section."""
    lines = text.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return []
    rows: list[list[str]] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if not line.strip().startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


def _provenance_target(value: str) -> str:
    """Normalize a URL/path in a human-facing source field."""
    value = unquote(value.strip()).replace("\\", "/")
    link = re.search(r"\]\(([^)]+)\)", value)
    if link:
        value = link.group(1).strip()
    value = value.rstrip("/ ").casefold()
    return value


def _provenance_matches(candidate_source: str, formal_source: str) -> bool:
    candidate = _provenance_target(candidate_source)
    formal = _provenance_target(formal_source)
    if not candidate or not formal:
        return False
    if candidate in formal or formal in candidate:
        return True
    candidate_name = Path(urlparse(candidate).path or candidate).name
    formal_name = Path(urlparse(formal).path or formal).name
    return bool(candidate_name and formal_name and candidate_name == formal_name)


def _claim_field(claim_block: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$",
        claim_block,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def retrieval_claim_source_errors(task_dir: Path) -> list[str]:
    """Check that website candidates and Formal Claims form one source chain.

    The old checks verified that a Claim ID existed and that a quote appeared
    somewhere in the Claim file. They did not verify that a website candidate
    was actually represented by that Claim's source. This allowed a website
    row to point at a PDF Claim, or a missing web Claim to be treated as ready.
    """
    retrieval_path = task_dir / "15_检索与知识准备记录.md"
    if not retrieval_path.is_file():
        return []
    text = retrieval_path.read_text(encoding="utf-8-sig")
    website_rows = _table_rows(text, "## 官网正文核验")
    candidate_rows = {
        row[0].strip(): row
        for row in _table_rows(text, "## 候选事实处置明细")
        if len(row) >= 5 and re.fullmatch(r"CF-\d{3}", row[0].strip())
    }
    if not website_rows or not candidate_rows:
        return []

    project_root = task_dir.parents[2]
    formal_root = project_root / "03_正式知识"
    claims: dict[str, tuple[Path, str]] = {}
    marker = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
    if formal_root.is_dir():
        for path in formal_root.rglob("*.md"):
            if not path.is_file():
                continue
            formal_text = path.read_text(encoding="utf-8-sig")
            matches = list(marker.finditer(formal_text))
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(formal_text)
                claims[match.group(1)] = (path, formal_text[match.start():end])

    errors: list[str] = []
    candidate_questions: dict[str, list[str]] = {}
    website_urls: dict[str, set[str]] = {}
    for row in website_rows:
        if len(row) < 7:
            continue
        question, page, _date, _position, _excerpt, candidate_result, disposition = (
            cell.strip() for cell in row[:7]
        )
        page_match = re.search(r"https?://[^\s)]+", page)
        page_url = _provenance_target(page_match.group(0)) if page_match else ""
        for candidate_id in sorted(set(re.findall(r"\bCF-\d{3}\b", candidate_result))):
            candidate_questions.setdefault(candidate_id, []).append(question)
            if page_url:
                website_urls.setdefault(candidate_id, set()).add(page_url)
            candidate = candidate_rows.get(candidate_id)
            if not candidate:
                continue
            source = candidate[2].strip()
            claim_id = candidate[4].strip()
            if page_url and page_url not in _provenance_target(source):
                errors.append(
                    f"官网候选事实来源未绑定同一URL：{candidate_id}（网页={page_url}；候选事实来源={source}）"
                )
            if not claim_id or claim_id in {"无", "未形成", "待补充"}:
                errors.append(f"官网候选事实尚未建立或复用Formal Claim：{candidate_id}")
                continue
            claim = claims.get(claim_id)
            if not claim:
                errors.append(f"官网候选事实引用的Formal Claim文件不存在：{candidate_id} -> {claim_id}")
                continue
            claim_path, claim_block = claim
            formal_source = _claim_field(claim_block, "来源链接")
            if page_url and page_url not in _provenance_target(formal_source):
                errors.append(
                    f"官网候选事实与Formal Claim来源不一致：{candidate_id} -> {claim_id}（{claim_path.name}）"
                )
            elif not page_url and not _provenance_matches(source, formal_source):
                errors.append(
                    f"候选事实与Formal Claim来源不一致：{candidate_id} -> {claim_id}（{claim_path.name}）"
                )
            if disposition and "已读取" not in disposition and "采用" not in disposition and "复用" not in disposition:
                errors.append(f"官网候选事实缺少明确的Claim采用/复用处置：{candidate_id}（{question}）")

    for candidate_id, questions in candidate_questions.items():
        unique_questions = list(dict.fromkeys(questions))
        if len(unique_questions) > 1:
            rows_for_candidate = [
                row for row in website_rows
                if len(row) >= 7 and candidate_id in row[5]
            ]
            if not any("同一候选事实明确支持多个问题" in row[6] for row in rows_for_candidate):
                errors.append(
                    f"同一官网候选事实被复制到多个大纲问题但未说明支持范围：{candidate_id}（{'、'.join(unique_questions)}）"
                )
    return list(dict.fromkeys(errors))


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
    # The summary rows in 20 are not evidence of a performed review. Require
    # the itemized, source-backed CUS/ANM check before the writing gate.
    try:
        errors.extend(governance_errors(task_dir, project_root_for_task(task_dir)))
    except ValueError as exc:
        errors.append(str(exc))
    material_text = material.read_text(encoding="utf-8-sig")
    material_lines = material_text.splitlines()
    request_path = task_dir / "10_文章知识需求.md"
    request_text = request_path.read_text(encoding="utf-8-sig") if request_path.is_file() else ""
    batch_id = parse_field(request_text, "批次ID")
    if batch_id and batch_id != "不适用":
        batch_safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", batch_id)
        batch_path = task_dir.parents[2] / "04_文章任务" / "批次运行" / f"{batch_safe}.json"
        try:
            from batch_knowledge_run import ledger_errors
            errors.extend(ledger_errors(batch_path, batch_id))
        except (ImportError, OSError, ValueError) as exc:
            errors.append(f"批次证据门禁无法执行：{exc}")
    english_target = is_english_target(parse_field(material_text, "目标语言"))
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

    # Rebuilding 35 is deterministic, but an old Faithfulness result must not
    # become current merely because its index hash was refreshed.
    faithfulness_record = task_dir / "50_文章知识使用与Faithfulness记录.md"
    if faithfulness_record.is_file():
        faithfulness_text = faithfulness_record.read_text(encoding="utf-8-sig")
        recorded_knowledge_hashes = {
            match.group(1).lower()
            for match in re.finditer(
                r"本篇知识库资料及SHA-256：.*?([0-9a-f]{64})", faithfulness_text, re.I
            )
        }
        if recorded_knowledge_hashes and actual_hash not in recorded_knowledge_hashes:
            errors.append(
                "当前30已变化但50仍引用旧知识附件哈希，旧Faithfulness结果不可继续沿用；"
                "请按当前文章版本重新审核并导入"
            )

    try:
        project_root = project_root_for_task(task_dir)
    except ValueError as exc:
        errors.append(str(exc))
        return list(dict.fromkeys(errors))
    # A website row, candidate fact, Formal Claim and 30 block must describe
    # one provenance chain.  Keep this check at the article gate so an invalid
    # 15 cannot be promoted merely because 30/35 happen to contain a valid ID.
    errors.extend(retrieval_claim_source_errors(task_dir))
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
            # A mapping uses a contiguous Markdown line range.  Blank lines
            # inside one evidence block are formatting only and should not
            # invalidate the range; every non-empty line must still belong to
            # the evidence scope so a row cannot silently span a heading or
            # unrelated control text.
            elif not all(
                (not material_lines[index].strip()) or evidence_scope[index]
                for index in range(start - 1, end)
            ):
                errors.append(f"{label}包含非证据正文行")
            else:
                mapped_evidence_lines.update(
                    index
                    for index in range(start, end + 1)
                    if evidence_scope[index - 1]
                )
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
                else:
                    # A real Claim must be the provenance of the evidence
                    # block, not merely a matching ID in the mapping table.
                    formal_text = formal_path.read_text(encoding="utf-8-sig")
                    quoted = [
                        re.sub(r"^\s*>\s?", "", material_lines[line_no - 1]).strip()
                        for line_no in range(start, end + 1)
                        if material_lines[line_no - 1].lstrip().startswith(">")
                    ]
                    quoted = [line for line in quoted if line]
                    if quoted and not all(line in formal_text for line in quoted):
                        errors.append(f"{label}的30证据正文未逐字出现在正式Claim文件中，疑似临时段落或被改写")
                    claim_block = _claim_block(formal_text, claim_id)
                    if request_text:
                        mismatch = formal_claim_theme_mismatch(
                            request_text, formal_path, claim_block
                        )
                        if mismatch:
                            theme_key, article_families, claim_families = mismatch
                            errors.append(
                                f"{label}的Formal Claim与文章主题不匹配：主题键={theme_key}，"
                                f"文章主题族={','.join(sorted(article_families)) or '未识别'}，"
                                f"Claim主题族={','.join(sorted(claim_families))}"
                            )
                    mapped_text = normalized_evidence_text(
                        "\n".join(material_lines[start - 1:end])
                    )
                    if english_target and contains_chinese(mapped_text):
                        errors.append(f"{label}的英文30证据正文不得包含中文管理说明或中文混入")
                    original_text = normalized_evidence_text(
                        markdown_section(claim_block, "最小原文证据")
                    )
                    translation_text = normalized_evidence_text(
                        markdown_section(claim_block, "经核验英文严格翻译")
                    )
                    expected_text = translation_text if contains_chinese(original_text) else original_text
                    if expected_text and expected_text not in mapped_text:
                        errors.append(f"{label}未完整复用Formal Claim的连续证据正文")
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
    """Validate knowledge readiness before delivery or while awaiting the final."""
    task_dir = task_dir.resolve()
    if task_dir.parent.name not in {"10_进行中", "20_等待终稿"}:
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
