"""Build a non-destructive handoff package for one or more v0.6 projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

from handoff_review import write_review


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else ""


def field(text: str, name: str) -> str:
    match = re.search(rf"(?m)^-\s*{re.escape(name)}[：:]\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def project_id(project: Path) -> str:
    value = field(read_text(project / "01_工作台/10_项目基础信息.md"), "项目ID")
    return value or project.name.split("_", 1)[0]


def project_name(project: Path) -> str:
    text = read_text(project / "01_工作台/10_项目基础信息.md")
    return (
        field(text, "项目中文名称")
        or field(text, "企业名称")
        or field(text, "项目名称")
        or project.name
    )


def configured_path(project: Path, label: str) -> Path | None:
    candidates = [
        project / "01_工作台/10_项目基础信息.md",
        project / "01_工作台/40_写作与Faithfulness接入配置.md",
    ]
    for candidate in candidates:
        value = field(read_text(candidate), label)
        if value and value not in {"待确认", "待填写", "无", "未登记"}:
            path = Path(value.strip().strip("`"))
            if not path.is_absolute():
                path = (project / path).resolve()
            return path
    return None


def safe_relative(child: Path, parent: Path) -> str | None:
    try:
        return child.resolve().relative_to(parent.resolve()).as_posix()
    except ValueError:
        return None


def faithfulness_project_dir(project: Path, root: Path | None, pid: str) -> Path | None:
    if root is None:
        return None
    candidate = root / pid
    if candidate.is_dir():
        return candidate
    return root if root.name == pid else candidate


def copy_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"handoff destination already exists: {destination}")
    shutil.copytree(source, destination)


def write_project_manifest(path: Path, item: dict) -> None:
    rows = [
        "# 项目交接清单",
        "",
        f"- 项目ID：{item['project_id']}",
        f"- 企业名称：{item['enterprise_name']}",
        f"- 原项目根目录：{item.get('project_root', '')}",
        f"- 客户原始资料路径：{item.get('customer_source_path', '')}",
        f"- 原Obsidian项目路径：{item['project_path']}",
        "",
        "## 包内内容",
        "",
        "| 内容 | 原路径 | 包内路径 | 状态 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for label, key in (("项目文件", "source"), ("Obsidian知识库", "obsidian"), ("Faithfulness审核", "faithfulness")):
        record = item[key]
        rows.append(
            f"| {label} | {record.get('source_path', '')} | {record.get('package_path', '')} | "
            f"{record.get('status', '')} | {record.get('note', '')} |"
        )
    rows.extend(
        [
            "",
            "## 接入入口",
            "",
            f"- 写作任务入口：{item.get('writing_entry', '') or '未从配置读取；接收方迁移时复核'}",
            f"- 终稿入口：{item.get('final_entry', '') or '未从配置读取；接收方迁移时复核'}",
            f"- Faithfulness结果入口：{item.get('faithfulness_entry', '') or '未从配置读取；接收方迁移时复核'}",
            "",
            "交接包制作不删除原文件。接收方须先预演目标路径和冲突，人工确认后再迁移。",
        ]
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def package_one(project: Path, output: Path) -> dict:
    project = project.resolve()
    pid = project_id(project)
    project_root = configured_path(project, "项目根目录")
    customer_source = configured_path(project, "客户原始资料路径")
    item = {
        "project_id": pid,
        "enterprise_name": project_name(project),
        "project_root": str(project_root or ""),
        "customer_source_path": str(customer_source or ""),
        "project_path": str(project),
        "writing_entry": configured_path(project, "写作任务入口路径"),
        "final_entry": configured_path(project, "终稿入口路径"),
        "faithfulness_entry": configured_path(project, "Faithfulness结果根目录"),
        "original_owner": field(read_text(project / "01_工作台/10_项目基础信息.md"), "内容运营负责人"),
        "source": {},
        "obsidian": {},
        "faithfulness": {},
        "errors": [],
    }
    if project_root and safe_relative(output, project_root) is not None:
        raise ValueError("交接包输出目录不能位于项目根目录内部")
    item_dir = output / f"{pid}_项目交接包"
    item_dir.mkdir(parents=True, exist_ok=False)

    source = project_root
    source_dir = item_dir / f"{pid}_项目文件"
    source_record = {
        "source_path": str(source) if source else "",
        "package_path": str(source_dir),
        "target_name": source.name if source else "",
        "status": "缺失",
        "note": "未读取到项目根目录",
    }
    if source and source.exists():
        copy_tree(source, source_dir)
        source_record.update(status="已打包", note="")
        if customer_source and safe_relative(customer_source, source) is None:
            source_record["note"] = "客户原始资料路径位于项目根目录之外，未随项目文件包含"
            item["errors"].append("客户原始资料未随项目文件包含")
    item["source"] = source_record

    obsidian_dir = item_dir / f"{pid}_Obsidian知识库"
    source_contains_project = source is not None and safe_relative(project, source) is not None
    if source_contains_project:
        obsidian_record = {"source_path": str(project), "package_path": str(source_dir), "relative_path": safe_relative(project, source), "target_name": project.name, "status": "已包含", "note": "Obsidian项目位于项目文件包内，未重复复制"}
    else:
        copy_tree(project, obsidian_dir)
        obsidian_record = {"source_path": str(project), "package_path": str(obsidian_dir), "relative_path": "", "target_name": obsidian_dir.name, "status": "已打包", "note": ""}
    item["obsidian"] = obsidian_record

    faith_root = configured_path(project, "Faithfulness结果根目录")
    faith_dir = faithfulness_project_dir(project, faith_root, pid)
    faith_package = item_dir / f"{pid}_Faithfulness审核"
    faith_record = {"source_path": str(faith_dir) if faith_dir else "", "package_path": str(faith_package), "status": "缺失", "note": "未读取到Faithfulness结果根目录或项目目录"}
    if faith_dir and faith_dir.exists():
        copy_tree(faith_dir, faith_package)
        faith_record.update(status="已打包", note="")
    item["faithfulness"] = faith_record

    if source_record["status"] == "缺失":
        item["errors"].append("项目文件未打包")
    if faith_record["status"] == "缺失":
        item["errors"].append("Faithfulness审核结果未打包")
    review_path = write_review(
        project,
        stage="交付前",
        project_id=pid,
        enterprise_name=item["enterprise_name"],
        original_owner=item["original_owner"],
        new_owner="待接收方确认",
        package_path=str(item_dir),
        issues=item["errors"],
    )
    review_relative = review_path.relative_to(project)
    if source_contains_project:
        project_relative = safe_relative(project, source)
        packaged_review = source_dir / project_relative / review_relative
    else:
        packaged_review = obsidian_dir / review_relative
    packaged_review.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(review_path, packaged_review)
    item["handoff_review"] = str(review_path)
    item["packaged_handoff_review"] = str(packaged_review)
    item["writing_entry"] = str(item["writing_entry"] or "")
    item["final_entry"] = str(item["final_entry"] or "")
    item["faithfulness_entry"] = str(item["faithfulness_entry"] or "")
    write_project_manifest(item_dir / "00_项目交接清单.md", item)
    (item_dir / "handoff-manifest.json").write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return item


def build_package(projects: list[Path], output: Path) -> dict:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    items = [package_one(project, output) for project in projects]
    manifest = {"schema_version": 1, "created_at": date.today().isoformat(), "package_path": str(output), "projects": items}
    (output / "handoff-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = ["# 交接总清单", "", f"- 生成日期：{manifest['created_at']}", f"- 项目数量：{len(items)}", "", "| 项目ID | 企业名称 | 项目文件 | Obsidian | Faithfulness | 异常 |", "|---|---|---|---|---|---|"]
    for item in items:
        rows.append(f"| {item['project_id']} | {item['enterprise_name']} | {item['source']['status']} | {item['obsidian']['status']} | {item['faithfulness']['status']} | {'；'.join(item['errors']) or '无'} |")
    rows.extend(["", "每个项目均有独立项目交接清单。交接包制作不删除原文件；接收方必须先预演，人工确认后再迁移。"])
    (output / "00_交接总清单.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="mak-package-") as temp:
        root = Path(temp)
        project = root / "P-001_项目知识库_v0.6"
        (project / "01_工作台").mkdir(parents=True)
        (project / "02_源资料").mkdir()
        workspace_project = root / "客户项目/P-001_测试项目"
        source = workspace_project / "客户资料"
        source.mkdir(parents=True)
        (source / "a.txt").write_text("a", encoding="utf-8")
        (workspace_project / "终稿").mkdir()
        (workspace_project / "终稿/article.docx").write_text("draft", encoding="utf-8")
        (project / "01_工作台/10_项目基础信息.md").write_text(
            "- 项目ID：P-001\n- 项目中文名称：测试企业\n- 企业名称：不应采用的旧字段值\n- 项目根目录：" + str(workspace_project)
            + "\n- 客户原始资料路径：" + str(source) + "\n",
            encoding="utf-8",
        )
        result = build_package([project], root / "handoff")
        assert result["projects"][0]["enterprise_name"] == "测试企业"
        assert result["projects"][0]["source"]["status"] == "已打包"
        assert (root / "handoff/P-001_项目交接包/P-001_项目文件/终稿/article.docx").is_file()
        review_name = f"{date.today().isoformat()}_交付前项目交接审核.md"
        assert (project / "05_数据与审核/40_月度与交接" / review_name).is_file()
        assert (root / "handoff/P-001_项目交接包/P-001_Obsidian知识库/05_数据与审核/40_月度与交接" / review_name).is_file()
        assert result["projects"][0]["handoff_review"].endswith("_交付前项目交接审核.md")
        assert result["projects"][0]["packaged_handoff_review"].endswith("_交付前项目交接审核.md")
        total_text = read_text(root / "handoff/00_交接总清单.md")
        project_text = read_text(root / "handoff/P-001_项目交接包/00_项目交接清单.md")
        total_json = json.loads(read_text(root / "handoff/handoff-manifest.json"))
        project_json = json.loads(read_text(root / "handoff/P-001_项目交接包/handoff-manifest.json"))
        assert "| P-001 | 测试企业 |" in total_text
        assert "- 企业名称：测试企业" in project_text
        assert total_json["projects"][0]["enterprise_name"] == "测试企业"
        assert project_json["enterprise_name"] == "测试企业"
        (project / "01_工作台/10_项目基础信息.md").write_text(
            "- 项目ID：P-001\n- 企业名称：旧版测试企业\n",
            encoding="utf-8",
        )
        assert project_name(project) == "旧版测试企业"
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", action="append", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.project or not args.output:
        raise SystemExit("--project and --output are required")
    print(json.dumps(build_package(args.project, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
