#!/usr/bin/env python3
"""Validate the fixed structure of managed v0.6 article Markdown files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from preparation_record import compact, validation_view, protocol_errors


TEMPLATE_VERSION = "v0.6-20260907.1"
ARTICLE_AUDIT_TEMPLATE_VERSION = TEMPLATE_VERSION
ARTICLE_BODY_START = "<!-- ARTICLE_BODY_START -->"
ARTICLE_BODY_END = "<!-- ARTICLE_BODY_END -->"
REVISION_MODES = {"new_article", "outline_refresh", "knowledge_reuse_rewrite"}
CLAIM_RECHECK_HEADER = (
    "本轮候选事实ID/当前Claim ID", "本轮重新打开的来源与精确位置", "本轮证据结论",
    "当前归类模块", "本轮处置", "依据",
)
REVISION_REVIEW_HEADER = ("复核项", "15记录入口", "审核结论", "阻塞或排除")
REFRESH_SUMMARY_HEADER = ("项目", "本轮结果")
REFRESH_SUMMARY_ITEMS = (
    "基线版本", "重新检索范围", "基线Claim数", "本轮候选事实数", "保留", "新增",
    "更新", "拆分", "迁移", "失效", "转入gap/CUS/MAT/ANM", "中文结论",
)
REFRESH_COUNT_ITEMS = (
    "基线Claim数", "本轮候选事实数", "保留", "新增", "更新", "拆分", "迁移",
    "失效", "转入gap/CUS/MAT/ANM",
)
CURRENT_GAP_REVIEW_HEADER = (
    "GAP ID", "当前台账入口与状态", "本轮具体公共知识问题", "与当前大纲关系", "本轮处理和证据",
)
WEBSITE_EVIDENCE_HEADER = (
    "大纲章节/知识问题", "页面名称与最终具体URL", "获取日期", "正文位置",
    "最小连续原文", "候选事实ID或未命中", "处置结果",
)
GENERIC_WEBSITE_DISPOSITIONS = (
    "仅用于链接和品牌导航",
    "用于关键词链接和品牌页面确认",
    "用于官网画像和链接选择",
    "不用官网导航替代Claim",
    "官网用于品牌与页面确认",
    "官网命中相关导航",
)
HTTP_URL_RE = re.compile(r"https?://[^\s|；，、]+", re.IGNORECASE)


def researched_gap_evidence(project: Path, gap_id: str, handling: str, run_id: str) -> bool:
    """Require research records bound to this gap, run, and formal Claim."""
    res_ids = set(re.findall(r"\bRES-[A-Za-z0-9-]+\b", handling))
    claim_ids = set(re.findall(r"\bCLM-EXT-[A-Za-z0-9-]+\b", handling))
    if not res_ids or not claim_ids or not run_id:
        return False
    evidence_root = project / "02_源资料/50_外部调研证据"
    formal_root = project / "03_正式知识/20_外部公共知识"
    for res_id in res_ids:
        matched = False
        for directory in evidence_root.glob(f"{res_id}_*"):
            source = directory / "10_来源原文证据.md"
            review = directory / "20_调研核验记录.md"
            if not source.is_file() or not review.is_file():
                continue
            source_text = source.read_text(encoding="utf-8-sig")
            review_text = review.read_text(encoding="utf-8-sig")
            if all(
                parse_field(text, "调研ID") == res_id
                and parse_field(text, "关联缺口") == gap_id
                and parse_field(text, "文章知识准备运行ID") == run_id
                for text in (source_text, review_text)
            ) and all(claim_id in review_text for claim_id in claim_ids):
                matched = True
                break
        if not matched:
            return False
    formal_texts = [
        path.read_text(encoding="utf-8-sig") for path in formal_root.rglob("*.md")
    ] if formal_root.is_dir() else []
    return all(
        any(claim_id in text and all(res_id in text for res_id in res_ids) for text in formal_texts)
        for claim_id in claim_ids
    )


def resolve_archive_entry(task_dir: Path, entry: str) -> Path | None:
    """Resolve a project-relative archive entry without escaping the project root."""
    if not entry or entry == "不适用":
        return None
    relative = Path(entry)
    if relative.is_absolute():
        return None
    project = task_dir.parents[2].resolve()
    candidate = (project / relative).resolve()
    try:
        candidate.relative_to(project)
    except ValueError:
        return None
    return candidate

COMPLEX_MATERIAL_HEADER = (
    "资料ID", "文件名与稳定路径", "未索引内容/处理原因", "与本篇关系判断",
    "实际处理范围与方法", "MinerU/提取稿入口", "原件核对位置与结论",
    "MAT/ANM/CUS入口", "最终状态",
)
COMPLEX_MATERIAL_REVIEW_HEADER = (
    "资料ID", "15处理记录入口", "最终状态", "对当前事实/Claim影响", "本篇审核结论",
)
COMPLEX_MATERIAL_STATES = {
    "已处理并核对", "已检查不相关", "等待材料或工具", "待知识库专员判断", "不适用",
}
BLOCKING_COMPLEX_MATERIAL_STATES = {"等待材料或工具", "待知识库专员判断"}
CUS_DETECTION_CATEGORIES = ("客户能力", "规格", "认证", "案例", "商业条件", "公开授权")

CONTRACTS: dict[str, dict[str, Any]] = {
    "10_文章知识需求.md": {
        "title": "# 文章知识需求",
        "version_field": "模板版本",
        "fields": ("文章ID", "当前版本", "模板版本", "交接合同版本", "标题", "关键词", "目标语言", "特殊限制", "大纲状态", "原始写作请求", "产品或内容对象", "选题方向", "原始写作要求", "当前状态", "写作Skill", "任务模式", "大纲ID", "大纲版本", "重写模式", "基线文章ID", "基线文章版本", "基线大纲ID", "基线大纲版本", "旧版本归档入口"),
        "headings": ("## 外部写作任务接入", "## 大纲", "## 随文章提交文件分类"),
        "tables": {"## 随文章提交文件分类": ("文件名", "原始路径", "SHA-256", "文件性质", "使用范围", "处理结果")},
    },
    "15_检索与知识准备记录.md": {
        "title": "# 检索与知识准备记录",
        "version_field": "模板版本",
        "fields": ("文章ID", "文章版本", "模板版本", "最近更新", "MAT依赖处理", "知识准备模式", "大纲ID", "大纲版本", "重写模式", "基线文章版本"),
        "refresh_fields": ("本轮知识重整运行ID", "官网正文抓取凭证"),
        "new_fields": ("本轮知识检索运行ID", "官网正文抓取凭证"),
        "headings": ("## 固定检索层状态", "## 来源命中记录", "## 官网正文核验", "## 候选事实处置明细", "## 本轮事实与Claim盘点", "## 大纲逐项检索与候选事实覆盖", "## MAT依赖与资料选择", "## 复杂资料处理与原件核对"),
        "tables": {
            "## 固定检索层状态": ("检索层", "当前状态", "结果或未查原因", "下一步"),
            "## 来源命中记录": ("知识问题", "命中Claim/资料名称与入口", "相关理由", "处理结果"),
            "## 官网正文核验": WEBSITE_EVIDENCE_HEADER,
            "## 候选事实处置明细": ("候选事实ID", "独立事实摘要", "来源与精确位置", "处置结果", "Formal Claim或排除/治理入口"),
            "## 本轮事实与Claim盘点": CLAIM_RECHECK_HEADER,
            "## 大纲逐项检索与候选事实覆盖": ("大纲章节", "六层检索范围与结果", "命中来源与精确入口", "候选事实ID", "候选事实数", "已沉淀Claim数", "未采用事实/缺口及原因", "下一步"),
            "## MAT依赖与资料选择": ("MAT ID", "候选SRC ID", "文件名与稳定路径", "关系/处理问题", "决定", "选取或排除范围", "决定依据", "决定方", "当前状态"),
            "## 复杂资料处理与原件核对": COMPLEX_MATERIAL_HEADER,
        },
    },
    "20_文章前知识审核.md": {
        "title": "# 文章前知识审核",
        "version_field": "审核模板版本",
        "fields": ("文章ID", "文章版本", "审核模板版本", "审核日期", "结论", "可用Claim数", "客户来源", "外部来源", "明确排除", "未解决但不阻塞事项", "计划写作素材", "计划写作素材来源索引", "知识准备模式", "大纲ID", "大纲版本", "重写模式", "基线文章版本"),
        "headings": ("## 本轮知识准备复核", "## 大纲知识覆盖检查", "## 知识准备充分性复核", "## 复杂资料与原件核对复核", "## CUS / ANM检测结果", "## CUS / ANM逐项核对明细"),
        "tables": {
            "## 本轮知识准备复核": REVISION_REVIEW_HEADER,
            "## 大纲知识覆盖检查": ("大纲章节", "知识问题", "覆盖状态", "已有证据/Claim", "缺口或治理事项", "本篇处理"),
            "## 知识准备充分性复核": ("大纲章节", "候选事实数", "已沉淀Claim数", "计划纳入30的事实块数", "覆盖结论", "未采用事实/缺口及入口"),
            "## 复杂资料与原件核对复核": COMPLEX_MATERIAL_REVIEW_HEADER,
            "## CUS / ANM检测结果": ("检测对象", "已检查信号与来源", "分类结论", "事项与证据入口", "本篇处理"),
        },
    },
    "文章前问题与处理单.md": {
        "title": "# 文章前问题与处理单",
        "version_field": "模板版本",
        "fields": ("文章ID", "文章版本", "模板版本", "文章标题", "生成日期", "当前状态", "当前影响", "需要处理人", "处理完成后"),
        "headings": ("## 需要处理的问题", "## 决定与材料记录", "## 自动恢复"),
        "tables": {"## 需要处理的问题": ("问题ID", "发生了什么", "对文章的影响", "Codex已自动处理", "需要决定或提供什么", "可选方案与依据", "证据与关联入口")},
    },
    "30_本篇知识库资料.md": {
        "title": "# 本篇写作素材包",
        "version_field": "模板版本",
        "fields": ("文章ID", "文章版本", "模板版本", "资料视图", "资料版本", "生成日期", "目标语言", "对应大纲", "使用对象"),
        "headings": ("## 一、可直接用于正文的事实", "## 二、可直接采用的英文表达", "## 三、可使用的数据表", "## 四、按大纲使用", "## 五、仅供生成控制（不得写入正文）", "## 六、缺少资料的章节及建议处理方式"),
        "tables": {
            "## 二、可直接采用的英文表达": ("使用场景/大纲章节", "可采用表达", "使用条件"),
            "## 四、按大纲使用": ("大纲章节", "可用事实/表达/数据表", "推荐写作角度"),
            "## 六、缺少资料的章节及建议处理方式": ("原大纲章节", "建议处理", "可保留的安全写作方向"),
        },
    },
    "35_写作素材来源索引.md": {
        "title": "# 写作素材来源索引",
        "version_field": "模板版本",
        "fields": ("文章ID", "文章版本", "模板版本", "索引版本", "生成日期", "对应写作素材", "写作素材SHA-256", "用途"),
        "headings": ("## 写作素材到正式知识映射", "## 写作事实输入确认"),
        "tables": {"## 写作素材到正式知识映射": ("证据正文行开始", "证据正文行结束", "素材主题", "正式Claim ID", "Claim通俗标题", "正式知识文件", "原始来源与精确位置")},
    },
    "40_最终文章.md": {
        "title": "# 最终文章",
        "version_field": "模板版本",
        "fields": ("文章ID", "文章版本", "模板版本", "完成日期", "文章标题", "外部终稿原路径", "外部终稿SHA-256"),
        "headings": ("## 最终正文",),
        "tables": {},
    },
    "50_文章知识使用与Faithfulness记录.md": {
        "title": "# 文章知识使用与Faithfulness记录",
        "version_field": "模板版本",
        "fields": ("文章ID", "文章标题", "文章版本", "模板版本", "交接合同版本", "当前状态", "终稿", "本篇知识库资料", "写作素材来源索引", "终稿接收日期", "Faithfulness结果入口", "指定审核结果目录", "Faithfulness导入日期", "Faithfulness执行器", "外部审核模式", "外部结果文件", "unsupported归组处置文件", "终稿SHA-256", "本篇知识库资料及SHA-256"),
        "headings": ("## 一、Faithfulness结果", "## 二、正式知识对文章事实的支撑", "## 三、未被本次知识附件覆盖的内容", "## 四、后续动作", "## 五、更新记录"),
        "tables": {
            "## 一、Faithfulness结果": ("明确支持", "全部可验证主张", "尚未确认（证据不足）", "明确冲突", "知识附件明确支撑率", "正式Claim映射数", "未映射的明确支持主张数"),
            "## 二、正式知识对文章事实的支撑": ("文章事实/位置", "Formal Claim及通俗标题", "正式知识文件", "原始来源与位置", "支撑判断"),
            "## 三、未被本次知识附件覆盖的内容": ("归组及claim_id", "知识问题/内容", "分类", "分类依据", "本篇影响", "关联事项/入口", "当前处理", "下一步"),
            "## 四、后续动作": ("事项", "当前状态", "下一责任人", "关联入口", "更新/关闭条件"),
            "## 五、更新记录": ("日期", "事件", "结果/状态", "相关文件"),
        },
    },
}


def parse_field(text: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def table_header(text: str, heading: str) -> tuple[str, ...]:
    text = validation_view(text)
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        return ()
    tail = text[match.end():]
    for line in tail.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            return ()
        if stripped.startswith("|"):
            return tuple(cell.strip() for cell in stripped.strip("|").split("|"))
    return ()


def table_rows(text: str, heading: str) -> list[list[str]]:
    """Return non-header markdown rows in the table immediately under a heading."""
    text = validation_view(text)
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        return []
    rows: list[list[str]] = []
    started = False
    for line in text[match.end():].splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|"):
            if started and stripped:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            started = True
            continue
        if started:
            rows.append(cells)
    return rows


def website_retrieval_errors(text: str) -> list[str]:
    """Require auditable page-body retrieval before an article can be delivered."""
    errors: list[str] = []
    layer_rows = table_rows(text, "## 固定检索层状态")
    website_layer = next(
        (row for row in layer_rows if row and row[0].strip() == "客户官网"),
        None,
    )
    if not website_layer or len(website_layer) < 4:
        return ["客户官网检索层缺失或列数不足"]

    status, layer_result, next_step = (cell.strip() for cell in website_layer[1:4])
    layer_record = " ".join((status, layer_result, next_step))
    if any(phrase in layer_record for phrase in GENERIC_WEBSITE_DISPOSITIONS):
        errors.append("客户官网仍使用仅导航/链接的笼统处置语，未证明读取正文")
    if status.startswith("已检索") and not HTTP_URL_RE.search(layer_record):
        errors.append("客户官网已标记检索，但固定检索层没有最终具体URL")

    if table_header(text, "## 官网正文核验") != WEBSITE_EVIDENCE_HEADER:
        errors.append("缺少固定表头的官网正文核验")
        return errors
    evidence_rows = table_rows(text, "## 官网正文核验")
    if not evidence_rows:
        errors.append("官网正文核验没有实际记录")
        return errors

    matrix_rows = table_rows(text, "## 大纲逐项检索与候选事实覆盖")
    expected_questions = [row[0].strip().strip("*`# ") for row in matrix_rows if row and row[0].strip()]
    actual_questions = [row[0].strip().strip("*`# ") for row in evidence_rows if row]
    for question in expected_questions:
        if not any(question == actual or question in actual or actual in question for actual in actual_questions):
            errors.append(f"官网正文核验未逐项覆盖：{question}")

    candidate_rows = {
        row[0].strip(): row
        for row in table_rows(text, "## 候选事实处置明细")
        if len(row) >= 5 and re.fullmatch(r"CF-\d{3}", row[0].strip())
    }
    website_candidate_ids: set[str] = set()
    for row in evidence_rows:
        if len(row) != len(WEBSITE_EVIDENCE_HEADER):
            errors.append("官网正文核验存在列数错误的数据行")
            continue
        question, page, fetched, position, excerpt, candidate_result, disposition = (
            cell.strip() for cell in row
        )
        if not all((question, page, fetched, position, excerpt, candidate_result, disposition)):
            errors.append(f"官网正文核验记录不完整：{question or '未命名知识问题'}")
            continue
        if not HTTP_URL_RE.search(page):
            errors.append(f"官网正文核验缺少最终具体URL：{question}")
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", fetched):
            errors.append(f"官网正文核验获取日期必须为YYYY-MM-DD：{question}")
        if position.strip().lower() in {"page title", "页面标题", "title"}:
            errors.append(f"官网正文核验不能只记录页面标题，必须提取正文区块或段落：{question}")
        if len(position) < 4 or len(excerpt) < 20:
            errors.append(f"官网正文核验必须记录可回读的正文位置和连续原文：{question}")
        if any(phrase in disposition for phrase in GENERIC_WEBSITE_DISPOSITIONS):
            errors.append(f"官网正文核验仍使用仅导航/链接的笼统处置语：{question}")

        candidate_ids = set(re.findall(r"\bCF-\d{3}\b", candidate_result))
        website_candidate_ids.update(candidate_ids)
        if candidate_ids:
            if position in {"无", "不适用", "导航", "页面"}:
                errors.append(f"官网候选事实缺少正文标题、区块或段落位置：{question}")
            if excerpt in {"无", "不适用", "页面标题", "导航"} or len(excerpt) < 12:
                errors.append(f"官网候选事实缺少最小连续原文：{question}")
            for candidate_id in sorted(candidate_ids):
                candidate = candidate_rows.get(candidate_id)
                if not candidate:
                    errors.append(f"官网正文核验引用不存在的候选事实：{candidate_id}")
                    continue
                if not HTTP_URL_RE.search(candidate[2]):
                    errors.append(f"官网候选事实没有在来源与精确位置保留URL：{candidate_id}")
                if candidate[3].strip() in {"排除", "进入治理"} and candidate[4].strip() in {
                    "无", "未采用", "待补充",
                }:
                    errors.append(f"官网候选事实缺少具体排除或治理依据：{candidate_id}")
        elif not any(marker in candidate_result for marker in ("未命中", "无法访问", "不适用")):
            errors.append(f"官网正文核验既没有候选事实ID，也没有明确未命中/访问结果：{question}")

    source_hit_rows = table_rows(text, "## 来源命中记录")
    if status.startswith("已检索") and not any(
        any(HTTP_URL_RE.search(cell) for cell in row) for row in source_hit_rows
    ):
        errors.append("来源命中记录没有官网具体URL，无法证明本篇实际访问")
    if "命中" in status and "未命中" not in status and not website_candidate_ids:
        errors.append("客户官网标记为命中，但官网正文核验没有任何候选事实ID")
    return list(dict.fromkeys(errors))


def website_manifest_errors(task_dir: Path, text: str) -> list[str]:
    """Cross-check article website rows against the current-run fetch manifest."""
    errors: list[str] = []
    mode = parse_field(text, "知识准备模式")
    if mode == "new_article":
        run_id = parse_field(text, "本轮知识检索运行ID")
    else:
        run_id = parse_field(text, "本轮知识重整运行ID") or parse_field(text, "本轮知识检索运行ID")
    manifest_name = parse_field(text, "官网正文抓取凭证")
    if not run_id:
        errors.append("文章知识准备缺少本轮知识检索运行ID")
    if not manifest_name:
        errors.append("知识重整缺少官网正文抓取凭证路径")
        return errors
    manifest_path = (task_dir / manifest_name).resolve()
    try:
        manifest_path.relative_to(task_dir.resolve())
    except ValueError:
        errors.append("官网正文抓取凭证必须位于当前任务目录内")
        return errors
    if not manifest_path.is_file():
        errors.append(f"官网正文抓取凭证不存在：{manifest_name}")
        return errors
    try:
        records = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"官网正文抓取凭证不是有效JSON：{exc}")
        return errors
    if not isinstance(records, list) or not records:
        errors.append("官网正文抓取凭证必须包含至少一条实际抓取记录")
        return errors
    valid_records: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            errors.append("官网正文抓取凭证存在非对象记录")
            continue
        required = (
            "refresh_run_id", "question", "final_url", "fetched_date", "position", "excerpt",
            "excerpt_sha256", "response_sha256", "website_id", "source_type", "block_id",
            "block_tag", "heading_path", "block_text",
        )
        missing = [key for key in required if not str(record.get(key, "")).strip()]
        if missing:
            errors.append("官网正文抓取凭证缺少字段：" + "、".join(missing))
            continue
        if str(record["refresh_run_id"]) != run_id:
            errors.append(f"官网正文抓取凭证运行ID不一致：{record.get('question', '')}")
        source_type = str(record.get("source_type", "")).strip()
        website_id = str(record.get("website_id", "")).strip()
        block_id = str(record.get("block_id", "")).strip()
        block_tag = str(record.get("block_tag", "")).strip().lower()
        heading_path = record.get("heading_path")
        block_text = str(record.get("block_text", ""))
        if not source_type or not website_id:
            errors.append(f"网页正文凭证缺少网站ID或来源类型：{record.get('question', '')}")
        if (website_id == "PRIMARY-WEBSITE" and source_type != "客户官网") or (
            website_id.startswith("WEB-") and source_type != "客户关联网站（内容运营提交）"
        ):
            errors.append(f"网页正文凭证网站ID与来源类型不匹配：{record.get('question', '')}")
        if website_id != "PRIMARY-WEBSITE" and not re.fullmatch(r"WEB-[A-Za-z0-9]+-\d{3}", website_id):
            errors.append(f"网页正文凭证网站ID格式无效：{record.get('question', '')}")
        if not re.fullmatch(r"B\d{3,}", block_id) or block_tag not in {
            "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "figcaption", "table_row",
        }:
            errors.append(f"网页正文凭证缺少语义区块定位：{record.get('question', '')}")
        if not isinstance(heading_path, list) or any(not str(item).strip() for item in heading_path):
            errors.append(f"网页正文凭证缺少有效标题路径：{record.get('question', '')}")
        if len(block_text.strip()) < 20:
            errors.append(f"网页正文凭证语义区块为空或过短：{record.get('question', '')}")
        excerpt = str(record["excerpt"])
        digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        if digest != str(record["excerpt_sha256"]):
            errors.append(f"官网正文抓取凭证摘录哈希不一致：{record.get('question', '')}")
        if excerpt not in block_text:
            errors.append(f"网页证据摘录不属于凭证记录的单一正文区块：{record.get('question', '')}")
        if str(record.get("position", "")).strip().lower() in {"page title", "页面标题", "title"}:
            errors.append(f"官网正文凭证不能只记录页面标题：{record.get('question', '')}")
        if len(excerpt.strip()) < 20:
            errors.append(f"官网正文凭证连续原文过短：{record.get('question', '')}")
        valid_records.append(record)
    evidence_rows = table_rows(text, "## 官网正文核验")
    matched_manifest_indexes: set[int] = set()
    for row in evidence_rows:
        if len(row) != len(WEBSITE_EVIDENCE_HEADER):
            continue
        question, page, fetched, position, excerpt, _, _ = (cell.strip() for cell in row)
        url_match = HTTP_URL_RE.search(page)
        if not url_match:
            continue
        url = url_match.group(0).rstrip(".)，。；")
        website_id_match = re.search(r"\b(?:PRIMARY-WEBSITE|WEB-[A-Za-z0-9]+-\d{3})\b", page)
        website_id = website_id_match.group(0) if website_id_match else "PRIMARY-WEBSITE"
        source_type = "客户官网" if website_id == "PRIMARY-WEBSITE" else "客户关联网站（内容运营提交）"
        matches = [
            index for index, item in enumerate(valid_records)
            if str(item.get("question", "")).strip() == question
            and str(item.get("final_url", "")).strip() == url
            and str(item.get("fetched_date", "")).strip() == fetched
            and str(item.get("position", "")).strip() == position
            and str(item.get("excerpt", "")).strip() == excerpt
            and str(item.get("website_id", "")).strip() == website_id
            and str(item.get("source_type", "")).strip() == source_type
        ]
        matched = bool(matches)
        if matched:
            matched_manifest_indexes.add(matches[0])
        if not matched:
            errors.append(f"官网正文核验没有对应的实际抓取凭证：{question}")
            continue
        if website_id.startswith("WEB-"):
            website = registered_related_website(task_dir, website_id)
            if website is None:
                errors.append(f"文章使用了未登记的客户关联网站：{website_id}")
            elif website.get("可访问状态") != "可访问":
                errors.append(f"文章使用的客户关联网站当前不可作为客户来源：{website_id}，状态={website.get('可访问状态', '')}")
            elif "关系待确认" in website.get("企业关系与依据", ""):
                errors.append(f"文章使用的客户关联网站关系仍待确认：{website_id}")
            elif not url_within_registered_scope(url, website.get("具体URL", "")):
                errors.append(f"客户关联网站凭证URL不属于登记的网站范围：{website_id}")

    unused_related = [
        item for index, item in enumerate(valid_records)
        if index not in matched_manifest_indexes and str(item.get("website_id", "")).startswith("WEB-")
    ]
    if unused_related:
        errors.append("网页凭证包含未在15官网正文核验表登记的客户关联网站记录")
    return list(dict.fromkeys(errors))


def registered_related_website(task_dir: Path, website_id: str) -> dict[str, str] | None:
    project_root = task_dir.parents[2]
    profile = project_root / "01_工作台" / "10_项目基础信息.md"
    if not profile.is_file():
        return None
    text = profile.read_text(encoding="utf-8-sig")
    heading = "## 内容运营提交的其他企业相关网站"
    rows = table_rows(text, heading)
    header = table_header(text, heading)
    if not rows or not header:
        return None
    for row in rows:
        if len(row) == len(header) and row[0].strip() == website_id:
            return dict(zip(header, row))
    return None


def url_within_registered_scope(candidate: str, registered: str) -> bool:
    """Require exact host and a path boundary for a registered website URL."""
    try:
        actual = urlparse(candidate)
        scope = urlparse(registered)
    except ValueError:
        return False
    actual_host = (actual.hostname or "").lower().rstrip(".")
    scope_host = (scope.hostname or "").lower().rstrip(".")
    if actual.scheme not in {"http", "https"} or not actual_host or actual_host != scope_host:
        return False
    if actual.port not in {None, 80, 443} or scope.port not in {None, 80, 443}:
        if actual.port != scope.port:
            return False
    scope_path = scope.path.rstrip("/")
    actual_path = actual.path.rstrip("/")
    return not scope_path or actual_path == scope_path or actual_path.startswith(scope_path + "/")


def markdown_table_layout_errors(text: str, heading: str) -> list[str]:
    """Validate the rendered Markdown table boundary, not only parsed cells."""
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        return []
    body = text[match.end():]
    next_heading = re.search(r"^##\s+", body, re.MULTILINE)
    if next_heading:
        body = body[:next_heading.start()]
    lines = body.splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip().startswith("|")), None)
    if first is None:
        return []
    table_end = first
    while table_end < len(lines) and lines[table_end].strip().startswith("|"):
        table_end += 1
    later_table = next(
        (index for index in range(table_end, len(lines)) if lines[index].strip().startswith("|")),
        None,
    )
    if later_table is not None:
        return [f"{heading}表格内部存在空行或非表格内容，表头和数据必须连续"]
    if table_end - first < 3:
        return [f"{heading}表头、分隔行和首条数据必须连续"]
    return []


def normalize_markdown_table_spacing(text: str) -> str:
    """Remove only blank lines sandwiched between Markdown table rows."""
    lines = text.splitlines()
    normalized: list[str] = []
    for index, line in enumerate(lines):
        if not line.strip() and normalized and normalized[-1].strip().startswith("|"):
            next_nonblank = next(
                (candidate for candidate in lines[index + 1:] if candidate.strip()),
                "",
            )
            if next_nonblank.strip().startswith("|"):
                continue
        normalized.append(line)
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(normalized) + suffix


def section_body(text: str, heading: str) -> str:
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if not match:
        return ""
    body = text[match.end():]
    next_heading = re.search(r"^##\s+", body, re.MULTILINE)
    return body[: next_heading.start()] if next_heading else body


def is_placeholder(value: str) -> bool:
    return not value or value.strip() in {"无", "待填写", "待补充", "未记录", "同上", "-"}


def complex_material_rows(text: str) -> list[list[str]]:
    return table_rows(text, "## 复杂资料处理与原件核对")


def validate_complex_material_rows(rows: list[list[str]]) -> list[str]:
    """Validate evidence that a relevant complex source was actually handled."""
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if len(row) < len(COMPLEX_MATERIAL_HEADER):
            errors.append("复杂资料处理与原件核对存在列数不足的数据行")
            continue
        source_id, filename, reason, relation, method, extraction, original_check, governance, state = (
            cell.strip() for cell in row[:len(COMPLEX_MATERIAL_HEADER)]
        )
        if state not in COMPLEX_MATERIAL_STATES:
            errors.append(f"复杂资料处理最终状态无效：{state or '空'}")
            continue
        if state == "不适用":
            if source_id != "无" or is_placeholder(reason):
                errors.append("复杂资料不适用行必须写资料ID“无”及本篇没有可能相关复杂资料的理由")
            continue
        if not re.fullmatch(r"SRC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", source_id):
            errors.append(f"复杂资料处理资料ID必须使用完整SRC ID：{source_id or '空'}")
        elif source_id in seen:
            errors.append(f"复杂资料处理资料ID重复：{source_id}")
        seen.add(source_id)
        if any(is_placeholder(value) for value in (filename, reason, relation)):
            errors.append(f"{source_id or '未编号资料'}缺少文件、处理原因或与本篇关系")
        if state in {"已处理并核对", "已检查不相关"}:
            if is_placeholder(method) or is_placeholder(extraction) or is_placeholder(original_check):
                errors.append(f"{source_id or '未编号资料'}标为{state}，但没有实际处理范围、提取入口或原件核对结论")
            if not re.search(r"(?:页|page|章节|section|表|图|slide|段落|区块)", original_check, re.I):
                errors.append(f"{source_id or '未编号资料'}原件核对必须写明页、章节、表图、幻灯片或区块位置")
        elif state in BLOCKING_COMPLEX_MATERIAL_STATES:
            if not re.search(r"\b(?:MAT|ANM|CUS)-[A-Za-z0-9-]+\b", governance):
                errors.append(f"{source_id or '未编号资料'}等待处理时必须关联MAT、ANM或CUS入口")
    return errors


def outline_labels(text: str) -> list[str]:
    body = section_body(text, "## 大纲")
    labels: list[str] = []
    plain: list[str] = []
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("|"):
            continue
        match = re.match(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)(.+)$", stripped)
        value = (match.group(1) if match else stripped).strip().strip("*`# ")
        if not value or value.startswith("大纲状态："):
            continue
        plain.append(value)
        if match:
            labels.append(value)
    selected = labels or plain[:1]
    return list(dict.fromkeys(selected))


def validate_file(path: Path, contract_name: str | None = None) -> list[str]:
    contract = CONTRACTS.get(contract_name or path.name)
    if not contract:
        return []
    raw_text = path.read_text(encoding="utf-8-sig")
    text = validation_view(raw_text) if path.name == "15_检索与知识准备记录.md" else raw_text
    errors: list[str] = []
    if path.name == "15_检索与知识准备记录.md":
        errors.extend(protocol_errors(raw_text))
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first != contract["title"]:
        errors.append(f"固定标题应为{contract['title']}，实际为{first or '空'}")
    for field in contract["fields"]:
        if not parse_field(text, field):
            errors.append(f"缺少固定字段：{field}")
    version = parse_field(text, contract["version_field"])
    if version and version != TEMPLATE_VERSION:
        errors.append(
            f"{contract['version_field']}无效：{version}；当前应为{TEMPLATE_VERSION}"
        )
    for heading in contract["headings"]:
        if not re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE):
            errors.append(f"缺少固定章节：{heading}")
    for heading, expected in contract["tables"].items():
        empty_candidates = compact(raw_text) and heading == "## 候选事实处置明细" and not table_rows(text, heading)
        if not empty_candidates:
            errors.extend(markdown_table_layout_errors(text, heading))
        actual = table_header(text, heading)
        legacy_faithfulness_headers = {
            (
                "有证据支持事实主张数", "全部事实主张数", "未获严格支持事实主张数",
                "Faithfulness（严格支撑）", "DeepEval兼容诊断（不代表知识库实际支撑率）",
                "证据不足（unknown）", "明确冲突（contradicted）", "正式Claim映射数",
                "未映射的支持主张数",
            ),
            (
                "严格支持事实主张数", "全部事实主张数", "严格不支持事实主张数",
                "Faithfulness（严格支撑）", "DeepEval规则复现率", "unknown数",
                "正式Claim映射数", "未映射的支持主张数",
            ),
            (
                "支持事实主张数", "全部事实主张数", "不支持事实主张数",
                "Faithfulness", "正式Claim映射数", "未映射的支持主张数",
            ),
        }
        legacy_ok = (
            (contract_name or path.name) == "50_文章知识使用与Faithfulness记录.md"
            and heading == "## 一、Faithfulness结果"
            and actual in legacy_faithfulness_headers
        )
        if actual != expected and not legacy_ok:
            errors.append(
                f"{heading}固定表头不符：应为{' | '.join(expected)}，实际为{' | '.join(actual) or '缺失'}"
            )
        if not table_rows(text, heading) and not empty_candidates:
            errors.append(f"{heading}必须至少有一行真实记录；不能只保留表头")

    if path.name == "10_文章知识需求.md":
        outline = section_body(text, "## 大纲").strip()
        if not outline or outline in {"[原样保存]", "待定", "未提供"}:
            errors.append("## 大纲必须保留非空的简要大纲")
        if parse_field(text, "大纲状态") != "已确认":
            errors.append("必须记录：大纲状态：已确认")
        mode = parse_field(text, "任务模式")
        if mode not in REVISION_MODES:
            errors.append(f"任务模式无效：{mode}")
        base_version = parse_field(text, "基线文章版本")
        article_id = parse_field(text, "文章ID")
        current_version = parse_field(text, "当前版本")
        outline_id = parse_field(text, "大纲ID")
        outline_version = parse_field(text, "大纲版本")
        rewrite_mode = parse_field(text, "重写模式")
        base_article_id = parse_field(text, "基线文章ID")
        base_outline_id = parse_field(text, "基线大纲ID")
        base_outline_version = parse_field(text, "基线大纲版本")
        archive_entry = parse_field(text, "旧版本归档入口")
        if not outline_id:
            errors.append("必须记录稳定的大纲ID")
        if not re.fullmatch(r"v[1-9]\d*", outline_version):
            errors.append("大纲版本必须使用vN")
        if mode == "new_article":
            if rewrite_mode != "not_applicable":
                errors.append("新文章的重写模式必须为not_applicable")
            if any(value != "不适用" for value in (
                base_article_id, base_version, base_outline_id, base_outline_version, archive_entry,
            )):
                errors.append("新文章的基线文章/大纲身份和旧版本归档入口必须为“不适用”")
        elif mode in {"outline_refresh", "knowledge_reuse_rewrite"}:
            if rewrite_mode != "same_outline":
                errors.append("重做任务的重写模式必须为same_outline")
            if base_article_id != article_id:
                errors.append("同大纲重写的基线文章ID必须与文章ID一致")
            if not re.fullmatch(r"v[1-9]\d*", base_version):
                errors.append("重做任务的基线文章版本必须使用vN")
            elif re.fullmatch(r"v[1-9]\d*", current_version):
                if int(current_version[1:]) != int(base_version[1:]) + 1:
                    errors.append("同大纲重写只允许文章版本在基线版本上递增1")
            if base_outline_id != outline_id or base_outline_version != outline_version:
                errors.append("同大纲重写必须原样沿用大纲ID和大纲版本")
            if not archive_entry or archive_entry == "不适用":
                errors.append("重做任务必须记录真实旧版本归档入口")
    elif path.name == "15_检索与知识准备记录.md":
        errors.extend(website_retrieval_errors(text))
        knowledge_mode = parse_field(text, "知识准备模式")
        base_version = parse_field(text, "基线文章版本")
        outline_id = parse_field(text, "大纲ID")
        outline_version = parse_field(text, "大纲版本")
        rewrite_mode = parse_field(text, "重写模式")
        if not outline_id or not re.fullmatch(r"v[1-9]\d*", outline_version):
            errors.append("15必须记录有效大纲ID和vN大纲版本")
        if rewrite_mode not in {"not_applicable", "same_outline"}:
            errors.append(f"重写模式无效：{rewrite_mode}")
        if knowledge_mode not in {"new_article", "outline_refresh"}:
            errors.append(f"知识准备模式无效：{knowledge_mode}")
        elif knowledge_mode == "new_article" and base_version != "不适用":
            errors.append("新文章知识准备的基线文章版本必须为“不适用”")
        elif knowledge_mode == "outline_refresh" and not re.fullmatch(r"v[1-9]\d*", base_version):
            errors.append("知识重整的基线文章版本必须使用vN")
        if knowledge_mode == "outline_refresh":
            for field in CONTRACTS["15_检索与知识准备记录.md"].get("refresh_fields", ()):
                if not parse_field(text, field):
                    errors.append(f"知识重整15缺少固定字段：{field}")
            if rewrite_mode != "same_outline":
                errors.append("知识重整重写的重写模式必须为same_outline")
            if table_header(text, "## 本轮知识准备结论") != REFRESH_SUMMARY_HEADER:
                errors.append("知识重整必须包含固定表头的本轮知识准备结论")
            refresh_rows = table_rows(text, "## 本轮知识准备结论")
            refresh_summary = {row[0].strip(): row[1].strip() for row in refresh_rows if len(row) >= 2}
            required_items = ("本轮候选事实数", "采用事实数", "排除事实数", "进入治理事实数", "中文结论") if compact(raw_text) else REFRESH_SUMMARY_ITEMS
            missing_items = [item for item in required_items if not refresh_summary.get(item)]
            if missing_items:
                errors.append("本轮知识准备结论缺少项目：" + "、".join(missing_items))
            for item in REFRESH_COUNT_ITEMS:
                value = refresh_summary.get(item, "")
                if value and not value.isdigit():
                    errors.append(f"本轮知识准备结论的{item}必须是非负整数")
            if not compact(raw_text) and refresh_summary.get("基线版本") != base_version:
                errors.append("本轮知识准备结论的基线版本必须与15头部一致")
            scope = refresh_summary.get("重新检索范围", "")
            if scope in {"已检索", "检索完成", "无", "不适用"}:
                errors.append("本轮知识准备结论必须用中文写明实际重新检索范围")
            conclusion = refresh_summary.get("中文结论", "")
            if not re.search(r"[\u3400-\u9fff]", conclusion):
                errors.append("本轮知识准备结论必须使用中文人话")
            if not compact(raw_text) and conclusion and "不阻塞文章重写" not in conclusion:
                errors.append("本轮知识准备结论必须明确说明不阻塞文章重写")
        elif knowledge_mode == "new_article":
            for field in CONTRACTS["15_检索与知识准备记录.md"].get("new_fields", ()):
                if not parse_field(text, field):
                    errors.append(f"新文章15缺少固定字段：{field}")
            errors.extend(f"15_检索与知识准备记录.md：{item}" for item in website_manifest_errors(path.parent, text))
        if knowledge_mode in {"new_article", "outline_refresh"}:
            matrix_questions = [row[0].strip() for row in table_rows(text, "## 大纲逐项检索与候选事实覆盖") if row and row[0].strip()]
            website_questions = [row[0].strip() for row in table_rows(text, "## 官网正文核验") if row]
            for question in matrix_questions:
                if not any(question == actual or question in actual or actual in question for actual in website_questions):
                    errors.append(f"官网正文核验未逐项覆盖大纲问题：{question}")
        if knowledge_mode == "outline_refresh" and "知识准备规则版本：SK-V06-124" in text:
            if "本轮知识上下文从空白开始" not in text:
                errors.append("固定大纲重写必须声明知识输入仅来自当前大纲和本轮重新检索")
        candidate_details = table_rows(text, "## 候选事实处置明细")
        candidate_ids: set[str] = set()
        candidate_claims: dict[str, str] = {}
        for row in candidate_details:
            if len(row) < 5:
                errors.append("候选事实处置明细存在列数不足的数据行")
                continue
            candidate_id, fact, source, disposition, result = row[:5]
            if not re.fullmatch(r"CF-\d{3}", candidate_id):
                errors.append(f"候选事实ID必须使用CF-三位流水号：{candidate_id or '空'}")
            elif candidate_id in candidate_ids:
                errors.append(f"候选事实ID重复：{candidate_id}")
            candidate_ids.add(candidate_id)
            if not fact or not source or not disposition or not result:
                errors.append(f"{candidate_id or '未编号候选事实'}缺少事实摘要、来源、处置或结果入口")
            if disposition not in {"已沉淀Formal Claim", "复用已有Formal Claim", "排除", "进入治理"}:
                errors.append(f"{candidate_id or '未编号候选事实'}处置结果无效：{disposition or '空'}")
            if disposition in {"已沉淀Formal Claim", "复用已有Formal Claim"}:
                claims = re.findall(r"\bCLM-[A-Za-z0-9-]+\b", result)
                if not claims:
                    errors.append(f"{candidate_id or '未编号候选事实'}已采用但没有Formal Claim ID")
                candidate_claims[candidate_id] = ",".join(claims)
            elif result in {"无", "未采用", "待补充"}:
                errors.append(f"{candidate_id or '未编号候选事实'}排除/治理结果必须写具体理由或入口")
        matrix = table_rows(text, "## 大纲逐项检索与候选事实覆盖")
        if not matrix:
            errors.append("大纲逐项检索与候选事实覆盖必须至少有一行真实记录")
        labels = {row[0] for row in matrix if row}
        for required_label in ("标题", "主问题"):
            if required_label not in labels:
                errors.append(f"大纲逐项检索与候选事实覆盖必须包含“{required_label}”行")
        for row in matrix:
            if len(row) < 8:
                errors.append("大纲逐项检索与候选事实覆盖存在列数不足的数据行")
                continue
            chapter, search_scope, source_entry, candidate_refs, candidates, claims, omitted, next_step = row[:8]
            if not chapter or not search_scope or not source_entry or not next_step:
                errors.append(f"{chapter or '未命名章节'}缺少检索范围、来源入口或下一步")
            if search_scope in {"已检索", "检索完成", "无"}:
                errors.append(f"{chapter or '未命名章节'}必须写明六层实际检索结果，不能只写“{search_scope}”")
            if not candidates.isdigit() or not claims.isdigit():
                errors.append(f"{chapter or '未命名章节'}的候选事实数和已沉淀Claim数必须是非负整数")
                continue
            candidate_count, claim_count = int(candidates), int(claims)
            referenced = set(re.findall(r"\bCF-\d{3}\b", candidate_refs))
            if candidate_refs == "无":
                referenced = set()
            if len(referenced) != candidate_count:
                errors.append(f"{chapter or '未命名章节'}引用的候选事实ID数量与候选事实数不一致")
            unknown = referenced - candidate_ids
            if unknown:
                errors.append(f"{chapter or '未命名章节'}引用不存在的候选事实ID：{', '.join(sorted(unknown))}")
            referenced_claims = {
                claim_id
                for candidate_id in referenced
                for claim_id in candidate_claims.get(candidate_id, "").split(",")
                if claim_id
            }
            if len(referenced_claims) != claim_count:
                errors.append(f"{chapter or '未命名章节'}引用候选事实对应的Formal Claim数与已沉淀Claim数不一致")
            if claim_count > candidate_count:
                errors.append(f"{chapter or '未命名章节'}的已沉淀Claim数不能大于候选事实数")
            if candidate_count == 0 and source_entry not in {"未命中", "无相关命中", "不适用"}:
                errors.append(f"{chapter or '未命名章节'}没有候选事实时，来源入口必须明确写未命中或不适用")
            if candidate_count > claim_count and (
                not omitted or omitted in {"无", "未记录", "待补充"}
            ):
                errors.append(f"{chapter or '未命名章节'}存在未沉淀候选事实，但没有逐项记录未采用原因或缺口入口")
        errors.extend(validate_complex_material_rows(complex_material_rows(text)))
    elif path.name == "20_文章前知识审核.md":
        knowledge_mode = parse_field(text, "知识准备模式")
        base_version = parse_field(text, "基线文章版本")
        outline_id = parse_field(text, "大纲ID")
        outline_version = parse_field(text, "大纲版本")
        rewrite_mode = parse_field(text, "重写模式")
        if not outline_id or not re.fullmatch(r"v[1-9]\d*", outline_version):
            errors.append("20必须记录有效大纲ID和vN大纲版本")
        if rewrite_mode not in {"not_applicable", "same_outline"}:
            errors.append(f"重写模式无效：{rewrite_mode}")
        if knowledge_mode not in {"new_article", "outline_refresh"}:
            errors.append(f"知识准备模式无效：{knowledge_mode}")
        elif knowledge_mode == "new_article" and base_version != "不适用":
            errors.append("新文章审核的基线文章版本必须为“不适用”")
        elif knowledge_mode == "outline_refresh" and not re.fullmatch(r"v[1-9]\d*", base_version):
            errors.append("知识重整审核的基线文章版本必须使用vN")
        revision_rows = table_rows(text, "## 本轮知识准备复核")
        required_revision_checks = {"本轮六层检索", "本轮官网正文与凭证", "本轮Claim盘点", "30/35重新生成"}
        if knowledge_mode == "outline_refresh":
            if rewrite_mode != "same_outline":
                errors.append("知识重整审核的重写模式必须为same_outline")
            required_revision_checks.add("本轮知识准备结论")
        actual_revision_checks = {row[0].strip() for row in revision_rows if row}
        for check in sorted(required_revision_checks - actual_revision_checks):
            errors.append(f"本轮知识准备复核缺少“{check}”固定行")
        coverage = table_rows(text, "## 大纲知识覆盖检查")
        sufficiency = table_rows(text, "## 知识准备充分性复核")
        complex_review = table_rows(text, "## 复杂资料与原件核对复核")
        detection = table_rows(text, "## CUS / ANM检测结果")
        if not coverage:
            errors.append("大纲知识覆盖检查必须逐项记录至少一行")
        coverage_labels = {row[0] for row in coverage if row}
        for required_label in ("标题", "主问题"):
            if required_label not in coverage_labels:
                errors.append(f"大纲知识覆盖检查必须包含“{required_label}”行")
        for row in coverage:
            if len(row) < 6:
                errors.append("大纲知识覆盖检查存在列数不足的数据行")
                continue
            if row[2] not in {"已覆盖", "部分覆盖", "未覆盖", "无需事实支持"}:
                errors.append(f"大纲知识覆盖检查的覆盖状态无效：{row[2] or '空'}")
            if row[2] in {"部分覆盖", "未覆盖"} and not (
                re.search(r"(?:gap|CUS|MAT|ANM)[-_A-Za-z0-9]", row[4], re.I)
                or row[4].startswith("不构成知识问题：")
            ):
                errors.append(f"{row[0] or '未命名章节'}的部分/未覆盖项缺少治理入口或具体排除理由")
        if not sufficiency:
            errors.append("知识准备充分性复核必须逐项记录至少一行")
        sufficiency_labels = {row[0] for row in sufficiency if row}
        for required_label in ("标题", "主问题"):
            if required_label not in sufficiency_labels:
                errors.append(f"知识准备充分性复核必须包含“{required_label}”行")
        for row in sufficiency:
            if len(row) < 6:
                errors.append("知识准备充分性复核存在列数不足的数据行")
                continue
            chapter, candidates, claims, fact_blocks, conclusion, omitted = row[:6]
            if not all(value.isdigit() for value in (candidates, claims, fact_blocks)):
                errors.append(f"{chapter or '未命名章节'}的候选事实数、Claim数和计划纳入30的事实块数必须是非负整数")
                continue
            candidate_count, claim_count, block_count = map(int, (candidates, claims, fact_blocks))
            if conclusion not in {"充分", "有明确边界", "无需事实支持"}:
                errors.append(f"{chapter or '未命名章节'}的知识准备覆盖结论无效：{conclusion or '空'}")
            if claim_count > candidate_count:
                errors.append(f"{chapter or '未命名章节'}的已沉淀Claim数不能大于候选事实数")
            if claim_count > 0 and block_count == 0 and (
                not omitted or omitted in {"无", "未记录", "待补充"}
            ):
                errors.append(f"{chapter or '未命名章节'}已有沉淀Claim但未计划纳入30，缺少排除原因或治理入口")
            if (candidate_count > claim_count or (claim_count > 0 and block_count == 0)) and (
                not omitted or omitted in {"无", "未记录", "待补充"}
            ):
                errors.append(f"{chapter or '未命名章节'}存在候选事实、Claim或计划纳入30事实块数量差异，但没有说明未采用原因或缺口入口")
        if not complex_review:
            errors.append("复杂资料与原件核对复核必须至少有一行真实记录")
        for row in complex_review:
            if len(row) < len(COMPLEX_MATERIAL_REVIEW_HEADER):
                errors.append("复杂资料与原件核对复核存在列数不足的数据行")
                continue
            source_id, retrieval_entry, state, impact, conclusion = (
                cell.strip() for cell in row[:len(COMPLEX_MATERIAL_REVIEW_HEADER)]
            )
            if state not in COMPLEX_MATERIAL_STATES:
                errors.append(f"复杂资料复核最终状态无效：{state or '空'}")
            if state == "不适用":
                if source_id != "无" or is_placeholder(conclusion):
                    errors.append("复杂资料复核不适用行必须写资料ID“无”和本篇审核结论")
            elif not re.fullmatch(r"SRC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", source_id):
                errors.append(f"复杂资料复核资料ID必须使用完整SRC ID：{source_id or '空'}")
            if any(is_placeholder(value) for value in (retrieval_entry, impact, conclusion)):
                errors.append(f"{source_id or '未编号资料'}复杂资料复核缺少15入口、对Claim影响或审核结论")
        if parse_field(text, "结论") in {"自动通过", "带明确排除通过"} and any(
            len(row) >= 3 and row[2].strip() in BLOCKING_COMPLEX_MATERIAL_STATES
            for row in complex_review
        ):
            errors.append("仍有等待处理的复杂资料时，20结论不得为可交付通过")
        if not any(row and "CUS" in row[0] for row in detection):
            errors.append("CUS / ANM检测结果必须包含CUS候选检测行")
        if not any(row and "ANM" in row[0] for row in detection):
            errors.append("CUS / ANM检测结果必须包含ANM异常检测行")
        for row in detection:
            if len(row) >= 2 and row[0] in {"CUS候选检测", "ANM异常检测"}:
                if not row[1] or row[1] in {"已检查", "无异常", "无"}:
                    errors.append(f"{row[0]}必须填写实际检查信号与来源")
                if row[0] == "CUS候选检测":
                    missing = [category for category in CUS_DETECTION_CATEGORIES if category not in row[1]]
                    if missing:
                        errors.append(f"CUS候选检测缺少固定类别：{'、'.join(missing)}")
    elif path.name == "30_本篇知识库资料.md":
        from evidence_identity import material_contexts, field as identity_field
        if identity_field(text, "证据模板版本") == "EC-1" or "证据归属（仅用于指代解析）" in text:
            try:
                material_contexts(text.splitlines(), required=identity_field(text, "证据模板版本") == "EC-1")
            except ValueError as exc:
                errors.append(str(exc))
        facts = section_body(text, "## 一、可直接用于正文的事实")
        if facts.strip() not in {"", "无"} and not re.search(r"证据正文", facts):
            errors.append("第一节的事实素材必须包含证据正文标记")
        data = section_body(text, "## 三、可使用的数据表")
        if data.strip() not in {"", "无"} and not re.search(r"证据正文", data):
            errors.append("第三节的数据块必须包含证据正文标记")
    elif path.name == "35_写作素材来源索引.md":
        if not table_rows(text, "## 写作素材到正式知识映射"):
            errors.append("写作素材到正式知识映射必须至少有一条映射记录")
    elif path.name == "40_最终文章.md":
        if text.count(ARTICLE_BODY_START) != 1 or text.count(ARTICLE_BODY_END) != 1:
            errors.append("最终文章必须且只能包含一组显式正文边界")
        elif text.index(ARTICLE_BODY_START) >= text.index(ARTICLE_BODY_END):
            errors.append("最终文章正文边界顺序无效")
        elif not text.split(ARTICLE_BODY_START, 1)[1].split(ARTICLE_BODY_END, 1)[0].strip():
            errors.append("最终文章正文边界内不得为空")
    elif (contract_name or path.name) == "50_文章知识使用与Faithfulness记录.md":
        status = parse_field(text, "当前状态")
        if status and not status.startswith("等待") and "等待结果" in text:
            errors.append("已导入的50记录不得残留“等待结果”占位内容")
    return errors


def coverage_mapping_errors(retrieval: str, audit: str, index: str) -> list[str]:
    """Check declared question support against this run, without guessing meaning."""
    errors = []
    candidates = {r[0]: r for r in table_rows(retrieval, "## 候选事实处置明细") if len(r) >= 5}
    by_question = {r[0]: r for r in table_rows(retrieval, "## 大纲逐项检索与候选事实覆盖") if len(r) >= 8}
    mapped = {r[3] for r in table_rows(index, "## 写作素材到正式知识映射") if len(r) >= 4}
    sufficiency = {r[0]: r for r in table_rows(audit, "## 知识准备充分性复核") if len(r) >= 6}
    for row in table_rows(audit, "## 大纲知识覆盖检查"):
        if len(row) < 6 or row[0] not in by_question:
            continue
        question = row[0]
        matrix = by_question[question]
        refs = set(re.findall(r"CF-\d{3}", matrix[3]))
        eligible = {cid for ref in refs for cid in re.findall(r"CLM-[A-Za-z0-9-]+", candidates.get(ref, [""] * 5)[4])
                    if candidates.get(ref, [""] * 5)[3] in {"已沉淀Formal Claim", "复用已有Formal Claim"}}
        claimed = set(re.findall(r"CLM-[A-Za-z0-9-]+", row[3]))
        if claimed - eligible:
            errors.append(f"20的{question}引用了未在15为该问题采用的Claim：{sorted(claimed - eligible)}")
        if row[2] == "已覆盖" and (not claimed or not claimed <= mapped):
            errors.append(f"20的{question}标已覆盖但Claim未完整进入当前35")
        if row[2] == "已覆盖" and row[4] not in {"无", "不适用"}:
            errors.append(f"20的{question}仍有缺口/治理事项，不能标已覆盖")
        if row[2] in {"部分覆盖", "未覆盖"} and sufficiency.get(question, [""] * 6)[4] == "充分":
            errors.append(f"20的{question}覆盖状态与充分结论冲突")
    return errors


def validate_task_templates(task_dir: Path) -> list[str]:
    errors: list[str] = []
    for name in CONTRACTS:
        path = task_dir / name
        if path.is_file():
            errors.extend(f"{name}：{item}" for item in validate_file(path))
    request = task_dir / "10_文章知识需求.md"
    retrieval = task_dir / "15_检索与知识准备记录.md"
    audit = task_dir / "20_文章前知识审核.md"
    if request.is_file():
        request_text = request.read_text(encoding="utf-8-sig")
        preparation_protocol = parse_field(request_text, "知识准备记录协议")
        if preparation_protocol and preparation_protocol != "PR-1":
            errors.append("10知识准备记录协议未知，不得自动降级")
        if preparation_protocol == "PR-1" and retrieval.is_file():
            if not compact(retrieval.read_text(encoding="utf-8-sig")):
                errors.append("15须使用10声明的PR-1六节模板；由知识库合并本轮记录后继续")
        from governance_source_check import HEADER as source_header, HEADING as source_heading, PROTOCOL
        protocol = parse_field(request_text, "来源核验模板版本")
        if protocol and protocol != PROTOCOL:
            errors.append("10来源核验模板版本未知，不得自动降级")
        if protocol == PROTOCOL and retrieval.is_file():
            source_text = retrieval.read_text(encoding="utf-8-sig")
            if tuple(table_header(source_text, source_heading)) != source_header or not table_rows(source_text, source_heading):
                errors.append("15缺少固定CUS / ANM来源核验记录；知识库继续回源核验，不得以临时任务笔记替代")
        requested = outline_labels(request_text)
        expected = ["标题", "主问题", *requested]
        checks = (
            (retrieval, "## 大纲逐项检索与候选事实覆盖", "15_检索与知识准备记录.md"),
            (audit, "## 大纲知识覆盖检查", "20_文章前知识审核.md"),
            (audit, "## 知识准备充分性复核", "20_文章前知识审核.md"),
        )
        for path, heading, filename in checks:
            if not path.is_file():
                continue
            rows = table_rows(path.read_text(encoding="utf-8-sig"), heading)
            actual = [row[0].strip().strip("*`# ") for row in rows if row]
            for label in expected:
                if not any(label == value or label in value or value in label for value in actual):
                    errors.append(f"{filename}：{heading}未逐项对应10中的“{label}”")
        if retrieval.is_file() and audit.is_file():
            retrieval_rows = table_rows(
                retrieval.read_text(encoding="utf-8-sig"),
                "## 大纲逐项检索与候选事实覆盖",
            )
            sufficiency_rows = table_rows(
                audit.read_text(encoding="utf-8-sig"),
                "## 知识准备充分性复核",
            )
            retrieval_counts = {
                row[0].strip().strip("*`# "): (row[4].strip(), row[5].strip())
                for row in retrieval_rows if len(row) >= 6
            }
            sufficiency_counts = {
                row[0].strip().strip("*`# "): (row[1].strip(), row[2].strip())
                for row in sufficiency_rows if len(row) >= 3
            }
            for label, counts in retrieval_counts.items():
                if label in sufficiency_counts and sufficiency_counts[label] != counts:
                    errors.append(
                        f"15与20的候选事实/已沉淀Claim计数不一致：{label}，"
                        f"15={counts[0]}/{counts[1]}，20={sufficiency_counts[label][0]}/{sufficiency_counts[label][1]}"
                    )
            if preparation_protocol == "PR-1":
                errors.extend(coverage_mapping_errors(
                    retrieval.read_text(encoding="utf-8-sig"),
                    audit.read_text(encoding="utf-8-sig"),
                    (task_dir / "35_写作素材来源索引.md").read_text(encoding="utf-8-sig")
                    if (task_dir / "35_写作素材来源索引.md").is_file() else ""))
            complex_rows = complex_material_rows(retrieval.read_text(encoding="utf-8-sig"))
            review_rows = table_rows(
                audit.read_text(encoding="utf-8-sig"), "## 复杂资料与原件核对复核"
            )
            complex_by_source = {
                row[0].strip(): row for row in complex_rows
                if len(row) >= len(COMPLEX_MATERIAL_HEADER) and row[0].strip() != "无"
            }
            review_by_source = {
                row[0].strip(): row for row in review_rows
                if len(row) >= len(COMPLEX_MATERIAL_REVIEW_HEADER) and row[0].strip() != "无"
            }
            for source_id, row in complex_by_source.items():
                if source_id not in review_by_source:
                    errors.append(f"20_文章前知识审核.md：复杂资料复核缺少15中资料{source_id}")
                    continue
                if review_by_source[source_id][2].strip() != row[8].strip():
                    errors.append(f"15与20的复杂资料最终状态不一致：{source_id}")
        mode = parse_field(request_text, "任务模式") or "new_article"
        request_outline_id = parse_field(request_text, "大纲ID")
        request_outline_version = parse_field(request_text, "大纲版本")
        request_rewrite_mode = parse_field(request_text, "重写模式")
        refresh_run: dict[str, Any] | None = None
        refresh_sidecar = task_dir / "知识重整运行.json"
        if mode == "outline_refresh":
            if not refresh_sidecar.is_file():
                errors.append("原大纲重新整理缺少知识重整运行.json；不得把旧知识包改版本使用")
            else:
                try:
                    loaded = json.loads(refresh_sidecar.read_text(encoding="utf-8-sig"))
                    if not isinstance(loaded, dict):
                        raise ValueError("必须是JSON对象")
                    refresh_run = loaded
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    errors.append(f"知识重整运行.json无法读取：{exc}")
            if refresh_run is not None:
                run_id = str(refresh_run.get("refresh_run_id", "")).strip()
                if not run_id:
                    errors.append("知识重整运行.json缺少refresh_run_id")
                if str(refresh_run.get("article_id", "")).strip() != parse_field(request_text, "文章ID"):
                    errors.append("知识重整运行.json的article_id与10不一致")
                if str(refresh_run.get("article_version", "")).strip() != parse_field(request_text, "当前版本"):
                    errors.append("知识重整运行.json的article_version与10不一致")
                if str(refresh_run.get("status", "")).strip() in {"copied_from_baseline", "reused_old_package"}:
                    errors.append("原大纲重新整理的运行记录标记为旧包复制/复用，禁止进入写作")
                if str(refresh_run.get("workflow_entry", "")).strip() != "run_outline_refresh.py":
                    errors.append("原大纲重新整理必须通过run_outline_refresh.py接续")
                if str(refresh_run.get("package_generation", "")).strip() == "copied_from_baseline":
                    errors.append("原大纲重新整理的知识包生成方式标记为旧版复制，禁止进入写作")
                if run_id:
                    for path, filename in (
                        (retrieval, "15_检索与知识准备记录.md"),
                        (audit, "20_文章前知识审核.md"),
                        (task_dir / "30_本篇知识库资料.md", "30_本篇知识库资料.md"),
                        (task_dir / "35_写作素材来源索引.md", "35_写作素材来源索引.md"),
                    ):
                        if path.is_file():
                            content = path.read_text(encoding="utf-8-sig")
                            recorded = parse_field(content, "本轮知识重整运行ID") or parse_field(content, "本轮运行ID")
                            if recorded != run_id:
                                errors.append(f"{filename}未绑定当前本轮知识重整运行ID：{run_id}")
        for path, filename in ((retrieval, "15_检索与知识准备记录.md"), (audit, "20_文章前知识审核.md")):
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8-sig")
            if parse_field(content, "大纲ID") != request_outline_id:
                errors.append(f"{filename}：大纲ID必须与10一致")
            if parse_field(content, "大纲版本") != request_outline_version:
                errors.append(f"{filename}：大纲版本必须与10一致")
            if parse_field(content, "重写模式") != request_rewrite_mode:
                errors.append(f"{filename}：重写模式必须与10一致")
        if mode == "outline_refresh":
            base_version = parse_field(request_text, "基线文章版本")
            archive_entry = parse_field(request_text, "旧版本归档入口")
            for path, filename in ((retrieval, "15_检索与知识准备记录.md"), (audit, "20_文章前知识审核.md")):
                if not path.is_file():
                    continue
                content = path.read_text(encoding="utf-8-sig")
                if parse_field(content, "知识准备模式") != mode:
                    errors.append(f"{filename}：知识准备模式必须为{mode}")
                if parse_field(content, "基线文章版本") != base_version:
                    errors.append(f"{filename}：基线文章版本必须与10一致")
            if retrieval.is_file():
                retrieval_text = retrieval.read_text(encoding="utf-8-sig")
                errors.extend(
                    f"15_检索与知识准备记录.md：{item}"
                    for item in website_manifest_errors(task_dir, retrieval_text)
                )
                claim_heading = "## 本轮事实与Claim盘点"
                if table_header(retrieval_text, claim_heading) != CLAIM_RECHECK_HEADER:
                    errors.append("15_检索与知识准备记录.md：本轮Claim盘点固定表头不符")
                claim_rows = table_rows(retrieval_text, claim_heading)
                if not claim_rows:
                    errors.append("15_检索与知识准备记录.md：本轮Claim盘点必须至少有一行真实记录")
                # outline_refresh is independent of the archived
                # knowledge inventory.  Archive contents are not read here.
                old_claims: set[str] = set()
                # Archived Claims are a comparison set, not mandatory current
                # inputs. Current inventory is defined by this run's sources.
                for row in claim_rows:
                    if len(row) < len(CLAIM_RECHECK_HEADER):
                        errors.append("15_检索与知识准备记录.md：本轮Claim盘点存在列数不足的数据行")
                        continue
                    if row[0].strip() != "无" and any(not cell.strip() for cell in row[:len(CLAIM_RECHECK_HEADER)]):
                        errors.append(f"15_检索与知识准备记录.md：{row[0] or '未编号事实'}本轮盘点记录不完整")
                    if row[0].strip() != "无" and row[CLAIM_RECHECK_HEADER.index("本轮处置")].strip() not in {"新建", "复用", "更新", "拆分", "迁移", "失效", "排除", "治理", "不适用"}:
                        errors.append(
                            f"15_检索与知识准备记录.md：{row[0] or '未编号事实'}本轮处置必须使用复用/更新/拆分/迁移/失效/不适用"
                        )
                    if row[0].strip() != "无" and re.search(
                        r"90_归档|(?:^|[/\\])(?:15|20|30|35)_", row[1]
                    ):
                        errors.append(
                            f"15_检索与知识准备记录.md：{row[0]}的本轮来源不能是归档知识文件，必须回到原始来源"
                        )
                refresh_rows = table_rows(retrieval_text, "## 本轮知识准备结论")
                refresh_summary = {
                    row[0].strip(): row[1].strip() for row in refresh_rows if len(row) >= 2
                }
                candidate_rows = table_rows(retrieval_text, "## 候选事实处置明细")
                current_index = task_dir / "35_写作素材来源索引.md"
                if current_index.is_file():
                    adopted_claims = {
                        claim_id
                        for row in candidate_rows if len(row) >= 5 and row[3].strip() in {
                            "已沉淀Formal Claim", "复用已有Formal Claim"
                        }
                        for claim_id in re.findall(r"\bCLM-[A-Za-z0-9-]+\b", row[4])
                    }
                    mapped_claims = {
                        row[3].strip()
                        for row in table_rows(
                            current_index.read_text(encoding="utf-8-sig"),
                            "## 写作素材到正式知识映射",
                        )
                        if len(row) >= 4 and re.fullmatch(r"CLM-[A-Za-z0-9-]+", row[3].strip())
                    }
                    for claim_id in sorted(mapped_claims - adopted_claims):
                        errors.append(f"35映射中的{claim_id}缺少本轮候选事实采用记录")
                newly_created_claims = {
                    claim_id
                    for row in candidate_rows if len(row) >= 5 and row[3].strip() == "已沉淀Formal Claim"
                    for claim_id in re.findall(r"\bCLM-[A-Za-z0-9-]+\b", row[4])
                }
                expected_counts = {
                    "本轮候选事实数": len({
                        row[0].strip() for row in candidate_rows
                        if row and re.fullmatch(r"CF-\d{3}", row[0].strip())
                    }),
                    "新增": len(newly_created_claims),
                    "保留": sum(1 for row in claim_rows if len(row) >= 6 and row[CLAIM_RECHECK_HEADER.index("本轮处置")].strip() == "复用"),
                    "更新": sum(1 for row in claim_rows if len(row) >= 6 and row[CLAIM_RECHECK_HEADER.index("本轮处置")].strip() == "更新"),
                    "拆分": sum(1 for row in claim_rows if len(row) >= 6 and row[CLAIM_RECHECK_HEADER.index("本轮处置")].strip() == "拆分"),
                    "迁移": sum(1 for row in claim_rows if len(row) >= 6 and row[CLAIM_RECHECK_HEADER.index("本轮处置")].strip() == "迁移"),
                    "失效": sum(1 for row in claim_rows if len(row) >= 6 and row[CLAIM_RECHECK_HEADER.index("本轮处置")].strip() == "失效"),
                    "转入gap/CUS/MAT/ANM": sum(
                        1 for row in candidate_rows if len(row) >= 4 and row[3].strip() == "进入治理"
                    ),
                }
                for label, expected_count in expected_counts.items():
                    value = refresh_summary.get(label, "")
                    if value.isdigit() and int(value) != expected_count:
                        errors.append(
                            f"15_检索与知识准备记录.md：本轮知识准备结论的{label}与明细不一致，"
                            f"应为{expected_count}，实际为{value}"
                        )
                gap_review_rows = table_rows(retrieval_text, "## 本轮待调研缺口复核")
                explicit_gap_ids = {
                    row[0].strip() for row in gap_review_rows
                    if row and re.fullmatch(r"GAP-[A-Za-z0-9-]+", row[0].strip())
                }
                # Query the current project ledger only when current-outline
                # research has identified a concrete gap to deduplicate.
                if explicit_gap_ids:
                    gap_csv = task_dir.parents[2] / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
                    gap_ledger: dict[str, dict[str, str]] = {}
                    if gap_csv.is_file():
                        with gap_csv.open("r", encoding="utf-8-sig", newline="") as stream:
                            gap_ledger = {
                                row.get("gap_key", ""): row for row in csv.DictReader(stream)
                                if row.get("gap_key", "")
                            }
                    if table_header(retrieval_text, "## 本轮待调研缺口复核") != CURRENT_GAP_REVIEW_HEADER:
                        errors.append("15_检索与知识准备记录.md：本轮待调研缺口复核固定表头不符")
                    reviews = {
                        row[0].strip(): row for row in gap_review_rows
                        if len(row) >= len(CURRENT_GAP_REVIEW_HEADER)
                    }
                    restrictions = " ".join(
                        parse_field(request_text, label)
                        for label in ("特殊限制", "原始写作要求", "原始写作请求")
                    )
                    forbidden = any(
                        marker in restrictions
                        for marker in ("本篇不开展新的外部调研", "禁止外部调研", "不使用任何外部来源")
                    )
                    for gap_id in sorted(explicit_gap_ids):
                        review = reviews.get(gap_id, [])
                        if len(review) < len(CURRENT_GAP_REVIEW_HEADER) or any(
                            not cell.strip() for cell in review[1:len(CURRENT_GAP_REVIEW_HEADER)]
                        ):
                            errors.append(f"本轮具体缺口缺少大纲关联、台账去重或本轮处理证据：{gap_id}")
                            continue
                        ledger_row = gap_ledger.get(gap_id)
                        if ledger_row and review[2].strip() != ledger_row.get("gap_topic", "").strip():
                            errors.append(f"{gap_id}的gap_key去重后问题描述与当前台账不一致")
                            continue
                        relationship = review[3].strip()
                        handling = review[4].strip()
                        excluded = any(marker in relationship for marker in ("无关", "不再需要", "不属于当前大纲"))
                        if excluded:
                            if not HTTP_URL_RE.search(handling) or len(handling) < 40:
                                errors.append(f"{gap_id}本轮排除缺少当前大纲边界与本轮证据定位")
                        elif forbidden:
                            errors.append(f"{gap_id}仍属于当前大纲但任务禁止新调研，不能推进写作")
                        elif not researched_gap_evidence(
                            task_dir.parents[2], gap_id, handling,
                            parse_field(retrieval_text, "本轮知识重整运行ID"),
                        ):
                            errors.append(f"{gap_id}仍属于当前大纲，必须有本轮RES原文/核验记录及外部Claim")
            if audit.is_file():
                audit_text = audit.read_text(encoding="utf-8-sig")
                review_heading = "## 本轮知识准备复核"
                if table_header(audit_text, review_heading) != REVISION_REVIEW_HEADER:
                    errors.append("20_文章前知识审核.md：本轮知识准备复核固定表头不符")
                rows = table_rows(audit_text, review_heading)
                required_checks = {"本轮六层检索", "本轮官网正文与凭证", "本轮Claim盘点", "本轮知识准备结论", "30/35重新生成"}
                actual_checks = {row[0].strip() for row in rows if row}
                for check in sorted(required_checks - actual_checks):
                    errors.append(f"20_文章前知识审核.md：本轮知识准备复核缺少“{check}”")
        material = task_dir / "30_本篇知识库资料.md"
        if material.is_file():
            outline_rows = table_rows(
                material.read_text(encoding="utf-8-sig"), "## 四、按大纲使用"
            )
            actual = [row[0].strip().strip("*`# ") for row in outline_rows if row]
            for label in requested:
                if not any(label == value or label in value or value in label for value in actual):
                    errors.append(f"30_本篇知识库资料.md：第四节未逐项对应10中的大纲项：{label}")
    return errors


def validate_completed_task_compatibility(task_dir: Path) -> list[str]:
    """Validate immutable identity and evidence anchors without regrading history.

    Completed tasks may predate the current contract fields and headings.  They
    still need identity, article boundary, and current-result anchors checked;
    missing fields introduced later are compatibility notices, not delivery
    errors.
    """
    errors: list[str] = []
    files = [task_dir / name for name in CONTRACTS if (task_dir / name).is_file()]
    ids = {
        parse_field(path.read_text(encoding="utf-8-sig"), "文章ID")
        for path in files
        if parse_field(path.read_text(encoding="utf-8-sig"), "文章ID")
    }
    expected_id = next(iter(ids), "")
    if not expected_id:
        return [f"{task_dir}：历史任务缺少可确认的文章ID"]
    if not task_dir.name.startswith(expected_id + "_") and task_dir.name != expected_id:
        errors.append(f"{task_dir}：任务目录名未以文章ID开头：{expected_id}")
    if len(ids) > 1:
        errors.append(f"{task_dir}：历史任务文件中的文章ID不一致：{sorted(ids)}")
    article = task_dir / "40_最终文章.md"
    if article.is_file():
        text = article.read_text(encoding="utf-8-sig")
        if text.count(ARTICLE_BODY_START) != 1 or text.count(ARTICLE_BODY_END) != 1:
            errors.append(f"{article}：最终文章正文边界无效")
        elif text.index(ARTICLE_BODY_START) >= text.index(ARTICLE_BODY_END):
            errors.append(f"{article}：最终文章正文边界顺序无效")
    record = task_dir / "50_文章知识使用与Faithfulness记录.md"
    if record.is_file():
        record_text = record.read_text(encoding="utf-8-sig")
        status = parse_field(record_text, "当前状态")
        if status and "等待结果" in record_text and not status.startswith("等待"):
            errors.append(f"{record}：已完成历史记录残留等待结果占位内容")
    return errors


def validate_project_templates(project: Path) -> list[str]:
    errors: list[str] = []
    task_root = project / "04_文章任务"
    if not task_root.is_dir():
        return errors
    for state in ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"):
        state_dir = task_root / state
        if not state_dir.is_dir():
            continue
        for task_dir in (item for item in state_dir.iterdir() if item.is_dir()):
            if state == "40_已完成":
                errors.extend(validate_completed_task_compatibility(task_dir))
            else:
                errors.extend(f"{task_dir}：{item}" for item in validate_task_templates(task_dir))
    return errors


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, contract in CONTRACTS.items():
            lines = [contract["title"], ""]
            for field in contract["fields"]:
                value = TEMPLATE_VERSION if field == contract["version_field"] else "测试值"
                if field == "大纲状态":
                    value = "已确认"
                elif field in {"任务模式", "知识准备模式"}:
                    value = "new_article"
                elif field == "大纲ID":
                    value = "DEMO-OUT-001"
                elif field == "大纲版本":
                    value = "v1"
                elif field == "重写模式":
                    value = "not_applicable"
                elif field in {"基线文章ID", "基线文章版本", "基线大纲ID", "基线大纲版本", "旧版本归档入口"}:
                    value = "不适用"
                lines.append(f"- {field}：{value}")
            if name == "15_检索与知识准备记录.md":
                lines.extend([
                    "- 本轮知识重整运行ID：refresh-self-test-001",
                    "- 本轮知识检索运行ID：research-self-test-001",
                    "- 官网正文抓取凭证：官网正文抓取凭证.json",
                ])
            for heading in contract["headings"]:
                lines.extend(["", heading, ""])
                expected = contract["tables"].get(heading)
                if expected:
                    lines.append("| " + " | ".join(expected) + " |")
                    lines.append("|" + "---|" * len(expected))
                    values = ["测试" for _ in expected]
                    if heading == "## 大纲知识覆盖检查":
                        values = ["标题", "标题成立需要哪些事实", "已覆盖", "CLM-DEMO-001", "无", "使用"]
                    elif heading == "## 固定检索层状态":
                        values = ["客户官网", "已检索并命中", "About正文 https://example.com/about-us/", "CF-001已建立客户官网Claim"]
                    elif heading == "## 来源命中记录":
                        values = ["标题", "https://example.com/about-us/ Company Introduction第1段", "直接支持", "建立客户官网Claim"]
                    elif heading == "## 官网正文核验":
                        values = ["标题", "About Us；https://example.com/about-us/", "2026-09-21", "Company Introduction第1段", "Example Company provides custom packaging services for brands.", "CF-001", "建立客户官网Claim CLM-DEMO-001"]
                    elif heading == "## 候选事实处置明细":
                        values = ["CF-001", "提供定制包装服务", "https://example.com/about-us/ Company Introduction第1段", "已沉淀Formal Claim", "CLM-DEMO-001"]
                    elif heading == "## 本轮事实与Claim盘点":
                        values = ["CF-001 / CLM-DEMO-001", "测试来源第1段", "本轮新证据", "客户知识", "新建", "本轮核验"]
                    elif heading == "## 本轮知识准备复核":
                        values = ["本轮六层检索", "[[15_检索与知识准备记录.md#固定检索层状态]]", "新文章从空白上下文执行", "无"]
                    elif heading == "## 大纲逐项检索与候选事实覆盖":
                        values = ["标题", "已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研", "测试来源第1段", "CF-001", "1", "1", "无", "纳入30"]
                    elif heading == "## 知识准备充分性复核":
                        values = ["标题", "1", "1", "1", "充分", "无"]
                    elif heading == "## 复杂资料处理与原件核对":
                        values = ["无", "无", "本篇无可能相关复杂资料", "不适用", "不适用", "不适用", "不适用", "无", "不适用"]
                    elif heading == "## 复杂资料与原件核对复核":
                        values = ["无", "15：复杂资料处理与原件核对", "不适用", "无复杂资料不影响Claim", "本篇无可能相关复杂资料，复核通过"]
                    elif heading == "## CUS / ANM检测结果":
                        values = ["CUS候选检测", "已核对客户能力、规格、认证、案例、商业条件、公开授权，以及Formal Claim和来源范围", "未触发", "无", "无需处理"]
                    lines.append("| " + " | ".join(values) + " |")
                    if heading == "## CUS / ANM检测结果":
                        lines.append("| ANM异常检测 | 已核对版本、定位、提取、数值、单位和外推信号 | 未触发 | 无 | 无需处理 |")
                    elif heading == "## 大纲知识覆盖检查":
                        lines.append("| 主问题 | 文章要回答的核心问题 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |")
                    elif heading == "## 大纲逐项检索与候选事实覆盖":
                        lines.append("| 主问题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | 测试来源第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |")
                        lines.append("| 测试主题与主要问题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | 测试来源第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |")
                    elif heading == "## 官网正文核验":
                        lines.append("| 主问题 | About Us；https://example.com/about-us/ | 2026-09-21 | Company Introduction第1段 | Example Company provides custom packaging services for brands. | CF-001 | 建立客户官网Claim CLM-DEMO-001 |")
                        lines.append("| 测试主题与主要问题 | About Us；https://example.com/about-us/ | 2026-09-21 | Company Introduction第1段 | Example Company provides custom packaging services for brands. | CF-001 | 建立客户官网Claim CLM-DEMO-001 |")
                    elif heading == "## 知识准备充分性复核":
                        lines.append("| 主问题 | 1 | 1 | 1 | 充分 | 无 |")
                        lines.append("| 测试主题与主要问题 | 1 | 1 | 1 | 充分 | 无 |")
                    elif heading == "## 本轮知识准备复核":
                        lines.append("| 本轮六层检索 | [[15_检索与知识准备记录.md#固定检索层状态]] | 新文章从空白上下文执行 | 无 |")
                        lines.append("| 本轮官网正文与凭证 | [[15_检索与知识准备记录.md#官网正文核验]] | 每个大纲问题均有凭证 | 无 |")
                        lines.append("| 本轮Claim盘点 | [[15_检索与知识准备记录.md#本轮事实与claim盘点]] | 逐候选事实记录处置 | 无 |")
                        lines.append("| 30/35重新生成 | 不适用 | 新文章不适用 | 无 |")
                elif heading == "## 大纲":
                    lines.append("- 测试主题与主要问题")
                elif heading == "## 最终正文":
                    lines.extend([ARTICLE_BODY_START, "测试正文。", ARTICLE_BODY_END])
            path = root / name
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            if name == "15_检索与知识准备记录.md":
                excerpt = "Example Company provides custom packaging services for brands."
                manifest_rows = [
                    {
                        "refresh_run_id": "research-self-test-001",
                        "question": question,
                        "final_url": "https://example.com/about-us/",
                        "fetched_date": "2026-09-21",
                        "position": "Company Introduction第1段",
                        "excerpt": excerpt,
                        "website_id": "PRIMARY-WEBSITE",
                        "source_type": "客户官网",
                        "block_id": "B001",
                        "block_tag": "p",
                        "heading_path": ["About Us", "Company Introduction"],
                        "block_text": excerpt,
                        "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                        "response_sha256": "self-test-response",
                    }
                    for question in ("标题", "主问题", "测试主题与主要问题")
                ]
                (root / "官网正文抓取凭证.json").write_text(
                    json.dumps(manifest_rows, ensure_ascii=False), encoding="utf-8"
                )
            assert not validate_file(path), (name, validate_file(path))
            if name == "20_文章前知识审核.md":
                valid_text = path.read_text(encoding="utf-8")
                broken = valid_text.replace(
                    "| 大纲章节 | 候选事实数 | 已沉淀Claim数 | 计划纳入30的事实块数 | 覆盖结论 | 未采用事实/缺口及入口 |\n|---|---|---|---|---|---|\n| 标题 |",
                    "| 大纲章节 | 候选事实数 | 已沉淀Claim数 | 计划纳入30的事实块数 | 覆盖结论 | 未采用事实/缺口及入口 |\n|---|---|---|---|---|---|\n\n| 标题 |",
                    1,
                )
                assert broken != valid_text
                path.write_text(broken, encoding="utf-8")
                assert any("表格内部存在空行" in error for error in validate_file(path))
                normalized = normalize_markdown_table_spacing(broken)
                assert "|---|---|---|---|---|---|\n| 标题 |" in normalized
                assert normalize_markdown_table_spacing(normalized) == normalized
                path.write_text(valid_text, encoding="utf-8")
            if name == "15_检索与知识准备记录.md":
                valid_text = path.read_text(encoding="utf-8")
                generic_website = valid_text.replace(
                    "About正文 https://example.com/about-us/",
                    "官网主页、Products和Custom Service仅用于链接和品牌导航",
                    1,
                )
                path.write_text(generic_website, encoding="utf-8")
                assert any("仅导航/链接" in item for item in validate_file(path))
                path.write_text(valid_text, encoding="utf-8")
                incomplete = valid_text.replace(
                    "| 标题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | 测试来源第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |",
                    "| 标题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | 测试来源第1段 | CF-001 | 2 | 1 | 无 | 纳入30 |",
                    1,
                )
                path.write_text(incomplete, encoding="utf-8")
                negative_errors = validate_file(path)
                assert any("候选事实ID数量与候选事实数不一致" in item for item in negative_errors)
                assert any("没有逐项记录未采用原因" in item for item in negative_errors)
                path.write_text(valid_text, encoding="utf-8")
                refresh_text = valid_text.replace(
                    "- 知识准备模式：new_article\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：not_applicable\n- 基线文章版本：不适用",
                    "- 知识准备模式：outline_refresh\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：same_outline\n- 基线文章版本：v1",
                    1,
                ) + (
                    "\n## 本轮知识准备结论\n\n| 项目 | 本轮结果 |\n|---|---|\n"
                    "| 基线版本 | v1 |\n| 重新检索范围 | 已检查正式Claim、客户源资料、官网、关联网站、外部Claim、新外部调研和治理队列 |\n"
                    "| 基线Claim数 | 0 |\n| 本轮候选事实数 | 1 |\n| 保留 | 0 |\n| 新增 | 1 |\n"
                    "| 更新 | 0 |\n| 拆分 | 0 |\n| 迁移 | 0 |\n| 失效 | 0 |\n| 转入gap/CUS/MAT/ANM | 0 |\n"
                    "| 中文结论 | 已按本轮问题重新检索并核验当前事实，本结论不阻塞文章重写。 |\n"
                )
                path.write_text(refresh_text, encoding="utf-8")
                assert not validate_file(path), validate_file(path)
                path.write_text(
                    refresh_text.replace("本结论不阻塞文章重写", "继续处理"),
                    encoding="utf-8",
                )
                assert any("不阻塞文章重写" in item for item in validate_file(path))
                path.write_text(valid_text, encoding="utf-8")
            elif name == "20_文章前知识审核.md":
                valid_text = path.read_text(encoding="utf-8")
                refresh_text = valid_text.replace(
                    "- 知识准备模式：new_article\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：not_applicable\n- 基线文章版本：不适用",
                    "- 知识准备模式：outline_refresh\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：same_outline\n- 基线文章版本：v1",
                    1,
                ).replace(
                    "| 30/35重新生成 | 不适用 | 新文章不适用 | 无 |",
                    "| 本轮知识准备结论 | [[15_检索与知识准备记录.md#本轮知识准备结论]] | 已复核 | 不阻塞 |\n"
                    "| 30/35重新生成 | 不适用 | 新文章不适用 | 无 |",
                    1,
                )
                path.write_text(refresh_text, encoding="utf-8")
                assert not validate_file(path), validate_file(path)
                path.write_text(valid_text, encoding="utf-8")
            path.write_text(path.read_text(encoding="utf-8").replace(contract["title"], "# 被简化的文件", 1), encoding="utf-8")
            assert validate_file(path), name
        handled = [[
            "SRC-DEMO001", "资料.pdf；02_源资料/资料.pdf", "第2页图表未被普通索引可靠读取", "可能相关：包含本篇所需规格",
            "MinerU解析第2页图表并核对原PDF", "[[../../02_源资料/20_MinerU按需提取/SRC-DEMO001/第2页.md]]",
            "原PDF第2页表1：型号、单位和脚注与提取稿一致", "无", "已处理并核对",
        ]]
        assert not validate_complex_material_rows(handled)
        handled[0][6] = "已核对一致"
        assert any("原件核对必须写明" in item for item in validate_complex_material_rows(handled))
        gap_id = "GAP-DEMO-001"
        run_id = "refresh-demo-001"
        res_id = "RES-DEMO-001"
        claim_id = "CLM-EXT-DEMO-001"
        handling = f"本轮调研：{res_id}；{claim_id}"
        evidence_dir = root / f"02_源资料/50_外部调研证据/{res_id}_测试"
        evidence_dir.mkdir(parents=True)
        source = evidence_dir / "10_来源原文证据.md"
        review = evidence_dir / "20_调研核验记录.md"
        record = (
            f"- 调研ID：{res_id}\n- 关联缺口：{gap_id}\n"
            f"- 文章知识准备运行ID：{run_id}\n"
        )
        source.write_text(record + "\n## 来源身份\n\n原始网页正文。\n", encoding="utf-8")
        review.write_text(record + f"\n## 去向\n\n{claim_id}。\n", encoding="utf-8")
        formal = root / "03_正式知识/20_外部公共知识/测试.md"
        formal.parent.mkdir(parents=True)
        formal.write_text(f"{claim_id}\n\n来源：{res_id}\n", encoding="utf-8")
        assert researched_gap_evidence(root, gap_id, handling, run_id)
        assert not researched_gap_evidence(root, gap_id, handling, "refresh-other-run")
        assert not researched_gap_evidence(root, "GAP-OTHER-001", handling, run_id)
        formal.write_text(claim_id, encoding="utf-8")
        assert not researched_gap_evidence(root, gap_id, handling, run_id)
    print(f"self-test=passed\ntemplate_version={TEMPLATE_VERSION}\ncontracts={len(CONTRACTS)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.project:
        parser.error("provide --project or --self-test")
    errors = validate_project_templates(args.project.resolve())
    for error in errors:
        print(f"ERROR: {error}")
    print(f"errors={len(errors)}")
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()

