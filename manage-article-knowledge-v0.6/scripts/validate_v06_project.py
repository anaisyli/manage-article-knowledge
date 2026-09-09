#!/usr/bin/env python3
"""Validate the lightweight control structure of a v0.6 project."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import tempfile
from pathlib import Path

from build_coverage_view import MODULES, coverage_fingerprint, formal_files, knowledge_gaps
from check_integration import validate as validate_integration_config
from template_contract import (
    ARTICLE_AUDIT_TEMPLATE_VERSION,
    BLOCKING_COMPLEX_MATERIAL_STATES,
    COMPLEX_MATERIAL_HEADER,
    complex_material_rows,
    validate_project_templates,
)
from mat_lifecycle import (
    MAT_DEPENDENCY_VALUES,
    MAT_ID_RE,
    MAT_LIFECYCLE_COLUMNS,
    MAT_PUSH_STATUSES,
    current_table,
    source_ledger_fields,
)


REQUIRED_FILES = (
    "01_工作台/10_项目基础信息.md",
    "01_工作台/20_当前待办.md",
    "01_工作台/30_版本与变更入口.md",
    "01_工作台/40_写作与Faithfulness接入配置.md",
    "02_源资料/源资料与可检索性台账.md",
    "02_源资料/源资料搜索索引说明.md",
    "02_源资料/source-index.sqlite",
    "05_数据与审核/01_数据说明.md",
    "05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md",
    "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv",
    "05_数据与审核/50_运行记录/10_写作任务接入记录.csv",
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
KNOWLEDGE_GAP_FIELDS = (
    "gap_key", "gap_topic", "gap_type", "trigger_basis", "article_ids",
    "article_count", "status", "current_impact", "next_action", "first_seen",
    "last_seen", "related_governance_ref",
)
KNOWLEDGE_GAP_STATUSES = {"观察中", "待外部调研", "已解决", "已关闭"}
WRITING_TASK_IMPORT_FIELDS = (
    "external_task_key", "source_path", "source_locator", "source_sha256",
    "article_id", "article_version", "imported_at", "current_status",
)
CLAIM_REQUIRED_FIELDS = (
    "Claim ID", "Claim", "适用范围", "来源类型", "来源链接", "精确位置",
    "日期或版本", "使用边界", "状态",
)
CLAIM_STATUSES = {"可用", "受限使用", "待知识库专员确认", "已失效"}
CLAIM_MODULES = {
    "公司概述", "产品介绍", "解决方案", "合作案例", "企业提供行业知识", "FAQ", "其他", "外部公共知识",
}
CLAIM_MODULE_PATHS = (
    (Path("10_客户知识/10_公司概述"), "公司概述"),
    (Path("10_客户知识/20_产品介绍"), "产品介绍"),
    (Path("10_客户知识/30_解决方案"), "解决方案"),
    (Path("10_客户知识/40_合作案例"), "合作案例"),
    (Path("10_客户知识/50_行业知识与洞察/10_企业提供"), "企业提供行业知识"),
    (Path("10_客户知识/60_FAQ"), "FAQ"),
    (Path("10_客户知识/70_其他"), "其他"),
    (Path("20_外部公共知识/50_行业知识与洞察"), "外部公共知识"),
)
UTF8_BOM = b"\xef\xbb\xbf"
PROJECT_ROOT_PATTERN = re.compile(r"^[^\\/:*?\"<>|]+_[^\\/:*?\"<>|]+知识库_v0\.6$")
SKFB_TERMINAL_STAGES = {"已关闭", "转为项目问题", "不纳入Skill"}
SKFB_NEGATIVE_VALIDATION_RE = re.compile(
    r"(?m)^-\s*(?:原复现项目验证|项目验证)[：:].*(?:未运行|未验证|尚未|待执行|待验证|不通过|失败)"
)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
REQUIRED_LAYOUT_DIRECTORIES = (
    "01_工作台",
    "02_源资料",
    "02_源资料/20_MinerU按需提取",
    "02_源资料/50_外部调研证据",
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


def is_transient_article_directory(path: Path) -> bool:
    """Return whether a bridge staging/retired directory is not a current task."""
    return path.name.startswith((".retired-", ".revision-"))
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
BLOCKING_AUDIT_RESULTS = {
    "等待内容运营处理", "等待项目负责人决定", "等待知识库专员处理",
    "等待内容运营业务决定",
}
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
            if in_evidence_section and re.match(r"^证据正文（供Faithfulness核验）$", title):
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
PREPARATION_COVERAGE_HEADER = (
    "大纲章节", "六层检索范围与结果", "命中来源与精确入口", "候选事实ID",
    "候选事实数", "已沉淀Claim数", "未采用事实/缺口及原因", "下一步",
)
OUTLINE_COVERAGE_HEADER = (
    "大纲章节", "知识问题", "覆盖状态", "已有证据/Claim", "缺口或治理事项", "本篇处理",
)
OUTLINE_COVERAGE_STATUSES = {"已覆盖", "部分覆盖", "未覆盖", "无需事实支持"}
PREPARATION_SUFFICIENCY_HEADER = (
    "大纲章节", "候选事实数", "已沉淀Claim数", "计划纳入30的事实块数",
    "覆盖结论", "未采用事实/缺口及入口",
)
PREPARATION_SUFFICIENCY_RESULTS = {"充分", "有明确边界", "无需事实支持"}
MAT_DEPENDENCY_STATES = {"无", "待决定", "已决定"}
MAT_SELECTION_STATES = {"待决定", "已决定", "不适用"}
MAT_SELECTION_DECISIONS = {
    "指定代表/当前版本", "全部比对后使用", "仅使用明确范围", "排除候选", "暂不处理", "待决定", "无"
}
MAT_DECISION_OWNERS = {
    "内容运营", "项目负责人（用户）", "AI知识库专员", "Codex自动处理", "待定", "无"
}
OPEN_MAT_STAGES = {"待知识库专员判断", "知识库专员处理中", "等待材料或工具"}
MAT_SELECTION_HEADER = (
    "MAT ID", "候选SRC ID", "文件名与稳定路径", "关系/处理问题", "决定",
    "选取或排除范围", "决定依据", "决定方", "当前状态",
)
GOVERNANCE_DETECTION_HEADER = (
    "检测对象", "已检查信号与来源", "分类结论", "事项与证据入口", "本篇处理",
)
GOVERNANCE_DETECTORS = {
    "CUS候选检测": {"未触发", "已复用", "已登记"},
    "ANM异常检测": {"未触发", "自动修复并留痕", "已复用", "已登记"},
}
FAITHFULNESS_DISPOSITION_HEADER = (
    "归组及claim_id", "知识问题/内容", "分类", "分类依据", "本篇影响",
    "关联事项/入口", "当前处理", "下一步",
)
LEGACY_FAITHFULNESS_DISPOSITION_HEADER = (
    "归组", "包含claim_id", "知识问题/内容", "分类与依据", "本篇影响", "处理结果与入口",
)
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
MONTHLY_TEMPLATE_VERSION = "v0.6-20260908"
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
CUS_DETECTION_CATEGORIES = (
    "客户能力", "规格", "认证", "案例", "商业条件", "公开授权",
)
CUS_LOW_FAITHFULNESS_THRESHOLD = 80.0


def table_headers(text: str) -> list[tuple[str, ...]]:
    lines = text.splitlines()
    headers: list[tuple[str, ...]] = []
    for index in range(len(lines) - 1):
        if not lines[index].strip().startswith("|") or not is_table_separator(lines[index + 1]):
            continue
        headers.append(tuple(cell.strip() for cell in lines[index].strip().strip("|").split("|")))
    return headers


def load_source_searchability_map(root: Path) -> dict[str, str]:
    """Read the source-ledger status needed for article-level complex-source checks."""
    path = root / "02_源资料/源资料与可检索性台账.md"
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("|") and "资料ID" in line and "可检索状态" in line),
        None,
    )
    if header_index is None or header_index + 1 >= len(lines):
        return {}
    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    indexes = {name: index for index, name in enumerate(header)}
    source_index = indexes.get("资料ID")
    searchability_index = indexes.get("可检索状态")
    if source_index is None or searchability_index is None:
        return {}
    mapping: dict[str, str] = {}
    for line in lines[header_index + 2:]:
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) <= max(source_index, searchability_index):
            continue
        if cells[source_index]:
            mapping[cells[source_index]] = cells[searchability_index]
    return mapping


def validate_retrieval_records(root: Path, errors: list[str]) -> None:
    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return
    project_info = root / "01_工作台/10_项目基础信息.md"
    requires_related_website_layer = (
        project_info.is_file()
        and RELATED_WEBSITE_SECTION in project_info.read_text(encoding="utf-8-sig")
    )
    source_searchability = load_source_searchability_map(root)
    for path in task_root.rglob("15_检索与知识准备记录.md"):
        if "90_归档" in path.parts:
            continue
        text = path.read_text(encoding="utf-8-sig")
        task_state = next((part for part in path.parts if part in ARTICLE_STATES), "")
        dependency = parse_field(text, "MAT依赖处理")
        if dependency not in MAT_DEPENDENCY_STATES:
            errors.append(f"文章检索记录缺少或未确定MAT依赖处理字段：{path}")
        selection_header, selection_rows = markdown_table(path, "## MAT依赖与资料选择")
        if tuple(selection_header) != MAT_SELECTION_HEADER:
            errors.append(f"文章检索记录缺少固定MAT依赖与资料选择表：{path}")
        else:
            if not selection_rows:
                errors.append(f"文章检索记录MAT依赖与资料选择表没有实际行：{path}")
            for row in selection_rows:
                if len(row) != len(MAT_SELECTION_HEADER):
                    errors.append(f"文章检索记录MAT选择行列数错误：{path}")
                    continue
                mat_id, source_id, filename, relation, decision, scope, basis, decision_owner, state_value = (
                    cell.strip() for cell in row
                )
                if state_value not in MAT_SELECTION_STATES:
                    errors.append(f"文章检索记录MAT选择状态无效：{state_value or '空'}（{path}）")
                if decision not in MAT_SELECTION_DECISIONS and not decision.startswith("无"):
                    errors.append(f"文章检索记录MAT选择决定无效：{decision or '空'}（{path}）")
                if decision_owner not in MAT_DECISION_OWNERS:
                    errors.append(f"文章检索记录MAT决定方无效：{decision_owner or '空'}（{path}）")
                if state_value == "待决定" and dependency != "待决定":
                    errors.append(f"文章检索记录MAT选择仍待决定但总字段不是待决定：{path}")
                if state_value == "已决定" and (not decision or decision == "无" or not basis):
                    errors.append(f"文章检索记录MAT已决定但缺少决定或依据：{path}")
            if dependency == "无" and not any(row[0].strip() == "无" for row in selection_rows if row):
                errors.append(f"MAT依赖处理为无时，选择表必须保留无/不适用行：{path}")

        complex_rows = complex_material_rows(text)
        complex_by_source = {
            row[0].strip(): row for row in complex_rows
            if len(row) >= len(COMPLEX_MATERIAL_HEADER) and row[0].strip() != "无"
        }
        referenced_partial_sources = {
            source_id for source_id in re.findall(r"\bSRC-[A-Za-z0-9]+\b", text)
            if source_searchability.get(source_id, "").startswith("部分内容可搜索")
        }
        for source_id in sorted(referenced_partial_sources):
            row = complex_by_source.get(source_id)
            if not row:
                errors.append(
                    f"文章引用部分内容可搜索资料但没有复杂资料处理与原件核对记录：{source_id}（{path}）"
                )
                continue
            if task_state in {"20_等待终稿", "30_等待Faithfulness", "40_已完成"} and row[8].strip() in BLOCKING_COMPLEX_MATERIAL_STATES:
                errors.append(
                    f"文章引用的部分内容可搜索资料尚未完成处理：{source_id} = {row[8].strip()}（{path}）"
                )

        source_mat = load_source_mat_map(root)
        mat_status = load_mat_status_map(root)
        state = next((part for part in path.parts if part in {
            "10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"
        }), "")
        referenced_sources = {
            source_id for source_id in re.findall(r"\bSRC-[A-Za-z0-9]+\b", text)
            if source_id in source_mat
        }
        referenced_mats = set(re.findall(r"\bMAT-[A-Za-z0-9-]+\b", text))
        open_dependencies = {
            mat_id for source_id, mat_id in source_mat.items()
            if source_id in referenced_sources and mat_status.get(mat_id, "") in OPEN_MAT_STAGES
        }
        open_dependencies.update(
            mat_id for mat_id in referenced_mats if mat_status.get(mat_id, "") in OPEN_MAT_STAGES
        )
        if open_dependencies and dependency != "已决定":
            if dependency != "待决定":
                errors.append(
                    f"文章命中开放MAT但MAT依赖处理未标为待决定：{', '.join(sorted(open_dependencies))}（{path}）"
                )
        if dependency == "待决定" and open_dependencies:
            if state != "10_进行中":
                errors.append(f"MAT依赖仍待决定但文章已离开10_进行中：{path}")
        if dependency == "已决定" and open_dependencies and state in {
            "20_等待终稿", "30_等待Faithfulness", "40_已完成"
        }:
            errors.append(
                f"文章MAT已决定但关联MAT仍未完成处理，必须先完成资料处理再交付：{', '.join(sorted(open_dependencies))}（{path}）"
            )
        headers = table_headers(text)
        if headers.count(SOURCE_HIT_HEADER) != 1:
            errors.append(f"文章检索记录必须只有一个标准四列表：{path}")
        if any(header == ("知识问题", "命中Claim或资料", "相关理由", "处理结果") for header in headers):
            errors.append(f"文章检索记录仍使用旧列名“命中Claim或资料”：{path}")
        if re.search(r"^##\s+官网产品页命中", text, re.MULTILINE):
            errors.append(f"文章检索记录不应另建官网产品页命中表：{path}")
        matrix_header, matrix_rows = markdown_table(path, "## 大纲逐项检索与候选事实覆盖")
        if tuple(matrix_header) != PREPARATION_COVERAGE_HEADER:
            errors.append(f"文章检索记录缺少固定大纲逐项检索与候选事实覆盖表：{path}")
        elif not matrix_rows:
            errors.append(f"文章检索记录大纲逐项检索与候选事实覆盖表没有实际行：{path}")
        else:
            labels = {row[0].strip() for row in matrix_rows if row}
            for required_label in ("标题", "主问题"):
                if required_label not in labels:
                    errors.append(f"文章检索记录逐项覆盖表缺少{required_label}：{path}")
            for row in matrix_rows:
                if len(row) != len(PREPARATION_COVERAGE_HEADER):
                    errors.append(f"文章检索记录逐项覆盖行列数错误：{path}")
                    continue
                chapter, search_scope, source_entry, candidate_refs, candidates, claims, omitted, next_step = (
                    cell.strip() for cell in row
                )
                if not chapter or not search_scope or not source_entry or not next_step:
                    errors.append(f"文章检索记录逐项覆盖行缺少章节、检索范围、来源入口或下一步：{path}")
                if search_scope in {"已检索", "检索完成", "无"}:
                    errors.append(f"文章检索记录未写明六层实际检索范围：{chapter}（{path}）")
                if not candidates.isdigit() or not claims.isdigit():
                    errors.append(f"文章检索记录候选事实数和Claim数必须为非负整数：{chapter}（{path}）")
                    continue
                candidate_count, claim_count = int(candidates), int(claims)
                referenced = set(re.findall(r"\bCF-\d{3}\b", candidate_refs))
                if candidate_refs == "无":
                    referenced = set()
                if len(referenced) != candidate_count:
                    errors.append(f"文章检索记录候选事实ID数量与候选事实数不一致：{chapter}（{path}）")
                if claim_count > candidate_count:
                    errors.append(f"文章检索记录Claim数大于候选事实数：{chapter}（{path}）")
                if candidate_count > claim_count and omitted in {"", "无", "未记录", "待补充"}:
                    errors.append(f"文章检索命中候选事实但未完整沉淀且没有逐项原因：{chapter}（{path}）")
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


def validate_article_governance_checks(
    root: Path,
    errors: list[str],
    warnings: list[str],
    metrics: list[dict[str, str]] | None = None,
) -> None:
    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return
    current_metrics = {
        row.get("article_id", ""): row
        for row in (metrics or [])
        if row.get("status") == "current"
    }
    for path in task_root.rglob("20_文章前知识审核.md"):
        if "90_归档" in path.parts:
            continue
        text = path.read_text(encoding="utf-8-sig")
        template_version = parse_field(text, "审核模板版本")
        if not template_version:
            errors.append(f"文章前审核缺少固定审核模板版本：{path}")
            continue
        if template_version != ARTICLE_AUDIT_TEMPLATE_VERSION:
            errors.append(f"文章前审核模板版本无效：{template_version}（{path}）")
            continue

        coverage_header, coverage_rows = markdown_table(path, "## 大纲知识覆盖检查")
        if tuple(coverage_header) != OUTLINE_COVERAGE_HEADER:
            errors.append(f"文章前审核缺少固定大纲知识覆盖表：{path}")
        elif not coverage_rows:
            errors.append(f"文章前审核大纲知识覆盖表没有实际检查行：{path}")
        else:
            for row in coverage_rows:
                if len(row) != len(OUTLINE_COVERAGE_HEADER):
                    errors.append(f"文章前审核大纲知识覆盖行列数错误：{path}")
                    continue
                chapter, question, status, evidence, governance, handling = (
                    cell.strip() for cell in row
                )
                if not chapter or not question or not handling:
                    errors.append(f"文章前审核大纲知识覆盖行缺少章节、知识问题或本篇处理：{path}")
                if status not in OUTLINE_COVERAGE_STATUSES:
                    errors.append(f"文章前审核覆盖状态无效：{status or '空'}（{path}）")
                if status == "已覆盖" and (not evidence or evidence in {"无", "待补充"}):
                    errors.append(f"文章前审核标记已覆盖但没有证据/Claim：{chapter}（{path}）")
                if status in {"部分覆盖", "未覆盖"}:
                    markers = ("gap_key", "CUS-", "MAT-", "ANM-", "不构成知识问题：")
                    if not governance or not any(marker in governance for marker in markers):
                        errors.append(
                            f"文章前审核{status}但未关联gap_key/CUS/MAT/ANM或写明排除理由："
                            f"{chapter}（{path}）"
                        )

        sufficiency_header, sufficiency_rows = markdown_table(path, "## 知识准备充分性复核")
        if tuple(sufficiency_header) != PREPARATION_SUFFICIENCY_HEADER:
            errors.append(f"文章前审核缺少固定知识准备充分性复核表：{path}")
        elif not sufficiency_rows:
            errors.append(f"文章前审核知识准备充分性复核表没有实际行：{path}")
        else:
            labels = {row[0].strip() for row in sufficiency_rows if row}
            for required_label in ("标题", "主问题"):
                if required_label not in labels:
                    errors.append(f"文章前审核充分性复核缺少{required_label}：{path}")
            for row in sufficiency_rows:
                if len(row) != len(PREPARATION_SUFFICIENCY_HEADER):
                    errors.append(f"文章前审核充分性复核行列数错误：{path}")
                    continue
                chapter, candidates, claims, blocks, conclusion, omitted = (
                    cell.strip() for cell in row
                )
                if not all(value.isdigit() for value in (candidates, claims, blocks)):
                    errors.append(f"文章前审核充分性计数必须为非负整数：{chapter}（{path}）")
                    continue
                candidate_count, claim_count, block_count = map(int, (candidates, claims, blocks))
                if conclusion not in PREPARATION_SUFFICIENCY_RESULTS:
                    errors.append(f"文章前审核充分性结论无效：{conclusion or '空'}（{path}）")
                if claim_count > candidate_count:
                    errors.append(f"文章前审核充分性计数顺序无效：{chapter}（{path}）")
                if claim_count > 0 and block_count == 0 and omitted in {"", "无", "未记录", "待补充"}:
                    errors.append(f"文章前审核已有Claim但未计划纳入30，缺少排除原因或治理入口：{chapter}（{path}）")
                if (candidate_count > claim_count or (claim_count > 0 and block_count == 0)) and omitted in {"", "无", "未记录", "待补充"}:
                    errors.append(f"文章前审核充分性存在数量差异但没有原因或治理入口：{chapter}（{path}）")

        detection_header, detection_rows = markdown_table(path, "## CUS / ANM检测结果")
        if tuple(detection_header) != GOVERNANCE_DETECTION_HEADER:
            errors.append(f"文章前审核缺少固定CUS/ANM检测结果表：{path}")
            continue
        by_detector = {row[0].strip(): row for row in detection_rows if row}
        for detector, allowed in GOVERNANCE_DETECTORS.items():
            row = by_detector.get(detector)
            if not row or len(row) != len(GOVERNANCE_DETECTION_HEADER):
                errors.append(f"文章前审核缺少{detector}结果：{path}")
                continue
            signals, conclusion, entry, handling = (
                row[1].strip(), row[2].strip(), row[3].strip(), row[4].strip()
            )
            if not signals or signals in {"已检查", "无异常", "无", "不适用"}:
                errors.append(f"{detector}未写实际检查信号与来源：{path}")
            if detector == "CUS候选检测":
                missing_categories = [
                    category for category in CUS_DETECTION_CATEGORIES
                    if category not in signals
                ]
                if missing_categories:
                    errors.append(
                        f"CUS候选检测未覆盖固定类别（{'、'.join(missing_categories)}）：{path}"
                    )
                article_id = parse_field(text, "文章ID")
                metric = current_metrics.get(article_id, {})
                try:
                    score = float(metric.get("faithfulness_percent", ""))
                except (TypeError, ValueError):
                    score = None
                if score is not None and score < CUS_LOW_FAITHFULNESS_THRESHOLD:
                    if "Faithfulness低于80%后复核" not in signals and "Faithfulness低于80%后复核" not in handling:
                        errors.append(
                            f"Faithfulness低于{CUS_LOW_FAITHFULNESS_THRESHOLD:.0f}%后必须重新检查CUS六类客户事实：{path}"
                        )
            if conclusion not in allowed:
                errors.append(f"{detector}分类结论无效：{conclusion or '空'}（{path}）")
            if not entry or not handling:
                errors.append(f"{detector}缺少事项/证据入口或本篇处理：{path}")
            if conclusion in {"已复用", "已登记"}:
                expected = "CUS-" if detector.startswith("CUS") else "ANM-"
                if expected not in entry:
                    errors.append(f"{detector}已触发但入口没有{expected}：{path}")
            if conclusion == "自动修复并留痕" and "处理记录" not in entry:
                errors.append(f"ANM自动修复结果缺少处理记录入口：{path}")


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


def load_mat_status_map(root: Path) -> dict[str, str]:
    path = root / "05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md"
    if not path.is_file():
        return {}
    header, rows = markdown_table(path, "## 当前事项")
    if "MAT ID" not in header or "当前阶段" not in header:
        return {}
    mat_index = header.index("MAT ID")
    status_index = header.index("当前阶段")
    result: dict[str, str] = {}
    for row in rows:
        if len(row) > max(mat_index, status_index) and row[mat_index].strip():
            result[row[mat_index].strip()] = row[status_index].strip()
    return result


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
            if not task_dir.is_dir() or is_transient_article_directory(task_dir):
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


def _open_article_mat_references(root: Path, mat_id: str) -> list[tuple[Path, str]]:
    matches: list[tuple[Path, str]] = []
    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return matches
    for path in task_root.rglob("文章前问题与处理单.md"):
        if "90_归档" in path.parts:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if mat_id not in text:
            continue
        state_match = re.search(r"(?m)^-\s*当前状态[：:]\s*(.*?)\s*$", text)
        matches.append((path, state_match.group(1).strip() if state_match else ""))
    return matches


def validate_mat_lifecycle(root: Path, errors: list[str], warnings: list[str]) -> None:
    """Cross-check source candidates, formal MATs, article work orders, and todo."""
    db = root / "02_源资料/source-index.sqlite"
    mat_path = root / "05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md"
    source_path = root / "02_源资料/源资料与可检索性台账.md"
    if not db.is_file() or not mat_path.is_file():
        return
    try:
        connection = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(sources)")}
        required = {"mat_candidate", "mat_id", "mat_disposition"}
        if not required.issubset(columns):
            if "mat_candidate" in columns:
                candidate_count = connection.execute(
                    "SELECT COUNT(*) FROM sources WHERE COALESCE(mat_candidate, '') <> '' AND COALESCE(duplicate_of, '') = ''"
                ).fetchone()[0]
                if candidate_count:
                    errors.append(
                        f"source-index.sqlite中有{candidate_count}个MAT候选，但缺少正式MAT关联字段；请重新构建来源索引"
                    )
            warnings.append("旧版source-index.sqlite缺少MAT正式化字段；重新构建来源索引后才会执行候选-MAT交叉校验")
            connection.close()
            return
        source_rows = connection.execute(
            "SELECT source_id, duplicate_of, mat_candidate, mat_id, mat_disposition FROM sources"
        ).fetchall()
        connection.close()
    except sqlite3.Error as exc:
        errors.append(f"无法读取MAT生命周期来源索引：{exc}")
        return

    table = current_table(mat_path)
    if table is None:
        errors.append(f"MAT正式台账缺少“## 当前事项”主表：{mat_path}")
        return
    header = list(table["header"])
    indexes = {name: index for index, name in enumerate(header)}
    formal: dict[str, dict[str, str]] = {}
    for row in table["rows"]:
        if not row or not MAT_ID_RE.fullmatch(row[0].strip()):
            continue
        formal[row[0].strip()] = {
            name: row[index].strip() if index < len(row) else ""
            for name, index in indexes.items()
        }
    candidate_source_ids = [
        source_id for source_id, duplicate_of, candidate, *_ in source_rows
        if candidate and not duplicate_of
    ]
    if candidate_source_ids and not formal:
        errors.append(
            f"来源台账存在{len(candidate_source_ids)}个MAT候选，但MAT当前事项主表为空；必须建立正式MAT或写明无需建立理由"
        )
    source_ledger = source_ledger_fields(source_path)
    for source_id, duplicate_of, candidate, db_mat_id, db_disposition in source_rows:
        ledger_row = source_ledger.get(source_id, {})
        ledger_mat_id = ledger_row.get("MAT", "").strip()
        mat_id = str(db_mat_id or ledger_mat_id or "").strip()
        if db_mat_id and ledger_mat_id and str(db_mat_id).strip() != ledger_mat_id:
            errors.append(f"来源{source_id}的source-index.sqlite MAT与来源台账不一致：{db_mat_id} / {ledger_mat_id}")
        if mat_id and mat_id not in formal:
            errors.append(f"来源{source_id}引用了不存在的正式MAT：{mat_id}")
        if candidate and not duplicate_of and not mat_id:
            disposition = str(db_disposition or ledger_row.get("MAT处置说明", "")).strip()
            if not disposition.startswith(("无需建立MAT", "不建立MAT", "完全重复", "已复用")):
                errors.append(f"来源{source_id}有MAT候选但没有正式MAT ID或明确无需建立理由")

    lifecycle_missing = [column for column in MAT_LIFECYCLE_COLUMNS if column not in indexes]
    has_candidates = any(candidate and not duplicate for _, duplicate, candidate, *_ in source_rows)
    if lifecycle_missing:
        if has_candidates:
            errors.append(f"MAT主表缺少生命周期字段：{', '.join(lifecycle_missing)}；请重新构建来源索引升级台账")
        else:
            warnings.append(f"旧版MAT主表缺少生命周期字段：{', '.join(lifecycle_missing)}")
        return

    todo_text = (root / "01_工作台/20_当前待办.md").read_text(encoding="utf-8-sig") if (root / "01_工作台/20_当前待办.md").is_file() else ""
    for mat_id, record in formal.items():
        dependency = record.get("是否有当前文章依赖", "")
        blocking = record.get("是否阻塞当前文章", "")
        push = record.get("内容运营推送状态", "")
        if dependency not in MAT_DEPENDENCY_VALUES:
            errors.append(f"MAT {mat_id} 的当前文章依赖值无效：{dependency or '空'}")
        if blocking not in {"否", "是"}:
            errors.append(f"MAT {mat_id} 的是否阻塞当前文章值无效：{blocking or '空'}")
        if push not in MAT_PUSH_STATUSES:
            errors.append(f"MAT {mat_id} 的内容运营推送状态无效：{push or '空'}")
        if dependency == "否" and blocking == "是":
            errors.append(f"MAT {mat_id} 标为阻塞但没有当前文章依赖")
        if dependency == "否" and push != "不需要推送":
            errors.append(f"MAT {mat_id} 没有当前文章依赖却标记为{push}")
        if blocking == "是" and push not in {"待推送", "已推送", "已升级"}:
            errors.append(f"MAT {mat_id} 已阻塞当前文章但没有内容运营推送状态")
        if push in {"待推送", "已推送", "已升级"}:
            if dependency != "是" or blocking != "是":
                errors.append(f"MAT {mat_id}已进入内容运营推送状态，但依赖/阻塞字段不是“是”")
            references = _open_article_mat_references(root, mat_id)
            if not references:
                errors.append(f"MAT {mat_id}已进入内容运营推送状态，但没有开放文章前问题与处理单")
            if mat_id not in todo_text:
                errors.append(f"MAT {mat_id}已进入内容运营推送状态，但当前待办没有对应入口")
        for path, state in _open_article_mat_references(root, mat_id):
            if state and state != "已关闭" and push == "不需要推送":
                errors.append(f"开放文章处理单引用MAT {mat_id}，但推送状态仍为“不需要推送”：{path}")


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
        stage = row[stage_index].strip()
        for field in ("关闭条件", "重开条件"):
            field_match = re.search(rf"(?m)^-\s*{re.escape(field)}[：:]\s*(.*?)\s*$", block)
            if not field_match or not field_match.group(1).strip():
                errors.append(f"SKFB详情缺少{field}：{item_id}（{path}）")
        if stage == "已关闭":
            close_evidence = re.search(r"(?m)^-\s*关闭依据[：:]\s*(.*?)\s*$", block)
            if not close_evidence or not close_evidence.group(1).strip():
                errors.append(f"已关闭SKFB缺少关闭依据：{item_id}（{path}）")
            if SKFB_NEGATIVE_VALIDATION_RE.search(block):
                errors.append(f"已关闭SKFB仍保留未验证或待执行的项目验证措辞：{item_id}（{path}）")

    for raw_target in WIKILINK_RE.findall(text):
        target = raw_target.strip()
        if not target or target.startswith(("http://", "https://")):
            continue
        if not any(char in target for char in ("/", "\\")) and Path(target).suffix.lower() not in {
            ".md", ".csv", ".json", ".jsonl", ".txt", ".py"
        }:
            continue
        candidate = (path.parent / target).resolve()
        if not candidate.exists():
            errors.append(f"SKFB关联入口不存在或已过期：{target}（{path}）")


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
            errors.append(f"Faithfulness明细CSV字段不符合v0.6：{path}")
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
        errors.append(f"CSV字段不符合v0.6：{path}")


def validate_writing_task_imports(path: Path, errors: list[str]) -> None:
    check_csv_schema(path, WRITING_TASK_IMPORT_FIELDS, errors)
    if not path.is_file():
        return
    seen: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for line_number, row in enumerate(csv.DictReader(stream), 2):
            key = row.get("external_task_key", "").strip()
            article_id = row.get("article_id", "").strip()
            if not key or not article_id:
                errors.append(f"写作任务接入记录缺少外部任务唯一键或文章ID：{path}:{line_number}")
                continue
            prior = seen.get(key)
            if prior and prior != article_id:
                errors.append(
                    f"同一外部任务唯一键映射多个文章ID：{key}（{prior}；{article_id}）"
                )
            seen[key] = article_id


def validate_knowledge_gaps(path: Path, errors: list[str]) -> None:
    check_csv_schema(path, KNOWLEDGE_GAP_FIELDS, errors)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        seen_keys: set[str] = set()
        for line_number, row in enumerate(reader, 2):
            key = row.get("gap_key", "").strip()
            if not key or key in seen_keys:
                errors.append(f"知识缺口gap_key缺失或重复：{path}:{line_number}")
            seen_keys.add(key)
            if row.get("gap_type") != "公共知识":
                errors.append(f"知识缺口只能记录真实公共知识：{path}:{line_number}")
            if row.get("status") not in KNOWLEDGE_GAP_STATUSES:
                errors.append(f"知识缺口状态无效：{path}:{line_number}")
            article_ids = list(dict.fromkeys(item.strip() for item in row.get("article_ids", "").split(";") if item.strip()))
            try:
                article_count = int(row.get("article_count", ""))
            except ValueError:
                article_count = -1
            if not article_ids or article_count != len(article_ids):
                errors.append(f"知识缺口文章数必须等于不同文章ID数：{path}:{line_number}")
            if not row.get("gap_topic", "").strip() or not row.get("next_action", "").strip():
                errors.append(f"知识缺口缺少人话主题或下一步：{path}:{line_number}")
            if row.get("status") == "已解决" and "RES-" not in row.get("related_governance_ref", ""):
                errors.append(f"已解决知识缺口必须关联RES调研记录：{path}:{line_number}")


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
            module = parse_field(block, "归类模块")
            rationale = parse_field(block, "归类依据")
            relative = path.relative_to(root / "03_正式知识")
            expected_module = next(
                (module_name for prefix, module_name in CLAIM_MODULE_PATHS if relative.is_relative_to(prefix)),
                "",
            )
            if not expected_module:
                errors.append(f"Claim {claim_id} 不在七模块或外部公共知识的固定目录：{path}")
            elif not module and not rationale:
                warnings.append(f"历史Claim缺少归类模块和归类依据；下次更新必须补齐：{claim_id}（{path}）")
            elif not module or not rationale:
                errors.append(f"Claim {claim_id} 的归类模块和归类依据必须同时填写：{path}")
            else:
                if module not in CLAIM_MODULES:
                    errors.append(f"Claim {claim_id} 归类模块无效：{module}（{path}）")
                elif module != expected_module:
                    errors.append(
                        f"Claim {claim_id} 归类模块与固定目录不一致：{module} != {expected_module}（{path}）"
                    )
                if len(rationale) < 12:
                    errors.append(f"Claim {claim_id} 归类依据过短，必须说明本条事实主要回答的对象：{path}")
                if module == "其他" and "不属于" not in rationale:
                    errors.append(f"Claim {claim_id} 归入其他时，归类依据必须说明不属于前六类的原因：{path}")
                if module == "外部公共知识" and not claim_id.startswith("CLM-EXT-"):
                    errors.append(f"外部公共知识Claim必须使用CLM-EXT命名空间：{claim_id}（{path}）")
                if module != "外部公共知识" and claim_id.startswith("CLM-EXT-"):
                    errors.append(f"客户知识Claim不能使用CLM-EXT命名空间：{claim_id}（{path}）")
            if "### 最小原文证据" not in block or not re.search(r"^\s*>\s*\S", block, re.MULTILINE):
                errors.append(f"Claim {claim_id} 未发现引用块形式的最小原文证据：{path}")

    external_groups: dict[str, list[tuple[int, str, Path]]] = {}
    for claim_id, path in claim_ids.items():
        if not claim_id.startswith("CLM-EXT-"):
            continue
        match = re.fullmatch(r"(.+-)(\d{3})", claim_id)
        if not match:
            errors.append(f"外部Claim编号必须使用CLM-EXT-[主题]-三位流水号：{claim_id}（{path}）")
            continue
        external_groups.setdefault(match.group(1), []).append((int(match.group(2)), claim_id, path))
    for prefix, entries in external_groups.items():
        numbers = sorted(item[0] for item in entries)
        expected = list(range(1, max(numbers) + 1))
        if numbers != expected:
            missing = sorted(set(expected) - set(numbers))
            errors.append(
                f"外部Claim命名空间{prefix}编号不连续；缺少{', '.join(f'{value:03d}' for value in missing)}，"
                "客户Claim编号不得用于补号"
            )


def formal_claim_index(root: Path) -> dict[str, Path]:
    """Return the current Formal Claim IDs and their concrete files."""
    marker = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
    index: dict[str, Path] = {}
    formal_root = root / "03_正式知识"
    if not formal_root.is_dir():
        return index
    for path in formal_root.rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        for match in marker.finditer(text):
            index.setdefault(match.group(1), path)
    return index


def validate_external_claim_links(
    root: Path,
    errors: list[str],
    warnings: list[str] | None = None,
) -> None:
    """Require external Claims to point back to one RES evidence and review record."""
    external_root = root / "03_正式知识/20_外部公共知识"
    if not external_root.is_dir():
        return
    project_info = root / "01_工作台/10_项目基础信息.md"
    is_competitor_policy_project = project_info.is_file() and "竞品信息限制：" in project_info.read_text(encoding="utf-8-sig")
    marker = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
    for path in external_root.rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        matches = list(marker.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.start():end]
            claim_id = match.group(1)
            if not claim_id.startswith("CLM-EXT-"):
                errors.append(f"外部公共知识目录中的Claim必须使用CLM-EXT命名空间：{claim_id}（{path}）")
            evidence = parse_field(block, "原文证据")
            review = parse_field(block, "调研核验")
            if not evidence or "RES-" not in evidence:
                errors.append(f"外部Claim {claim_id} 缺少RES原文证据回链：{path}")
            if not review or "RES-" not in review:
                errors.append(f"外部Claim {claim_id} 缺少RES调研核验回链：{path}")
            competitor_screen = parse_field(block, "竞品信息筛查")
            if not competitor_screen and is_competitor_policy_project:
                errors.append(f"外部Claim {claim_id} 缺少竞品信息筛查记录：{path}")
            elif not competitor_screen and warnings is not None:
                warnings.append(f"外部Claim {claim_id} 缺少竞品信息筛查记录（旧知识不自动改写）：{path}")
            elif competitor_screen and "通过" not in competitor_screen:
                errors.append(f"外部Claim {claim_id} 未通过竞品信息筛查：{path}")


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
        required = {"metadata", "sources", "chunks", "chunks_fts", "relationships", "source_topic_mappings"}
        missing = required - tables
        if missing:
            errors.append(f"机器索引缺少表：{', '.join(sorted(missing))}")
        source_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sources)")
        }
        expected_columns = {
            "media_duration", "transcript_status", "office_media_count", "office_embedded_count",
            "source_role", "role_basis", "role_confidence", "role_status",
        }
        missing_columns = expected_columns - source_columns
        if missing_columns:
            errors.append(f"机器索引sources缺少v0.6字段：{', '.join(sorted(missing_columns))}")
        source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        if source_count == 0:
            warnings.append("机器索引中没有登记任何源文件")
        if "source_topic_mappings" in tables:
            valid_modules = {"公司概述", "产品介绍", "解决方案", "合作案例", "行业知识与洞察", "FAQ", "其他", "待确认"}
            valid_confidence = {"高", "中", "低"}
            valid_status = {"机器初判", "已核验", "待确认"}
            valid_roles = {"客户事实资料", "写作运营资料", "疑似文章或终稿", "待确认"}
            role_rows = {
                row[0]: {"role": row[1], "sha256": row[2]}
                for row in connection.execute("SELECT source_id, source_role, sha256 FROM sources")
            }
            for source_id, module, topic, basis, confidence, status in connection.execute(
                "SELECT source_id, module, topic, basis, confidence, status FROM source_topic_mappings"
            ):
                if module not in valid_modules:
                    errors.append(f"来源主题映射模块值无效：{source_id} / {module}")
                if confidence not in valid_confidence or status not in valid_status:
                    errors.append(f"来源主题映射判断状态无效：{source_id} / {confidence} / {status}")
                if not str(topic).strip() or not str(basis).strip():
                    errors.append(f"来源主题映射缺少主题或判断依据：{source_id} / {module}")
                if role_rows.get(source_id, {}).get("role") != "客户事实资料":
                    errors.append(f"非客户事实资料不得进入七模块候选：{source_id}")
            mapping_rows = connection.execute(
                "SELECT source_id, source_sha256 FROM source_topic_mappings"
            ).fetchall()
            source_hashes = {source_id: values["sha256"] for source_id, values in role_rows.items()}
            for source_id, mapping_sha256 in mapping_rows:
                if source_hashes.get(source_id, "").lower() != str(mapping_sha256).lower():
                    errors.append(f"来源主题映射与来源SHA-256不一致：{source_id}")
            for source_id, values in role_rows.items():
                if values["role"] not in valid_roles:
                    errors.append(f"来源资料角色值无效：{source_id} / {values['role']}")
        connection.close()
    except sqlite3.Error as exc:
        errors.append(f"机器索引无法读取：{exc}")

    ledger = root / "02_源资料/源资料与可检索性台账.md"
    if ledger.is_file():
        headers = table_headers(ledger.read_text(encoding="utf-8-sig"))
        mapping_header = ("资料ID/资料名称", "资料角色", "标准模块候选", "主题候选", "判断依据", "归类状态")
        if any("可能主题" in header for header in headers):
            errors.append(f"来源台账旧“可能主题”列尚未迁移：{ledger}")
        if headers.count(mapping_header) != 1:
            errors.append(f"来源台账缺少唯一“来源主题与模块候选”表：{ledger}")


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
    if "manage-article-knowledge v0.6" not in text:
        errors.append(f"版本入口未声明manage-article-knowledge v0.6：{path}")
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


def validate_competitor_policy(root: Path, errors: list[str], warnings: list[str]) -> None:
    """Check that the project/article templates carry the non-relaxable competitor boundary."""
    project_info = root / "01_工作台/10_项目基础信息.md"
    if project_info.is_file():
        text = project_info.read_text(encoding="utf-8-sig")
        if "竞品信息限制：" not in text:
            warnings.append(f"项目基础信息缺少固定竞品信息限制字段（旧项目不自动改写）：{project_info}")
        elif "禁止搜索、保存或沉淀" not in text or "仅允许保留去品牌化" not in text:
            errors.append(f"项目基础信息的竞品信息限制未使用禁止搜索/去品牌化固定规则：{project_info}")
        if "竞品限制继承规则：" not in text:
            warnings.append(f"项目基础信息缺少竞品限制继承规则字段（旧项目不自动改写）：{project_info}")

    task_root = root / "04_文章任务"
    if not task_root.is_dir():
        return
    for request in task_root.rglob("10_文章知识需求.md"):
        if "90_归档" in request.parts:
            continue
        text = request.read_text(encoding="utf-8-sig")
        if "竞品信息限制：" not in text:
            warnings.append(f"文章知识需求缺少竞品信息限制字段（旧任务不自动改写）：{request}")
        elif "继承项目级禁止" not in text or "不可放宽" not in text:
            errors.append(f"文章知识需求的竞品信息限制必须继承项目级禁止且不可放宽：{request}")


def validate_coverage_freshness(
    root: Path,
    errors: list[str],
    warnings: list[str],
    *,
    strict: bool = False,
) -> None:
    """Ensure the human view is generated from the current governed data."""
    coverage = root / "05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md"
    if not coverage.is_file():
        return
    text = coverage.read_text(encoding="utf-8-sig")
    recorded = parse_field(text, "覆盖数据指纹").lower()
    if not recorded:
        message = f"知识库覆盖视图缺少覆盖数据指纹，无法证明页面是最新的：{coverage}"
        (errors if strict else warnings).append(message)
        return
    actual = coverage_fingerprint(root)
    if recorded != actual:
        message = f"知识库覆盖视图已过期：页面指纹={recorded}，当前数据指纹={actual}（{coverage}）"
        (errors if strict else warnings).append(message)
        return

    for _, _, relative in MODULES:
        for formal in formal_files(root, relative):
            if formal.stem not in text:
                errors.append(f"知识库覆盖视图未列出正式知识文件：{formal}（{coverage}）")
            if "未识别到标准Claim标题" in text or "类型未登记" in text or "状态未登记" in text:
                errors.append(f"知识库覆盖视图包含无法识别的正式知识摘要：{formal}（{coverage}）")
    for gap in knowledge_gaps(root):
        topic = gap.get("gap_topic", "").strip()
        if topic and topic not in text:
            errors.append(f"知识库覆盖视图未列出知识缺口：{topic}（{coverage}）")


def validate_layout(
    root: Path,
    errors: list[str],
    warnings: list[str],
    *,
    strict_coverage: bool = False,
) -> None:
    """Report naming and layout drift without renaming an existing project."""
    if not PROJECT_ROOT_PATTERN.fullmatch(root.name):
        warnings.append(f"项目根目录不符合统一命名 [项目ID]_[企业中文名称]知识库_v0.6：{root}")
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
        validate_coverage_freshness(root, errors, warnings, strict=strict_coverage)

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
                if not task_dir.is_dir() or is_transient_article_directory(task_dir):
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
        result.extend(
            (state, path)
            for path in state_root.iterdir()
            if path.is_dir() and not is_transient_article_directory(path)
        )
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

        request_path = task_dir / "10_文章知识需求.md"
        if state in {"20_等待终稿", "30_等待Faithfulness", "40_已完成"} and request_path.is_file():
            request_text = request_path.read_text(encoding="utf-8-sig")
            for label in ("文章ID", "当前版本", "文章标题", "目标语言", "关键词"):
                value = parse_field(request_text, label)
                if label == "文章标题" and not value:
                    value = parse_field(request_text, "标题")
                if not value:
                    errors.append(f"交付前文章知识需求缺少固定字段“{label}”：{request_path}")
            outline_match = re.search(
                r"^##\s+大纲\s*$([\s\S]*?)(?=^##\s+|\Z)",
                request_text,
                re.MULTILINE,
            )
            outline_body = outline_match.group(1).strip() if outline_match else ""
            outline_status = parse_field(outline_body, "大纲状态")
            outline_content = re.sub(r"^\s*-\s*大纲状态[：:].*$", "", outline_body, flags=re.MULTILINE).strip()
            if not outline_match or outline_status != "已确认" or not outline_content or outline_content in {"待定", "待知识准备后按原写作流程确定"}:
                errors.append(f"交付前文章知识需求的大纲必须非空且标记“已确认”：{request_path}")

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
    claim_index = formal_claim_index(root)
    required_metadata = {
        "文章ID": None,
        "文章版本": None,
        "资料视图": "写作素材包",
        "资料版本": None,
        "生成日期": None,
        "目标语言": None,
        "对应大纲": None,
        "使用对象": None,
    }
    for material_path in task_root.rglob("30_本篇知识库资料.md"):
        if "90_归档" in material_path.parts:
            continue
        material_text = material_path.read_text(encoding="utf-8-sig")
        audit_path = material_path.with_name("35_写作素材来源索引.md")
        if parse_field(material_text, "资料视图") != "写作素材包":
            warnings.append(f"文章仍使用旧审计混合资料包，建议后续重建30/35文件对：{material_path}")
            continue

        for field, expected in required_metadata.items():
            value = parse_field(material_text, field)
            if not value:
                errors.append(f"30写作素材包缺少固定元数据“{field}”：{material_path}")
            elif expected is not None and value != expected:
                errors.append(f"30写作素材包{field}必须为“{expected}”：{material_path}")

        if not audit_path.is_file():
            legacy_path = material_path.with_name("25_文章证据与审核包.md")
            if legacy_path.is_file():
                warnings.append(f"文章仍使用旧25/30文件对；当前版本保持可读，后续实质修改时升级为30/35：{material_path.parent}")
                continue
            errors.append(f"新写作素材包缺少35_写作素材来源索引.md：{material_path.parent}")
            continue
        audit_text = audit_path.read_text(encoding="utf-8-sig")
        required_audit_metadata = {
            "文章ID": None,
            "文章版本": None,
            "索引版本": None,
            "生成日期": None,
            "对应写作素材": None,
            "写作素材SHA-256": None,
            "用途": None,
        }
        for field in required_audit_metadata:
            if not parse_field(audit_text, field):
                errors.append(f"35来源索引缺少固定元数据“{field}”：{audit_path}")
        if not re.search(r"^#\s+本篇写作素材包\s*$", material_text, re.MULTILINE):
            errors.append(f"30文件标题必须为“本篇写作素材包”：{material_path}")
        for heading in required_material_headings:
            if not re.search(rf"^##\s+{re.escape(heading)}\s*$", material_text, re.MULTILINE):
                errors.append(f"30写作素材包缺少固定章节“{heading}”：{material_path}")
        for heading in (
            "二、可直接采用的英文表达",
            "三、可使用的数据表",
            "四、按大纲使用",
            "六、缺少资料的章节及建议处理方式",
        ):
            section_match = re.search(
                rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
                material_text,
                re.MULTILINE,
            )
            section_body = section_match.group(1).strip() if section_match else ""
            explicitly_empty = bool(re.fullmatch(r"(?:[-*]\s*)?无[。.]?", section_body))
            if section_body and not explicitly_empty and not table_headers(section_body):
                errors.append(f"30写作素材包“{heading}”必须使用模板表格，或明确写“无”：{material_path}")
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
            mapping_ranges: list[tuple[int, int]] = []
            mapped_claim_ids: set[str] = set()
            for row_text in mapping_body.splitlines():
                row_text = row_text.strip()
                if not row_text.startswith("|"):
                    continue
                cells = [cell.strip() for cell in row_text.strip("|").split("|")]
                # Skip the header/separator and tolerate non-table prose in this section.
                if len(cells) < 7 or not cells[0].isdigit() or not cells[1].isdigit():
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", cells[3]):
                    continue
                start, end = int(cells[0]), int(cells[1])
                claim_id = cells[3]
                mapped_claim_ids.add(claim_id)
                formal_ref = cells[5]
                clean_ref = formal_ref.strip()
                if clean_ref.startswith("[[") and clean_ref[-2:] == "]]":
                    clean_ref = clean_ref[2:-2]
                clean_ref = clean_ref.split("|", 1)[0].strip()
                if claim_id not in claim_index:
                    errors.append(f"35映射引用的Formal Claim不存在：{claim_id}（{audit_path}）")
                if not clean_ref or not clean_ref.lower().endswith(".md"):
                    errors.append(f"35映射必须指向具体正式知识.md文件，不能只写目录：{audit_path}（{claim_id}）")
                else:
                    formal_path = (audit_path.parent / clean_ref).resolve() if clean_ref.startswith(".") else (root / clean_ref).resolve()
                    if not formal_path.is_file():
                        errors.append(f"35映射引用的正式知识文件不存在：{formal_ref}（{audit_path}）")
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
            prewrite_path = material_path.with_name("20_文章前知识审核.md")
            if prewrite_path.is_file():
                declared = parse_field(
                    prewrite_path.read_text(encoding="utf-8-sig"), "可用Claim数"
                )
                if not declared.isdigit() or int(declared) != len(mapped_claim_ids):
                    errors.append(
                        f"20可用Claim数与35唯一Formal Claim数不一致："
                        f"声明={declared or '缺失'}，映射={len(mapped_claim_ids)}（{material_path.parent}）"
                    )

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
        if receipt.is_file():
            receipt_text = receipt.read_text(encoding="utf-8-sig")
            disposition_file = parse_field(receipt_text, "unsupported归组处置文件")
            try:
                unsupported_count = int(metric.get("unsupported_claims", "0") or 0)
            except ValueError:
                unsupported_count = 0
            if unsupported_count > 0:
                if not disposition_file:
                    warnings.append(f"既有Faithfulness记录未使用unsupported归组处置合同：{receipt}")
                else:
                    if disposition_file.startswith(("不适用", "等待结果", "未导入")):
                        errors.append(f"Faithfulness存在unsupported但没有有效归组处置文件：{receipt}")
                    header, rows = markdown_table(receipt, "## 三、未被本次知识附件覆盖的内容")
                    if not rows or tuple(header) not in {
                        FAITHFULNESS_DISPOSITION_HEADER,
                        LEGACY_FAITHFULNESS_DISPOSITION_HEADER,
                    }:
                        errors.append(f"Faithfulness记录缺少unsupported归组结果表：{receipt}")
                    elif tuple(header) == LEGACY_FAITHFULNESS_DISPOSITION_HEADER:
                        warnings.append(f"既有Faithfulness记录仍使用合并的处理结果与入口列：{receipt}")
                    if "单篇观察，不自动处理" in receipt_text:
                        errors.append(f"Faithfulness记录仍把unsupported默认写成单篇观察：{receipt}")
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

REPORT_NO_ITEM_MARKERS = (
    "无未完成事项", "无待外部调研事项", "无未关闭知识缺口", "无开放处理单",
)
REPORT_LEDGER_SPECS = {
    "MAT": ("05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md", "## 当前事项", "暂不处理", "已处理"),
    "CUS": ("05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md", "## 当前事项", "无需询问", "已完成"),
    "ANM": ("05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md", "## 当前异常", "已解决", "已完成处置（原文未修复）"),
    "SKFB": ("05_数据与审核/30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md", "## 当前反馈", "已关闭", "转为项目问题", "不纳入Skill"),
}


def _open_report_items(root: Path, *, handoff: bool) -> dict[str, list[str]]:
    """Read current ledger rows so reports cannot claim a clean state from memory."""
    result: dict[str, list[str]] = {}
    for kind, spec in REPORT_LEDGER_SPECS.items():
        path, heading, *terminal = spec
        table = current_table(root / path, heading)
        if table is None:
            result[kind] = []
            continue
        headers = list(table["header"])
        status_name = "当前阶段"
        status_index = headers.index(status_name) if status_name in headers else -1
        ids: list[str] = []
        for row in table["rows"]:
            if not row or row[0].strip().startswith("["):
                continue
            item_id = row[0].strip()
            status = row[status_index].strip() if 0 <= status_index < len(row) else ""
            if item_id and status not in terminal:
                ids.append(item_id)
        result[kind] = ids

    gap_path = root / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
    gap_ids: list[str] = []
    if gap_path.is_file():
        try:
            with gap_path.open("r", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    if row.get("status", "").strip() in {"观察中", "待外部调研"}:
                        key = row.get("gap_key", "").strip()
                        topic = row.get("gap_topic", "").strip()
                        if key:
                            gap_ids.append(key)
                        elif topic:
                            gap_ids.append(topic)
        except (OSError, csv.Error):
            pass
    result["知识缺口"] = gap_ids
    return result


def _report_section(text: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^###\s+{re.escape(heading)}[^\r\n]*\r?$([\s\S]*?)(?=^###\s+|^##\s+|\Z)",
        text,
    )
    return match.group(1) if match else ""


def _check_report_snapshot(path: Path, text: str, open_items: dict[str, list[str]], *, handoff: bool) -> None:
    headings = {kind: ("知识缺口" if handoff else "知识缺口（仅需当前行动）") if kind == "知识缺口" else kind for kind in (*REPORT_LEDGER_SPECS, "知识缺口")}
    for kind, item_ids in open_items.items():
        section = _report_section(text, headings[kind])
        if not section:
            raise ValueError(f"报告缺少{kind}汇总小节：{path}")
        missing = [item_id for item_id in item_ids if item_id not in section]
        has_no_item = any(marker in section for marker in REPORT_NO_ITEM_MARKERS)
        if item_ids:
            if has_no_item:
                raise ValueError(f"报告{kind}仍写无未完成事项，但当前台账有开放事项：{path}")
            if missing:
                raise ValueError(f"报告{kind}未逐项汇总当前开放事项：{', '.join(missing)}（{path}）")
        elif not has_no_item:
            raise ValueError(f"报告{kind}没有开放事项时必须明确写无未完成事项：{path}")


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

    monthly_open_items = _open_report_items(root, handoff=False)
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
            if "#### 本月SKFB维护复核（只读）" not in text:
                errors.append(f"月度审核缺少本月SKFB维护复核小节：{path}")
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
        try:
            _check_report_snapshot(path, text, monthly_open_items, handoff=False)
        except ValueError as exc:
            errors.append(str(exc))
    handoff_open_items = _open_report_items(root, handoff=True)
    for path in review_root.glob("*_项目交接审核.md"):
        text = path.read_text(encoding="utf-8-sig")
        conclusion = parse_field(text, "结论")
        if conclusion not in {"可以交接", "补充后交接", "暂不能交接"}:
            errors.append(f"项目交接结论无效：{path}")
        for label in ("### CUS", "### ANM", "### MAT", "### SKFB"):
            if label not in text:
                errors.append(f"项目交接缺少 {label}：{path}")
        check_problem_sheet_links(path, text)
        try:
            _check_report_snapshot(path, text, handoff_open_items, handoff=True)
        except ValueError as exc:
            errors.append(str(exc))


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v06-claim-check-test-") as temp:
        root = Path(temp)
        external = root / "03_正式知识/20_外部公共知识/50_行业知识与洞察/选型原则.md"
        customer = root / "03_正式知识/10_客户知识/20_产品介绍/测试产品.md"
        external.parent.mkdir(parents=True)
        customer.parent.mkdir(parents=True)
        external.write_text(
            """# 外部公共知识

