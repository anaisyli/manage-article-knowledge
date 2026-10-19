"""Check evidence-backed pre-writing governance decisions, not just summaries."""

from __future__ import annotations

import re
from pathlib import Path


DETAIL_HEADING = "## CUS / ANM逐项核对明细"
DETAIL_HEADER = (
    "检测对象", "检测类别", "本篇事实或适用范围", "已核对来源与定位", "核对依据原文",
    "核对结论", "判断依据", "事项与证据入口", "本篇处理",
)
CATEGORIES = {
    "CUS候选检测": ("客户能力", "规格", "认证", "案例", "商业条件", "公开授权"),
    "ANM异常检测": ("版本", "定位", "提取", "数值与单位", "OCR", "翻译与规范化", "来源冲突", "残缺与外推"),
}
RESULTS = {"已核验", "不适用", "安全排除", "需客户确认", "事实异常", "自动修复并留痕", "待核对"}
LEDGERS = {
    "CUS": ("05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md", "## 当前事项", {"无需询问", "已完成"}),
    "ANM": ("05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md", "## 当前异常", {"已解决", "已完成处置（原文未修复）"}),
}
ISSUE_RE = re.compile(r"(?<![A-Za-z0-9-])(?:[A-Za-z0-9_.]+-)*(?:CUS|ANM)-[0-9]+\b")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _reference_text(task: Path, project: Path, value: str) -> str | None:
    """Resolve an explicit local evidence link and its heading without guessing."""
    targets = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", value)
    if not targets:
        targets = re.findall(r"\[[^\]]*\]\(([^)]+)\)", value)
    if len(targets) != 1:
        return None
    raw, _, anchor = targets[0].partition("#")
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [task / path, project / path]
    existing = {item.resolve() for item in candidates if item.is_file()}
    if len(existing) != 1:
        return None
    selected = existing.pop()
    if selected.name.startswith(("20_", "30_", "35_")) or "90_归档" in selected.parts:
        return None
    # A freshly written task note is not an independent source. Keep the
    # established request/retrieval/handling entries for historical records.
    if selected.is_relative_to(task.resolve()) and selected.name not in {
        "10_文章知识需求.md", "15_检索与知识准备记录.md", "文章前问题与处理单.md",
    }:
        return None
    if selected.suffix.lower() not in {".md", ".txt", ".html", ".htm", ".json"}:
        return None
    text = selected.read_text(encoding="utf-8-sig")
    if not anchor:
        return text
    headings = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    for index, heading in enumerate(headings):
        if heading.group(2).casefold() != anchor.casefold():
            continue
        end = next((later.start() for later in headings[index + 1:] if len(later.group(1)) <= len(heading.group(1))), len(text))
        return text[heading.end():end]
    return None


def _issue_error(project: Path, item_id: str) -> tuple[str, bool]:
    from template_contract import section_body, table_rows

    kind = "CUS" if re.search(r"(?:^|-)CUS-", item_id) else "ANM"
    relative, heading, closed = LEDGERS[kind]
    path = project / relative
    if not path.is_file():
        return f"{item_id}的真实台账不存在：{relative}", False
    text = path.read_text(encoding="utf-8-sig")
    rows = [row for row in table_rows(text, heading) if row and row[0] == item_id]
    details = list(re.finditer(rf"(?m)^###\s+{re.escape(item_id)}[｜|].+$", text))
    if len(rows) != 1 or len(details) != 1:
        return f"{item_id}必须有唯一真实主表行和同ID详情", False
    detail_match = details[0]
    detail_end = re.search(r"(?m)^###\s+", text[detail_match.end():])
    detail = text[detail_match.end(): detail_match.end() + detail_end.start()] if detail_end else text[detail_match.end():]
    if not detail.strip():
        return f"{item_id}的事项详情为空", False
    if len(rows[0]) < (8 if kind == "CUS" else 9) or any(not value.strip() or value in {"待填写", "待补充"} for value in rows[0]):
        return f"{item_id}的台账主表未填写完整", False
    status_index = 4 if kind == "CUS" else 5
    return "", rows[0][status_index] in closed


