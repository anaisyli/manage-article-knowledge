#!/usr/bin/env python3
"""Import external Faithfulness artifacts without re-judging their claims."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from article_state import transition_task


METRIC_FIELDS = (
    "audit_id", "article_id", "article_version", "article_date", "article_file",
    "article_sha256", "knowledge_files", "knowledge_sha256", "evaluation_mode",
    "prepared_file", "judgments_file", "summary_file", "supported_claims",
    "total_claims", "unsupported_claims", "faithfulness_percent",
    "mapped_formal_claims", "unmapped_supported_claims", "imported_at", "status",
)
SUPPORT_FIELDS = (
    "audit_id", "article_id", "article_version", "article_fact_id", "article_line",
    "article_quote", "article_claim", "verdict", "formal_claim_id", "mapping_status",
    "evidence_source_file", "evidence_line_start", "evidence_line_end",
    "evidence_quote", "reason",
)
ADMIN_END_HEADINGS = (
    "codex自动闭环结果", "codex 自动闭环结果", "自动审核结果", "引用率统计",
)
WORD_RE = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode text file: {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_field(text: str, label: str) -> str:
    pattern = re.compile(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$",
        re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def markdown_cell(value: Any) -> str:
    return " ".join(str(value or "").replace("|", "\\|").split()) or "无"


def normalize_inline_markdown(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace(chr(96), "").replace("**", "").replace("__", "")
    text = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)", "", text)
    return " ".join(text.split())


def markdown_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), normalize_inline_markdown(match.group(2))


def is_table_rule(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*", line))


def visible_body_line(line: str) -> str:
    if is_table_rule(line):
        return ""
    if "|" in line and line.strip().startswith("|"):
        cells = [normalize_inline_markdown(cell) for cell in line.strip().strip("|").split("|")]
        return " | ".join(cell for cell in cells if cell)
    return normalize_inline_markdown(line)


def extract_article_lines(path: Path) -> list[dict[str, Any]]:
    lines = read_text(path).splitlines()
    start = 0
    for index, raw in enumerate(lines):
        heading = markdown_heading(raw)
        if heading and "最终正文" in heading[1]:
            start = index + 1
            break
    article_lines: list[dict[str, Any]] = []
    for index in range(start, len(lines)):
        raw = lines[index]
        heading = markdown_heading(raw)
        if heading:
            lowered = heading[1].lower().replace(" ", "")
            if any(marker in lowered for marker in ADMIN_END_HEADINGS):
                break
            continue
        text = visible_body_line(raw)
        if text and WORD_RE.search(text):
            article_lines.append({"line": index + 1, "text": text})
    return article_lines


def source_scope(lines: list[str], path: Path) -> list[bool]:
    writing_material = (
        parse_field("\n".join(lines), "资料视图") == "写作素材包"
        or "写作输入" in path.name
    )
    if not writing_material:
        return [True] * len(lines)
    if parse_field("\n".join(lines), "资料视图") == "写作素材包":
        selected = [False] * len(lines)
        evidence_sections = {
            "一、可直接用于正文的事实",
            "二、可直接采用的英文表达",
            "三、可使用的数据表",
        }
        in_evidence_section = False
        evidence_level: int | None = None
        found_evidence = False
        for index, line in enumerate(lines):
            heading = markdown_heading(line)
            if heading:
                level, title = heading
                if level == 2:
                    in_evidence_section = title in evidence_sections
                    evidence_level = None
                elif evidence_level is not None and level <= evidence_level:
                    evidence_level = None
                if in_evidence_section and re.match(r"^证据正文(?:（供Faithfulness核验）)?$", title):
                    evidence_level = level
                    found_evidence = True
                continue
            if evidence_level is not None:
                selected[index] = True
        if not found_evidence:
            raise ValueError(
                f"Writing material has no recognizable evidence bodies: {path}. "
                "Use a '证据正文（供Faithfulness核验）' heading in sections 1-3."
            )
        return selected

    has_source_blocks = any(
        re.match(r"^\s*#{3,5}\s+(?:来源块|事实素材|证据块)[：:]", line)
        for line in lines
    )
    if not has_source_blocks:
        raise ValueError(
            f"Writing material has no recognizable evidence blocks: {path}. "
            "Use '事实素材：' (or '来源块：') followed by '证据正文'."
        )
    selected = [False] * len(lines)
    in_source_block = False
    in_evidence_body = False
    for index, line in enumerate(lines):
        heading = markdown_heading(line)
        if heading:
            level, title = heading
            if re.match(r"^(?:来源块|事实素材|证据块)[：:]", title):
                in_source_block = True
                in_evidence_body = False
            elif in_source_block and level <= 4:
                in_source_block = False
                in_evidence_body = False
            elif in_source_block and any(marker in title for marker in ("原文", "证据", "来源正文", "可核验依据")):
                in_evidence_body = True
            continue
        if in_source_block and in_evidence_body:
            selected[index] = True
    return selected


def extract_knowledge_chunks(path: Path) -> list[dict[str, Any]]:
    lines = read_text(path).splitlines()
    allowed = source_scope(lines, path)
    chunks: list[dict[str, Any]] = []
    section = ""
    buffer: list[str] = []
    start_line = 0
    end_line = 0

    def flush() -> None:
        nonlocal buffer, start_line, end_line
        text = " ".join(buffer).strip()
        if text and WORD_RE.search(text):
            chunks.append(
                {
                    "source_file": str(path.resolve()),
                    "section": section,
                    "line_start": start_line,
                    "line_end": end_line,
                    "text": text,
                }
            )
        buffer = []
        start_line = 0
        end_line = 0

    for index, raw in enumerate(lines):
        line_no = index + 1
        heading = markdown_heading(raw)
        if heading:
            flush()
            section = heading[1]
            continue
        if not allowed[index]:
            flush()
            continue
        text = visible_body_line(raw)
        if not text:
            flush()
            continue
        if not buffer:
            start_line = line_no
        buffer.append(text)
        end_line = line_no
        if len(" ".join(buffer)) >= 900 or ("|" in raw and raw.strip().startswith("|")):
            flush()
    flush()
    return chunks


def normalized_path(path: str | Path) -> str:
    return str(Path(path).resolve()).casefold()


def verify_prepared(prepared: dict[str, Any], article: Path, knowledge: list[Path]) -> None:
    if prepared.get("article_lines") != extract_article_lines(article):
        raise ValueError("Prepared article content no longer matches the current final article")

    prepared_files = {normalized_path(item) for item in prepared.get("knowledge_files", [])}
    actual_files = {normalized_path(item) for item in knowledge}
    if prepared_files != actual_files:
        raise ValueError("Prepared knowledge-file set does not match the supplied knowledge inputs")

    expected_chunks: list[dict[str, Any]] = []
    for path in knowledge:
        expected_chunks.extend(extract_knowledge_chunks(path))
    prepared_chunks: list[dict[str, Any]] = []
    for item in prepared.get("knowledge_chunks", []):
        prepared_chunks.append(
            {
                "source_file": normalized_path(item["source_file"]),
                "section": item.get("section", ""),
                "line_start": item["line_start"],
                "line_end": item["line_end"],
                "text": item["text"],
            }
        )
    normalized_expected = [
        {**item, "source_file": normalized_path(item["source_file"])}
        for item in expected_chunks
    ]
    if prepared_chunks != normalized_expected:
        raise ValueError("Prepared knowledge chunks no longer match the current knowledge files")


def parse_summary(path: Path, article_id: str) -> dict[str, Any]:
    for line in read_text(path).splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] != article_id or len(cells) < 6:
            continue
        try:
            score_text = cells[5].rstrip("%")
            return {
                "supported": int(cells[2]),
                "total": int(cells[3]),
                "unsupported": int(cells[4]),
                "score": None if score_text.upper() == "N/A" else float(score_text),
                "mode": cells[6] if len(cells) > 6 else "",
            }
        except ValueError as exc:
            raise ValueError(f"Invalid summary row for {article_id}") from exc
    raise ValueError(f"Article {article_id} not found in Faithfulness summary")


def claim_ranges(path: Path) -> list[tuple[int, int, str]]:
    lines = read_text(path).splitlines()
    markers: list[tuple[int, str]] = []
    pattern = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.IGNORECASE)
    for index, line in enumerate(lines, 1):
        match = pattern.match(line)
        if match:
            markers.append((index, match.group(1)))
    ranges: list[tuple[int, int, str]] = []
    for position, (start, claim_id) in enumerate(markers):
        end = markers[position + 1][0] - 1 if position + 1 < len(markers) else len(lines)
        ranges.append((start, end, claim_id))
    return ranges


def writing_material_mapping(path: Path) -> list[tuple[int, int, str]]:
    """Load deterministic 30-line to Formal Claim mappings from sibling 35."""
    text = read_text(path)
    if parse_field(text, "资料视图") != "写作素材包":
        return claim_ranges(path)

    audit_path = path.with_name("35_写作素材来源索引.md")
    legacy_mapping = False
    if not audit_path.is_file():
        legacy_path = path.with_name("25_文章证据与审核包.md")
        if legacy_path.is_file():
            audit_path = legacy_path
            legacy_mapping = True
    if not audit_path.is_file():
        raise ValueError(f"New writing-material view is missing its source index: {audit_path}")
    audit_text = read_text(audit_path)
    material_article_id = parse_field(text, "文章ID")
    audit_article_id = parse_field(audit_text, "文章ID")
    if not material_article_id or material_article_id != audit_article_id:
        raise ValueError(f"Article ID mismatch between 30 and 35: {audit_path}")
    recorded_hash = parse_field(audit_text, "写作素材SHA-256").lower()
    actual_hash = sha256_file(path).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", recorded_hash) or recorded_hash != actual_hash:
        raise ValueError(f"Writing-material SHA-256 mismatch between 30 and 35: {audit_path}")

    lines = audit_text.splitlines()
    mapping_heading = next(
        (
            index
            for index, line in enumerate(lines)
            if (heading := markdown_heading(line))
            and (
                "写作素材到正式知识映射" in heading[1]
                or (legacy_mapping and "写作素材映射" in heading[1])
            )
        ),
        None,
    )
    if mapping_heading is None:
        raise ValueError(f"Source index has no writing-material mapping section: {audit_path}")
    ranges: list[tuple[int, int, str]] = []
    material_line_count = len(text.splitlines())
    evidence_scope = source_scope(text.splitlines(), path)
    row_pattern = re.compile(
        r"^\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([A-Za-z0-9_.-]+)\s*\|"
        if legacy_mapping
        else r"^\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*[^|]*\|\s*([A-Za-z0-9_.-]+)\s*\|"
    )
    for line in lines[mapping_heading + 1:]:
        heading = markdown_heading(line)
        if heading and heading[0] <= 2:
            break
        match = row_pattern.match(line)
        if not match:
            continue
        start, end = int(match.group(1)), int(match.group(2))
        claim_id = match.group(3)
        if start < 1 or end < start or end > material_line_count:
            raise ValueError(f"Invalid writing-material mapping range in {audit_path}: {start}-{end}")
        if not all(evidence_scope[start - 1:end]):
            raise ValueError(
                f"Writing-material mapping is outside a marked evidence body in {audit_path}: {start}-{end}"
            )
        ranges.append((start, end, claim_id))
    return ranges


def formal_claims_for(
    source_file: str,
    line_start: int,
    line_end: int,
    ranges_by_file: dict[str, list[tuple[int, int, str]]],
) -> list[str]:
    result: list[str] = []
    for start, end, claim_id in ranges_by_file.get(normalized_path(source_file), []):
        if start <= line_end and line_start <= end and claim_id not in result:
            result.append(claim_id)
    return result


def verify_judgment_locations(
    claims: list[dict[str, Any]],
    article: Path,
    knowledge: list[Path],
) -> None:
    article_lines = read_text(article).splitlines()
    knowledge_lines = {
        normalized_path(path): read_text(path).splitlines()
        for path in knowledge
    }
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        article_line = int(claim.get("article_line") or 0)
        article_quote = str(claim.get("article_quote", ""))
        if article_line < 1 or article_line > len(article_lines):
            raise ValueError(f"Article location is invalid for {claim_id}")
        if article_quote and article_quote not in article_lines[article_line - 1]:
            raise ValueError(f"Article quotation does not match the current article for {claim_id}")
        for evidence in claim.get("evidence") or []:
            source_file = normalized_path(str(evidence.get("source_file", "")))
            if source_file not in knowledge_lines:
                raise ValueError(f"Evidence source is outside the evaluated knowledge context for {claim_id}")
            start = int(evidence.get("line_start") or 0)
            end = int(evidence.get("line_end") or 0)
            lines = knowledge_lines[source_file]
            if start < 1 or end < start or end > len(lines):
                raise ValueError(f"Evidence location is invalid for {claim_id}")
            quote = str(evidence.get("quote", ""))
            if quote and quote not in "\n".join(lines[start - 1:end]):
                raise ValueError(f"Evidence quotation does not match the knowledge file for {claim_id}")


def load_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != fields:
            raise ValueError(f"Unexpected CSV schema: {path}")
        return list(reader)


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    temporary.replace(path)


def resolve_artifacts(
    result_dir: Path | None,
    prepared: Path | None,
    judgments: Path | None,
    summary: Path | None,
) -> tuple[Path, Path, Path]:
    if result_dir is None:
        if not prepared or not judgments or not summary:
            raise ValueError("Provide --result-dir or all of --prepared, --judgments and --summary")
        return prepared, judgments, summary
    if any((prepared, judgments, summary)):
        raise ValueError("Do not combine --result-dir with individual artifact arguments")
    if not result_dir.is_dir():
        raise ValueError(f"Faithfulness result directory not found: {result_dir}")

    def unique(pattern: str, label: str) -> Path:
        matches = sorted(path for path in result_dir.glob(pattern) if path.is_file())
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one {label} in {result_dir}; found {len(matches)}"
            )
        return matches[0]

    return (
        unique("*-prepared.json", "prepared artifact"),
        unique("*-judgments.json", "judgments artifact"),
        unique("faithfulness_summary.md", "faithfulness summary"),
    )


def formal_claim_catalog(project_root: Path) -> dict[str, tuple[str, str]]:
    catalog: dict[str, tuple[str, str]] = {}
    knowledge_root = project_root / "03_正式知识"
    if not knowledge_root.is_dir():
        return catalog
    heading_pattern = re.compile(
        r"^#{2,6}\s+([A-Za-z0-9_.-]+)(?:\s*[｜|]\s*(.+?))?\s*$",
        re.MULTILINE,
    )
    for path in knowledge_root.rglob("*.md"):
        text = read_text(path)
        for match in heading_pattern.finditer(text):
            claim_id = match.group(1)
            if not claim_id.upper().startswith(("CLM-", "CLAIM-")):
                continue
            title = (match.group(2) or claim_id).strip()
            catalog[claim_id] = (title, str(path.relative_to(project_root)))
    return catalog


def write_support_summary(
    path: Path,
    project_root: Path,
    metrics_rows: list[dict[str, str]],
    support_rows: list[dict[str, str]],
) -> None:
    current_metrics = {
        row["audit_id"]: row for row in metrics_rows if row.get("status") == "current"
    }
    catalog = formal_claim_catalog(project_root)
    grouped: dict[str, dict[str, tuple[str, str, str]]] = {}
    for row in support_rows:
        claim_id = row.get("formal_claim_id", "").strip()
        metric = current_metrics.get(row.get("audit_id", ""))
        if not claim_id or not metric or row.get("verdict") != "supported":
            continue
        article_id = row.get("article_id", "").strip()
        grouped.setdefault(claim_id, {})[article_id] = (
            metric.get("article_date", ""),
            article_id,
            metric.get("article_file", ""),
        )
    lines = [
        "# Claim文章支撑总表",
        "",
        "- 统计口径：只统计当前有效Faithfulness结果；同一Formal Claim按不同文章ID去重。",
        "- 关系含义：事后证据支撑，不代表写作模型内部实际调用轨迹。",
        f"- 最近重算：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "| Formal Claim及通俗标题 | 正式知识文件 | 支持文章数 | 最近支撑文章 | 最近日期 | 当前状态 |",
        "|---|---|---:|---|---|---|",
    ]
    for claim_id in sorted(grouped):
        articles = grouped[claim_id]
        recent = max(articles.values(), key=lambda item: (item[0], item[1]))
        title, knowledge_path = catalog.get(claim_id, (claim_id, "未在正式知识目录定位"))
        recent_label = f"{recent[1]}（{Path(recent[2]).stem if recent[2] else '文章文件未登记'}）"
        lines.append(
            f"| {markdown_cell(claim_id + '｜' + title)} | {markdown_cell(knowledge_path)} | "
            f"{len(articles)} | {markdown_cell(recent_label)} | {markdown_cell(recent[0])} | 当前有效 |"
        )
    if not grouped:
        lines.append("| 无 | 无 | 0 | 无 | 无 | 暂无当前有效支撑关系 |")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--judgments", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--article", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, action="append", required=True)
    parser.add_argument("--article-version", required=True)
    parser.add_argument("--article-date", required=True)
    parser.add_argument("--metrics-csv", type=Path, required=True)
    parser.add_argument("--support-csv", type=Path, required=True)
    parser.add_argument("--support-summary", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    try:
        args.prepared, args.judgments, args.summary = resolve_artifacts(
            args.result_dir, args.prepared, args.judgments, args.summary
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    for path in [args.prepared, args.judgments, args.summary, args.article, *args.knowledge]:
        if not path.is_file():
            raise SystemExit(f"Required file not found: {path}")
    new_view_inputs = [
        path for path in args.knowledge
        if parse_field(read_text(path), "资料视图") == "写作素材包"
    ]
    if new_view_inputs:
        if len(args.knowledge) != 1 or len(new_view_inputs) != 1:
            raise SystemExit(
                "manage-article-knowledge v0.5 accepts exactly one factual input: 30_本篇知识库资料.md"
            )
        if new_view_inputs[0].name != "30_本篇知识库资料.md":
            raise SystemExit("The v0.5 writing-material input must be named 30_本篇知识库资料.md")
    try:
        date.fromisoformat(args.article_date)
    except ValueError as exc:
        raise SystemExit("--article-date must use YYYY-MM-DD") from exc

    prepared = json.loads(read_text(args.prepared))
    judgments = json.loads(read_text(args.judgments))
    article_id = str(judgments.get("article_id", "")).strip()
    if not article_id or prepared.get("article_id") != article_id:
        raise SystemExit("Prepared and judgment article IDs do not match")
    if str(prepared.get("schema_version")) != "1.0" or str(judgments.get("schema_version")) != "1.0":
        raise SystemExit("Unsupported Faithfulness artifact schema")
    evaluation_mode = str(judgments.get("evaluation_mode", "")).strip()
    if not evaluation_mode:
        raise SystemExit("Judgment artifact is missing evaluation_mode")
    try:
        verify_prepared(prepared, args.article.resolve(), [path.resolve() for path in args.knowledge])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    claims = judgments.get("claims")
    if not isinstance(claims, list):
        raise SystemExit("Judgment artifact has no claims array")
    try:
        verify_judgment_locations(claims, args.article.resolve(), [path.resolve() for path in args.knowledge])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    article_fact_ids: set[str] = set()
    supported = 0
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        if not claim_id or claim_id in article_fact_ids:
            raise SystemExit("Article fact IDs must be present and unique")
        article_fact_ids.add(claim_id)
        verdict = claim.get("verdict")
        if verdict not in {"supported", "unsupported"}:
            raise SystemExit(f"Invalid verdict for {claim_id}: {verdict}")
        if verdict == "supported":
            supported += 1
            if not claim.get("evidence"):
                raise SystemExit(f"Supported fact {claim_id} has no evidence")
    total = len(claims)
    unsupported = total - supported
    score = round(supported * 100 / total, 2) if total else None
    summary = parse_summary(args.summary, article_id)
    if (
        summary["supported"] != supported
        or summary["total"] != total
        or summary["unsupported"] != unsupported
        or (score is None) != (summary["score"] is None)
        or (score is not None and abs(summary["score"] - score) > 0.01)
    ):
        raise SystemExit("Summary counts do not agree with the judgment artifact")
    if summary["mode"] and summary["mode"] != evaluation_mode:
        raise SystemExit("Summary evaluation mode does not agree with the judgment artifact")

    artifact_digest = hashlib.sha256()
    artifact_digest.update(args.prepared.read_bytes())
    artifact_digest.update(args.judgments.read_bytes())
    audit_id = f"FTH-{artifact_digest.hexdigest()[:16].upper()}"
    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    article_hash = sha256_file(args.article)
    knowledge_hashes = [sha256_file(path) for path in args.knowledge]
    try:
        ranges_by_file = {
            normalized_path(path): writing_material_mapping(path)
            for path in args.knowledge
        }
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    support_rows: list[dict[str, Any]] = []
    mapped_claim_ids: set[str] = set()
    unmapped_supported: set[str] = set()
    for claim in claims:
        evidence_items = claim.get("evidence") or [{}]
        mapped_for_fact: set[str] = set()
        for evidence in evidence_items:
            source_file = str(evidence.get("source_file", ""))
            line_start = int(evidence.get("line_start") or 0)
            line_end = int(evidence.get("line_end") or line_start)
            formal_claim_ids: list[str] = []
            if claim["verdict"] == "supported" and source_file and line_start:
                formal_claim_ids = formal_claims_for(
                    source_file, line_start, line_end, ranges_by_file
                )
                mapped_for_fact.update(formal_claim_ids)
                mapped_claim_ids.update(formal_claim_ids)
            for formal_claim_id in formal_claim_ids or [""]:
                support_rows.append(
                    {
                        "audit_id": audit_id,
                        "article_id": article_id,
                        "article_version": args.article_version,
                        "article_fact_id": claim.get("claim_id", ""),
                        "article_line": claim.get("article_line", ""),
                        "article_quote": claim.get("article_quote", ""),
                        "article_claim": claim.get("claim", ""),
                        "verdict": claim.get("verdict", ""),
                        "formal_claim_id": formal_claim_id,
                        "mapping_status": "mapped" if formal_claim_id else "unmapped",
                        "evidence_source_file": source_file,
                        "evidence_line_start": evidence.get("line_start", ""),
                        "evidence_line_end": evidence.get("line_end", ""),
                        "evidence_quote": evidence.get("quote", ""),
                        "reason": claim.get("reason", ""),
                    }
                )
        if claim["verdict"] == "supported" and not mapped_for_fact:
            unmapped_supported.add(str(claim.get("claim_id", "")))

    new_view_supplied = any(
        parse_field(read_text(path), "资料视图") == "写作素材包"
        for path in args.knowledge
    )
    if new_view_supplied and unmapped_supported:
        missing = ", ".join(sorted(unmapped_supported))
        raise SystemExit(
            "Supported facts could not be mapped through 35_写作素材来源索引.md: " + missing
        )

    metrics_rows = load_csv(args.metrics_csv, METRIC_FIELDS)
    if any(row["audit_id"] == audit_id for row in metrics_rows):
        raise SystemExit(f"Audit already imported: {audit_id}")
    for row in metrics_rows:
        if row["article_id"] == article_id and row["status"] == "current":
            row["status"] = "superseded"
    metric_row = {
        "audit_id": audit_id,
        "article_id": article_id,
        "article_version": args.article_version,
        "article_date": args.article_date,
        "article_file": str(args.article.resolve()),
        "article_sha256": article_hash,
        "knowledge_files": json.dumps([str(path.resolve()) for path in args.knowledge], ensure_ascii=False),
        "knowledge_sha256": json.dumps(knowledge_hashes, ensure_ascii=False),
        "evaluation_mode": evaluation_mode,
        "prepared_file": str(args.prepared.resolve()),
        "judgments_file": str(args.judgments.resolve()),
        "summary_file": str(args.summary.resolve()),
        "supported_claims": supported,
        "total_claims": total,
        "unsupported_claims": unsupported,
        "faithfulness_percent": "" if score is None else f"{score:.2f}",
        "mapped_formal_claims": len(mapped_claim_ids),
        "unmapped_supported_claims": len(unmapped_supported),
        "imported_at": imported_at,
        "status": "current",
    }
    metrics_rows.append(metric_row)
    existing_support = load_csv(args.support_csv, SUPPORT_FIELDS)
    existing_support.extend(support_rows)
    write_csv(args.metrics_csv, METRIC_FIELDS, metrics_rows)
    write_csv(args.support_csv, SUPPORT_FIELDS, existing_support)
    support_summary = args.support_summary or args.support_csv.with_name("30_Claim文章支撑总表.md")
    project_root = args.metrics_csv.resolve().parents[2]
    write_support_summary(support_summary, project_root, metrics_rows, existing_support)

    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    knowledge_hash_text = "；".join(
        f"{path.resolve()} = {checksum}"
        for path, checksum in zip(args.knowledge, knowledge_hashes)
    )
    score_text = "N/A" if score is None else f"{score:.2f}%"
    article_title = parse_field(read_text(args.article), "文章标题") or parse_field(
        read_text(args.article), "最终标题"
    ) or args.article.stem
    result_directory = args.result_dir.resolve() if args.result_dir else args.summary.resolve().parent
    result_entry = "指定审核结果目录" if args.result_dir else "内容运营提交"
    support_table_rows: list[str] = []
    seen_support: set[tuple[str, str]] = set()
    for row in support_rows:
        formal_claim_id = str(row.get("formal_claim_id", "")).strip()
        if row.get("verdict") != "supported" or not formal_claim_id:
            continue
        key = (str(row.get("article_fact_id", "")), formal_claim_id)
        if key in seen_support:
            continue
        seen_support.add(key)
        support_table_rows.append(
            "| " + " | ".join(
                [
                    markdown_cell(f"{row.get('article_claim', '')}（正文行{row.get('article_line', '')}）"),
                    markdown_cell(formal_claim_id),
                    markdown_cell("见35_写作素材来源索引.md"),
                    markdown_cell(
                        f"{row.get('evidence_source_file', '')}:{row.get('evidence_line_start', '')}-{row.get('evidence_line_end', '')}"
                    ),
                    "supported",
                ]
            ) + " |"
        )
    if not support_table_rows:
        support_table_rows.append("| 无可确定映射 | 无 | 无 | 无 | 无 |")

    unsupported_claims = [claim for claim in claims if claim.get("verdict") == "unsupported"]
    if unsupported_claims:
        unsupported_summary = "；".join(
            markdown_cell(claim.get("claim", "")) for claim in unsupported_claims[:5]
        )
        if len(unsupported_claims) > 5:
            unsupported_summary += f"；另有{len(unsupported_claims) - 5}条，详见外部判断文件"
        unsupported_row = (
            f"| 本篇未覆盖事实（{len(unsupported_claims)}条） | {unsupported_summary} | "
            "只表示本次附件未覆盖 | 单篇观察，不自动处理 | 同类主题跨文章或连续月份反复出现时月度重评 |"
        )
    else:
        unsupported_row = "| 无 | 本篇事实均被本次附件覆盖 | 无 | 无需处理 | 无 |"
    args.receipt.write_text(
        "\n".join(
            [
                "# 文章知识使用与Faithfulness记录",
                "",
                f"- 文章ID：{article_id}",
                f"- 文章标题：{article_title}",
                f"- 文章版本：{args.article_version}",
                "- 当前状态：已导入，观察完成",
                f"- 终稿：[[{args.article.name}]]",
                "- 本篇知识库资料：[[30_本篇知识库资料.md]]",
                "- 写作素材来源索引：[[35_写作素材来源索引.md]]",
                f"- 终稿接收日期：{args.article_date}",
                f"- Faithfulness结果入口：{result_entry}",
                f"- 指定审核结果目录：{result_directory}",
                f"- Faithfulness导入日期：{imported_at}",
                f"- 外部审核模式：{evaluation_mode}",
                f"- 外部结果文件：{args.summary.resolve()}",
                f"- 外部判断文件：{args.judgments.resolve()}",
                f"- 终稿SHA-256：{article_hash}",
                f"- 本篇知识库资料及SHA-256：{knowledge_hash_text}",
                f"- 导入ID：{audit_id}",
                "",
                "## 一、Faithfulness结果",
                "",
                "| 支持事实主张数 | 全部事实主张数 | 不支持事实主张数 | Faithfulness | 正式Claim映射数 | 未映射的支持主张数 |",
                "|---:|---:|---:|---:|---:|---:|",
                f"| {supported} | {total} | {unsupported} | {score_text} | {len(mapped_claim_ids)} | {len(unmapped_supported)} |",
                "",
                "## 二、正式知识对文章事实的支撑",
                "",
                "以下是审核后的事后证据支撑关系，不代表写作模型内部实际调用轨迹。",
                "",
                "| 文章事实/位置 | Formal Claim及通俗标题 | 正式知识文件 | 原始来源与位置 | 支撑判断 |",
                "|---|---|---|---|---|",
                *support_table_rows,
                "",
                "## 三、未被本次知识附件覆盖的内容",
                "",
                "| 主题/类型 | 人能看懂的内容说明 | 本篇影响 | 处理方式 | 重开/升级条件 |",
                "|---|---|---|---|---|",
                unsupported_row,
                "",
                "## 四、后续动作",
                "",
                "| 事项 | 当前状态 | 下一责任人 | 关联入口 | 更新/关闭条件 |",
                "|---|---|---|---|---|",
                "| 无 | 无需处理 | 无 | 无 | 同类主题跨文章或连续月份反复出现时月度重评 |",
                "",
                "## 五、更新记录",
                "",
                "| 日期 | 事件 | 结果/状态 | 相关文件 |",
                "|---|---|---|---|",
                f"| {imported_at} | 导入外部Faithfulness结果 | 当前有效 | {args.summary.resolve()} |",
                "",
                "本记录导入外部审核结论，本Skill没有重新执行Faithfulness语义判断。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed_task = transition_task(
        args.article.parent,
        "40_已完成",
        article_id=article_id,
        human_text=f"{article_title}已完成Faithfulness导入（{score_text}），保留当前文章与知识支撑记录",
        blocked="否",
        owner="Codex维护；月度审核观察重复知识缺口",
        condition="终稿、30或35发生实质变化时先归档并递增文章版本，旧Faithfulness自动失效",
        updated=imported_at[:10],
        link_file="50_文章知识使用与Faithfulness记录.md",
    )
    print(f"audit_id={audit_id}")
    print(f"article_id={article_id}")
    print(f"faithfulness={score_text}")
    print(f"mapped_formal_claims={len(mapped_claim_ids)}")
    print(f"unmapped_supported_claims={len(unmapped_supported)}")
    print(f"task={completed_task}")


if __name__ == "__main__":
    main()
