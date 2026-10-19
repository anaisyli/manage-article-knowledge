"""Write the two stage-specific project handoff reviews."""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path


REVIEW_RELATIVE = Path("05_数据与审核/40_月度与交接")
METRICS_RELATIVE = Path("05_数据与审核/10_Faithfulness/10_文章Faithfulness明细.csv")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else ""


def field(text: str, label: str) -> str:
    match = re.search(rf"(?m)^-\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text)
    return match.group(1).strip() if match else ""


def project_value(project: Path, label: str) -> str:
    for relative in (
        Path("01_工作台/10_项目基础信息.md"),
        Path("01_工作台/40_写作与Faithfulness接入配置.md"),
    ):
        value = field(read_text(project / relative), label)
        if value:
            return value
    return "未登记"


def integer_or_none(row: dict[str, str], field_name: str) -> int | None:
    value = row.get(field_name, "").strip()
    try:
        return int(value) if value else None
    except ValueError:
        return None


def total_or_na(rows: list[dict[str, str]], field_name: str) -> str:
    values = [integer_or_none(row, field_name) for row in rows]
    if any(value is None for value in values):
        return "N/A（包含旧协议未记录）"
    return str(sum(value for value in values if value is not None))


def faithfulness_handoff_lines(project: Path) -> list[str]:
    metrics_path = project / METRICS_RELATIVE
    if metrics_path.is_file():
        with metrics_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    else:
        rows = []
    current = [row for row in rows if row.get("status") == "current"]
    waiting_root = project / "04_文章任务/30_等待Faithfulness"
    waiting_count = sum(path.is_dir() for path in waiting_root.iterdir()) if waiting_root.is_dir() else 0
    record_paths = (project / "04_文章任务").rglob("50_文章知识使用与Faithfulness记录.md") if (project / "04_文章任务").is_dir() else []
    recheck_count = sum(
        "等待重审" in field(read_text(path), "当前状态")
        for path in record_paths
        if "90_归档" not in path.parts
    )
    supported_total = sum(integer_or_none(row, "supported_claims") or 0 for row in current)
    monthly_files = sorted(
        path for path in (project / REVIEW_RELATIVE).glob("*.md")
        if "项目交接审核" not in path.name
    ) if (project / REVIEW_RELATIVE).is_dir() else []
    latest_monthly = "N/A（尚无月度结果）"
    for path in reversed(monthly_files):
        match = re.search(r"(?m)^-\s*月平均知识附件明确支撑率[：:]\s*(.+?)\s*$", read_text(path))
        if match:
            latest_monthly = match.group(1).strip()
            break
    return [
        f"- 当前有效结果数：{len(current)}",
        f"- 等待结果数：{waiting_count}",
        f"- 待重审数：{recheck_count}",
        f"- 当前有效结果中的明确支持主张总数：{supported_total}",
        f"- 当前有效结果中的尚未确认主张总数：{total_or_na(current, 'unknown_claims')}",
        f"- 当前有效结果中的明确冲突主张总数：{total_or_na(current, 'contradicted_claims')}",
        f"- 最近月度知识附件明确支撑率：{latest_monthly}",
        "- 指标说明：没有目标值，不判定文章质量、发布资格或是否需要重写；后续只依据具体黄色/红色主张的语义归组。",
        f"- 机器明细入口：`{metrics_path}`",
    ]


def write_review(
    project: Path,
    *,
    stage: str,
    project_id: str,
    enterprise_name: str,
    original_owner: str,
    new_owner: str,
    package_path: str,
    issues: list[str],
) -> Path:
    is_delivery = stage == "交付前"
    title = f"{stage}项目交接审核"
    filename = f"{date.today().isoformat()}_{title}.md"
    destination = project / REVIEW_RELATIVE / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    conclusion = "补充后交接" if issues else "可以交接"
    issue_text = "；".join(issues) if issues else "无"
    lines = [
        f"# {title}",
        "",
        f"- 项目ID：{project_id}",
        f"- 企业名称：{enterprise_name}",
        f"- 交接阶段：{stage}",
        f"- 原负责人：{original_owner or '未登记'}",
        f"- 新负责人：{new_owner or '待接收方确认'}",
        f"- 交接日期：{date.today().isoformat()}",
        f"- 交接包：{package_path or '未登记'}",
        f"- 结论：{conclusion}",
        "",
        "## 路径与入口",
        "",
        "| 项目 | 当前值 | 已验证 | 问题 |",
        "|---|---|---|---|",
        f"| 客户官网 | {project_value(project, '官网')} | {'交付前读取' if is_delivery else '接收后复核'} | 无 |",
        f"| 项目根目录 | `{project_value(project, '项目根目录')}` | {'已读取' if is_delivery else '已迁移后读取'} | 无 |",
        f"| 客户原始资料路径 | `{project_value(project, '客户原始资料路径')}` | {'已读取' if is_delivery else '已迁移后读取'} | 无 |",
        f"| Obsidian项目路径 | `{project}` | {'已打包' if is_delivery else '已复核'} | 无 |",
        f"| 写作任务入口 | `{project_value(project, '写作任务入口路径')}` | 配置已读取 | 首个真实样例仍按配置复核 |",
        f"| 终稿入口 | `{project_value(project, '终稿入口路径')}` | 配置已读取 | 首个真实样例仍按配置复核 |",
        f"| Faithfulness结果入口 | `{project_value(project, 'Faithfulness结果根目录')}` | 配置已读取 | 结果目录和历史结果以交接包/新环境核对为准 |",
        "",
        "## 包与迁移核对",
        "",
        f"- 本阶段：{('已制作交接包，等待接收方预演和确认迁移' if is_delivery else '已执行迁移后的目标路径、重复文件和冲突复核')}",
        f"- 本阶段发现：{issue_text}",
        "- 校验入口：[[../../../01_工作台/10_项目基础信息.md]]、[[../../../01_工作台/40_写作与Faithfulness接入配置.md]]、[[../../50_运行记录/项目运行账本.jsonl]]。",
        "",
        "## 进行中任务",
        "",
        "- 按当前文章任务目录、当前待办和处理单核对；未决任务及恢复条件不得因交接关闭。",
        "",
        "## Faithfulness交接",
        "",
        *faithfulness_handoff_lines(project),
        "",
        "## 未解决事项",
        "",
        "### CUS",
        "",
        "- 以[[../../30_异常与待决定/10_待客户补充/01_待客户补充事项.md]]当前开放事项为准。",
        "",
        "### ANM",
        "",
        "- 以[[../../30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md]]当前开放事项为准。",
        "",
        "### MAT",
        "",
        "- 以[[../../30_异常与待决定/20_源资料处理/01_源资料处理台账.md]]当前开放事项为准。",
        "",
        "### SKFB",
        "",
        "- 以[[../../30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md]]当前开放事项为准。",
        "",
        "## 交接结论",
        "",
        f"- 结论：{conclusion}",
        f"- 需要处理：{issue_text}",
        f"- 下一步：{('接收方完成预演并由人工确认后迁移；接收后审核必须在verify完成后生成。' if is_delivery else '新负责人根据当前未解决事项继续运营；交付方原文件不由本流程删除。')}",
    ]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