def governance_errors(task: Path, project: Path | None = None) -> list[str]:
    """Require real evidence, linked governance, and a safe article disposition."""
    from template_contract import parse_field, table_header, table_rows

    project = project or task.parents[2]
    audit = task / "20_文章前知识审核.md"
    if not audit.is_file():
        return ["缺少20，知识库必须继续完成CUS/ANM逐项核对"]
    text = audit.read_text(encoding="utf-8-sig")
    request = task / "10_文章知识需求.md"
    request_text = request.read_text(encoding="utf-8-sig") if request.is_file() else ""
    from governance_source_check import PROTOCOL, record_errors
    strict_sources = parse_field(request_text, "来源核验模板版本") == PROTOCOL
    errors: list[str] = []
    protocol = parse_field(request_text, "来源核验模板版本")
    if protocol and protocol != PROTOCOL:
        errors.append(f"未知来源核验模板版本：{protocol}；不得自动降级为历史核验规则")
    rows = table_rows(text, DETAIL_HEADING)
    if tuple(table_header(text, DETAIL_HEADING)) != DETAIL_HEADER or not rows:
        errors.append("20缺少CUS/ANM逐项核对明细；知识库继续读取来源并完成检测，不得默认未触发")
    seen: set[tuple[str, str]] = set()
    triggered: dict[str, set[str]] = {detector: set() for detector in CATEGORIES}
    fixed = False
    for row in rows:
        if len(row) != len(DETAIL_HEADER):
            errors.append("CUS/ANM逐项核对明细列数错误")
            continue
        detector, category, scope, source, excerpt, result, reason, entry, handling = row
        label = f"{detector}/{category}"
        if detector not in CATEGORIES or category not in CATEGORIES[detector]:
            errors.append(f"未知检测类别：{label}")
            continue
        seen.add((detector, category))
        if any(not value or value in {"无", "已检查", "无异常", "待填写", "待补充"} for value in (scope, excerpt, reason)):
            errors.append(f"{label}缺少具体对象、核对依据原文或判断依据")
        if result not in RESULTS:
            errors.append(f"{label}核对结论无效：{result}")
        if result == "待核对":
            errors.append(f"{label}尚未检测，知识库继续核对，不得签发writing_ready")
            continue
        if strict_sources or re.search(r"\bGC-\d{3,}\b", source):
            errors.extend(record_errors(task, project, detector, category, source, excerpt, result, scope, reason))
        else:
            evidence = _reference_text(task, project, source)
            if evidence is None:
                errors.append(f"{label}缺少可回读的受管来源/定位（不能使用自建任务笔记、20/30/35或归档结论）")
            elif not excerpt or _compact(excerpt) not in _compact(evidence):
                errors.append(f"{label}核对依据原文不在所指来源位置中")
        if result == "已核验" and "10_文章知识需求.md" in source:
            errors.append(f"{label}写作需求不能证明客户事实或来源无异常")
        if not handling or not handling.startswith(("按证据使用", "不涉及", "已排除", "已缩小", "等待")):
            errors.append(f"{label}必须明确按证据使用/不涉及/已排除/已缩小/等待及具体处理")
        if handling.startswith("等待"):
            errors.append(f"{label}仍依赖待确认事实，不得签发writing_ready")
        if result == "不适用" and not handling.startswith("不涉及"):
            errors.append(f"{label}不适用必须说明本篇不涉及的范围")
        if result == "安全排除" and not handling.startswith(("已排除", "已缩小")):
            errors.append(f"{label}安全排除必须已落实排除或缩小")
        issue_ids = set(ISSUE_RE.findall(entry))
        if result in {"需客户确认", "事实异常"}:
            kind = "CUS" if result == "需客户确认" else "ANM"
            matching = {item for item in issue_ids if re.search(rf"(?:^|-){kind}-", item)}
            if not matching:
                errors.append(f"{label}已触发但没有真实{kind}事项入口")
            triggered[detector].update(issue_ids)
            if not handling.startswith(("已排除", "已缩小", "按证据使用")):
                errors.append(f"{label}异常或待确认事实尚未隔离")
        for item in issue_ids:
            error, closed = _issue_error(project, item)
            if error:
                errors.append(error)
            elif result in {"需客户确认", "事实异常"} and handling.startswith("按证据使用") and not closed:
                errors.append(f"{label}事项{item}尚未核实关闭，不能按证据使用")
        if result == "自动修复并留痕":
            fixed = True
            if "处理记录" not in entry or _reference_text(task, project, entry) is None:
                errors.append(f"{label}自动修复缺少可回读处理记录")
    for detector, categories in CATEGORIES.items():
        missing = [category for category in categories if (detector, category) not in seen]
        if missing:
            errors.append(f"{detector}逐项核对缺少类别：{'、'.join(missing)}")
    summaries = {row[0]: row for row in table_rows(text, "## CUS / ANM检测结果") if len(row) == 5}
    for detector in CATEGORIES:
        summary = summaries.get(detector)
        if not summary:
            errors.append(f"缺少{detector}汇总结论")
            continue
        conclusion, entry = summary[2:4]
        if conclusion not in {"未触发", "已复用", "已登记", "自动修复并留痕", "待核对"}:
            errors.append(f"{detector}汇总尚未完成或分类无效：{conclusion}")
        if conclusion == "待核对":
            errors.append(f"{detector}汇总仍为待核对，知识库继续检测，不得签发writing_ready")
        summary_ids = set(ISSUE_RE.findall(entry))
        if triggered[detector] and (conclusion not in {"已复用", "已登记"} or not triggered[detector].issubset(summary_ids)):
            errors.append(f"{detector}逐项检测已触发，汇总不得漏记或写未触发")
        if conclusion in {"已复用", "已登记"} and not summary_ids:
            errors.append(f"{detector}汇总已触发但缺少事项编号")
        if conclusion == "自动修复并留痕" and not fixed:
            errors.append("ANM汇总自动修复缺少逐项修复依据")
        for item in summary_ids:
            error, _closed = _issue_error(project, item)
            if error:
                errors.append(error)
    # A governance reference in retrieval or outline coverage cannot be lost in
    # a later all-clear summary.  This only acts on explicit recorded signals.
    retrieval = task / "15_检索与知识准备记录.md"
    recorded = retrieval.read_text(encoding="utf-8-sig") if retrieval.is_file() else ""
    coverage = table_rows(text, "## 大纲知识覆盖检查")
    recorded += "\n" + "\n".join(" ".join(row) for row in coverage)
    all_summary_ids = {item for row in summaries.values() for item in ISSUE_RE.findall(row[3])}
    for item in set(ISSUE_RE.findall(recorded)):
        error, closed = _issue_error(project, item)
        if error:
            errors.append(error)
        if not closed and item not in all_summary_ids:
            errors.append(f"15或覆盖表已有{item}，20检测汇总遗漏开放事项")
    return list(dict.fromkeys(errors))


