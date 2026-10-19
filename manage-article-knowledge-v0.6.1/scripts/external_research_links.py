#!/usr/bin/env python3
"""Maintain explicit GAP / RES / Claim links without judging research conclusions."""
from __future__ import annotations

import argparse
import csv
import re
import tempfile
from pathlib import Path

RESEARCH_ROOT = Path("02_源资料/50_外部调研证据")
GAP_CSV = Path("05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv")
HEADING = "## GAP / RES / Claim关联"
FIELDS = ("GAP ID", "缺口主题", "本次RES已回答范围", "尚缺范围", "关联Claim/正式知识", "本次处理结果")
PROTOCOL = "- 缺口关联协议：GR-1"
EMPTY = {"", "无", "不适用"}
RESULTS = {"待外部调研", "部分解决", "已解决", "仅复核"}
CLAIM_RE = re.compile(r"\bCLM-[A-Za-z0-9_.-]+\b")
GAP_RE = re.compile(r"\bGAP-[A-Za-z0-9-]+\b")
RES_RE = re.compile(r"\bRES-[A-Za-z0-9-]+\b")


def field(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*-\s*{re.escape(name)}[：:]\s*(.*?)\s*$", text)
    return match.group(1) if match else ""


def research_id(path: Path, text: str) -> str:
    return field(text, "调研ID") or path.parent.name.split("_", 1)[0]


def parse_links(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """Strict only for opt-in records; legacy records remain readable."""
    protocol = field(text, "缺口关联协议")
    errors: list[str] = []
    if protocol and protocol != "GR-1":
        errors.append(f"未知缺口关联协议：{protocol}")
    sections = list(re.finditer(r"(?m)^## GAP / RES / Claim关联\s*$", text))
    if not sections:
        return [], errors + (["GR-1缺少固定关联表"] if protocol else [])
    if len(sections) != 1:
        errors.append("GAP / RES / Claim关联章节重复")
    body = text[sections[0].end():]
    body = re.split(r"(?m)^## ", body, maxsplit=1)[0]
    # Links may contain alias pipes, so split only unescaped table delimiters.
    table = [re.split(r"(?<!\\)\|", line.strip())[1:-1]
             for line in body.splitlines() if line.strip().startswith("|")]
    table = [[cell.strip().replace(r"\|", "|") for cell in row] for row in table]
    if len(table) < 2 or tuple(table[0]) != FIELDS:
        return [], errors + ["缺口关联表表头不符合固定模板"]
    if len(table[1]) != len(FIELDS) or not all(re.fullmatch(r":?-{3,}:?", c) for c in table[1]):
        errors.append("缺口关联表分隔行无效")
    rows = []
    seen = set()
    for cells in table[2:]:
        if len(cells) != len(FIELDS):
            errors.append("缺口关联表列数错误")
            continue
        row = dict(zip(FIELDS, cells))
        key = row[FIELDS[0]]
        if key in seen:
            errors.append(f"同一RES重复登记GAP：{key}")
        seen.add(key)
        if not GAP_RE.fullmatch(key) and key != "无":
            errors.append(f"每行只能登记一个GAP ID：{key}")
        result = row[FIELDS[5]]
        if result not in RESULTS or (key == "无") != (result == "仅复核"):
            errors.append(f"GAP {key}处理结果无效")
        if row[FIELDS[1]] in EMPTY:
            errors.append(f"GAP {key}缺少具体主题")
        if result in {"已解决", "部分解决"}:
            if row[FIELDS[2]] in EMPTY or not CLAIM_RE.search(row[FIELDS[4]]):
                errors.append(f"GAP {key}解决记录缺少已回答范围或正式Claim")
            if result == "已解决" and row[FIELDS[3]] not in {"无", "不适用"}:
                errors.append(f"GAP {key}尚有剩余范围，不能已解决")
            if result == "部分解决" and row[FIELDS[3]] in EMPTY:
                errors.append(f"GAP {key}部分解决必须写尚缺范围")
        if result == "待外部调研" and row[FIELDS[3]] in EMPTY:
            errors.append(f"GAP {key}待调研必须写尚缺范围")
        rows.append(row)
    if not rows:
        errors.append("缺口关联表不能为空；纯Claim复核使用无/仅复核行")
    return rows, errors


def claim_locations(root: Path) -> dict[str, list[Path]]:
    locations: dict[str, list[Path]] = {}
    for path in sorted((root / "03_正式知识").rglob("*.md")):
        for claim in re.findall(r"(?m)^\s*[-*]\s*Claim ID[：:]\s*(CLM-[A-Za-z0-9_.-]+)\s*$", path.read_text(encoding="utf-8-sig")):
            locations.setdefault(claim, []).append(path)
    return locations


def research_records(root: Path) -> list[dict]:
    records = []
    for path in sorted((root / RESEARCH_ROOT).rglob("20_调研核验记录.md")):
        text = path.read_text(encoding="utf-8-sig")
        rows, errors = parse_links(text)
        records.append(dict(path=path, res_id=research_id(path, text), rows=rows,
                            errors=errors, text=text, structured=HEADING in text or bool(field(text, "缺口关联协议"))))
    return records


def validate_research_links(root: Path, errors: list[str]) -> None:
    gaps = {}
    if (root / GAP_CSV).is_file():
        with (root / GAP_CSV).open(encoding="utf-8-sig", newline="") as stream:
            gaps = {r["gap_key"]: r for r in csv.DictReader(stream)}
    claims = claim_locations(root)
    for record in research_records(root):
        prefix = str(record["path"]) + ": "
        errors.extend(prefix + error for error in record["errors"])
        if not record["structured"]:
            continue
        keys = {r[FIELDS[0]] for r in record["rows"] if r[FIELDS[0]] != "无"}
        if set(GAP_RE.findall(field(record["text"], "关联缺口"))) != keys:
            errors.append(prefix + "顶部关联缺口与固定关联表不一致")
        if not record["res_id"].startswith("RES-"):
            errors.append(prefix + "缺少有效调研ID")
        source = record["path"].with_name("10_来源原文证据.md")
        if not source.is_file():
            errors.append(prefix + "缺少配对来源原文证据")
        else:
            source_text = source.read_text(encoding="utf-8-sig")
            if research_id(source, source_text) != record["res_id"] or set(GAP_RE.findall(field(source_text, "关联缺口"))) != keys:
                errors.append(prefix + "配对10来源记录的RES/GAP与20不一致")
        for row in record["rows"]:
            key = row[FIELDS[0]]
            if key != "无" and key not in gaps:
                errors.append(prefix + f"关联GAP不存在：{key}")
            elif key != "无" and record["res_id"] not in RES_RE.findall(gaps[key].get("related_governance_ref", "")):
                errors.append(prefix + f"GAP未回链当前RES：{key}")
            for claim in CLAIM_RE.findall(row[FIELDS[4]]):
                if len(claims.get(claim, [])) != 1:
                    errors.append(prefix + f"正式Claim不存在或不唯一：{claim}")


def links_for_gap(gap: dict[str, str], records: list[dict]) -> list[dict]:
    """Use explicit table rows, or explicit legacy links; never infer by topic."""
    key = gap["gap_key"]
    result = []
    for record in records:
        if record["structured"]:
            for row in record["rows"]:
                if row[FIELDS[0]] == key:
                    result.append(dict(record=record, row=row))
        elif key in GAP_RE.findall(field(record["text"], "关联缺口")) or record["res_id"] in RES_RE.findall(gap.get("related_governance_ref", "")):
            result.append(dict(record=record, row=None))
    return result


def atomic_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as stream:
        stream.write(text)
        temporary = Path(stream.name)
    temporary.replace(path)


def record_link(root: Path, record: Path, row: dict[str, str]) -> None:
    """Upsert a verified link and its CSV backlink; lifecycle stays with gap recorder."""
    from record_knowledge_gap import read_rows, write_rows
    root, record = root.resolve(), record.resolve()
    if not record.is_relative_to((root / RESEARCH_ROOT).resolve()) or record.name != "20_调研核验记录.md":
        raise ValueError("核验记录必须位于项目外部调研目录，使用固定文件名")
    text = record.read_text(encoding="utf-8-sig")
    source = record.with_name("10_来源原文证据.md")
    if not source.is_file():
        raise ValueError("先保存配对10_来源原文证据.md，再登记调研关联")
    source_text = source.read_text(encoding="utf-8-sig")
    if research_id(source, source_text) != research_id(record, text):
        raise ValueError("10和20调研ID不一致，先核对来源身份")
    rows, errors = parse_links(text)
    errors = [e for e in errors if e != "缺口关联表不能为空；纯Claim复核使用无/仅复核行"]
    if errors:
        raise ValueError("；".join(errors))
    gaps = read_rows(root / GAP_CSV)
    gap = next((g for g in gaps if g["gap_key"] == row[FIELDS[0]]), None)
    if row[FIELDS[0]] != "无" and gap is None:
        raise ValueError("先登记具体GAP，再关联RES")
    if gap:
        row = dict(row, **{FIELDS[1]: gap["gap_topic"]})
    rows = [r for r in rows if r[FIELDS[0]] != row[FIELDS[0]]]
    # A research record with actual gaps no longer needs the no-gap placeholder.
    if gap:
        rows = [r for r in rows if r[FIELDS[0]] != "无"]
    elif any(r[FIELDS[0]] != "无" for r in rows):
        raise ValueError("已有GAP关联的RES不能增加无/仅复核行")
    rows.append(row)
    def cell(value):
        return value.replace("|", r"\|").replace("\n", " ").replace("\r", " ")
    table = HEADING + "\n\n| " + " | ".join(FIELDS) + " |\n|" + "---|" * len(FIELDS) + "\n"
    table += "".join("| " + " | ".join(cell(r[f]) for f in FIELDS) + " |\n" for r in rows)
    if HEADING in text:
        text = re.sub(r"(?ms)^## GAP / RES / Claim关联\s*\n.*?(?=^## |\Z)", lambda _: table + "\n", text)
    else:
        text = text.rstrip() + "\n\n" + table
    keys = [r[FIELDS[0]] for r in rows if r[FIELDS[0]] != "无"]
    for name, value in (("缺口关联协议", "GR-1"), ("关联缺口", "; ".join(keys) or "无（仅复核既有Claim）")):
        pattern = rf"(?m)^\s*-\s*{re.escape(name)}[：:].*$"
        if re.search(pattern, text):
            text = re.sub(pattern, lambda _: f"- {name}：{value}", text)
        else:
            text = f"- {name}：{value}\n" + text
    _, errors = parse_links(text)
    if not research_id(record, text).startswith("RES-"):
        errors.append("缺少有效调研ID")
    locations = claim_locations(root)
    for claim in CLAIM_RE.findall(row[FIELDS[4]]):
        if len(locations.get(claim, [])) != 1:
            errors.append(f"正式Claim不存在或不唯一：{claim}")
    if errors:
        raise ValueError("；".join(errors))
    if gap:
        refs = [r for r in gap["related_governance_ref"].split(";") if r.strip() and r.strip() != "无"]
        refs.extend([research_id(record, text), *CLAIM_RE.findall(row[FIELDS[4]])])
        gap["related_governance_ref"] = ";".join(dict.fromkeys(refs))
        write_rows(root / GAP_CSV, gaps)
    atomic_text(record, text)
    # Source content stays verbatim; only its navigation field is synchronized.
    gap_value = "; ".join(keys) or "无（仅复核既有Claim）"
    pattern = r"(?m)^\s*-\s*关联缺口[：:].*$"
    if re.search(pattern, source_text):
        source_text = re.sub(pattern, lambda _: f"- 关联缺口：{gap_value}", source_text)
    else:
        source_text = f"- 关联缺口：{gap_value}\n" + source_text
    atomic_text(source, source_text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--gap-key", required=True)
    parser.add_argument("--topic", default="既有Claim回源复核")
    parser.add_argument("--answered", required=True)
    parser.add_argument("--remaining", required=True)
    parser.add_argument("--claims", required=True)
    parser.add_argument("--result", choices=sorted(RESULTS), required=True)
    args = parser.parse_args()
    row = dict(zip(FIELDS, (args.gap_key, args.topic, args.answered, args.remaining, args.claims, args.result)))
    try:
        record_link(args.project, args.record, row)
        from build_coverage_view import rebuild_view
        rebuild_view(args.project)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print("research_gap_link_recorded=true")


if __name__ == "__main__":
    main()
