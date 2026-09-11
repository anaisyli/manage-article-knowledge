#!/usr/bin/env python3
"""Create confirmed project skeletons and configure their external interfaces.

The discovery report is deliberately read-only.  This command is the write step
and therefore requires an explicit batch authorization flag.  It never moves or
overwrites an external writing or final-draft file. A successful result is not a
completed initialization: Codex must continue with website profiling, source
indexing, coverage rebuilding, and project validation in the same run.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


CONFIG_RELATIVE = Path("01_工作台/40_写作与Faithfulness接入配置.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--confirm-batch",
        action="store_true",
        help="Authorize initialization and creation of missing external entry directories.",
    )
    parser.add_argument("--final-choice", action="append", default=[], metavar="P-001=PATH")
    parser.add_argument("--set", action="append", default=[], metavar="P-001:FIELD=VALUE")
    parser.add_argument("--skip-project", action="append", default=[], metavar="P-001")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_report(path: Path) -> dict[str, object]:
    report = json.loads(path.resolve().read_text(encoding="utf-8-sig"))
    if report.get("report_type") != "manage-article-knowledge-workspace-discovery":
        raise SystemExit("不是可用于批量建库的工作区盘点报告")
    if report.get("read_only") is not True:
        raise SystemExit("工作区盘点报告必须标记 read_only=true")
    if not isinstance(report.get("projects"), list):
        raise SystemExit("盘点报告缺少 projects 列表")
    return report


def parse_pairs(values: list[str], separator: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if separator not in value:
            raise SystemExit(f"参数格式无效：{value}")
        key, raw = value.split(separator, 1)
        key, raw = key.strip(), raw.strip()
        if not key or not raw:
            raise SystemExit(f"参数不能为空：{value}")
        result[key] = raw
    return result


def parse_overrides(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for value in values:
        if ":" not in value or "=" not in value:
            raise SystemExit(f"参数格式无效：{value}（应为 P-001:field=value）")
        project_id, remainder = value.split(":", 1)
        field, raw = remainder.split("=", 1)
        project_id, field, raw = project_id.strip(), field.strip(), raw.strip()
        if not project_id or not field or not raw:
            raise SystemExit(f"参数不能为空：{value}")
        result.setdefault(project_id, {})[field] = raw
    return result


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "-", value).strip(" .")
    return value or "未命名项目"


def resolve_existing_obsidian_project(obsidian_root: Path, candidate_id: str, project_name: str) -> tuple[Path, str | None]:
    """Resolve the standard path while preserving a historical v0.6 path."""
    stem = f"{candidate_id}_{project_name}知识库"
    standard = obsidian_root / stem
    legacy = obsidian_root / f"{stem}_v0.6"
    existing = [path for path in (standard, legacy) if path.is_dir()]
    if len(existing) > 1:
        return standard, f"同时发现新旧知识库目录，无法安全选择：{standard}；{legacy}"
    if existing:
        return existing[0], None
    return standard, None


def replace_field(text: str, label: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*[-*]\s*{re.escape(label)}[：:]\s*).*$", re.MULTILINE)
    text, count = pattern.subn(lambda match: match.group(1) + value, text, count=1)
    if count != 1:
        raise ValueError(f"接入配置缺少字段：{label}")
    return text


def replace_confirmation_rows(text: str, task: str, final: str, faithfulness: str, timestamp: str) -> str:
    replacements = {
        "写作任务": (task, "已自动登记" if task else "未接入"),
        "终稿": (final, "已自动登记" if final else "待人工选择"),
        "Faithfulness结果": (faithfulness, "已自动登记"),
    }
    lines = text.splitlines()
    for index, line in enumerate(lines):
        for interface, (confirmed, status) in replacements.items():
            if line.startswith(f"| {interface} |"):
                lines[index] = (
                    f"| {interface} | {confirmed or '无'} | {confirmed or '待确认'} | {status} | "
                    f"{timestamp} | 路径、命名、字段或合同变化 |")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def choose_final(project_id: str, candidates: list[str], choices: dict[str, str]) -> tuple[str | None, str | None]:
    if len(candidates) <= 1:
        return (candidates[0] if candidates else None), None
    selected = choices.get(project_id)
    if not selected:
        return None, "存在多个终稿候选，必须由人工选择"
    selected_path = Path(selected).expanduser().resolve()
    allowed = {str(Path(item).resolve()).casefold() for item in candidates}
    if str(selected_path).casefold() not in allowed:
        return None, f"终稿选择不在候选中：{selected_path}"
    return str(selected_path), None


def entry_path(assessment: dict[str, object], key: str) -> tuple[str | None, list[str]]:
    item = assessment.get(key) or {}
    if not isinstance(item, dict):
        return None, []
    value = str(item.get("value") or "")
    candidates = [item.strip() for item in value.split("；") if item.strip() and Path(item.strip()).exists()]
    return value or None, candidates


def initialize(project: dict[str, object], report: dict[str, object], overrides: dict[str, str], final_choices: dict[str, str], dry_run: bool) -> dict[str, object]:
    candidate_id = str(project["candidate_id"])
    assessment = project.get("field_assessment") or {}
    if not isinstance(assessment, dict):
        return {"project": candidate_id, "status": "跳过", "reason": "缺少字段评估"}

    website = overrides.get("website") or str((assessment.get("website") or {}).get("value") or "")
    source = overrides.get("source_path") or str((assessment.get("source_path") or {}).get("value") or "")
    source_status = str((assessment.get("source_path") or {}).get("status") or "")
    if website in {"", "未发现"}:
        return {"project": candidate_id, "status": "跳过", "reason": "官网仍需人工补充"}
    if not overrides.get("source_path") and source_status != "已确定":
        return {"project": candidate_id, "status": "跳过", "reason": "客户原始资料入口仍不唯一"}

    project_root = Path(str(project["candidate_path"])).resolve()
    project_name = safe_name(overrides.get("project_name") or str((assessment.get("project_name") or {}).get("value") or project_root.name))
    obsidian_root = Path(str(report["obsidian_root"])).resolve()
    obsidian_project, naming_error = resolve_existing_obsidian_project(obsidian_root, candidate_id, project_name)
    task_value, task_candidates = entry_path(assessment, "writing_task_entry")
    final_value, final_candidates = entry_path(assessment, "final_entry")
    default_task = Path(str(project.get("suggested_external_paths", {}).get("writing_task") or project_root / "写作任务")).resolve()
    default_final = Path(str(project.get("suggested_external_paths", {}).get("final") or project_root / "终稿")).resolve()
    task_path = Path(overrides.get("writing_task") or (task_candidates[0] if len(task_candidates) == 1 else default_task)).resolve()
    final_path, final_error = choose_final(candidate_id, final_candidates, final_choices)
    if overrides.get("final"):
        override_final = Path(overrides["final"]).expanduser().resolve()
        if final_candidates and str(override_final).casefold() not in {
            str(Path(item).resolve()).casefold() for item in final_candidates
        }:
            final_error = f"终稿选择不在候选中：{override_final}"
            final_path = None
        else:
            final_path = str(override_final)
            final_error = None
    if final_path is None and final_error is None:
        final_path = str(default_final)

    result: dict[str, object] = {"project": candidate_id, "status": "待处理", "obsidian_project": str(obsidian_project)}
    if naming_error:
        result.update({"status": "失败", "reason": naming_error})
        return result
    if obsidian_project.is_dir() and not dry_run:
        result.update({
            "status": "已存在，未重复初始化",
            "initialization_complete": False,
            "must_continue": True,
            "next_step": "existing_project_startup_check",
        })
        return result
    if final_error:
        result["final_status"] = "待人工选择"
        result["reason"] = final_error

    faithfulness_root = Path(str(report["faithfulness_root"])).resolve()
    if not dry_run:
        task_path.mkdir(parents=True, exist_ok=True)
        if final_path:
            Path(final_path).mkdir(parents=True, exist_ok=True)
        init_script = Path(__file__).with_name("initialize_project.py")
        command = [
            sys.executable, str(init_script), "--project", str(obsidian_project),
            "--project-name", project_name, "--workspace-project-root", str(project_root),
            "--source-root", source,
            "--website", website, "--content-owner", str(report["default_content_owner"]),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if completed.returncode:
            result.update({"status": "失败", "reason": completed.stderr.strip() or completed.stdout.strip()})
            return result
        config = obsidian_project / CONFIG_RELATIVE
        text = config.read_text(encoding="utf-8")
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        text = replace_field(text, "接入状态", "部分接入")
        text = replace_field(text, "写作任务入口路径", str(task_path))
        text = replace_field(text, "外部任务唯一键规则", "样例出现后按合同自动识别")
        text = replace_field(text, "可接收状态规则", "样例出现后按合同自动识别")
        text = replace_field(text, "任务字段映射", "样例出现后按合同自动识别标题、非空简要大纲和状态")
        text = replace_field(text, "终稿入口路径", final_path or "待人工选择")
        text = replace_field(text, "终稿识别规则", "按文章ID/版本、外部任务键或精确路径匹配；多候选待人工选择")
        text = replace_field(text, "Faithfulness结果根目录", str(faithfulness_root))
        text = replace_field(text, "首次确认日期", timestamp)
        text = replace_confirmation_rows(text, str(task_path), final_path, str(faithfulness_root), timestamp)
        config.write_text(text, encoding="utf-8")
    result["status"] = "骨架与接入已建立，初始化未完成" if not final_error else "骨架已建立，终稿待人工选择，初始化未完成"
    result["initialization_complete"] = False
    result["must_continue"] = True
    result["next_step"] = "website_profile_then_source_index_and_validation"
    result["website"] = website
    result["writing_task_entry"] = str(task_path)
    result["final_entry"] = final_path or "待人工选择"
    return result


def main() -> None:
    args = parse_args()
    if not args.confirm_batch and not args.dry_run:
        raise SystemExit("写入操作必须带 --confirm-batch；盘点报告本身不会授权建库")
    report = load_report(args.report)
    choices = parse_pairs(args.final_choice, "=")
    overrides = parse_overrides(args.set)
    skipped = {item.casefold() for item in args.skip_project}
    results: list[dict[str, object]] = []
    for project in report["projects"]:
        if not isinstance(project, dict):
            continue
        candidate_id = str(project.get("candidate_id") or "")
        if candidate_id.casefold() in skipped or project.get("initialization_batch") == "待处理":
            results.append({"project": candidate_id, "status": "待处理"})
            continue
        results.append(initialize(project, report, overrides.get(candidate_id, {}), choices, args.dry_run))
    print(json.dumps({"ok": True, "authorized": bool(args.confirm_batch), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
