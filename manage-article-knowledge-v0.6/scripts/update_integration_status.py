#!/usr/bin/env python3
"""Refresh the dynamic status summary in 01_工作台/40_写作与Faithfulness接入配置.md.

The configuration file remains the single current integration entry. This
helper only changes runtime summary fields; paths, mapping rules and human
confirmation text are never inferred from an event.
"""

from __future__ import annotations

import argparse
import re
import tempfile
from datetime import datetime
from pathlib import Path


CONFIG_RELATIVE = Path("01_工作台/40_写作与Faithfulness接入配置.md")
SUMMARY_HEADING = "## 自动状态摘要"
SUMMARY_HEADING_RE = re.compile(r"^##\s+(?:(?:六、)?)自动状态摘要\s*$", re.MULTILINE)
SUMMARY_FIELDS = (
    "最近检查时间",
    "最近成功读取",
    "最近成功接收",
    "最近成功导入",
    "月度审核触发器",
    "最近一次接入事件",
    "最近一次异常",
)
EVENTS = {
    "check": "接入检查",
    "writing_task_success": "成功读取写作任务",
    "writing_task_failure": "读取写作任务失败",
    "final_received_success": "成功接收终稿",
    "final_received_failure": "接收终稿失败",
    "faithfulness_import_success": "成功导入Faithfulness结果",
    "faithfulness_import_failure": "导入Faithfulness结果失败",
    "monthly_automation_configured": "月度自动化已配置",
    "monthly_review_success": "月度审核完成",
    "monthly_review_failure": "月度审核失败",
    "interface_reconfirmed": "接入接口重新确认",
}


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码接入配置：{path}")


def field(text: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$",
        text,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def _replace_field(text: str, label: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"^(\s*[-*]\s*{re.escape(label)}[：:]\s*).*?$",
        re.MULTILINE,
    )
    replacement = rf"\g<1>{value}"
    updated, count = pattern.subn(replacement, text, count=1)
    return updated, bool(count)


def _summary_slice(text: str) -> tuple[int, int] | None:
    heading = SUMMARY_HEADING_RE.search(text)
    if not heading:
        return None
    next_heading = re.search(r"^##\s+", text[heading.end():], re.MULTILINE)
    end = heading.end() + next_heading.start() if next_heading else len(text)
    return heading.end(), end


def _append_summary_fields(text: str) -> str:
    """Ensure the summary section exists and contains every dynamic field.

    Field lookup is deliberately limited to this section: older templates also
    contain similarly named descriptive fields elsewhere in the file.
    """
    bounds = _summary_slice(text)
    if bounds is None:
        block = [SUMMARY_HEADING, ""]
        block.extend(f"- {label}：无" for label in SUMMARY_FIELDS)
        suffix = "\n" if text.endswith("\n") else "\n\n"
        return text + suffix + "\n".join(block) + "\n"
    start, end = bounds
    section = text[start:end]
    missing = [label for label in SUMMARY_FIELDS if not re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]", section, re.MULTILINE
    )]
    if not missing:
        return text
    addition = "\n".join(f"- {label}：无" for label in missing) + "\n"
    insertion = end
    prefix = text[:insertion]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + addition + text[insertion:]


def _replace_summary_field(text: str, label: str, value: str) -> tuple[str, bool]:
    bounds = _summary_slice(text)
    if bounds is None:
        return text, False
    start, end = bounds
    section = text[start:end]
    updated, found = _replace_field(section, label, value)
    if not found:
        return text, False
    return text[:start] + updated + text[end:], True


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _event_context(
    external_task_key: str,
    article_id: str,
    article_version: str,
    detail: str,
) -> str:
    values: list[str] = []
    if external_task_key:
        values.append(f"任务键：{external_task_key.strip()}")
    if article_id:
        values.append(f"文章ID：{article_id.strip()}")
    if article_version:
        values.append(f"版本：{article_version.strip()}")
    if detail:
        values.append(detail.strip().replace("\n", " "))
    return "；".join(values)


def _infer_state(text: str) -> str:
    """Return a conservative state after a successful recheck.

    A missing sample keeps the project at 部分接入; it is never promoted to
    已确认 merely because the three paths exist.
    """
    aliases = {
        "task_path": ("写作任务入口路径", "写作任务路径"),
        "final_path": ("终稿入口路径", "终稿路径"),
    }
    values = {
        "task_path": next((field(text, label) for label in aliases["task_path"] if field(text, label)), ""),
        "final_path": next((field(text, label) for label in aliases["final_path"] if field(text, label)), ""),
        "faithfulness_root": field(text, "Faithfulness结果根目录"),
        "task_key": field(text, "外部任务唯一键规则"),
        "task_status": field(text, "可接收状态规则"),
        "task_mapping": field(text, "任务字段映射"),
        "final_match": field(text, "终稿识别规则"),
        "identity": field(text, "文章身份回传规则"),
    }
    placeholders = {"", "待确认", "待扫描", "未接入", "无"}
    usable = lambda value: value not in placeholders and not value.startswith("待确认")
    paths: list[Path] = []
    for key in ("task_path", "final_path", "faithfulness_root"):
        value = values[key]
        if not usable(value):
            continue
        try:
            paths.append(Path(value).expanduser())
        except (TypeError, ValueError, OSError):
            return "部分接入"
    if not paths:
        return "待写作流程建立"
    if all(usable(value) for value in values.values()) and all(path.exists() for path in paths):
        try:
            task_path = Path(values["task_path"]).expanduser()
            has_sample = task_path.is_file() or (
                task_path.is_dir() and any(task_path.iterdir())
            )
        except (TypeError, ValueError, OSError):
            has_sample = False
        if has_sample:
            return "已确认"
    return "部分接入"


