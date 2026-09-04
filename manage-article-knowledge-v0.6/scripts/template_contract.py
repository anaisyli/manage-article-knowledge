#!/usr/bin/env python3
"""Validate the fixed structure of managed v0.6 article Markdown files."""

from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path
from typing import Any


TEMPLATE_VERSION = "v0.6-20260904.5"
ARTICLE_AUDIT_TEMPLATE_VERSION = TEMPLATE_VERSION

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

CONTRACTS: dict[str, dict[str, Any]] = {
    "10_文章知识需求.md": {
        "title": "# 文章知识需求",
        "version_field": "模板版本",
        "fields": ("文章ID", "当前版本", "模板版本", "交接合同版本", "标题", "关键词", "目标语言", "特殊限制", "大纲状态", "原始写作请求", "产品或内容对象", "选题方向", "原始写作要求", "当前状态", "写作Skill"),
        "headings": ("## 外部写作任务接入", "## 大纲", "## 随文章提交文件分类"),
        "tables": {"## 随文章提交文件分类": ("文件名", "原始路径", "SHA-256", "文件性质", "使用范围", "处理结果")},
    },
    "15_检索与知识准备记录.md": {
        "title": "# 检索与知识准备记录",
        "version_field": "模板版本",
        "fields": ("文章ID", "文章版本", "模板版本", "最近更新", "MAT依赖处理"),
        "headings": ("## 固定检索层状态", "## 来源命中记录", "## 候选事实处置明细", "## 大纲逐项检索与候选事实覆盖", "## MAT依赖与资料选择", "## 复杂资料处理与原件核对"),
        "tables": {
            "## 固定检索层状态": ("检索层", "当前状态", "结果或未查原因", "下一步"),
            "## 来源命中记录": ("知识问题", "命中Claim/资料名称与入口", "相关理由", "处理结果"),
            "## 候选事实处置明细": ("候选事实ID", "独立事实摘要", "来源与精确位置", "处置结果", "Formal Claim或排除/治理入口"),
            "## 大纲逐项检索与候选事实覆盖": ("大纲章节", "六层检索范围与结果", "命中来源与精确入口", "候选事实ID", "候选事实数", "已沉淀Claim数", "未采用事实/缺口及原因", "下一步"),
            "## MAT依赖与资料选择": ("MAT ID", "候选SRC ID", "文件名与稳定路径", "关系/处理问题", "决定", "选取或排除范围", "决定依据", "决定方", "当前状态"),
            "## 复杂资料处理与原件核对": COMPLEX_MATERIAL_HEADER,
        },
    },
    "20_文章前知识审核.md": {
        "title": "# 文章前知识审核",
        "version_field": "审核模板版本",
        "fields": ("文章ID", "文章版本", "审核模板版本", "审核日期", "结论", "可用Claim数", "客户来源", "外部来源", "明确排除", "未解决但不阻塞事项", "计划写作素材", "计划写作素材来源索引"),
        "headings": ("## 大纲知识覆盖检查", "## 知识准备充分性复核", "## 复杂资料与原件核对复核", "## CUS / ANM检测结果"),
        "tables": {
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
            "## 一、Faithfulness结果": ("支持事实主张数", "全部事实主张数", "不支持事实主张数", "Faithfulness", "正式Claim映射数", "未映射的支持主张数"),
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
        if not re.fullmatch(r"SRC-[A-Za-z0-9]+", source_id):
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
    text = path.read_text(encoding="utf-8-sig")
    errors: list[str] = []
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
        actual = table_header(text, heading)
        if actual != expected:
            errors.append(
                f"{heading}固定表头不符：应为{' | '.join(expected)}，实际为{' | '.join(actual) or '缺失'}"
            )
        if not table_rows(text, heading):
            errors.append(f"{heading}必须至少有一行真实记录；不能只保留表头")

    if path.name == "10_文章知识需求.md":
        outline = section_body(text, "## 大纲").strip()
        if not outline or outline in {"[原样保存]", "待定", "未提供"}:
            errors.append("## 大纲必须保留非空的简要大纲")
        if parse_field(text, "大纲状态") != "已确认":
            errors.append("必须记录：大纲状态：已确认")
    elif path.name == "15_检索与知识准备记录.md":
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
            elif not re.fullmatch(r"SRC-[A-Za-z0-9]+", source_id):
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
    elif path.name == "30_本篇知识库资料.md":
        facts = section_body(text, "## 一、可直接用于正文的事实")
        if facts.strip() not in {"", "无"} and not re.search(r"证据正文", facts):
            errors.append("第一节的事实素材必须包含证据正文标记")
        data = section_body(text, "## 三、可使用的数据表")
        if data.strip() not in {"", "无"} and not re.search(r"证据正文", data):
            errors.append("第三节的数据块必须包含证据正文标记")
    elif path.name == "35_写作素材来源索引.md":
        if not table_rows(text, "## 写作素材到正式知识映射"):
            errors.append("写作素材到正式知识映射必须至少有一条映射记录")
    elif (contract_name or path.name) == "50_文章知识使用与Faithfulness记录.md":
        status = parse_field(text, "当前状态")
        if status and not status.startswith("等待") and "等待结果" in text:
            errors.append("已导入的50记录不得残留“等待结果”占位内容")
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
        requested = outline_labels(request.read_text(encoding="utf-8-sig"))
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
                lines.append(f"- {field}：{value}")
            for heading in contract["headings"]:
                lines.extend(["", heading, ""])
                expected = contract["tables"].get(heading)
                if expected:
                    lines.append("| " + " | ".join(expected) + " |")
                    lines.append("|" + "---|" * len(expected))
                    values = ["测试" for _ in expected]
                    if heading == "## 大纲知识覆盖检查":
                        values = ["标题", "标题成立需要哪些事实", "已覆盖", "CLM-DEMO-001", "无", "使用"]
                    elif heading == "## 候选事实处置明细":
                        values = ["CF-001", "测试独立事实", "测试来源第1段", "已沉淀Formal Claim", "CLM-DEMO-001"]
                    elif heading == "## 大纲逐项检索与候选事实覆盖":
                        values = ["标题", "已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研", "测试来源第1段", "CF-001", "1", "1", "无", "纳入30"]
                    elif heading == "## 知识准备充分性复核":
                        values = ["标题", "1", "1", "1", "充分", "无"]
                    elif heading == "## 复杂资料处理与原件核对":
                        values = ["无", "无", "本篇无可能相关复杂资料", "不适用", "不适用", "不适用", "不适用", "无", "不适用"]
                    elif heading == "## 复杂资料与原件核对复核":
                        values = ["无", "15：复杂资料处理与原件核对", "不适用", "无复杂资料不影响Claim", "本篇无可能相关复杂资料，复核通过"]
                    elif heading == "## CUS / ANM检测结果":
                        values = ["CUS候选检测", "已核对客户事实、正式Claim和来源范围", "未触发", "无", "无需处理"]
                    lines.append("| " + " | ".join(values) + " |")
                    if heading == "## CUS / ANM检测结果":
                        lines.append("| ANM异常检测 | 已核对版本、定位、提取、数值、单位和外推信号 | 未触发 | 无 | 无需处理 |")
                    elif heading == "## 大纲知识覆盖检查":
                        lines.append("| 主问题 | 文章要回答的核心问题 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |")
                    elif heading == "## 大纲逐项检索与候选事实覆盖":
                        lines.append("| 主问题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | 测试来源第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |")
                        lines.append("| 测试主题与主要问题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | 测试来源第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |")
                    elif heading == "## 知识准备充分性复核":
                        lines.append("| 主问题 | 1 | 1 | 1 | 充分 | 无 |")
                        lines.append("| 测试主题与主要问题 | 1 | 1 | 1 | 充分 | 无 |")
                elif heading == "## 大纲":
                    lines.append("- 测试主题与主要问题")
            path = root / name
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            assert not validate_file(path), (name, validate_file(path))
            if name == "15_检索与知识准备记录.md":
                valid_text = path.read_text(encoding="utf-8")
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

