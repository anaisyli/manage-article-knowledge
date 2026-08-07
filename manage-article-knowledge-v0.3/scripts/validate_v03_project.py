#!/usr/bin/env python3
"""Validate v0.3 Obsidian projects before writing input, deposition, or closure."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path


REQUIRED_TOP_DIRS = (
    "01_工作台",
    "02_正式知识",
    "03_文章任务",
    "04_资料与证据",
    "05_数据与审核",
    "90_归档",
)

ARTICLE_FILES = (
    "01_文章要求与大纲.md",
    "10_待提交资料清单与就绪检查.md",
    "15_提取范围与处理样本确认.md",
    "20_文章前知识审核.md",
    "30_文章写作输入.md",
    "40_最终文章与引用率.md",
)

MANAGEMENT_PREFIXES = (
    "01_工作台/",
    "03_文章任务/",
    "05_数据与审核/",
    "04_资料与证据/30_整理与翻译稿/90_处理记录/",
)

ENGLISH_MANAGEMENT_PATTERNS = (
    re.compile(r"^(Article|Page title|Retrieved|Scope|Status|Page text path|Visible text blocks|Structure note):", re.I),
    re.compile(r"^#{1,6}\s+(Processing note|Source|Status|Audit result)\s*$", re.I),
)

CUSTOMER_REQUEST_RELATIVE = Path(
    "05_数据与审核/30_异常与待决定/10_企业知识异常待处理/01_待客户补充事项.md"
)

CUSTOMER_REQUEST_STATUSES = {
    "待整理",
    "待发送",
    "已发送待回复",
    "已回复待复核",
    "已解决",
    "无法取得",
    "已关闭不再询问",
}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    file: str
    line: int
    message: str


def relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def strip_inline_code(line: str) -> str:
    return re.sub(r"`[^`]*`", "", line)


def count_table_cells(line: str) -> int:
    line = strip_inline_code(line.rstrip())
    escaped = False
    pipes = 0
    for char in line:
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "|" and not escaped:
            pipes += 1
        escaped = False
    if pipes == 0:
        return 0
    return pipes - int(line.lstrip().startswith("|")) - int(line.rstrip().endswith("|")) + 1


def is_separator_row(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def resolve_local_link(source: Path, target: str, root: Path) -> bool:
    target = target.strip().strip("<>")
    target = target.split("#", 1)[0]
    if not target or re.match(r"^(https?://|mailto:|obsidian://)", target, re.I):
        return True
    target = target.replace("%20", " ")
    candidate = (source.parent / target).resolve()
    if candidate.exists() or candidate.with_suffix(".md").exists():
        return True
    vault_candidate = root.joinpath(*target.replace("\\", "/").split("/")).resolve()
    return vault_candidate.exists() or vault_candidate.with_suffix(".md").exists()


def build_basename_map(files: list[Path]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for file in files:
        result.setdefault(file.stem, []).append(file)
    return result


def parse_field(text: str, name: str) -> str | None:
    patterns = (
        rf"(?m)^-\s*{re.escape(name)}\s*[：:]\s*(.+?)\s*$",
        rf"(?m)^{re.escape(name)}\s*[：:]\s*(.+?)\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def parse_int_field(text: str, name: str) -> int | None:
    value = parse_field(text, name)
    if value and re.fullmatch(r"\d+", value):
        return int(value)
    return None


def source_id_from_clean(path: Path, text: str) -> str | None:
    value = parse_field(text, "资料ID")
    if value:
        return value
    match = re.search(r"([A-Z][A-Z0-9-]*-SRC-\d+)", path.name, re.I)
    return match.group(1).upper() if match else None


def normalize_heading(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value).lower()


def extract_outline(text: str) -> list[str]:
    match = re.search(r"(?ms)^##\s+大纲\s*$\n(.*?)(?=^##\s+|\Z)", text)
    if not match:
        return []
    items = []
    for line in match.group(1).splitlines():
        item = re.match(r"\s*\d+[.)、]\s*(.+?)\s*$", line)
        if item:
            items.append(item.group(1).strip())
    return items


def extract_headings(text: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", text)]


def validate_project(root: Path) -> list[Issue]:
    issues: list[Issue] = []

    def add(severity: str, code: str, file: Path | None, line: int, message: str) -> None:
        issues.append(Issue(severity, code, relpath(file, root) if file else ".", line, message))

    if not root.is_dir():
        add("ERROR", "PROJECT_NOT_FOUND", None, 0, f"项目目录不存在：{root}")
        return issues

    for name in REQUIRED_TOP_DIRS:
        if not (root / name).is_dir():
            add("ERROR", "MISSING_TOP_DIR", root, 0, f"缺少v0.3顶层目录：{name}")

    customer_request_file = root / CUSTOMER_REQUEST_RELATIVE
    if not customer_request_file.is_file():
        add(
            "ERROR",
            "MISSING_CUSTOMER_REQUEST_LEDGER",
            customer_request_file,
            0,
            "缺少项目级待客户补充事项总表",
        )

    md_files = sorted(root.rglob("*.md"))
    current_md = [file for file in md_files if "/90_归档/" not in f"/{relpath(file, root)}/" and "/历史版本/" not in f"/{relpath(file, root)}/"]
    basename_map = build_basename_map(md_files)
    text_cache = {file: read_text(file) for file in md_files}

    completed_ids: set[str] = set()
    article_dirs: list[tuple[str, Path]] = []
    article_root = root / "03_文章任务"
    for status in ("10_进行中", "20_等待终稿", "30_已完成"):
        status_root = article_root / status
        if not status_root.exists():
            continue
        for year_month in status_root.iterdir():
            if not year_month.is_dir():
                continue
            for article_dir in year_month.iterdir():
                if article_dir.is_dir():
                    article_dirs.append((status, article_dir))
                    article_id = article_dir.name.split("_", 1)[0]
                    if status == "30_已完成":
                        completed_ids.add(article_id)

    for file in current_md:
        text = text_cache[file]
        relative = relpath(file, root)

        for match in re.finditer(r"\$srcLink|\{\{[^}\n]+\}\}|(?i:\bTODO\b|\bTBD\b)", text):
            add("ERROR", "PLACEHOLDER", file, line_number(text, match.start()), f"残留未替换变量：{match.group(0)}")

        for match in re.finditer(r"(?i)(?:<|\()\s*[A-Z]:[/\\]Users[/\\][^)>\n]+", text):
            add("ERROR", "OLD_COMPUTER_LINK", file, line_number(text, match.start()), "存在指向电脑用户目录的不可移植链接")

        if relative.startswith(MANAGEMENT_PREFIXES):
            if not relative.endswith("/30_文章写作输入.md") and not relative.endswith("/40_最终文章与引用率.md"):
                for number, line in enumerate(text.splitlines(), 1):
                    if any(pattern.search(line) for pattern in ENGLISH_MANAGEMENT_PATTERNS):
                        add("ERROR", "ENGLISH_MANAGEMENT_FIELD", file, number, f"管理层应使用中文：{line.strip()}")

        lines = text.splitlines()
        row = 0
        while row + 1 < len(lines):
            if lines[row].lstrip().startswith("|") and is_separator_row(lines[row + 1]):
                expected = count_table_cells(lines[row])
                cursor = row + 2
                while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
                    actual = count_table_cells(lines[cursor])
                    if actual != expected:
                        add("ERROR", "TABLE_COLUMNS", file, cursor + 1, f"表格列数不一致：表头{expected}列，本行{actual}列")
                    cursor += 1
                row = cursor
            else:
                row += 1

        for match in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text):
            target = match.group(1).strip()
            ok = False
            if "/" in target or "\\" in target:
                candidate = root / target.replace("\\", "/")
                ok = candidate.exists() or candidate.with_suffix(".md").exists()
            else:
                ok = len(basename_map.get(target, [])) == 1
            if not ok:
                add("ERROR", "BROKEN_WIKILINK", file, line_number(text, match.start()), f"无法解析Wikilink：{target}")

        for match in re.finditer(r"(?<!!)\[[^\]\n]+\]\((<[^>]+>|[^)\n]+)\)", text):
            target = match.group(1).strip()
            if not resolve_local_link(file, target, root):
                add("ERROR", "BROKEN_MD_LINK", file, line_number(text, match.start()), f"无法解析Markdown链接：{target}")

    if customer_request_file.is_file():
        customer_text = text_cache.get(customer_request_file, read_text(customer_request_file))
        for heading in ("# 待客户补充事项", "## 当前事项", "## 事项详情"):
            if heading not in customer_text:
                add(
                    "ERROR",
                    "CUSTOMER_REQUEST_SECTION",
                    customer_request_file,
                    1,
                    f"待客户补充事项缺少小节：{heading.lstrip('# ').strip()}",
                )

        table_lines = customer_text.splitlines()
        header_index = next(
            (
                index
                for index, line in enumerate(table_lines)
                if line.lstrip().startswith("|")
                and "问题ID" in line
                and "当前状态" in line
                and "回复或证据位置" in line
            ),
            None,
        )
        if header_index is None:
            add(
                "ERROR",
                "CUSTOMER_REQUEST_TABLE",
                customer_request_file,
                1,
                "待客户补充事项缺少固定当前事项表",
            )
        else:
            headers = [cell.strip() for cell in table_lines[header_index].strip().strip("|").split("|")]
            id_index = headers.index("问题ID")
            status_index = headers.index("当前状态")
            evidence_index = headers.index("回复或证据位置")
            seen_request_ids: set[str] = set()
            cursor = header_index + 2
            while cursor < len(table_lines) and table_lines[cursor].lstrip().startswith("|"):
                cells = [cell.strip() for cell in table_lines[cursor].strip().strip("|").split("|")]
                if len(cells) == len(headers) and any(cells):
                    request_id = cells[id_index]
                    status = cells[status_index]
                    evidence = cells[evidence_index]
                    if request_id:
                        if request_id in seen_request_ids:
                            add(
                                "ERROR",
                                "DUPLICATE_CUSTOMER_REQUEST_ID",
                                customer_request_file,
                                cursor + 1,
                                f"待客户补充事项问题ID重复：{request_id}",
                            )
                        seen_request_ids.add(request_id)
                        if status not in CUSTOMER_REQUEST_STATUSES:
                            add(
                                "ERROR",
                                "CUSTOMER_REQUEST_STATUS",
                                customer_request_file,
                                cursor + 1,
                                f"待客户补充事项状态无效：{status or '空值'}",
                            )
                        if status == "已解决" and not evidence:
                            add(
                                "ERROR",
                                "CUSTOMER_REQUEST_EVIDENCE",
                                customer_request_file,
                                cursor + 1,
                                "已解决的客户补充事项必须填写回复或证据位置",
                            )
                cursor += 1

    knowledge_ids: dict[str, tuple[Path, int]] = {}
    for file in current_md:
        text = text_cache[file]
        for match in re.finditer(r"(?mi)^(?:knowledge_id\s*:|-\s*知识ID\s*[：:])\s*([^\s#]+)", text):
            knowledge_id = match.group(1).strip()
            if not knowledge_id or knowledge_id in {"未分配", "无"}:
                continue
            if knowledge_id in knowledge_ids:
                previous, previous_line = knowledge_ids[knowledge_id]
                add("ERROR", "DUPLICATE_KNOWLEDGE_ID", file, line_number(text, match.start()), f"知识ID重复；首次出现于{relpath(previous, root)}:{previous_line}")
            else:
                knowledge_ids[knowledge_id] = (file, line_number(text, match.start()))

    formal_root = root / "02_正式知识"
    if formal_root.exists():
        for file in formal_root.rglob("*.md"):
            relative = relpath(file, root)
            if "/01_" in f"/{relative}" and ("目录" in file.name or "总览" in file.name):
                continue
            text = text_cache.get(file, read_text(file))
            for match in re.finditer(r"\]\(([^)]+)\)|\[\[([^\]]+)\]\]", text):
                target = " ".join(group or "" for group in match.groups())
                if "30_文章写作输入" in target or "40_最终文章与引用率" in target:
                    add("ERROR", "FORMAL_FROM_ARTICLE", file, line_number(text, match.start()), "正式知识不得把写作输入或最终文章作为事实来源")
            if "## 来源" not in text:
                add("ERROR", "FORMAL_SOURCE_SECTION", file, 1, "正式知识缺少“来源”小节")

            if "/10_企业提供/" in f"/{relative}" and re.search(r"(?mi)^source_type\s*:\s*Codex外部调研", text):
                add("ERROR", "SOURCE_DIR_MIXED", file, 1, "Codex外部调研误放入企业提供目录")
            if "/20_Codex外部调研/" in f"/{relative}" and re.search(r"(?mi)^source_type\s*:\s*企业提供", text):
                add("ERROR", "SOURCE_DIR_MIXED", file, 1, "企业提供资料误放入Codex外部调研目录")

    clean_dir = root / "04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿"
    clean_ids: dict[str, Path] = {}
    if clean_dir.exists():
        for file in clean_dir.glob("*.md"):
            text = text_cache.get(file, read_text(file))
            source_id = source_id_from_clean(file, text)
            if not source_id:
                add("ERROR", "CLEAN_SOURCE_ID", file, 1, "当前清理稿缺少资料ID")
            elif source_id in clean_ids:
                add("ERROR", "DUPLICATE_CLEAN_DRAFT", file, 1, f"同一资料存在多份当前清理稿；另一份为{relpath(clean_ids[source_id], root)}")
            else:
                clean_ids[source_id] = file

            if re.search(r"(?i)(topic[_-]|话题稿)", file.name):
                add("ERROR", "TOPIC_DRAFT", file, 1, "当前整理区禁止文章话题稿")

            required = ("对应原文件", "已确认范围", "范围确认", "核验状态")
            for field in required:
                if not parse_field(text, field):
                    add("ERROR", "CLEAN_REQUIRED_FIELD", file, 1, f"清理稿缺少字段：{field}")
            for heading in ("## 位置与正文结构定位", "## 清理后的正文", "## 差异与补核记录", "## 未处理或明确排除范围", "## 来源与回溯"):
                if heading not in text:
                    add("ERROR", "CLEAN_REQUIRED_SECTION", file, 1, f"清理稿缺少小节：{heading[3:]}")

            original_file = parse_field(text, "对应原文件") or ""
            if re.search(r"(?i)\.(pdf|pptx?)\b", original_file):
                for field in ("原始表格数（确认范围内）", "当前保留表格数", "原始公式数（确认范围内）", "当前保留公式数"):
                    if parse_int_field(text, field) is None:
                        add("ERROR", "STRUCTURE_COUNT", file, 1, f"PDF/PPT清理稿缺少可校验整数：{field}")
                original_tables = parse_int_field(text, "原始表格数（确认范围内）")
                clean_tables = parse_int_field(text, "当前保留表格数")
                original_formulas = parse_int_field(text, "原始公式数（确认范围内）")
                clean_formulas = parse_int_field(text, "当前保留公式数")
                exclusion = parse_field(text, "结构排除说明") or ""
                exclusion_is_valid = exclusion not in {"", "无", "不适用", "未说明"}
                if original_tables is not None and clean_tables is not None and clean_tables < original_tables and not exclusion_is_valid:
                    add("ERROR", "TABLE_LOSS", file, 1, "清理稿保留表格数少于确认范围原始表格数，且未说明排除")
                if original_formulas is not None and clean_formulas is not None and clean_formulas < original_formulas and not exclusion_is_valid:
                    add("ERROR", "FORMULA_LOSS", file, 1, "清理稿保留公式数少于确认范围原始公式数，且未说明排除")

    for status, article_dir in article_dirs:
        article_id = article_dir.name.split("_", 1)[0]
        for name in ARTICLE_FILES:
            if not (article_dir / name).is_file():
                add("ERROR", "MISSING_ARTICLE_FILE", article_dir, 0, f"文章任务缺少固定文件：{name}")

        audit = article_dir / "20_文章前知识审核.md"
        audit_text = ""
        if audit.exists():
            audit_text = text_cache.get(audit, read_text(audit))
            audit_source_text = re.sub(
                r"(?m)^-\s*(?:当前写作输入|复核对象)\s*[：:].*$",
                "",
                audit_text,
            )
            if re.search(r"\]\([^)]*30_文章写作输入|\[\[[^\]]*30_文章写作输入", audit_source_text):
                add("ERROR", "AUDIT_CIRCULAR_SOURCE", audit, 1, "文章前审核不得把尚未生成的写作输入作为来源")
            if re.search(r"以后问客户|希望客户提供|待客户确认", audit_text) and "01_待客户补充事项.md" not in audit_text:
                add(
                    "ERROR",
                    "AUDIT_CUSTOMER_REQUEST_LINK",
                    audit,
                    1,
                    "文章审核中的待客户事项必须链接项目级待客户补充事项总表",
                )

        writing = article_dir / "30_文章写作输入.md"
        if writing.exists() and writing.stat().st_size:
            writing_text = text_cache.get(writing, read_text(writing))
            if "按源文件整理" in writing_text:
                add("ERROR", "WRITING_BY_SOURCE", writing, 1, "写作输入必须按大纲组织，不得按源文件堆放")
            if (
                "## 按大纲排列的本篇可用知识" in writing_text
                or "结构化来源派生" in writing_text
                or "##### 目标语言可用内容" in writing_text
            ):
                add(
                    "ERROR",
                    "WRITING_SUMMARY_TEMPLATE",
                    writing,
                    1,
                    "写作输入仍使用容易把正文压缩为摘要的旧知识卡模板，必须按完整来源块重建",
                )
            if "## 按大纲排列的本篇可用正文" not in writing_text:
                add("ERROR", "WRITING_OUTLINE_SECTION", writing, 1, "写作输入缺少按大纲排列的完整正文区")
            if "来源：" not in writing_text or "位置：" not in writing_text:
                add("ERROR", "WRITING_INLINE_SOURCE", writing, 1, "写作输入的正文块缺少来源或精确位置")

            source_blocks = len(re.findall(r"(?m)^####\s+来源块：", writing_text))
            full_body_blocks = len(re.findall(r"(?m)^#####\s+目标语言完整正文（非摘要）\s*$", writing_text))
            adopted_ranges = len(re.findall(r"(?m)^-\s*采用范围\s*[：:]", writing_text))
            omitted_ranges = len(re.findall(r"(?m)^-\s*未迁入内容及理由\s*[：:]", writing_text))
            if source_blocks == 0:
                add("ERROR", "WRITING_SOURCE_BLOCK", writing, 1, "写作输入没有按来源建立完整正文块")
            elif full_body_blocks != source_blocks:
                add("ERROR", "WRITING_FULL_BODY_BLOCK", writing, 1, f"来源块{source_blocks}个，完整正文块{full_body_blocks}个")
            if source_blocks and (adopted_ranges < source_blocks or omitted_ranges < source_blocks):
                add("ERROR", "WRITING_RANGE_ACCOUNTING", writing, 1, "每个来源块都必须填写采用范围和未迁入内容及理由")

            writing_has_body = "## 按大纲排列的本篇可用正文" in writing_text and source_blocks > 0
            if writing_has_body and audit.exists():
                current_input = parse_field(audit_text, "当前写作输入") or ""
                if (
                    "30_文章写作输入" not in current_input
                    or "尚未生成" in current_input
                    or "已作废" in current_input
                ):
                    add("ERROR", "AUDIT_WRITING_STATE", audit, 1, "写作输入已有正文，但文章审核未链接当前写作输入或仍标记尚未生成/已作废")
                fidelity_match = re.search(
                    r"(?ms)^##\s+写作输入保真复核\s*$\n(.*?)(?=^##\s+|\Z)",
                    audit_text,
                )
                if not fidelity_match or not re.search(
                    r"(?m)^-\s*结论\s*[：:]\s*通过\s*$",
                    fidelity_match.group(1) if fidelity_match else "",
                ):
                    add("ERROR", "AUDIT_WRITING_FIDELITY", audit, 1, "写作输入已有正文，但缺少结论为通过的写作输入保真复核")

            outline_file = article_dir / "01_文章要求与大纲.md"
            if outline_file.exists():
                outline = extract_outline(text_cache.get(outline_file, read_text(outline_file)))
                heading_keys = [normalize_heading(value) for value in extract_headings(writing_text)]
                for item in outline:
                    key = normalize_heading(item)
                    if key and not any(key == heading or key in heading or heading in key for heading in heading_keys):
                        add("ERROR", "WRITING_OUTLINE_MISSING", writing, 1, f"写作输入未按大纲建立对应标题：{item}")

        if status == "30_已完成":
            final_file = article_dir / "40_最终文章与引用率.md"
            if final_file.exists():
                final_text = text_cache.get(final_file, read_text(final_file))
                rate = parse_field(final_text, "正式引用率")
                if not rate:
                    add("ERROR", "FORMAL_RATE", final_file, 1, "已完成文章必须填写正式引用率或“未提供”")
            for file in article_dir.glob("*.md"):
                text = text_cache.get(file, read_text(file))
                if f"{article_id}" in text and "03_文章任务/10_进行中/" in text:
                    add("ERROR", "STALE_ARTICLE_STATE_LINK", file, 1, "已完成文章仍链接进行中路径")

    for file in current_md:
        text = text_cache[file]
        for article_id in completed_ids:
            if article_id in text and "03_文章任务/10_进行中/" in text:
                add("ERROR", "STALE_ARTICLE_STATE_LINK", file, 1, f"已完成文章{article_id}仍链接进行中路径")

    return sorted(issues, key=lambda item: (item.severity != "ERROR", item.file, item.line, item.code))


def create_self_test_project(root: Path) -> None:
    for name in REQUIRED_TOP_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    for path in (
        "02_正式知识/01_正式知识目录",
        "02_正式知识/50_行业知识与洞察/10_企业提供",
        "02_正式知识/50_行业知识与洞察/20_Codex外部调研",
        "03_文章任务/01_文章总览",
        "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章",
        "04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿",
        "05_数据与审核/30_异常与待决定/10_企业知识异常待处理",
    ):
        (root / path).mkdir(parents=True, exist_ok=True)

    article = root / "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章"
    (article / "01_文章要求与大纲.md").write_text("# 文章要求与大纲\n\n## 大纲\n\n1. 测试主题\n", encoding="utf-8")
    for name in ARTICLE_FILES[1:4]:
        (article / name).write_text(f"# {name[:-3]}\n", encoding="utf-8")
    (article / "20_文章前知识审核.md").write_text(
        "# 文章前知识审核\n\n- 当前写作输入：[当前写作输入](30_文章写作输入.md)\n\n## 写作输入保真复核\n\n- 复核对象：[当前写作输入](30_文章写作输入.md)\n- 采用范围与未迁入理由：已逐块核对\n- 完整段落及限定条件：通过\n- 表格、公式、数字、单位和脚注：不适用\n- 多来源分块与来源定位：通过\n- 摘要、知识点卡或AI综合正文检查：通过\n- 结论：通过\n",
        encoding="utf-8",
    )
    (article / "30_文章写作输入.md").write_text(
        "# 文章写作输入\n\n## 按大纲排列的本篇可用正文\n\n### 测试主题\n\n#### 来源块：TEST-KB-001｜测试正文\n\n- 原始来源：测试清理稿\n- 内容类型：来源原文\n- 采用范围：选定完整段落\n- 未迁入内容及理由：无\n\n##### 目标语言完整正文（非摘要）\n\n可直接使用的完整测试正文。\n\n来源：[测试清理稿](../../../../04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md)；位置：PDF p.1\n",
        encoding="utf-8",
    )
    (article / "40_最终文章与引用率.md").write_text("# 最终文章与引用率\n\n- 正式引用率：未提供\n", encoding="utf-8")

    scope_link = "../../../03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/15_提取范围与处理样本确认.md"
    clean = root / "04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md"
    clean.write_text(
        "# 测试｜清理与字段统一稿\n\n- 资料ID：TEST-SRC-001\n- 对应原文件：test.pdf\n- 对应运营Markdown：test.md\n- 已确认范围：PDF p.1\n- 范围确认：[确认](" + scope_link + ")\n- 核验状态：已核验\n- 原始表格数（确认范围内）：0\n- 当前保留表格数：0\n- 原始公式数（确认范围内）：0\n- 当前保留公式数：0\n- 结构排除说明：不适用\n\n## 位置与正文结构定位\n\nPDF p.1\n\n## 清理后的正文\n\n测试正文。\n\n## 差异与补核记录\n\n确认范围内未发现需要补核的结构或文字差异。\n\n## 未处理或明确排除范围\n\n- 无\n\n## 来源与回溯\n\n- 原文件：test.pdf\n",
        encoding="utf-8",
    )

    formal = root / "02_正式知识/50_行业知识与洞察/10_企业提供/测试主题.md"
    formal.write_text(
        "---\nknowledge_id: KB-TEST-001\nsource_type: 企业提供\n---\n\n# 测试主题\n\n## 已处理内容\n\n测试知识。\n\n## 使用限制\n\n无。\n\n## 来源\n\n- [测试清理稿](../../../04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md)；PDF p.1\n",
        encoding="utf-8",
    )

    customer_request = root / CUSTOMER_REQUEST_RELATIVE
    customer_request.write_text(
        "# 待客户补充事项\n\n- 项目ID：TEST\n- 最近检查日期：2026-08-06\n\n## 当前事项\n\n| 问题ID | 事实主题 | 希望客户提供 | 关联文章与大纲位置 | 当前安全处理 | 当前影响 | 内部接收人/对客沟通人 | 当前状态 | 计划或发送日期 | 回复或证据位置 | 返回节点 | 最近更新 |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n\n## 事项详情\n",
        encoding="utf-8",
    )


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="validate-v03-") as temp:
        root = Path(temp) / "TEST-知识库"
        create_self_test_project(root)
        issues = validate_project(root)
        if issues:
            print("SELF-TEST FAILED: valid fixture produced issues")
            for issue in issues:
                print(asdict(issue))
            return 1
        formal = root / "02_正式知识/50_行业知识与洞察/10_企业提供/测试主题.md"
        formal.write_text(read_text(formal) + "\n$srcLink\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "PLACEHOLDER" for issue in issues):
            print("SELF-TEST FAILED: placeholder was not detected")
            return 1
        formal.write_text(read_text(formal).replace("\n$srcLink\n", "\n"), encoding="utf-8")
        writing = root / "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/30_文章写作输入.md"
        valid_writing = read_text(writing)
        writing.write_text(
            valid_writing.replace("##### 目标语言完整正文（非摘要）", "##### 目标语言可用内容"),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "WRITING_SUMMARY_TEMPLATE" for issue in issues):
            print("SELF-TEST FAILED: legacy summary-style writing input was not detected")
            return 1
        writing.write_text(valid_writing, encoding="utf-8")
        audit = root / "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/20_文章前知识审核.md"
        valid_audit = read_text(audit)
        audit.write_text(
            valid_audit.replace(
                "- 当前写作输入：[当前写作输入](30_文章写作输入.md)",
                "- 当前写作输入：尚未生成",
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "AUDIT_WRITING_STATE" for issue in issues):
            print("SELF-TEST FAILED: stale writing input state was not detected")
            return 1
        audit.write_text(valid_audit.replace("- 结论：通过", "- 结论：未执行"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "AUDIT_WRITING_FIDELITY" for issue in issues):
            print("SELF-TEST FAILED: missing writing input fidelity review was not detected")
            return 1
        audit.write_text(valid_audit, encoding="utf-8")
        customer_request = root / CUSTOMER_REQUEST_RELATIVE
        customer_request.write_text(
            read_text(customer_request).replace(
                "\n\n## 事项详情",
                "\n| TEST-CUS-001 | 测试事实 | 客户答复 | TEST-ART-001/测试主题 | 明确排除 | 不阻塞 | 运营/待定 | 错误状态 |  |  | 节点5 | 2026-08-06 |\n\n## 事项详情",
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "CUSTOMER_REQUEST_STATUS" for issue in issues):
            print("SELF-TEST FAILED: invalid customer request status was not detected")
            return 1
        customer_request.write_text(
            read_text(customer_request).replace("错误状态", "待发送"),
            encoding="utf-8",
        )
        audit.write_text(read_text(audit) + "\n以后问客户。\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "AUDIT_CUSTOMER_REQUEST_LINK" for issue in issues):
            print("SELF-TEST FAILED: missing customer request backlink was not detected")
            return 1
        customer_request.unlink()
        issues = validate_project(root)
        if not any(issue.code == "MISSING_CUSTOMER_REQUEST_LEDGER" for issue in issues):
            print("SELF-TEST FAILED: missing customer request ledger was not detected")
            return 1
    print("SELF-TEST PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检查manage-article-knowledge v0.3 Obsidian项目")
    parser.add_argument("--project", type=Path, help="Obsidian项目根目录")
    parser.add_argument("--json", action="store_true", help="输出JSON")
    parser.add_argument("--self-test", action="store_true", help="运行内置正反例测试")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if not args.project:
        parser.error("--project is required unless --self-test is used")

    root = args.project.resolve()
    issues = validate_project(root)
    errors = sum(issue.severity == "ERROR" for issue in issues)
    warnings = sum(issue.severity == "WARNING" for issue in issues)

    if args.json:
        print(json.dumps({"project": str(root), "errors": errors, "warnings": warnings, "issues": [asdict(issue) for issue in issues]}, ensure_ascii=False, indent=2))
    else:
        for issue in issues:
            location = f"{issue.file}:{issue.line}" if issue.line else issue.file
            print(f"{issue.severity} [{issue.code}] {location} - {issue.message}")
        print(f"SUMMARY errors={errors} warnings={warnings} files={len(list(root.rglob('*.md')))}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