def update(
    project: Path,
    event: str,
    *,
    article_id: str = "",
    article_version: str = "",
    external_task_key: str = "",
    detail: str = "",
    trigger: str = "",
    error: str = "",
    at: str | None = None,
) -> dict[str, str | bool]:
    config = project.resolve() / CONFIG_RELATIVE
    if not config.is_file():
        return {"updated": False, "reason": f"缺少接入配置：{config}"}
    if event not in EVENTS:
        raise ValueError(f"未知接入事件：{event}")
    timestamp = at or datetime.now().astimezone().isoformat(timespec="seconds")
    text = _append_summary_fields(read_text(config))
    context = _event_context(external_task_key, article_id, article_version, detail)
    event_value = f"{timestamp}｜{EVENTS[event]}"
    if context:
        event_value += f"｜{context}"
    changed = False
    for label, value in (("最近检查时间", timestamp), ("最近一次接入事件", event_value)):
        text, found = _replace_summary_field(text, label, value)
        changed = changed or found
    success_field = {
        "writing_task_success": "最近成功读取",
        "final_received_success": "最近成功接收",
        "faithfulness_import_success": "最近成功导入",
    }.get(event)
    if success_field:
        text, found = _replace_summary_field(text, success_field, event_value)
        changed = changed or found
    if event.endswith("_failure"):
        error_value = f"{timestamp}｜{EVENTS[event]}"
        if error:
            error_value += f"｜{error.strip().replace(chr(10), ' ')}"
        if context:
            error_value += f"｜{context}"
        text, found = _replace_summary_field(text, "最近一次异常", error_value)
        changed = changed or found
        text, found = _replace_field(text, "接入状态", "异常，待重新确认")
        changed = changed or found
    if event == "monthly_automation_configured":
        trigger_value = trigger.strip() or f"Codex总控自动化（配置时间：{timestamp}）"
        text, found = _replace_summary_field(text, "月度审核触发器", trigger_value)
        changed = changed or found
    if event == "interface_reconfirmed":
        text, found = _replace_field(text, "接入状态", _infer_state(text))
        changed = changed or found
    if changed:
        _write_atomic(config, text)
    return {"updated": changed, "config": str(config), "event": event, "timestamp": timestamp}


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp)
        config = project / CONFIG_RELATIVE
        config.parent.mkdir(parents=True)
        config.write_text(
            "# 写作与Faithfulness接入配置\n\n"
            "- 接入状态：部分接入\n"
            "- 最近检查时间：待检查\n"
            "- 最近成功读取：顶层说明（不应被摘要更新覆盖）\n"
            "\n## 自动状态摘要\n\n"
            "- 最近成功读取：无\n"
            "- 最近成功接收：无\n"
            "- 最近成功导入：无\n"
            "- 月度审核触发器：待配置\n",
            encoding="utf-8",
        )
        result = update(project, "writing_task_success", article_id="A-1", at="2026-09-03T10:00:00+08:00")
        content = read_text(config)
        if (
            not result["updated"]
            or "2026-09-03T10:00:00+08:00" not in content
            or "最近成功读取：顶层说明（不应被摘要更新覆盖）" not in content
        ):
            raise SystemExit("self-test failed: success event")
        update(project, "monthly_automation_configured", trigger="Codex总控自动化", at="2026-09-03T10:01:00+08:00")
        content = read_text(config)
        if "月度审核触发器：Codex总控自动化" not in content:
            raise SystemExit("self-test failed: trigger event")
        update(project, "faithfulness_import_failure", error="哈希不匹配", at="2026-09-03T10:02:00+08:00")
        content = read_text(config)
        if "接入状态：异常，待重新确认" not in content or "哈希不匹配" not in content:
            raise SystemExit("self-test failed: failure event")
    print("self-test=passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--event", choices=sorted(EVENTS))
    parser.add_argument("--article-id", default="")
    parser.add_argument("--article-version", default="")
    parser.add_argument("--external-task-key", default="")
    parser.add_argument("--detail", default="")
    parser.add_argument("--trigger", default="")
    parser.add_argument("--error", default="")
    parser.add_argument("--at", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.project or not args.event:
        raise SystemExit("请提供 --project 和 --event，或使用 --self-test")
    print(update(
        args.project,
        args.event,
        article_id=args.article_id,
        article_version=args.article_version,
        external_task_key=args.external_task_key,
        detail=args.detail,
        trigger=args.trigger,
        error=args.error,
        at=args.at or None,
    ))


if __name__ == "__main__":
    main()
