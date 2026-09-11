"""Write the two stage-specific project handoff reviews."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path


REVIEW_RELATIVE = Path("05_数据与审核/40_月度与交接")


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
        "- 按当前有效结果、等待外部结果和正文变化后待重审记录核对；不得用其他项目结果替代。",
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
