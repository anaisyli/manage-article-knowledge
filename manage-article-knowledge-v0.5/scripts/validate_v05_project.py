#!/usr/bin/env python3
"""Validate the lightweight control structure of a v0.5 project."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import tempfile
from pathlib import Path


REQUIRED_FILES = (
    "01_工作台/10_项目基础信息.md",
    "01_工作台/20_当前待办.md",
    "01_工作台/30_版本与变更入口.md",
    "02_源资料/源资料与可检索性台账.md",
    "02_源资料/源资料搜索索引说明.md",
    "02_源资料/source-index.sqlite",
    "05_数据与审核/01_数据说明.md",
    "05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md",
    "05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md",
    "05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md",
    "05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md",
    "05_数据与审核/30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md",
)
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
CLAIM_REQUIRED_FIELDS = (
    "Claim ID", "Claim", "适用范围", "来源类型", "来源链接", "精确位置",
    "日期或版本", "使用边界", "状态",
)
CLAIM_STATUSES = {"可用", "受限使用", "待知识库专员确认", "已失效"}
UTF8_BOM = b"\xef\xbb\xbf"
PROJECT_ROOT_PATTERN = re.compile(r"^[^\\/:*?\"<>|]+_[^\\/:*?\"<>|]+知识库_v0\.5$")
REQUIRED_LAYOUT_DIRECTORIES = (
    "01_工作台",
    "02_源资料",
    "02_源资料/20_MinerU按需提取",
    "03_正式知识",
    "03_正式知识/10_客户知识",
    "03_正式知识/20_外部公共知识",
    "04_文章任务",
    "04_文章任务/10_进行中",
    "04_文章任务/20_等待终稿",
    "04_文章任务/30_等待Faithfulness",
    "04_文章任务/40_已完成",
    "04_文章任务/90_归档",
    "04_文章任务/90_归档/10_文章历史版本",
    "04_文章任务/90_归档/20_已取消任务",
    "05_数据与审核",
    "05_数据与审核/10_Faithfulness",
    "05_数据与审核/20_知识库覆盖与缺口",
    "05_数据与审核/30_异常与待决定/10_待客户补充",
    "05_数据与审核/30_异常与待决定/20_源资料处理",
    "05_数据与审核/30_异常与待决定/30_源文与事实异常",
    "05_数据与审核/30_异常与待决定/40_Skill运行反馈",
    "05_数据与审核/40_月度与交接",
    "05_数据与审核/50_运行记录",
    "05_数据与审核/60_版本归档/10_正式知识历史",
    "05_数据与审核/60_版本归档/20_控制文件迁移历史",
    "05_数据与审核/60_版本归档/30_机器文件迁移快照",
    "05_数据与审核/60_版本归档/40_源资料版本记录",
)
CANONICAL_ARTICLE_FILES = {
    "10_文章知识需求.md", "15_检索与知识准备记录.md", "20_文章前知识审核.md",
    "30_本篇知识库资料.md", "35_写作素材来源索引.md",
    "40_最终文章.md", "50_文章知识使用与Faithfulness记录.md",
    "25_文章证据与审核包.md", "50_Faithfulness结果.md",
    "文章前问题与处理单.md",
}
ARTICLE_STATES = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成")
ARTICLE_REQUIRED_BY_STATE = {
    "10_进行中": ("10_文章知识需求.md",),
    "20_等待终稿": (
        "10_文章知识需求.md", "15_检索与知识准备记录.md",
        "20_文章前知识审核.md", "30_本篇知识库资料.md",
    ),
    "30_等待Faithfulness": (
        "10_文章知识需求.md", "15_检索与知识准备记录.md",
        "20_文章前知识审核.md", "30_本篇知识库资料.md", "40_最终文章.md",
    ),
    "40_已完成": (
        "10_文章知识需求.md", "15_检索与知识准备记录.md",
        "20_文章前知识审核.md", "30_本篇知识库资料.md", "40_最终文章.md",
    ),
}
ARTICLE_ID_FILES = (
    "10_文章知识需求.md", "15_检索与知识准备记录.md", "20_文章前知识审核.md",
    "30_本篇知识库资料.md", "35_写作素材来源索引.md",
    "40_最终文章.md", "50_文章知识使用与Faithfulness记录.md",
    "25_文章证据与审核包.md", "50_Faithfulness结果.md",
    "文章前问题与处理单.md",
)
DELIVERABLE_AUDIT_RESULTS = {"自动通过", "带明确排除通过"}
BLOCKING_AUDIT_RESULTS = {"等待知识库专员处理", "等待内容运营业务决定"}
PROBLEM_SHEET_STATUSES = {"等待人工处理", "已处理，待自动复核", "已关闭"}
LEDGER_RULES = {
    "MAT": {
        "path": "05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md",
        "statuses": {"待知识库专员判断", "知识库专员处理中", "等待材料或工具", "暂不处理", "已处理"},
        "status_column": 6,
        "section": "## 当前事项",
    },
    "CUS": {
        "path": "05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md",
        "statuses": {
            "待判断要不要问", "无需询问", "准备客户话术", "等待发送",
            "等待客户回复", "收到回复，待核实", "已完成",
        },
        "status_column": 4,
        "section": "## 当前事项",
    },
    "ANM": {
        "path": "05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md",
        "statuses": {"待判断", "等待材料", "处理中", "部分解决", "已解决", "已完成处置（原文未修复）"},
        "status_column": 5,
        "section": "## 当前异常",
    },
    "SKFB": {
        "path": "05_数据与审核/30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md",
        "statuses": {
            "自动记录，待维护判断", "人工提出，待维护判断", "已纳入维护", "维护中",
            "已修复，待项目验证", "已关闭", "转为项目问题", "不纳入Skill",
        },
        "status_column": 5,
        "section": "## 当前反馈",
    },
}
HUMAN_LEDGER_FIELDS = {
    "MAT": ("事项名称", "代表文件/资料范围", "资料数量", "通俗问题", "当前文章影响", "下一责任人/动作", "重开条件", "详情入口"),
    "CUS": ("想确认什么", "为什么需要", "回复前怎么处理", "下一责任人", "相关文章/Claim入口"),
    "ANM": ("发生了什么", "为什么有风险", "现在怎么处理", "下一责任人", "证据包入口"),
    "SKFB": ("通俗说明", "提出来源", "复现依据", "维护负责人", "关联项目对象入口"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_field(text: str, field: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(field)}[：:]\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def writing_material_evidence_scope(lines: list[str]) -> tuple[list[bool], int]:
    """Return lines inside explicit evidence bodies in sections 1-3."""
    selected = [False] * len(lines)
    evidence_sections = {
        "一、可直接用于正文的事实",
        "二、可直接采用的英文表达",
        "三、可使用的数据表",
    }
    in_evidence_section = False
    evidence_level: int | None = None
    found = 0
    for index, line in enumerate(lines):
        match = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            if level == 2:
                in_evidence_section = title in evidence_sections
                evidence_level = None
            elif evidence_level is not None and level <= evidence_level:
                evidence_level = None
            if in_evidence_section and re.match(r"^证据正文(?:（供Faithfulness核验）)?$", title):
                evidence_level = level
                found += 1
            continue
        if evidence_level is not None:
            selected[index] = True
    return selected, found


def markdown_table(path: Path, section: str) -> tuple[list[str], list[list[str]]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    try:
        start = lines.index(section) + 1
    except ValueError:
        return [], []
    table_lines: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.strip().startswith("|"):
            table_lines.append(line)
        elif table_lines:
            break
    parsed: list[list[str]] = []
    for line in table_lines:
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        parsed.append(cells)
    return (parsed[0], parsed[1:]) if parsed else ([], [])


def is_table_separator(line: str) -> bool:
    if not line.strip().startswith("|"):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def table_continuity_errors(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    errors: list[str] = []
    for index in range(len(lines) - 1):
        if not lines[index].strip().startswith("|") or not is_table_separator(lines[index + 1]):
            continue
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            cursor += 1
        if cursor >= len(lines) or lines[cursor].strip():
            continue
        next_nonblank = cursor + 1
        while next_nonblank < len(lines) and not lines[next_nonblank].strip():
            next_nonblank += 1
        if next_nonblank >= len(lines) or not lines[next_nonblank].strip().startswith("|"):
            continue
        # A new header+separator is a separate table; a pipe row without a new
        # header means the current table was split by an illegal blank line.
        if next_nonblank + 1 < len(lines) and is_table_separator(lines[next_nonblank + 1]):
            continue
        errors.append(f"Markdown表格数据行之间存在空行：{path}:{cursor + 1}")
    return errors


RETRIEVAL_LAYERS = (
    "已有正式Claim", "客户源资料索引", "客户官网", "已有外部公共Claim", "新外部调研",
)
RELATED_WEBSITE_LAYER = "客户关联网站"
RETRIEVAL_HEADER = ("检索层", "当前状态", "结果或未查原因", "下一步")
SOURCE_HIT_HEADER = ("知识问题", "命中Claim/资料名称与入口", "相关理由", "处理结果")
RELATED_WEBSITE_SECTION = "## 内容运营提交的其他企业相关网站"
RELATED_WEBSITE_HEADER = (
    "网站ID", "网站名称与用途", "网站类型", "具体URL", "企业关系与依据", "使用范围",
    "关联文章", "可访问状态", "最近检查", "覆盖模块/内容", "下次复核条件",
)
RELATED_WEBSITE_TYPES = {
    "子品牌官网", "集团或母公司站", "区域站", "平台店铺或企业主页", "其他企业相关站点",
}
RELATED_WEBSITE_STATUSES = {
    "可访问", "部分可访问", "暂时无法访问", "关系待确认", "已停用",
}
MONTHLY_TEMPLATE_VERSION = "v0.5-20260821"
MONTHLY_SOURCE_HEADER = ("来源类型", "已登记对象", "当前可用/可检索状态", "主要限制", "当前入口")
MONTHLY_SOURCE_TYPES = (
    "客户提供文件", "客户主官网", "内容运营提交的其他企业相关网站",
)
MONTHLY_COVERAGE_HEADER = (
    "标准模块", "覆盖状态", "客户提供文件", "客户主官网",
    "内容运营提交的其他企业相关网站", "已形成的正式知识", "当前覆盖内容", "尚缺或尚未处理",
)
MONTHLY_MODULES = ("公司概述", "产品介绍", "解决方案", "合作案例", "行业知识与洞察", "FAQ", "其他")
MONTHLY_COVERAGE_STATUSES = {
    "已有来源且已有正式知识", "已有来源，尚未形成正式知识", "来源处理中",
    "尚未发现相关来源", "来源归类待确认",
}


def table_headers(text: str) -> list[tuple[str, ...]]:
    lines = text.splitlines()
    headers: list[tuple[str, ...]] = []
    for index in range(len(lines) - 1):
        if not lines[index].strip().startswith("|") or not is_table_separator(lines[index + 1]):
            continue
        headers.append(tuple(cell.strip() for cell in lines[index].strip().strip("|").split("|")))
    return headers


def validate_retrieval_records(root: Path, errors: list[str]) -> None:
    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return
    project_info = root / "01_工作台/10_项目基础信息.md"
    requires_related_website_layer = (
        project_info.is_file()
        and RELATED_WEBSITE_SECTION in project_info.read_text(encoding="utf-8-sig")
    )
    for path in task_root.rglob("15_检索与知识准备记录.md"):
        if "90_归档" in path.parts:
            continue
        text = path.read_text(encoding="utf-8-sig")
        headers = table_headers(text)
        if headers.count(SOURCE_HIT_HEADER) != 1:
            errors.append(f"文章检索记录必须只有一个标准四列表：{path}")
        if any(header == ("知识问题", "命中Claim或资料", "相关理由", "处理结果") for header in headers):
            errors.append(f"文章检索记录仍使用旧列名“命中Claim或资料”：{path}")
        if re.search(r"^##\s+官网产品页命中", text, re.MULTILINE):
            errors.append(f"文章检索记录不应另建官网产品页命中表：{path}")
        header, rows = markdown_table(path, "## 固定检索层状态")
        state = next((part for part in path.parts if part in {
            "10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"
        }), "")
        if tuple(header) != RETRIEVAL_HEADER:
            errors.append(f"文章检索记录缺少固定检索层状态表：{path}")
            continue
        by_layer = {row[0].strip(): row for row in rows if row and row[0].strip()}
        required_layers = RETRIEVAL_LAYERS + ((RELATED_WEBSITE_LAYER,) if requires_related_website_layer else ())
        for layer in required_layers:
            row = by_layer.get(layer)
            if not row or len(row) < 3:
                errors.append(f"文章检索记录缺少固定检索层：{layer}（{path}）")
                continue
            status = row[1].strip()
            reason = row[2].strip()
            if not status or status in {"待填写", "待检索", "待补充"} or " / " in status:
                errors.append(f"文章检索层状态未确定：{layer} = {status or '空'}（{path}）")
            if not reason or reason in {"待填写", "待补充"}:
                errors.append(f"文章检索层缺少结果或未查原因：{layer}（{path}）")
            if state in {"20_等待终稿", "30_等待Faithfulness", "40_已完成"} and status in {"待检索", "未开始", "处理中"}:
                errors.append(f"文章检索阶段已完成但固定层仍未检索：{layer}（{path}）")


def validate_source_references(root: Path, errors: list[str]) -> None:
    db = root / "02_源资料/source-index.sqlite"
    if not db.is_file():
        return
    try:
        connection = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        source_ids = {row[0] for row in connection.execute("SELECT source_id FROM sources")}
        connection.close()
    except sqlite3.Error as exc:
        errors.append(f"无法读取来源ID集合：{exc}")
        return
    marker = re.compile(r"\bSRC-[A-Za-z0-9]+\b")
    for path in root.rglob("*.md"):
        if any(part in {".obsidian", ".git", "90_归档", "40_Skill运行反馈"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8-sig")
        for line_number, line in enumerate(text.splitlines(), 1):
            for source_id in marker.findall(line):
                if source_id not in source_ids:
                    errors.append(f"来源ID不存在或被截断：{source_id}（{path}:{line_number}）")


def load_source_mat_map(root: Path) -> dict[str, str]:
    path = root / "02_源资料/源资料与可检索性台账.md"
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_index = next(
        (
            index for index, line in enumerate(lines)
            if line.strip().startswith("|") and "资料ID" in line and "MAT" in line
        ),
        None,
    )
    if header_index is None:
        return {}
    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    indexes = {name: index for index, name in enumerate(header)}
    source_index = indexes.get("资料ID")
    mat_index = indexes.get("MAT")
    if source_index is None or mat_index is None:
        return {}
    mapping: dict[str, str] = {}
    for line in lines[header_index + 2:]:
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) <= max(source_index, mat_index):
            continue
        source_id = cells[source_index]
        mat_id = cells[mat_index]
        if source_id and mat_id:
            mapping[source_id] = mat_id
    return mapping


def validate_mat_dependencies(root: Path, errors: list[str]) -> None:
    source_mat = load_source_mat_map(root)
    if not source_mat:
        return
    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return
    source_marker = re.compile(r"\bSRC-[A-Za-z0-9]+\b")
    for article_dir in task_root.iterdir():
        if not article_dir.is_dir() or article_dir.name == "90_归档":
            continue
        for task_dir in article_dir.iterdir():
            if not task_dir.is_dir():
                continue
            state = next((part for part in task_dir.parts if part in {
                "10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"
            }), "")
            if state not in {"20_等待终稿", "30_等待Faithfulness", "40_已完成"}:
                continue
            relevant_paths = [
                task_dir / "15_检索与知识准备记录.md",
                task_dir / "20_文章前知识审核.md",
                task_dir / "35_写作素材来源索引.md",
                task_dir / "30_本篇知识库资料.md",
            ]
            combined = "\n".join(
                path.read_text(encoding="utf-8-sig") for path in relevant_paths if path.is_file()
            )
            referenced = set(source_marker.findall(combined))
            for source_id in sorted(referenced):
                mat_id = source_mat.get(source_id)
                if not mat_id:
                    continue
                if mat_id not in combined:
                    errors.append(
                        f"文章命中MAT资料但审核记录未登记MAT依赖：{source_id} → {mat_id}（{task_dir}）"
                    )


def validate_feedback_details(root: Path, errors: list[str]) -> None:
    path = root / str(LEDGER_RULES["SKFB"]["path"])
    if not path.is_file():
        return
    header, rows = markdown_table(path, str(LEDGER_RULES["SKFB"]["section"]))
    if not header:
        return
    current_ids = {
        row[0].strip()
        for row in rows
        if row and row[0].strip() and not row[0].strip().startswith("[")
    }
    text = path.read_text(encoding="utf-8-sig")
    detail_ids = set(re.findall(r"^###\s+([A-Za-z0-9_.-]+-SKFB-\d+)｜", text, re.MULTILINE))
    for item_id in sorted(current_ids - detail_ids):
        errors.append(f"SKFB主表事项缺少对应详情区块：{item_id}（{path}）")
    try:
        stage_index = header.index("当前阶段")
    except ValueError:
        return
    for row in rows:
        if not row or len(row) <= stage_index:
            continue
        item_id = row[0].strip()
        if not item_id or item_id.startswith("[") or item_id not in detail_ids:
            continue
        block = detail_block(text, item_id)
        match = re.search(r"(?m)^- 当前阶段[：:]\s*(.+?)\s*$", block)
        if not match:
            errors.append(f"SKFB详情缺少当前阶段：{item_id}（{path}）")
        elif match.group(1).strip() != row[stage_index].strip():
            errors.append(
                f"SKFB主表与详情当前阶段不一致：{item_id}，主表={row[stage_index].strip()}，详情={match.group(1).strip()}（{path}）"
            )


def looks_id_only(value: str) -> bool:
    tokens = [item for item in re.split(r"[\s,，、;/]+", value.strip()) if item]
    if not tokens:
        return False
    id_pattern = re.compile(r"(?:[A-Z][A-Z0-9]*-[A-Za-z0-9_.-]+|[0-9a-fA-F]{12,64})")
    return all(id_pattern.fullmatch(token) for token in tokens)


def detail_block(text: str, item_id: str) -> str:
    match = re.search(
        rf"^###\s+[^\n]*{re.escape(item_id)}[^\n]*｜[^\n\[]+\s*$([\s\S]*?)(?=^###\s+|\Z)",
        text,
        re.MULTILINE,
    )
    return match.group(1) if match else ""


def load_metrics(path: Path, errors: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != METRIC_FIELDS:
            errors.append(f"Faithfulness明细CSV字段不符合v0.5：{path}")
            return []
        return list(reader)


def check_csv_schema(path: Path, expected: tuple[str, ...], errors: list[str]) -> None:
    if not path.is_file():
        return
    if not path.read_bytes().startswith(UTF8_BOM):
        errors.append(f"受管CSV必须使用UTF-8 with BOM：{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = tuple(next(reader, []))
    if header != expected:
        errors.append(f"CSV字段不符合v0.5：{path}")


def validate_claims(root: Path, errors: list[str], warnings: list[str]) -> None:
    claim_ids: dict[str, Path] = {}
    marker = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
    for path in (root / "03_正式知识").rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        matches = list(marker.finditer(text))
        if not matches:
            continue
        for index, match in enumerate(matches):
            claim_id = match.group(1)
            if claim_id in claim_ids:
                errors.append(f"正式Claim ID重复：{claim_id}，{claim_ids[claim_id]} 与 {path}")
            claim_ids[claim_id] = path
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.start():end]
            for field in CLAIM_REQUIRED_FIELDS:
                if not parse_field(block, field):
                    errors.append(f"Claim {claim_id} 缺少字段：{field}（{path}）")
            status = parse_field(block, "状态")
            if status and status not in CLAIM_STATUSES:
                errors.append(f"Claim {claim_id} 状态无效：{status}")
            if "### 最小原文证据" not in block or not re.search(r"^\s*>\s*\S", block, re.MULTILINE):
                errors.append(f"Claim {claim_id} 未发现引用块形式的最小原文证据：{path}")


def validate_ledgers(root: Path, errors: list[str]) -> None:
    for prefix, rule in LEDGER_RULES.items():
        path = root / str(rule["path"])
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        seen: set[str] = set()
        header, rows = markdown_table(path, str(rule["section"]))
        if not header:
            errors.append(f"{prefix}缺少当前事项主表：{path}")
            continue
        missing_human = [field for field in HUMAN_LEDGER_FIELDS[prefix] if field not in header]
        if missing_human:
            errors.append(f"{prefix}人工可读表头缺少字段 {missing_human}：{path}")
        indexes = {name: index for index, name in enumerate(header)}
        group_keys: dict[str, str] = {}
        for cells in rows:
            if not cells or not cells[0]:
                continue
            item_id = cells[0]
            if item_id.startswith("["):
                continue
            if not item_id.startswith(prefix + "-") and not re.match(rf".+-{prefix}-\d+$", item_id):
                errors.append(f"{prefix}编号格式异常：{item_id}（{path}）")
            if item_id in seen:
                errors.append(f"{prefix}编号重复：{item_id}（{path}）")
            seen.add(item_id)
            for field in HUMAN_LEDGER_FIELDS[prefix]:
                index = indexes.get(field)
                if index is None:
                    continue
                value = cells[index].strip() if index < len(cells) else ""
                if not value or value in {"-", "—", "待补充", "待填写"}:
                    errors.append(f"{prefix}事项 {item_id} 缺少人工可读字段：{field}")
            status_column = int(rule["status_column"])
            if len(cells) <= status_column:
                errors.append(f"{prefix}行字段不足：{item_id}（{path}）")
                continue
            status = cells[status_column]
            if status not in rule["statuses"]:
                errors.append(f"{prefix}状态无效：{item_id} = {status}")
            if prefix != "MAT":
                continue
            representative_index = indexes.get("代表文件/资料范围", -1)
            representative = cells[representative_index].strip() if 0 <= representative_index < len(cells) else ""
            if representative and looks_id_only(representative):
                errors.append(f"MAT事项 {item_id} 的代表文件/资料范围只有ID，必须写文件名、资料范围或稳定路径")
            count_index = indexes.get("资料数量", -1)
            count = cells[count_index].strip() if 0 <= count_index < len(cells) else ""
            if not re.fullmatch(r"[1-9]\d*", count):
                errors.append(f"MAT事项 {item_id} 的资料数量必须是正整数：{count or '空'}")
            detail_index = indexes.get("详情入口", -1)
            detail_link = cells[detail_index].strip() if 0 <= detail_index < len(cells) else ""
            if "[[" not in detail_link and "](" not in detail_link:
                errors.append(f"MAT事项 {item_id} 缺少可点击详情入口")
            block = detail_block(text, item_id)
            if not block:
                errors.append(f"MAT事项 {item_id} 缺少同一事项的人话详情标题")
            else:
                for label in (
                    "归组范围", "代表文件/资料范围", "资料数量", "为什么合并为一项",
                    "源资料总表", "稳定源资料根路径与相对路径", "下一责任人/动作", "重开条件",
                ):
                    if not parse_field(block, label):
                        errors.append(f"MAT事项 {item_id} 详情缺少字段：{label}")
            name_index = indexes.get("事项名称", -1)
            issue_index = indexes.get("通俗问题", -1)
            name = cells[name_index].strip() if 0 <= name_index < len(cells) else ""
            issue = cells[issue_index].strip() if 0 <= issue_index < len(cells) else ""
            group_key = re.sub(r"\s+", "", f"{name}|{issue}").casefold()
            if group_key in group_keys:
                errors.append(f"MAT疑似把同一类问题重复拆项：{group_keys[group_key]} 与 {item_id}")
            else:
                group_keys[group_key] = item_id


def validate_index(root: Path, errors: list[str], warnings: list[str]) -> None:
    db = root / "02_源资料/source-index.sqlite"
    if not db.is_file():
        return
    try:
        connection = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
        }
        required = {"metadata", "sources", "chunks", "chunks_fts", "relationships"}
        missing = required - tables
        if missing:
            errors.append(f"机器索引缺少表：{', '.join(sorted(missing))}")
        source_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sources)")
        }
        expected_columns = {
            "media_duration", "possible_subject", "transcript_status",
            "office_media_count", "office_embedded_count",
        }
        missing_columns = expected_columns - source_columns
        if missing_columns:
            errors.append(f"机器索引sources缺少v0.5字段：{', '.join(sorted(missing_columns))}")
        source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        if source_count == 0:
            warnings.append("机器索引中没有登记任何源文件")
        connection.close()
    except sqlite3.Error as exc:
        errors.append(f"机器索引无法读取：{exc}")


def validate_source_exclusions(root: Path, errors: list[str], warnings: list[str]) -> None:
    """Verify that explicit body exclusions are durable and contain no chunks."""
    path = root / "02_源资料/source-index-exclusions.json"
    ledger = root / "02_源资料/源资料与可检索性台账.md"
    if not path.is_file():
        if ledger.is_file() and re.search(r"正文(?:已)?排除|不得提取|正文不索引", ledger.read_text(encoding="utf-8-sig")):
            errors.append(f"来源台账声明了正文排除，但缺少持久排除清单：{path}")
        else:
            warnings.append(f"缺少项目级正文排除清单：{path}")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"正文排除清单无法读取：{path}：{exc}")
        return
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        errors.append(f"正文排除清单schema_version必须为1：{path}")
        return
    entries = payload.get("entries")
    if not isinstance(entries, list):
        errors.append(f"正文排除清单entries必须是数组：{path}")
        return
    db = root / "02_源资料/source-index.sqlite"
    if not db.is_file():
        return
    try:
        connection = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        source_rows = {
            row[0]: {"relative_path": row[1], "sha256": row[2], "searchability": row[3]}
            for row in connection.execute(
                "SELECT source_id, relative_path, sha256, searchability FROM sources"
            )
        }
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"正文排除清单存在非对象条目：{path}")
                continue
            source_id = str(entry.get("source_id", "")).strip()
            relative_path = str(entry.get("relative_path", "")).replace("\\", "/").strip()
            checksum = str(entry.get("sha256", "")).strip().lower()
            if entry.get("exclude_body") is not True:
                errors.append(f"正文排除条目未设置exclude_body=true：{source_id or '未填写'}（{path}）")
                continue
            if not source_id or not relative_path or not re.fullmatch(r"[0-9a-f]{64}", checksum) or not str(entry.get("reason", "")).strip():
                errors.append(f"正文排除条目字段不完整：{source_id or '未填写'}（{path}）")
                continue
            row = source_rows.get(source_id)
            if not row:
                errors.append(f"正文排除条目引用不存在的资料ID：{source_id}（{path}）")
                continue
            if row["relative_path"].casefold() != relative_path.casefold() or row["sha256"].lower() != checksum:
                errors.append(f"正文排除条目与当前资料路径或SHA-256不一致：{source_id}（{path}）")
                continue
            chunk_count = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE source_id=?", (source_id,)
            ).fetchone()[0]
            fts_count = connection.execute(
                "SELECT COUNT(*) FROM chunks_fts WHERE source_id=?", (source_id,)
            ).fetchone()[0]
            if chunk_count or fts_count:
                errors.append(f"明确排除的资料仍有正文索引：{source_id} chunks={chunk_count}, fts={fts_count}（{db}）")
            if row["searchability"] != "仅文件信息可搜索":
                errors.append(f"明确排除的资料可检索状态不正确：{source_id} = {row['searchability']}（{db}）")
        connection.close()
    except sqlite3.Error as exc:
        errors.append(f"无法核对正文排除清单与SQLite：{exc}")


def validate_version_entry(root: Path, errors: list[str], warnings: list[str]) -> None:
    path = root / "01_工作台/30_版本与变更入口.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8-sig")
    if "manage-article-knowledge v0.5" not in text:
        errors.append(f"版本入口未声明manage-article-knowledge v0.5：{path}")
    if "Skill文件SHA-256：待计算" in text:
        warnings.append(f"版本入口尚未写入Skill SHA-256：{path}")
    if "[[20_当前待办.md]]" not in text:
        errors.append(f"版本入口未链接当前待办：{path}")


def validate_project_profile(root: Path, errors: list[str], warnings: list[str]) -> None:
    """Surface missing website profile data without changing existing projects."""
    path = root / "01_工作台/10_项目基础信息.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8-sig")
    website = parse_field(text, "官网")
    if website and website not in {"待补充", "无", "不适用"}:
        if "## 官网初步画像" not in text:
            warnings.append(f"官网已填写但项目基础信息缺少官网初步画像：{path}")
        else:
            profile_status = parse_field(text, "画像状态")
            if profile_status in {"待执行", "官网状态：待检查", "官网不可访问，待重试"}:
                warnings.append(f"官网画像尚未完成或需要重试：{path}")
            for field in ("项目英文名称", "行业或业务类别", "主要业务与产品", "市场、服务区域与网站语言"):
                if f"| {field} |" not in text:
                    warnings.append(f"官网画像缺少回写字段 {field}：{path}")

    if RELATED_WEBSITE_SECTION not in text:
        warnings.append(f"项目基础信息缺少其他企业相关网站登记表（旧项目不自动改写）：{path}")
        return
    header, rows = markdown_table(path, RELATED_WEBSITE_SECTION)
    if tuple(header) != RELATED_WEBSITE_HEADER:
        errors.append(f"其他企业相关网站未使用固定登记表头：{path}")
        return
    seen_ids: set[str] = set()
    for row in rows:
        if len(row) != len(RELATED_WEBSITE_HEADER):
            errors.append(f"其他企业相关网站登记行列数不正确：{path}")
            continue
        item = dict(zip(RELATED_WEBSITE_HEADER, row))
        website_id = item["网站ID"].strip()
        if website_id == "无":
            if item["可访问状态"].strip() != "未登记":
                errors.append(f"暂无网站占位行状态必须是“未登记”：{path}")
            continue
        if not re.fullmatch(r"WEB-[A-Za-z0-9]+-\d{3}", website_id):
            errors.append(f"企业相关网站ID不符合 WEB-[项目短码]-[三位流水]：{website_id}")
        if website_id in seen_ids:
            errors.append(f"企业相关网站ID重复：{website_id}")
        seen_ids.add(website_id)
        for field, value in item.items():
            if not value.strip():
                errors.append(f"企业相关网站 {website_id} 缺少字段：{field}")
        if item["网站类型"].strip() not in RELATED_WEBSITE_TYPES:
            errors.append(f"企业相关网站类型无效：{website_id}")
        if not re.match(r"^https?://", item["具体URL"].strip(), re.IGNORECASE):
            errors.append(f"企业相关网站缺少可用的具体URL：{website_id}")
        status = item["可访问状态"].strip()
        if status not in RELATED_WEBSITE_STATUSES:
            errors.append(f"企业相关网站状态无效：{website_id} = {status}")
        relationship = item["企业关系与依据"].strip()
        if status == "关系待确认" and "待确认" not in relationship:
            errors.append(f"关系待确认站点未在关系依据中说明：{website_id}")
        if status == "暂时无法访问" and item["下次复核条件"].strip() in {"", "无", "不适用"}:
            errors.append(f"暂时无法访问站点缺少重试条件：{website_id}")


def validate_layout(root: Path, errors: list[str], warnings: list[str]) -> None:
    """Report naming and layout drift without renaming an existing project."""
    if not PROJECT_ROOT_PATTERN.fullmatch(root.name):
        warnings.append(f"项目根目录不符合统一命名 [项目ID]_[企业中文名称]知识库_v0.5：{root}")
    for relative in REQUIRED_LAYOUT_DIRECTORIES:
        if not (root / relative).is_dir():
            warnings.append(f"缺少标准项目目录：{root / relative}")

    coverage = root / "05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md"
    if coverage.is_file():
        coverage_text = coverage.read_text(encoding="utf-8-sig")
        for heading in ("# 知识库覆盖与缺口", "## 来源可检索性", "## 知识库覆盖与缺口"):
            if heading not in coverage_text:
                warnings.append(f"知识库覆盖与缺口页面缺少固定小节 {heading}：{coverage}")
        required_header = ["知识分区/标准模块", "已有正式知识与可安全使用范围", "已覆盖来源", "尚未定向处理材料", "明确缺少材料或事实", "当前文章影响"]
        actual_header, _ = markdown_table(coverage, "## 知识库覆盖与缺口")
        if actual_header != required_header:
            warnings.append(f"知识库覆盖与缺口页面未使用固定覆盖表头：{coverage}")
        if "不代表完备度评分" not in coverage_text or "不替代Formal Claim" not in coverage_text:
            warnings.append(f"知识库覆盖与缺口页面缺少职责边界说明：{coverage}")
        nested_industry = root / "03_正式知识/10_客户知识/50_行业知识与洞察"
        nested_files = [item for item in nested_industry.rglob("*.md") if not item.name.startswith("00_")] if nested_industry.is_dir() else []
        industry_row = next((line for line in coverage_text.splitlines() if line.startswith("| 客户知识／行业知识与洞察")), "")
        if nested_files and (not industry_row or "暂无正式知识" in industry_row):
            errors.append(f"知识库覆盖视图漏记企业提供行业知识子目录中的正式知识：{coverage}")

    info = root / "01_工作台/10_项目基础信息.md"
    if info.is_file():
        text = info.read_text(encoding="utf-8-sig")
        for heading in ("## 官网初步画像", RELATED_WEBSITE_SECTION, "## 人工接触节点", "## 七个业务模块入口"):
            if heading not in text:
                warnings.append(f"项目基础信息缺少标准小节 {heading}：{info}")
        if "目标市场与语言：" not in text:
            warnings.append(f"项目基础信息应使用统一字段“目标市场与语言”：{info}")

    todo = root / "01_工作台/20_当前待办.md"
    if todo.is_file() and "| 对象ID | 人能看懂的事项 | 当前阶段 | 是否阻塞 | 下一步由谁做 | 直达链接 | 更新/重开条件 | 最近更新 |" not in todo.read_text(encoding="utf-8-sig"):
        warnings.append(f"当前待办未使用标准八列表头：{todo}")

    version = root / "01_工作台/30_版本与变更入口.md"
    if version.is_file():
        text = version.read_text(encoding="utf-8-sig")
        for heading in ("## 项目级变更", "## 相关入口"):
            if heading not in text:
                warnings.append(f"版本入口缺少标准小节 {heading}：{version}")

    for transient in ("source-index.sqlite-wal", "source-index.sqlite-shm"):
        for path in root.rglob(transient):
            warnings.append(f"发现SQLite临时文件，不应纳入项目受管文件：{path}")

    article_root = root / "04_文章任务"
    if article_root.is_dir():
        for state_dir in ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"):
            for task_dir in (article_root / state_dir).iterdir() if (article_root / state_dir).is_dir() else ():
                if not task_dir.is_dir():
                    continue
                for child in task_dir.iterdir():
                    if child.is_file() and child.suffix.lower() == ".md" and child.name not in CANONICAL_ARTICLE_FILES:
                        warnings.append(f"文章任务含非标准文件名：{child}")


def validate_token_usage(root: Path, errors: list[str]) -> None:
    path = root / "05_数据与审核/50_运行记录/token_usage.jsonl"
    if not path.is_file():
        return
    required = {"schema_version", "record_id", "recorded_at", "project_id", "step", "status"}
    statuses = {"success", "partial", "failed", "unknown"}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"token用量JSONL第{line_number}行无效：{exc}")
                continue
            missing = required - item.keys()
            if missing:
                errors.append(f"token用量记录缺少字段 {sorted(missing)}：{path}:{line_number}")
            if item.get("status") not in statuses:
                errors.append(f"token用量状态无效：{item.get('status')}（{path}:{line_number}）")
            effort = item.get("reasoning_effort")
            if effort is not None and effort not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
                errors.append(f"token推理档位无效：{effort}（{path}:{line_number}）")
            for field in ("input_tokens", "output_tokens"):
                value = item.get(field)
                if value is not None and (not isinstance(value, int) or value < 0):
                    errors.append(f"token用量字段无效：{field}（{path}:{line_number}）")


def article_task_dirs(root: Path) -> list[tuple[str, Path]]:
    task_root = root / "04_文章任务"
    result: list[tuple[str, Path]] = []
    for state in ARTICLE_STATES:
        state_root = task_root / state
        if not state_root.is_dir():
            continue
        result.extend((state, path) for path in state_root.iterdir() if path.is_dir())
    return result


def load_todo_blocking(root: Path) -> dict[str, str]:
    path = root / "01_工作台/20_当前待办.md"
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        header = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if "对象ID" not in header or "是否阻塞" not in header:
            continue
        object_index = header.index("对象ID")
        blocking_index = header.index("是否阻塞")
        result: dict[str, str] = {}
        for row_line in lines[index + 2:]:
            if not row_line.strip().startswith("|"):
                break
            cells = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
            if len(cells) <= max(object_index, blocking_index):
                continue
            result[cells[object_index]] = cells[blocking_index]
        return result
    return {}


def validate_article_state_gates(
    root: Path,
    errors: list[str],
    *,
    completion_gate: bool = False,
) -> None:
    seen_ids: dict[str, Path] = {}
    todo_blocking = load_todo_blocking(root)
    for state, task_dir in article_task_dirs(root):
        required = ARTICLE_REQUIRED_BY_STATE[state]
        for filename in required:
            if not (task_dir / filename).is_file():
                errors.append(f"文章任务在{state}缺少必需文件{filename}：{task_dir}")
        source_index = task_dir / "35_写作素材来源索引.md"
        legacy_evidence = task_dir / "25_文章证据与审核包.md"
        legacy_task = legacy_evidence.is_file() and not source_index.is_file()
        if state in {"20_等待终稿", "30_等待Faithfulness", "40_已完成"}:
            if not source_index.is_file() and not legacy_task:
                errors.append(f"文章任务在{state}缺少35_写作素材来源索引.md：{task_dir}")
        if state in {"30_等待Faithfulness", "40_已完成"}:
            current_record = task_dir / "50_文章知识使用与Faithfulness记录.md"
            legacy_record = task_dir / "50_Faithfulness结果.md"
            if not current_record.is_file() and not legacy_record.is_file() and not legacy_task:
                errors.append(f"文章任务在{state}缺少50_文章知识使用与Faithfulness记录.md：{task_dir}")

        file_ids: dict[str, str] = {}
        for filename in ARTICLE_ID_FILES:
            path = task_dir / filename
            if not path.is_file():
                continue
            article_id = parse_field(path.read_text(encoding="utf-8-sig"), "文章ID")
            if not article_id:
                errors.append(f"文章任务文件缺少文章ID：{path}")
            else:
                file_ids[filename] = article_id
        ids = set(file_ids.values())
        if len(ids) > 1:
            errors.append(f"同一文章任务文件中的文章ID不一致：{task_dir}（{file_ids}）")
        article_id = file_ids.get("10_文章知识需求.md", next(iter(ids), ""))
        if article_id:
            if not task_dir.name.startswith(article_id + "_"):
                errors.append(f"文章任务目录名未以文章ID开头：{task_dir}")
            prior = seen_ids.get(article_id)
            if prior and prior != task_dir:
                errors.append(f"同一文章ID存在多个当前任务目录：{article_id}（{prior}；{task_dir}）")
            else:
                seen_ids[article_id] = task_dir

        audit_path = task_dir / "20_文章前知识审核.md"
        audit_result = ""
        if audit_path.is_file():
            audit_result = parse_field(audit_path.read_text(encoding="utf-8-sig"), "结论")
            if audit_result not in DELIVERABLE_AUDIT_RESULTS | BLOCKING_AUDIT_RESULTS:
                errors.append(f"文章前审核结论无效或未确定：{audit_path}")

        problem_path = task_dir / "文章前问题与处理单.md"
        problem_status = ""
        if problem_path.is_file():
            problem_text = problem_path.read_text(encoding="utf-8-sig")
            problem_status = parse_field(problem_text, "当前状态")
            if problem_status not in PROBLEM_SHEET_STATUSES:
                errors.append(f"文章前问题处理单状态无效：{problem_path}")
            for label in ("当前待办", "文章前审核", "返回步骤", "恢复条件", "自动执行方"):
                if not parse_field(problem_text, label):
                    errors.append(f"文章前问题处理单缺少{label}：{problem_path}")
            if not any(token in problem_text for token in ("CUS-", "MAT-", "ANM-", "无，并说明")):
                errors.append(f"文章前问题处理单未关联CUS/MAT/ANM或说明仅属文章决定：{problem_path}")

        if audit_result in BLOCKING_AUDIT_RESULTS:
            if not problem_path.is_file():
                errors.append(f"文章前审核等待人工处理但缺少文章前问题与处理单：{task_dir}")
            elif problem_status == "已关闭":
                errors.append(f"文章前审核仍在等待人工处理，但问题处理单已关闭：{task_dir}")

        if state in {"20_等待终稿", "30_等待Faithfulness", "40_已完成"}:
            if audit_result not in DELIVERABLE_AUDIT_RESULTS:
                errors.append(f"文章未通过审核却进入{state}：{task_dir}")
            if problem_path.is_file() and problem_status != "已关闭":
                errors.append(f"文章问题处理单未关闭却进入{state}：{task_dir}")

        if completion_gate and state == "10_进行中" and article_id:
            ready_files = all((task_dir / filename).is_file() for filename in ARTICLE_REQUIRED_BY_STATE["20_等待终稿"])
            ready_files = ready_files and (source_index.is_file() or legacy_task)
            ready = ready_files and audit_result in DELIVERABLE_AUDIT_RESULTS and (
                not problem_path.is_file() or problem_status == "已关闭"
            )
            if ready:
                errors.append(f"文章已具备交付条件但仍停在10_进行中，应自动移入20_等待终稿：{task_dir}")
                continue
            blocked_by_problem = problem_status in {"等待人工处理", "已处理，待自动复核"}
            blocked_in_todo = todo_blocking.get(article_id, "").startswith("是")
            if not blocked_by_problem and not blocked_in_todo:
                errors.append(
                    f"文章任务尚未形成可用输入且未记录真实阻塞，不得结束本轮或等待人工催办：{task_dir}"
                )


def validate_article_knowledge_packages(
    root: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    required_material_headings = (
        "一、可直接用于正文的事实",
        "二、可直接采用的英文表达",
        "三、可使用的数据表",
        "四、按大纲使用",
        "五、仅供生成控制（不得写入正文）",
        "六、缺少资料的章节及建议处理方式",
    )
    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return
    for material_path in task_root.rglob("30_本篇知识库资料.md"):
        if "90_归档" in material_path.parts:
            continue
        material_text = material_path.read_text(encoding="utf-8-sig")
        audit_path = material_path.with_name("35_写作素材来源索引.md")
        if parse_field(material_text, "资料视图") != "写作素材包":
            warnings.append(f"文章仍使用旧审计混合资料包，建议后续重建30/35文件对：{material_path}")
            continue

        if not audit_path.is_file():
            legacy_path = material_path.with_name("25_文章证据与审核包.md")
            if legacy_path.is_file():
                warnings.append(f"文章仍使用旧25/30文件对；当前版本保持可读，后续实质修改时升级为30/35：{material_path.parent}")
                continue
            errors.append(f"新写作素材包缺少35_写作素材来源索引.md：{material_path.parent}")
            continue
        audit_text = audit_path.read_text(encoding="utf-8-sig")
        if not re.search(r"^#\s+本篇写作素材包\s*$", material_text, re.MULTILINE):
            errors.append(f"30文件标题必须为“本篇写作素材包”：{material_path}")
        for heading in required_material_headings:
            if not re.search(rf"^##\s+{re.escape(heading)}\s*$", material_text, re.MULTILINE):
                errors.append(f"30写作素材包缺少固定章节“{heading}”：{material_path}")
        if re.search(r"^\s*[-*]\s*(?:Formal\s+)?Claim ID[：:]", material_text, re.MULTILINE | re.IGNORECASE):
            errors.append(f"30写作素材包不得显示Formal Claim ID：{material_path}")
        for forbidden in ("最小原文证据", "不应写入或尚无支持", "未解决知识问题"):
            if forbidden in material_text:
                errors.append(f"30写作素材包仍含审核包字段“{forbidden}”：{material_path}")
        material_lines = material_text.splitlines()
        evidence_scope, evidence_count = writing_material_evidence_scope(material_lines)
        factual_content = any(
            evidence_scope[index] or (
                line.strip()
                and not line.lstrip().startswith("#")
                and line.strip() != "无"
                and index > 0
            )
            for index, line in enumerate(material_lines)
        )
        if factual_content and evidence_count == 0:
            errors.append(f"30写作素材包存在内容但没有第1至第3节的证据正文：{material_path}")

        if not re.search(r"^#\s+写作素材来源索引\s*$", audit_text, re.MULTILINE):
            errors.append(f"35文件标题必须为“写作素材来源索引”：{audit_path}")
        for heading in ("写作素材到正式知识映射", "写作事实输入确认"):
            if not re.search(rf"^##\s+{re.escape(heading)}\s*$", audit_text, re.MULTILINE):
                errors.append(f"35写作素材来源索引缺少固定章节“{heading}”：{audit_path}")
        for forbidden in ("最小原文证据", "完整使用边界与明确排除", "未解决知识问题与处理状态"):
            if forbidden in audit_text:
                errors.append(f"35来源索引不得复制旧审核包章节“{forbidden}”：{audit_path}")

        material_id = parse_field(material_text, "文章ID")
        audit_id = parse_field(audit_text, "文章ID")
        if not material_id or material_id != audit_id:
            errors.append(f"30/35文章ID不一致：{material_path.parent}")
        recorded_hash = parse_field(audit_text, "写作素材SHA-256").lower()
        actual_hash = sha256_file(material_path).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", recorded_hash) or recorded_hash != actual_hash:
            errors.append(f"35记录的写作素材SHA-256与当前30不一致：{audit_path}")

        version_fields = {
            "10_文章知识需求.md": "当前版本",
            "15_检索与知识准备记录.md": "文章版本",
            "20_文章前知识审核.md": "文章版本",
            "30_本篇知识库资料.md": "文章版本",
            "35_写作素材来源索引.md": "文章版本",
            "40_最终文章.md": "文章版本",
            "50_文章知识使用与Faithfulness记录.md": "文章版本",
            "文章前问题与处理单.md": "文章版本",
        }
        versions: dict[str, str] = {}
        for filename, label in version_fields.items():
            version_path = material_path.with_name(filename)
            if not version_path.is_file():
                continue
            version_value = parse_field(version_path.read_text(encoding="utf-8-sig"), label)
            if not version_value:
                errors.append(f"新文章版本文件缺少{label}：{version_path}")
            else:
                versions[filename] = version_value
        if len(set(versions.values())) > 1:
            errors.append(f"同一文章当前文件的文章版本不一致：{material_path.parent}（{versions}）")

        material_line_count = len(material_lines)
        mapping_heading = re.search(
            r"^##\s+写作素材到正式知识映射\s*$",
            audit_text,
            re.MULTILINE,
        )
        if mapping_heading:
            mapping_body = audit_text[mapping_heading.end():]
            next_heading = re.search(r"^##\s+", mapping_body, re.MULTILINE)
            if next_heading:
                mapping_body = mapping_body[:next_heading.start()]
            row_pattern = re.compile(
                r"^\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*[^|]*\|\s*([A-Za-z0-9_.-]+)\s*\|",
                re.MULTILINE,
            )
            mapping_ranges: list[tuple[int, int]] = []
            for match in row_pattern.finditer(mapping_body):
                start, end = int(match.group(1)), int(match.group(2))
                claim_id = match.group(3)
                if start < 1 or end < start or end > material_line_count:
                    errors.append(f"35写作素材映射行范围无效（{start}-{end}）：{audit_path}")
                    continue
                if not all(evidence_scope[start - 1:end]):
                    errors.append(f"35映射必须完全位于30的证据正文内（{start}-{end}）：{audit_path}")
                    continue
                mapping_ranges.append((start, end))
            for index, in_evidence in enumerate(evidence_scope, 1):
                if not in_evidence or not material_lines[index - 1].strip():
                    continue
                if not any(start <= index <= end for start, end in mapping_ranges):
                    errors.append(f"30证据正文第{index}行没有35 Formal Claim映射：{audit_path}")

    for audit_path in task_root.rglob("35_写作素材来源索引.md"):
        if "90_归档" in audit_path.parts:
            continue
        material_path = audit_path.with_name("30_本篇知识库资料.md")
        if not material_path.is_file():
            errors.append(f"35写作素材来源索引缺少配对的30写作素材包：{audit_path.parent}")


def validate_version_archives(root: Path, errors: list[str]) -> None:
    archive_roots = (
        root / "04_文章任务/90_归档/10_文章历史版本",
        root / "05_数据与审核/60_版本归档/10_正式知识历史",
        root / "05_数据与审核/60_版本归档/20_控制文件迁移历史",
        root / "05_数据与审核/60_版本归档/30_机器文件迁移快照",
    )
    required_fields = (
        "对象类型", "对象ID", "人话名称", "归档版本", "归档时间",
        "归档原因", "归档前状态", "替代版本", "当前入口",
        "执行Skill", "Skill SHA-256",
    )
    manifest_pattern = re.compile(
        r"^\|\s*(?!文件名\s*\|)([^|]+?)\s*\|\s*`?([0-9a-fA-F]{64})`?\s*\|",
        re.MULTILINE,
    )
    for archive_root in archive_roots:
        if not archive_root.is_dir():
            continue
        for manifest in archive_root.rglob("00_版本说明.md"):
            text = manifest.read_text(encoding="utf-8-sig")
            for field in required_fields:
                if not parse_field(text, field):
                    errors.append(f"历史版本说明缺少{field}：{manifest}")
            rows = list(manifest_pattern.finditer(text))
            if not rows:
                errors.append(f"历史版本说明没有归档文件指纹：{manifest}")
                continue
            for match in rows:
                relative = match.group(1).strip().replace("\\|", "|")
                archived_file = manifest.parent / Path(relative)
                if not archived_file.is_file():
                    errors.append(f"历史版本说明引用的文件不存在：{archived_file}")
                elif sha256_file(archived_file).lower() != match.group(2).lower():
                    errors.append(f"历史归档文件SHA-256不匹配：{archived_file}")

    source_history = root / "05_数据与审核/60_版本归档/40_源资料版本记录/source_version_history.jsonl"
    if source_history.is_file():
        seen: set[str] = set()
        required = {
            "schema_version", "event_id", "detected_at", "source_id", "relative_path",
            "old_sha256", "new_sha256", "old_content_retained",
        }
        with source_history.open("r", encoding="utf-8-sig") as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.strip():
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    errors.append(f"源资料版本记录第{line_number}行不是有效JSON：{source_history}")
                    continue
                if not required.issubset(item):
                    errors.append(f"源资料版本记录第{line_number}行字段不完整：{source_history}")
                event_id = str(item.get("event_id", ""))
                if not event_id or event_id in seen:
                    errors.append(f"源资料版本记录event_id缺失或重复：{source_history}:{line_number}")
                seen.add(event_id)
                for field in ("old_sha256", "new_sha256"):
                    if not re.fullmatch(r"[0-9a-f]{64}", str(item.get(field, "")).lower()):
                        errors.append(f"源资料版本记录{field}无效：{source_history}:{line_number}")
                if item.get("old_content_retained") is not False:
                    errors.append(f"源资料版本记录不得声称已保存旧正文：{source_history}:{line_number}")


def validate_articles(
    root: Path,
    metrics: list[dict[str, str]],
    errors: list[str],
    warnings: list[str],
) -> None:
    current_metrics = {
        row["article_id"]: row
        for row in metrics
        if row.get("status") == "current"
    }
    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return
    for old_name in task_root.rglob("30_文章写作输入.md"):
        errors.append(f"发现v0.4旧写作输入文件，应使用30_本篇知识库资料.md：{old_name}")
    for old_name in task_root.rglob("40_最终文章与引用率.md"):
        errors.append(f"发现v0.4旧终稿文件，应使用40_最终文章.md：{old_name}")

    for article in task_root.rglob("40_最终文章.md"):
        if "90_归档" in article.parts:
            continue
        text = article.read_text(encoding="utf-8-sig")
        article_id = parse_field(text, "文章ID")
        article_version = parse_field(text, "文章版本")
        article_date = parse_field(text, "完成日期")
        if not article_id:
            errors.append(f"最终文章缺少文章ID：{article}")
            continue
        if not article_version:
            errors.append(f"最终文章缺少文章版本：{article}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", article_date):
            errors.append(f"最终文章完成日期无效：{article}")
        if re.search(r"^\s*[-*]\s*(?:正式)?引用率[：:]", text, re.MULTILINE):
            errors.append(f"最终文章仍含旧引用率字段：{article}")

        metric = current_metrics.get(article_id)
        state = next((part for part in article.parts if part in {
            "10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"
        }), "")
        task_dir = article.parent
        if not (task_dir / "30_本篇知识库资料.md").is_file():
            errors.append(f"有终稿但缺少本篇知识库资料：{task_dir}")
        receipt = task_dir / "50_文章知识使用与Faithfulness记录.md"
        legacy_task = (task_dir / "25_文章证据与审核包.md").is_file() and not (
            task_dir / "35_写作素材来源索引.md"
        ).is_file()
        legacy_receipt = task_dir / "50_Faithfulness结果.md"
        if not receipt.is_file() and not legacy_receipt.is_file() and not legacy_task:
            errors.append(f"有终稿但缺少文章知识使用与Faithfulness记录：{article_id}")
        if not metric:
            if state == "40_已完成":
                errors.append(f"已完成文章缺少当前Faithfulness结果：{article_id}")
            else:
                warnings.append(f"文章等待外部Faithfulness结果：{article_id}")
            continue
        if Path(metric["article_file"]).resolve() != article.resolve():
            errors.append(f"Faithfulness记录的文章路径不匹配：{article_id}")
        elif sha256_file(article) != metric["article_sha256"]:
            message = f"文章正文已修改，Faithfulness已失效：{article_id}"
            if state == "40_已完成":
                errors.append(message)
            else:
                warnings.append(message)
        if state == "40_已完成" and receipt.is_file():
            receipt_text = receipt.read_text(encoding="utf-8-sig")
            if parse_field(receipt_text, "当前状态") not in {"已导入，观察完成", "已导入，存在待处理事项"}:
                errors.append(f"已完成文章的50记录状态不是已导入：{article_id}")

def validate_monthly_and_handoff(root: Path, errors: list[str], warnings: list[str]) -> None:
    review_root = root / "05_数据与审核/40_月度与交接"
    if not review_root.is_dir():
        return
    open_problem_sheets: list[tuple[str, str, Path]] = []
    for sheet in (root / "04_文章任务").rglob("文章前问题与处理单.md"):
        text = sheet.read_text(encoding="utf-8-sig")
        status = parse_field(text, "当前状态")
        if status == "已关闭":
            continue
        article_id = parse_field(text, "文章ID")
        article_title = parse_field(text, "文章标题")
        if article_id and article_title:
            open_problem_sheets.append((article_id, article_title, sheet))

    def check_problem_sheet_links(path: Path, text: str) -> None:
        if not open_problem_sheets:
            return
        section = text.split("### 文章前问题与处理单", 1)[1] if "### 文章前问题与处理单" in text else ""
        if not section or "[[" not in section:
            errors.append(f"记录未提供开放文章处理单的逐篇直达链接：{path}")
            return
        for article_id, article_title, sheet in open_problem_sheets:
            if article_id not in section or article_title not in section or sheet.name not in section:
                errors.append(
                    f"记录未逐篇关联开放文章处理单（需文章ID、文章标题和文件名）：{sheet} -> {path}"
                )

    for path in review_root.glob("*_月度知识库审核.md"):
        text = path.read_text(encoding="utf-8-sig")
        for heading in (
            "## 一、运行与规范",
            "## 二、知识库基础情况",
            "## 三、本月提取与知识沉淀",
            "## 四、月度文章 Faithfulness",
            "## 五、问题与闭环",
            "### MAT", "### CUS", "### ANM", "### SKFB",
        ):
            if heading not in text:
                errors.append(f"月度审核缺少固定部分 {heading}：{path}")
        if "15%" in text:
            errors.append(f"月度审核仍使用v0.4的15%阈值：{path}")
        template_version = parse_field(text, "月度模板版本")
        if template_version != MONTHLY_TEMPLATE_VERSION:
            warnings.append(f"历史月度审核尚未使用三类企业来源与七模块新模板，不自动改写：{path}")
        else:
            for heading in ("### 企业来源入口与可用状态", "### 七模块资料与正式知识覆盖"):
                if heading not in text:
                    errors.append(f"月度审核第二部分缺少固定小节 {heading}：{path}")
            source_header, source_rows = markdown_table(path, "### 企业来源入口与可用状态")
            if tuple(source_header) != MONTHLY_SOURCE_HEADER:
                errors.append(f"月度审核第二部分未使用固定企业来源表头：{path}")
            else:
                source_types = {row[0].strip() for row in source_rows if row}
                for source_type in MONTHLY_SOURCE_TYPES:
                    if source_type not in source_types:
                        errors.append(f"月度审核第二部分缺少企业来源类型 {source_type}：{path}")
            coverage_header, coverage_rows = markdown_table(path, "### 七模块资料与正式知识覆盖")
            if tuple(coverage_header) != MONTHLY_COVERAGE_HEADER:
                errors.append(f"月度审核第二部分未使用固定七模块覆盖表头：{path}")
            else:
                by_module = {row[0].strip(): row for row in coverage_rows if row}
                for module in MONTHLY_MODULES:
                    row = by_module.get(module)
                    if not row or len(row) != len(MONTHLY_COVERAGE_HEADER):
                        errors.append(f"月度审核第二部分缺少标准模块 {module}：{path}")
                        continue
                    status = row[1].strip()
                    if status not in MONTHLY_COVERAGE_STATUSES:
                        errors.append(f"月度审核第二部分覆盖状态无效：{module} = {status or '空'}（{path}）")
                    for column_index in range(2, len(MONTHLY_COVERAGE_HEADER)):
                        if not row[column_index].strip():
                            errors.append(
                                f"月度审核第二部分 {module} 缺少内容："
                                f"{MONTHLY_COVERAGE_HEADER[column_index]}（{path}）"
                            )
            section_two = text.split("## 二、知识库基础情况", 1)[1].split("## 三、本月提取与知识沉淀", 1)[0]
            if "当前文章影响" in section_two:
                errors.append(f"月度审核第二部分不应继续以当前文章影响为固定列：{path}")
        check_problem_sheet_links(path, text)
    for path in review_root.glob("*_项目交接审核.md"):
        text = path.read_text(encoding="utf-8-sig")
        conclusion = parse_field(text, "结论")
        if conclusion not in {"可以交接", "补充后交接", "暂不能交接"}:
            errors.append(f"项目交接结论无效：{path}")
        for label in ("### CUS", "### ANM", "### MAT", "### SKFB"):
            if label not in text:
                errors.append(f"项目交接缺少 {label}：{path}")
        check_problem_sheet_links(path, text)


def run_self_test() -> int:
    relative = Path(str(LEDGER_RULES["MAT"]["path"]))
    with tempfile.TemporaryDirectory(prefix="v05-validator-test-") as temp:
        root = Path(temp)
        path = root / relative
        path.parent.mkdir(parents=True)
        valid = """# 源资料处理台账