- Claim ID：CLM-EXT-DEMO-SELECT-001
- Claim：External selection principle.
- 适用范围：公开行业知识
- 来源类型：外部公共来源
- 来源链接：https://example.invalid/source
- 精确位置：第1段
- 日期或版本：2026-08-26
- 使用边界：不得外推为客户事实
- 状态：可用
- 原文证据：RES-DEMO-20260826-001/10_来源原文证据.md
- 调研核验：RES-DEMO-20260826-001/20_调研核验记录.md
- 归类模块：外部公共知识
- 归类依据：本条说明可复用的公开选型原则，不陈述客户能力或产品规格。

### 最小原文证据

> External source text.
""",
            encoding="utf-8",
        )
        customer.write_text(
            """# 客户知识

- Claim ID：CLM-DEMO-SELECT-004
- Claim：Customer fact.
- 适用范围：项目级
- 来源类型：客户源文件
- 来源链接：客户原始资料
- 精确位置：第1页
- 日期或版本：2026-08-26
- 归类模块：产品介绍
- 归类依据：本条主要说明客户产品本身的已核验属性，不涉及交付流程或服务方法。
- 使用边界：仅限客户资料明确范围
- 状态：可用

### 最小原文证据

> Customer source text.
""",
            encoding="utf-8",
        )
        claim_errors: list[str] = []
        claim_warnings: list[str] = []
        validate_claims(root, claim_errors, claim_warnings)
        validate_external_claim_links(root, claim_errors)
        if claim_errors:
            print(json.dumps({"ok": False, "stage": "valid-claim-evidence-and-namespaces", "errors": claim_errors}, ensure_ascii=False))
            return 1

        external.write_text(external.read_text(encoding="utf-8").replace(
            "CLM-EXT-DEMO-SELECT-001", "CLM-EXT-DEMO-SELECT-003", 1
        ).replace(
            "> External source text.", "External source text.", 1
        ), encoding="utf-8")
        invalid_claims: list[str] = []
        invalid_warnings: list[str] = []
        validate_claims(root, invalid_claims, invalid_warnings)
        validate_external_claim_links(root, invalid_claims)
        expected_claim_errors = ("最小原文证据", "编号不连续")
        if not all(any(fragment in item for item in invalid_claims) for fragment in expected_claim_errors):
            print(json.dumps({"ok": False, "stage": "invalid-claim-evidence-and-sequence", "errors": invalid_claims}, ensure_ascii=False))
            return 1

    with tempfile.TemporaryDirectory(prefix="v06-governance-check-test-") as temp:
        root = Path(temp)
        audit = root / "04_文章任务/10_进行中/DEMO-ART-001_检测测试/20_文章前知识审核.md"
        audit.parent.mkdir(parents=True)
        valid_audit = f"""# 文章前知识审核

