#!/usr/bin/env python3
"""Detect a changed v0.6 Skill at project start and record the audit result."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from manage_skill_feedback import audit


VERSION_ENTRY_RELATIVE = Path("01_工作台/30_版本与变更入口.md")
FEEDBACK_RELATIVE = Path("05_数据与审核/30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md")
SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_field(text: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def current_skill(skill_path: Path = SKILL_PATH) -> tuple[str, str]:
    text = read_text(skill_path)
    version_match = re.search(r"-v(\d+(?:\.\d+)*)$", skill_path.parent.name)
    if not version_match:
        version_match = re.search(r"(?im)^# .*?\bv(\d+(?:\.\d+)*)\b", text)
    version = f"v{version_match.group(1)}" if version_match else "unknown"
    return version, sha256_file(skill_path)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def append_change_row(text: str, row: str) -> str:
    section = re.search(r"(?ms)^## 项目级变更\s*\n(.*?)(?=^##\s|\Z)", text)
    if not section:
        marker = re.search(r"(?m)^## 相关入口\s*$", text)
        addition = (
            "## 项目级变更\n\n"
            "| 日期 | 变更 | 依据 | 执行方 | 关联对象 | 影响范围 |\n"
            "|---|---|---|---|---|---|\n"
            f"{row}\n\n"
        )
        return text[: marker.start()] + addition + text[marker.start() :] if marker else text.rstrip() + "\n\n" + addition
    body = section.group(1)
    lines = body.splitlines()
    header = next((index for index, line in enumerate(lines) if line.strip().startswith("| 日期 |")), None)
    if header is None:
        body = body.rstrip() + "\n\n" + (
            "| 日期 | 变更 | 依据 | 执行方 | 关联对象 | 影响范围 |\n"
            "|---|---|---|---|---|---|\n" + row + "\n"
        )
    else:
        insert_at = header + 2
        while insert_at < len(lines) and lines[insert_at].strip().startswith("|"):
            insert_at += 1
        lines.insert(insert_at, row)
        body = "\n".join(lines) + "\n"
    return text[: section.start(1)] + body + text[section.end(1) :]


def update_version_entry(path: Path, *, version: str, skill_hash: str, old_hash: str, detected_at: str) -> None:
    text = read_text(path)
    current_skill_line = re.compile(r"(?m)^\s*-\s*当前Skill[：:].*$")
    if current_skill_line.search(text):
        text = current_skill_line.sub(f"- 当前Skill：manage-article-knowledge {version}", text, count=1)
    else:
        text = text.rstrip() + f"\n- 当前Skill：manage-article-knowledge {version}\n"
    hash_line = re.compile(r"(?m)^\s*-\s*Skill文件SHA-256[：:].*$")
    replacement = f"- Skill文件SHA-256：{skill_hash}"
    if hash_line.search(text):
        text = hash_line.sub(replacement, text, count=1)
    else:
        text = text.rstrip() + f"\n{replacement}\n"
    row = (
        f"| {detected_at[:10]} | 启动检测同步Skill版本 | "
        f"当前Skill SHA-256 `{skill_hash}`；旧值 `{old_hash or '未记录'}` | "
        "Codex | Skill版本与反馈台账 | 项目启动版本检查 |"
    )
    text = append_change_row(text, row)
    atomic_write(path, text)


def update_feedback_ledger(
    path: Path,
    *,
    version: str,
    skill_hash: str,
    old_hash: str,
    detected_at: str,
    report: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    report = report if report is not None else audit(path)
    open_items = [item for item in report if item.get("open")]
    ids = ", ".join(str(item["id"]) for item in open_items) if open_items else "无"
    section_text = (
        "## 最近Skill版本检测\n\n"
        f"- 检测时间：{detected_at}\n"
        f"- 项目上次记录的Skill SHA-256：{old_hash or '未记录'}\n"
        f"- 当前Skill：manage-article-knowledge {version}\n"
        f"- 当前Skill SHA-256：{skill_hash}\n"
        "- 检测结果：检测到新版Skill\n"
        f"- 开放反馈：{len(open_items)}项（{ids}）\n"
        "- 处理结果：已审计开放SKFB；未自动关闭任何反馈，仍需按专项自测和项目验证推进\n"
    )
    text = read_text(path)
    existing = re.search(r"(?ms)^## 最近Skill版本检测\s*\n.*?(?=^##\s|\Z)", text)
    if existing:
        text = text[: existing.start()] + section_text + "\n" + text[existing.end() :]
    else:
        marker = re.search(r"(?m)^## 反馈详情\s*$", text)
        if marker:
            text = text[: marker.start()] + section_text + "\n" + text[marker.start() :]
        else:
            text = text.rstrip() + "\n\n" + section_text
    atomic_write(path, text)
    return {"open_feedback": len(open_items), "open_feedback_ids": [str(item["id"]) for item in open_items]}


def check_project(project: Path) -> dict[str, object]:
    project = project.expanduser().resolve()
    version_entry = project / VERSION_ENTRY_RELATIVE
    feedback = project / FEEDBACK_RELATIVE
    if not version_entry.is_file():
        raise FileNotFoundError(f"项目版本入口不存在：{version_entry}")
    version, skill_hash = current_skill()
    previous = read_text(version_entry)
    old_hash = parse_field(previous, "Skill文件SHA-256")
    changed = not re.fullmatch(r"[0-9a-fA-F]{64}", old_hash or "") or old_hash.lower() != skill_hash.lower()
    result: dict[str, object] = {
        "project": str(project),
        "current_skill": f"manage-article-knowledge {version}",
        "current_sha256": skill_hash,
        "previous_sha256": old_hash or None,
        "changed": changed,
        "feedback_updated": False,
    }
    feedback_report: list[dict[str, object]] | None = None
    if feedback.is_file():
        # Validate before changing either control file so a malformed ledger
        # cannot leave the project with a new hash but no audit record.
        feedback_report = audit(feedback)
    if not changed:
        result["message"] = "Skill版本未变化；未改写项目文件。"
        return result
    detected_at = datetime.now().astimezone().isoformat(timespec="seconds")
    update_version_entry(version_entry, version=version, skill_hash=skill_hash, old_hash=old_hash, detected_at=detected_at)
    result["version_entry_updated"] = True
    if feedback.is_file():
        result["feedback"] = update_feedback_ledger(
            feedback,
            version=version,
            skill_hash=skill_hash,
            old_hash=old_hash,
            detected_at=detected_at,
            report=feedback_report,
        )
        result["feedback_updated"] = True
    else:
        result["feedback"] = {"skipped": f"反馈台账不存在：{feedback}"}
    result["message"] = "检测到新版Skill；已同步版本入口并审计反馈台账，未自动关闭反馈。"
    return result


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v05-skill-update-test-") as temp:
        direct_skill = Path(temp) / "manage-article-knowledge" / "SKILL.md"
        direct_skill.parent.mkdir(parents=True)
        direct_skill.write_text(
            "---\nname: manage-article-knowledge\n---\n\n# 企业文章知识库管理 v0.6\n",
            encoding="utf-8",
        )
        if current_skill(direct_skill)[0] != "v0.6":
            print(json.dumps({"ok": False, "stage": "direct-root-version"}, ensure_ascii=False))
            return 1
        project = Path(temp) / "DEMO-001_测试知识库_v0.6"
        version_entry = project / VERSION_ENTRY_RELATIVE
        feedback = project / FEEDBACK_RELATIVE
        version_entry.parent.mkdir(parents=True)
        feedback.parent.mkdir(parents=True)
        version_entry.write_text(
            "# 版本与变更入口\n\n"
            "- 当前Skill：manage-article-knowledge v0.6\n"
            f"- Skill文件SHA-256：{'a' * 64}\n\n"
            "## 项目级变更\n\n"
            "| 日期 | 变更 | 依据 | 执行方 | 关联对象 | 影响范围 |\n"
            "|---|---|---|---|---|---|\n\n"
            "## 相关入口\n",
            encoding="utf-8",
        )
        feedback.write_text(
            "# Skill反馈台账\n\n## 当前反馈\n\n"
            "| SKFB ID | 提出来源 | 类型 | 通俗说明 | 复现依据 | 当前阶段 | 维护负责人 | 关联项目对象入口 | 最近更新 |\n"
            "|---|---|---|---|---|---|---|---|---|\n\n"
            "## 反馈详情\n",
            encoding="utf-8",
        )
        first = check_project(project)
        second = check_project(project)
        version_text = read_text(version_entry)
        feedback_text = read_text(feedback)
        if not first["changed"] or not first["feedback_updated"] or second["changed"]:
            print(json.dumps({"ok": False, "stage": "change-detection", "first": first, "second": second}, ensure_ascii=False))
            return 1
        if "## 最近Skill版本检测" not in feedback_text or version_text.count("启动检测同步Skill版本") != 1:
            print(json.dumps({"ok": False, "stage": "artifacts"}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    if not args.project:
        raise SystemExit("--project is required")
    print(json.dumps(check_project(args.project), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
