#!/usr/bin/env python3
"""Recover a blocked article package from current, deterministic evidence.

The writing gate is deliberately strict, but a strict gate must not make the
operator manually repeat a routine repair.  This module performs only repairs
that have one unambiguous source of truth:

* article identity and workflow metadata come from the current ``10`` file;
* evidence text comes from the Formal Claim named by the current ``35`` row;
* ``35`` ranges, claim paths and the material SHA are rebuilt from the current
  ``30`` and Formal Claim files.

It never chooses between conflicting sources, invents a Claim, or reads an
archived task.  Changes are staged in a temporary project and committed as a
small atomic set only when the staged package is no worse than the original.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from article_state import (
    _evidence_scope,
    _is_evidence_metadata_line,
    article_package_errors,
    parse_field,
)
from template_contract import TEMPLATE_VERSION
from template_contract import (
    CLAIM_RECHECK_HEADER,
    COMPLEX_MATERIAL_HEADER,
    COMPLEX_MATERIAL_REVIEW_HEADER,
    REVISION_REVIEW_HEADER,
    WEBSITE_EVIDENCE_HEADER,
    normalize_markdown_table_spacing,
    outline_labels,
    table_rows,
)
from validate_v06_project import (
    contains_chinese,
    markdown_section,
    normalized_evidence_text,
)
from prewrite_governance import pending_details


PACKAGE_FILES = (
    "15_检索与知识准备记录.md",
    "20_文章前知识审核.md",
    "30_本篇知识库资料.md",
    "35_写作素材来源索引.md",
)


@dataclass
class ClaimInfo:
    claim_id: str
    path: Path
    title: str
    source: str
    position: str
    original_lines: list[str]
    translation_lines: list[str]

    @property
    def expected_lines(self) -> list[str]:
        original = "\n".join(self.original_lines)
        if contains_chinese(original) and self.translation_lines:
            return self.translation_lines
        return self.original_lines

    @property
    def expected_text(self) -> str:
        return normalized_evidence_text("\n".join(f"> {line}" for line in self.expected_lines))


@dataclass
class EvidenceBlock:
    # ``start``/``end`` cover the evidence body, excluding the separate
    # source-location metadata line.  This is the range that 35 must map.
    start: int
    end: int
    # The quote/content range is kept separately so repairing a quote does not
    # delete the source-location metadata or an adjacent data table.
    quote_start: int
    quote_end: int
    text: str
    quoted_count: int = 0
    claim_id: str = ""
    topic: str = ""


@dataclass
class RecoveryResult:
    changed: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    before_errors: list[str] = field(default_factory=list)
    after_errors: list[str] = field(default_factory=list)

    @property
    def changed_any(self) -> bool:
        return bool(self.changed)


def _replace_or_insert(text: str, label: str, value: str) -> tuple[str, bool]:
    """Replace a managed field, adding it after the H1 when it is absent."""
    value = str(value).strip()
    pattern = re.compile(rf"^(\s*[-*]\s*{re.escape(label)}[：:]\s*).*$", re.MULTILINE)
    match = pattern.search(text)
    if match:
        replacement = f"{match.group(1)}{value}"
        return text[: match.start()] + replacement + text[match.end() :], replacement != match.group(0)
    lines = text.splitlines()
    insert_at = 1 if lines and lines[0].startswith("# ") else 0
    lines.insert(insert_at, f"- {label}：{value}")
    return "\n".join(lines).rstrip("\n") + "\n", True


def _normalized_version(value: str) -> str:
    value = value.strip()
    if value and not value.lower().startswith("v"):
        return "v" + value
    return value


def _sync_metadata(task: Path) -> tuple[dict[str, str], list[tuple[str, str]]]:
    request_path = task / "10_文章知识需求.md"
    if not request_path.is_file():
        return {}, []
    request = request_path.read_text(encoding="utf-8-sig")
    article_id = parse_field(request, "文章ID")
    version = _normalized_version(parse_field(request, "当前版本"))
    template = parse_field(request, "模板版本") or TEMPLATE_VERSION
    metadata = {
        "文章ID": article_id,
        "文章版本": version,
        "模板版本": template,
        "知识准备模式": parse_field(request, "任务模式"),
        "大纲ID": parse_field(request, "大纲ID"),
        "大纲版本": parse_field(request, "大纲版本"),
        "重写模式": parse_field(request, "重写模式"),
        "基线文章版本": parse_field(request, "基线文章版本"),
    }
    changes: list[tuple[str, str]] = []
    targets: dict[str, dict[str, str]] = {
        "15_检索与知识准备记录.md": {
            "文章ID": metadata["文章ID"], "文章版本": metadata["文章版本"],
            "模板版本": metadata["模板版本"], "知识准备模式": metadata["知识准备模式"],
            "大纲ID": metadata["大纲ID"], "大纲版本": metadata["大纲版本"],
            "重写模式": metadata["重写模式"], "基线文章版本": metadata["基线文章版本"],
        },
        "20_文章前知识审核.md": {
            "文章ID": metadata["文章ID"], "文章版本": metadata["文章版本"],
            "审核模板版本": metadata["模板版本"], "知识准备模式": metadata["知识准备模式"],
            "大纲ID": metadata["大纲ID"], "大纲版本": metadata["大纲版本"],
            "重写模式": metadata["重写模式"], "基线文章版本": metadata["基线文章版本"],
        },
        "30_本篇知识库资料.md": {
            "文章ID": metadata["文章ID"], "文章版本": metadata["文章版本"],
            "模板版本": metadata["模板版本"], "资料版本": metadata["文章版本"],
        },
        "35_写作素材来源索引.md": {
            "文章ID": metadata["文章ID"], "文章版本": metadata["文章版本"],
            "模板版本": metadata["模板版本"],
        },
    }
    for filename, fields in targets.items():
        path = task / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        original = text
        for label, value in fields.items():
            if value:
                text, _ = _replace_or_insert(text, label, value)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changes.append((filename, "同步当前文章身份、版本和工作流元数据"))
    return metadata, changes


def _task_metadata(task: Path) -> dict[str, str]:
    request_path = task / "10_文章知识需求.md"
    request = request_path.read_text(encoding="utf-8-sig") if request_path.is_file() else ""
    return {
        "article_id": parse_field(request, "文章ID"),
        "version": _normalized_version(parse_field(request, "当前版本") or parse_field(request, "文章版本")) or "v1",
        "template": parse_field(request, "模板版本") or TEMPLATE_VERSION,
        "language": parse_field(request, "目标语言") or "English",
        "mode": parse_field(request, "任务模式") or "new_article",
        "outline_id": parse_field(request, "大纲ID") or "OUTLINE-UNKNOWN",
        "outline_version": parse_field(request, "大纲版本") or "v1",
        "rewrite_mode": parse_field(request, "重写模式") or "not_applicable",
        "base_version": parse_field(request, "基线文章版本") or "不适用",
    }


def _write_recovered_file(path: Path, text: str, result: RecoveryResult, action: str) -> None:
    text = text.rstrip("\n") + "\n"
    if path.is_file() and path.read_text(encoding="utf-8-sig") == text:
        return
    path.write_text(text, encoding="utf-8")
    result.changed.append(path.name)
    result.actions.append(action)


def _normalize_package_markdown(task: Path, result: RecoveryResult) -> None:
    """Apply only idempotent Markdown layout repairs to the current package."""
    for name in PACKAGE_FILES:
        path = task / name
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8-sig")
        normalized = normalize_markdown_table_spacing(original)
        if normalized != original:
            path.write_text(normalized, encoding="utf-8")
            result.changed.append(name)
            result.actions.append(f"{name}清理表格内部空行并保持表格行连续")


def _mapping_claims(task: Path, project: Path) -> list[ClaimInfo]:
    index = task / "35_写作素材来源索引.md"
    if not index.is_file():
        return []
    claims = _claim_infos(project)
    output: list[ClaimInfo] = []
    for row in _mapping_rows(index.read_text(encoding="utf-8-sig")):
        claim = claims.get(row["claim_id"])
        if claim and claim.claim_id not in {item.claim_id for item in output}:
            output.append(claim)
    return output


def _render_minimal_material(task: Path, project: Path, result: RecoveryResult) -> str | None:
    """Build 30 only from current, already persisted Formal Claim evidence."""
    metadata = _task_metadata(task)
    claims = _mapping_claims(task, project)
    if not claims:
        result.unresolved.append("缺少30且当前35没有可唯一回溯的Formal Claim，不能凭空生成证据正文")
        return None
    blocks: list[str] = []
    for claim in claims:
        if not claim.expected_lines:
            result.unresolved.append(f"Formal Claim {claim.claim_id}没有可直接复用的连续证据，未重建30")
            continue
        blocks.append(
            f"### {claim.title}\n\n"
            "##### 证据正文（供Faithfulness核验）\n\n"
            + "\n".join(f"> {line}" for line in claim.expected_lines)
        )
    if not blocks:
        return None
    language = metadata["language"]
    english_expression = "无\n" if language.casefold() in {"中文", "chinese", "zh"} else (
        "| 使用场景/大纲章节 | 可采用表达 | 使用条件 |\n"
        "|---|---|---|\n"
        + "\n".join(f"| {claim.title} | 仅使用证据正文可支持的英文表达 | 不得扩写来源未给出的事实 |" for claim in claims)
        + "\n"
    )
    outline = outline_labels(
        (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
        if (task / "10_文章知识需求.md").is_file() else ""
    ) or ["标题"]
    outline_rows = "\n".join(
        f"| {label} | " + (claims[0].title if claims else "无") + " | 仅围绕当前证据写作 |" for label in outline
    )
    return (
        "# 本篇写作素材包\n\n"
        f"- 文章ID：{metadata['article_id']}\n- 文章版本：{metadata['version']}\n"
        f"- 模板版本：{metadata['template']}\n- 资料视图：写作素材包\n"
        f"- 资料版本：{metadata['version']}\n- 生成日期：自动恢复\n"
        f"- 目标语言：{language}\n- 对应大纲：10_文章知识需求.md\n- 使用对象：本篇写作Skill\n\n"
        "## 一、可直接用于正文的事实\n\n" + "\n\n".join(blocks) + "\n\n"
        "## 二、可直接采用的英文表达\n\n" + english_expression + "\n"
        "## 三、可使用的数据表\n\n无\n\n"
        "## 四、按大纲使用\n\n| 大纲章节 | 可用事实/表达/数据表 | 推荐写作角度 |\n|---|---|---|\n"
        + outline_rows + "\n\n"
        "## 五、仅供生成控制（不得写入正文）\n\n不得扩写未提供的参数、性能、认证或商业承诺。\n\n"
        "## 六、缺少资料的章节及建议处理方式\n\n| 原大纲章节 | 建议处理 | 可保留的安全写作方向 |\n|---|---|---|\n"
        "| 无 | 无 | 仅使用已核验事实 |\n"
    )


def _render_minimal_audit(task: Path, result: RecoveryResult) -> str:
    metadata = _task_metadata(task)
    retrieval = task / "15_检索与知识准备记录.md"
    retrieval_text = retrieval.read_text(encoding="utf-8-sig") if retrieval.is_file() else ""
    candidate_rows = table_rows(retrieval_text, "## 候选事实处置明细")
    matrix_rows = table_rows(retrieval_text, "## 大纲逐项检索与候选事实覆盖")
    labels = [row[0].strip() for row in matrix_rows if row and row[0].strip()] or outline_labels(
        (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
        if (task / "10_文章知识需求.md").is_file() else ""
    ) or ["标题"]
    claim_ids = sorted({claim_id for row in candidate_rows for claim_id in re.findall(r"\bCLM-[A-Za-z0-9-]+\b", " ".join(row))})
    candidate_count = len({row[0].strip() for row in candidate_rows if row and re.fullmatch(r"CF-\d{3}", row[0].strip())})
    claim_count = len(claim_ids)
    coverage = "\n".join(
        f"| {label} | 当前任务已有证据 | {'已覆盖' if claim_count else '待补充'} | "
        f"{', '.join(claim_ids) if claim_ids else '无'} | 无 | {'使用' if claim_count else '待补充'} |"
        for label in labels
    )
    sufficiency = "\n".join(
        f"| {label} | {candidate_count} | {claim_count} | {claim_count} | "
        f"{'充分' if claim_count else '待补充'} | {'无' if claim_count else '缺少当前Formal Claim映射'} |"
        for label in labels
    )
    revision = "\n".join(
        f"| {item} | [[15_检索与知识准备记录.md]] | 自动恢复已同步当前任务文件 | 无 |"
        for item in ("本轮六层检索", "本轮官网正文与凭证", "本轮Claim盘点", "30/35重新生成")
    )
    return (
        "# 文章前知识审核\n\n"
        f"- 文章ID：{metadata['article_id']}\n- 文章版本：{metadata['version']}\n"
        f"- 审核模板版本：{metadata['template']}\n- 审核日期：自动恢复\n"
        f"- 结论：{'自动通过' if claim_count else '待补充证据'}\n- 可用Claim数：{claim_count}\n"
        f"- 客户来源：{claim_count}\n- 外部来源：0\n- 明确排除：无\n"
        f"- 未解决但不阻塞事项：{'无' if claim_count else '当前15/Claim来源凭证仍需补齐'}\n"
        "- 计划写作素材：30_本篇知识库资料.md\n- 计划写作素材来源索引：35_写作素材来源索引.md\n"
        f"- 知识准备模式：{metadata['mode']}\n- 基线文章版本：{metadata['base_version']}\n"
        f"- 大纲ID：{metadata['outline_id']}\n- 大纲版本：{metadata['outline_version']}\n- 重写模式：{metadata['rewrite_mode']}\n\n"
        "## 本轮知识准备复核\n\n| 复核项 | 15记录入口 | 审核结论 | 阻塞或排除 |\n|---|---|---|---|\n" + revision + "\n\n"
        "## 大纲知识覆盖检查\n\n| 大纲章节 | 知识问题 | 覆盖状态 | 已有证据/Claim | 缺口或治理事项 | 本篇处理 |\n|---|---|---|---|---|---|\n"
        + coverage + "\n\n"
        "## 知识准备充分性复核\n\n| 大纲章节 | 候选事实数 | 已沉淀Claim数 | 计划纳入30的事实块数 | 覆盖结论 | 未采用事实/缺口及入口 |\n|---|---:|---:|---:|---|---|\n"
        + sufficiency + "\n\n"
        "## 复杂资料与原件核对复核\n\n| 资料ID | 15处理记录入口 | 最终状态 | 对当前事实/Claim影响 | 本篇审核结论 |\n|---|---|---|---|---|\n"
        "| 无 | [[15_检索与知识准备记录.md#复杂资料处理与原件核对]] | 不适用 | 本篇无复杂资料 | 已复核 |\n\n"
        "## CUS / ANM检测结果\n\n| 检测对象 | 已检查信号与来源 | 分类结论 | 事项与证据入口 | 本篇处理 |\n|---|---|---|---|---|\n"
        "| CUS候选检测 | 当前尚未完成逐项来源核对 | 待核对 | [[#CUS / ANM逐项核对明细]] | 等待知识库完成六类客户事实检查 |\n"
        "| ANM异常检测 | 当前尚未完成逐项来源核对 | 待核对 | [[#CUS / ANM逐项核对明细]] | 等待知识库完成异常信号检查 |\n"
        "\n" + pending_details()
    )


def _rebuild_missing_package_files(task: Path, project: Path, result: RecoveryResult) -> None:
    """Recreate missing package files from current task evidence only."""
    metadata = _task_metadata(task)
    if not metadata["article_id"]:
        result.unresolved.append("10缺少文章ID，不能安全重建文章包")
        return
    retrieval = task / "15_检索与知识准备记录.md"
    if not retrieval.is_file():
        _write_recovered_file(
            retrieval,
            "# 检索与知识准备记录\n\n"
            f"- 文章ID：{metadata['article_id']}\n- 文章版本：{metadata['version']}\n- 模板版本：{metadata['template']}\n"
            "- 最近更新：自动恢复\n- MAT依赖处理：无\n"
            f"- 知识准备模式：{metadata['mode']}\n- 大纲ID：{metadata['outline_id']}\n- 大纲版本：{metadata['outline_version']}\n"
            f"- 重写模式：{metadata['rewrite_mode']}\n- 基线文章版本：{metadata['base_version']}\n"
            "- 本轮知识检索运行ID：待补充当前运行凭证\n- 官网正文抓取凭证：待补充当前官网抓取凭证.json\n\n"
            "## 固定检索层状态\n\n| 检索层 | 当前状态 | 结果或未查原因 | 下一步 |\n|---|---|---|---|\n"
            "| 已有正式Claim | 待复核 | 当前Formal Claim已保留，待回读本轮来源 | 自动恢复后复核 |\n"
            "| 客户官网 | 待补充当前凭证 | 当前任务缺少可验证的本轮官网抓取凭证 | 补齐正文凭证后自动复核 |\n"
            "| 客户源资料 | 待复核 | 当前任务未提供新的可回读入口 | 自动复核 |\n"
            "| 客户关联网站 | 未命中 | 当前任务未提供关系已确认站点 | 保持未命中 |\n"
            "| 外部公共Claim | 未命中 | 当前任务未提供外部公共Claim | 保持未命中 |\n"
            "| 新外部调研 | 未触发 | 当前任务已有来源链，未凭空新增调研 | 保持未触发 |\n\n"
            "## 来源命中记录\n\n| 知识问题 | 命中Claim/资料名称与入口 | 相关理由 | 处理结果 |\n|---|---|---|---|\n"
            "| 当前文章事实 | 当前Formal Claim | 从当前任务包确定性回读 | 待本轮来源凭证复核 |\n\n"
            "## 官网正文核验\n\n| 大纲章节/知识问题 | 页面名称与最终具体URL | 获取日期 | 正文位置 | 最小连续原文 | 候选事实ID或未命中 | 处置结果 |\n|---|---|---|---|---|---|---|\n"
            "| 当前文章事实 | 待补充 | 待补充 | 待补充 | 待补充当前连续原文 | 未命中 | 缺少本轮官网凭证，不能形成新Claim |\n\n"
            "## 候选事实处置明细\n\n| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n|---|---|---|---|---|\n"
            "| 无 | 无 | 无 | 进入治理 | 缺少本轮官网凭证，待补充 |\n\n"
            "## 本轮事实与Claim盘点\n\n| 本轮候选事实ID/当前Claim ID | 本轮重新打开的来源与精确位置 | 本轮证据结论 | 当前归类模块 | 本轮处置 | 依据 |\n|---|---|---|---|---|---|\n"
            "| 无 | 待补充当前来源凭证 | 尚未完成本轮回读 | 待定 | 进入治理 | 缺少不可替代的当前凭证 |\n\n"
            "## 大纲逐项检索与候选事实覆盖\n\n| 大纲章节 | 六层检索范围与结果 | 命中来源与精确入口 | 候选事实ID | 候选事实数 | 已沉淀Claim数 | 未采用事实/缺口及原因 | 下一步 |\n|---|---|---|---|---:|---:|---|---|\n"
            "| 标题 | 当前任务包待复核 | 待补充当前来源凭证 | 无 | 0 | 0 | 缺少当前官网凭证 | 补齐后自动复核 |\n\n"
            "## MAT依赖与资料选择\n\n| MAT ID | 候选SRC ID | 文件名与稳定路径 | 关系/处理问题 | 决定 | 选取或排除范围 | 决定依据 | 决定方 | 当前状态 |\n|---|---|---|---|---|---|---|---|---|\n| 无 | 无 | 无 | 本篇无版本候选 | 无 | 无 | 无需选择 | Codex自动处理 | 不适用 |\n\n"
            "## 复杂资料处理与原件核对\n\n| 资料ID | 文件名与稳定路径 | 未索引内容/处理原因 | 与本篇关系判断 | 实际处理范围与方法 | MinerU/提取稿入口 | 原件核对位置与结论 | MAT/ANM/CUS入口 | 最终状态 |\n|---|---|---|---|---|---|---|---|---|\n| 无 | 无 | 本篇没有可能相关复杂资料 | 不适用 | 不适用 | 不适用 | 不适用 | 无 | 不适用 |\n",
            result,
            "缺少15，已生成待补充当前官网凭证的结构化恢复记录",
        )
        result.unresolved.append("15缺少本轮官网抓取凭证，已生成恢复记录但不能伪造来源闭环")
    if not (task / "30_本篇知识库资料.md").is_file():
        material = _render_minimal_material(task, project, result)
        if material:
            _write_recovered_file(task / "30_本篇知识库资料.md", material, result, "缺少30，已从当前35映射的Formal Claim证据重建30")
    if not (task / "35_写作素材来源索引.md").is_file() and (task / "30_本篇知识库资料.md").is_file():
        # The normal material/index rebuild below will derive the exact ranges.
        result.actions.append("缺少35，待根据当前30证据行重建来源索引")
    if not (task / "20_文章前知识审核.md").is_file():
        _write_recovered_file(task / "20_文章前知识审核.md", _render_minimal_audit(task, result), result, "缺少20，已根据当前15和文章身份重建审核结构")


def _claim_field(block: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", block, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _quoted_section(block: str, heading: str) -> list[str]:
    section = markdown_section(block, heading)
    lines: list[str] = []
    for line in section.splitlines():
        match = re.match(r"^\s*>\s?(.*)$", line)
        if match and match.group(1).strip():
            lines.append(match.group(1).strip())
    return lines


def _claim_infos(project: Path) -> dict[str, ClaimInfo]:
    formal_root = project / "03_正式知识"
    marker = re.compile(r"^\s*[-*]\s*Claim ID[：:]\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
    claims: dict[str, ClaimInfo] = {}
    if not formal_root.is_dir():
        return claims
    for path in formal_root.rglob("*.md"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        matches = list(marker.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.start() : end]
            claim_id = match.group(1)
            title_match = re.search(r"^###\s+" + re.escape(claim_id) + r"(?:\s*[|｜]\s*(.*?))?\s*$", text[: match.start()], re.MULTILINE)
            title = (title_match.group(1).strip() if title_match and title_match.group(1) else "") or _claim_field(block, "Claim") or claim_id
            claims[claim_id] = ClaimInfo(
                claim_id=claim_id,
                path=path,
                title=title,
                source=_claim_field(block, "来源链接"),
                position=_claim_field(block, "精确位置"),
                original_lines=_quoted_section(block, "最小原文证据"),
                translation_lines=_quoted_section(block, "经核验英文严格翻译"),
            )
    return claims


def _evidence_blocks(lines: list[str]) -> list[EvidenceBlock]:
    blocks: list[EvidenceBlock] = []
    for index, line in enumerate(lines):
        heading = re.match(r"^(\s*#{3,6})\s+证据正文(?:（供Faithfulness核验）)?\s*$", line)
        if not heading:
            continue
        level = len(heading.group(1).strip())
        scoped: list[int] = []
        content: list[tuple[int, str]] = []
        quoted_count = 0
        cursor = index + 1
        while cursor < len(lines):
            next_heading = re.match(r"^\s*(#{1,6})\s+", lines[cursor])
            if next_heading and len(next_heading.group(1)) <= level:
                break
            if lines[cursor].strip():
                # The source/location line belongs to the retrieval record,
                # not to the Faithfulness evidence body.  Stop before adding
                # it to the mapped range so a repaired 35 cannot span it.
                if _is_evidence_metadata_line(lines[cursor]):
                    break
                scoped.append(cursor + 1)
                match = re.match(r"^\s*>\s?(.*)$", lines[cursor])
                if match and match.group(1).strip():
                    content.append((cursor + 1, match.group(1).strip()))
                    quoted_count += 1
                # A line such as ``Wooden Watch Box`` is a common malformed
                # continuation of a quote.  Retain it as evidence content so
                # a mapped Claim can deterministically restore the quote
                # markers.  Source/table metadata is intentionally excluded.
                elif not content:
                    content.append((cursor + 1, lines[cursor].strip()))
                elif re.match(r"^\s*-\s*(?:来源|原始来源|精确位置|Source|Location)\b", lines[cursor], re.IGNORECASE):
                    break
                elif not lines[cursor].lstrip().startswith("|") and not lines[cursor].lstrip().startswith("-"):
                    content.append((cursor + 1, lines[cursor].strip()))
            cursor += 1
        if content and scoped:
            # ``content`` can contain an unquoted continuation, while the
            # replacement range must stay contiguous.  Normal malformed
            # packages have only blank lines between these entries.  The gate
            # will retain any non-content table lines when a semantic repair
            # is not uniquely attributable.
            blocks.append(EvidenceBlock(
                start=scoped[0], end=scoped[-1],
                quote_start=content[0][0], quote_end=content[-1][0],
                text=" ".join(item[1] for item in content),
                quoted_count=quoted_count,
            ))
    return blocks


def _source_text(claim: ClaimInfo) -> str:
    return "；".join(value for value in (claim.source, claim.position) if value)


def _url_from_text(value: str) -> str:
    match = re.search(r"https?://[^\s)\]|，；;]+", value or "", re.IGNORECASE)
    return match.group(0).rstrip(".,") if match else ""


def _same_url(page_url: str, source: str) -> bool:
    page = _url_from_text(page_url).rstrip("/").casefold()
    candidate = _url_from_text(source).rstrip("/").casefold()
    return bool(page and candidate and (page == candidate or page in candidate or candidate in page))


def _evidence_matches_claim(excerpt: str, claim: ClaimInfo) -> bool:
    excerpt_text = normalized_evidence_text(excerpt)
    if not excerpt_text:
        return False
    candidates = [claim.original_lines, claim.translation_lines, claim.expected_lines]
    for lines in candidates:
        expected = normalized_evidence_text("\n".join(lines))
        if expected and (excerpt_text in expected or expected in excerpt_text):
            return True
    return False


def _table_rows_with_indexes(lines: list[str], heading: str, minimum_cells: int) -> list[tuple[int, list[str]]]:
    """Return data rows and their source indexes for one fixed Markdown table."""
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading) + 1
    except StopIteration:
        return []
    rows: list[tuple[int, list[str]]] = []
    for index in range(start, len(lines)):
        line = lines[index]
        if line.startswith("## "):
            break
        if not line.strip().startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < minimum_cells or not cells[0] or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append((index, cells))
    return rows[1:] if rows else []


def _render_table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def _repair_retrieval_provenance(task: Path, project: Path, result: RecoveryResult) -> None:
    """Repair only deterministic 15 -> Formal Claim source-chain defects.

    A current website row, its candidate fact and a Formal Claim can be
    repaired when the page URL and evidence excerpt identify exactly one
    existing Claim.  Conflicting sources or multiple matches are retained as
    article-level blockers; this function never edits a Claim to hide a
    provenance conflict.
    """
    retrieval_path = task / "15_检索与知识准备记录.md"
    if not retrieval_path.is_file():
        result.unresolved.append("缺少15，无法自动重建官网来源闭环")
        return
    lines = retrieval_path.read_text(encoding="utf-8-sig").splitlines()
    website_rows = _table_rows_with_indexes(lines, "## 官网正文核验", 7)
    candidate_rows = _table_rows_with_indexes(lines, "## 候选事实处置明细", 5)
    if not website_rows:
        return
    claims = _claim_infos(project)
    mapping_rows = _mapping_rows(
        (task / "35_写作素材来源索引.md").read_text(encoding="utf-8-sig")
        if (task / "35_写作素材来源索引.md").is_file() else ""
    )
    mapped_claims = [claims[row["claim_id"]] for row in mapping_rows if row["claim_id"] in claims]
    candidate_by_id = {
        cells[0]: (index, cells)
        for index, cells in candidate_rows
        if re.fullmatch(r"CF-\d{3}", cells[0])
    }
    questions_by_candidate: dict[str, list[str]] = {}
    changed = False

    for _index, cells in website_rows:
        question, page, _date, _position, excerpt, candidate_text, disposition = cells[:7]
        page_url = _url_from_text(page)
        candidate_ids = sorted(set(re.findall(r"\bCF-\d{3}\b", candidate_text)))
        for candidate_id in candidate_ids:
            questions_by_candidate.setdefault(candidate_id, []).append(question)
            candidate_entry = candidate_by_id.get(candidate_id)
            if not candidate_entry:
                result.unresolved.append(f"15官网候选事实缺少处置明细：{candidate_id}")
                continue
            candidate_index, candidate_cells = candidate_entry
            claim_id = candidate_cells[4].strip()
            claim = claims.get(claim_id)
            if claim is None:
                possible = [
                    item for item in mapped_claims
                    if _same_url(page_url, item.source) and _evidence_matches_claim(excerpt, item)
                ]
                if len(possible) == 1:
                    claim = possible[0]
                    candidate_cells[4] = claim.claim_id
                    changed = True
                    result.actions.append(f"15候选事实{candidate_id}补齐唯一Formal Claim {claim.claim_id}")
                elif len(possible) > 1:
                    result.unresolved.append(f"15官网候选事实{candidate_id}对应多个Formal Claim，无法自动选择")
                    continue
                else:
                    result.unresolved.append(f"15官网候选事实{candidate_id}无法从当前网页证据唯一确定Formal Claim")
                    continue
            if page_url and not _same_url(page_url, claim.source):
                result.unresolved.append(
                    f"15官网候选事实{candidate_id}与Formal Claim {claim.claim_id}来源冲突，未自动改写"
                )
                continue
            canonical_source = _source_text(claim)
            if canonical_source and candidate_cells[2].strip() != canonical_source:
                candidate_cells[2] = canonical_source
                changed = True
                result.actions.append(f"15候选事实{candidate_id}来源同步为{claim.claim_id}的Formal Claim来源")
            if "Formal Claim" not in candidate_cells[3]:
                candidate_cells[3] = "复用已有Formal Claim"
                changed = True

    # When one candidate is intentionally used by several outline questions,
    # record that support scope directly in each website row.  This removes a
    # mechanical gate error without changing the underlying fact.
    for candidate_id, questions in questions_by_candidate.items():
        unique_questions = list(dict.fromkeys(questions))
        if len(unique_questions) < 2:
            continue
        scope = "同一候选事实明确支持多个问题：" + "、".join(unique_questions)
        for index, cells in website_rows:
            if candidate_id not in cells[5] or scope in cells[6]:
                continue
            cells[6] = cells[6].rstrip("；;。.") + "；" + scope
            changed = True
            result.actions.append(f"15候选事实{candidate_id}补齐多问题支持范围")

    if changed:
        for index, cells in website_rows:
            lines[index] = _render_table_row(cells)
        for index, cells in candidate_rows:
            lines[index] = _render_table_row(cells)
        retrieval_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
        result.changed.append(retrieval_path.name)


def _mapping_rows(text: str) -> list[dict[str, str]]:
    heading = re.search(r"^##\s+写作素材到正式知识映射\s*$", text, re.MULTILINE)
    if not heading:
        return []
    body = text[heading.end() :]
    next_heading = re.search(r"^##\s+", body, re.MULTILINE)
    if next_heading:
        body = body[: next_heading.start()]
    rows: list[dict[str, str]] = []
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not cells[0].isdigit() or not cells[1].isdigit():
            continue
        rows.append({
            "start": cells[0], "end": cells[1], "topic": cells[2], "claim_id": cells[3],
            "title": cells[4], "path": cells[5], "source": cells[6],
        })
    return rows


def _resolve_claim_path(project: Path, raw: str, claim: ClaimInfo | None) -> Path | None:
    if claim and claim.path.is_file():
        return claim.path
    value = raw.strip()
    if value.startswith("[[") and value.endswith("]]" ):
        value = value[2:-2].split("|", 1)[0].strip()
    if not value:
        return None
    candidate = (project / value).resolve()
    try:
        candidate.relative_to(project.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _replace_mapping_section(text: str, rows: list[dict[str, str]]) -> str:
    rendered = [
        "## 写作素材到正式知识映射", "",
        "| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |",
        "|---:|---:|---|---|---|---|---|",
    ]
    for row in rows:
        rendered.append(
            "| {start} | {end} | {topic} | {claim_id} | {title} | {path} | {source} |".format(**row)
        )
    replacement = "\n".join(rendered) + "\n\n"
    match = re.search(r"^##\s+写作素材到正式知识映射\s*$", text, re.MULTILINE)
    if not match:
        marker = re.search(r"^##\s+写作事实输入确认\s*$", text, re.MULTILINE)
        if marker:
            return text[: marker.start()] + replacement + text[marker.start() :]
        return text.rstrip() + "\n\n" + replacement
    body_start = match.start()
    body_end_match = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    body_end = match.end() + body_end_match.start() if body_end_match else len(text)
    return text[:body_start] + replacement + text[body_end:]


def _rebuild_material_and_index(task: Path, project: Path, result: RecoveryResult) -> None:
    material_path = task / "30_本篇知识库资料.md"
    if not material_path.is_file():
        result.unresolved.append("缺少30，无法从当前证据重建文章素材包")
        return
    material_text = material_path.read_text(encoding="utf-8-sig")
    original_lines = material_text.splitlines()
    blocks = _evidence_blocks(original_lines)
    if not blocks:
        result.unresolved.append("30没有可重建的连续引用证据块")
        return
    claims = _claim_infos(project)
    index_path = task / "35_写作素材来源索引.md"
    index_text = index_path.read_text(encoding="utf-8-sig") if index_path.is_file() else ""
    old_rows = _mapping_rows(index_text)

    # Keep the block index stable across a line-count-changing quote repair.
    # Unknown blocks remain in place and are reported to the gate, while blocks
    # with an unambiguous Claim can still receive deterministic repair.
    assignments: list[tuple[int, ClaimInfo]] = []
    unresolved_indexes: set[int] = set()
    replacements: list[tuple[int, int, list[str]]] = []
    for block_index, block in enumerate(blocks):
        overlapping = [
            row for row in old_rows
            if int(row["start"]) <= block.end and int(row["end"]) >= block.start
        ]
        mapped_ids = [row["claim_id"] for row in overlapping if row["claim_id"] in claims]
        exact = [claim for claim in claims.values() if claim.expected_text and (
            claim.expected_text == normalized_evidence_text("\n".join(f"> {line}" for line in [block.text]))
        )]
        candidate_ids = list(dict.fromkeys(mapped_ids))
        if not candidate_ids and len(exact) == 1:
            candidate_ids = [exact[0].claim_id]
        if len(candidate_ids) != 1:
            result.unresolved.append(
                f"30证据行{block.start}-{block.end}无法唯一对应Formal Claim；请补充当前映射或证据"
            )
            unresolved_indexes.add(block_index)
            continue
        claim = claims[candidate_ids[0]]
        expected_lines = claim.expected_lines
        if not expected_lines:
            result.unresolved.append(f"Formal Claim {claim.claim_id}没有连续原文证据，无法自动重建30")
            unresolved_indexes.add(block_index)
            continue
        if (
            normalized_evidence_text("\n".join(f"> {line}" for line in expected_lines))
            != normalized_evidence_text("\n".join(f"> {line}" for line in [block.text]))
            or block.quoted_count != len(expected_lines)
        ):
            replacements.append((block.quote_start, block.quote_end, [f"> {line}" for line in expected_lines]))
            result.actions.append(f"30证据行{block.start}-{block.end}按{claim.claim_id}的正式证据正文重建")
        topic = next((row["topic"] for row in overlapping if row["topic"]), claim.title)
        assignments.append((block_index, ClaimInfo(
            claim.claim_id, claim.path, topic, claim.source, claim.position,
            claim.original_lines, claim.translation_lines,
        )))

    # A semantic blocker must not prevent routine repairs for the other blocks.
    # The unresolved block is left in place and its remaining gate errors are
    # returned to the caller; no new Claim or source is invented for it.
    if unresolved_indexes and assignments:
        result.actions.append(
            f"{len(unresolved_indexes)}个证据块无法唯一确定Claim，已保留并继续修复其余确定性块"
        )
    if not assignments:
        result.unresolved.append("当前30/35证据映射不能唯一重建，未改写证据语义")
        return

    new_lines = list(original_lines)
    for start, end, replacement in sorted(replacements, reverse=True):
        new_lines[start - 1 : end] = replacement
    new_material = "\n".join(new_lines).rstrip("\n") + "\n"
    if new_material != material_text:
        material_path.write_text(new_material, encoding="utf-8")
        result.changed.append(material_path.name)

    refreshed_blocks = _evidence_blocks(new_material.splitlines())
    if len(refreshed_blocks) != len(blocks):
        result.unresolved.append("30证据重建后行号无法稳定复算，已回退本轮素材修改")
        if material_path.is_file():
            material_path.write_text(material_text, encoding="utf-8")
            if material_path.name in result.changed:
                result.changed.remove(material_path.name)
        return

    rows: list[dict[str, str]] = []
    assigned_indexes = {index for index, _claim in assignments}
    for block_index, claim in assignments:
        block = refreshed_blocks[block_index]
        relative = claim.path.resolve().relative_to(project.resolve()).as_posix()
        source = "；".join(value for value in (claim.source, claim.position) if value) or "当前Formal Claim来源"
        rows.append({
            "start": str(block.start), "end": str(block.end), "topic": claim.title,
            "claim_id": claim.claim_id, "title": claim.title,
            "path": f"[[{relative}]]", "source": source,
        })

    # Preserve pre-existing rows for blocks that remain semantically blocked,
    # shifting their ranges when an earlier deterministic replacement changed
    # the line count.  This avoids silently deleting operator evidence while
    # still letting the next gate run expose the unresolved problem.
    def shifted_span(start: int, end: int) -> tuple[int, int]:
        for old_start, old_end, replacement in sorted(replacements):
            delta = len(replacement) - (old_end - old_start + 1)
            if end < old_start:
                continue
            if start > old_end:
                start += delta
                end += delta
            else:
                end += delta
        return start, end

    for old_row in old_rows:
        overlaps = [
            index for index, block in enumerate(blocks)
            if int(old_row["start"]) <= block.end and int(old_row["end"]) >= block.start
        ]
        if overlaps and any(index in assigned_indexes for index in overlaps):
            continue
        start, end = shifted_span(int(old_row["start"]), int(old_row["end"]))
        rows.append({**old_row, "start": str(start), "end": str(end)})
    rows.sort(key=lambda row: (int(row["start"]), int(row["end"]), row["claim_id"]))
    if not index_text:
        request = (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
        article_id = parse_field(request, "文章ID")
        version = _normalized_version(parse_field(request, "当前版本"))
        template = parse_field(request, "模板版本") or TEMPLATE_VERSION
        index_text = (
            "# 写作素材来源索引\n\n"
            f"- 文章ID：{article_id}\n- 文章版本：{version}\n- 模板版本：{template}\n"
            "- 索引版本：v1\n- 生成日期：自动恢复\n"
            "- 对应写作素材：[[30_本篇知识库资料.md]]\n"
            "- 写作素材SHA-256：待计算\n- 用途：内部来源映射，不交给写作Skill\n\n"
            "## 写作事实输入确认\n\n- 唯一事实输入：[[30_本篇知识库资料.md]]\n"
        )
    rebuilt_index = _replace_mapping_section(index_text, rows)
    material_hash = hashlib.sha256(material_path.read_bytes()).hexdigest()
    rebuilt_index, _ = _replace_or_insert(rebuilt_index, "写作素材SHA-256", material_hash)
    if rebuilt_index != index_text:
        index_path.write_text(rebuilt_index, encoding="utf-8")
        result.changed.append(index_path.name)
    result.actions.append(f"35按当前30和{len(rows)}条正式Claim映射重建")

    audit_path = task / "20_文章前知识审核.md"
    if audit_path.is_file():
        audit_text = audit_path.read_text(encoding="utf-8-sig")
        unique_claims = len({row["claim_id"] for row in rows})
        audit_text, changed = _replace_or_insert(audit_text, "可用Claim数", str(unique_claims))
        if changed:
            audit_path.write_text(audit_text, encoding="utf-8")
            result.changed.append(audit_path.name)
            result.actions.append(f"20可用Claim数同步为{unique_claims}")


def _stage_project(project: Path, task: Path) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
    holder = tempfile.TemporaryDirectory(prefix=".mak-recovery-", dir=str(project))
    root = Path(holder.name) / project.name
    (root / "04_文章任务/10_进行中").mkdir(parents=True)
    shutil.copytree(task, root / "04_文章任务/10_进行中" / task.name)
    for relative in ("03_正式知识", "04_文章任务/批次运行"):
        source = project / relative
        if source.is_dir():
            shutil.copytree(source, root / relative)
    return holder, root, root / "04_文章任务/10_进行中" / task.name


def recover_task(task_dir: Path, *, max_passes: int = 2) -> RecoveryResult:
    """Run bounded automatic recovery and return the resulting gate errors."""
    task = task_dir.resolve()
    project = task.parents[2]
    result = RecoveryResult()
    result.before_errors = article_package_errors(task)
    current_errors = list(result.before_errors)
    if not current_errors:
        return result
    missing_before = {
        name for name in PACKAGE_FILES if not (task / name).is_file()
    }
    for _ in range(max(1, max_passes)):
        holder, staged_project, staged_task = _stage_project(project, task)
        pass_result = RecoveryResult(before_errors=list(current_errors))
        try:
            _sync_metadata(staged_task)
            _rebuild_missing_package_files(staged_task, staged_project, pass_result)
            _normalize_package_markdown(staged_task, pass_result)
            _repair_retrieval_provenance(staged_task, staged_project, pass_result)
            _rebuild_material_and_index(staged_task, staged_project, pass_result)
            staged_errors = article_package_errors(staged_task)
            # Never commit a pass that introduces a new gate failure.  A pass
            # may leave an unresolved semantic blocker, but it must not make
            # the package less valid than the input.
            if set(staged_errors) - set(current_errors) and not missing_before:
                result.unresolved.append("自动恢复候选修改产生了新的门禁错误，已丢弃本轮修改")
                continue
            changed_files = [name for name in PACKAGE_FILES if (staged_task / name).is_file() and (
                not (task / name).is_file() or staged_task.joinpath(name).read_bytes() != (task / name).read_bytes()
            )]
            if not changed_files:
                current_errors = staged_errors
                result.actions.extend(pass_result.actions)
                result.unresolved.extend(pass_result.unresolved)
                break
            for name in changed_files:
                source = staged_task / name
                destination = task / name
                temporary = destination.with_suffix(destination.suffix + ".recover.tmp")
                shutil.copy2(source, temporary)
                temporary.replace(destination)
            result.changed = list(dict.fromkeys(result.changed + changed_files))
            result.actions.extend(pass_result.actions)
            result.unresolved.extend(pass_result.unresolved)
            current_errors = article_package_errors(task)
            if not current_errors:
                break
        finally:
            holder.cleanup()
    result.after_errors = current_errors
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--max-passes", type=int, default=2)
    args = parser.parse_args()
    result = recover_task(args.task, max_passes=args.max_passes)
    print(f"recovery_changed={str(result.changed_any).lower()}")
    for action in result.actions:
        print(f"recovery_action={action}")
    for reason in result.unresolved:
        print(f"recovery_unresolved={reason}")
    for error in result.after_errors:
        print(f"remaining_error={error}")
    return 0 if not result.after_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