- 文章ID：DEMO-ART-001
- 文章版本：v1
- 审核模板版本：{ARTICLE_AUDIT_TEMPLATE_VERSION}
- 审核日期：2026-08-26
- 结论：带明确排除通过

## 大纲知识覆盖检查

| 大纲章节 | 知识问题 | 覆盖状态 | 已有证据/Claim | 缺口或治理事项 | 本篇处理 |
|---|---|---|---|---|---|
| 采购标准 | 当前公共选型标准是什么 | 未覆盖 | 无 | gap_key: uv-vis-selection | 缩小为一般性说明 |
| 总结 | 无独立事实问题 | 无需事实支持 | 不适用 | 不构成知识问题：结构总结 | 保留结构总结 |

## 知识准备充分性复核

| 大纲章节 | 候选事实数 | 已沉淀Claim数 | 计划纳入30的事实块数 | 覆盖结论 | 未采用事实/缺口及入口 |
|---|---:|---:|---:|---|---|
| 标题 | 1 | 1 | 1 | 有明确边界 | 无 |
| 主问题 | 0 | 0 | 0 | 无需事实支持 | 无；结构性问题 |
| 采购标准 | 0 | 0 | 0 | 有明确边界 | gap_key: uv-vis-selection |

## CUS / ANM检测结果