## 当前事项

| MAT ID | 事项名称 | 代表文件/资料范围 | 资料数量 | 通俗问题 | 当前文章影响 | 当前阶段 | 下一责任人/动作 | 重开条件 | 详情入口 | 最近更新 |
|---|---|---|---:|---|---|---|---|---|---|---|
| DEMO-MAT-001 | 培训资料版本判断 | 4段培训视频 + 1份配套PPT | 5 | 不确定哪些版本可作为当前依据 | 当前无 | 待知识库专员判断 | AI知识库专员核对版本 | 新文章命中或文件变化 | [[#DEMO-MAT-001｜培训资料版本判断]] | 2026-08-18 |

## 事项详情

### DEMO-MAT-001｜培训资料版本判断

- 归组范围：同一套培训资料
- 代表文件/资料范围：4段培训视频 + 1份配套PPT
- 资料数量：5
- 为什么合并为一项：处理原因、责任人和关闭条件一致
- 源资料总表：[[../../../../02_源资料/源资料与可检索性台账.md]]
- 稳定源资料根路径与相对路径：培训资料/中低压电缆/
- 下一责任人/动作：AI知识库专员核对版本
- 重开条件：新文章命中或文件变化
"""
        path.write_text(valid, encoding="utf-8")
        valid_errors: list[str] = []
        validate_ledgers(root, valid_errors)
        if valid_errors:
            print(json.dumps({"ok": False, "stage": "valid-grouped-mat", "errors": valid_errors}, ensure_ascii=False))
            return 1

        invalid = valid.replace(
            "4段培训视频 + 1份配套PPT | 5 |",
            "SRC-a1b2c3d4e5f6, SRC-112233aabbcc | 2 |",
            1,
        ).replace("### DEMO-MAT-001｜培训资料版本判断", "### 资料处理详情", 1)
        path.write_text(invalid, encoding="utf-8")
        invalid_errors: list[str] = []
        validate_ledgers(root, invalid_errors)
        expected = ("代表文件/资料范围只有ID", "缺少同一事项的人话详情标题")
        if not all(any(fragment in item for item in invalid_errors) for fragment in expected):
            print(json.dumps({"ok": False, "stage": "invalid-id-only-mat", "errors": invalid_errors}, ensure_ascii=False))
            return 1
        broken_table = root / "broken-table.md"
        broken_table.write_text("| A |\n|---|\n| 1 |\n\n| 2 |\n", encoding="utf-8")
        if not table_continuity_errors(broken_table):
            print(json.dumps({"ok": False, "stage": "broken-table", "errors": []}, ensure_ascii=False))
            return 1
        feedback = root / str(LEDGER_RULES["SKFB"]["path"])
        feedback.parent.mkdir(parents=True, exist_ok=True)
        feedback.write_text(
            "# Skill反馈台账\n\n## 当前反馈\n\n"
            "| SKFB ID | 提出来源 | 类型 | 通俗说明 | 复现依据 | 当前阶段 | 维护负责人 | 关联项目对象入口 | 最近更新 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| DEMO-SKFB-001 | Codex | 校验遗漏 | 表格结构未校验 | self-test | 已纳入维护 | 维护负责人 | [[对象]] | 2026-08-19 |\n\n"
            "## 反馈详情\n\n### DEMO-SKFB-001｜表格结构未校验\n\n- 当前阶段：已纳入维护\n",
            encoding="utf-8",
        )
        feedback_errors: list[str] = []
        validate_feedback_details(root, feedback_errors)
        if feedback_errors:
            print(json.dumps({"ok": False, "stage": "feedback-detail-pair", "errors": feedback_errors}, ensure_ascii=False))
            return 1

        task_root = root / "04_文章任务"
        for state in ARTICLE_STATES:
            (task_root / state).mkdir(parents=True, exist_ok=True)
        empty_waiting = task_root / "20_等待终稿/DEMO-ART-EMPTY_空任务"
        empty_waiting.mkdir()
        empty_errors: list[str] = []
        validate_article_state_gates(root, empty_errors)
        expected_files = ("10_文章知识需求.md", "15_检索与知识准备记录.md", "20_文章前知识审核.md", "30_本篇知识库资料.md", "35_写作素材来源索引.md")
        if not all(any(filename in item for item in empty_errors) for filename in expected_files):
            print(json.dumps({"ok": False, "stage": "empty-waiting-task", "errors": empty_errors}, ensure_ascii=False))
            return 1
        empty_waiting.rmdir()

        article_id = "DEMO-ART-001"
        valid_task = task_root / f"20_等待终稿/{article_id}_测试文章"
        valid_task.mkdir()
        (valid_task / "10_文章知识需求.md").write_text(
            f"# 文章知识需求\n\n- 文章ID：{article_id}\n- 当前版本：v1\n", encoding="utf-8"
        )
        (valid_task / "15_检索与知识准备记录.md").write_text(
            f"# 检索与知识准备记录\n\n- 文章ID：{article_id}\n- 文章版本：v1\n", encoding="utf-8"
        )
        (valid_task / "20_文章前知识审核.md").write_text(
            f"# 文章前知识审核\n\n- 文章ID：{article_id}\n- 文章版本：v1\n- 结论：自动通过\n", encoding="utf-8"
        )
        material_path = valid_task / "30_本篇知识库资料.md"
        material_path.write_text(
            f"# 本篇写作素材包\n\n"
            f"- 文章ID：{article_id}\n- 文章版本：v1\n- 资料视图：写作素材包\n- 资料版本：1\n"
            "- 生成日期：2026-08-19\n- 目标语言：英文\n"
            "- 对应大纲：[[10_文章知识需求.md#大纲]]\n"
            "- 使用对象：写作流程；本文件为唯一写作事实输入。\n\n"
            "## 一、可直接用于正文的事实\n\n"
            "### Demo section\n\n#### 事实素材：Demo\n\n"
            "- 可直接采用的事实：Verified fact.\n- 使用条件：无\n\n"
            "##### 证据正文（供Faithfulness核验）\n\n> Verified fact.\n\n"
            "## 二、可直接采用的英文表达\n\n无\n\n"
            "## 三、可使用的数据表\n\n无\n\n"
            "## 四、按大纲使用\n\n无\n\n"
            "## 五、仅供生成控制（不得写入正文）\n\n- 仅使用明确事实。\n\n"
            "## 六、缺少资料的章节及建议处理方式\n\n无\n",
            encoding="utf-8",
        )
        material_hash = sha256_file(material_path)
        (valid_task / "35_写作素材来源索引.md").write_text(
            f"# 写作素材来源索引\n\n- 文章ID：{article_id}\n- 文章版本：v1\n- 索引版本：1\n"
            f"- 生成日期：2026-08-19\n- 对应写作素材：[[30_本篇知识库资料.md]]\n"
            f"- 写作素材SHA-256：{material_hash}\n"
            "- 用途：仅供内部追溯与Faithfulness映射；不得交给写作模型。\n\n"
            "## 写作素材到正式知识映射\n\n"
            "| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 23 | 23 | Demo | CLM-DEMO-001 | Demo fact | [[demo.md]] | demo.pdf p.1 |\n\n"
            "## 写作事实输入确认\n\n"
            "- 唯一事实输入：[[30_本篇知识库资料.md]]\n"
            "- 其他事实附件：无；随文事实文件必须先进入来源层、Formal Claim和当前30/35。\n",
            encoding="utf-8",
        )
        valid_task_errors: list[str] = []
        validate_article_state_gates(root, valid_task_errors)
        if valid_task_errors:
            print(json.dumps({"ok": False, "stage": "valid-waiting-task", "errors": valid_task_errors}, ensure_ascii=False))
            return 1
        package_errors: list[str] = []
        package_warnings: list[str] = []
        validate_article_knowledge_packages(root, package_errors, package_warnings)
        if package_errors or package_warnings:
            print(json.dumps({"ok": False, "stage": "valid-30-35-pair", "errors": package_errors, "warnings": package_warnings}, ensure_ascii=False))
            return 1
        audit_path = valid_task / "35_写作素材来源索引.md"
        valid_audit_text = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(valid_audit_text.replace("| 23 | 23 |", "| 18 | 18 |"), encoding="utf-8")
        boundary_errors: list[str] = []
        validate_article_knowledge_packages(root, boundary_errors, [])
        if not any("必须完全位于30的证据正文" in item for item in boundary_errors):
            print(json.dumps({"ok": False, "stage": "non-evidence-35-mapping", "errors": boundary_errors}, ensure_ascii=False))
            return 1
        audit_path.write_text(valid_audit_text, encoding="utf-8")
        material_path.write_text(material_path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        mismatch_errors: list[str] = []
        validate_article_knowledge_packages(root, mismatch_errors, [])
        if not any("SHA-256" in item for item in mismatch_errors):
            print(json.dumps({"ok": False, "stage": "mismatched-30-35-pair", "errors": mismatch_errors}, ensure_ascii=False))
            return 1

        in_progress_id = "DEMO-ART-002"
        in_progress = task_root / f"10_进行中/{in_progress_id}_未阻塞任务"
        in_progress.mkdir()
        (in_progress / "10_文章知识需求.md").write_text(
            f"# 文章知识需求\n\n- 文章ID：{in_progress_id}\n", encoding="utf-8"
        )
        completion_errors: list[str] = []
        validate_article_state_gates(root, completion_errors, completion_gate=True)
        if not any("不得结束本轮或等待人工催办" in item for item in completion_errors):
            print(json.dumps({"ok": False, "stage": "nonblocking-completion-gate", "errors": completion_errors}, ensure_ascii=False))
            return 1
        (in_progress / "20_文章前知识审核.md").write_text(
            f"# 文章前知识审核\n\n- 文章ID：{in_progress_id}\n- 结论：等待内容运营业务决定\n",
            encoding="utf-8",
        )
        missing_problem_errors: list[str] = []
        validate_article_state_gates(root, missing_problem_errors)
        if not any("缺少文章前问题与处理单" in item for item in missing_problem_errors):
            print(json.dumps({"ok": False, "stage": "missing-problem-sheet", "errors": missing_problem_errors}, ensure_ascii=False))
            return 1
        (in_progress / "文章前问题与处理单.md").write_text(
            f"# 文章前问题与处理单\n\n"
            f"- 文章ID：{in_progress_id}\n"
            "- 当前状态：等待人工处理\n"
            "- 当前待办：[[../../../01_工作台/20_当前待办.md]]\n"
            "- 文章前审核：[[20_文章前知识审核.md]]\n"
            "- 返回步骤：文章前审核\n"
            "- 恢复条件：人工决定公开范围\n"
            "- 自动执行方：Codex\n\n"
            "- 证据与关联入口：无，并说明为什么只属于文章业务决定\n",
            encoding="utf-8",
        )
        valid_problem_errors: list[str] = []
        validate_article_state_gates(root, valid_problem_errors)
        if valid_problem_errors:
            print(json.dumps({"ok": False, "stage": "valid-problem-sheet", "errors": valid_problem_errors}, ensure_ascii=False))
            return 1

        archive_dir = root / "04_文章任务/90_归档/10_文章历史版本/DEMO-ART-ARCHIVE/v1_20260819-120000"
        archive_dir.mkdir(parents=True)
        snapshot = archive_dir / "10_文章知识需求.md"
        snapshot.write_text("# 文章知识需求\n\n- 文章ID：DEMO-ART-ARCHIVE\n", encoding="utf-8")
        snapshot_hash = sha256_file(snapshot)
        (archive_dir / "00_版本说明.md").write_text(
            "# 历史版本说明\n\n"
            "- 对象类型：article\n"
            "- 对象ID：DEMO-ART-ARCHIVE\n"
            "- 人话名称：归档校验文章\n"
            "- 归档版本：v1\n"
            "- 归档时间：2026-08-19T12:00:00+08:00\n"
            "- 归档原因：self-test\n"
            "- 归档前状态：20_等待终稿\n"
            "- 替代版本：v2\n"
            "- 当前入口：04_文章任务/20_等待终稿/DEMO-ART-ARCHIVE_归档校验文章\n"
            "- 执行Skill：manage-article-knowledge v0.5\n"
            f"- Skill SHA-256：{'a' * 64}\n\n"
            "## 归档文件与指纹\n\n"
            "| 文件名 | SHA-256 | 说明 |\n"
            "|---|---|---|\n"
            f"| 10_文章知识需求.md | `{snapshot_hash}` | 修改前只读快照 |\n",
            encoding="utf-8",
        )
        archive_errors: list[str] = []
        validate_version_archives(root, archive_errors)
        if archive_errors:
            print(json.dumps({"ok": False, "stage": "valid-version-archive", "errors": archive_errors}, ensure_ascii=False))
            return 1
        snapshot.write_text(snapshot.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        tamper_errors: list[str] = []
        validate_version_archives(root, tamper_errors)
        if not any("SHA-256不匹配" in item for item in tamper_errors):
            print(json.dumps({"ok": False, "stage": "tampered-version-archive", "errors": tamper_errors}, ensure_ascii=False))
            return 1
    with tempfile.TemporaryDirectory(prefix="v05-website-monthly-test-") as temp:
        root = Path(temp)
        info = root / "01_工作台/10_项目基础信息.md"
        info.parent.mkdir(parents=True)
        info.write_text(
            "# 项目基础信息\n\n"
            "- 官网：https://example.com\n\n"
            "## 官网初步画像\n\n"
            "- 画像状态：已完成\n\n"
            "| 回写字段 | 当前值 | 页面名称与具体URL | 获取日期 | 原文依据 | 判断方式 | 使用边界 |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 项目英文名称 | Demo | Home https://example.com | 2026-08-21 | Demo | 官网明确 | 不证明法定名称 |\n"
            "| 行业或业务类别 | Demo | Home https://example.com | 2026-08-21 | Demo | 官网明确 | 不替代人工决定 |\n"
            "| 主要业务与产品 | Demo | Home https://example.com | 2026-08-21 | Demo | 官网明确 | 官网展示范围 |\n"
            "| 市场、服务区域与网站语言 | Demo | Home https://example.com | 2026-08-21 | Demo | 官网明确 | 不推定销售范围 |\n\n"
            f"{RELATED_WEBSITE_SECTION}\n\n"
            f"| {' | '.join(RELATED_WEBSITE_HEADER)} |\n"
            f"|{'|'.join('---' for _ in RELATED_WEBSITE_HEADER)}|\n"
            "| WEB-DEMO-001 | Demo子品牌产品站 | 子品牌官网 | https://brand.example.com | 子品牌；内容运营于2026-08-21提交 | 项目级通用（默认） | 全部文章（默认） | 可访问 | 2026-08-21 | 产品介绍；品牌产品目录 | 页面变化、文章命中或月度审核 |\n",
            encoding="utf-8",
        )
        profile_errors: list[str] = []
        profile_warnings: list[str] = []
        validate_project_profile(root, profile_errors, profile_warnings)
        if profile_errors:
            print(json.dumps({"ok": False, "stage": "valid-related-website", "errors": profile_errors}, ensure_ascii=False))
            return 1
        invalid_profile = info.read_text(encoding="utf-8").replace(
            "| 可访问 | 2026-08-21 |", "| 暂时无法访问 | 2026-08-21 |", 1
        ).replace("页面变化、文章命中或月度审核 |", "无 |", 1)
        info.write_text(invalid_profile, encoding="utf-8")
        invalid_profile_errors: list[str] = []
        validate_project_profile(root, invalid_profile_errors, [])
        if not any("缺少重试条件" in item for item in invalid_profile_errors):
            print(json.dumps({"ok": False, "stage": "invalid-related-website", "errors": invalid_profile_errors}, ensure_ascii=False))
            return 1

        review = root / "05_数据与审核/40_月度与交接/2026-08_月度知识库审核.md"
        review.parent.mkdir(parents=True)
        source_rows = "\n".join(
            f"| {source_type} | 1组 | 可用 | 无 | [[入口]] |" for source_type in MONTHLY_SOURCE_TYPES
        )
        coverage_rows = "\n".join(
            f"| {module} | 已有来源且已有正式知识 | [[客户文件]] | https://example.com | https://brand.example.com | [[正式知识]] | 已核验的当前范围 | 尚未发现 |"
            for module in MONTHLY_MODULES
        )
        monthly = (
            "# 企业知识库月度审核\n\n"
            "## 一、运行与规范\n\n"
            "## 二、知识库基础情况\n\n"
            f"- 月度模板版本：{MONTHLY_TEMPLATE_VERSION}\n\n"
            "### 企业来源入口与可用状态\n\n"
            f"| {' | '.join(MONTHLY_SOURCE_HEADER)} |\n"
            f"|{'|'.join('---' for _ in MONTHLY_SOURCE_HEADER)}|\n{source_rows}\n\n"
            "### 七模块资料与正式知识覆盖\n\n"
            f"| {' | '.join(MONTHLY_COVERAGE_HEADER)} |\n"
            f"|{'|'.join('---' for _ in MONTHLY_COVERAGE_HEADER)}|\n{coverage_rows}\n\n"
            "## 三、本月提取与知识沉淀\n\n"
            "## 四、月度文章 Faithfulness\n\n"
            "## 五、问题与闭环\n\n"
            "### MAT\n\n### CUS\n\n### ANM\n\n### SKFB\n"
        )
        review.write_text(monthly, encoding="utf-8")
        monthly_errors: list[str] = []
        validate_monthly_and_handoff(root, monthly_errors, [])
        if monthly_errors:
            print(json.dumps({"ok": False, "stage": "valid-monthly-section-two", "errors": monthly_errors}, ensure_ascii=False))
            return 1
        review.write_text(monthly.replace("已有来源且已有正式知识", "自由填写", 1), encoding="utf-8")
        invalid_monthly_errors: list[str] = []
        validate_monthly_and_handoff(root, invalid_monthly_errors, [])
        if not any("覆盖状态无效" in item for item in invalid_monthly_errors):
            print(json.dumps({"ok": False, "stage": "invalid-monthly-section-two", "errors": invalid_monthly_errors}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--completion-gate",
        action="store_true",
        help="结束本轮前检查：不允许未阻塞的文章任务停在自动流程中间",
    )
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(run_self_test())
    if not args.project:
        raise SystemExit("--project is required unless --self-test is used")
    root = args.project.resolve()
    if not root.is_dir():
        raise SystemExit(f"Project not found: {root}")

    errors: list[str] = []
    warnings: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"缺少必需文件：{relative}")

    base = root / "01_工作台/10_项目基础信息.md"
    if base.is_file() and "manage-article-knowledge v0.5" not in base.read_text(encoding="utf-8-sig"):
        errors.append("项目基础信息未声明manage-article-knowledge v0.5")

    metrics_path = root / "05_数据与审核/10_Faithfulness/10_文章Faithfulness明细.csv"
    support_path = root / "05_数据与审核/10_Faithfulness/20_Claim文章支撑记录.csv"
    metrics = load_metrics(metrics_path, errors)
    check_csv_schema(support_path, SUPPORT_FIELDS, errors)
    validate_index(root, errors, warnings)
    validate_source_exclusions(root, errors, warnings)
    validate_version_entry(root, errors, warnings)
    validate_project_profile(root, errors, warnings)
    validate_layout(root, errors, warnings)
    validate_version_archives(root, errors)
    validate_token_usage(root, errors)
    validate_claims(root, errors, warnings)
    validate_ledgers(root, errors)
    validate_feedback_details(root, errors)
    for markdown_path in root.rglob("*.md"):
        if any(part in {".obsidian", ".git", "90_归档"} for part in markdown_path.parts):
            continue
        errors.extend(table_continuity_errors(markdown_path))
    validate_retrieval_records(root, errors)
    validate_source_references(root, errors)
    validate_mat_dependencies(root, errors)
    validate_article_knowledge_packages(root, errors, warnings)
    validate_articles(root, metrics, errors, warnings)
    validate_article_state_gates(root, errors, completion_gate=args.completion_gate)
    validate_monthly_and_handoff(root, errors, warnings)

    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}")
    print(f"warnings={len(warnings)}")
    print(f"errors={len(errors)}")
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
