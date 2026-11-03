#!/usr/bin/env python3
"""Record a verified website profile and reconcile initialization state.

This helper does not access the website. Codex supplies either a verified JSON
profile or a recoverable failure. The helper updates the project information,
current work queue, version entry, and run ledger as one logical transaction.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from record_project_run import append_record, make_record
from todo_sync import refresh_project_todo


INFO_RELATIVE = Path("01_工作台/10_项目基础信息.md")
TODO_RELATIVE = Path("01_工作台/20_当前待办.md")
VERSION_RELATIVE = Path("01_工作台/30_版本与变更入口.md")
SOURCE_DB_RELATIVE = Path("02_源资料/source-index.sqlite")
PROFILE_FIELDS = (
    "项目英文名称",
    "行业或业务类别",
    "主要业务与产品",
    "市场、服务区域与网站语言",
)
JUDGMENTS = {"官网明确", "根据官网推定", "官网不足"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def field(text: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text, re.MULTILINE
    )
    return match.group(1).strip() if match else ""


def replace_field(text: str, label: str, value: str) -> str:
    pattern = re.compile(
        rf"^(\s*[-*]\s*{re.escape(label)}[：:]\s*).*?$", re.MULTILINE
    )
    updated, count = pattern.subn(lambda match: match.group(1) + value, text, count=1)
    if count != 1:
        raise ValueError(f"控制文件缺少字段：{label}")
    return updated


def table_cell(value: object) -> str:
    return str(value or "").strip().replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def load_profile(path: Path) -> dict[str, object]:
    data = json.loads(path.resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
        raise ValueError("画像JSON必须包含 fields 对象")
    fields = data["fields"]
    for label in PROFILE_FIELDS:
        item = fields.get(label)
        if not isinstance(item, dict):
            raise ValueError(f"画像JSON缺少字段对象：{label}")
        for key in ("value", "source", "evidence", "judgment", "boundary"):
            if not str(item.get(key) or "").strip():
                raise ValueError(f"画像字段 {label} 缺少 {key}")
        if item["judgment"] not in JUDGMENTS:
            raise ValueError(f"画像字段 {label} 的 judgment 无效：{item['judgment']}")
    return data


def profile_date(profile: dict[str, object], at: str) -> str:
    value = str(profile.get("profiled_at") or at[:10]).strip()
    return value[:10]


def update_contact_row(text: str, status: str, next_action: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("| 项目基础信息 |"):
            cells = [item.strip() for item in line.strip().strip("|").split("|")]
            if len(cells) >= 7:
                cells[3] = status
                cells[4] = next_action
                lines[index] = "| " + " | ".join(cells[:7]) + " |"
            break
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def success_info(text: str, profile: dict[str, object], at: str) -> str:
    fields = profile["fields"]
    date = profile_date(profile, at)
    website_status = str(profile.get("website_status") or "可访问").strip()
    industry = fields["行业或业务类别"]
    judgment = str(industry["judgment"])
    method = {
        "官网明确": "官网明确",
        "根据官网推定": "Codex根据官网推定",
        "官网不足": "官网不足以判断",
    }[judgment]
    replacements = {
        "项目英文名称": fields["项目英文名称"]["value"],
        "行业": industry["value"],
        "行业填写方式": method,
        "行业判断依据": industry["evidence"],
        "主要业务与产品": fields["主要业务与产品"]["value"],
        "目标市场与语言": fields["市场、服务区域与网站语言"]["value"],
    }
    for label, value in replacements.items():
        text = replace_field(text, label, str(value).strip())
    rows = []
    for label in PROFILE_FIELDS:
        item = fields[label]
        fetched = str(item.get("fetched_at") or date).strip()[:10]
        rows.append(
            "| " + " | ".join(
                table_cell(value)
                for value in (
                    label,
                    item["value"],
                    item["source"],
                    fetched,
                    item["evidence"],
                    item["judgment"],
                    item["boundary"],
                )
            ) + " |"
        )
    block = (
        "## 官网初步画像\n\n"
        "- 画像状态：已完成\n"
        f"- 最近画像日期：{date}\n"
        f"- 官网状态：{website_status}\n"
        "- 上次失败与重试条件：无；官网路径或页面内容变化时重新画像\n\n"
        "| 回写字段 | 当前值 | 页面名称与具体URL | 获取日期 | 原文依据 | 判断方式 | 使用边界 |\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n"
    )
    section = re.search(r"(?ms)^## 官网初步画像\s*\n.*?(?=^##\s|\Z)", text)
    if not section:
        raise ValueError("项目基础信息缺少官网初步画像小节")
    text = text[: section.start()] + block + text[section.end() :]
    return update_contact_row(
        text,
        "官网画像已完成；运营组、公开限制和AI知识库专员待补",
        "内容运营负责人补齐人工字段；官网内容变化时Codex重新画像",
    )


def failed_info(text: str, failure_stage: str, error: str, retry_when: str, at: str) -> str:
    current_status = field(text, "画像状态")
    status = "部分完成" if current_status in {"已完成", "部分完成"} else "官网不可访问，待重试"
    section = re.search(r"(?ms)^## 官网初步画像\s*\n.*?(?=^##\s|\Z)", text)
    if not section:
        raise ValueError("项目基础信息缺少官网初步画像小节")
    profile_text = section.group(0)
    profile_text = replace_field(profile_text, "画像状态", status)
    profile_text = replace_field(profile_text, "最近画像日期", at[:10])
    profile_text = replace_field(profile_text, "官网状态", "无法访问，待重试")
    detail = f"{failure_stage}；{at}；{error}；重试条件：{retry_when}"
    profile_text = replace_field(profile_text, "上次失败与重试条件", detail)
    text = text[: section.start()] + profile_text + text[section.end() :]
    return update_contact_row(
        text,
        "官网画像待重试；人工字段待补",
        "Codex继续本地建库并在官网恢复、来源刷新、文章官网检索或月度审核时自动重试",
    )


def infer_local_build(project: Path, requested: str) -> bool:
    if requested == "complete":
        return True
    if requested == "pending":
        return False
    return (project / SOURCE_DB_RELATIVE).is_file()


def todo_state(profile_complete: bool, local_complete: bool) -> tuple[str, str, str | None]:
    if profile_complete and local_complete:
        return "等待写作任务", "初始化、官网画像、来源索引和项目校验已完成", None
    if profile_complete:
        return (
            "来源索引与项目校验",
            "官网画像已完成；继续建立来源台账、机器索引、覆盖视图并校验",
            "完成来源索引、覆盖视图和项目校验",
        )
    if local_complete:
        return (
            "官网画像待重试",
            "本地建库已完成；官网恢复时自动重试画像",
            "重试官网画像并同步项目基础信息",
        )
    return (
        "来源索引与官网画像待重试",
        "官网暂时失败；继续本地来源索引，官网恢复时自动重试",
        "完成本地来源索引并在触发条件满足时重试官网画像",
    )


def update_todo(text: str, project_id: str, profile_complete: bool, local_complete: bool, at: str) -> str:
    node, status, action = todo_state(profile_complete, local_complete)
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith("| 对象ID |")), None)
    if header is None or header + 1 >= len(lines):
        raise ValueError("当前待办缺少标准八列表")
    end = header + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    data = []
    for line in lines[header + 2 : end]:
        cells = [item.strip() for item in line.strip().strip("|").split("|")]
        if not cells or cells[0] in {project_id, "无"}:
            continue
        data.append(line)
    if action:
        blocking = "否"
        data.append(
            f"| {project_id} | {action} | {node} | {blocking} | Codex自动继续 | "
            f"[[10_项目基础信息.md]] | 官网恢复、来源变化或项目启动时重开 | {at[:10]} |"
        )
    if not data:
        data.append(
            f"| 无 | 暂无开放事项 | {node} | 否 | 等待新的写作任务或项目变化 | "
            f"[[30_版本与变更入口.md]] | 新任务、来源或官网变化时重开 | {at[:10]} |"
        )
    lines[header + 2 : end] = data
    other_active = any(
        not line.startswith(f"| {project_id} |") and not line.startswith("| 无 |") for line in data
    )
    updated = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    updated = replace_field(updated, "更新日期", at[:10])
    if not other_active:
        updated = replace_field(updated, "当前节点", node)
        updated = replace_field(updated, "当前状态", status)
    return updated


def append_version_change(text: str, project_id: str, change: str, basis: str, at: str) -> str:
    section = re.search(r"(?ms)^## 项目级变更\s*\n(.*?)(?=^##\s|\Z)", text)
    if not section:
        raise ValueError("版本入口缺少项目级变更小节")
    body = section.group(1)
    row = (
        f"| {at[:10]} | {table_cell(change)} | {table_cell(basis)} | Codex | "
        f"{project_id} | 项目基础信息、当前待办与运行记录 |"
    )
    lines = body.splitlines()
    insert_at = len(lines)
    while insert_at and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, row)
    new_body = "\n".join(lines) + "\n\n"
    return text[: section.start(1)] + new_body + text[section.end(1) :]


def apply_update(
    project: Path,
    status: str,
    *,
    profile_file: Path | None = None,
    failure_stage: str = "",
    error: str = "",
    retry_when: str = "",
    local_build_status: str = "auto",
    at: str | None = None,
) -> dict[str, object]:
    project = project.expanduser().resolve()
    timestamp = at or now_iso()
    paths = [project / INFO_RELATIVE, project / TODO_RELATIVE, project / VERSION_RELATIVE]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("缺少项目控制文件：" + "；".join(missing))
    originals = {path: read_text(path) for path in paths}
    info_text, todo_text, version_text = (originals[path] for path in paths)
    project_id = field(info_text, "项目ID") or project.name.split("_", 1)[0]
    local_complete = infer_local_build(project, local_build_status)
    profile_input: list[Path] = []

    if status == "success":
        if not profile_file:
            raise ValueError("status=success 时必须提供 --profile-file")
        profile = load_profile(profile_file)
        profile_input.append(profile_file)
        info_text = success_info(info_text, profile, timestamp)
        profile_complete = True
        change = "官网画像完成并同步初始化状态"
        basis = f"官网：{field(info_text, '官网')}；画像日期：{profile_date(profile, timestamp)}"
        ledger_status = "success"
        ledger_failure = None
        note = "官网画像已核验并回写；本地建库状态已同步。"
    elif status == "failed":
        if not failure_stage or not error or not retry_when:
            raise ValueError("status=failed 时必须提供 --failure-stage、--error 和 --retry-when")
        info_text = failed_info(info_text, failure_stage, error, retry_when, timestamp)
        profile_complete = False
        change = "官网画像失败并登记自动重试"
        basis = f"{failure_stage}；{error}；重试条件：{retry_when}"
        ledger_status = "partial"
        ledger_failure = failure_stage
        note = "官网失败不阻断本地来源索引；后续触发时自动重试。"
    else:
        profile_complete = field(info_text, "画像状态") == "已完成"
        change = "初始化状态收口"
        basis = "官网画像状态与本地来源索引状态重新核对"
        ledger_status = "success" if profile_complete and local_complete else "partial"
        ledger_failure = None if profile_complete else "website_profile"
        note = "来源索引完成后重新计算初始化状态。"

    todo_text = update_todo(todo_text, project_id, profile_complete, local_complete, timestamp)
    changed = info_text != originals[paths[0]] or todo_text != originals[paths[1]]
    if status != "reconcile" or changed:
        version_text = append_version_change(version_text, project_id, change, basis, timestamp)
        changed = True
    updates = {paths[0]: info_text, paths[1]: todo_text, paths[2]: version_text}
    if not changed:
        return {
            "ok": True,
            "changed": False,
            "project": str(project),
            "profile_complete": profile_complete,
            "local_build_complete": local_complete,
        }
    try:
        for path, content in updates.items():
            atomic_write(path, content)
        # Reconcile the project-level row with every other open todo after the
        # profile transaction has written its authoritative state.
        refresh_project_todo(
            project,
            at=timestamp,
            profile_complete=profile_complete,
            local_complete=local_complete,
        )
        record = make_record(
            project_root=project,
            task="官网画像" if status != "reconcile" else "初始化状态收口",
            status=ledger_status,
            inputs=profile_input,
            read_files=paths,
            outputs=paths,
            failure_stage=ledger_failure,
            tool_calls=[{"tool": "record_website_profile.py", "status": status}],
            note=note,
        )
        ledger = append_record(project, record)
    except Exception:
        for path, content in originals.items():
            atomic_write(path, content)
        raise
    return {
        "ok": True,
        "changed": True,
        "project": str(project),
        "profile_complete": profile_complete,
        "local_build_complete": local_complete,
        "initialization_complete": profile_complete and local_complete,
        "ledger": str(ledger),
    }


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="website-profile-test-") as temp:
        project = Path(temp) / "DEMO-001_测试知识库_v0.6"
        info = project / INFO_RELATIVE
        todo = project / TODO_RELATIVE
        version = project / VERSION_RELATIVE
        info.parent.mkdir(parents=True)
        info.write_text(
            "# 项目基础信息\n\n- 项目ID：DEMO-001\n- 项目英文名称：待补充（官网画像后自动回写）\n"
            "- 官网：https://example.com/\n- 行业：待补充\n- 行业填写方式：待官网画像\n"
            "- 行业判断依据：待官网画像\n- 主要业务与产品：待官网画像\n- 目标市场与语言：待官网画像\n\n"
            "## 官网初步画像\n\n- 画像状态：待执行\n- 最近画像日期：待记录\n- 官网状态：待检查\n"
            "- 上次失败与重试条件：无\n\n| 回写字段 | 当前值 | 页面名称与具体URL | 获取日期 | 原文依据 | 判断方式 | 使用边界 |\n"
            "|---|---|---|---|---|---|---|\n| 项目英文名称 | 待官网画像 | 待记录 | 待记录 | 待记录 | 官网不足 | 边界 |\n\n"
            "## 人工接触节点\n\n| 节点 | 需要谁提供/决定 | 需要确认的内容 | 当前状态 | 下一责任人/动作 | 处理入口 | 更新/重开条件 |\n"
            "|---|---|---|---|---|---|---|\n| 项目基础信息 | 内容运营负责人 | 字段 | 待填写 | 补齐 | 本文件 | 变化时 |\n",
            encoding="utf-8",
        )
        todo.write_text(
            "# 当前待办\n\n- 更新日期：2026-01-01\n- 当前节点：初始化\n- 当前状态：待执行\n\n"
            "| 对象ID | 人能看懂的事项 | 当前阶段 | 是否阻塞 | 下一步由谁做 | 直达链接 | 更新/重开条件 | 最近更新 |\n"
            "|---|---|---|---|---|---|---|---|\n| DEMO-001 | 初始化 | 初始化 | 是 | Codex | [[10_项目基础信息.md]] | 变化时 | 2026-01-01 |\n",
            encoding="utf-8",
        )
        version.write_text(
            "# 版本与变更入口\n\n## 项目级变更\n\n| 日期 | 变更 | 依据 | 执行方 | 关联对象 | 影响范围 |\n"
            "|---|---|---|---|---|---|\n| 2026-01-01 | 初始化 | 测试 | Codex | DEMO-001 | 控制结构 |\n\n## 相关入口\n",
            encoding="utf-8",
        )
        failed = apply_update(
            project,
            "failed",
            failure_stage="HTTP",
            error="503",
            retry_when="项目启动或官网恢复",
            local_build_status="complete",
            at="2026-09-09T10:00:00+08:00",
        )
        if failed["initialization_complete"] or "官网画像待重试" not in read_text(todo):
            return 1
        profile = Path(temp) / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "profiled_at": "2026-09-09",
                    "website_status": "可访问",
                    "fields": {
                        label: {
                            "value": f"测试{label}",
                            "source": "Home；https://example.com/",
                            "evidence": f"官网证据 {label}",
                            "judgment": "根据官网推定" if label == "行业或业务类别" else "官网明确",
                            "boundary": "仅用于测试",
                        }
                        for label in PROFILE_FIELDS
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        success = apply_update(
            project,
            "success",
            profile_file=profile,
            local_build_status="complete",
            at="2026-09-09T11:00:00+08:00",
        )
        info_text = read_text(info)
        todo_text = read_text(todo)
        ledger = project / "05_数据与审核/50_运行记录/项目运行账本.jsonl"
        if (
            not success["initialization_complete"]
            or "画像状态：已完成" not in info_text
            or "上次失败与重试条件：无；" not in info_text
            or "| 无 | 暂无开放事项 |" not in todo_text
            or len(ledger.read_text(encoding="utf-8").splitlines()) != 2
        ):
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--status", choices=("success", "failed", "reconcile"))
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--failure-stage", default="")
    parser.add_argument("--error", default="")
    parser.add_argument("--retry-when", default="")
    parser.add_argument("--local-build-status", choices=("auto", "pending", "complete"), default="auto")
    parser.add_argument("--at", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project or not args.status:
        raise SystemExit("请提供 --project 和 --status，或使用 --self-test")
    print(
        json.dumps(
            apply_update(
                args.project,
                args.status,
                profile_file=args.profile_file,
                failure_stage=args.failure_stage,
                error=args.error,
                retry_when=args.retry_when,
                local_build_status=args.local_build_status,
                at=args.at or None,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