| 检测对象 | 已检查信号与来源 | 分类结论 | 事项与证据入口 | 本篇处理 |
|---|---|---|---|---|
| CUS候选检测 | 已检查客户能力、规格、认证、案例、商业条件、公开授权，以及Formal Claim、本地索引和官网 | 未触发 | 无 | 不新增客户事实 |
| ANM异常检测 | 已检查版本、定位、数值单位、OCR、冲突和外推 | 未触发 | 无 | 按现有核验事实使用 |
"""
        audit.write_text(valid_audit, encoding="utf-8")
        governance_errors: list[str] = []
        governance_warnings: list[str] = []
        validate_article_governance_checks(root, governance_errors, governance_warnings)
        if governance_errors or governance_warnings:
            print(json.dumps({"ok": False, "stage": "valid-governance-detection", "errors": governance_errors, "warnings": governance_warnings}, ensure_ascii=False))
            return 1
        audit.write_text(valid_audit.replace("gap_key: uv-vis-selection", "无", 1), encoding="utf-8")
        invalid_governance: list[str] = []
        validate_article_governance_checks(root, invalid_governance, [])
        if not any("未关联gap_key/CUS/MAT/ANM" in item for item in invalid_governance):
            print(json.dumps({"ok": False, "stage": "invalid-unclassified-outline-gap", "errors": invalid_governance}, ensure_ascii=False))
            return 1

    relative = Path(str(LEDGER_RULES["MAT"]["path"]))
    with tempfile.TemporaryDirectory(prefix="v06-validator-test-") as temp:
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
            "## 反馈详情\n\n### DEMO-SKFB-001｜表格结构未校验\n\n- 当前阶段：已纳入维护\n- 关闭条件：Skill专项自测和受影响项目验证均通过\n- 重开条件：同一校验遗漏再次复现\n",
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
        formal_demo = root / "03_正式知识/demo.md"
        formal_demo.parent.mkdir(parents=True, exist_ok=True)
        formal_demo.write_text(
            "# Demo正式知识\n\n- Claim ID：CLM-DEMO-001\n- Claim标题：Demo fact\n",
            encoding="utf-8",
        )
        (valid_task / "10_文章知识需求.md").write_text(
            f"# 文章知识需求\n\n- 文章ID：{article_id}\n- 当前版本：v1\n"
            "- 文章标题：测试文章\n- 目标语言：中文\n- 关键词：测试\n\n"
            "## 大纲\n\n- 大纲状态：已确认\n\n测试文章的基本组织方向。\n",
            encoding="utf-8",
        )
        (valid_task / "15_检索与知识准备记录.md").write_text(
            f"# 检索与知识准备记录\n\n- 文章ID：{article_id}\n- 文章版本：v1\n", encoding="utf-8"
        )
        (valid_task / "20_文章前知识审核.md").write_text(
            f"# 文章前知识审核\n\n- 文章ID：{article_id}\n- 文章版本：v1\n"
            "- 结论：自动通过\n- 可用Claim数：1\n", encoding="utf-8"
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
            "| 23 | 23 | Demo | CLM-DEMO-001 | Demo fact | [[../../../03_正式知识/demo.md]] | demo.pdf p.1 |\n\n"
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
            "- 执行Skill：manage-article-knowledge v0.6\n"
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
    with tempfile.TemporaryDirectory(prefix="v06-mat-lifecycle-test-") as temp:
        root = Path(temp)
        source_dir = root / "02_源资料"
        source_dir.mkdir(parents=True)
        database = source_dir / "source-index.sqlite"
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE sources (source_id TEXT, duplicate_of TEXT, mat_candidate TEXT, mat_id TEXT, mat_disposition TEXT)"
        )
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?)",
            ("SRC-MAT-001", "", "建议建立MAT", "DEMO-MAT-001", "已建立正式MAT：DEMO-MAT-001"),
        )
        connection.commit()
        connection.close()
        (source_dir / "源资料与可检索性台账.md").write_text(
            "# 源资料与可检索性台账\n\n"
            "| 资料ID | 原始相对路径 | MAT | MAT处置说明 |\n"
            "|---|---|---|---|\n"
            "| SRC-MAT-001 | materials/sample.zip | DEMO-MAT-001 | 已建立正式MAT：DEMO-MAT-001 |\n",
            encoding="utf-8",
        )
        mat_path = root / relative
        mat_path.parent.mkdir(parents=True)
        mat_path.write_text(
            "# 源资料处理台账\n\n## 当前事项\n\n"
            "| MAT ID | 事项名称 | 代表文件/资料范围 | 资料数量 | 通俗问题 | 当前文章影响 | 当前阶段 | 下一责任人/动作 | 重开条件 | 详情入口 | 最近更新 | 是否有当前文章依赖 | 是否阻塞当前文章 | 内容运营推送状态 |\n"
            "|---|---|---|---:|---|---|---|---|---|---|---|---|---|---|\n"
            "| DEMO-MAT-001 | 压缩包资料核验 | sample.zip（materials/sample.zip） | 1 | 需要核验压缩包成员 | 当前文章受影响 | 等待材料或工具 | 内容运营确认可用成员 | 新文章命中或文件变化 | [[#DEMO-MAT-001｜压缩包资料核验]] | 2026-08-26 | 是 | 是 | 待推送 |\n\n"
            "## 事项详情\n\n### DEMO-MAT-001｜压缩包资料核验\n\n"
            "- 代表文件/资料范围：sample.zip（materials/sample.zip）\n"
            "- 资料数量：1\n- 为什么合并为一项：同一处理原因、责任人和关闭条件。\n"
            "- 下一责任人/动作：内容运营确认可用成员\n- 重开条件：新文章命中或文件变化\n",
            encoding="utf-8",
        )
        todo = root / "01_工作台/20_当前待办.md"
        todo.parent.mkdir(parents=True)
        todo.write_text("# 当前待办\n\n- DEMO-MAT-001：等待内容运营确认可用成员。\n", encoding="utf-8")
        problem = root / "04_文章任务/10_进行中/DEMO-ART-001_测试/文章前问题与处理单.md"
        problem.parent.mkdir(parents=True)
        problem.write_text(
            "# 文章前问题与处理单\n\n- 当前状态：等待人工处理\n"
            "- 关联MAT：DEMO-MAT-001\n- 当前待办：[[../../../01_工作台/20_当前待办.md]]\n",
            encoding="utf-8",
        )
        lifecycle_errors: list[str] = []
        lifecycle_warnings: list[str] = []
        validate_mat_lifecycle(root, lifecycle_errors, lifecycle_warnings)
        if lifecycle_errors:
            print(json.dumps({"ok": False, "stage": "valid-mat-push-gate", "errors": lifecycle_errors}, ensure_ascii=False))
            return 1
        todo.write_text("# 当前待办\n", encoding="utf-8")
        invalid_lifecycle: list[str] = []
        validate_mat_lifecycle(root, invalid_lifecycle, [])
        if not any("当前待办没有对应入口" in item for item in invalid_lifecycle):
            print(json.dumps({"ok": False, "stage": "invalid-mat-push-gate", "errors": invalid_lifecycle}, ensure_ascii=False))
            return 1

    with tempfile.TemporaryDirectory(prefix="v06-website-monthly-test-") as temp:
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
            "### MAT\n\n- 无未完成事项\n\n### CUS\n\n- 无未完成事项\n\n### ANM\n\n- 无未完成事项\n\n### SKFB\n\n- 无未完成事项\n\n### 知识缺口（仅需当前行动）\n\n- 无未完成事项\n\n"
            "#### 本月SKFB维护复核（只读）\n\n"
            "| 复核范围 | 本月新增 | 已完成Skill专项自测 | 待原复现项目验证 | 已关闭 | 重新打开/阶段不一致 | 复核依据 |\n"
            "|---|---:|---:|---:|---:|---|---|\n"
            "| 以本项目SKFB台账为准 | 0 | 0 | 0 | 0 | 无 | manage_skill_feedback.py --audit |\n"
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
    if base.is_file() and "manage-article-knowledge v0.6" not in base.read_text(encoding="utf-8-sig"):
        errors.append("项目基础信息未声明manage-article-knowledge v0.6")

    metrics_path = root / "05_数据与审核/10_Faithfulness/10_文章Faithfulness明细.csv"
    support_path = root / "05_数据与审核/10_Faithfulness/20_Claim文章支撑记录.csv"
    gap_path = root / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
    writing_import_path = root / "05_数据与审核/50_运行记录/10_写作任务接入记录.csv"
    metrics = load_metrics(metrics_path, errors)
    check_csv_schema(support_path, SUPPORT_FIELDS, errors)
    validate_knowledge_gaps(gap_path, errors)
    validate_writing_task_imports(writing_import_path, errors)
    integration = validate_integration_config(
        root / "01_工作台/40_写作与Faithfulness接入配置.md"
    )
    errors.extend(f"接入配置：{item}" for item in integration["errors"])
    warnings.extend(f"接入配置：{item}" for item in integration["warnings"])
    validate_index(root, errors, warnings)
    validate_source_exclusions(root, errors, warnings)
    validate_version_entry(root, errors, warnings)
    validate_project_profile(root, errors, warnings)
    validate_competitor_policy(root, errors, warnings)
    validate_layout(root, errors, warnings, strict_coverage=args.completion_gate)
    validate_version_archives(root, errors)
    validate_token_usage(root, errors)
    validate_claims(root, errors, warnings)
    validate_external_claim_links(root, errors, warnings)
    validate_ledgers(root, errors)
    validate_feedback_details(root, errors)
    for markdown_path in root.rglob("*.md"):
        if any(part in {".obsidian", ".git", "90_归档"} for part in markdown_path.parts):
            continue
        errors.extend(table_continuity_errors(markdown_path))
    validate_retrieval_records(root, errors)
    errors.extend(f"受管模板：{item}" for item in validate_project_templates(root))
    validate_article_governance_checks(root, errors, warnings, metrics)
    validate_source_references(root, errors)
    validate_mat_dependencies(root, errors)
    validate_mat_lifecycle(root, errors, warnings)
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
