#!/usr/bin/env python3
"""Produce a read-only candidate map for first-time workspace onboarding."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


IGNORED_DIRS = {
    ".git",
    ".idea",
    ".obsidian",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
    "assets",
    "changelog",
    "docs",
    "references",
    "scripts",
    "versions",
    ".article-build",
}
IGNORED_PREFIXES = ("render_", "lo_profile_", ".revision-", ".retired-")
SOURCE_NAMES = ("原始", "客户资料", "源资料", "资料", "知识库", "source", "sources", "reference")
TASK_NAMES = ("写作任务", "任务", "周计划", "排期", "topic", "keyword", "outline", "brief")
FINAL_NAMES = ("终稿", "成稿", "已发", "final", "publish", "published", "delivery")
FAITHFULNESS_NAMES = ("faithfulness", "审核结果", "deepeval", "审核")
IMAGE_NAMES = ("图片", "配图", "images", "assets", "media")
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".html", ".htm"}
SOURCE_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md"}
OUTPUT_EXTENSIONS = {".docx", ".md", ".html", ".zip"}
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# Existing vaults may use the historical `_v0.6` suffix. New vaults omit it.
V06_PROJECT_NAME_RE = re.compile(r"知识库(?:[_ -]?v?0\.6)?$", re.IGNORECASE)
NON_CLIENT_HOSTS = {
    "chatgpt.com", "www.chatgpt.com", "github.com", "www.github.com",
    "deepeval.com", "www.deepeval.com", "docs.ragas.io", "doi.org",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", action="append", required=True, type=Path)
    parser.add_argument("--obsidian-root", required=True, type=Path)
    parser.add_argument("--faithfulness-root", required=True, type=Path)
    parser.add_argument("--default-content-owner", required=True, help="Default content operations owner recorded for the confirmation step.")
    parser.add_argument(
        "--scope",
        choices=("single", "selected", "all"),
        default="all",
        help="Discovery scope; this does not authorize initialization.",
    )
    parser.add_argument("--project", action="append", default=[], help="Project directory or name for single/selected scope.")
    parser.add_argument("--max-projects", type=int, default=0, help="Optional initialization batch limit recorded in the report.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path. Existing files are never overwritten.")
    return parser.parse_args()


def ignored(path: Path) -> bool:
    ignored_names = {name.casefold() for name in IGNORED_DIRS}
    return any(
        part.casefold() in ignored_names
        or any(part.casefold().startswith(prefix.casefold()) for prefix in IGNORED_PREFIXES)
        for part in path.parts
    )


def ignored_name(name: str) -> bool:
    lowered = name.casefold()
    return lowered in {item.casefold() for item in IGNORED_DIRS} or any(
        lowered.startswith(prefix.casefold()) for prefix in IGNORED_PREFIXES
    )


def name_matches(name: str, terms: tuple[str, ...]) -> bool:
    lowered = name.casefold()
    return any(term.casefold() in lowered for term in terms)


def is_knowledge_base_project_name(name: str) -> bool:
    """Keep an existing vault from being mistaken for source material."""
    return bool(V06_PROJECT_NAME_RE.search(name.strip()))


def child_dirs(root: Path) -> list[Path]:
    try:
        return sorted((item for item in root.iterdir() if item.is_dir() and not ignored(item)), key=lambda item: item.name.casefold())
    except OSError:
        return []


def collect_evidence(project: Path, max_depth: int = 2, max_files: int = 2500) -> dict[str, object]:
    extensions: Counter[str] = Counter()
    source_dirs: list[str] = []
    task_dirs: list[str] = []
    final_dirs: list[str] = []
    faithfulness_dirs: list[str] = []
    image_dirs: list[str] = []
    urls: list[dict[str, str]] = []
    files_seen = 0
    unreadable = False
    excluded_dirs: list[str] = []

    try:
        for current, dirs, files in os.walk(project):
            current_path = Path(current)
            relative_depth = len(current_path.relative_to(project).parts)
            excluded_dirs.extend(str(current_path / name) for name in dirs if ignored_name(name))
            dirs[:] = [name for name in dirs if not ignored_name(name)]
            if relative_depth >= max_depth:
                dirs[:] = []
            if name_matches(current_path.name, SOURCE_NAMES) and not is_knowledge_base_project_name(current_path.name):
                source_dirs.append(str(current_path))
            if name_matches(current_path.name, TASK_NAMES):
                task_dirs.append(str(current_path))
            if name_matches(current_path.name, FINAL_NAMES):
                final_dirs.append(str(current_path))
            if name_matches(current_path.name, FAITHFULNESS_NAMES):
                faithfulness_dirs.append(str(current_path))
            if name_matches(current_path.name, IMAGE_NAMES):
                image_dirs.append(str(current_path))

            for filename in files:
                files_seen += 1
                path = current_path / filename
                extensions[path.suffix.casefold() or "[no extension]"] += 1
                if files_seen > max_files:
                    unreadable = True
                    break
                try:
                    file_size = path.stat().st_size
                except OSError:
                    unreadable = True
                    continue
                if path.suffix.casefold() in TEXT_EXTENSIONS and file_size <= 64 * 1024:
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                    except (OSError, UnicodeError):
                        continue
                    for url in URL_RE.findall(text)[:10]:
                        urls.append({"url": url.rstrip(".,);"), "source": str(path)})
            if files_seen > max_files:
                break
    except OSError:
        unreadable = True

    source_file_count = sum(extensions.get(ext, 0) for ext in SOURCE_EXTENSIONS)
    output_file_count = sum(extensions.get(ext, 0) for ext in OUTPUT_EXTENSIONS)
    score = min(100, len(source_dirs) * 20 + len(task_dirs) * 15 + len(final_dirs) * 15 + len(faithfulness_dirs) * 15 + min(source_file_count, 20) * 2)
    if urls:
        score = min(100, score + 10)

    return {
        "candidate_path": str(project.resolve()),
        "candidate_name": project.name,
        "confidence": "高" if score >= 60 else "中" if score >= 25 else "低",
        "confidence_score": score,
        "files_seen": files_seen,
        "scan_truncated": unreadable,
        "file_extensions": dict(sorted(extensions.items())),
        "source_file_count": source_file_count,
        "output_file_count": output_file_count,
        "source_candidates": source_dirs,
        "writing_task_candidates": task_dirs,
        "final_candidates": final_dirs,
        "faithfulness_candidates": faithfulness_dirs,
        "image_candidates": image_dirs,
        "website_candidates": urls,
        "excluded_directories": sorted(set(excluded_dirs)),
        "missing": {
            "website": not bool(urls),
            "writing_task": not bool(task_dirs),
            "final": not bool(final_dirs),
            "faithfulness": not bool(faithfulness_dirs),
        },
    }


def candidate_dirs(root: Path, include_nested: bool) -> list[Path]:
    candidates: list[Path] = []
    for first in child_dirs(root):
        candidates.append(first)
        if include_nested:
            for second in child_dirs(first):
                candidates.append(second)
    return candidates


def unique_paths(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def suggested_project_name(value: str) -> str:
    cleaned = re.sub(r"^\s*\d+\s*", "", value).strip()
    cleaned = re.sub(r"[（(][^）)]*组[^）)]*[）)]\s*$", "", cleaned).strip()
    cleaned = re.sub(r"(?i)\s*知识库(?:\s*v?\d[^\\/]*)?$", "", cleaned).strip()
    return cleaned or value.strip()


def likely_client_website(values: list[dict[str, str]]) -> tuple[str, str, list[str]]:
    by_host: dict[str, list[dict[str, str]]] = {}
    for item in values:
        raw = item["url"].split("](", 1)[0].rstrip(".,);，；")
        try:
            parsed = urlsplit(raw)
        except ValueError:
            continue
        host = (parsed.hostname or "").casefold()
        if not host or host in NON_CLIENT_HOSTS:
            continue
        by_host.setdefault(host, []).append({"url": raw, "source": item["source"]})
    if not by_host:
        return "未发现", "需人工补充", []
    ranked = sorted(by_host.items(), key=lambda row: (-len(row[1]), row[0]))
    host, matches = ranked[0]
    homepage = f"https://{host}/"
    source = matches[0]["source"]
    other_hosts = [name for name, _ in ranked[1:]]
    if not other_hosts:
        return homepage, f"已确定；同一企业域名线索来自：{source}", []
    return (
        homepage,
        f"Codex优先识别为客户主官网；主要线索来自：{source}",
        ["继续核对其他网址是否只是外部资料或工具网站；只有企业关系仍不明确时才询问人工。"],
    )


def build_field_assessment(evidence: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    project = Path(str(evidence["candidate_path"]))
    sources = unique_paths(list(evidence["source_candidates"]))
    tasks = unique_paths(list(evidence["writing_task_candidates"]))
    finals = unique_paths(list(evidence["final_candidates"]))
    codex_review: list[str] = []
    human_questions: list[str] = []
    creation_proposals: list[str] = []

    if len(sources) == 1:
        source_value = sources[0]
        source_status = "已确定"
    elif len(sources) > 1:
        source_value = "；".join(sources)
        source_status = "由Codex继续判断主资料入口"
        codex_review.append("核对多个资料目录的包含关系和实际资料内容；只有仍无法唯一判断时才询问人工。")
    elif int(evidence["source_file_count"]) >= 2:
        source_value = str(project)
        source_status = "由Codex继续区分项目根目录中的客户资料与写作产物"
        codex_review.append("在项目根目录内识别客户原始资料，排除终稿、写作要求、审核结果和临时产物；仍无法分清时才询问人工。")
    else:
        source_value = "未发现"
        source_status = "需人工补充"
        human_questions.append("请提供客户原始资料所在目录。")

    website_value, website_status, website_review = likely_client_website(list(evidence["website_candidates"]))
    codex_review.extend(website_review)
    if website_value == "未发现":
        human_questions.append("请提供客户主官网；没有官网时明确回复“无官网”。")

    def external_entry(values: list[str], suggested: Path, label: str) -> dict[str, str]:
        if len(values) == 1:
            return {"value": values[0], "status": "已确定"}
        if len(values) > 1:
            if label == "终稿入口":
                human_questions.append("终稿入口存在多个候选，只能由人工选择：" + "；".join(values))
                return {"value": "；".join(values), "status": "待人工选择"}
            codex_review.append(f"核对多个{label}候选的包含关系和实际使用记录；仍不唯一时才询问人工。")
            return {"value": "；".join(values), "status": "由Codex继续判断"}
        creation_proposals.append(f"待建立入口（确认后自动创建）：{label}：{suggested}")
        return {"value": str(suggested), "status": "待建立入口（确认后自动创建）；否则暂不接入"}

    task = external_entry(tasks, project / "写作任务", "写作任务入口")
    final = external_entry(finals, project / "终稿", "终稿入口")
    return {
        "project_name": {"value": suggested_project_name(str(evidence["candidate_name"])), "status": f"已识别；原目录名：{evidence['candidate_name']}"},
        "website": {"value": website_value, "status": website_status},
        "source_path": {"value": source_value, "status": source_status},
        "obsidian_root": {"value": str(args.obsidian_root.resolve()), "status": "已由统一配置确定"},
        "post_initialization_project_path": {
            "value": "由Codex按项目命名合同生成并在初始化后登记",
            "status": "建库后自动确定",
        },
        "content_owner": {"value": args.default_content_owner, "status": "已由统一配置确定"},
        "writing_task_entry": task,
        "final_entry": final,
        "faithfulness_entry": {
            "value": str(args.faithfulness_root.resolve()),
            "status": "已由统一配置确定；项目、文章和版本子目录由系统自动建立",
        },
        "codex_review": codex_review,
        "human_questions": human_questions,
        "creation_proposals": creation_proposals,
        "ready_without_human": not human_questions,
    }


def select_projects(candidates: list[dict[str, object]], args: argparse.Namespace) -> list[dict[str, object]]:
    requested = {str(Path(item).resolve()).casefold() for item in args.project}
    if args.scope == "all":
        selected = candidates
    else:
        selected = [item for item in candidates if str(Path(str(item["candidate_path"])).resolve()).casefold() in requested or str(item["candidate_name"]).casefold() in {Path(value).name.casefold() for value in args.project}]
    if args.max_projects > 0:
        for index, item in enumerate(selected):
            item["initialization_batch"] = "本次处理" if index < args.max_projects else "待处理"
    return selected


def filter_candidate_paths(paths: list[Path], args: argparse.Namespace) -> list[Path]:
    if args.scope == "all":
        return paths
    if not args.project:
        raise SystemExit(f"--scope {args.scope} requires at least one --project value")

    selected: list[Path] = []
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for value in args.project:
        exact = [path for path in paths if str(path.resolve()).casefold() == str(Path(value).resolve()).casefold()]
        if exact:
            selected.extend(exact)
            continue
        named = [path for path in paths if path.name.casefold() == Path(value).name.casefold()]
        if not named:
            unmatched.append(value)
        elif len(named) > 1:
            ambiguous.append(f"{value}: " + ", ".join(str(path) for path in named))
        else:
            selected.extend(named)

    if unmatched or ambiguous:
        messages: list[str] = []
        if unmatched:
            messages.append("未找到候选项目：" + ", ".join(unmatched))
        if ambiguous:
            messages.append("项目名称对应多个候选路径，请改用绝对路径：" + "；".join(ambiguous))
        raise SystemExit("；".join(messages))

    unique: dict[str, Path] = {str(path.resolve()).casefold(): path for path in selected}
    if args.scope == "single" and len(unique) != 1:
        raise SystemExit("--scope single 只能对应一个项目")
    return list(unique.values())


def is_project_candidate(evidence: dict[str, object]) -> bool:
    markers = (
        evidence["source_candidates"],
        evidence["writing_task_candidates"],
        evidence["final_candidates"],
        evidence["faithfulness_candidates"],
    )
    return bool(any(markers) or int(evidence["source_file_count"]) >= 2)


def main() -> None:
    args = parse_args()
    roots = [root.resolve() for root in args.workspace_root]
    candidate_paths: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        # In all-project mode the operator-selected workspace root defines the
        # project boundary: each direct child is one project. Nested folders
        # are evidence/entry candidates inside that project, never additional
        # projects. Explicit single/selected modes may still name a deeper
        # directory directly.
        for project in candidate_dirs(root, include_nested=args.scope != "all"):
            key = str(project.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            candidate_paths.append(project)

    # An explicitly supplied in-scope path may be deeper than the lightweight
    # two-level discovery walk. It is safe to inspect it because the operator
    # named it and it is still constrained to the declared workspace roots.
    if args.scope != "all":
        for value in args.project:
            explicit = Path(value).expanduser()
            if not explicit.is_dir():
                continue
            resolved = explicit.resolve()
            if not any(resolved == root or root in resolved.parents for root in roots):
                continue
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                candidate_paths.append(resolved)

    candidate_paths = filter_candidate_paths(candidate_paths, args)
    candidates: list[dict[str, object]] = []
    for project in candidate_paths:
        evidence = collect_evidence(project)
        if is_project_candidate(evidence) or args.scope != "all":
            evidence["recognition_status"] = "候选项目" if is_project_candidate(evidence) else "未识别项目"
            evidence["suggested_external_paths"] = {
                "writing_task": str(project / "写作任务"),
                "final": str(project / "终稿"),
            }
            candidates.append(evidence)
    candidates = select_projects(candidates, args)
    for index, evidence in enumerate(candidates, start=1):
        evidence["candidate_id"] = f"P-{index:03d}"
        evidence["field_assessment"] = build_field_assessment(evidence, args)
    report = {
        "report_type": "manage-article-knowledge-workspace-discovery",
        "read_only": True,
        "workspace_roots": [str(root) for root in roots],
        "obsidian_root": str(args.obsidian_root.resolve()),
        "faithfulness_root": str(args.faithfulness_root.resolve()),
        "default_content_owner": args.default_content_owner,
        "scope": args.scope,
        "requested_projects": args.project,
        "max_projects": args.max_projects,
        "projects": candidates,
        "shared_decision": "对所有待建立入口一次选择：确认后自动创建，或本次暂不接入缺失的写作任务/终稿入口。",
        "next_step": "人工确认项目映射后，才允许调用initialize_project.py；本报告不创建目录、不访问官网、不修改原始资料。",
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output.resolve()
        if output.exists():
            raise SystemExit(f"Refusing to overwrite existing report: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
