#!/usr/bin/env python3
"""Group project validation output for human-readable monthly closure records."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass


STATES = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成")
FILES = ("10_文章知识需求.md", "15_检索与知识准备记录.md", "20_文章前知识审核.md", "30_本篇知识库资料.md", "35_写作素材来源索引.md", "40_最终文章.md", "50_文章知识使用与Faithfulness记录.md")


@dataclass(frozen=True)
class IssueGroup:
    state: str
    file_type: str
    root_cause: str
    count: int
    examples: tuple[str, ...]


def _state(error: str) -> str:
    return next((state for state in STATES if state in error), "项目级")


def _file_type(error: str) -> str:
    return next((name for name in FILES if name in error), "项目级")


def _root_cause(error: str) -> str:
    rules = (
        ("模板身份/字段兼容", ("固定字段", "固定章节", "固定表头", "大纲", "版本无效")),
        ("官网正文凭证或来源记录", ("官网正文", "抓取凭证", "来源命中", "来源ID")),
        ("文章级Claim与审核映射", ("Claim", "知识准备复核", "审核", "覆盖检查")),
        ("30/35证据映射", ("30/35", "映射", "证据正文")),
        ("正文或知识附件哈希", ("哈希", "SHA-256", "正文内容")),
    )
    for label, markers in rules:
        if any(marker in error for marker in markers):
            return label
    return "其他结构或生命周期校验"


def group_errors(errors: list[str]) -> list[IssueGroup]:
    buckets: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for error in errors:
        key = (_state(error), _file_type(error), _root_cause(error))
        buckets[key].append(error)
    return [
        IssueGroup(state, file_type, cause, len(items), tuple(items[:3]))
        for (state, file_type, cause), items in sorted(buckets.items())
    ]


def render_groups(groups: list[IssueGroup]) -> str:
    lines = ["### 本次校验错误归组", "", "| 任务状态 | 文件类型 | 根因 | 条数 |", "|---|---|---|---:|"]
    lines.extend(f"| {g.state} | {g.file_type} | {g.root_cause} | {g.count} |" for g in groups)
    lines.append("")
    lines.append("同一根因按任务状态、文件类型和根因合并；条数是校验触发次数，不等同于独立事实错误数。")
    return "\n".join(lines)


def report_requires_grouping(report_text: str) -> bool:
    return bool(re.search(r"项目校验.*?(?:错误|失败)|\d+项文章校验错误", report_text))


def validate_report_grouping(report_text: str) -> list[str]:
    if not report_requires_grouping(report_text):
        return []
    errors: list[str] = []
    if "本次校验错误归组" not in report_text:
        errors.append("月报校验失败时必须提供按任务状态、文件类型和根因的错误归组")
    else:
        required_headers = ("任务状态", "文件类型", "根因", "条数")
        if not all(header in report_text for header in required_headers):
            errors.append("月报错误归组表必须包含任务状态、文件类型、根因和条数")
        if "条数不是事实错误数" not in report_text and "不等同于独立事实错误数" not in report_text:
            errors.append("月报必须说明校验触发次数不等同于独立事实错误数")
    if "知识库维护清单" not in report_text and "KMR-" not in report_text:
        errors.append("月报校验失败时必须链接并同步知识库维护清单")
    return errors


if __name__ == "__main__":
    sample = ["40_已完成/ART/10_文章知识需求.md：缺少固定字段", "10_进行中/ART/15_检索与知识准备记录.md：官网正文核验缺少凭证"]
    print(render_groups(group_errors(sample)))
