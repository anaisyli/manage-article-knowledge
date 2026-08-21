#!/usr/bin/env python3
"""Audit and atomically advance the project Skill feedback ledger."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import date
from pathlib import Path


LEDGER_RELATIVE = Path("05_数据与审核/30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md")
STAGES = (
    "自动记录，待维护判断",
    "人工提出，待维护判断",
    "已纳入维护",
    "维护中",
    "已修复，待项目验证",
    "已关闭",
    "转为项目问题",
    "不纳入Skill",
)
TERMINAL = {"已关闭", "转为项目问题", "不纳入Skill"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def feedback_rows(text: str) -> list[dict[str, object]]:
    section = re.search(r"(?ms)^## 当前反馈\s*$\n(.*?)(?=^##\s|\Z)", text)
    if not section:
        raise ValueError("Skill反馈台账缺少“当前反馈”小节")
    lines = section.group(1).splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.strip().startswith("| SKFB ID")), None)
    if header_index is None or header_index + 1 >= len(lines):
        raise ValueError("Skill反馈台账缺少标准主表")
    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    rows: list[dict[str, object]] = []
    for offset, line in enumerate(lines[header_index + 2 :], start=header_index + 2):
        stripped = line.strip()
        if not stripped.startswith("|"):
            if stripped:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) == len(header):
            rows.append({"line": offset, "cells": cells, "data": dict(zip(header, cells))})
    return rows


def detail_block(text: str, item_id: str) -> tuple[int, int, str]:
    match = re.search(rf"(?ms)^###\s+{re.escape(item_id)}｜.*?(?=^###\s+[^\n]+｜|\Z)", text)
    if not match:
        raise ValueError(f"SKFB主表事项缺少详情：{item_id}")
    return match.start(), match.end(), match.group(0)


def audit(path: Path) -> list[dict[str, object]]:
    text = read_text(path)
    result: list[dict[str, object]] = []
    for row in feedback_rows(text):
        data = row["data"]
        item_id = str(data.get("SKFB ID", ""))
        _, _, detail = detail_block(text, item_id)
        detail_stage = re.search(r"(?m)^- 当前阶段[：:]\s*(.+?)\s*$", detail)
        result.append({
            "id": item_id,
            "summary": data.get("通俗说明", ""),
            "table_stage": data.get("当前阶段", ""),
            "detail_stage": detail_stage.group(1).strip() if detail_stage else None,
            "stage_consistent": bool(detail_stage and detail_stage.group(1).strip() == data.get("当前阶段", "")),
            "has_close_condition": "关闭条件" in detail,
            "open": data.get("当前阶段", "") not in TERMINAL,
        })
    return result


def replace_detail_field(block: str, label: str, value: str) -> str:
    pattern = rf"(?m)^- {re.escape(label)}[：:].*?$"
    replacement = f"- {label}：{value}"
    if re.search(pattern, block):
        return re.sub(pattern, replacement, block, count=1)
    marker = "#### 先看结论"
    if marker in block:
        return block.replace(marker, marker + "\n\n" + replacement, 1)
    return block.rstrip() + "\n\n" + replacement + "\n"


def transition(
    path: Path,
    item_id: str,
    target_stage: str,
    evidence: str,
    next_owner: str,
    skill_test: str | None,
    project_validation: str | None,
    updated: str,
) -> None:
    if target_stage not in STAGES:
        raise ValueError(f"不支持的SKFB阶段：{target_stage}")
    if target_stage == "已关闭":
        if not skill_test or "通过" not in skill_test:
            raise ValueError("关闭SKFB必须提供含“通过”的Skill专项自测结果")
        if not project_validation or "通过" not in project_validation:
            raise ValueError("关闭SKFB必须提供含“通过”的项目验证结果")
    text = read_text(path)
    section_match = re.search(r"(?ms)^## 当前反馈\s*$\n(.*?)(?=^##\s|\Z)", text)
    if not section_match:
        raise ValueError("Skill反馈台账缺少“当前反馈”小节")
    section = section_match.group(1)
    lines = section.splitlines()
    header_index = next(index for index, line in enumerate(lines) if line.strip().startswith("| SKFB ID"))
    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    try:
        stage_index = header.index("当前阶段")
        updated_index = header.index("最近更新")
    except ValueError as exc:
        raise ValueError("Skill反馈主表缺少当前阶段或最近更新列") from exc
    found = False
    for index in range(header_index + 2, len(lines)):
        stripped = lines[index].strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) == len(header) and cells[0] == item_id:
            cells[stage_index] = target_stage
            cells[updated_index] = updated
            lines[index] = "| " + " | ".join(cells) + " |"
            found = True
            break
    if not found:
        raise ValueError(f"Skill反馈主表中不存在：{item_id}")
    new_section = "\n".join(lines).rstrip() + "\n\n"
    text = text[: section_match.start(1)] + new_section + text[section_match.end(1) :]
    start, end, block = detail_block(text, item_id)
    block = replace_detail_field(block, "当前阶段", target_stage)
    block = replace_detail_field(block, "下一步由谁做", next_owner)
    verification = [
        "#### 自动状态检查",
        "",
        f"- 检查日期：{updated}",
        f"- 本次状态：{target_stage}",
        f"- 状态依据：{evidence}",
    ]
    if skill_test:
        verification.append(f"- Skill专项自测：{skill_test}")
    if project_validation:
        verification.append(f"- 项目验证：{project_validation}")
    verification.append("- 维护方式：本区块由状态工具追加；主表与详情已在同一事务同步。")
    block = block.rstrip() + "\n\n" + "\n".join(verification) + "\n"
    text = text[:start] + block + text[end:]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v05-skfb-test-") as temp:
        path = Path(temp) / "01_Skill反馈台账.md"
        path.write_text(
            "# Skill反馈台账\n\n## 当前反馈\n\n"
            "| SKFB ID | 提出来源 | 类型 | 通俗说明 | 复现依据 | 当前阶段 | 维护负责人 | 关联项目对象入口 | 最近更新 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| DEMO-SKFB-001 | 自动 | 工具兼容 | 深层路径失败 | 复现 | 已修复，待项目验证 | 负责人 | [[文件]] | 2026-08-21 |\n\n"
            "## 反馈详情\n\n### DEMO-SKFB-001｜深层路径失败\n\n#### 先看结论\n\n"
            "- 当前阶段：已修复，待项目验证\n- 下一步由谁做：Codex\n- 关闭条件：自测和项目验证通过\n",
            encoding="utf-8",
        )
        transition(path, "DEMO-SKFB-001", "已关闭", "原问题不再复现", "无", "通过", "通过", "2026-08-21")
        result = audit(path)
        current = read_text(path)
        if len(result) != 1 or result[0]["table_stage"] != "已关闭" or not result[0]["stage_consistent"] or "| 2026-08-21 |## 反馈详情" in current:
            print(json.dumps({"ok": False}, ensure_ascii=False))
            return 1
        before = read_text(path)
        try:
            transition(path, "DEMO-SKFB-001", "已关闭", "缺少验证", "无", None, None, "2026-08-21")
        except ValueError:
            pass
        else:
            print(json.dumps({"ok": False, "stage": "close-gate"}, ensure_ascii=False))
            return 1
        if read_text(path) != before:
            print(json.dumps({"ok": False, "stage": "atomicity"}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--item-id")
    parser.add_argument("--set-stage", choices=STAGES)
    parser.add_argument("--evidence")
    parser.add_argument("--next-owner", default="Skill维护负责人")
    parser.add_argument("--skill-test")
    parser.add_argument("--project-validation")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(run_self_test())
    if not args.project:
        raise SystemExit("--project is required")
    path = args.project.resolve() / LEDGER_RELATIVE
    if not path.is_file():
        raise SystemExit(f"Skill feedback ledger not found: {path}")
    if args.audit:
        print(json.dumps(audit(path), ensure_ascii=False, indent=2))
        return
    if not args.item_id or not args.set_stage or not args.evidence:
        raise SystemExit("transition requires --item-id, --set-stage and --evidence")
    transition(path, args.item_id, args.set_stage, args.evidence, args.next_owner, args.skill_test, args.project_validation, args.date)
    print(json.dumps({"ok": True, "item_id": args.item_id, "stage": args.set_stage}, ensure_ascii=False))


if __name__ == "__main__":
    main()
