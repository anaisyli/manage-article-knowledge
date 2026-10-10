#!/usr/bin/env python3
"""Single article entry point for an original-outline knowledge refresh.

This command is deliberately a gate and continuation receipt, not a content
generator.  It prevents ad-hoc scripts from promoting a copied v1 package:
the current task must be ``outline_refresh``, its sidecar must identify this
entry point, and every current 15/20/30/35 file must carry the same refresh
run id before the normal delivery gate can proceed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from article_state import parse_field, article_package_errors
from template_contract import validate_task_templates
from writing_bridge import locate_task, read_text


ENTRY = "run_outline_refresh.py"


def continuation_result(result: dict[str, object]) -> dict[str, object]:
    return {
        "terminal": False,
        "next_owner": "manage-article-knowledge",
        "resume_condition": "本轮知识包通过校验后重新运行门禁",
        "next_action": "修复任务身份或逐文件重建本轮知识包后重跑本入口",
        **result,
    }


def check_task(task: Path) -> dict[str, object]:
    request_path = task / "10_文章知识需求.md"
    if not request_path.is_file():
        return continuation_result({"ok": False, "state": "task_initialization", "errors": [f"缺少10：{request_path}"]})
    request = read_text(request_path)
    mode = parse_field(request, "任务模式")
    if mode != "outline_refresh":
        return continuation_result({
            "ok": False,
            "state": "identity_error",
            "errors": [f"当前任务不是outline_refresh，而是{mode or '空'}；不得用此入口处理new_article或knowledge_reuse_rewrite"],
        })
    sidecar = task / "知识重整运行.json"
    errors: list[str] = []
    run: dict[str, object] = {}
    if not sidecar.is_file():
        errors.append("缺少知识重整运行.json；不得从旧版本复制知识包")
    else:
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8-sig"))
            if not isinstance(loaded, dict):
                raise ValueError("必须是JSON对象")
            run = loaded
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"知识重整运行.json无法读取：{exc}")
    run_id = str(run.get("refresh_run_id", "")).strip()
    if not run_id:
        errors.append("知识重整运行.json缺少refresh_run_id")
    if str(run.get("workflow_entry", "")).strip() != ENTRY:
        errors.append(f"本轮必须由{ENTRY}接续，当前workflow_entry不匹配")
    if str(run.get("article_id", "")).strip() != parse_field(request, "文章ID"):
        errors.append("知识重整运行.json的article_id与10不一致")
    if str(run.get("article_version", "")).strip() != parse_field(request, "当前版本"):
        errors.append("知识重整运行.json的article_version与10不一致")
    if str(run.get("status", "")).strip() in {"copied_from_baseline", "reused_old_package"}:
        errors.append("本轮标记为旧包复制/复用，必须从当前大纲和本轮来源重建")
    files = ("15_检索与知识准备记录.md", "20_文章前知识审核.md", "30_本篇知识库资料.md", "35_写作素材来源索引.md")
    present = [name for name in files if (task / name).is_file()]
    if run_id:
        for name in present:
            text = read_text(task / name)
            recorded = parse_field(text, "本轮知识重整运行ID") or parse_field(text, "本轮运行ID")
            if recorded != run_id:
                errors.append(f"{name}未绑定本轮运行ID：{run_id}")
    errors.extend(validate_task_templates(task))
    if len(present) == len(files) and not errors:
        errors.extend(article_package_errors(task))
    return continuation_result({
        "ok": not errors and len(present) == len(files),
        "state": "writing_ready_candidate" if not errors and len(present) == len(files) else "knowledge_repair_required",
        "task": str(task),
        "refresh_run_id": run_id,
        "present": present,
        "errors": list(dict.fromkeys(errors)),
        "next_action": "运行issue_writing_ready.py" if not errors and len(present) == len(files) else "只使用本轮来源逐文件重建缺失或不合格文件；每生成一个文件立即重新运行本入口",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--article-id", required=True)
    try:
        args = parser.parse_args()
        task = locate_task(args.project.resolve(), args.article_id, "")
        result = check_task(task)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        result = continuation_result({"ok": False, "state": "invocation_error", "errors": ["必须提供有效的--project和--article-id"]})
    except (OSError, ValueError, RuntimeError) as exc:
        result = continuation_result({"ok": False, "state": "task_initialization", "errors": [str(exc)]})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
