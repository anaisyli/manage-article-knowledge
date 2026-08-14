#!/usr/bin/env python3
"""Validate v0.4 Obsidian projects before writing input, deposition, or closure."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import unquote


UTF8_BOM = b"\xef\xbb\xbf"


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

SOURCE_ANOMALY_RELATIVE = Path(
    "05_数据与审核/30_异常与待决定/10_企业知识异常待处理/02_源文与事实异常台账.md"
)

MATERIAL_TODO_RELATIVE = Path(
    "05_数据与审核/30_异常与待决定/10_企业知识异常待处理/03_源资料处理待办.md"
)

SOURCE_REGISTER_RELATIVE = Path("04_资料与证据/10_源文件登记/01_源文件总表.md")
CONTENT_NAV_DIR_RELATIVE = Path("04_资料与证据/10_源文件登记/20_内容导航")
CONTENT_NAV_HEADERS = (
    "位置",
    "原始标题路径",
    "内容说明",
    "语言",
    "带文字的表格、图示或特殊结构",
    "提取状态",
    "可能归属模块",
    "定位限制",
)
CONTENT_NAV_PLACEHOLDER_PATTERNS = (
    re.compile(r"\{\s*likely_modules\s*\(") ,
    re.compile(r"\{\{[^}\n]+\}\}"),
    re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*"),
)
CONTENT_NAV_GENERIC_CONTENT = (
    "初始化仅建立页面/章节导航",
    "待文章定向提取",
    "标题路径待文章定向处理",
    "字段与行列关系初始化登记",
    "内容待定",
    "页内语义待定",
)

WORKBENCH_TODO_RELATIVE = Path("01_工作台/20_当前待办.md")
VERSION_ENTRY_RELATIVE = Path("01_工作台/30_版本与变更入口.md")
CHECK_ENTRY_RELATIVE = Path("05_数据与审核/01_检查入口/01_当前待办.md")
SKILL_FEEDBACK_RELATIVE = Path(
    "05_数据与审核/30_异常与待决定/30_Skill运行反馈/01_Skill反馈台账.md"
)

RUN_LEDGER_RELATIVE = Path("90_归档/20_项目运行历史/项目运行账本.jsonl")
RUN_LEDGER_REQUIRED_FIELDS = {
    "schema_version",
    "run_id",
    "project_id",
    "task",
    "status",
    "started_at",
    "ended_at",
    "skill",
    "inputs",
    "read_files",
    "tool_calls",
    "outputs",
    "retry_count",
    "failure_stage",
    "human_intervention",
    "usage",
}
RUN_LEDGER_STATUSES = {"success", "partial", "failed", "blocked"}

DATA_EXPLANATION_RELATIVE = Path(
    "05_数据与审核/20_知识使用与引用/01_数据说明.md"
)

DATA_EXPLANATION_HEADERS = (
    "文件",
    "类型",
    "用途",
    "维护责任",
    "是否允许人工编辑",
    "更新触发",
    "查看方式",
    "编码/格式",
    "最近校验",
)

IGNORED_VAULT_DIRS = {".obsidian", ".git", ".trash"}
IGNORED_VAULT_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
FORBIDDEN_RUNTIME_DIRS = {
    "scripts",
    "cache",
    "temp",
    "tmp",
    ".cache",
    ".temp",
    ".tmp",
    "__pycache__",
    "node_modules",
}
FORBIDDEN_RUNTIME_SUFFIXES = {".py", ".pyc", ".pyo", ".tmp", ".temp", ".swp"}

CUSTOMER_REQUEST_HEADERS = (
    "问题ID",
    "想向客户确认什么",
    "为什么需要",
    "回复前怎么处理",
    "当前阶段",
    "下一步由谁做",
    "最近更新",
)

CUSTOMER_REQUEST_STAGES = {
    "待判断要不要问",
    "无需询问",
    "准备客户话术",
    "等待发送",
    "等待客户回复",
    "收到回复，待核实",
    "已完成",
}

SOURCE_ANOMALY_HEADERS = (
    "异常ID",
    "通俗说明",
    "原文是否修复",
    "现在怎么处理",
    "当前阶段",
    "谁需要做什么",
    "下一步或重开条件",
)

SOURCE_REPAIR_STATES = {"未修复", "部分修复", "已修复", "无法判断"}

SOURCE_ANOMALY_STAGES = {
    "待判断",
    "等待材料",
    "处理中",
    "部分解决",
    "已解决",
    "已完成处置（原文未修复）",
}

SOURCE_EVIDENCE_COMPLETENESS = {"完整", "截断片段", "仅截图", "无法取得完整正文"}
SOURCE_EVIDENCE_TYPES = {"逐字文本", "原表", "原公式", "页面截图", "音视频时间码"}

MATERIAL_TODO_HEADERS = (
    "事项ID",
    "资料ID",
    "资料与问题",
    "触发原因",
    "当前阶段",
    "AI知识库专员决定",
    "下一步",
    "最近更新",
)

MATERIAL_TODO_STAGES = {
    "待专员判断",
    "等待处理条件",
    "待处理",
    "处理中",
    "处理稿待核验",
    "已处理可复用",
    "暂不处理",
    "无法处理，保留登记",
}

SOURCE_RELATIONS_WITH_TARGET = {
    "完全重复副本",
    "疑似旧版",
    "疑似新版",
    "版本关系未确认",
    "内容部分重合",
}
SOURCE_RELATIONS_STANDALONE = {"主文件", "独立资料"}

SKILL_FEEDBACK_HEADERS = (
    "反馈ID",
    "人话说明",
    "提出来源",
    "类型",
    "当前阶段",
    "影响",
    "下一步",
    "最近更新",
)

SKILL_FEEDBACK_ORIGINS = {"Codex自动发现", "人工提出"}
SKILL_FEEDBACK_TYPES = {"缺陷", "规则歧义", "校验遗漏", "模板与可读性", "流程改进", "环境兼容"}
SKILL_FEEDBACK_STAGES = {
    "自动记录，待维护判断",
    "人工提出，待维护判断",
    "已纳入维护",
    "维护中",
    "已修复，待项目验证",
    "已关闭",
    "转为项目问题",
    "不纳入Skill",
}

FORMAL_REQUIRED_DIRS = (
    "02_正式知识/20_产品介绍/10_产品类目",
    "02_正式知识/20_产品介绍/20_产品主数据",
    "02_正式知识/20_产品介绍/30_重点产品卡",
    "02_正式知识/50_行业知识与洞察/10_企业提供",
    "02_正式知识/50_行业知识与洞察/20_Codex外部调研",
)

FORMAL_TYPE_DIRS = {
    "产品类目": "02_正式知识/20_产品介绍/10_产品类目/",
    "产品主数据": "02_正式知识/20_产品介绍/20_产品主数据/",
    "重点产品卡": "02_正式知识/20_产品介绍/30_重点产品卡/",
    "行业知识": "02_正式知识/50_行业知识与洞察/",
}

FORMAL_TYPES = {
    "公司概述",
    "产品类目",
    "产品主数据",
    "重点产品卡",
    "解决方案",
    "合作案例",
    "行业知识",
    "FAQ",
    "其他",
}

FORMAL_FILE_FIELDS = (
    "知识ID",
    "正式知识类型",
    "知识状态",
    "来源类型",
    "数据或版本日期",
    "最近核验日期",
    "使用前复核",
)

FORMAL_CLAIM_FIELDS = (
    "知识ID",
    "知识类型",
    "适用范围",
    "不可外推",
    "来源",
    "精确位置",
    "数据日期",
    "使用前复核",
)

CANDIDATE_RELATIVE = Path("05_数据与审核/10_知识沉淀与分流/10_知识候选分流.md")
DEPOSITION_STATE_RELATIVE = Path("05_数据与审核/10_知识沉淀与分流/20_知识沉淀记录.md")
DEPOSITION_EVENT_RELATIVE = Path("05_数据与审核/10_知识沉淀与分流/40_正式知识沉淀记录.csv")
CLAIM_USAGE_DETAIL_RELATIVE = Path("05_数据与审核/20_知识使用与引用/20_知识块使用明细.csv")
CLAIM_USAGE_TOTAL_RELATIVE = Path("05_数据与审核/20_知识使用与引用/30_知识块使用总表.md")
CLAIM_MANIFEST_DIR_RELATIVE = Path("05_数据与审核/20_知识使用与引用/40_文章引用清单")

CANDIDATE_HEADERS = (
    "候选ID",
    "内容主题",
    "来源类型",
    "就绪来源文件",
    "原文精确位置",
    "稳定实体/主题键",
    "主归属模块",
    "预定正式路径",
    "CLAIM数量",
    "处理状态",
    "校验结果/异常",
    "正式知识ID或处理位置",
    "最近更新",
)

CANDIDATE_GATE_HEADERS = (
    "候选ID",
    "范围确认文件",
    "范围版本",
    "批准范围ID",
    "文章前审核文件",
    "文章前审核状态",
    "原文证据状态",
    "网页交互覆盖",
    "表格完整性",
    "源语言清理状态",
    "独立审核状态",
    "知识沉淀就绪",
)

SCOPE_RANGE_HEADERS = (
    "范围ID",
    "资料ID与名称",
    "原文件/运营稿/网页直达链接",
    "原始语言",
    "精确位置",
    "该位置实际包含什么",
    "拟提取主题与字段",
    "附件/图片/复杂结构",
    "处理样本组",
    "排除范围",
    "输出位置",
)

SCOPE_WEB_HEADERS = (
    "状态ID",
    "页面/表格",
    "控件名称",
    "切换动作",
    "状态标识或结果指纹",
    "完整表头",
    "文章相关完整行数",
    "单位",
    "脚注",
    "原文证据位置",
    "取得状态",
)

CANDIDATE_STATUSES = {
    "待核验",
    "可自动沉淀",
    "部分可沉淀",
    "异常待处理",
    "已沉淀",
    "不沉淀",
}

CLAIM_USAGE_HEADERS = (
    "project_id",
    "article_id",
    "article_title",
    "article_version",
    "claim_id",
    "knowledge_id",
    "knowledge_title",
    "knowledge_path",
    "article_location",
    "source_location",
    "use_type",
    "usage_status",
    "confirmed_at",
    "issue_flag",
    "citation_manifest",
)

CLAIM_USAGE_STATUSES = {"尚未核对", "已确认使用", "未使用", "未追踪"}

CLAIM_TOTAL_HEADERS = (
    "CLAIM ID",
    "所属正式知识ID",
    "标题",
    "正式知识位置",
    "来源类型",
    "已确认使用文章",
    "累计使用次数",
    "尚未核对文章数",
    "最近使用日期",
    "异常数",
    "当前追踪状态",
)

CLAIM_MANIFEST_HEADERS = (
    "文章位置/主张",
    "CLAIM ID",
    "所属正式知识ID",
    "正式知识位置",
    "原始来源与精确位置",
    "使用方式",
    "使用判断",
    "异常处理",
)

DEPOSITION_STATE_HEADERS = (
    "知识ID",
    "稳定实体或主题键",
    "标题",
    "来源类型",
    "原始来源",
    "处理状态",
    "主归属模块",
    "正式知识位置",
    "数据或版本日期",
    "更新条件",
    "使用限制或待决定事项",
    "最近更新日期",
)

DEPOSITION_EVENT_HEADERS = (
    "date",
    "knowledge_id",
    "claim_ids",
    "entity_key",
    "action",
    "formal_file",
    "heading",
    "source_refs",
    "source_ready_artifact",
    "status",
    "operator",
    "notes",
)

RUNTIME_CHECKLIST_RELATIVE = Path("references/runtime-execution-checklist.md")
AGENT_ORCHESTRATION_RELATIVE = Path("references/multi-agent-orchestration.md")
RUNTIME_CHECKLIST_HEADINGS = (
    "## 1. 每一阶段都执行的内部规则",
    "## 2. 打开已有项目或初始化",
    "## 3. 接收文章需求与资料路由",
    "## 4. 资料就绪检查",
    "## 5. 范围与样本确认",
    "## 6. 提取、清理、翻译与候选准备",
    "## 7. 条件式外部调研",
    "## 8. 文章前审核、正式沉淀与写作输入",
    "## 9. 写作后闭环、维护与反馈",
    "## 10. 自动恢复与人工边界速查",
)


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


def skill_file(path: Path | None = None) -> Path:
    candidate = path if path is not None else Path(__file__).resolve().parent.parent
    return (candidate / "SKILL.md" if candidate.is_dir() else candidate).resolve()


def validate_skill_runtime_contract(skill_root: Path | None = None) -> list[str]:
    """Check the internal execution layer without creating operator-facing files."""
    root = (skill_root or Path(__file__).resolve().parent.parent).resolve()
    failures: list[str] = []
    main_skill = root / "SKILL.md"
    checklist = root / RUNTIME_CHECKLIST_RELATIVE
    orchestration = root / AGENT_ORCHESTRATION_RELATIVE

    for required in (main_skill, checklist, orchestration):
        if not required.is_file():
            failures.append(f"missing required runtime contract file: {required.relative_to(root).as_posix()}")
    if failures:
        return failures

    skill_text = read_text(main_skill)
    checklist_text = read_text(checklist)
    orchestration_text = read_text(orchestration)

    if "references/runtime-execution-checklist.md" not in skill_text:
        failures.append("SKILL.md does not route each stage through the internal runtime checklist")
    for phrase in ("不形成新的运营表单或人工确认节点", "自动修复并重检", "不得把机器可修复问题转交内容运营"):
        if phrase not in skill_text:
            failures.append(f"SKILL.md runtime rule missing: {phrase}")
    for heading in RUNTIME_CHECKLIST_HEADINGS:
        if heading not in checklist_text:
            failures.append(f"runtime checklist section missing: {heading}")
    for phrase in ("不复制到客户Obsidian项目", "不为清单新增Agent", "不提交人工确认", "运行项目校验并执行反馈信号检查"):
        if phrase not in checklist_text:
            failures.append(f"runtime checklist constraint missing: {phrase}")
    for role in ("主Agent", "资料处理Agent", "调研Agent", "审核Agent"):
        if role not in orchestration_text:
            failures.append(f"existing Agent role missing from orchestration: {role}")
    if "不增加第四个子Agent" not in orchestration_text:
        failures.append("orchestration no longer fixes the existing three-subagent boundary")
    return failures


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def normalize_sha256(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?i)\b[0-9a-f]{64}\b", value)
    return match.group(0).upper() if match else None


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


def markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def find_markdown_table(
    text: str,
    required_headers: tuple[str, ...],
) -> tuple[list[str], list[tuple[int, dict[str, str]]]] | None:
    """Return the first Markdown table whose header contains all required fields."""
    lines = text.splitlines()
    for index in range(len(lines) - 1):
        if not lines[index].lstrip().startswith("|") or not is_separator_row(lines[index + 1]):
            continue
        headers = markdown_cells(lines[index])
        if not all(header in headers for header in required_headers):
            continue
        rows: list[tuple[int, dict[str, str]]] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            cells = markdown_cells(lines[cursor])
            if len(cells) == len(headers) and any(cells):
                rows.append((cursor + 1, dict(zip(headers, cells))))
            cursor += 1
        return headers, rows
    return None


def validate_content_navigation(
    root: Path,
    source_rows_by_id: dict[str, tuple[int, dict[str, str]]],
    add: callable,
) -> None:
    """Reject structurally valid navigation that still contains template prose."""
    nav_dir = root / CONTENT_NAV_DIR_RELATIVE
    if not nav_dir.is_dir():
        if source_rows_by_id:
            add("ERROR", "MISSING_CONTENT_NAV_DIR", nav_dir, 0, "存在源文件登记，但缺少内容导航目录")
        return

    nav_files = sorted(nav_dir.glob("*.md"))
    nav_ids: set[str] = set()
    for nav_file in nav_files:
        text = read_text(nav_file)
        source_id = parse_field(text, "资料ID")
        if source_id:
            nav_ids.add(source_id)
        table = find_markdown_table(text, CONTENT_NAV_HEADERS)
        if table is None:
            add(
                "ERROR",
                "CONTENT_NAV_SCHEMA",
                nav_file,
                1,
                "内容导航必须包含位置、标题路径、内容说明和定位限制等固定字段",
            )
            continue

        _, rows = table
        for pattern in CONTENT_NAV_PLACEHOLDER_PATTERNS:
            match = pattern.search(text)
            if match:
                add(
                    "ERROR",
                    "CONTENT_NAV_PLACEHOLDER",
                    nav_file,
                    line_number(text, match.start()),
                    f"内容导航残留未替换变量：{match.group(0)}",
                )
                break

        source_row = source_rows_by_id.get(source_id or "")
        readable = bool(source_row and "可读取" in source_row[1].get("可读性", ""))
        source_name = (source_row[1].get("格式", "") if source_row else "").casefold()
        identity_only = source_name in {"mp4", "m4a", "mp3", "wav", "avi", "mov", "zip", "rar", "7z"} and not readable

        if not rows:
            add("ERROR", "CONTENT_NAV_EMPTY", nav_file, 1, "内容导航的内容位置表不能没有数据行")
            continue

        semantic_empty_reported = False
        generic_rows = 0
        first_generic_line = 0
        for row_line, row in rows:
            position = row.get("位置", "").strip()
            title_path = row.get("原始标题路径", "").strip()
            description = row.get("内容说明", "").strip()
            if not is_substantive(position) or not is_substantive(description):
                if not semantic_empty_reported:
                    add(
                        "ERROR",
                        "CONTENT_NAV_SEMANTIC_EMPTY",
                        nav_file,
                        row_line,
                        "内容导航数据行必须提供实际位置和内容说明，不能只登记格式或状态",
                    )
                    semantic_empty_reported = True
                continue
            generic_title = (
                title_path in {"页面主题待文章定向提取", "标题路径待文章定向处理", "内容待定"}
                or title_path.startswith("字段与行列关系初始化登记")
                or title_path.startswith("初始化登记，未提取正文")
                or (title_path == "未识别页标题" and "待文章定向提取" in description)
            )
            # A real title path is useful navigation even when extraction is
            # intentionally deferred. Only treat a generic description as a
            # placeholder when the row has no real semantic title/path.
            has_real_title_path = is_substantive(title_path) and not generic_title
            generic_description = (
                description in CONTENT_NAV_GENERIC_CONTENT
                or description.startswith("初始化仅建立页面/章节导航")
                or description in {"初始化登记，未提取正文", "初始化扫描，待文章需求"}
            )
            if generic_title or (generic_description and not has_real_title_path):
                generic_rows += 1
                if not first_generic_line:
                    first_generic_line = row_line
        if generic_rows and (generic_rows == len(rows) or len(rows) == 1):
            add(
                "ERROR",
                "CONTENT_NAV_GENERIC",
                nav_file,
                first_generic_line,
                "可读取资料的导航不能使用通用占位语句，必须写页面主题、标题路径、表区或字段大意",
            )

    for source_id, (_, row) in source_rows_by_id.items():
        nav_value = row.get("内容导航", "").strip()
        format_name = row.get("格式", "").casefold()
        identity_only = format_name in {"mp4", "m4a", "mp3", "wav", "avi", "mov", "zip", "rar", "7z"} and "可读取" not in row.get("可读性", "")
        if identity_only:
            continue
        if not nav_value or not has_clickable_link(nav_value):
            add("ERROR", "SOURCE_CONTENT_NAV_LINK", root / SOURCE_REGISTER_RELATIVE, 1, f"资料{source_id}缺少内容导航链接")
            continue
        if source_id not in nav_ids:
            add("ERROR", "SOURCE_CONTENT_NAV_FILE", root / SOURCE_REGISTER_RELATIVE, 1, f"资料{source_id}的内容导航文件不存在或缺少资料ID")


def has_clickable_link(value: str) -> bool:
    return bool(
        re.search(r"\[[^\]\n]+\]\((?:<[^>]+>|[^)\n]+)\)", value)
        or re.search(r"\[\[[^\]\n]+\]\]", value)
    )


def anomaly_detail(text: str, anomaly_id: str) -> str | None:
    match = re.search(
        rf"(?ms)^###\s+{re.escape(anomaly_id)}(?:｜[^\n]+)?\s*$\n(.*?)(?=^###\s+|^##\s+已完成处置与历史\s*$|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def material_detail(text: str, material_id: str) -> str | None:
    match = re.search(
        rf"(?ms)^###\s+{re.escape(material_id)}(?:｜[^\n]+)?\s*$\n(.*?)(?=^###\s+|^##\s+已完成、暂不处理与历史\s*$|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def customer_detail(text: str, request_id: str) -> str | None:
    match = re.search(
        rf"(?ms)^###\s+{re.escape(request_id)}(?:｜[^\n]+)?\s*$\n(.*?)(?=^###\s+|^##\s+|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def skill_feedback_detail(text: str, feedback_id: str) -> str | None:
    match = re.search(
        rf"(?ms)^###\s+{re.escape(feedback_id)}(?:｜[^\n]+)?\s*$\n(.*?)(?=^###\s+|^##\s+已关闭与不纳入\s*$|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def heading_body(text: str, heading_pattern: str) -> str | None:
    match = re.search(
        rf"(?ms)^#####\s+{heading_pattern}\s*$\n(.*?)(?=^####[#]?\s+|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def verbatim_body(text: str) -> str:
    fenced = [
        match.group(1).strip()
        for match in re.finditer(r"(?ms)^```(?:text)?\s*$\n(.*?)^```\s*$", text)
    ]
    quoted = [
        value.strip()
        for value in re.findall(r"(?m)^>\s*(.+)$", text)
        if not value.lstrip().startswith("[")
    ]
    return "\n".join(fenced + quoted).strip()


def unprotected_double_percent_lines(text: str) -> list[int]:
    result: list[int] = []
    fence_char: str | None = None
    fence_length = 0
    for number, line in enumerate(text.splitlines(), 1):
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
                fence_length = 0
            continue
        if fence_char is not None:
            continue
        without_inline_code = re.sub(r"`+[^`\n]*`+", "", line)
        if "%%" in without_inline_code:
            result.append(number)
    return result


def read_csv_rows(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [(line, {key: (value or "").strip() for key, value in row.items()}) for line, row in enumerate(reader, 2)]
    return headers, rows


def split_link_target(target: str) -> tuple[str, str | None]:
    target = target.strip().strip("<>")
    path, separator, anchor = target.partition("#")
    return unquote(path).strip(), unquote(anchor).strip() if separator else None


def resolve_markdown_link_target(source: Path, target: str, root: Path) -> Path | None:
    path, _ = split_link_target(target)
    if re.match(r"^(https?://|mailto:|obsidian://)", path, re.I):
        return None
    if not path:
        return source.resolve()
    normalized = path.replace("\\", "/")
    candidates = [source.parent / normalized, root.joinpath(*normalized.split("/"))]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.exists():
            return candidate
        markdown_candidate = candidate.with_suffix(".md")
        if not candidate.suffix and markdown_candidate.exists():
            return markdown_candidate
    return None


def build_basename_map(files: list[Path]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for file in files:
        result.setdefault(file.stem, []).append(file)
        if file.name != file.stem:
            result.setdefault(file.name, []).append(file)
    return result


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_ignored_vault_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return relative.name.lower() in IGNORED_VAULT_FILES or any(
        part.lower() in IGNORED_VAULT_DIRS for part in relative.parts[:-1]
    )


def iter_link_targets(text: str) -> list[str]:
    targets = [
        match.group(1).strip()
        for match in re.finditer(r"!?\[[^\]\n]*\]\((<[^>]+>|[^)\n]+)\)", text)
    ]
    targets.extend(
        match.group(1).strip()
        for match in re.finditer(r"!?\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text)
    )
    return targets


def resolve_vault_target(source: Path, target: str, root: Path, vault_files: list[Path]) -> Path | None:
    target, _ = split_link_target(target)
    if not target or re.match(r"^(https?://|mailto:|obsidian://)", target, re.I):
        return None

    normalized = target.replace("\\", "/")
    candidates = [source.parent / normalized, root.joinpath(*normalized.split("/"))]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file() and is_within(candidate, root.resolve()):
            return candidate
        markdown_candidate = candidate.with_suffix(".md")
        if not candidate.suffix and markdown_candidate.is_file() and is_within(markdown_candidate, root.resolve()):
            return markdown_candidate

    if "/" not in normalized:
        matches = [file for file in vault_files if file.name == normalized or file.stem == normalized]
        if len(matches) == 1:
            return matches[0].resolve()
    return None


def normalize_anchor(value: str) -> str:
    value = html.unescape(unquote(value)).strip()
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"\\([\\`*_{}\[\]()#+.!|~-])", r"\1", value)
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def markdown_anchors(text: str) -> tuple[set[str], dict[str, list[int]]]:
    headings: set[str] = set()
    block_ids: dict[str, list[int]] = {}
    fence_char: str | None = None
    fence_length = 0
    for number, line in enumerate(text.splitlines(), 1):
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
                fence_length = 0
            continue
        if fence_char is not None:
            continue
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if heading:
            value = re.sub(r"\s+#+\s*$", "", heading.group(1)).strip()
            headings.add(normalize_anchor(value))
        block = re.search(r"(?:^|\s)\^([A-Za-z0-9-]+)\s*$", line)
        if block:
            block_ids.setdefault(block.group(1).casefold(), []).append(number)
    return headings, block_ids


def anchor_exists(target: Path, anchor: str | None, text_cache: dict[Path, str]) -> bool:
    if anchor is None or not anchor or target.suffix.lower() != ".md":
        return True
    text = text_cache.get(target, read_text(target))
    headings, block_ids = markdown_anchors(text)
    if anchor.startswith("^"):
        return anchor[1:].casefold() in block_ids
    return normalize_anchor(anchor) in headings


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


def parse_formal_field(text: str, name: str) -> str | None:
    """Read a Chinese bullet field or its supported YAML equivalent."""
    value = parse_field(text, name)
    if value:
        return value
    yaml_names = {
        "知识ID": "knowledge_id",
        "正式知识类型": "formal_type",
        "稳定实体键": "entity_key",
        "稳定主题键": "topic_key",
        "知识状态": "knowledge_status",
        "来源类型": "source_type",
        "数据或版本日期": "data_date",
        "最近核验日期": "verified_date",
        "使用前复核": "review_before_use",
    }
    yaml_name = yaml_names.get(name)
    if not yaml_name:
        return None
    match = re.search(rf"(?mi)^{re.escape(yaml_name)}\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip().strip('"\'') if match else None


def section_body(text: str, heading: str) -> str | None:
    match = re.search(
        rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        text,
    )
    return match.group(1).strip() if match else None


def formal_claim_blocks(text: str) -> list[tuple[str, str, int]]:
    matches = list(re.finditer(r"(?m)^###\s+(CLAIM-[^\n]+?)\s*$", text))
    blocks: list[tuple[str, str, int]] = []
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_end = re.search(r"(?m)^##\s+", text[match.end():next_start])
        end = match.end() + section_end.start() if section_end else next_start
        blocks.append((match.group(1).strip(), text[match.end():end], line_number(text, match.start())))
    return blocks


def is_substantive(value: str | None) -> bool:
    if value is None:
        return False
    normalized = re.sub(r"[\s。；;，,、\-]", "", value)
    return normalized not in {"", "无", "未注明", "待补", "待确认", "不适用", "未知"}


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if any(token in normalized for token in ("中文", "汉语", "简体", "繁体", "chinese", "zh-cn", "zh-tw")):
        return "zh"
    if any(token in normalized for token in ("英文", "英语", "english", "en-us", "en-gb")):
        return "en"
    return normalized or None


def strong_language_mismatch(body: str, declared_language: str | None) -> bool:
    """Only flag a high-confidence mismatch; technical text commonly mixes languages."""
    language = normalize_language(declared_language)
    if language not in {"zh", "en"}:
        return False
    body = re.sub(r"(?ms)```.*?```", "", body)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", body))
    latin = len(re.findall(r"[A-Za-z]", body))
    if language == "en":
        return cjk >= 40 and cjk > latin
    return latin >= 160 and latin > max(cjk * 4, 160)


def split_ids(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token.strip()
        for token in re.split(r"[，,、；;\s]+", value)
        if token.strip() and token.strip() not in {"无", "不适用", "待确认"}
    }


def field_is_human_identity(value: str | None) -> bool:
    if not is_substantive(value):
        return False
    return not bool(re.search(r"(?i)Skill|Codex|Agent|自动|系统|机器人|AI知识库专员", value or ""))


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


def validate_project(root: Path, runtime_skill: Path | None = None) -> list[Issue]:
    issues: list[Issue] = []

    def add(severity: str, code: str, file: Path | None, line: int, message: str) -> None:
        issues.append(Issue(severity, code, relpath(file, root) if file else ".", line, message))

    if not root.is_dir():
        add("ERROR", "PROJECT_NOT_FOUND", None, 0, f"项目目录不存在：{root}")
        return issues

    for name in REQUIRED_TOP_DIRS:
        if not (root / name).is_dir():
            add("ERROR", "MISSING_TOP_DIR", root, 0, f"缺少v0.4顶层目录：{name}")

    customer_request_file = root / CUSTOMER_REQUEST_RELATIVE
    if not customer_request_file.is_file():
        add(
            "ERROR",
            "MISSING_CUSTOMER_REQUEST_LEDGER",
            customer_request_file,
            0,
            "缺少项目级待客户补充事项总表",
        )

    source_anomaly_file = root / SOURCE_ANOMALY_RELATIVE
    if not source_anomaly_file.is_file():
        add(
            "ERROR",
            "MISSING_SOURCE_ANOMALY_LEDGER",
            source_anomaly_file,
            0,
            "缺少项目级源文与事实异常台账",
        )

    material_todo_file = root / MATERIAL_TODO_RELATIVE
    if not material_todo_file.is_file():
        add(
            "ERROR",
            "MISSING_MATERIAL_TODO_LEDGER",
            material_todo_file,
            0,
            "缺少项目级源资料处理待办",
        )

    source_register_file = root / SOURCE_REGISTER_RELATIVE
    if not source_register_file.is_file():
        add(
            "ERROR",
            "MISSING_SOURCE_REGISTER",
            source_register_file,
            0,
            "缺少项目级源文件总表",
        )

    workbench_todo_file = root / WORKBENCH_TODO_RELATIVE
    version_entry_file = root / VERSION_ENTRY_RELATIVE
    check_entry_file = root / CHECK_ENTRY_RELATIVE
    skill_feedback_file = root / SKILL_FEEDBACK_RELATIVE
    for required_file, code, message in (
        (workbench_todo_file, "MISSING_WORKBENCH_TODO", "缺少唯一项目当前状态正文20_当前待办.md"),
        (version_entry_file, "MISSING_VERSION_ENTRY", "缺少版本与变更入口"),
        (check_entry_file, "MISSING_CHECK_ENTRY", "缺少数据与审核检查入口"),
        (skill_feedback_file, "MISSING_SKILL_FEEDBACK_LEDGER", "缺少项目级Skill反馈台账"),
    ):
        if not required_file.is_file():
            add("ERROR", code, required_file, 0, message)

    vault_files = sorted(
        file for file in root.rglob("*") if file.is_file() and not is_ignored_vault_file(file, root)
    )
    md_files = [file for file in vault_files if file.suffix.lower() == ".md"]
    non_md_files = [file for file in vault_files if file.suffix.lower() != ".md"]
    current_md = [file for file in md_files if "/90_归档/" not in f"/{relpath(file, root)}/" and "/历史版本/" not in f"/{relpath(file, root)}/"]
    basename_map = build_basename_map(vault_files)
    text_cache = {file: read_text(file) for file in md_files}

    source_ids: set[str] = set()
    source_rows_by_id: dict[str, tuple[int, dict[str, str]]] = {}
    if source_register_file.is_file():
        source_text = text_cache.get(source_register_file, read_text(source_register_file))
        source_table = find_markdown_table(
            source_text,
            ("资料ID", "指纹", "版本或重复关系"),
        )
        if source_table is None:
            add(
                "ERROR",
                "SOURCE_REGISTER_SCHEMA",
                source_register_file,
                1,
                "源文件总表必须包含资料ID、指纹和版本或重复关系",
            )
        else:
            _, source_rows = source_table
            for line, row in source_rows:
                source_id = row.get("资料ID", "").strip()
                if not source_id:
                    add("ERROR", "SOURCE_REGISTER_ID", source_register_file, line, "源文件总表存在空资料ID")
                    continue
                if source_id in source_rows_by_id:
                    add("ERROR", "SOURCE_REGISTER_ID", source_register_file, line, f"源文件总表资料ID重复：{source_id}")
                source_ids.add(source_id)
                source_rows_by_id[source_id] = (line, row)

            for source_id, (line, row) in source_rows_by_id.items():
                relation = row.get("版本或重复关系", "").strip()
                if relation in SOURCE_RELATIONS_STANDALONE:
                    continue
                relation_match = re.fullmatch(
                    rf"({'|'.join(map(re.escape, sorted(SOURCE_RELATIONS_WITH_TARGET, key=len, reverse=True)))})→([^\s→]+)",
                    relation,
                )
                if relation_match is None:
                    add(
                        "ERROR",
                        "SOURCE_RELATION_STATE",
                        source_register_file,
                        line,
                        f"资料{source_id}的版本或重复关系不是固定写法：{relation or '空值'}",
                    )
                    continue
                relation_type, target_id = relation_match.groups()
                if target_id == source_id:
                    add("ERROR", "SOURCE_RELATION_SELF", source_register_file, line, f"资料{source_id}不能指向自身")
                    continue
                target = source_rows_by_id.get(target_id)
                if target is None:
                    add("ERROR", "SOURCE_RELATION_TARGET", source_register_file, line, f"资料{source_id}指向不存在的资料ID：{target_id}")
                    continue
                if relation_type == "完全重复副本":
                    target_row = target[1]
                    if target_row.get("版本或重复关系", "").strip() != "主文件":
                        add("ERROR", "DUPLICATE_SOURCE_MAIN", source_register_file, line, f"完全重复副本{source_id}必须指向标记为主文件的资料")
                    fingerprint = row.get("指纹", "").strip()
                    target_fingerprint = target_row.get("指纹", "").strip()
                    if not fingerprint or fingerprint != target_fingerprint:
                        add("ERROR", "DUPLICATE_SOURCE_FINGERPRINT", source_register_file, line, f"完全重复副本{source_id}与主文件{target_id}的指纹不一致")

            fingerprint_groups: dict[str, list[tuple[str, int, dict[str, str]]]] = {}
            for source_id, (line, row) in source_rows_by_id.items():
                fingerprint = row.get("指纹", "").strip()
                if fingerprint and fingerprint not in {"-", "未知", "待提取", "待确认"}:
                    fingerprint_groups.setdefault(fingerprint, []).append((source_id, line, row))
            for fingerprint, group in fingerprint_groups.items():
                if len(group) < 2:
                    continue
                main_ids = [source_id for source_id, _, row in group if row.get("版本或重复关系", "").strip() == "主文件"]
                if len(main_ids) != 1:
                    add(
                        "ERROR",
                        "DUPLICATE_SOURCE_GROUP",
                        source_register_file,
                        group[0][1],
                        f"相同指纹{fingerprint}必须且只能有一个主文件",
                    )
                    continue
                expected = f"完全重复副本→{main_ids[0]}"
                for source_id, line, row in group:
                    relation = row.get("版本或重复关系", "").strip()
                    if source_id != main_ids[0] and relation != expected:
                        add(
                            "ERROR",
                            "DUPLICATE_SOURCE_GROUP",
                            source_register_file,
                            line,
                            f"资料{source_id}与主文件指纹相同，必须写为{expected}",
                        )

    validate_content_navigation(root, source_rows_by_id, add)

    run_history_root = root / "90_归档/20_项目运行历史"
    run_ledger_file = root / RUN_LEDGER_RELATIVE
    for machine_log in non_md_files:
        if (
            is_within(machine_log.resolve(), run_history_root.resolve())
            and machine_log.suffix.lower() in {".json", ".jsonl"}
            and machine_log.resolve() != run_ledger_file.resolve()
        ):
            add(
                "ERROR",
                "RUN_LEDGER_FRAGMENT",
                machine_log,
                1,
                "项目运行记录只能追加到唯一的项目运行账本.jsonl，不得按次新建JSON/JSONL",
            )

    if run_ledger_file.is_file():
        seen_run_ids: set[str] = set()
        try:
            with run_ledger_file.open("r", encoding="utf-8") as handle:
                for ledger_line_number, raw_line in enumerate(handle, start=1):
                    if not raw_line.strip():
                        continue
                    try:
                        record = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        add("ERROR", "RUN_LEDGER_JSON", run_ledger_file, ledger_line_number, f"运行账本不是合法的逐行JSON：{exc}")
                        continue
                    if not isinstance(record, dict):
                        add("ERROR", "RUN_LEDGER_OBJECT", run_ledger_file, ledger_line_number, "运行账本每行必须是一个JSON对象")
                        continue
                    missing = sorted(RUN_LEDGER_REQUIRED_FIELDS - set(record))
                    if missing:
                        add("ERROR", "RUN_LEDGER_FIELDS", run_ledger_file, ledger_line_number, "运行账本缺少字段：" + ", ".join(missing))
                    if record.get("schema_version") != 1:
                        add("ERROR", "RUN_LEDGER_SCHEMA", run_ledger_file, ledger_line_number, "运行账本schema_version必须为1")
                    if record.get("status") not in RUN_LEDGER_STATUSES:
                        add("ERROR", "RUN_LEDGER_STATUS", run_ledger_file, ledger_line_number, "运行账本status不合法")
                    run_id = str(record.get("run_id", "")).strip()
                    if not run_id:
                        add("ERROR", "RUN_LEDGER_RUN_ID", run_ledger_file, ledger_line_number, "运行账本缺少run_id")
                    elif run_id in seen_run_ids:
                        add("ERROR", "RUN_LEDGER_DUPLICATE", run_ledger_file, ledger_line_number, f"运行账本run_id重复：{run_id}")
                    else:
                        seen_run_ids.add(run_id)
                    human = record.get("human_intervention")
                    if not isinstance(human, dict):
                        add("ERROR", "RUN_LEDGER_HUMAN", run_ledger_file, ledger_line_number, "human_intervention必须是JSON对象")
                    elif human.get("required") and not human.get("reason"):
                        add("ERROR", "RUN_LEDGER_HUMAN_REASON", run_ledger_file, ledger_line_number, "需要人工介入时必须记录原因")
        except (OSError, UnicodeError) as exc:
            add("ERROR", "RUN_LEDGER_READ", run_ledger_file, 0, f"无法以UTF-8读取运行账本：{exc}")

    if workbench_todo_file.is_file():
        todo_text = text_cache.get(workbench_todo_file, read_text(workbench_todo_file))
        for label, target in (
            ("待客户补充事项", CUSTOMER_REQUEST_RELATIVE),
            ("源文与事实异常", SOURCE_ANOMALY_RELATIVE),
            ("源资料处理待办", MATERIAL_TODO_RELATIVE),
            ("Skill运行反馈", SKILL_FEEDBACK_RELATIVE),
        ):
            if not any(
                resolve_vault_target(workbench_todo_file, raw, root, vault_files) == (root / target).resolve()
                for raw in iter_link_targets(todo_text)
            ):
                add("ERROR", "WORKBENCH_CONTROL_LINK", workbench_todo_file, 1, f"当前待办缺少{label}入口")

    if check_entry_file.is_file():
        check_text = text_cache.get(check_entry_file, read_text(check_entry_file))
        for label, target in (
            ("工作台当前待办", WORKBENCH_TODO_RELATIVE),
            ("待客户补充事项", CUSTOMER_REQUEST_RELATIVE),
            ("源文与事实异常", SOURCE_ANOMALY_RELATIVE),
            ("源资料处理待办", MATERIAL_TODO_RELATIVE),
            ("Skill运行反馈", SKILL_FEEDBACK_RELATIVE),
        ):
            if not any(
                resolve_vault_target(check_entry_file, raw, root, vault_files) == (root / target).resolve()
                for raw in iter_link_targets(check_text)
            ):
                add("ERROR", "CHECK_ENTRY_LINK", check_entry_file, 1, f"检查入口缺少{label}链接")

    if version_entry_file.is_file():
        version_text = text_cache.get(version_entry_file, read_text(version_entry_file))
        if re.search(r"(?m)^-\s*当前项目状态\s*[：:]", version_text):
            add("ERROR", "VERSION_ENTRY_DUPLICATE_STATE", version_entry_file, 1, "版本入口不得复制当前项目状态正文，必须链接20_当前待办.md")
        current_state = parse_field(version_text, "当前状态") or ""
        if not has_clickable_link(current_state):
            add("ERROR", "VERSION_ENTRY_CURRENT_LINK", version_entry_file, 1, "版本入口的当前状态必须链接20_当前待办.md")
        for label, target in (
            ("当前待办", WORKBENCH_TODO_RELATIVE),
            ("源资料处理待办", MATERIAL_TODO_RELATIVE),
            ("Skill运行反馈", SKILL_FEEDBACK_RELATIVE),
        ):
            if not any(
                resolve_vault_target(version_entry_file, raw, root, vault_files) == (root / target).resolve()
                for raw in iter_link_targets(version_text)
            ):
                add("ERROR", "VERSION_ENTRY_LINK", version_entry_file, 1, f"版本入口缺少{label}链接")
        version_table = find_markdown_table(version_text, ("日期", "变更", "依据", "执行人", "关联对象", "影响范围"))
        if version_table is None:
            add("ERROR", "VERSION_ENTRY_TABLE", version_entry_file, 1, "版本入口缺少固定六列项目级变更表")

        maintained_skill_file = skill_file()
        actual_runtime_skill_file = skill_file(runtime_skill) if runtime_skill is not None else maintained_skill_file
        if not maintained_skill_file.is_file():
            add("ERROR", "MAINTAINED_SKILL_NOT_FOUND", maintained_skill_file, 0, "校验器所属Skill缺少SKILL.md")
        elif not actual_runtime_skill_file.is_file():
            add("ERROR", "RUNTIME_SKILL_NOT_FOUND", actual_runtime_skill_file, 0, "指定的实际运行Skill不存在或缺少SKILL.md")
        else:
            maintained_hash = sha256_file(maintained_skill_file)
            runtime_hash = sha256_file(actual_runtime_skill_file)
            if maintained_hash != runtime_hash:
                add(
                    "ERROR",
                    "RUNTIME_SKILL_MISMATCH",
                    actual_runtime_skill_file,
                    0,
                    f"实际运行Skill指纹{runtime_hash}与维护源{maintained_hash}不一致，先同步运行副本再迁移项目",
                )
            project_hash = normalize_sha256(parse_field(version_text, "Skill指纹"))
            if project_hash is None:
                add("ERROR", "PROJECT_SKILL_FINGERPRINT", version_entry_file, 1, "版本入口缺少有效的64位SHA-256 Skill指纹")
            elif project_hash != runtime_hash:
                add(
                    "ERROR",
                    "PROJECT_SKILL_MISMATCH",
                    version_entry_file,
                    1,
                    f"项目登记Skill指纹{project_hash}与实际运行版本{runtime_hash}不一致，必须先执行版本迁移",
                )

    forbidden_runtime_files: set[Path] = set()
    mineru_root = root / "04_资料与证据/20_Codex提取"
    if mineru_root.is_dir():
        for asset_dir in sorted(path for path in mineru_root.rglob("*_assets") if path.is_dir()):
            add(
                "ERROR",
                "MINERU_ASSETS_FORBIDDEN",
                asset_dir,
                0,
                "MinerU提取区只保留主Markdown，不归档自动生成的assets目录",
            )
    for file in non_md_files:
        relative = file.relative_to(root)
        if (
            any(part.lower() in FORBIDDEN_RUNTIME_DIRS for part in relative.parts[:-1])
            or file.suffix.lower() in FORBIDDEN_RUNTIME_SUFFIXES
        ):
            forbidden_runtime_files.add(file.resolve())
            add("ERROR", "VAULT_RUNTIME_FILE", file, 1, "客户Obsidian项目不得包含脚本、缓存、临时文件或运行产物")

    data_explanation_file = root / DATA_EXPLANATION_RELATIVE
    registered_managed_files: set[Path] = set()
    if not data_explanation_file.is_file():
        add("ERROR", "MISSING_DATA_EXPLANATION", data_explanation_file, 0, "缺少受管非Markdown数据文件的Markdown导航入口")
    else:
        data_text = text_cache.get(data_explanation_file, read_text(data_explanation_file))
        data_table = find_markdown_table(data_text, DATA_EXPLANATION_HEADERS)
        if data_table is None:
            add("ERROR", "DATA_EXPLANATION_SCHEMA", data_explanation_file, 1, "数据说明缺少固定九列表格")
        else:
            _, rows = data_table
            for line, row in rows:
                file_cell = row.get("文件", "")
                if not has_clickable_link(file_cell):
                    add("ERROR", "DATA_EXPLANATION_LINK", data_explanation_file, line, "受管文件必须使用可点击链接登记")
                resolved_targets = {
                    target
                    for raw_target in iter_link_targets(file_cell)
                    if (target := resolve_vault_target(data_explanation_file, raw_target, root, vault_files)) is not None
                }
                managed_targets = {
                    target for target in resolved_targets if is_within(target, (root / "05_数据与审核").resolve())
                }
                if not managed_targets:
                    add("ERROR", "DATA_EXPLANATION_TARGET", data_explanation_file, line, "文件链接必须指向05_数据与审核中的现存非Markdown文件")
                for target in managed_targets:
                    if target.suffix.lower() == ".md":
                        add("ERROR", "DATA_EXPLANATION_TARGET", data_explanation_file, line, "数据说明只登记非Markdown受管文件")
                    else:
                        registered_managed_files.add(target)
                for header in DATA_EXPLANATION_HEADERS[1:]:
                    if not row.get(header, "").strip():
                        add("ERROR", "DATA_EXPLANATION_FIELD", data_explanation_file, line, f"受管文件登记缺少字段：{header}")

    managed_csv_root = root / "05_数据与审核"
    if managed_csv_root.is_dir():
        for csv_file in sorted(managed_csv_root.rglob("*.csv")):
            try:
                has_bom = csv_file.read_bytes().startswith(UTF8_BOM)
            except OSError as exc:
                add("ERROR", "CSV_READ_ERROR", csv_file, 0, f"无法读取受管CSV：{exc}")
                continue
            if not has_bom:
                add("ERROR", "CSV_UTF8_BOM", csv_file, 1, "知识库受管CSV必须使用UTF-8 with BOM，避免Windows Excel中文乱码")

        for managed_file in non_md_files:
            resolved = managed_file.resolve()
            if not is_within(resolved, managed_csv_root.resolve()) or resolved in forbidden_runtime_files:
                continue
            if resolved not in registered_managed_files:
                add("ERROR", "MANAGED_FILE_NOT_REGISTERED", managed_file, 1, "05_数据与审核中的非Markdown文件未登记到01_数据说明.md")

    linked_non_md_files: set[Path] = set()
    for markdown_file in current_md:
        for raw_target in iter_link_targets(text_cache[markdown_file]):
            target = resolve_vault_target(markdown_file, raw_target, root, vault_files)
            if target is not None and target.suffix.lower() != ".md":
                linked_non_md_files.add(target.resolve())

    for non_md_file in non_md_files:
        resolved = non_md_file.resolve()
        relative = f"/{relpath(non_md_file, root)}/"
        if (
            resolved in forbidden_runtime_files
            or is_within(resolved, managed_csv_root.resolve())
            or "/90_归档/" in relative
        ):
            continue
        if resolved not in linked_non_md_files:
            add("ERROR", "NON_MD_ORPHAN", non_md_file, 1, "Vault内非Markdown文件没有当前Markdown导航或证据回链")

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

        for match in re.finditer(r"AI知识库专员(?:自动|自行执行)|由AI知识库专员自动", text):
            add(
                "ERROR",
                "AUTOMATION_ACTOR_MISLABELED",
                file,
                line_number(text, match.start()),
                "AI知识库专员是人工业务角色；自动执行必须写为Skill、Codex主Agent或具体自动化Agent",
            )

        if relative.startswith("04_资料与证据/20_Codex提取/"):
            for match in re.finditer(r"!\[[^\]\n]*\]\((?!https?://|data:)([^)\n]+)\)", text, re.I):
                add(
                    "ERROR",
                    "MINERU_ASSETS_FORBIDDEN",
                    file,
                    line_number(text, match.start()),
                    "MinerU运营Markdown不得引用本地资源文件；视觉证据应从原件另行选取最少截图",
                )

        if relative.startswith("04_资料与证据/") or relative == SOURCE_ANOMALY_RELATIVE:
            for number in unprotected_double_percent_lines(text):
                add(
                    "ERROR",
                    "OBSIDIAN_CONTROL_SYNTAX",
                    file,
                    number,
                    "逐字内容中的%%必须放入行内代码或text围栏代码块，避免Obsidian把后续内容解析成注释",
                )

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

        _, block_ids = markdown_anchors(text)
        for block_id, block_lines in block_ids.items():
            if len(block_lines) > 1:
                add(
                    "ERROR",
                    "DUPLICATE_BLOCK_ID",
                    file,
                    block_lines[1],
                    f"同一Markdown文件中的块ID必须唯一：^{block_id}（出现于第{', '.join(map(str, block_lines))}行）",
                )

        for match in re.finditer(r"!?\[\[([^\]|#]*)(?:#([^\]|]+))?(?:\|[^\]]+)?\]\]", text):
            target = match.group(1).strip()
            anchor = (match.group(2) or "").strip() or None
            resolved: Path | None = None
            if not target:
                resolved = file.resolve()
            elif "/" in target or "\\" in target:
                candidate = (root / target.replace("\\", "/")).resolve()
                if candidate.exists():
                    resolved = candidate
                elif candidate.with_suffix(".md").exists():
                    resolved = candidate.with_suffix(".md")
            else:
                matches = basename_map.get(target, [])
                if len(matches) == 1:
                    resolved = matches[0].resolve()
            if resolved is None:
                add("ERROR", "BROKEN_WIKILINK", file, line_number(text, match.start()), f"无法解析Wikilink：{target or '#'+(anchor or '')}")
            elif not anchor_exists(resolved, anchor, text_cache):
                add(
                    "ERROR",
                    "BROKEN_LINK_ANCHOR",
                    file,
                    line_number(text, match.start()),
                    f"Wikilink锚点不存在：{anchor}（目标：{relpath(resolved, root)}）",
                )

        for match in re.finditer(r"!?\[[^\]\n]*\]\((<[^>]+>|[^)\n]+)\)", text):
            target = match.group(1).strip()
            path, anchor = split_link_target(target)
            if re.match(r"^(https?://|mailto:|obsidian://)", path, re.I):
                continue
            resolved = resolve_markdown_link_target(file, target, root)
            if resolved is None:
                add("ERROR", "BROKEN_MD_LINK", file, line_number(text, match.start()), f"无法解析Markdown链接：{target}")
            elif not anchor_exists(resolved, anchor, text_cache):
                add(
                    "ERROR",
                    "BROKEN_LINK_ANCHOR",
                    file,
                    line_number(text, match.start()),
                    f"Markdown链接锚点不存在：{anchor}（目标：{relpath(resolved, root)}）",
                )

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

        customer_table = find_markdown_table(customer_text, CUSTOMER_REQUEST_HEADERS)
        if customer_table is None:
            add(
                "ERROR",
                "CUSTOMER_REQUEST_TABLE",
                customer_request_file,
                1,
                "待客户补充事项缺少固定当前事项表",
            )
        else:
            headers, rows = customer_table
            if headers != list(CUSTOMER_REQUEST_HEADERS):
                add("ERROR", "CUSTOMER_REQUEST_TABLE", customer_request_file, 1, "待客户补充事项字段顺序或数量不符合v0.4固定结构")
            seen_request_ids: set[str] = set()
            for line, row in rows:
                request_id = row.get("问题ID", "")
                stage = row.get("当前阶段", "")
                next_actor = row.get("下一步由谁做", "")
                for header in CUSTOMER_REQUEST_HEADERS:
                    if not row.get(header, "").strip():
                        add("ERROR", "CUSTOMER_REQUEST_FIELD", customer_request_file, line, f"待客户补充事项缺少字段：{header}")
                if not request_id:
                    add("ERROR", "CUSTOMER_REQUEST_ID_MISSING", customer_request_file, line, "待客户补充事项缺少问题ID")
                    continue
                if request_id in seen_request_ids:
                    add("ERROR", "DUPLICATE_CUSTOMER_REQUEST_ID", customer_request_file, line, f"待客户补充事项问题ID重复：{request_id}")
                seen_request_ids.add(request_id)
                if stage not in CUSTOMER_REQUEST_STAGES:
                    add("ERROR", "CUSTOMER_REQUEST_STAGE", customer_request_file, line, f"待客户补充事项阶段无效：{stage or '空值'}")
                if stage == "待判断要不要问" and "知识库专员" not in next_actor:
                    add("ERROR", "CUSTOMER_REQUEST_SPECIALIST", customer_request_file, line, "待判断要不要问的事项必须把下一步明确交给知识库专员")

                detail = customer_detail(customer_text, request_id)
                if detail is None:
                    add("ERROR", "CUSTOMER_REQUEST_DETAIL", customer_request_file, line, f"事项{request_id}缺少对应详情")
                    continue
                if "#### 先看结论" not in detail:
                    add("ERROR", "CUSTOMER_REQUEST_PLAIN_SUMMARY", customer_request_file, line, f"事项{request_id}详情必须先提供通俗结论")
                for field in ("发生了什么", "希望客户确认或提供什么", "为什么值得询问", "客户回复前怎么处理", "当前阶段", "下一步由谁做"):
                    if not is_substantive(parse_field(detail, field)):
                        add("ERROR", "CUSTOMER_REQUEST_DETAIL_FIELD", customer_request_file, line, f"事项{request_id}缺少通俗字段：{field}")
                detail_stage = parse_field(detail, "当前阶段") or ""
                if detail_stage and detail_stage != stage:
                    add("ERROR", "CUSTOMER_REQUEST_STAGE_MISMATCH", customer_request_file, line, f"事项{request_id}主表与详情阶段不一致")
                if stage == "无需询问" and not is_substantive(parse_field(detail, "为什么值得询问")):
                    add("ERROR", "CUSTOMER_REQUEST_NO_ASK_REASON", customer_request_file, line, "无需询问必须用通俗语言说明现有资料、排除或安全改写为何已经足够")
                if stage in {"等待发送", "等待客户回复", "收到回复，待核实", "已完成"}:
                    script = parse_field(detail, "话术") or ""
                    specialist_confirmation = parse_field(detail, "知识库专员确认") or ""
                    optimizer = parse_field(detail, "对客执行人（优化师）") or ""
                    if not is_substantive(script) or not is_substantive(specialist_confirmation):
                        add("ERROR", "CUSTOMER_REQUEST_SCRIPT_REQUIRED", customer_request_file, line, "进入发送流程前必须保存知识库专员确认的客户话术")
                    if not is_substantive(optimizer):
                        add("ERROR", "CUSTOMER_REQUEST_OPTIMIZER", customer_request_file, line, "进入发送流程前必须指定优化师")
                if stage in {"等待客户回复", "收到回复，待核实", "已完成"}:
                    if not is_substantive(parse_field(detail, "发送日期与渠道")):
                        add("ERROR", "CUSTOMER_REQUEST_SENT_RECORD", customer_request_file, line, "实际发送后必须记录日期与渠道")
                if stage in {"收到回复，待核实", "已完成"}:
                    reply_evidence = parse_field(detail, "回复或客户材料证据") or ""
                    if not has_clickable_link(reply_evidence):
                        add("ERROR", "CUSTOMER_REQUEST_REPLY_EVIDENCE", customer_request_file, line, "收到回复后必须保存可点击回复或客户材料证据")
                if stage == "已完成":
                    if not is_substantive(parse_field(detail, "新材料或答复是否解决问题")):
                        add("ERROR", "CUSTOMER_REQUEST_COMPLETION", customer_request_file, line, "已完成事项必须说明新材料或答复是否解决问题")
                    if not is_substantive(parse_field(detail, "更新了哪些知识、候选或文章输入")):
                        add("ERROR", "CUSTOMER_REQUEST_COMPLETION", customer_request_file, line, "已完成事项必须说明回复后的下游更新")

    if material_todo_file.is_file():
        material_text = text_cache.get(material_todo_file, read_text(material_todo_file))
        for heading in ("# 源资料处理待办", "## 当前事项", "## 事项详情", "## 已完成、暂不处理与历史"):
            if heading not in material_text:
                add("ERROR", "MATERIAL_TODO_SECTION", material_todo_file, 1, f"源资料处理待办缺少小节：{heading.lstrip('# ').strip()}")
        material_table = find_markdown_table(material_text, MATERIAL_TODO_HEADERS)
        if material_table is None:
            add("ERROR", "MATERIAL_TODO_TABLE", material_todo_file, 1, "源资料处理待办缺少固定当前事项表")
        else:
            headers, rows = material_table
            if headers != list(MATERIAL_TODO_HEADERS):
                add("ERROR", "MATERIAL_TODO_TABLE", material_todo_file, 1, "源资料处理待办字段顺序或数量不符合v0.4固定结构")
            seen_material_ids: set[str] = set()
            for line, row in rows:
                material_id = row.get("事项ID", "").strip()
                source_id = row.get("资料ID", "").strip()
                stage = row.get("当前阶段", "").strip()
                decision = row.get("AI知识库专员决定", "").strip()
                next_step = row.get("下一步", "").strip()
                for header in MATERIAL_TODO_HEADERS:
                    if not row.get(header, "").strip():
                        add("ERROR", "MATERIAL_TODO_FIELD", material_todo_file, line, f"源资料处理事项缺少字段：{header}")
                if not re.fullmatch(r"[A-Za-z0-9_-]+-MAT-\d{3,}", material_id):
                    add("ERROR", "MATERIAL_TODO_ID", material_todo_file, line, f"源资料处理事项ID格式无效：{material_id or '空值'}")
                elif material_id in seen_material_ids:
                    add("ERROR", "DUPLICATE_MATERIAL_TODO_ID", material_todo_file, line, f"源资料处理事项ID重复：{material_id}")
                seen_material_ids.add(material_id)
                if not source_id:
                    add("ERROR", "MATERIAL_TODO_SOURCE_ID", material_todo_file, line, "源资料处理事项必须登记资料ID")
                elif source_ids and source_id not in source_ids:
                    add("ERROR", "MATERIAL_TODO_SOURCE_ID", material_todo_file, line, f"源资料处理事项指向不存在的资料ID：{source_id}")
                if stage not in MATERIAL_TODO_STAGES:
                    add("ERROR", "MATERIAL_TODO_STAGE", material_todo_file, line, f"源资料处理事项阶段无效：{stage or '空值'}")
                if stage == "待专员判断" and "知识库专员" not in (decision + next_step):
                    add("ERROR", "MATERIAL_TODO_SPECIALIST", material_todo_file, line, "待专员判断事项必须把决定或下一步明确交给AI知识库专员")
                detail = material_detail(material_text, material_id)
                if detail is None:
                    add("ERROR", "MATERIAL_TODO_DETAIL", material_todo_file, line, f"事项{material_id}缺少对应详情")
                    continue
                if "#### 先看结论" not in detail or "#### 资料与关联" not in detail:
                    add("ERROR", "MATERIAL_TODO_DETAIL_SECTION", material_todo_file, line, f"事项{material_id}缺少通俗结论或资料关联小节")
                for field in ("资料是什么", "现在为什么不能正常处理", "是否影响当前文章", "当前阶段", "AI知识库专员决定", "下一步"):
                    if not is_substantive(parse_field(detail, field)):
                        add("ERROR", "MATERIAL_TODO_DETAIL_FIELD", material_todo_file, line, f"事项{material_id}缺少字段：{field}")
                detail_stage = parse_field(detail, "当前阶段") or ""
                if detail_stage and detail_stage != stage:
                    add("ERROR", "MATERIAL_TODO_STAGE_MISMATCH", material_todo_file, line, f"事项{material_id}主表与详情阶段不一致")
                source_register = parse_field(detail, "源文件总表") or ""
                if not has_clickable_link(source_register):
                    add("ERROR", "MATERIAL_TODO_SOURCE_LINK", material_todo_file, line, f"事项{material_id}必须链接源文件总表")
                if stage == "已处理可复用":
                    processed = parse_field(detail, "当前处理稿") or ""
                    mapping = parse_field(detail, "时间码/页码/包内路径等来源映射") or ""
                    audit = parse_field(detail, "审核结果") or ""
                    if not has_clickable_link(processed):
                        add("ERROR", "MATERIAL_TODO_ARTIFACT", material_todo_file, line, f"事项{material_id}已处理可复用但缺少可点击当前处理稿")
                    if not is_substantive(mapping) or not is_substantive(audit):
                        add("ERROR", "MATERIAL_TODO_REUSE_EVIDENCE", material_todo_file, line, f"事项{material_id}已处理可复用但缺少来源映射或审核结果")
                if stage in {"暂不处理", "无法处理，保留登记"}:
                    reopen = parse_field(detail, "重开条件或复查日期") or ""
                    if not is_substantive(reopen):
                        add("ERROR", "MATERIAL_TODO_REOPEN", material_todo_file, line, f"事项{material_id}必须记录重开条件或复查日期")

    if source_anomaly_file.is_file():
        anomaly_text = text_cache.get(source_anomaly_file, read_text(source_anomaly_file))
        for heading in ("# 源文与事实异常台账", "## 当前异常", "## 异常详情", "## 已完成处置与历史"):
            if heading not in anomaly_text:
                add(
                    "ERROR",
                    "SOURCE_ANOMALY_SECTION",
                    source_anomaly_file,
                    1,
                    f"源文与事实异常台账缺少小节：{heading.lstrip('# ').strip()}",
                )

        anomaly_table = find_markdown_table(anomaly_text, SOURCE_ANOMALY_HEADERS)
        if anomaly_table is None:
            add(
                "ERROR",
                "SOURCE_ANOMALY_TABLE",
                source_anomaly_file,
                1,
                "源文与事实异常台账缺少固定当前异常表",
            )
        else:
            headers, rows = anomaly_table
            if headers != list(SOURCE_ANOMALY_HEADERS):
                add(
                    "ERROR",
                    "SOURCE_ANOMALY_TABLE",
                    source_anomaly_file,
                    1,
                    "源文与事实异常表字段顺序或数量不符合v0.4固定结构",
                )
            seen_anomaly_ids: set[str] = set()
            for line, row in rows:
                anomaly_id = row.get("异常ID", "")
                repair_state = row.get("原文是否修复", "")
                stage = row.get("当前阶段", "")
                reopen = row.get("下一步或重开条件", "")
                for header in SOURCE_ANOMALY_HEADERS:
                    if not row.get(header, "").strip():
                        add("ERROR", "SOURCE_ANOMALY_FIELD", source_anomaly_file, line, f"源文与事实异常缺少字段：{header}")
                if not anomaly_id:
                    add("ERROR", "SOURCE_ANOMALY_ID_MISSING", source_anomaly_file, line, "源文与事实异常缺少异常ID")
                    continue
                if anomaly_id in seen_anomaly_ids:
                    add("ERROR", "DUPLICATE_SOURCE_ANOMALY_ID", source_anomaly_file, line, f"源文与事实异常ID重复：{anomaly_id}")
                seen_anomaly_ids.add(anomaly_id)
                if repair_state not in SOURCE_REPAIR_STATES:
                    add("ERROR", "SOURCE_ANOMALY_REPAIR_STATE", source_anomaly_file, line, f"原文是否修复状态无效：{repair_state or '空值'}")
                if stage not in SOURCE_ANOMALY_STAGES:
                    add("ERROR", "SOURCE_ANOMALY_STAGE", source_anomaly_file, line, f"源文与事实异常阶段无效：{stage or '空值'}")
                if stage == "已解决" and repair_state != "已修复":
                    add("ERROR", "SOURCE_ANOMALY_STAGE_REPAIR", source_anomaly_file, line, "只有原文已修复时才能标记已解决")
                if stage == "部分解决" and repair_state != "部分修复":
                    add("ERROR", "SOURCE_ANOMALY_STAGE_REPAIR", source_anomaly_file, line, "部分解决必须对应原文部分修复；范围混合时应拆分异常")
                if stage == "已完成处置（原文未修复）" and repair_state not in {"未修复", "无法判断"}:
                    add("ERROR", "SOURCE_ANOMALY_STAGE_REPAIR", source_anomaly_file, line, "已完成处置（原文未修复）只能用于未修复或无法判断的原文")

                detail = anomaly_detail(anomaly_text, anomaly_id)
                if detail is None:
                    add("ERROR", "SOURCE_ANOMALY_DETAIL", source_anomaly_file, line, f"异常{anomaly_id}缺少对应详情和原文现场证据包")
                else:
                    if "#### 先看结论" not in detail:
                        add("ERROR", "SOURCE_ANOMALY_PLAIN_SUMMARY", source_anomaly_file, line, f"异常{anomaly_id}详情必须先提供通俗结论")
                    for field in ("发生了什么", "为什么有风险", "现在怎么处理", "为什么本轮结束，或者还在等什么"):
                        if not is_substantive(parse_field(detail, field)):
                            add("ERROR", "SOURCE_ANOMALY_PLAIN_FIELD", source_anomaly_file, line, f"异常{anomaly_id}缺少通俗字段：{field}")
                    detail_repair = parse_field(detail, "原文是否修复") or ""
                    detail_stage = parse_field(detail, "当前阶段") or ""
                    if detail_repair and detail_repair != repair_state:
                        add("ERROR", "SOURCE_ANOMALY_REPAIR_MISMATCH", source_anomaly_file, line, f"异常{anomaly_id}主表与详情的原文修复状态不一致")
                    if detail_stage and detail_stage != stage:
                        add("ERROR", "SOURCE_ANOMALY_STAGE_MISMATCH", source_anomaly_file, line, f"异常{anomaly_id}主表与详情阶段不一致")
                    saved_evidence = parse_field(detail, "保存原文证据") or ""
                    original_source = parse_field(detail, "原始来源") or ""
                    source_version = parse_field(detail, "来源版本/指纹") or ""
                    detail_location = parse_field(detail, "精确位置") or ""
                    detail_completeness = parse_field(detail, "证据完整性") or ""
                    evidence_type = parse_field(detail, "现场证据类型") or ""
                    page_evidence = parse_field(detail, "页面截图或原始版面") or ""
                    audit_result = parse_field(detail, "审核Agent独立复核") or ""
                    completion_evidence = parse_field(detail, "完成处置的证据") or ""
                    actual = heading_body(detail, r"实际取得的原文或原始结构（逐字/原样）") or ""
                    usable = heading_body(detail, r"经核验仍可使用的原文或原始结构（如有）")
                    usable_location = parse_field(detail, "可使用证据位置") or ""
                    if "#### 原文现场证据" not in detail:
                        add("ERROR", "SOURCE_ANOMALY_EVIDENCE_SECTION", source_anomaly_file, line, f"异常{anomaly_id}缺少原文现场证据小节")
                    if not has_clickable_link(saved_evidence):
                        add("ERROR", "SOURCE_ANOMALY_SAVED_EVIDENCE", source_anomaly_file, line, f"异常{anomaly_id}缺少可点击保存原文证据")
                    if not original_source or (not has_clickable_link(original_source) and "无法取得" not in original_source):
                        add("ERROR", "SOURCE_ANOMALY_ORIGINAL_SOURCE", source_anomaly_file, line, f"异常{anomaly_id}必须链接原始来源，无法取得时写明原因")
                    if not source_version:
                        add("ERROR", "SOURCE_ANOMALY_SOURCE_VERSION", source_anomaly_file, line, f"异常{anomaly_id}缺少来源版本或指纹")
                    if not detail_location:
                        add("ERROR", "SOURCE_ANOMALY_DETAIL_LOCATION", source_anomaly_file, line, f"异常{anomaly_id}详情缺少精确位置")
                    if detail_completeness not in SOURCE_EVIDENCE_COMPLETENESS:
                        add("ERROR", "SOURCE_ANOMALY_DETAIL_COMPLETENESS", source_anomaly_file, line, f"异常{anomaly_id}详情的证据完整性无效")
                    if evidence_type not in SOURCE_EVIDENCE_TYPES:
                        add("ERROR", "SOURCE_ANOMALY_EVIDENCE_TYPE", source_anomaly_file, line, f"异常{anomaly_id}的现场证据类型无效")
                    if not verbatim_body(actual):
                        add("ERROR", "SOURCE_ANOMALY_VERBATIM", source_anomaly_file, line, f"异常{anomaly_id}缺少实际取得的逐字原文或原始结构")
                    if "##### 必要上下文" not in detail or not (parse_field(detail, "异常位置") or ""):
                        add("ERROR", "SOURCE_ANOMALY_CONTEXT", source_anomaly_file, line, f"异常{anomaly_id}缺少必要上下文或异常位置")
                    if usable is None:
                        add("ERROR", "SOURCE_ANOMALY_USABLE_EVIDENCE", source_anomaly_file, line, f"异常{anomaly_id}缺少经核验仍可使用的原文或原始结构小节")
                    else:
                        usable_text = verbatim_body(usable)
                        if usable_text and usable_text != "无" and not has_clickable_link(usable_location):
                            add("ERROR", "SOURCE_ANOMALY_USABLE_LINK", source_anomaly_file, line, f"异常{anomaly_id}存在经核验仍可使用的证据，但没有可点击定位链接")
                    if evidence_type and evidence_type != "逐字文本" and not has_clickable_link(page_evidence):
                        add("ERROR", "SOURCE_ANOMALY_VISUAL_EVIDENCE", source_anomaly_file, line, f"异常{anomaly_id}属于视觉/结构现场，必须链接原页、截图、原表或公式")
                    if stage in {"已解决", "已完成处置（原文未修复）"}:
                        current_updates = parse_field(detail, "当前正式知识/候选/项目资料稿更新")
                        historical_impact = parse_field(detail, "已完成文章历史影响与修订决定")
                        if not is_substantive(audit_result):
                            add("ERROR", "SOURCE_ANOMALY_COMPLETION_AUDIT", source_anomaly_file, line, "完成异常处置前必须记录审核Agent实际核对结果")
                        if not has_clickable_link(completion_evidence) or "本台账" in completion_evidence:
                            add("ERROR", "SOURCE_ANOMALY_COMPLETION_EVIDENCE", source_anomaly_file, line, "完成异常处置必须链接原文现场、审核记录或下游更新，不能只写本台账")
                        if current_updates is None or historical_impact is None:
                            add("ERROR", "SOURCE_ANOMALY_DOWNSTREAM", source_anomaly_file, line, "完成异常处置必须登记当前下游更新和已完成文章历史影响")
                        customer_issue = parse_field(detail, "关联客户问题ID") or ""
                        specialist_review = parse_field(detail, "知识库专员必要性判断") or ""
                        if stage == "已完成处置（原文未修复）" and is_substantive(customer_issue) and not is_substantive(specialist_review):
                            add("ERROR", "SOURCE_ANOMALY_SPECIALIST_REVIEW", source_anomaly_file, line, "客户专属事实原文未修复时，必须先记录知识库专员是否需要向客户补充询问的判断")
                        if not reopen:
                            add("ERROR", "SOURCE_ANOMALY_REOPEN_CONDITION", source_anomaly_file, line, "已解决或已完成处置的异常必须填写重开条件")

    if skill_feedback_file.is_file():
        feedback_text = text_cache.get(skill_feedback_file, read_text(skill_feedback_file))
        for heading in ("# Skill反馈台账", "## 当前反馈", "## 反馈详情", "## 已关闭与不纳入"):
            if heading not in feedback_text:
                add("ERROR", "SKILL_FEEDBACK_SECTION", skill_feedback_file, 1, f"Skill反馈台账缺少小节：{heading.lstrip('# ').strip()}")
        feedback_table = find_markdown_table(feedback_text, SKILL_FEEDBACK_HEADERS)
        if feedback_table is None:
            add("ERROR", "SKILL_FEEDBACK_TABLE", skill_feedback_file, 1, "Skill反馈台账缺少固定八列表")
        else:
            headers, rows = feedback_table
            if headers != list(SKILL_FEEDBACK_HEADERS):
                add("ERROR", "SKILL_FEEDBACK_TABLE", skill_feedback_file, 1, "Skill反馈表字段顺序或数量不符合v0.4固定结构")
            seen_feedback_ids: set[str] = set()
            for line, row in rows:
                feedback_id = row.get("反馈ID", "")
                origin = row.get("提出来源", "")
                feedback_type = row.get("类型", "")
                stage = row.get("当前阶段", "")
                for header in SKILL_FEEDBACK_HEADERS:
                    if not row.get(header, "").strip():
                        add("ERROR", "SKILL_FEEDBACK_FIELD", skill_feedback_file, line, f"Skill反馈缺少字段：{header}")
                if not feedback_id:
                    continue
                if feedback_id in seen_feedback_ids:
                    add("ERROR", "DUPLICATE_SKILL_FEEDBACK_ID", skill_feedback_file, line, f"Skill反馈ID重复：{feedback_id}")
                seen_feedback_ids.add(feedback_id)
                if origin not in SKILL_FEEDBACK_ORIGINS:
                    add("ERROR", "SKILL_FEEDBACK_ORIGIN", skill_feedback_file, line, f"Skill反馈提出来源无效：{origin or '空值'}")
                if feedback_type not in SKILL_FEEDBACK_TYPES:
                    add("ERROR", "SKILL_FEEDBACK_TYPE", skill_feedback_file, line, f"Skill反馈类型无效：{feedback_type or '空值'}")
                if stage not in SKILL_FEEDBACK_STAGES:
                    add("ERROR", "SKILL_FEEDBACK_STAGE", skill_feedback_file, line, f"Skill反馈阶段无效：{stage or '空值'}")
                expected_stage = {
                    "Codex自动发现": "自动记录，待维护判断",
                    "人工提出": "人工提出，待维护判断",
                }.get(origin)
                if expected_stage and stage in {"自动记录，待维护判断", "人工提出，待维护判断"} and stage != expected_stage:
                    add("ERROR", "SKILL_FEEDBACK_ORIGIN_STAGE", skill_feedback_file, line, "待维护判断阶段必须与首次提出来源一致")
                detail = skill_feedback_detail(feedback_text, feedback_id)
                if detail is None:
                    add("ERROR", "SKILL_FEEDBACK_DETAIL", skill_feedback_file, line, f"反馈{feedback_id}缺少对应详情")
                    continue
                for field in ("实际发生了什么", "原本希望怎样", "对当前项目有什么影响", "当前临时处理", "提出来源", "提出日期", "当前阶段", "下一步由谁做"):
                    if not is_substantive(parse_field(detail, field)):
                        add("ERROR", "SKILL_FEEDBACK_DETAIL_FIELD", skill_feedback_file, line, f"反馈{feedback_id}缺少字段：{field}")
                if origin == "Codex自动发现" and not is_substantive(parse_field(detail, "自动总结依据（Codex自动发现时必填）")):
                    add("ERROR", "SKILL_FEEDBACK_AUTO_EVIDENCE", skill_feedback_file, line, f"自动反馈{feedback_id}缺少自动总结依据")
                if origin == "人工提出" and not is_substantive(parse_field(detail, "人工提出摘要（人工提出时必填）")):
                    add("ERROR", "SKILL_FEEDBACK_HUMAN_EVIDENCE", skill_feedback_file, line, f"人工反馈{feedback_id}缺少人工提出摘要")
                related_file = parse_field(detail, "相关文件") or ""
                related_ids = " ".join(
                    parse_field(detail, name) or ""
                    for name in ("相关文章ID（有才写）", "关联客户事项ID（有才写）", "关联源文异常ID（有才写）", "关联校验结果（有才写）")
                )
                if not has_clickable_link(related_file) and not is_substantive(related_ids):
                    add("ERROR", "SKILL_FEEDBACK_RELATION", skill_feedback_file, line, f"反馈{feedback_id}必须关联项目文件、文章、CUS、ANM或校验结果")
                if stage not in {"已关闭", "转为项目问题", "不纳入Skill"} and workbench_todo_file.is_file():
                    todo_text = text_cache.get(workbench_todo_file, read_text(workbench_todo_file))
                    if feedback_id not in todo_text:
                        add("ERROR", "SKILL_FEEDBACK_NOT_IN_WORKBENCH", workbench_todo_file, 1, f"未关闭反馈{feedback_id}未出现在当前待办")

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
    formal_files: list[Path] = []
    formal_file_ids: dict[str, Path] = {}
    formal_claim_ids: dict[str, Path] = {}
    formal_issue_files: set[str] = set()

    def add_formal(code: str, file: Path, line: int, message: str) -> None:
        add("ERROR", code, file, line, message)
        formal_issue_files.add(relpath(file, root))

    if formal_root.exists():
        for required in FORMAL_REQUIRED_DIRS:
            required_path = root / required
            if not required_path.is_dir():
                add("ERROR", "MISSING_FORMAL_SUBDIR", required_path, 0, f"缺少正式知识硬映射子目录：{required}")

        for file in formal_root.rglob("*.md"):
            relative = relpath(file, root)
            if "/01_" in f"/{relative}" and ("目录" in file.name or "总览" in file.name):
                continue
            formal_files.append(file)
            text = text_cache.get(file, read_text(file))

            if file.parent == root / "02_正式知识/20_产品介绍":
                add_formal("FORMAL_FILE_AT_MODULE_ROOT", file, 1, "产品正式知识不得直接放在产品介绍根目录；必须进入三个规定子目录之一")
            if file.parent == root / "02_正式知识/50_行业知识与洞察":
                add_formal("FORMAL_FILE_AT_MODULE_ROOT", file, 1, "行业正式知识不得直接放在行业知识与洞察根目录；必须按来源进入规定子目录")

            for match in re.finditer(r"\]\(([^)]+)\)|\[\[([^\]]+)\]\]", text):
                target = " ".join(group or "" for group in match.groups())
                if "30_文章写作输入" in target or "40_最终文章与引用率" in target:
                    add_formal("FORMAL_FROM_ARTICLE", file, line_number(text, match.start()), "正式知识不得把写作输入或最终文章作为事实来源")

            for field in FORMAL_FILE_FIELDS:
                if not parse_formal_field(text, field):
                    add_formal("FORMAL_REQUIRED_FIELD", file, 1, f"正式知识缺少文件级字段：{field}")
            if not (parse_formal_field(text, "稳定实体键") or parse_formal_field(text, "稳定主题键")):
                add_formal("FORMAL_REQUIRED_FIELD", file, 1, "正式知识缺少稳定实体键或稳定主题键")
            for heading in ("已处理内容", "使用限制", "来源"):
                if section_body(text, heading) is None:
                    add_formal("FORMAL_REQUIRED_SECTION", file, 1, f"正式知识缺少小节：{heading}")

            file_id = parse_formal_field(text, "知识ID")
            if file_id and file_id not in {"未分配", "无"}:
                formal_file_ids[file_id] = file

            formal_type = parse_formal_field(text, "正式知识类型") or ""
            if formal_type and formal_type not in FORMAL_TYPES:
                add_formal("FORMAL_TYPE_INVALID", file, 1, f"正式知识类型不在固定枚举中：{formal_type}")
            expected_prefix = FORMAL_TYPE_DIRS.get(formal_type)
            if expected_prefix and not relative.startswith(expected_prefix):
                add_formal("FORMAL_TYPE_WRONG_DIR", file, 1, f"正式知识类型“{formal_type}”必须位于：{expected_prefix}")
            if relative.startswith("02_正式知识/20_产品介绍/") and formal_type not in {"产品类目", "产品主数据", "重点产品卡"}:
                add_formal("PRODUCT_FORMAL_TYPE", file, 1, "产品正式知识必须声明正式知识类型为产品类目、产品主数据或重点产品卡")

            source_type = parse_formal_field(text, "来源类型") or ""
            if relative.startswith("02_正式知识/50_行业知识与洞察/"):
                if source_type in {"企业提供", "客户源文件", "客户官网"} and "/10_企业提供/" not in f"/{relative}":
                    add_formal("INDUSTRY_SOURCE_WRONG_DIR", file, 1, "企业提供的行业知识必须进入10_企业提供目录")
                if source_type == "Codex外部调研" and "/20_Codex外部调研/" not in f"/{relative}":
                    add_formal("INDUSTRY_SOURCE_WRONG_DIR", file, 1, "Codex外部调研行业知识必须进入20_Codex外部调研目录")

            claims = formal_claim_blocks(text)
            if not claims:
                add_formal("FORMAL_CLAIM_MISSING", file, 1, "正式知识不能只保留摘要；“已处理内容”中至少需要一个可独立核验的CLAIM块")
            for claim_name, block, claim_line in claims:
                claim_id = claim_name.split("｜", 1)[0].strip()
                if claim_id in formal_claim_ids:
                    add_formal(
                        "DUPLICATE_FORMAL_CLAIM_ID",
                        file,
                        claim_line,
                        f"CLAIM ID重复；另一处为{relpath(formal_claim_ids[claim_id], root)}：{claim_id}",
                    )
                else:
                    formal_claim_ids[claim_id] = file
                for field in FORMAL_CLAIM_FIELDS:
                    if not parse_field(block, field):
                        add_formal("FORMAL_CLAIM_FIELD", file, claim_line, f"{claim_name}缺少字段：{field}")
                stable_key = parse_field(block, "稳定实体键") or parse_field(block, "稳定主题键")
                if not is_substantive(stable_key):
                    add_formal("FORMAL_CLAIM_FIELD", file, claim_line, f"{claim_name}缺少稳定实体键或稳定主题键")
                verified = parse_field(block, "已核验事实") or parse_field(block, "已核验规则")
                if not is_substantive(verified):
                    add_formal("FORMAL_CLAIM_FIELD", file, claim_line, f"{claim_name}缺少已核验事实或已核验规则")
                claim_source = parse_field(block, "来源") or ""
                for field in ("适用范围", "不可外推", "来源", "精确位置"):
                    if parse_field(block, field) is not None and not is_substantive(parse_field(block, field)):
                        add_formal("FORMAL_CLAIM_VALUE", file, claim_line, f"{claim_name}字段不能使用空泛值：{field}")
                if "30_文章写作输入" in claim_source or "40_最终文章与引用率" in claim_source:
                    add_formal("FORMAL_FROM_ARTICLE", file, claim_line, f"{claim_name}把文章派生文件作为事实来源")

        index_file = formal_root / "01_正式知识目录/01_正式知识目录.md"
        if not index_file.is_file():
            add("ERROR", "MISSING_FORMAL_INDEX", index_file, 0, "缺少唯一正式知识目录")
        else:
            index_text = text_cache.get(index_file, read_text(index_file))
            for knowledge_id, file in formal_file_ids.items():
                if knowledge_id not in index_text:
                    add_formal("FORMAL_INDEX_MISSING_ID", file, 1, f"正式知识目录未登记知识ID：{knowledge_id}")

        for module_name, module_dir, overview_name in (
            ("产品介绍", formal_root / "20_产品介绍", "01_产品介绍总览.md"),
            ("行业知识与洞察", formal_root / "50_行业知识与洞察", "01_行业知识与洞察总览.md"),
        ):
            module_files = [file for file in formal_files if module_dir in file.parents]
            overview = module_dir / overview_name
            if not overview.is_file():
                add("ERROR", "MISSING_MODULE_OVERVIEW", overview, 0, f"缺少{module_name}总览")
            elif module_files:
                overview_text = text_cache.get(overview, read_text(overview))
                processed = section_body(overview_text, "已处理内容") or ""
                normalized = re.sub(r"[\s\-。；;]", "", processed)
                empty_overview = re.fullmatch(
                    r"(?:当前|本轮)?(?:无|暂无|未处理)(?:正式知识|已处理内容)?",
                    normalized,
                )
                if not processed or normalized in {"0", "零"} or empty_overview:
                    add("ERROR", "OVERVIEW_FORMAL_CONTRADICTION", overview, 1, f"{module_name}已有正式知识文件，但总览仍声明无已处理内容")

        deposition_log = root / DEPOSITION_EVENT_RELATIVE
        if not deposition_log.is_file():
            add("ERROR", "MISSING_DEPOSITION_EVENT_LOG", deposition_log, 0, "缺少正式知识沉淀事件记录")
        else:
            event_headers, _ = read_csv_rows(deposition_log)
            if event_headers != list(DEPOSITION_EVENT_HEADERS):
                add(
                    "ERROR",
                    "DEPOSITION_EVENT_SCHEMA",
                    deposition_log,
                    1,
                    "正式知识沉淀事件记录字段不符合v0.4固定结构，且不得包含文章使用字段",
                )
        if deposition_log.is_file() and formal_issue_files:
            log_text = read_text(deposition_log)
            if re.search(r"(?mi)(?:^|,)(?:completed|已沉淀|已完成)(?:,|$)", log_text):
                add("ERROR", "DEPOSITION_COMPLETED_WITH_FORMAL_ERRORS", deposition_log, 1, "存在正式知识错误时，沉淀记录不得标记completed/已沉淀/已完成")

    clean_dir = root / "04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿"
    clean_ids: dict[str, Path] = {}
    clean_languages: dict[str, str | None] = {}
    clean_statuses: dict[str, str] = {}
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

            required = ("对应原文件", "已确认范围", "范围确认", "核验状态", "原始语言", "清理正文语言", "内容类型")
            for field in required:
                if not parse_field(text, field):
                    add("ERROR", "CLEAN_REQUIRED_FIELD", file, 1, f"清理稿缺少字段：{field}")
            original_language = parse_field(text, "原始语言")
            clean_language = parse_field(text, "清理正文语言")
            if source_id:
                clean_languages[source_id] = normalize_language(clean_language or original_language)
                clean_statuses[source_id] = (parse_field(text, "核验状态") or "").strip()
            if normalize_language(original_language) and normalize_language(clean_language) != normalize_language(original_language):
                add("ERROR", "SOURCE_LANGUAGE_MISMATCH", file, 1, "清理稿必须保持源语言；目标语言内容应另建忠实翻译稿")
            if (parse_field(text, "内容类型") or "").strip().casefold() != "source-language-clean":
                add("ERROR", "SOURCE_LANGUAGE_MISMATCH", file, 1, "清理稿内容类型必须为source-language-clean")
            clean_body = section_body(text, "清理后的正文") or ""
            if strong_language_mismatch(clean_body, clean_language or original_language):
                add("ERROR", "SOURCE_LANGUAGE_MISMATCH", file, 1, "清理后的正文与声明语言明显不一致")
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

    translation_dir = root / "04_资料与证据/30_整理与翻译稿/20_翻译稿"
    translations: dict[str, list[tuple[Path, str | None, str, str | None]]] = {}
    if translation_dir.is_dir():
        for file in translation_dir.glob("*.md"):
            text = text_cache.get(file, read_text(file))
            source_id = parse_field(text, "资料ID")
            required = ("资料ID", "对应清理稿", "来源语言", "目标语言", "范围确认", "范围版本", "批准范围ID", "核验状态", "独立审核方", "内容类型")
            for field in required:
                if not parse_field(text, field):
                    add("ERROR", "TRANSLATION_REQUIRED_FIELD", file, 1, f"翻译稿缺少字段：{field}")
            if (parse_field(text, "内容类型") or "").strip().casefold() != "translation":
                add("ERROR", "TRANSLATION_REQUIRED_FIELD", file, 1, "翻译稿内容类型必须为translation")
            if source_id:
                translations.setdefault(source_id, []).append(
                    (
                        file,
                        normalize_language(parse_field(text, "目标语言")),
                        (parse_field(text, "核验状态") or "").strip(),
                        normalize_language(parse_field(text, "来源语言")),
                    )
                )

    for source_id, source_language in clean_languages.items():
        if source_language == "en" or clean_statuses.get(source_id) != "已核验":
            continue
        matching = [item for item in translations.get(source_id, []) if item[1] == "en"]
        clean_file = clean_ids[source_id]
        if not matching:
            add("ERROR", "REQUIRED_TRANSLATION_MISSING", clean_file, 1, f"{source_id}的来源语言不是英语，缺少独立英语忠实翻译稿")
            continue
        if not any(item[2] == "已核验" for item in matching):
            add("ERROR", "TRANSLATION_NOT_VERIFIED", matching[0][0], 1, f"{source_id}的英语忠实翻译稿尚未核验")
        for file, _, _, declared_source in matching:
            if declared_source and source_language and declared_source != source_language:
                add("ERROR", "TRANSLATION_SOURCE_LANGUAGE_MISMATCH", file, 1, f"翻译稿来源语言与{source_id}清理稿声明不一致")

    candidate_file = root / CANDIDATE_RELATIVE
    candidate_text = ""
    if not candidate_file.is_file():
        add("ERROR", "MISSING_CANDIDATE_LEDGER", candidate_file, 0, "缺少唯一知识就绪队列：10_知识候选分流.md")
    else:
        candidate_text = read_text(candidate_file)
        gate_table = find_markdown_table(candidate_text, CANDIDATE_GATE_HEADERS)
        candidate_gates: dict[str, tuple[int, dict[str, str]]] = {}
        if gate_table is None or gate_table[0] != list(CANDIDATE_GATE_HEADERS):
            add("ERROR", "CANDIDATE_GATE_SCHEMA", candidate_file, 1, "知识候选分流缺少v0.4固定的候选沉淀门禁表")
        else:
            for gate_line, gate_row in gate_table[1]:
                gate_id = gate_row.get("候选ID", "")
                if gate_id:
                    candidate_gates[gate_id] = (gate_line, gate_row)
        candidate_table = find_markdown_table(candidate_text, CANDIDATE_HEADERS)
        if candidate_table is None:
            add("ERROR", "CANDIDATE_LEDGER_SCHEMA", candidate_file, 1, "知识候选分流表缺少v0.4固定字段")
        else:
            headers, rows = candidate_table
            if headers != list(CANDIDATE_HEADERS):
                add("ERROR", "CANDIDATE_LEDGER_SCHEMA", candidate_file, 1, "知识候选分流表字段顺序或数量不符合v0.4固定结构")
            seen_candidates: set[str] = set()
            for line, row in rows:
                candidate_id = row.get("候选ID", "")
                status = row.get("处理状态", "")
                target = row.get("正式知识ID或处理位置", "")
                issue = row.get("校验结果/异常", "")
                if not candidate_id:
                    add("ERROR", "CANDIDATE_ID_MISSING", candidate_file, line, "知识候选缺少候选ID")
                elif candidate_id in seen_candidates:
                    add("ERROR", "DUPLICATE_CANDIDATE_ID", candidate_file, line, f"候选ID重复：{candidate_id}")
                seen_candidates.add(candidate_id)
                if status not in CANDIDATE_STATUSES:
                    add("ERROR", "CANDIDATE_STATUS_INVALID", candidate_file, line, f"知识候选状态无效：{status or '空值'}")
                if status == "可自动沉淀":
                    add("ERROR", "READY_CANDIDATE_NOT_DEPOSITED", candidate_file, line, "可自动沉淀只允许作为事务中间态；本轮结束前必须完成沉淀或记录真实异常")
                if status == "部分可沉淀" and (not is_substantive(issue) or not is_substantive(target)):
                    add("ERROR", "PARTIAL_CANDIDATE_UNRESOLVED", candidate_file, line, "部分可沉淀必须同时记录已沉淀位置和剩余CLAIM异常")
                if status == "已沉淀":
                    known_target = any(knowledge_id in target for knowledge_id in formal_file_ids) or any(
                        file.name in target or file.stem in target for file in formal_files
                    )
                    if not is_substantive(target) or not known_target:
                        add("ERROR", "DEPOSITED_CANDIDATE_TARGET", candidate_file, line, "已沉淀候选必须指向实际存在的正式知识ID或正式知识文件")
                gate_entry = candidate_gates.get(candidate_id)
                if gate_entry is None:
                    add("ERROR", "DEPOSITION_UPSTREAM_GATE_FAILED", candidate_file, line, f"候选{candidate_id or '（空ID）'}缺少上游门禁记录")
                elif status in {"可自动沉淀", "部分可沉淀", "已沉淀"}:
                    gate_line, gate_row = gate_entry
                    failed_fields: list[str] = []
                    for field in ("范围确认文件", "范围版本", "批准范围ID", "文章前审核文件", "文章前审核状态", "原文证据状态", "源语言清理状态", "独立审核状态"):
                        if not is_substantive(gate_row.get(field)):
                            failed_fields.append(field)
                    if gate_row.get("知识沉淀就绪", "").strip() != "通过":
                        failed_fields.append("知识沉淀就绪")
                    if not has_clickable_link(gate_row.get("范围确认文件", "")):
                        failed_fields.append("范围确认文件链接")
                    if not has_clickable_link(gate_row.get("文章前审核文件", "")):
                        failed_fields.append("文章前审核文件链接")
                    if gate_row.get("文章前审核状态", "").strip() not in {"已完成，无待修正", "已完成，受影响CLAIM已修正"}:
                        failed_fields.append("文章前审核状态")
                    audit_targets = [
                        target
                        for raw_target in iter_link_targets(gate_row.get("文章前审核文件", ""))
                        if (target := resolve_vault_target(candidate_file, raw_target, root, vault_files)) is not None
                    ]
                    if not audit_targets:
                        failed_fields.append("文章前审核文件解析")
                    else:
                        audit_body = section_body(text_cache.get(audit_targets[0], read_text(audit_targets[0])), "总体结论") or ""
                        valid_audit_conclusions = ("可以进入写作", "处理指定问题后可以进入写作", "暂不能进入写作")
                        if not any(conclusion in audit_body for conclusion in valid_audit_conclusions):
                            failed_fields.append("文章前审核结论未完成")
                    if failed_fields:
                        add(
                            "ERROR",
                            "DEPOSITION_UPSTREAM_GATE_FAILED",
                            candidate_file,
                            gate_line,
                            f"候选{candidate_id}上游门禁未通过：{'、'.join(dict.fromkeys(failed_fields))}",
                        )
                gate_text = " ".join(row.values())
                if re.search(r"文章未使用|未被文章使用|等待终稿|终稿未使用|待文章使用", gate_text):
                    add("ERROR", "ARTICLE_USE_AS_DEPOSIT_GATE", candidate_file, line, "文章是否使用或是否提交终稿不得作为知识沉淀条件")

        for source_id, file in clean_ids.items():
            clean_text = text_cache.get(file, read_text(file))
            if (parse_field(clean_text, "核验状态") or "").strip() == "已核验":
                if source_id not in candidate_text and file.name not in candidate_text and file.stem not in candidate_text:
                    add("ERROR", "VERIFIED_SOURCE_NOT_ROUTED", file, 1, "已核验清理稿未登记到知识候选分流表")

        external_root = root / "04_资料与证据/50_外部调研"
        if external_root.exists():
            for file in external_root.rglob("20_调研整理与核验.md"):
                text = text_cache.get(file, read_text(file))
                status = parse_field(text, "核验状态") or parse_field(text, "verification_status") or ""
                if status.strip().lower() in {"已核验", "通过", "verified", "passed"}:
                    relative = relpath(file, root)
                    if relative not in candidate_text and file.name not in candidate_text and file.stem not in candidate_text:
                        add("ERROR", "VERIFIED_EXTERNAL_NOT_ROUTED", file, 1, "已核验外部调研未登记到知识候选分流表")

    deposition_state = root / DEPOSITION_STATE_RELATIVE
    if not deposition_state.is_file():
        add("ERROR", "MISSING_DEPOSITION_STATE", deposition_state, 0, "缺少正式知识当前沉淀状态表")
    else:
        state_table = find_markdown_table(read_text(deposition_state), DEPOSITION_STATE_HEADERS)
        if state_table is None or state_table[0] != list(DEPOSITION_STATE_HEADERS):
            add("ERROR", "DEPOSITION_STATE_SCHEMA", deposition_state, 1, "知识沉淀记录缺少v0.4固定字段")

    usage_detail = root / CLAIM_USAGE_DETAIL_RELATIVE
    confirmed_articles: dict[str, set[str]] = {}
    pending_articles: dict[str, set[str]] = {}
    if not usage_detail.is_file():
        add("ERROR", "MISSING_CLAIM_USAGE_DETAIL", usage_detail, 0, "缺少CLAIM级知识块使用明细")
    else:
        usage_headers, usage_rows = read_csv_rows(usage_detail)
        if usage_headers != list(CLAIM_USAGE_HEADERS):
            add("ERROR", "CLAIM_USAGE_SCHEMA", usage_detail, 1, "知识块使用明细字段不符合v0.4固定结构")
        else:
            seen_usage: set[tuple[str, str, str]] = set()
            for line, row in usage_rows:
                claim_id = row["claim_id"]
                article_id = row["article_id"]
                status = row["usage_status"]
                key = (article_id, row["article_version"], claim_id)
                if key in seen_usage:
                    add("ERROR", "DUPLICATE_CLAIM_USAGE", usage_detail, line, f"同一文章版本与CLAIM存在重复当前关系：{article_id}/{claim_id}")
                seen_usage.add(key)
                if status not in CLAIM_USAGE_STATUSES:
                    add("ERROR", "CLAIM_USAGE_STATUS", usage_detail, line, f"CLAIM使用状态无效：{status or '空值'}")
                if claim_id and claim_id not in formal_claim_ids:
                    add("ERROR", "CLAIM_USAGE_UNKNOWN_CLAIM", usage_detail, line, f"使用明细引用不存在的正式CLAIM：{claim_id}")
                if status == "已确认使用":
                    required_values = ("article_id", "claim_id", "knowledge_path", "article_location", "source_location", "confirmed_at", "citation_manifest")
                    missing = [field for field in required_values if not row[field]]
                    if missing:
                        add("ERROR", "CONFIRMED_USAGE_INCOMPLETE", usage_detail, line, f"已确认使用缺少定位字段：{'、'.join(missing)}")
                    if article_id and claim_id:
                        confirmed_articles.setdefault(claim_id, set()).add(article_id)
                elif status == "尚未核对":
                    if row["confirmed_at"]:
                        add("ERROR", "UNVERIFIED_USAGE_CONFIRMED", usage_detail, line, "尚未核对的关系不得填写确认时间或计入使用次数")
                    if article_id and claim_id:
                        pending_articles.setdefault(claim_id, set()).add(article_id)

    usage_total = root / CLAIM_USAGE_TOTAL_RELATIVE
    if not usage_total.is_file():
        add("ERROR", "MISSING_CLAIM_USAGE_TOTAL", usage_total, 0, "缺少CLAIM级知识块使用总表")
    else:
        total_table = find_markdown_table(read_text(usage_total), CLAIM_TOTAL_HEADERS)
        if total_table is None or total_table[0] != list(CLAIM_TOTAL_HEADERS):
            add("ERROR", "CLAIM_USAGE_TOTAL_SCHEMA", usage_total, 1, "知识块使用总表缺少v0.4固定字段")
        else:
            seen_totals: set[str] = set()
            for line, row in total_table[1]:
                claim_id = row["CLAIM ID"]
                if claim_id in seen_totals:
                    add("ERROR", "DUPLICATE_CLAIM_TOTAL", usage_total, line, f"知识块使用总表重复CLAIM：{claim_id}")
                seen_totals.add(claim_id)
                try:
                    total_count = int(row["累计使用次数"])
                    pending_count = int(row["尚未核对文章数"])
                except ValueError:
                    add("ERROR", "CLAIM_USAGE_TOTAL_COUNT", usage_total, line, "累计使用次数和尚未核对文章数必须为整数")
                    continue
                expected_total = len(confirmed_articles.get(claim_id, set()))
                expected_pending = len(pending_articles.get(claim_id, set()))
                if total_count != expected_total or pending_count != expected_pending:
                    add("ERROR", "CLAIM_USAGE_TOTAL_MISMATCH", usage_total, line, f"CLAIM汇总与使用明细不一致：应为使用{expected_total}、尚未核对{expected_pending}")
            for claim_id, file in formal_claim_ids.items():
                if claim_id not in seen_totals:
                    add("ERROR", "FORMAL_CLAIM_NOT_IN_USAGE_TOTAL", file, 1, f"正式CLAIM未进入知识块使用总表：{claim_id}")

    manifest_dir = root / CLAIM_MANIFEST_DIR_RELATIVE
    manifest_files = sorted(manifest_dir.glob("*.md")) if manifest_dir.is_dir() else []
    if not manifest_dir.is_dir():
        add("ERROR", "MISSING_CLAIM_MANIFEST_DIR", manifest_dir, 0, "缺少文章CLAIM引用清单目录")
    manifest_texts: dict[Path, str] = {}
    for file in manifest_files:
        text = read_text(file)
        manifest_texts[file] = text
        table = find_markdown_table(text, CLAIM_MANIFEST_HEADERS)
        if table is None or table[0] != list(CLAIM_MANIFEST_HEADERS):
            add("ERROR", "CLAIM_MANIFEST_SCHEMA", file, 1, "文章引用清单缺少CLAIM级固定字段")
            continue
        for line, row in table[1]:
            status = row["使用判断"]
            if status not in CLAIM_USAGE_STATUSES:
                add("ERROR", "CLAIM_MANIFEST_STATUS", file, line, f"文章引用清单使用判断无效：{status or '空值'}")
            if status == "已确认使用":
                missing = [field for field in ("文章位置/主张", "CLAIM ID", "正式知识位置", "原始来源与精确位置") if not row[field]]
                if missing:
                    add("ERROR", "CLAIM_MANIFEST_CONFIRMED_INCOMPLETE", file, line, f"已确认使用缺少定位字段：{'、'.join(missing)}")
            if row["CLAIM ID"] and row["CLAIM ID"] not in formal_claim_ids:
                add("ERROR", "CLAIM_MANIFEST_UNKNOWN_CLAIM", file, line, f"文章引用清单引用不存在的正式CLAIM：{row['CLAIM ID']}")

    for status, article_dir in article_dirs:
        article_id = article_dir.name.split("_", 1)[0]
        for name in ARTICLE_FILES:
            if not (article_dir / name).is_file():
                add("ERROR", "MISSING_ARTICLE_FILE", article_dir, 0, f"文章任务缺少固定文件：{name}")

        scope = article_dir / "15_提取范围与处理样本确认.md"
        scope_text = text_cache.get(scope, read_text(scope)) if scope.is_file() else ""
        range_table = find_markdown_table(scope_text, SCOPE_RANGE_HEADERS) if scope_text else None
        scope_started = bool(
            parse_field(scope_text, "范围版本")
            or parse_field(scope_text, "当前状态")
            or (range_table and range_table[1])
        )
        if scope_started:
            current_state = (parse_field(scope_text, "当前状态") or "").strip()
            if current_state != "已人工确认":
                add("ERROR", "SCOPE_HUMAN_APPROVAL_REQUIRED", scope, 1, "已开始处理的文章范围必须由真实人工确认后才能进入下游")
            required_scope_fields = (
                "范围版本",
                "确认方式",
                "确认人",
                "确认时间",
                "决定",
                "批准范围ID",
                "批准样本组ID",
                "外部调研决定",
                "人工原话摘要",
            )
            missing_scope = [field for field in required_scope_fields if not is_substantive(parse_field(scope_text, field))]
            if missing_scope:
                add("ERROR", "SCOPE_APPROVAL_DETAIL_MISSING", scope, 1, f"人工范围确认缺少：{'、'.join(missing_scope)}")
            if (parse_field(scope_text, "确认方式") or "").strip() != "人工确认":
                add("ERROR", "SCOPE_HUMAN_APPROVAL_REQUIRED", scope, 1, "确认方式必须明确为人工确认")
            if not field_is_human_identity(parse_field(scope_text, "确认人")):
                add("ERROR", "SCOPE_HUMAN_APPROVAL_REQUIRED", scope, 1, "确认人必须是真实人工姓名，不能填写Skill、Codex、Agent或AI知识库专员")
            if re.search(r"(?i)(?:可以继续|继续处理).{0,40}(?:视为|等同|代表).{0,20}(?:范围确认|批准)|(?:Skill|Codex|Agent).{0,20}(?:自动确认|一致同意)", scope_text):
                add("ERROR", "GENERIC_CONTINUE_USED_AS_APPROVAL", scope, 1, "通用的‘可以继续’或Agent一致意见不能替代本文章、本范围版本的人工确认")
            research_decision = (parse_field(scope_text, "外部调研决定") or "").strip()
            if not (
                research_decision in {"若缺口仍存在则开展", "不开展"}
                or research_decision.startswith("仅研究指定问题：")
            ):
                add("ERROR", "RESEARCH_DECISION_MISSING", scope, 1, "范围确认必须给出条件式外部调研决定")

            if range_table is None or range_table[0] != list(SCOPE_RANGE_HEADERS) or not range_table[1]:
                add("ERROR", "SCOPE_APPROVAL_DETAIL_MISSING", scope, 1, "范围确认缺少固定范围总览表或有效范围行")
            else:
                approved_ids = split_ids(parse_field(scope_text, "批准范围ID"))
                table_ids = {row.get("范围ID", "").strip() for _, row in range_table[1] if row.get("范围ID", "").strip()}
                if not approved_ids or not approved_ids.issubset(table_ids):
                    add("ERROR", "SCOPE_APPROVAL_DETAIL_MISSING", scope, 1, "批准范围ID必须逐项对应范围总览中的现存范围ID")

                web_required = any(
                    re.search(r"https?://", row.get("原文件/运营稿/网页直达链接", ""), re.I)
                    for _, row in range_table[1]
                    if row.get("范围ID", "").strip() in approved_ids
                )
                if web_required:
                    web_table = find_markdown_table(scope_text, SCOPE_WEB_HEADERS)
                    if web_table is None or web_table[0] != list(SCOPE_WEB_HEADERS) or not web_table[1]:
                        add("ERROR", "WEB_INTERACTION_STATE_MISSING", scope, 1, "网页范围缺少逐状态的网页交互与表格覆盖记录")
                    else:
                        for line, row in web_table[1]:
                            acquisition = row.get("取得状态", "").strip()
                            if acquisition == "不适用":
                                continue
                            required_web = (
                                "状态ID",
                                "页面/表格",
                                "控件名称",
                                "切换动作",
                                "状态标识或结果指纹",
                                "完整表头",
                                "文章相关完整行数",
                                "原文证据位置",
                                "取得状态",
                            )
                            missing_web = [field for field in required_web if not is_substantive(row.get(field))]
                            if missing_web or acquisition not in {"完整", "已取得"}:
                                add("ERROR", "WEB_TABLE_ROWS_MISSING", scope, line, f"网页状态记录不完整：{'、'.join(missing_web) or acquisition}")

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
            matching_manifests = [
                file
                for file, text in manifest_texts.items()
                if article_id in file.name or re.search(rf"(?m)^-\s*文章ID\s*[：:]\s*{re.escape(article_id)}\s*$", text)
            ]
            if not matching_manifests:
                add("ERROR", "COMPLETED_ARTICLE_MISSING_CLAIM_MANIFEST", article_dir, 0, "已完成文章缺少CLAIM级文章引用清单；未完成回对时也必须建立清单并标记尚未核对")
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

    if completed_ids and version_entry_file.is_file():
        version_text = text_cache.get(version_entry_file, read_text(version_entry_file))
        for article_id in completed_ids:
            if article_id not in version_text:
                add("ERROR", "COMPLETED_ARTICLE_MISSING_VERSION_EVENT", version_entry_file, 1, f"已完成文章{article_id}没有对应的项目级完成变更记录")

    return sorted(issues, key=lambda item: (item.severity != "ERROR", item.file, item.line, item.code))


def create_self_test_project(root: Path) -> None:
    for name in REQUIRED_TOP_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    for path in (
        "02_正式知识/01_正式知识目录",
        "02_正式知识/20_产品介绍/10_产品类目",
        "02_正式知识/20_产品介绍/20_产品主数据",
        "02_正式知识/20_产品介绍/30_重点产品卡",
        "02_正式知识/50_行业知识与洞察/10_企业提供",
        "02_正式知识/50_行业知识与洞察/20_Codex外部调研",
        "03_文章任务/01_文章总览",
        "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章",
        "04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿",
        "04_资料与证据/30_整理与翻译稿/20_翻译稿",
        "05_数据与审核/01_检查入口",
        "05_数据与审核/10_知识沉淀与分流",
        "05_数据与审核/20_知识使用与引用/40_文章引用清单",
        "05_数据与审核/30_异常与待决定/10_企业知识异常待处理",
        "05_数据与审核/30_异常与待决定/30_Skill运行反馈",
    ):
        (root / path).mkdir(parents=True, exist_ok=True)

    source_register = root / "04_资料与证据/10_源文件登记/01_源文件总表.md"
    source_register.parent.mkdir(parents=True, exist_ok=True)
    source_register.write_text(
        "# 源文件总表\n\n| 资料ID | 原文件名 | 相对路径 | 格式 | 可读性 | 指纹 | 版本或重复关系 | 处理状态 | 内容导航 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| TEST-SRC-VID-001 | test.mp4 | test.mp4 | mp4 | 仅登记媒体身份 | test-video-sha256 | 独立资料 | 待专员判断→TEST-MAT-001 | 见媒体登记 |\n"
        "| TEST-SRC-DOC-001 | main.docx | main.docx | docx | 可读取 | test-doc-sha256 | 主文件 | 待处理 | [内容导航](04_资料与证据/10_源文件登记/20_内容导航/TEST-SRC-DOC-001_内容导航.md) |\n",
        encoding="utf-8",
    )
    nav_fixture = root / "04_资料与证据/10_源文件登记/20_内容导航/TEST-SRC-DOC-001_内容导航.md"
    nav_fixture.parent.mkdir(parents=True, exist_ok=True)
    nav_fixture.write_text(
        "# main.docx｜内容导航\n\n- 资料ID：TEST-SRC-DOC-001\n- 原文件：main.docx\n\n"
        "## 内容位置\n\n"
        "| 位置 | 原始标题路径 | 内容说明 | 语言 | 带文字的表格、图示或特殊结构 | 提取状态 | 可能归属模块 | 定位限制 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| Word正文/第1个标题 | 产品概述 | 产品用途、适用范围和主要组成的连续段落 | 中文 | 无 | 未提取；等待文章范围确认 | 产品介绍 | 回到原文件标题定位 |\n",
        encoding="utf-8",
    )

    (root / WORKBENCH_TODO_RELATIVE).write_text(
        "# 当前待办\n\n- 项目ID：TEST\n- 更新日期：2026-08-11\n- 当前节点：测试完成\n- 当前状态：测试项目已完成\n"
        "- 待客户补充事项：[[05_数据与审核/30_异常与待决定/10_企业知识异常待处理/01_待客户补充事项]]\n"
        "- 源文与事实异常：[[05_数据与审核/30_异常与待决定/10_企业知识异常待处理/02_源文与事实异常台账]]\n"
        "- 源资料处理待办：[[05_数据与审核/30_异常与待决定/10_企业知识异常待处理/03_源资料处理待办]]\n"
        "- Skill运行反馈：[[05_数据与审核/30_异常与待决定/30_Skill运行反馈/01_Skill反馈台账]]\n",
        encoding="utf-8",
    )
    (root / VERSION_ENTRY_RELATIVE).write_text(
        "# 版本与变更入口\n\n- 项目ID：TEST\n- 当前状态：[[20_当前待办]]\n- 使用Skill：manage-article-knowledge v0.4\n"
        f"- Skill版本日期：2026-08-12\n- Skill指纹：{sha256_file(skill_file())}\n- 初始化日期：2026-08-06\n- 最近项目级变更：2026-08-11｜测试文章完成\n\n"
        "## 项目级变更\n\n| 日期 | 变更 | 依据 | 执行人 | 关联对象 | 影响范围 |\n|---|---|---|---|---|---|\n"
        "| 2026-08-11 | 测试文章完成 | 终稿闭环 | Codex | TEST-ART-001 | 文章任务与数据 |\n\n"
        "## 相关入口\n\n- [当前待办](20_当前待办.md)\n"
        "- [待客户补充事项](../05_数据与审核/30_异常与待决定/10_企业知识异常待处理/01_待客户补充事项.md)\n"
        "- [源文与事实异常](../05_数据与审核/30_异常与待决定/10_企业知识异常待处理/02_源文与事实异常台账.md)\n"
        "- [源资料处理待办](../05_数据与审核/30_异常与待决定/10_企业知识异常待处理/03_源资料处理待办.md)\n"
        "- [Skill运行反馈](../05_数据与审核/30_异常与待决定/30_Skill运行反馈/01_Skill反馈台账.md)\n",
        encoding="utf-8",
    )
    (root / CHECK_ENTRY_RELATIVE).write_text(
        "# 当前待办检查入口\n\n- [工作台当前待办](../../01_工作台/20_当前待办.md)\n"
        "- [待客户补充事项](../30_异常与待决定/10_企业知识异常待处理/01_待客户补充事项.md)\n"
        "- [源文与事实异常](../30_异常与待决定/10_企业知识异常待处理/02_源文与事实异常台账.md)\n"
        "- [源资料处理待办](../30_异常与待决定/10_企业知识异常待处理/03_源资料处理待办.md)\n"
        "- [Skill运行反馈](../30_异常与待决定/30_Skill运行反馈/01_Skill反馈台账.md)\n",
        encoding="utf-8",
    )
    (root / SKILL_FEEDBACK_RELATIVE).write_text(
        "# Skill反馈台账\n\n- 项目ID：TEST\n- 最近检查日期：2026-08-11\n\n## 当前反馈\n\n"
        "| 反馈ID | 人话说明 | 提出来源 | 类型 | 当前阶段 | 影响 | 下一步 | 最近更新 |\n"
        "|---|---|---|---|---|---|---|---|\n\n## 反馈详情\n\n## 已关闭与不纳入\n",
        encoding="utf-8",
    )

    article = root / "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章"
    (article / "01_文章要求与大纲.md").write_text("# 文章要求与大纲\n\n- 目标语言：中文\n\n## 大纲\n\n1. 测试主题\n", encoding="utf-8")
    for name in ARTICLE_FILES[1:4]:
        (article / name).write_text(f"# {name[:-3]}\n", encoding="utf-8")
    (article / "15_提取范围与处理样本确认.md").write_text(
        "# 提取范围与处理样本确认\n\n"
        "- 文章ID：TEST-ART-001\n- 生成日期：2026-08-06\n- 依据文件版本：test-sha256\n- 范围版本：v1\n- 当前状态：已人工确认\n\n"
        "## 范围总览\n\n"
        "| 范围ID | 资料ID与名称 | 原文件/运营稿/网页直达链接 | 原始语言 | 精确位置 | 该位置实际包含什么 | 拟提取主题与字段 | 附件/图片/复杂结构 | 处理样本组 | 排除范围 | 输出位置 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| TEST-RNG-001 | TEST-SRC-001｜测试PDF | test.pdf | 中文 | PDF p.1 | 测试正文 | 测试事实 | 无 | TEST-SMP-001 | 无 | 清理稿 |\n\n"
        "## 代表处理样本\n\n"
        "| 样本组ID | 处理结构与版本 | 代表来源位置 | 原稿/截图定位 | 拟转写或解读结果 | 需确认的关系与不确定点 | 可复用范围 | 新结构触发条件 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| TEST-SMP-001 | 正文v1 | PDF p.1 | test.pdf p.1 | 保留原文 | 无 | 同结构段落 | 新结构时重审 |\n\n"
        "## 预计缺口与条件式外部调研\n\n"
        "| 调研问题ID | 对应大纲/主张 | 为什么本地资料预计不能覆盖 | 允许的来源与时间范围 | 不得用于证明 | 人工决定 |\n"
        "|---|---|---|---|---|---|\n"
        "| 不适用 | 测试主题 | 无缺口 | 不适用 | 不适用 | 不开展 |\n\n"
        "## 确认记录\n\n"
        "- 确认方式：人工确认\n- 确认人：测试审核人\n- 确认时间：2026-08-06 10:00 +08:00\n- 范围版本：v1\n"
        "- 决定：确认\n- 修改：无\n- 批准范围ID：TEST-RNG-001\n- 批准样本组ID：TEST-SMP-001\n"
        "- 外部调研决定：不开展\n- 人工原话摘要：确认上述范围和样本，可按v1处理。\n",
        encoding="utf-8",
    )
    (article / "20_文章前知识审核.md").write_text(
        "# 文章前知识审核\n\n- 当前写作输入：[当前写作输入](30_文章写作输入.md)\n\n## 总体结论\n\n可以进入写作\n\n## 写作输入保真复核\n\n- 复核对象：[当前写作输入](30_文章写作输入.md)\n- 采用范围与未迁入理由：已逐块核对\n- 完整段落及限定条件：通过\n- 表格、公式、数字、单位和脚注：不适用\n- 多来源分块与来源定位：通过\n- 摘要、知识点卡或AI综合正文检查：通过\n- 结论：通过\n",
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
        "# 测试｜清理与字段统一稿\n\n- 资料ID：TEST-SRC-001\n- 对应原文件：test.pdf\n- 对应运营Markdown：test.md\n- 已确认范围：PDF p.1\n- 范围确认：[确认](" + scope_link + ")\n- 原始语言：中文\n- 清理正文语言：中文\n- 内容类型：source-language-clean\n- 核验状态：已核验\n- 原始表格数（确认范围内）：0\n- 当前保留表格数：0\n- 原始公式数（确认范围内）：0\n- 当前保留公式数：0\n- 结构排除说明：不适用\n\n## 位置与正文结构定位\n\nPDF p.1\n\n## 清理后的正文\n\n测试正文。\n\n## 差异与补核记录\n\n确认范围内未发现需要补核的结构或文字差异。\n\n## 未处理或明确排除范围\n\n- 无\n\n## 来源与回溯\n\n- 原文件：test.pdf\n",
        encoding="utf-8",
    )

    translation = root / "04_资料与证据/30_整理与翻译稿/20_翻译稿/TEST-SRC-001_英语忠实翻译稿.md"
    translation.write_text(
        "# 测试｜英语忠实翻译稿\n\n"
        "- 资料ID：TEST-SRC-001\n"
        "- 对应清理稿：[测试清理稿](../10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md)\n"
        "- 范围确认：[确认](../../../03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/15_提取范围与处理样本确认.md)\n"
        "- 范围版本：v1\n- 批准范围ID：TEST-RNG-001\n- 来源语言：中文\n- 目标语言：英语\n"
        "- 内容类型：translation\n- 核验状态：已核验\n- 独立审核方：审核Agent\n\n"
        "## 逐段与逐表翻译\n\n"
        "| 来源位置 | 来源块ID | 英语完整译文 | 原有英文保留核验 | 数字/单位/脚注核验 | 术语依据 | 核验状态 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| PDF p.1 | TEST-BLK-001 | Test body. | 不适用 | 通过 | 不适用 | 已核验 |\n\n"
        "## 未翻译或异常范围\n\n- 无\n",
        encoding="utf-8",
    )

    formal = root / "02_正式知识/50_行业知识与洞察/10_企业提供/测试主题.md"
    formal.write_text(
        "# 测试主题\n\n- 知识ID：KB-TEST-IND-001\n- 正式知识类型：行业知识\n- 稳定主题键：industry:test-topic\n- 知识状态：有效\n- 来源类型：企业提供\n- 数据或版本日期：2026-08-06\n- 最近核验日期：2026-08-06\n- 使用前复核：否\n\n## 已处理内容\n\n### CLAIM-TEST-IND-001-01｜测试事实\n\n- 知识ID：KB-TEST-IND-001-01\n- 稳定主题键：industry:test-topic\n- 知识类型：事实\n- 已核验事实：测试资料在PDF第1页明确给出测试正文。\n- 适用范围：测试项目与该测试主题\n- 不可外推：不得外推为其他项目或其他主题的事实\n- 来源：[测试清理稿](../../../04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md)\n- 精确位置：PDF p.1，清理后的正文\n- 数据日期：2026-08-06\n- 使用前复核：否\n\n## 使用限制\n\n仅用于测试。\n\n## 来源\n\n- [测试清理稿](../../../04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md)\n",
        encoding="utf-8",
    )

    (root / "02_正式知识/01_正式知识目录/01_正式知识目录.md").write_text(
        "# 正式知识目录\n\n| 知识ID | 稳定实体/主题键 | 标题 | 模块 | 正式知识位置 | 当前状态 | 数据日期/最近核验 |\n|---|---|---|---|---|---|---|\n| KB-TEST-IND-001 | industry:test-topic | 测试主题 | 行业知识 | 测试主题.md | 有效 | 2026-08-06 |\n",
        encoding="utf-8",
    )
    (root / "02_正式知识/20_产品介绍/01_产品介绍总览.md").write_text(
        "# 产品介绍总览\n\n## 已处理内容\n\n- 无\n",
        encoding="utf-8",
    )
    (root / "02_正式知识/50_行业知识与洞察/01_行业知识与洞察总览.md").write_text(
        "# 行业知识与洞察总览\n\n## 已处理内容\n\n- KB-TEST-IND-001｜测试主题\n",
        encoding="utf-8",
    )

    (root / CANDIDATE_RELATIVE).write_text(
        "# 知识候选分流\n\n"
        "| 候选ID | 内容主题 | 来源类型 | 就绪来源文件 | 原文精确位置 | 稳定实体/主题键 | 主归属模块 | 预定正式路径 | CLAIM数量 | 处理状态 | 校验结果/异常 | 正式知识ID或处理位置 | 最近更新 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| TEST-CAND-001 | 测试主题 | 客户源文件 | TEST-SRC-001_测试_清理与字段统一稿.md | PDF p.1 | industry:test-topic | 行业知识与洞察/企业提供 | 02_正式知识/50_行业知识与洞察/10_企业提供/测试主题.md | 1 | 已沉淀 | 通过 | KB-TEST-IND-001 | 2026-08-06 |\n\n"
        "## 候选沉淀门禁\n\n"
        "| 候选ID | 范围确认文件 | 范围版本 | 批准范围ID | 文章前审核文件 | 文章前审核状态 | 原文证据状态 | 网页交互覆盖 | 表格完整性 | 源语言清理状态 | 独立审核状态 | 知识沉淀就绪 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| TEST-CAND-001 | [范围确认](../../03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/15_提取范围与处理样本确认.md) | v1 | TEST-RNG-001 | [文章前审核](../../03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/20_文章前知识审核.md) | 已完成，无待修正 | 完整 | 不适用 | 不适用 | 已核验 | 已通过 | 通过 |\n",
        encoding="utf-8",
    )
    (root / DEPOSITION_STATE_RELATIVE).write_text(
        "# 知识沉淀记录\n\n"
        "| 知识ID | 稳定实体或主题键 | 标题 | 来源类型 | 原始来源 | 处理状态 | 主归属模块 | 正式知识位置 | 数据或版本日期 | 更新条件 | 使用限制或待决定事项 | 最近更新日期 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| KB-TEST-IND-001 | industry:test-topic | 测试主题 | 客户源文件 | TEST-SRC-001 | 已沉淀 | 行业知识与洞察/企业提供 | 测试主题.md | 2026-08-06 | 来源变化 | 仅用于测试 | 2026-08-06 |\n",
        encoding="utf-8",
    )
    (root / DEPOSITION_EVENT_RELATIVE).write_text(
        "date,knowledge_id,claim_ids,entity_key,action,formal_file,heading,source_refs,source_ready_artifact,status,operator,notes\n"
        "2026-08-06,KB-TEST-IND-001,CLAIM-TEST-IND-001-01,industry:test-topic,create,测试主题.md,测试事实,TEST-SRC-001,TEST-SRC-001_测试_清理与字段统一稿.md,completed,Codex,test\n",
        encoding="utf-8-sig",
    )
    (root / CLAIM_USAGE_DETAIL_RELATIVE).write_text(
        "project_id,article_id,article_title,article_version,claim_id,knowledge_id,knowledge_title,knowledge_path,article_location,source_location,use_type,usage_status,confirmed_at,issue_flag,citation_manifest\n"
        "TEST,TEST-ART-001,测试文章,v1,CLAIM-TEST-IND-001-01,KB-TEST-IND-001,测试主题,02_正式知识/50_行业知识与洞察/10_企业提供/测试主题.md,正文第1段,TEST-SRC-001/PDF p.1,直接事实,已确认使用,2026-08-06,,TEST-ART-001.md\n",
        encoding="utf-8-sig",
    )
    (root / CLAIM_USAGE_TOTAL_RELATIVE).write_text(
        "# 知识块使用总表\n\n"
        "| CLAIM ID | 所属正式知识ID | 标题 | 正式知识位置 | 来源类型 | 已确认使用文章 | 累计使用次数 | 尚未核对文章数 | 最近使用日期 | 异常数 | 当前追踪状态 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| CLAIM-TEST-IND-001-01 | KB-TEST-IND-001 | 测试事实 | 测试主题.md | 企业提供 | TEST-ART-001 | 1 | 0 | 2026-08-06 | 0 | 正常 |\n",
        encoding="utf-8",
    )
    (root / DATA_EXPLANATION_RELATIVE).write_text(
        "# 数据说明\n\n- 最近检查日期：2026-08-11\n\n## 受管非Markdown数据文件\n\n"
        "| 文件 | 类型 | 用途 | 维护责任 | 是否允许人工编辑 | 更新触发 | 查看方式 | 编码/格式 | 最近校验 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| [正式知识沉淀记录](../10_知识沉淀与分流/40_正式知识沉淀记录.csv) | CSV | 沉淀事件 | 主Agent | 否 | 正式知识变更 | Excel或CSV工具 | UTF-8 with BOM | 2026-08-11，通过 |\n"
        "| [知识块使用明细](20_知识块使用明细.csv) | CSV | CLAIM使用关系 | 主Agent | 否 | 终稿核对 | Excel或CSV工具 | UTF-8 with BOM | 2026-08-11，通过 |\n\n"
        "## 数据口径与查看说明\n\n- CSV保存逐行机器明细，本页不复制完整数据行。\n",
        encoding="utf-8",
    )
    (root / CLAIM_MANIFEST_DIR_RELATIVE / "TEST-ART-001.md").write_text(
        "# 文章引用清单\n\n- 文章ID：TEST-ART-001\n- 标题：测试文章\n- 版本：v1\n- 正文指纹：test\n- 生成时间：2026-08-06\n\n"
        "| 文章位置/主张 | CLAIM ID | 所属正式知识ID | 正式知识位置 | 原始来源与精确位置 | 使用方式 | 使用判断 | 异常处理 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 正文第1段 | CLAIM-TEST-IND-001-01 | KB-TEST-IND-001 | 测试主题.md | TEST-SRC-001/PDF p.1 | 直接事实 | 已确认使用 | 无 |\n\n"
        "## 未追踪内容\n\n| 文章位置/主张 | 原因 | 是否企业事实 | 风险 | 处理位置 |\n|---|---|---|---|---|\n",
        encoding="utf-8",
    )

    customer_request = root / CUSTOMER_REQUEST_RELATIVE
    customer_request.write_text(
        "# 待客户补充事项\n\n- 项目ID：TEST\n- 最近检查日期：2026-08-11\n\n## 当前事项\n\n"
        "| 问题ID | 想向客户确认什么 | 为什么需要 | 回复前怎么处理 | 当前阶段 | 下一步由谁做 | 最近更新 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| TEST-CUS-BASE | 是否需要客户补充测试事实 | 当前资料无法确认该事实 | 本篇先排除该事实 | 待判断要不要问 | 知识库专员判断是否值得询问 | 2026-08-11 |\n\n"
        "## 事项详情\n\n"
        "### TEST-CUS-BASE｜是否需要客户补充测试事实\n\n"
        "#### 先看结论\n\n"
        "- 发生了什么：当前资料没有说明测试事实。\n"
        "- 希望客户确认或提供什么：确认测试事实是否成立并提供可核验材料。\n"
        "- 为什么值得询问：这项事实可能影响后续文章，但本篇可以先排除。\n"
        "- 客户回复前怎么处理：不把该事实写入正式知识或文章。\n"
        "- 当前阶段：待判断要不要问\n"
        "- 下一步由谁做：知识库专员判断是否值得询问。\n\n"
        "> [!info]- 内部追溯信息\n> - 发现来源：审核Agent\n> - 关联文章与大纲位置：TEST-ART-001/测试主题\n> - 返回节点：节点5\n",
        encoding="utf-8",
    )
    material_todo = root / MATERIAL_TODO_RELATIVE
    material_todo.write_text(
        "# 源资料处理待办\n\n- 项目ID：TEST\n- 最近检查日期：2026-08-13\n\n"
        "## 当前事项\n\n"
        "| 事项ID | 资料ID | 资料与问题 | 触发原因 | 当前阶段 | AI知识库专员决定 | 下一步 | 最近更新 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| TEST-MAT-001 | TEST-SRC-VID-001 | 测试视频需要判断是否处理 | 初始化发现视频 | 待专员判断 | AI知识库专员判断处理方式 | AI知识库专员月度审核 | 2026-08-13 |\n\n"
        "## 事项详情\n\n"
        "### TEST-MAT-001｜测试视频需要判断是否处理\n\n"
        "#### 先看结论\n\n"
        "- 资料是什么：一个初始化扫描发现的测试视频。\n"
        "- 现在为什么不能正常处理：尚未判断是否有处理价值和采用何种方式。\n"
        "- 是否影响当前文章：否\n"
        "- 当前阶段：待专员判断\n"
        "- AI知识库专员决定：AI知识库专员在月度审核中判断。\n"
        "- 下一步：AI知识库专员决定暂不处理或选择转写方式。\n\n"
        "#### 资料与关联\n\n"
        "- 源文件总表：[打开资料登记](../../../04_资料与证据/10_源文件登记/01_源文件总表.md)\n"
        "- 原始资料：测试稳定路径/test.mp4\n"
        "- 资料ID：TEST-SRC-VID-001\n"
        "- 格式、大小、时长/页数/文件数：MP4；1 MB；1分钟\n"
        "- 版本/指纹：test-video-sha256\n"
        "- 版本或重复关系：独立资料\n"
        "- 仅据文件名初判（音视频有才写）：测试演示\n\n"
        "#### 处理与核验\n\n"
        "- 触发来源：初始化扫描\n"
        "- 已尝试方法与结果：只完成基础登记。\n"
        "- 处理方式：待AI知识库专员判断。\n"
        "- 覆盖范围和未处理范围：尚未处理视频内容。\n"
        "- 重开条件或复查日期：2026-09月度维护复查。\n"
        "- 最近更新：2026-08-13\n\n"
        "## 已完成、暂不处理与历史\n",
        encoding="utf-8",
    )
    source_anomaly = root / SOURCE_ANOMALY_RELATIVE
    source_anomaly.write_text(
        "# 源文与事实异常台账\n\n- 项目ID：TEST\n- 最近检查日期：2026-08-11\n\n"
        "## 当前异常\n\n"
        "| 异常ID | 通俗说明 | 原文是否修复 | 现在怎么处理 | 当前阶段 | 谁需要做什么 | 下一步或重开条件 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| TEST-ANM-BASE | 原文中的测试参数写法无法确认含义 | 未修复 | 不使用这条参数，其他可靠内容照常使用 | 已完成处置（原文未修复） | 主Agent保留限制，审核Agent已核对证据 | 取得完整且可核验的新版本时重开 |\n\n"
        "## 异常详情\n\n"
        "### TEST-ANM-BASE｜原文中的测试参数写法无法确认含义\n\n"
        "#### 先看结论\n\n"
        "- 发生了什么：原文把测试参数写成包含特殊符号的形式，现有上下文不足以确认它代表什么。\n"
        "- 为什么有风险：直接改写或补全可能把错误参数当成真实参数。\n"
        "- 现在怎么处理：不使用这条参数，其他可独立核验的内容继续使用。\n"
        "- 为什么本轮结束，或者还在等什么：当前能做的安全隔离和下游检查已经完成，等待新的完整版本。\n"
        "- 原文是否修复：未修复\n"
        "- 当前阶段：已完成处置（原文未修复）\n"
        "- 谁需要做什么：主Agent保留使用限制；有新材料时重新核验。\n\n"
        "#### 原文现场证据\n\n"
        "- 保存原文证据：[打开保存的原文证据](../../../04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md#清理后的正文)\n"
        "- 原始来源：[打开原始来源](https://example.com/test)\n- 来源版本/指纹：test-sha256\n- 精确位置：PDF p.1\n- 证据完整性：完整\n- 现场证据类型：逐字文本\n\n"
        "##### 实际取得的原文或原始结构（逐字/原样）\n\n```text\n0.00004%%T @220nm\n```\n\n"
        "##### 必要上下文\n\n- 前文：测试条件如下。\n- 异常位置：见上方围栏代码块中的测试参数。\n- 后文：无更多解释。\n- 表头、脚注或公式上下文：不适用\n- 页面截图或原始版面：不适用\n\n"
        "##### 经核验仍可使用的原文或原始结构（如有）\n\n```text\n无\n```\n\n- 可使用证据位置：无\n\n"
        "#### 内部追溯与处理记录\n\n"
        "- 首次发现日期：2026-08-11\n- 问题类型：语义不确定或事实风险\n"
        "- 受影响CLAIM、正式知识、候选和文章（有才写）：CLAIM-TEST-IND-001-01\n"
        "- 负责人：主Agent\n- 本次只重跑的范围：测试参数范围\n"
        "- 资料处理Agent结果：保留原文并隔离该参数。\n"
        "- 审核Agent独立复核：已打开原文链接并核对逐字文本与上下文。\n"
        "- 当前正式知识/候选/项目资料稿更新：候选保留不沉淀限制。\n"
        "- 进行中的文章写作输入更新：没有进行中的受影响文章。\n"
        "- 已完成文章历史影响与修订决定：没有已完成的受影响文章。\n"
        "- 完成处置的证据：[打开原文现场](../../../04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md#清理后的正文)\n"
        "- 最近更新：2026-08-11\n\n"
        "## 已完成处置与历史\n",
        encoding="utf-8",
    )


def run_self_test() -> int:
    contract_failures = validate_skill_runtime_contract()
    if contract_failures:
        print("SELF-TEST FAILED: internal runtime contract is incomplete")
        for failure in contract_failures:
            print(f"- {failure}")
        return 1
    with tempfile.TemporaryDirectory(prefix="validate-v04-") as temp:
        root = Path(temp) / "TEST-知识库"
        create_self_test_project(root)
        issues = validate_project(root)
        if issues:
            print("SELF-TEST FAILED: valid fixture produced issues")
            for issue in issues:
                print(asdict(issue))
            return 1
        run_ledger = root / RUN_LEDGER_RELATIVE
        run_ledger.parent.mkdir(parents=True, exist_ok=True)
        valid_run_record = {
            "schema_version": 1,
            "run_id": "RUN-TEST-001",
            "project_id": "TEST",
            "task": "校验器自测",
            "status": "success",
            "started_at": "2026-08-12T10:00:00+08:00",
            "ended_at": "2026-08-12T10:00:01+08:00",
            "skill": {"name": "manage-article-knowledge", "version": "v0.4", "sha256": "test"},
            "inputs": [],
            "read_files": [],
            "tool_calls": [],
            "outputs": [],
            "retry_count": 0,
            "failure_stage": None,
            "human_intervention": {"required": False, "reason": None},
            "usage": {"model": None, "input_tokens": None, "output_tokens": None, "cost": None, "currency": None},
        }
        valid_run_ledger = json.dumps(valid_run_record, ensure_ascii=False, separators=(",", ":")) + "\n"
        run_ledger.write_text(valid_run_ledger, encoding="utf-8")
        issues = validate_project(root)
        if any(issue.code.startswith("RUN_LEDGER_") for issue in issues):
            print("SELF-TEST FAILED: valid run ledger was rejected")
            return 1
        run_fragment = run_ledger.parent / "RUN-TEST-002.json"
        run_fragment.write_text("{}\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "RUN_LEDGER_FRAGMENT" for issue in issues):
            print("SELF-TEST FAILED: fragmented run JSON was not detected")
            return 1
        run_fragment.unlink()
        run_ledger.write_text(valid_run_ledger + "{broken json}\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "RUN_LEDGER_JSON" for issue in issues):
            print("SELF-TEST FAILED: invalid JSONL line was not detected")
            return 1
        run_ledger.write_text(valid_run_ledger, encoding="utf-8")
        managed_csv = root / CLAIM_USAGE_DETAIL_RELATIVE
        valid_csv_bytes = managed_csv.read_bytes()
        managed_csv.write_bytes(valid_csv_bytes.removeprefix(UTF8_BOM))
        issues = validate_project(root)
        if not any(issue.code == "CSV_UTF8_BOM" for issue in issues):
            print("SELF-TEST FAILED: managed CSV without UTF-8 BOM was not detected")
            return 1
        managed_csv.write_bytes(valid_csv_bytes)
        data_explanation = root / DATA_EXPLANATION_RELATIVE
        valid_data_explanation = read_text(data_explanation)
        data_explanation.write_text(
            "\n".join(
                line for line in valid_data_explanation.splitlines() if "(20_知识块使用明细.csv)" not in line
            )
            + "\n",
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "MANAGED_FILE_NOT_REGISTERED" for issue in issues):
            print("SELF-TEST FAILED: unregistered managed non-Markdown file was not detected")
            return 1
        data_explanation.write_text(valid_data_explanation, encoding="utf-8")
        orphan = root / "04_资料与证据/未登记证据.bin"
        orphan.write_bytes(b"test")
        issues = validate_project(root)
        if not any(issue.code == "NON_MD_ORPHAN" for issue in issues):
            print("SELF-TEST FAILED: orphan non-Markdown file was not detected")
            return 1
        orphan.unlink()
        formal = root / "02_正式知识/50_行业知识与洞察/10_企业提供/测试主题.md"
        formal.write_text(read_text(formal) + "\n$srcLink\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "PLACEHOLDER" for issue in issues):
            print("SELF-TEST FAILED: placeholder was not detected")
            return 1
        formal.write_text(read_text(formal).replace("\n$srcLink\n", "\n"), encoding="utf-8")
        valid_formal = read_text(formal)
        formal.write_text(
            re.sub(
                r"(?ms)(## 已处理内容\s*\n).*?(?=^## 使用限制)",
                r"\1\n测试知识摘要。\n\n",
                valid_formal,
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "FORMAL_CLAIM_MISSING" for issue in issues):
            print("SELF-TEST FAILED: summary-only formal knowledge was not detected")
            return 1
        formal.write_text(valid_formal, encoding="utf-8")

        formal.write_text(valid_formal.replace("- 精确位置：PDF p.1，清理后的正文\n", ""), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "FORMAL_CLAIM_FIELD" and "精确位置" in issue.message for issue in issues):
            print("SELF-TEST FAILED: missing claim source position was not detected")
            return 1
        formal.write_text(valid_formal, encoding="utf-8")

        product_at_root = root / "02_正式知识/20_产品介绍/错误落位产品.md"
        product_at_root.write_text(
            valid_formal.replace("KB-TEST-IND-001", "KB-TEST-PROD-001")
            .replace("行业知识", "产品主数据")
            .replace("industry:test-topic", "product:TEST-001")
            .replace("来源类型：企业提供", "来源类型：客户官网"),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "FORMAL_FILE_AT_MODULE_ROOT" for issue in issues):
            print("SELF-TEST FAILED: formal knowledge at module root was not detected")
            return 1
        product_at_root.unlink()

        industry_overview = root / "02_正式知识/50_行业知识与洞察/01_行业知识与洞察总览.md"
        valid_overview = read_text(industry_overview)
        industry_overview.write_text("# 行业知识与洞察总览\n\n## 已处理内容\n\n- 无\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "OVERVIEW_FORMAL_CONTRADICTION" for issue in issues):
            print("SELF-TEST FAILED: contradictory module overview was not detected")
            return 1
        industry_overview.write_text(valid_overview, encoding="utf-8")

        formal.write_text(valid_formal.replace("- 精确位置：PDF p.1，清理后的正文\n", ""), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "DEPOSITION_COMPLETED_WITH_FORMAL_ERRORS" for issue in issues):
            print("SELF-TEST FAILED: completed deposition with invalid formal knowledge was not detected")
            return 1
        formal.write_text(valid_formal, encoding="utf-8")

        candidate_file = root / CANDIDATE_RELATIVE
        valid_candidate = read_text(candidate_file)
        candidate_file.write_text(valid_candidate.replace("| 已沉淀 | 通过 |", "| 可自动沉淀 | 通过 |"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "READY_CANDIDATE_NOT_DEPOSITED" for issue in issues):
            print("SELF-TEST FAILED: ready candidate left undeposited was not detected")
            return 1
        candidate_file.write_text(valid_candidate.replace("| 已沉淀 | 通过 |", "| 异常待处理 | 文章未使用 |"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "ARTICLE_USE_AS_DEPOSIT_GATE" for issue in issues):
            print("SELF-TEST FAILED: article use as deposition gate was not detected")
            return 1
        candidate_file.write_text(
            valid_candidate.replace("TEST-SRC-001_测试_清理与字段统一稿.md", "OTHER-SRC-001_其他清理稿.md"),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "VERIFIED_SOURCE_NOT_ROUTED" for issue in issues):
            print("SELF-TEST FAILED: verified source missing from candidate routing was not detected")
            return 1
        candidate_file.write_text(valid_candidate, encoding="utf-8")

        scope = root / "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/15_提取范围与处理样本确认.md"
        valid_scope = read_text(scope)
        scope.write_text(valid_scope.replace("- 当前状态：已人工确认", "- 当前状态：待人工确认"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "SCOPE_HUMAN_APPROVAL_REQUIRED" for issue in issues):
            print("SELF-TEST FAILED: missing real human scope approval was not detected")
            return 1
        scope.write_text(valid_scope + "\n- 说明：用户说可以继续，等同范围确认。\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "GENERIC_CONTINUE_USED_AS_APPROVAL" for issue in issues):
            print("SELF-TEST FAILED: generic continuation used as scope approval was not detected")
            return 1
        scope.write_text(valid_scope.replace("- 外部调研决定：不开展", "- 外部调研决定：待确认"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "RESEARCH_DECISION_MISSING" for issue in issues):
            print("SELF-TEST FAILED: missing conditional research decision was not detected")
            return 1
        scope.write_text(valid_scope.replace("| test.pdf | 中文 |", "| https://example.com/test | 中文 |"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "WEB_INTERACTION_STATE_MISSING" for issue in issues):
            print("SELF-TEST FAILED: missing web interaction states were not detected")
            return 1
        scope.write_text(valid_scope, encoding="utf-8")

        clean_file = root / "04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md"
        valid_clean = read_text(clean_file)
        clean_file.write_text(valid_clean.replace("- 清理正文语言：中文", "- 清理正文语言：英文"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "SOURCE_LANGUAGE_MISMATCH" for issue in issues):
            print("SELF-TEST FAILED: source-language clean mismatch was not detected")
            return 1
        clean_file.write_text(valid_clean, encoding="utf-8")

        translation_file = root / "04_资料与证据/30_整理与翻译稿/20_翻译稿/TEST-SRC-001_英语忠实翻译稿.md"
        valid_translation = read_text(translation_file)
        translation_file.unlink()
        issues = validate_project(root)
        if not any(issue.code == "REQUIRED_TRANSLATION_MISSING" for issue in issues):
            print("SELF-TEST FAILED: required English translation for non-English source was not detected")
            return 1
        translation_file.write_text(valid_translation.replace("- 核验状态：已核验", "- 核验状态：待核验"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "TRANSLATION_NOT_VERIFIED" for issue in issues):
            print("SELF-TEST FAILED: unverified English translation was not detected")
            return 1
        translation_file.write_text(valid_translation, encoding="utf-8")

        candidate_file.write_text(valid_candidate.replace("| 已通过 | 通过 |", "| 已通过 | 未通过 |"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "DEPOSITION_UPSTREAM_GATE_FAILED" for issue in issues):
            print("SELF-TEST FAILED: failed deposition upstream gate was not detected")
            return 1
        candidate_file.write_text(valid_candidate, encoding="utf-8")

        gate_audit = root / "03_文章任务/30_已完成/2026-08/TEST-ART-001_测试文章/20_文章前知识审核.md"
        valid_gate_audit = read_text(gate_audit)
        gate_audit.write_text(valid_gate_audit.replace("可以进入写作", "暂不能进入写作", 1), encoding="utf-8")
        issues = validate_project(root)
        if any(issue.code == "DEPOSITION_UPSTREAM_GATE_FAILED" and "文章前审核" in issue.message for issue in issues):
            print("SELF-TEST FAILED: a completed but writing-blocked audit incorrectly blocked qualified deposition")
            return 1
        gate_audit.write_text(valid_gate_audit, encoding="utf-8")

        candidate_file.write_text(valid_candidate.replace("| 已完成，无待修正 | 完整 |", "| 未完成 | 完整 |"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "DEPOSITION_UPSTREAM_GATE_FAILED" and "文章前审核状态" in issue.message for issue in issues):
            print("SELF-TEST FAILED: incomplete article knowledge audit did not block deposition")
            return 1
        candidate_file.write_text(valid_candidate, encoding="utf-8")

        workbench = root / WORKBENCH_TODO_RELATIVE
        valid_workbench = read_text(workbench)
        workbench.write_text(valid_workbench + "\n- 处理：由AI知识库专员自动执行。\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "AUTOMATION_ACTOR_MISLABELED" for issue in issues):
            print("SELF-TEST FAILED: mislabeled human/automation actor was not detected")
            return 1
        workbench.write_text(valid_workbench, encoding="utf-8")

        mineru_assets = root / "04_资料与证据/20_Codex提取/TEST-SRC-001_assets"
        mineru_assets.mkdir(parents=True, exist_ok=True)
        issues = validate_project(root)
        if not any(issue.code == "MINERU_ASSETS_FORBIDDEN" for issue in issues):
            print("SELF-TEST FAILED: MinerU assets directory was not detected")
            return 1
        mineru_assets.rmdir()

        usage_detail = root / CLAIM_USAGE_DETAIL_RELATIVE
        valid_usage = read_text(usage_detail)
        usage_detail.write_text(valid_usage.replace("正文第1段,TEST-SRC-001", ",TEST-SRC-001"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "CONFIRMED_USAGE_INCOMPLETE" for issue in issues):
            print("SELF-TEST FAILED: incomplete confirmed claim usage was not detected")
            return 1
        usage_detail.write_text(valid_usage, encoding="utf-8")

        usage_total = root / CLAIM_USAGE_TOTAL_RELATIVE
        valid_total = read_text(usage_total)
        usage_total.write_text(valid_total.replace("| 1 | 0 |", "| 2 | 0 |"), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "CLAIM_USAGE_TOTAL_MISMATCH" for issue in issues):
            print("SELF-TEST FAILED: claim usage aggregate mismatch was not detected")
            return 1
        usage_total.write_text(valid_total, encoding="utf-8")

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

        anchor_target = root / "04_资料与证据/锚点目标.md"
        anchor_target.write_text("# 完整标题｜测试对象\n\n可定位正文。 ^test-block\n", encoding="utf-8")
        anchor_source = root / "04_资料与证据/锚点链接测试.md"
        anchor_source.write_text(
            "# 锚点链接测试\n\n"
            "- [[04_资料与证据/锚点目标#完整标题｜测试对象|标题锚点]]\n"
            "- [块锚点](锚点目标.md#^test-block)\n",
            encoding="utf-8",
        )
        issues = validate_project(root)
        if any(issue.code == "BROKEN_LINK_ANCHOR" and issue.file.endswith("锚点链接测试.md") for issue in issues):
            print("SELF-TEST FAILED: valid heading or block anchor was incorrectly rejected")
            return 1
        anchor_source.write_text(
            read_text(anchor_source)
            + "- [[04_资料与证据/锚点目标#不存在的短锚点|错误标题锚点]]\n"
            + "- [错误块锚点](锚点目标.md#^missing-block)\n",
            encoding="utf-8",
        )
        issues = validate_project(root)
        broken_anchor_issues = [
            issue
            for issue in issues
            if issue.code == "BROKEN_LINK_ANCHOR" and issue.file.endswith("锚点链接测试.md")
        ]
        if len(broken_anchor_issues) != 2:
            print("SELF-TEST FAILED: missing heading and block anchors were not both detected")
            return 1
        anchor_target.write_text(read_text(anchor_target) + "重复定位。 ^test-block\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "DUPLICATE_BLOCK_ID" and issue.file.endswith("锚点目标.md") for issue in issues):
            print("SELF-TEST FAILED: duplicate block ID was not detected")
            return 1
        anchor_source.unlink()
        anchor_target.unlink()

        version_entry = root / VERSION_ENTRY_RELATIVE
        valid_version_entry = read_text(version_entry)
        version_entry.write_text(valid_version_entry + "\n- 当前项目状态：旧状态\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "VERSION_ENTRY_DUPLICATE_STATE" for issue in issues):
            print("SELF-TEST FAILED: duplicated current project state in version entry was not detected")
            return 1
        version_entry.write_text(valid_version_entry, encoding="utf-8")

        current_skill_hash = sha256_file(skill_file())
        version_entry.write_text(valid_version_entry.replace(current_skill_hash, "0" * 64), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "PROJECT_SKILL_MISMATCH" for issue in issues):
            print("SELF-TEST FAILED: outdated project Skill fingerprint was not detected")
            return 1
        version_entry.write_text(valid_version_entry, encoding="utf-8")

        fake_runtime_skill = Path(temp) / "runtime-skill" / "SKILL.md"
        fake_runtime_skill.parent.mkdir(parents=True, exist_ok=True)
        fake_runtime_skill.write_text("---\nname: manage-article-knowledge\ndescription: stale runtime\n---\n", encoding="utf-8")
        issues = validate_project(root, fake_runtime_skill)
        if not any(issue.code == "RUNTIME_SKILL_MISMATCH" for issue in issues):
            print("SELF-TEST FAILED: stale installed/runtime Skill was not detected")
            return 1

        check_entry = root / CHECK_ENTRY_RELATIVE
        valid_check_entry = read_text(check_entry)
        check_entry.write_text(
            "\n".join(line for line in valid_check_entry.splitlines() if "Skill运行反馈" not in line) + "\n",
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "CHECK_ENTRY_LINK" and "Skill运行反馈" in issue.message for issue in issues):
            print("SELF-TEST FAILED: missing Skill feedback link in check entry was not detected")
            return 1
        check_entry.write_text(valid_check_entry, encoding="utf-8")

        skill_feedback = root / SKILL_FEEDBACK_RELATIVE
        valid_skill_feedback = read_text(skill_feedback)
        skill_feedback.write_text(
            valid_skill_feedback.replace(
                "\n\n## 反馈详情",
                "\n| TEST-SKFB-001 | Codex发现测试入口矛盾 | Codex自动发现 | 校验遗漏 | 人工提出，待维护判断 | 可能遗漏状态错误 | AI知识库专员判断 | 2026-08-11 |\n\n## 反馈详情",
            )
            .replace(
                "\n\n## 已关闭与不纳入",
                "\n\n### TEST-SKFB-001｜Codex发现测试入口矛盾\n\n#### 先看结论\n\n- 实际发生了什么：检查入口没有覆盖测试反馈。\n- 原本希望怎样：检查入口应链接全部反馈。\n- 对当前项目有什么影响：维护人员可能看不到反馈。\n- 当前临时处理：人工打开反馈台账。\n- 提出来源：Codex自动发现\n- 提出日期：2026-08-11\n- 当前阶段：人工提出，待维护判断\n- 下一步由谁做：AI知识库专员判断。\n\n#### 发现与关联\n\n- 自动总结依据（Codex自动发现时必填）：项目校验发现入口缺失。\n- 相关文件：[检查入口](../../../01_检查入口/01_当前待办.md)\n- 使用的Skill版本、日期和指纹：v0.4；2026-08-11；test\n- 是否可以复现：是\n- 敏感信息处理：无需脱敏\n\n## 已关闭与不纳入",
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "SKILL_FEEDBACK_ORIGIN_STAGE" for issue in issues):
            print("SELF-TEST FAILED: inconsistent Skill feedback origin and stage was not detected")
            return 1
        skill_feedback.write_text(valid_skill_feedback, encoding="utf-8")

        nav_fixture = root / "04_资料与证据/10_源文件登记/20_内容导航/TEST-SRC-DOC-001_内容导航.md"
        valid_nav_fixture = read_text(nav_fixture)
        nav_fixture.write_text(
            valid_nav_fixture.replace(
                "产品概述",
                "标题路径待文章定向处理",
            ).replace(
                "产品用途、适用范围和主要组成的连续段落",
                "初始化仅建立页面/章节导航；{likely_modules(rel)}",
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "CONTENT_NAV_GENERIC" for issue in issues):
            print("SELF-TEST FAILED: generic content navigation was not detected")
            return 1
        if not any(issue.code == "CONTENT_NAV_PLACEHOLDER" for issue in issues):
            print("SELF-TEST FAILED: content navigation placeholder was not detected")
            return 1
        nav_fixture.write_text(valid_nav_fixture, encoding="utf-8")

        # A real title path plus deferred extraction status is valid navigation;
        # the status must not be mistaken for the content summary.
        nav_fixture.write_text(
            valid_nav_fixture.replace(
                "产品用途、适用范围和主要组成的连续段落",
                "初始化扫描，待文章需求",
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if any(issue.code == "CONTENT_NAV_GENERIC" for issue in issues):
            print("SELF-TEST FAILED: real title path with deferred extraction was rejected")
            return 1
        nav_fixture.write_text(valid_nav_fixture, encoding="utf-8")

        material_todo = root / MATERIAL_TODO_RELATIVE
        valid_material_todo = read_text(material_todo)
        material_todo.write_text(valid_material_todo.replace("| 待专员判断 |", "| 错误阶段 |", 1), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "MATERIAL_TODO_STAGE" for issue in issues):
            print("SELF-TEST FAILED: invalid material todo stage was not detected")
            return 1
        material_todo.write_text(
            valid_material_todo.replace("| 待专员判断 |", "| 已处理可复用 |", 1).replace(
                "- 当前阶段：待专员判断", "- 当前阶段：已处理可复用"
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "MATERIAL_TODO_ARTIFACT" for issue in issues):
            print("SELF-TEST FAILED: reusable material todo without artifact was not detected")
            return 1
        material_todo.write_text(valid_material_todo, encoding="utf-8")

        source_register = root / SOURCE_REGISTER_RELATIVE
        valid_source_register = read_text(source_register)
        source_register.write_text(
            valid_source_register.replace("独立资料", "疑似重复", 1),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "SOURCE_RELATION_STATE" for issue in issues):
            print("SELF-TEST FAILED: invalid source relation state was not detected")
            return 1
        source_register.write_text(
            "# 源文件总表\n\n"
            "| 资料ID | 原文件名 | 相对路径 | 指纹 | 版本或重复关系 | 处理状态 |\n"
            "|---|---|---|---|---|---|\n"
            "| TEST-SRC-VID-001 | test.mp4 | test.mp4 | test-video-sha256 | 独立资料 | 待专员判断→TEST-MAT-001 |\n"
            "| TEST-SRC-DOC-001 | main.docx | main.docx | duplicate-sha256 | 主文件 | 待处理 |\n"
            "| TEST-SRC-DOC-002 | copy.docx | copy.docx | different-sha256 | 完全重复副本→TEST-SRC-DOC-001 | 复用主文件 |\n",
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "DUPLICATE_SOURCE_FINGERPRINT" for issue in issues):
            print("SELF-TEST FAILED: duplicate source with different fingerprint was not detected")
            return 1
        source_register.write_text(valid_source_register, encoding="utf-8")

        customer_request = root / CUSTOMER_REQUEST_RELATIVE
        valid_customer_request = read_text(customer_request)
        customer_request.write_text(valid_customer_request.replace("| 待判断要不要问 |", "| 错误阶段 |", 1), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "CUSTOMER_REQUEST_STAGE" for issue in issues):
            print("SELF-TEST FAILED: invalid customer request stage was not detected")
            return 1
        customer_request.write_text(
            valid_customer_request.replace("| 待判断要不要问 |", "| 等待发送 |", 1).replace(
                "- 当前阶段：待判断要不要问", "- 当前阶段：等待发送"
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "CUSTOMER_REQUEST_SCRIPT_REQUIRED" for issue in issues):
            print("SELF-TEST FAILED: missing confirmed customer script was not detected")
            return 1
        customer_request.write_text(valid_customer_request, encoding="utf-8")
        audit.write_text(read_text(audit) + "\n以后问客户。\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "AUDIT_CUSTOMER_REQUEST_LINK" for issue in issues):
            print("SELF-TEST FAILED: missing customer request backlink was not detected")
            return 1
        source_anomaly = root / SOURCE_ANOMALY_RELATIVE
        valid_source_anomaly = read_text(source_anomaly)
        source_anomaly.write_text(valid_source_anomaly.replace("| 已完成处置（原文未修复） |", "| 错误阶段 |", 1), encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "SOURCE_ANOMALY_STAGE" for issue in issues):
            print("SELF-TEST FAILED: invalid source anomaly stage was not detected")
            return 1
        source_anomaly.write_text(
            valid_source_anomaly.replace("| 未修复 |", "| 已修复 |", 1).replace("- 原文是否修复：未修复", "- 原文是否修复：已修复"),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "SOURCE_ANOMALY_STAGE_REPAIR" for issue in issues):
            print("SELF-TEST FAILED: inconsistent anomaly repair stage was not detected")
            return 1
        source_anomaly.write_text(
            valid_source_anomaly.replace(
                "[打开保存的原文证据](../../../04_资料与证据/30_整理与翻译稿/10_清理与字段统一稿/TEST-SRC-001_测试_清理与字段统一稿.md#清理后的正文)",
                "TEST-SRC-001/PDF p.1",
                1,
            ),
            encoding="utf-8",
        )
        issues = validate_project(root)
        if not any(issue.code == "SOURCE_ANOMALY_SAVED_EVIDENCE" for issue in issues):
            print("SELF-TEST FAILED: missing source anomaly evidence link was not detected")
            return 1
        source_anomaly.write_text(valid_source_anomaly, encoding="utf-8")
        control_syntax = root / "04_资料与证据/控制语法测试.md"
        control_syntax.write_text("# 测试\n\n原文为0.00004%%T @220nm。\n", encoding="utf-8")
        issues = validate_project(root)
        if not any(issue.code == "OBSIDIAN_CONTROL_SYNTAX" for issue in issues):
            print("SELF-TEST FAILED: unprotected Obsidian control syntax was not detected")
            return 1
        control_syntax.write_text("# 测试\n\n```text\n原文为0.00004%%T @220nm。\n```\n", encoding="utf-8")
        issues = validate_project(root)
        if any(issue.code == "OBSIDIAN_CONTROL_SYNTAX" and issue.file.endswith("控制语法测试.md") for issue in issues):
            print("SELF-TEST FAILED: protected Obsidian control syntax was incorrectly rejected")
            return 1
        control_syntax.unlink()
        source_anomaly.unlink()
        issues = validate_project(root)
        if not any(issue.code == "MISSING_SOURCE_ANOMALY_LEDGER" for issue in issues):
            print("SELF-TEST FAILED: missing source anomaly ledger was not detected")
            return 1
        material_todo.unlink()
        issues = validate_project(root)
        if not any(issue.code == "MISSING_MATERIAL_TODO_LEDGER" for issue in issues):
            print("SELF-TEST FAILED: missing material todo ledger was not detected")
            return 1
        customer_request.unlink()
        issues = validate_project(root)
        if not any(issue.code == "MISSING_CUSTOMER_REQUEST_LEDGER" for issue in issues):
            print("SELF-TEST FAILED: missing customer request ledger was not detected")
            return 1
    print("SELF-TEST PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检查manage-article-knowledge v0.4 Obsidian项目")
    parser.add_argument("--project", type=Path, help="Obsidian项目根目录")
    parser.add_argument("--json", action="store_true", help="输出JSON")
    parser.add_argument("--self-test", action="store_true", help="运行内置正反例测试")
    parser.add_argument("--runtime-skill", type=Path, help="实际运行Skill目录或SKILL.md；用于发布、安装和迁移一致性检查")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if not args.project:
        parser.error("--project is required unless --self-test is used")

    root = args.project.resolve()
    issues = validate_project(root, args.runtime_skill)
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
