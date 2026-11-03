"""Register related enterprise websites and record primary-website changes."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from todo_sync import refresh_project_todo, remove_todo_row, upsert_todo_row


INFO_RELATIVE = Path("01_工作台/10_项目基础信息.md")
RELATED_HEADING = "## 内容运营提交的其他企业相关网站"
HISTORY_HEADING = "## 官网变更记录"
RELATED_HEADER = "| 网站ID | 网站名称与用途 | 网站类型 | 具体URL | 企业关系与依据 | 使用范围 | 关联文章 | 可访问状态 | 最近检查 | 覆盖模块/内容 | 下次复核条件 |"


def load(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def save(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def project_id(text: str, fallback: str) -> str:
    match = re.search(r"(?m)^-\s*项目ID[：:]\s*(\S+)", text)
    return match.group(1) if match else fallback.split("_", 1)[0]


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("网站URL必须是http或https地址")


def next_website_id(text: str, pid: str) -> str:
    values = [int(item) for item in re.findall(rf"WEB-{re.escape(pid)}-(\d{{3}})", text)]
    return f"WEB-{pid}-{max(values, default=0) + 1:03d}"


def related_row(website_id: str, name: str, site_type: str, url: str, relation: str, scope: str, articles: str, checked: str) -> str:
    return f"| {website_id} | {name} | {site_type} | {url} | {relation} | {scope} | {articles} | 待检查 | {checked} | 待确认 | 页面变化、文章命中或月度审核 |"


def register_related(project: Path, name: str, url: str, site_type: str, relation: str, scope: str, articles: str) -> dict:
    validate_url(url)
    path = project / INFO_RELATIVE
    text = load(path)
    if RELATED_HEADING not in text:
        raise ValueError(f"项目基础信息缺少固定网站登记表：{path}")
    pid = project_id(text, project.name)
    website_id = next_website_id(text, pid)
    today = date.today().isoformat()
    row = related_row(website_id, name, site_type, url, relation or "关系待确认；依据不足", scope, articles, today)
    lines = text.splitlines()
    heading_index = lines.index(RELATED_HEADING)
    next_heading = next((i for i in range(heading_index + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[heading_index:next_heading]
    placeholder = next((i for i, line in enumerate(section) if line.startswith("| 无 | 暂无内容运营提交的其他企业相关网站 |")), None)
    if placeholder is not None:
        section[placeholder] = row
    else:
        insert_at = next((i for i, line in enumerate(section) if line.startswith(RELATED_HEADER)), None)
        if insert_at is None:
            raise ValueError("网站登记表缺少固定表头")
        section.insert(insert_at + 2, row)
    lines[heading_index:next_heading] = section
    save(path, "\n".join(lines))
    refresh_project_todo(project)
    upsert_todo_row(
        project, object_id=website_id,
        human_text=f"完成关联网站 {website_id} 的关系与可访问性核验",
        stage="关联网站核验", blocked="是" if not relation else "否",
        owner="内容运营负责人确认企业关系；Codex核验页面可访问性",
        link="[[10_项目基础信息.md#内容运营提交的其他企业相关网站]]",
        condition="关系、授权、可访问性或文章依赖变化时重开",
    )
    return {"ok": True, "action": "register-related", "website_id": website_id, "project": str(project), "path": str(path)}


def update_primary(project: Path, new_url: str, old_url: str, note: str) -> dict:
    validate_url(new_url)
    path = project / INFO_RELATIVE
    text = load(path)
    match = re.search(r"(?m)^(-\s*官网[：:])\s*(.*)$", text)
    if not match:
        raise ValueError(f"项目基础信息缺少官网字段：{path}")
    current = match.group(2).strip()
    old = old_url.strip() or current
    today = date.today().isoformat()
    updated = text[: match.start()] + f"{match.group(1)} {new_url}" + text[match.end() :]
    profile = re.search(r"(?ms)^## 官网初步画像\s*\n.*?(?=^##\s|\Z)", updated)
    if not profile:
        raise ValueError("项目基础信息缺少官网初步画像小节")
    profile_text = profile.group(0)
    for label, value in (("画像状态", "待重新画像"), ("最近画像日期", today), ("官网状态", "待检查")):
        pattern = re.compile(rf"^(\s*[-*]\s*{re.escape(label)}[：:]\s*).*?$", re.MULTILINE)
        profile_text, count = pattern.subn(lambda item, value=value: item.group(1) + value, profile_text, count=1)
        if count != 1:
            raise ValueError(f"官网初步画像缺少字段：{label}")
    updated = updated[:profile.start()] + profile_text + updated[profile.end():]
    row = f"| {today} | {old} | {new_url} | {note or '主官网更新，待重新执行官网画像'} | 待重新画像 |"
    if HISTORY_HEADING in updated:
        lines = updated.splitlines()
        index = lines.index(HISTORY_HEADING)
        insert = next((i for i in range(index + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        lines[insert:insert] = [row]
        updated = "\n".join(lines)
    else:
        updated = updated.rstrip() + "\n\n" + "\n".join([
            HISTORY_HEADING,
            "",
            "| 日期 | 原官网 | 新官网 | 变更说明 | 画像状态 |",
            "|---|---|---|---|---|",
            row,
        ])
    save(path, updated)
    upsert_todo_row(
        project, object_id=project_id(text, project.name),
        human_text="重新执行主官网画像并同步受影响知识",
        stage="官网画像待重试", blocked="是",
        owner="Codex核验新官网并运行官网画像回写",
        link="[[10_项目基础信息.md#官网初步画像]]",
        condition="官网画像成功或失败回写后收口；页面变化时重开",
    )
    return {"ok": True, "action": "update-primary", "old_url": old, "new_url": new_url, "project": str(project), "path": str(path)}


def verify_related(project: Path, website_id: str, access_status: str, relation: str, coverage: str) -> dict:
    path = project / INFO_RELATIVE
    text = load(path)
    lines = text.splitlines()
    found = False
    for index, line in enumerate(lines):
        if not line.startswith(f"| {website_id} |"):
            continue
        cells = [item.strip() for item in line.strip().strip("|").split("|")]
        if len(cells) != 11:
            raise ValueError(f"关联网站行不是标准十一列：{website_id}")
        if relation:
            cells[4] = relation
        cells[7] = access_status
        cells[8] = date.today().isoformat()
        if coverage:
            cells[9] = coverage
        lines[index] = "| " + " | ".join(cells) + " |"
        found = True
        pending = "待确认" in cells[4] or access_status != "可访问"
        if pending:
            upsert_todo_row(
                project, object_id=website_id, human_text=f"继续核验关联网站 {website_id}",
                stage="关联网站核验", blocked="是" if "待确认" in cells[4] else "否",
                owner="内容运营负责人确认企业关系；Codex重试可访问性",
                link="[[10_项目基础信息.md#内容运营提交的其他企业相关网站]]",
                condition="关系确认且网站可访问后关闭；关系、授权或文章依赖变化时重开",
            )
        else:
            remove_todo_row(project, object_id=website_id)
        break
    if not found:
        raise ValueError(f"未找到关联网站：{website_id}")
    save(path, "\n".join(lines))
    return {"ok": True, "action": "verify-related", "website_id": website_id, "project": str(project), "path": str(path)}


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="mak-web-") as temp:
        project = Path(temp) / "P-001_知识库"
        (project / INFO_RELATIVE.parent).mkdir(parents=True)
        (project / INFO_RELATIVE).write_text(
            "- 项目ID：P-001\n- 官网：https://old.example.com\n\n"
            "## 官网初步画像\n\n- 画像状态：已完成\n- 最近画像日期：2026-01-01\n"
            "- 官网状态：可访问\n- 上次失败与重试条件：无\n\n"
            f"{RELATED_HEADING}\n\n{RELATED_HEADER}\n|---|---|---|---|---|---|---|---|---|---|---|\n"
            "| 无 | 暂无内容运营提交的其他企业相关网站 | 不适用 | 无 | 无 | 不适用 | 不适用 | 未登记 | 未检查 | 无 | 内容运营提交站点时建立 |\n",
            encoding="utf-8",
        )
        (project / "01_工作台/20_当前待办.md").write_text(
            "# 当前待办\n\n- 更新日期：2026-01-01\n- 当前节点：等待写作任务\n"
            "- 当前状态：初始化、官网画像、来源索引和项目校验已完成\n\n"
            f"{__import__('todo_sync').TODO_HEADER}\n|---|---|---|---|---|---|---|---|\n"
            "| 无 | 暂无开放事项 | 等待写作任务 | 否 | 等待任务 | [[30_版本与变更入口.md]] | 变化时 | 2026-01-01 |\n",
            encoding="utf-8",
        )
        (project / "02_源资料").mkdir(parents=True)
        (project / "02_源资料/source-index.sqlite").touch()
        result = register_related(project, "子品牌站", "https://brand.example.com", "子品牌官网", "子品牌；内容运营提交", "项目级通用（默认）", "全部文章（默认）")
        assert result["website_id"] == "WEB-P-001-001"
        verify_related(project, "WEB-P-001-001", "可访问", "子品牌；已核验", "公司概述")
        update_primary(project, "https://new.example.com", "", "迁移")
        text = load(project / INFO_RELATIVE)
        todo = load(project / "01_工作台/20_当前待办.md")
        assert "https://new.example.com" in text and HISTORY_HEADING in text
        assert "画像状态：待重新画像" in text and "重新执行主官网画像" in todo
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register-related", "verify-related", "update-primary"), nargs="?")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--name", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--site-type", default="其他企业相关站点")
    parser.add_argument("--relation", default="")
    parser.add_argument("--scope", default="项目级通用（默认）")
    parser.add_argument("--articles", default="全部文章（默认）")
    parser.add_argument("--old-url", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--website-id", default="")
    parser.add_argument("--access-status", choices=("可访问", "部分可访问", "暂时无法访问", "已停用"), default="可访问")
    parser.add_argument("--coverage", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.action or not args.project:
        raise SystemExit("action and --project are required")
    if args.action != "verify-related" and not args.url:
        raise SystemExit("--url is required")
    project = args.project.resolve()
    if args.action == "register-related":
        if not args.name:
            raise SystemExit("--name is required")
        result = register_related(project, args.name, args.url, args.site_type, args.relation, args.scope, args.articles)
    elif args.action == "verify-related":
        if not args.website_id:
            raise SystemExit("--website-id is required")
        result = verify_related(project, args.website_id, args.access_status, args.relation, args.coverage)
    else:
        result = update_primary(project, args.url, args.old_url, args.note)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
