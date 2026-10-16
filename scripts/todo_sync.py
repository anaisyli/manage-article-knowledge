"""Project-level current-todo helpers shared by maintenance scripts."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

INFO_RELATIVE = Path("01_工作台/10_项目基础信息.md")
TODO_RELATIVE = Path("01_工作台/20_当前待办.md")
SOURCE_DB_RELATIVE = Path("02_源资料/source-index.sqlite")
TODO_HEADER = "| 对象ID | 人能看懂的事项 | 当前阶段 | 是否阻塞 | 下一步由谁做 | 直达链接 | 更新/重开条件 | 最近更新 |"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _field(text: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _replace_field(text: str, label: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*[-*]\s*{re.escape(label)}[：:]\s*).*?$", re.MULTILINE)
    updated, count = pattern.subn(lambda match: match.group(1) + value, text, count=1)
    if count != 1:
        raise ValueError(f"当前待办缺少字段：{label}")
    return updated


def _table(text: str) -> tuple[list[str], int, int]:
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if line.strip() == TODO_HEADER), None)
    if header is None or header + 1 >= len(lines):
        raise ValueError("当前待办缺少标准八列表")
    end = header + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return lines, header, end


def _write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def upsert_todo_row(project: Path, *, object_id: str, human_text: str, stage: str,
                    blocked: str, owner: str, link: str, condition: str,
                    updated: str | None = None) -> Path:
    project = project.resolve()
    path = project / TODO_RELATIVE
    text = _read(path)
    lines, header, end = _table(text)
    stamp = (updated or datetime.now().astimezone().isoformat())[:10]
    row = "| " + " | ".join(value.replace("|", "\\|") for value in (object_id, human_text, stage, blocked, owner, link, condition, stamp)) + " |"
    found = next((i for i in range(header + 2, end) if lines[i].split("|", 2)[1].strip() == object_id), None)
    if found is None:
        lines.insert(end, row)
    else:
        lines[found] = row
    result = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    result = _replace_field(_replace_field(_replace_field(result, "更新日期", stamp), "当前节点", stage), "当前状态", human_text)
    _write(path, result)
    return path


def remove_todo_row(project: Path, *, object_id: str, updated: str | None = None) -> Path:
    """Close one action by removing its current row; preserve all other rows."""
    project = project.resolve()
    path = project / TODO_RELATIVE
    text = _read(path)
    lines, header, end = _table(text)
    stamp = (updated or datetime.now().astimezone().isoformat())[:10]
    data = [line for line in lines[header + 2:end] if line.split("|", 2)[1].strip() != object_id]
    if not data:
        data = [f"| 无 | 暂无开放事项 | 等待写作任务 | 否 | 等待新的写作任务或项目变化 | [[30_版本与变更入口.md]] | 新任务、来源或官网变化时重开 | {stamp} |"]
    lines[header + 2:end] = data
    cells = [item.strip() for item in data[0].strip().strip("|").split("|")]
    result = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    result = _replace_field(_replace_field(_replace_field(result, "更新日期", stamp), "当前节点", cells[2]), "当前状态", cells[1])
    _write(path, result)
    return path


def refresh_project_todo(
    project: Path,
    *,
    at: str | None = None,
    profile_complete: bool | None = None,
    local_complete: bool | None = None,
) -> Path:
    project = project.resolve()
    info = _read(project / INFO_RELATIVE)
    todo_path = project / TODO_RELATIVE
    text = _read(todo_path)
    project_id = _field(info, "项目ID") or project.name.split("_", 1)[0]
    if profile_complete is None:
        profile_complete = _field(info, "画像状态") == "已完成"
    if local_complete is None:
        local_complete = (project / SOURCE_DB_RELATIVE).is_file()
    if profile_complete and local_complete:
        node, status, action = "等待写作任务", "初始化、官网画像、来源索引和项目校验已完成", None
    elif profile_complete:
        node, status, action = "来源索引与项目校验", "官网画像已完成；继续建立来源台账、机器索引、覆盖视图并校验", "完成来源索引、覆盖视图和项目校验"
    elif local_complete:
        node, status, action = "官网画像待重试", "本地建库已完成；官网恢复时自动重试画像", "重试官网画像并同步项目基础信息"
    else:
        node, status, action = "来源索引与官网画像待重试", "官网暂时失败；继续本地来源索引，官网恢复时自动重试", "完成本地来源索引并在触发条件满足时重试官网画像"
    stamp = (at or datetime.now().astimezone().isoformat())[:10]
    lines, header, end = _table(text)
    data = [line for line in lines[header + 2:end] if line.strip() and not line.startswith(f"| {project_id} |") and not line.startswith("| 无 |")]
    if action:
        data.append(f"| {project_id} | {action} | {node} | 否 | Codex自动继续 | [[10_项目基础信息.md]] | 官网恢复、来源变化或项目启动时重开 | {stamp} |")
    if not data:
        data = [f"| 无 | 暂无开放事项 | {node} | 否 | 等待新的写作任务或项目变化 | [[30_版本与变更入口.md]] | 新任务、来源或官网变化时重开 | {stamp} |"]
    lines[header + 2:end] = data
    result = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    result = _replace_field(result, "更新日期", stamp)
    if not any(not line.startswith(f"| {project_id} |") and not line.startswith("| 无 |") for line in data):
        result = _replace_field(_replace_field(result, "当前节点", node), "当前状态", status)
    _write(todo_path, result)
    return todo_path
