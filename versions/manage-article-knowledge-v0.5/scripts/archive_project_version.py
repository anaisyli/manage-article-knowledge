#!/usr/bin/env python3
"""Create a read-only project version snapshot before changing current files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path


ARTICLE_STATES = {"10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"}


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode text file: {path}")


def parse_field(text: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_segment(value: str, fallback: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", value.strip())
    value = re.sub(r"\s+", "_", value).strip(" ._")
    return value[:100] or fallback


def relative_inside(path: Path, root: Path, label: str) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside the project: {path}") from exc


def skill_identity() -> tuple[str, str]:
    skill = Path(__file__).resolve().parent.parent / "SKILL.md"
    return "manage-article-knowledge v0.5", sha256_file(skill)


def archive_destination(
    project: Path,
    target: Path,
    kind: str,
    object_id: str,
    version: str,
    archived_at: datetime,
) -> Path:
    stamp = archived_at.strftime("%Y%m%d-%H%M%S")
    folder = f"{safe_segment(version, 'version-unknown')}_{stamp}"
    if kind == "article":
        return project / "04_文章任务/90_归档/10_文章历史版本" / safe_segment(object_id, "article-unknown") / folder
    relative = relative_inside(target, project, "Target")
    if kind == "formal-knowledge":
        base = project / "05_数据与审核/60_版本归档/10_正式知识历史"
        return base / safe_segment(object_id, target.stem) / folder
    base = project / "05_数据与审核/60_版本归档/20_控制文件迁移历史"
    # Do not mirror the full control-file path: deep OneDrive projects can exceed
    # Windows MAX_PATH before the archive is even created. The manifest retains
    # the original relative path, while this short key remains deterministic.
    relative_key = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:12]
    return base / f"{safe_segment(target.stem, 'control-file')}-{relative_key}" / folder


def staging_destination(destination: Path) -> Path:
    """Keep the staging path shorter than the final path on Windows."""
    return destination.parent / f".tmp-{uuid.uuid4().hex[:8]}"


def snapshot_files(target: Path, kind: str) -> list[tuple[Path, Path]]:
    if kind == "article":
        result: list[tuple[Path, Path]] = []
        for source in sorted(target.rglob("*")):
            if not source.is_file() or source.name.endswith(".tmp") or any(part.startswith(".") for part in source.relative_to(target).parts):
                continue
            result.append((source, source.relative_to(target)))
        return result
    return [(target, Path(target.name))]


def create_archive(
    *,
    project: Path,
    target: Path,
    kind: str,
    reason: str,
    replacement_version: str,
    archived_at: datetime | None = None,
) -> Path:
    project = project.resolve()
    target = target.resolve()
    target_relative = relative_inside(target, project, "Target")
    if "90_归档" in target_relative.parts or "60_版本归档" in target_relative.parts:
        raise ValueError("Historical archives are read-only and cannot be archived again as current files")
    if kind == "article":
        if not target.is_dir() or target.parent.name not in ARTICLE_STATES:
            raise ValueError("Article target must be a current task directory under a standard state")
        identity = target / "10_文章知识需求.md"
        if not identity.is_file():
            raise ValueError(f"Article task is missing 10_文章知识需求.md: {target}")
        text = read_text(identity)
        object_id = parse_field(text, "文章ID")
        object_name = parse_field(text, "标题") or target.name
        version = parse_field(text, "当前版本")
        original_state = target.parent.name
    else:
        if not target.is_file():
            raise ValueError(f"File target not found: {target}")
        text = read_text(target) if target.suffix.lower() == ".md" else ""
        if kind == "formal-knowledge":
            required_root = project / "03_正式知识"
            relative_inside(target, required_root, "Formal knowledge target")
            object_id = parse_field(text, "知识ID") or target.stem
            object_name = target.stem
            version = parse_field(text, "知识版本") or "version-unknown"
        elif kind == "control":
            object_id = target.relative_to(project).as_posix()
            object_name = target.name
            version = parse_field(text, "当前版本") or "snapshot"
        else:
            raise ValueError(f"Unsupported archive kind: {kind}")
        original_state = "current-file"
    if not object_id:
        raise ValueError(f"Archive object has no stable ID: {target}")
    if not version:
        raise ValueError(f"Archive object has no current version: {target}")

    archived_at = archived_at or datetime.now().astimezone()
    destination = archive_destination(project, target, kind, object_id, version, archived_at)
    if destination.exists():
        raise ValueError(f"Archive destination already exists: {destination}")
    temporary = staging_destination(destination)
    files = snapshot_files(target, kind)
    if not files:
        raise ValueError(f"Archive target has no files: {target}")
    skill_name, skill_hash = skill_identity()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.mkdir()
        rows: list[tuple[str, str, str]] = []
        for source, relative in files:
            copied = temporary / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
            source_hash = sha256_file(source)
            if sha256_file(copied) != source_hash:
                raise ValueError(f"Archive copy hash mismatch: {source}")
            rows.append((relative.as_posix(), source_hash, "修改前只读快照"))
        current_entry = target.relative_to(project).as_posix()
        manifest = [
            "# 历史版本说明",
            "",
            f"- 对象类型：{kind}",
            f"- 对象ID：{object_id}",
            f"- 人话名称：{object_name}",
            f"- 归档版本：{version}",
            f"- 归档时间：{archived_at.isoformat(timespec='seconds')}",
            f"- 归档原因：{reason}",
            f"- 归档前状态：{original_state}",
            f"- 替代版本：{replacement_version}",
            f"- 当前入口：{current_entry}",
            f"- 执行Skill：{skill_name}",
            f"- Skill SHA-256：{skill_hash}",
            "",
            "## 归档文件与指纹",
            "",
            "| 文件名 | SHA-256 | 说明 |",
            "|---|---|---|",
        ]
        manifest.extend(f"| {name} | `{digest}` | {note} |" for name, digest, note in rows)
        (temporary / "00_版本说明.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v05-archive-test-") as temp:
        project = Path(temp) / "DEMO_示例知识库_v0.5"
        task = project / "04_文章任务/20_等待终稿/DEMO-ART-001_测试文章"
        task.mkdir(parents=True)
        (task / "10_文章知识需求.md").write_text(
            "# 文章知识需求\n\n- 文章ID：DEMO-ART-001\n- 当前版本：v1\n- 标题：测试文章\n",
            encoding="utf-8",
        )
        (task / "30_本篇知识库资料.md").write_text("# 本篇写作素材包\n", encoding="utf-8")
        fixed_time = datetime.fromisoformat("2026-08-19T12:00:00+08:00")
        archived = create_archive(
            project=project,
            target=task,
            kind="article",
            reason="self-test",
            replacement_version="v2",
            archived_at=fixed_time,
        )
        expected = archived / "10_文章知识需求.md"
        if not expected.is_file() or sha256_file(expected) != sha256_file(task / expected.name):
            print(json.dumps({"ok": False, "stage": "copy"}, ensure_ascii=False))
            return 1
        manifest = archived / "00_版本说明.md"
        if not manifest.is_file() or "- 归档版本：v1" not in read_text(manifest):
            print(json.dumps({"ok": False, "stage": "manifest"}, ensure_ascii=False))
            return 1

        deep_project = Path(temp) / ("深层项目路径_" + "A" * 70) / "DEMO_示例知识库_v0.5"
        control = deep_project / "05_数据与审核/40_月度与交接/2026-08_月度知识库审核.md"
        control.parent.mkdir(parents=True)
        control.write_text("# 企业知识库月度审核\n", encoding="utf-8")
        control_archive = create_archive(
            project=deep_project,
            target=control,
            kind="control",
            reason="deep-path-self-test",
            replacement_version="新版模板",
            archived_at=fixed_time,
        )
        copied_control = control_archive / control.name
        if not copied_control.is_file() or sha256_file(copied_control) != sha256_file(control):
            print(json.dumps({"ok": False, "stage": "deep-control-copy"}, ensure_ascii=False))
            return 1
        if len(str(control_archive)) >= 240 or "40_月度与交接" in str(control_archive):
            print(json.dumps({"ok": False, "stage": "deep-control-destination"}, ensure_ascii=False))
            return 1
        if f"- 当前入口：{control.relative_to(deep_project).as_posix()}" not in read_text(control_archive / "00_版本说明.md"):
            print(json.dumps({"ok": False, "stage": "deep-control-manifest"}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--kind", choices=("article", "formal-knowledge", "control"))
    parser.add_argument("--reason")
    parser.add_argument("--replacement-version", default="待建立")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(run_self_test())
    if not args.project or not args.target or not args.kind or not args.reason:
        raise SystemExit("--project, --target, --kind and --reason are required")
    try:
        destination = create_archive(
            project=args.project,
            target=args.target,
            kind=args.kind,
            reason=args.reason,
            replacement_version=args.replacement_version,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"ok": True, "archive": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