def pending_details() -> str:
    """Recovery may restore structure, but cannot manufacture a review result."""
    lines = [DETAIL_HEADING, "", "| " + " | ".join(DETAIL_HEADER) + " |", "|" + "---|" * len(DETAIL_HEADER)]
    for detector, categories in CATEGORIES.items():
        for category in categories:
            lines.append(f"| {detector} | {category} | 待核对当前需求与来源 | [[15_检索与知识准备记录.md]] | 待核对原文 | 待核对 | 自动恢复没有执行事实判断 | 无 | 等待知识库继续检测 |")
    return "\n".join(lines) + "\n"


def verified_self_test_details() -> str:
    """Evidence-backed no-trigger fixture used by executable self-tests."""
    lines = [DETAIL_HEADING, "", "| " + " | ".join(DETAIL_HEADER) + " |", "|" + "---|" * len(DETAIL_HEADER)]
    for detector, categories in CATEGORIES.items():
        for category in categories:
            lines.append(
                f"| {detector} | {category} | 本篇不涉及{category}客户事实或异常信号 | "
                "[[15_检索与知识准备记录.md#固定检索层状态]] | 已检索并命中 | 不适用 | "
                f"当前范围不涉及{category} | 无 | 不涉及本篇 |"
            )
    return "\n".join(lines) + "\n"
