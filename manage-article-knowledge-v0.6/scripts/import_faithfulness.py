#!/usr/bin/env python3
"""Import external Faithfulness artifacts without re-judging their claims."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from handoff_contract import HandoffContractError, load_contract, validate_event, validate_version
from template_contract import TEMPLATE_VERSION, validate_file

from article_state import transition_task, validate_transition_inputs
from check_integration import project_id_for_root
from update_integration_status import update as update_integration_status
from build_coverage_view import rebuild_view


METRIC_FIELDS = (
    "audit_id", "article_id", "article_version", "article_date", "article_file",
    "article_sha256", "knowledge_files", "knowledge_sha256", "evaluation_mode",
    "prepared_file", "judgments_file", "summary_file", "supported_claims",
    "total_claims", "unsupported_claims", "faithfulness_percent",
    "mapped_formal_claims", "unmapped_supported_claims", "imported_at", "status",
)
CUS_LOW_FAITHFULNESS_THRESHOLD = 80.0
SUPPORT_FIELDS = (
    "audit_id", "article_id", "article_version", "article_fact_id", "article_line",
    "article_quote", "article_claim", "verdict", "formal_claim_id", "mapping_status",
    "evidence_source_file", "evidence_line_start", "evidence_line_end",
    "evidence_quote", "reason",
)


def write_completion_receipt(
    result_dir: Path,
    *,
    contract_version: str,
    article_id: str,
    article_version: str,
    task_dir: str,
    audit_id: str,
    imported_at: str,
) -> Path:
    receipt = result_dir / "article_completed.json"
    payload = {
        "handoff_event": "article_completed",
        "handoff_contract_version": contract_version,
        "issuer": "import_faithfulness.py",
        "article_id": article_id,
        "article_version": article_version,
        "task_dir": task_dir,
        "audit_id": audit_id,
        "faithfulness_imported_at": imported_at,
    }
    receipt.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt
DISPOSITION_CATEGORIES = {
    "existing_gap", "new_public_gap", "cus", "mat", "anm",
    "package_omission", "writing_only",
}
GOVERNANCE_LEDGERS = {
    "cus": Path("05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md"),
    "mat": Path("05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md"),
    "anm": Path("05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md"),
}
DISPOSITION_REQUIRED_TEXT = (
    "group_id", "topic", "classification_basis", "status", "article_impact",
    "handling", "next_owner", "entry", "close_condition",
)
FACT_CHECK_DOMAINS = {
    "none", "customer_fact", "technical", "method", "regulation_standard",
    "safety_limit", "detection_validity", "procurement_selection",
    "dynamic_fact", "other_public_knowledge",
}
WRITING_ONLY_RISK_PATTERNS = (
    (
        "regulation/standard/certification",
        re.compile(
            r"\b(?:regulat\w*|standard\w*|certif\w*|compliance|legal|law)\b"
            r"|法规|标准|认证|合规|法律",
            re.IGNORECASE,
        ),
    ),
    (
        "safety/limit",
        re.compile(
            r"\b(?:safety|hazard\w*|threshold\w*|exposure limit\w*)\b"
            r"|安全|危害|限值|阈值",
            re.IGNORECASE,
        ),
    ),
    (
        "technical/method/detection validity",
        re.compile(
            r"\b(?:method\w*|workflow\w*|measurement\w*|detector\w*|"
            r"calibrat\w*|quantif\w*|identif\w*|validat\w*|accuracy|precision|"
            r"repeatability|detection limit\w*|sample preparation)\b"
            r"|技术|方法|流程|测量|检测器|校准|定量|鉴定|验证|准确度|精密度|重复性|检出限|样品制备",
            re.IGNORECASE,
        ),
    ),
    (
        "procurement/selection",
        re.compile(
            r"\b(?:procure\w*|purchas\w*|buyer\w*|selection|selecting|ROI)\b"
            r"|采购|选型|买方|投资回报",
            re.IGNORECASE,
        ),
    ),
    (
        "dynamic fact",
        re.compile(
            r"\b(?:latest|currently effective|current version|as of)\b"
            r"|最新|现行版本|目前有效|截至\d{4}",
            re.IGNORECASE,
        ),
    ),
)
ADMIN_END_HEADINGS = (
    "codex自动闭环结果", "codex 自动闭环结果", "自动审核结果", "引用率统计",
)
WORD_RE = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")
CHINESE_HUMAN_FIELDS = {
    "topic", "classification_basis", "status", "article_impact", "handling", "close_condition",
}


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


def mark_low_faithfulness_cus_recheck(audit_path: Path, score: float | None) -> None:
    """Record the mandatory six-category CUS recheck trigger on low scores."""
    if score is None or score >= CUS_LOW_FAITHFULNESS_THRESHOLD or not audit_path.is_file():
        return
    text = read_text(audit_path)
    marker = "Faithfulness低于80%后复核"
    if marker in text:
        return
    pattern = re.compile(
        r"(?m)^\|\s*CUS候选检测\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*$"
    )
    match = pattern.search(text)
    if not match:
        return
    signals = match.group(1).strip()
    replacement = "| CUS候选检测 | " + signals + "；" + marker + " | " + " | ".join(
        group.strip() for group in match.groups()[1:]
    ) + " |"
    audit_path.write_text(text[:match.start()] + replacement + text[match.end():], encoding="utf-8")


def markdown_cell(value: Any) -> str:
    return " ".join(str(value or "").replace("|", "\\|").split()) or "无"


def require_human_chinese(value: str, field: str, group_id: str) -> None:
    if not re.search(r"[\u3400-\u9fff]", value):
        raise ValueError(f"处置组{group_id}的{field}必须包含中文人话")


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


def remap_task_path(value: str, source_task: Path, destination_task: Path) -> str:
    """Rewrite a path inside the task directory before the task is moved."""
    if not value:
        return value
    try:
        relative = Path(value).resolve().relative_to(source_task.resolve())
    except (OSError, ValueError):
        return value
    return str(destination_task / relative)


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
    def traceable(quote: str, atomic_claim: str) -> bool:
        clean = lambda value: " ".join(re.sub(r"[^A-Za-z0-9\u3400-\u9fff]+", " ", value).lower().split())
        quote_plain, claim_plain = clean(quote), clean(atomic_claim)
        stop = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "has", "have", "can", "will", "into", "its", "your", "our"}
        words = lambda value: {item for item in re.findall(r"[a-z0-9]+", value) if len(item) >= 3 and item not in stop}
        if words(quote_plain) & words(claim_plain):
            return True
        quote_cjk = "".join(re.findall(r"[\u3400-\u9fff]", quote_plain))
        claim_cjk = "".join(re.findall(r"[\u3400-\u9fff]", claim_plain))
        if len(quote_cjk) >= 2 and len(claim_cjk) >= 2:
            quote_pairs = {quote_cjk[index:index + 2] for index in range(len(quote_cjk) - 1)}
            claim_pairs = {claim_cjk[index:index + 2] for index in range(len(claim_cjk) - 1)}
            if quote_pairs & claim_pairs:
                return True
        return bool(quote_plain and claim_plain and (quote_plain in claim_plain or claim_plain in quote_plain))

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
        atomic_claim = str(claim.get("claim", "")).strip()
        if not atomic_claim:
            raise ValueError(f"Atomic claim is empty for {claim_id}")
        if not traceable(article_quote, atomic_claim) and len(str(claim.get("derivation_note", "")).strip()) < 12:
            raise ValueError(
                f"Atomic claim is not traceable to its article quotation for {claim_id}; "
                "the judgment may be attached to the wrong article unit"
            )
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


def audit_matches_existing(
    existing: dict[str, str],
    *,
    article_id: str,
    article_version: str,
    article_hash: str,
    knowledge_hashes: list[str],
) -> bool:
    try:
        existing_knowledge_hashes = json.loads(existing.get("knowledge_sha256", ""))
    except (TypeError, json.JSONDecodeError):
        existing_knowledge_hashes = None
    return (
        existing.get("article_id", "") == article_id
        and existing.get("article_version", "") == article_version
        and existing.get("article_sha256", "").strip().lower() == article_hash.lower()
        and existing_knowledge_hashes == knowledge_hashes
    )


def self_test() -> None:
    row = {
        "article_id": "A-001",
        "article_version": "1",
        "article_sha256": "ABC123",
        "knowledge_sha256": json.dumps(["K1", "K2"]),
    }
    if not audit_matches_existing(
        row,
        article_id="A-001",
        article_version="1",
        article_hash="abc123",
        knowledge_hashes=["K1", "K2"],
    ):
        raise SystemExit("self-test failed: identical audit input")
    if audit_matches_existing(
        row,
        article_id="A-001",
        article_version="2",
        article_hash="abc123",
        knowledge_hashes=["K1", "K2"],
    ):
        raise SystemExit("self-test failed: conflicting audit input")
    print("self-test=passed")


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    temporary.replace(path)


def load_disposition(
    path: Path | None,
    article_id: str,
    claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unsupported_ids = {
        str(claim.get("claim_id", "")).strip()
        for claim in claims
        if claim.get("verdict") == "unsupported"
    }
    supported_ids = {
        str(claim.get("claim_id", "")).strip()
        for claim in claims
        if claim.get("verdict") == "supported"
    }
    if not unsupported_ids:
        if path is None:
            return []
    elif path is None:
        raise ValueError("Unsupported facts require --disposition with exhaustive grouped handling")
    if path is None or not path.is_file():
        raise ValueError(f"Disposition file not found: {path}")

    payload = json.loads(read_text(path))
    schema_version = str(payload.get("schema_version"))
    if schema_version not in {"1.0", "1.1"}:
        raise ValueError("Unsupported disposition schema")
    if str(payload.get("article_id", "")).strip() != article_id:
        raise ValueError("Disposition article_id does not match the Faithfulness result")
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise ValueError("Disposition has no groups array")

    seen_group_ids: set[str] = set()
    seen_claim_ids: set[str] = set()
    seen_public_issue_keys: set[str] = set()
    claim_by_id = {
        str(claim.get("claim_id", "")).strip(): claim
        for claim in claims
        if str(claim.get("claim_id", "")).strip()
    }
    normalized: list[dict[str, Any]] = []
    for raw in groups:
        if not isinstance(raw, dict):
            raise ValueError("Each disposition group must be an object")
        group = dict(raw)
        for field in DISPOSITION_REQUIRED_TEXT:
            if not str(group.get(field, "")).strip():
                raise ValueError(f"Disposition group is missing {field}")
            group[field] = str(group[field]).strip()
        group_id = group["group_id"]
        for field in CHINESE_HUMAN_FIELDS:
            require_human_chinese(group[field], field, group_id)
        if group["next_owner"] != "Codex":
            require_human_chinese(group["next_owner"], "next_owner", group_id)
        if group_id in seen_group_ids:
            raise ValueError(f"Disposition group_id is duplicated: {group_id}")
        seen_group_ids.add(group_id)
        category = str(group.get("category", "")).strip()
        if category not in DISPOSITION_CATEGORIES:
            raise ValueError(f"Disposition category is invalid for {group_id}: {category}")
        group["category"] = category
        issue_key = str(group.get("issue_key", "")).strip()
        group["issue_key"] = issue_key
        claim_ids = group.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids:
            raise ValueError(f"Disposition group has no claim_ids: {group_id}")
        normalized_ids: list[str] = []
        for value in claim_ids:
            claim_id = str(value).strip()
            if not claim_id:
                raise ValueError(f"Disposition group contains an empty claim_id: {group_id}")
            if claim_id in supported_ids:
                raise ValueError(f"Supported claim_id cannot appear in disposition: {claim_id}")
            if claim_id not in unsupported_ids:
                raise ValueError(f"Unknown claim_id in disposition: {claim_id}")
            if claim_id in seen_claim_ids:
                raise ValueError(f"Unsupported claim_id appears more than once: {claim_id}")
            seen_claim_ids.add(claim_id)
            normalized_ids.append(claim_id)
        group["claim_ids"] = normalized_ids
        if category in {"existing_gap", "new_public_gap", "cus", "mat", "anm"} and not issue_key:
            raise ValueError(f"Disposition category {category} requires issue_key: {group_id}")
        if category in {"existing_gap", "new_public_gap"}:
            if issue_key in seen_public_issue_keys:
                raise ValueError(
                    f"Public knowledge gap must be represented by one group per issue_key: {issue_key}; "
                    "combine its claim_ids instead of repeating the same gap in 50"
                )
            seen_public_issue_keys.add(issue_key)
        if category in {"package_omission", "writing_only"} and issue_key:
            raise ValueError(f"Disposition category {category} must not invent issue_key: {group_id}")

        if schema_version == "1.0":
            if category == "writing_only":
                raise ValueError(
                    f"Disposition schema 1.0 cannot use writing_only; reclassify {group_id} with schema 1.1"
                )
        else:
            fact_check = group.get("fact_check")
            if not isinstance(fact_check, dict):
                raise ValueError(f"Disposition group is missing fact_check: {group_id}")
            contains_factual = fact_check.get("contains_factual_judgment")
            reusable = fact_check.get("reusable_across_articles")
            if not isinstance(contains_factual, bool) or not isinstance(reusable, bool):
                raise ValueError(
                    f"Disposition fact_check booleans are invalid: {group_id}"
                )
            domains = fact_check.get("knowledge_domains")
            if not isinstance(domains, list) or not domains:
                raise ValueError(
                    f"Disposition fact_check knowledge_domains are missing: {group_id}"
                )
            normalized_domains = []
            for value in domains:
                domain = str(value).strip()
                if domain not in FACT_CHECK_DOMAINS:
                    raise ValueError(
                        f"Disposition fact_check domain is invalid for {group_id}: {domain}"
                    )
                if domain not in normalized_domains:
                    normalized_domains.append(domain)
            if "none" in normalized_domains and len(normalized_domains) != 1:
                raise ValueError(
                    f"Disposition fact_check domain none cannot be combined for {group_id}"
                )
            why_not = str(fact_check.get("why_not_knowledge_issue", "")).strip()
            group["fact_check"] = {
                "contains_factual_judgment": contains_factual,
                "reusable_across_articles": reusable,
                "knowledge_domains": normalized_domains,
                "why_not_knowledge_issue": why_not,
            }

            if category == "writing_only":
                if contains_factual or reusable or normalized_domains != ["none"]:
                    raise ValueError(
                        f"writing_only fact_check is inconsistent for {group_id}; split factual or reusable claims"
                    )
                if len(why_not) < 8 or why_not.lower() in {
                    "无", "不适用", "无需治理", "纯写作内容", "writing only",
                }:
                    raise ValueError(
                        f"writing_only requires a concrete why_not_knowledge_issue: {group_id}"
                    )
                claim_text = "\n".join(
                    str(
                        claim_by_id[claim_id].get("claim")
                        or claim_by_id[claim_id].get("article_claim")
                        or claim_by_id[claim_id].get("text")
                        or claim_by_id[claim_id].get("statement")
                        or ""
                    )
                    for claim_id in normalized_ids
                )
                matched_risks = [
                    label for label, pattern in WRITING_ONLY_RISK_PATTERNS
                    if pattern.search(claim_text)
                ]
                if matched_risks:
                    raise ValueError(
                        f"writing_only contains protected factual-domain signals for {group_id}: "
                        + ", ".join(matched_risks)
                    )
            else:
                if not contains_factual and not reusable:
                    raise ValueError(
                        f"Non-writing disposition must be factual or reusable: {group_id}"
                    )
                if normalized_domains == ["none"]:
                    raise ValueError(
                        f"Non-writing disposition cannot use knowledge domain none: {group_id}"
                    )
                if why_not:
                    raise ValueError(
                        f"Non-writing disposition must leave why_not_knowledge_issue empty: {group_id}"
                    )
                if category == "package_omission":
                    if reusable:
                        raise ValueError(
                            f"package_omission cannot contain cross-article reusable knowledge: {group_id}; "
                            "record a public gap or another governance item"
                        )
                    if "customer_fact" not in normalized_domains:
                        raise ValueError(
                            f"package_omission is only for an existing verified customer fact omitted from 30: {group_id}"
                        )
                    basis = group["classification_basis"]
                    if not re.search(r"(?:正式Claim|正式知识|35_写作素材来源索引|35写作素材来源索引)", basis):
                        raise ValueError(
                            f"package_omission must identify the existing formal knowledge or 35 mapping checked: {group_id}"
                        )
        normalized.append(group)

    missing = sorted(unsupported_ids - seen_claim_ids)
    if missing:
        raise ValueError("Unsupported claim_ids are missing from disposition: " + ", ".join(missing))
    if not unsupported_ids and normalized:
        raise ValueError("Disposition groups were supplied although there are no unsupported facts")
    return normalized


def validate_disposition_links(
    groups: list[dict[str, Any]],
    project_root: Path,
    article_id: str,
) -> None:
    public_groups = [
        group for group in groups
        if group["category"] in {"existing_gap", "new_public_gap"}
    ]
    if public_groups:
        gap_path = project_root / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
        if not gap_path.is_file():
            raise ValueError(f"Knowledge-gap ledger not found: {gap_path}")
        with gap_path.open("r", encoding="utf-8-sig", newline="") as stream:
            gap_rows = {row.get("gap_key", ""): row for row in csv.DictReader(stream)}
        for group in public_groups:
            row = gap_rows.get(group["issue_key"])
            if row is None:
                raise ValueError(
                    f"Disposition gap_key is not recorded before import: {group['issue_key']}"
                )
            article_ids = {
                item.strip() for item in str(row.get("article_ids", "")).split(";") if item.strip()
            }
            if article_id not in article_ids:
                raise ValueError(
                    f"Disposition gap_key does not include current article_id: {group['issue_key']}"
                )

    for group in groups:
        category = group["category"]
        if category not in GOVERNANCE_LEDGERS:
            continue
        issue_key = group["issue_key"]
        expected_marker = f"-{category.upper()}-"
        if expected_marker not in issue_key:
            raise ValueError(f"Disposition {category} issue_key has wrong prefix: {issue_key}")
        ledger = project_root / GOVERNANCE_LEDGERS[category]
        if not ledger.is_file() or issue_key not in read_text(ledger):
            raise ValueError(
                f"Disposition governance item is not recorded before import: {issue_key} ({ledger})"
            )


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
    for path in knowledge_root.rglob("*.md"):
        text = read_text(path)
        # 支持“描述性标题 + Claim ID元数据”，也兼容标题直接带ID的旧格式。
        blocks = re.finditer(r"(?ms)^#{2,6}\s+(.+?)\s*$\n(.*?)(?=^#{2,6}\s|\Z)", text)
        for match in blocks:
            heading = match.group(1).strip()
            body = match.group(2)
            id_match = re.search(
                r"(?m)^\s*[-*]\s*Claim ID[：:]\s*(CLM-[A-Za-z0-9_.-]+)\s*$", body
            )
            if id_match:
                claim_id = id_match.group(1)
            else:
                direct = re.match(r"^(CLM-[A-Za-z0-9_.-]+)(?:\s*[｜|]\s*(.*))?$", heading)
                if not direct:
                    continue
                claim_id = direct.group(1)
            title = heading
            if title.startswith(claim_id):
                title = title[len(claim_id):].lstrip("｜| ")
            catalog[claim_id] = (title or claim_id, str(path.relative_to(project_root)))
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
        if claim_id not in catalog:
            raise ValueError(f"正式Claim无法定位到知识目录文件：{claim_id}")
        title, knowledge_path = catalog[claim_id]
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
    if "--self-test" in sys.argv:
        self_test()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--judgments", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--article", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, action="append", required=True)
    parser.add_argument("--article-version", required=True)
    parser.add_argument(
        "--handoff-contract-version",
        help="v0.6受管导入必填；必须与prepared和当前安装合同一致。",
    )
    parser.add_argument("--article-date", required=True)
    parser.add_argument("--metrics-csv", type=Path, required=True)
    parser.add_argument("--support-csv", type=Path, required=True)
    parser.add_argument("--support-summary", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--disposition",
        type=Path,
        help="Required when judgments contain unsupported facts; exhaustive grouped handling JSON.",
    )
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
                "manage-article-knowledge v0.6 accepts exactly one factual input: 30_本篇知识库资料.md"
            )
        if new_view_inputs[0].name != "30_本篇知识库资料.md":
            raise SystemExit("The v0.6 writing-material input must be named 30_本篇知识库资料.md")
        knowledge_text = read_text(new_view_inputs[0])
        if parse_field(knowledge_text, "文章ID") == "" or parse_field(knowledge_text, "文章版本") == "":
            raise SystemExit("The v0.6 writing-material input must contain 文章ID and 文章版本")
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
    managed_contract = args.result_dir is not None or prepared.get("integration_mode") == "manage-article-knowledge-v0.6"
    contract_version = ""
    if managed_contract:
        try:
            contract = load_contract()
            contract_version = validate_version(args.handoff_contract_version or "", contract)
        except HandoffContractError as exc:
            raise SystemExit(str(exc)) from exc
        if str(prepared.get("handoff_contract_version", "")).strip() != contract_version:
            raise SystemExit(
                "prepared handoff_contract_version does not match the supplied/current contract"
            )
        result_dir_for_event = str((args.result_dir or args.prepared.parent).resolve())
        try:
            validate_event(
                "faithfulness_completed",
                {
                    "handoff_event": "faithfulness_completed",
                    "handoff_contract_version": contract_version,
                    "result_dir": result_dir_for_event,
                    "article_id": article_id,
                    "article_version": args.article_version,
                },
                contract,
            )
        except HandoffContractError as exc:
            raise SystemExit(str(exc)) from exc
    evaluation_mode = str(judgments.get("evaluation_mode", "")).strip()
    if not evaluation_mode:
        raise SystemExit("Judgment artifact is missing evaluation_mode")
    prepared_version = str(prepared.get("article_version", "")).strip()
    if prepared_version and prepared_version != args.article_version:
        raise SystemExit("Prepared article_version does not match the supplied article version")
    article_text = read_text(args.article)
    article_metadata_id = parse_field(article_text, "文章ID")
    article_metadata_version = parse_field(article_text, "文章版本")
    if article_metadata_id and article_metadata_id != article_id:
        raise SystemExit("Article ID does not match the Faithfulness artifacts")
    if article_metadata_version and article_metadata_version != args.article_version:
        raise SystemExit("Article version does not match the Faithfulness artifacts")
    if args.result_dir:
        result_dir = args.result_dir.resolve()
        expected_version_dir = "v" + args.article_version.strip().lstrip("vV")
        project_root_for_result = args.article.resolve().parents[3]
        try:
            project_id = project_id_for_root(project_root_for_result)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if (
            result_dir.name != expected_version_dir
            or result_dir.parent.name != article_id
            or result_dir.parent.parent.name != project_id
            ):
            raise SystemExit(
                "Faithfulness result directory must be [result root]/[project_id]/[article_id]/v[version]"
            )
        if str(prepared.get("project_id", "")).strip() != project_id:
            raise SystemExit("Prepared project_id does not match Faithfulness result directory")
        if args.prepared.resolve().parent != result_dir or args.judgments.resolve().parent != result_dir or args.summary.resolve().parent != result_dir:
            raise SystemExit("Faithfulness artifacts must all be inside --result-dir")
        if prepared.get("integration_mode") != "manage-article-knowledge-v0.6":
            raise SystemExit("--result-dir requires a v0.6 managed prepared artifact")
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
    try:
        disposition_groups = load_disposition(args.disposition, article_id, claims)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
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
    recorded_article_hash = str(prepared.get("article_sha256", "")).strip().lower()
    if recorded_article_hash and recorded_article_hash != article_hash:
        # Markdown editors can rewrite serialization without changing parsed
        # article content; reject only a semantic content change.
        if prepared.get("article_lines") != extract_article_lines(args.article):
            raise SystemExit("Prepared article content does not match the current final article")
    knowledge_hashes = [sha256_file(path) for path in args.knowledge]
    recorded_knowledge_hashes = prepared.get("knowledge_sha256")
    if recorded_knowledge_hashes and recorded_knowledge_hashes != knowledge_hashes:
        raise SystemExit("Prepared knowledge SHA-256 does not match the current knowledge files")
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
    existing_audits = [row for row in metrics_rows if row.get("audit_id") == audit_id]
    if existing_audits:
        for existing in existing_audits:
            if audit_matches_existing(
                existing,
                article_id=article_id,
                article_version=args.article_version,
                article_hash=article_hash,
                knowledge_hashes=knowledge_hashes,
            ):
                completed_article = existing.get("article_file", "")
                completed_task = str(Path(completed_article).parent) if completed_article else ""
                if not completed_task or Path(completed_task).parent.name != "40_已完成":
                    raise SystemExit(
                        "Audit记录存在，但当前完成任务目录无效；拒绝签发article_completed"
                    )
                completion_receipt = None
                if managed_contract:
                    completion_receipt = write_completion_receipt(
                        (args.result_dir or args.summary.parent).resolve(),
                        contract_version=contract_version,
                        article_id=article_id,
                        article_version=args.article_version,
                        task_dir=completed_task,
                        audit_id=audit_id,
                        imported_at=existing.get("imported_at", ""),
                    )
                print(f"audit_id={audit_id}")
                print("idempotent=true")
                print("message=该Faithfulness Audit已成功导入，无需重复处理")
                if managed_contract:
                    print("handoff_event=article_completed")
                    print(f"handoff_contract_version={contract_version}")
                    print("issuer=import_faithfulness.py")
                print(f"article_id={article_id}")
                print(f"article_version={args.article_version}")
                print(f"task_dir={completed_task}")
                if managed_contract:
                    print(f"faithfulness_imported_at={existing.get('imported_at', '')}")
                if completion_receipt:
                    print(f"completion_receipt={completion_receipt}")
                return
        raise SystemExit(f"Audit ID已存在但输入身份不一致，拒绝重复导入：{audit_id}")
    source_task = args.article.parent.resolve()
    if source_task.parent.name != "30_等待Faithfulness":
        raise SystemExit(f"Faithfulness导入任务必须位于30_等待Faithfulness：{source_task}")
    project_root = args.metrics_csv.resolve().parents[2]
    try:
        validate_disposition_links(disposition_groups, project_root, article_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    destination_task = project_root / "04_文章任务/40_已完成" / source_task.name
    if destination_task.exists():
        raise SystemExit(f"目标文章任务已存在，拒绝覆盖：{destination_task}")
    current_article_path = destination_task / args.article.name
    current_knowledge_paths = [destination_task / path.name for path in args.knowledge]
    for row in support_rows:
        row["evidence_source_file"] = remap_task_path(
            str(row.get("evidence_source_file", "")), source_task, destination_task
        )
    for row in metrics_rows:
        if row["article_id"] == article_id and row["status"] == "current":
            row["status"] = "superseded"
    metric_row = {
        "audit_id": audit_id,
        "article_id": article_id,
        "article_version": args.article_version,
        "article_date": args.article_date,
        "article_file": str(current_article_path),
        "article_sha256": article_hash,
        "knowledge_files": json.dumps([str(path) for path in current_knowledge_paths], ensure_ascii=False),
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
    support_summary = args.support_summary or args.support_csv.with_name("30_Claim文章支撑总表.md")
    # Preflight the derived summary before mutating any CSV or moving the task.
    summary_preflight = support_summary.with_suffix(support_summary.suffix + ".preflight")
    try:
        write_support_summary(summary_preflight, project_root, metrics_rows, existing_support)
    except Exception:
        if summary_preflight.exists():
            summary_preflight.unlink()
        raise
    metrics_preflight = args.metrics_csv.with_suffix(args.metrics_csv.suffix + ".preflight")
    support_preflight = args.support_csv.with_suffix(args.support_csv.suffix + ".preflight")
    try:
        write_csv(metrics_preflight, METRIC_FIELDS, metrics_rows)
        write_csv(support_preflight, SUPPORT_FIELDS, existing_support)
    except Exception:
        metrics_preflight.unlink(missing_ok=True)
        support_preflight.unlink(missing_ok=True)
        summary_preflight.unlink(missing_ok=True)
        raise
    try:
        validate_transition_inputs(args.article.parent, "40_已完成")
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        if summary_preflight.exists():
            summary_preflight.unlink()
        metrics_preflight.unlink(missing_ok=True)
        support_preflight.unlink(missing_ok=True)
        raise SystemExit(f"状态迁移预检查失败，未写入Faithfulness结果或指标：{exc}") from exc
    mark_low_faithfulness_cus_recheck(
        source_task / "20_文章前知识审核.md", score
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    knowledge_hash_text = "；".join(
        f"{path} = {checksum}"
        for path, checksum in zip(current_knowledge_paths, knowledge_hashes)
    )
    score_text = "暂无结果" if score is None else f"{score:.2f}%"
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
                    "已支持",
                ]
            ) + " |"
        )
    if not support_table_rows:
        support_table_rows.append("| 无可确定映射 | 无 | 无 | 无 | 无 |")

    category_labels = {
        "existing_gap": "已有公共知识缺口",
        "new_public_gap": "新增公共知识缺口",
        "cus": "CUS客户确认",
        "mat": "MAT源资料处理",
        "anm": "ANM源文与事实异常",
        "package_omission": "资料包覆盖遗漏",
        "writing_only": "无需治理的写作内容",
    }
    disposition_table_rows: list[str] = []
    action_table_rows: list[str] = []
    actionable_groups: list[dict[str, Any]] = []
    for group in disposition_groups:
        if group["category"] == "writing_only":
            issue_entry = "无（不是知识事项）"
        elif group["issue_key"]:
            issue_entry = f"{group['issue_key']}｜{group['entry']}"
        else:
            issue_entry = group["entry"]
        disposition_table_rows.append(
            "| " + " | ".join(
                [
                    markdown_cell(f"{group['group_id']}（{', '.join(group['claim_ids'])}）"),
                    markdown_cell(group["topic"]),
                    markdown_cell(category_labels[group["category"]]),
                    markdown_cell(group["classification_basis"]),
                    markdown_cell(group["article_impact"]),
                    markdown_cell(issue_entry),
                    markdown_cell(group["handling"]),
                    markdown_cell(f"{group['next_owner']}；{group['close_condition']}"),
                ]
            ) + " |"
        )
        if group["category"] != "writing_only" or group["next_owner"] not in {"无", "无需处理"}:
            actionable_groups.append(group)
            action_table_rows.append(
                "| " + " | ".join(
                    [
                        markdown_cell(f"{group['group_id']}｜{group['topic']}"),
                        markdown_cell(group["status"]),
                        markdown_cell(group["next_owner"]),
                        markdown_cell(group["entry"]),
                        markdown_cell(group["close_condition"]),
                    ]
                ) + " |"
            )
    if not disposition_table_rows:
        disposition_table_rows.append(
            "| 无 | 本篇事实均被本次附件覆盖 | 无需归组 | 无 | 无 | 无 | 无需处理 | 无 |"
        )
    if not action_table_rows:
        action_table_rows.append("| 无 | 无需处理 | 无 | 无 | 无 |")
    receipt_status = "已导入，存在待处理事项" if actionable_groups else "已导入，观察完成"
    receipt_preflight = args.receipt.with_suffix(args.receipt.suffix + ".preflight")
    receipt_preflight.write_text(
        "\n".join(
            [
                "# 文章知识使用与Faithfulness记录",
                "",
                f"- 文章ID：{article_id}",
                f"- 文章标题：{article_title}",
                f"- 文章版本：{args.article_version}",
                f"- 模板版本：{TEMPLATE_VERSION}",
                f"- 交接合同版本：{contract_version or '不适用（兼容旧流程）'}",
                f"- 当前状态：{receipt_status}",
                f"- 终稿：[[{args.article.name}]]",
                "- 本篇知识库资料：[[30_本篇知识库资料.md]]",
                "- 写作素材来源索引：[[35_写作素材来源索引.md]]",
                f"- 终稿接收日期：{args.article_date}",
                f"- Faithfulness结果入口：{result_entry}",
                f"- 指定审核结果目录：{result_directory}",
                f"- Faithfulness导入日期：{imported_at}",
                "- Faithfulness执行器：deepeval-article-audit",
                f"- 外部审核模式：{evaluation_mode}",
                f"- 外部结果文件：{args.summary.resolve()}",
                f"- 外部判断文件：{args.judgments.resolve()}",
                f"- unsupported归组处置文件：{args.disposition.resolve() if args.disposition else '不适用（无unsupported）'}",
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
                "全部unsupported claim_id已按稳定知识问题穷尽且互斥归组；终稿不作为证据。",
                "",
                "| 归组及claim_id | 知识问题/内容 | 分类 | 分类依据 | 本篇影响 | 关联事项/入口 | 当前处理 | 下一步 |",
                "|---|---|---|---|---|---|---|---|",
                *disposition_table_rows,
                "",
                "## 四、后续动作",
                "",
                "| 事项 | 当前状态 | 下一责任人 | 关联入口 | 更新/关闭条件 |",
                "|---|---|---|---|---|",
                *action_table_rows,
                "",
                "## 五、更新记录",
                "",
                "| 日期 | 事件 | 结果/状态 | 相关文件 |",
                "|---|---|---|---|",
                f"| {imported_at} | 导入外部Faithfulness结果并核验unsupported归组 | 当前有效 | {args.summary.resolve()} |",
                "",
                "本记录导入外部审核结论，本Skill没有重新执行Faithfulness语义判断。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    receipt_errors = validate_file(
        receipt_preflight, "50_文章知识使用与Faithfulness记录.md"
    )
    if receipt_errors or "等待结果" in read_text(receipt_preflight):
        details = "；".join(receipt_errors) or "仍含等待结果占位内容"
        receipt_preflight.unlink(missing_ok=True)
        summary_preflight.unlink(missing_ok=True)
        metrics_preflight.unlink(missing_ok=True)
        support_preflight.unlink(missing_ok=True)
        raise SystemExit(f"50记录完成门禁失败，任务保持30_等待Faithfulness：{details}")
    metrics_preflight.replace(args.metrics_csv)
    support_preflight.replace(args.support_csv)
    summary_preflight.replace(support_summary)
    receipt_preflight.replace(args.receipt)
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
    try:
        rebuild_view(project_root)
    except Exception as exc:
        raise SystemExit(f"Faithfulness已导入，但知识库覆盖页重建失败：{exc}") from exc
    update_integration_status(
        project_root,
        "faithfulness_import_success",
        article_id=article_id,
        article_version=args.article_version,
        detail=f"导入ID：{audit_id}",
    )
    completion_receipt = None
    if managed_contract:
        completion_receipt = write_completion_receipt(
            result_directory,
            contract_version=contract_version,
            article_id=article_id,
            article_version=args.article_version,
            task_dir=str(completed_task),
            audit_id=audit_id,
            imported_at=imported_at,
        )
    print(f"audit_id={audit_id}")
    print(f"article_id={article_id}")
    print(f"faithfulness={score_text}")
    print(f"mapped_formal_claims={len(mapped_claim_ids)}")
    print(f"unmapped_supported_claims={len(unmapped_supported)}")
    print(f"task={completed_task}")
    print("handoff_event=article_completed")
    if contract_version:
        print(f"handoff_contract_version={contract_version}")
        print("issuer=import_faithfulness.py")
    print(f"article_version={args.article_version}")
    print(f"task_dir={completed_task}")
    if managed_contract:
        print(f"faithfulness_imported_at={imported_at}")
    if completion_receipt:
        print(f"completion_receipt={completion_receipt}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        # Best-effort failure telemetry; never hide the original CLI error.
        try:
            if "--metrics-csv" in sys.argv:
                metrics = Path(sys.argv[sys.argv.index("--metrics-csv") + 1]).resolve()
                if metrics.is_file() and len(metrics.parents) >= 3:
                    update_integration_status(
                        metrics.parents[2],
                        "faithfulness_import_failure",
                        error=str(exc),
                    )
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            if "--metrics-csv" in sys.argv:
                metrics = Path(sys.argv[sys.argv.index("--metrics-csv") + 1]).resolve()
                if metrics.is_file() and len(metrics.parents) >= 3:
                    update_integration_status(
                        metrics.parents[2],
                        "faithfulness_import_failure",
                        error=str(exc),
                    )
        except Exception:
            pass
        raise
