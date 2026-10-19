"""Preview, apply, and verify non-destructive v0.6 handoff migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from handoff_review import project_value, write_review


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_map(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*") if p.is_file()}


def conflicts(source: Path, target: Path) -> dict:
    if not target.exists():
        return {"target_status": "不存在，将创建", "same": [], "missing": sorted(file_map(source)), "conflicts": []}
    source_files = file_map(source)
    target_files = file_map(target)
    same = sorted(k for k, v in source_files.items() if target_files.get(k) == v)
    missing = sorted(k for k in source_files if k not in target_files)
    changed = sorted(k for k in source_files if k in target_files and target_files[k] != source_files[k])
    return {"target_status": "已存在", "same": same, "missing": missing, "conflicts": changed}


def copy_merge(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    report = conflicts(source, target)
    if report["conflicts"]:
        raise FileExistsError(f"target conflicts: {target}: {report['conflicts'][:5]}")
    for relative in report["missing"]:
        origin = source / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)


def read_manifest(package: Path) -> dict:
    manifest = package / "handoff-manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"handoff-manifest.json not found: {manifest}")
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not isinstance(data.get("projects"), list):
        raise ValueError("unsupported handoff manifest")
    return data


def resolve_package_path(package: Path, item: dict, key: str) -> Path | None:
    record = item.get(key, {})
    if record.get("status") not in {"已打包", "已包含"}:
        return None
    if record.get("status") == "已包含" and key == "obsidian":
        source = item.get("source", {})
        if source.get("status") != "已打包":
            return None
        base = package / f"{item['project_id']}_项目交接包" / Path(source["package_path"]).name
        relative = record.get("relative_path")
        return base / relative if relative else base
    return package / f"{item['project_id']}_项目交接包" / Path(record["package_path"]).name


def project_targets(item: dict, package: Path, workspace: Path | None, obsidian: Path | None, faithfulness: Path | None) -> dict:
    pid = item["project_id"]
    source = resolve_package_path(package, item, "source")
    obs = resolve_package_path(package, item, "obsidian")
    faith = resolve_package_path(package, item, "faithfulness")
    source_target_name = item.get("source", {}).get("target_name") or (source.name if source else "")
    return {
        "source": {"package": source, "target": workspace / source_target_name if source and workspace else None},
        "obsidian": {"package": obs, "target": obsidian / item.get("obsidian", {}).get("target_name", obs.name) if obs and obsidian else None},
        "faithfulness": {"package": faith, "target": faithfulness / pid if faith and faithfulness else None},
    }


def replace_field(text: str, label: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^(-\s*{re.escape(label)}[：:]\s*).*$")
    if pattern.search(text):
        return pattern.sub(lambda match: match.group(1) + value, text, count=1)
    return text.rstrip() + f"\n- {label}：{value}\n"


def remap_path(value: str, old_root: str, new_root: Path) -> str:
    if not value or value in {"待确认", "待填写"}:
        return value
    old = Path(value.strip().strip("`"))
    if not old.is_absolute():
        return value
    try:
        return str(new_root / old.resolve().relative_to(Path(old_root).resolve()))
    except ValueError:
        return value


def update_project_config(kb: Path, item: dict, targets: dict, owner: str) -> list[str]:
    errors: list[str] = []
    info_path = kb / "01_工作台/10_项目基础信息.md"
    config_path = kb / "01_工作台/40_写作与Faithfulness接入配置.md"
    if not info_path.is_file():
        return [f"缺少项目基础信息：{info_path}"]
    info = info_path.read_text(encoding="utf-8-sig", errors="replace")
    old_source = item.get("source", {}).get("source_path", "")
    source_target = targets["source"]["target"]
    old_project_root = item.get("project_root", "")
    if source_target and old_project_root:
        info = replace_field(info, "项目根目录", str(source_target))
        customer_source = item.get("customer_source_path", "")
        if customer_source:
            info = replace_field(
                info,
                "客户原始资料路径",
                remap_path(customer_source, old_project_root, source_target),
            )
    elif source_target:
        # v1早期交接包的source记录代表客户原始资料，而不是整个项目根目录。
        info = replace_field(info, "客户原始资料路径", str(source_target))
    info = replace_field(info, "Obsidian项目路径", str(kb))
    info = replace_field(info, "内容运营负责人", owner)
    info_path.write_text(info, encoding="utf-8")
    if config_path.is_file():
        config = config_path.read_text(encoding="utf-8-sig", errors="replace")
        for label, key in (("写作任务入口路径", "writing_entry"), ("终稿入口路径", "final_entry")):
            old_value = item.get(key, "")
            remap_root = old_project_root or old_source
            if source_target and remap_root:
                old_value = remap_path(old_value, remap_root, source_target)
            if old_value:
                config = replace_field(config, label, old_value)
        faith_target = targets["faithfulness"]["target"]
        if faith_target:
            config = replace_field(config, "Faithfulness结果根目录", str(faith_target.parent))
        config_path.write_text(config, encoding="utf-8")
    else:
        errors.append(f"缺少接入配置，未更新三个入口：{config_path}")
    return errors


def inspect_item(item: dict, package: Path, workspace: Path | None, obsidian: Path | None, faithfulness: Path | None) -> dict:
    targets = project_targets(item, package, workspace, obsidian, faithfulness)
    sections = {}
    errors = []
    for key, record in targets.items():
        source = record["package"]
        target = record["target"]
        if source is None:
            sections[key] = {"status": "交接包未提供", "target": str(target) if target else ""}
            continue
        if target is None:
            sections[key] = {"status": "目标根目录未提供", "package": str(source), "target": ""}
            errors.append(f"{key}目标根目录未提供")
            continue
        report = conflicts(source, target)
        report.update({"package": str(source), "target": str(target)})
        sections[key] = report
        if report["conflicts"]:
            errors.append(f"{key}存在文件冲突")
    return {
        "project_id": item["project_id"],
        "enterprise_name": item.get("enterprise_name", ""),
        "sections": sections,
        "package_issues": item.get("errors", []),
        "errors": errors,
    }


def run(package: Path, workspace: Path | None, obsidian: Path | None, faithfulness: Path | None, owner: str | None, mode: str, confirm: str | None, selected: set[str] | None) -> dict:
    package = package.resolve()
    manifest = read_manifest(package)
    results = []
    for item in manifest["projects"]:
        if selected and item["project_id"] not in selected:
            continue
        inspection = inspect_item(item, package, workspace, obsidian, faithfulness)
        if mode == "apply":
            if confirm != "确认迁移":
                inspection["errors"].append("缺少确认口令：确认迁移")
            elif not owner:
                inspection["errors"].append("缺少新的内容运营负责人")
            elif not inspection["errors"]:
                targets = project_targets(item, package, workspace, obsidian, faithfulness)
                try:
                    for record in targets.values():
                        if record["package"] and record["target"]:
                            copy_merge(record["package"], record["target"])
                    kb = targets["obsidian"]["target"]
                    inspection["config_errors"] = update_project_config(kb, item, targets, owner)
                    inspection["errors"].extend(inspection["config_errors"])
                    inspection["status"] = "已迁移" if not inspection["errors"] else "迁移后需处理"
                except (OSError, ValueError) as exc:
                    inspection["errors"].append(str(exc))
                    inspection["status"] = "本项目失败"
        if mode == "verify":
            targets = project_targets(item, package, workspace, obsidian, faithfulness)
            kb = targets["obsidian"]["target"]
            if kb and kb.is_dir():
                try:
                    review_path = write_review(
                        kb,
                        stage="接收后",
                        project_id=item["project_id"],
                        enterprise_name=item.get("enterprise_name", ""),
                        original_owner=item.get("original_owner", "未从交接包读取"),
                        new_owner=project_value(kb, "内容运营负责人"),
                        package_path=str(package),
                        issues=[*item.get("errors", []), *inspection["errors"]],
                    )
                    inspection["handoff_review"] = str(review_path)
                except OSError as exc:
                    inspection["errors"].append(f"接收后项目交接审核未生成：{exc}")
                    inspection["handoff_review"] = ""
            else:
                inspection["errors"].append("接收后项目交接审核未生成：目标Obsidian知识库不存在")
                inspection["handoff_review"] = ""
        results.append(inspection)
    return {"schema_version": 1, "mode": mode, "package": str(package), "projects": results}


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="mak-migration-") as temp:
        root = Path(temp)
        package = root / "handoff"
        item_dir = package / "P-001_项目交接包"
        project_files = item_dir / "P-001_项目文件"
        (project_files / "客户资料").mkdir(parents=True)
        (project_files / "写作任务").mkdir()
        (project_files / "终稿").mkdir()
        (item_dir / "P-001_Obsidian知识库/01_工作台").mkdir(parents=True)
        (item_dir / "P-001_Obsidian知识库/01_工作台/10_项目基础信息.md").write_text(
            "- 项目ID：P-001\n- 项目根目录：C:\\旧位置\\测试项目\n"
            "- 客户原始资料路径：C:\\旧位置\\测试项目\\客户资料\n"
            "- 内容运营负责人：旧负责人\n",
            encoding="utf-8",
        )
        (item_dir / "P-001_Obsidian知识库/01_工作台/40_写作与Faithfulness接入配置.md").write_text(
            "- 写作任务入口路径：C:\\旧位置\\测试项目\\写作任务\n"
            "- 终稿入口路径：C:\\旧位置\\测试项目\\终稿\n"
            "- Faithfulness结果根目录：C:\\旧Faithfulness\n",
            encoding="utf-8",
        )
        manifest = {"schema_version": 1, "projects": [{"project_id": "P-001", "enterprise_name": "测试", "project_root": "C:\\旧位置\\测试项目", "customer_source_path": "C:\\旧位置\\测试项目\\客户资料", "source": {"status": "已打包", "package_path": str(project_files), "source_path": "C:\\旧位置\\测试项目", "target_name": "测试项目"}, "obsidian": {"status": "已打包", "package_path": str(item_dir / "P-001_Obsidian知识库"), "target_name": "P-001_测试知识库_v0.6"}, "faithfulness": {"status": "缺失"}, "writing_entry": "C:\\旧位置\\测试项目\\写作任务", "final_entry": "C:\\旧位置\\测试项目\\终稿", "errors": []}]}
        package.mkdir(exist_ok=True)
        (package / "handoff-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        preview = run(package, root / "workspace", root / "obsidian", root / "faith", "新负责人", "preview", None, None)
        assert preview["projects"][0]["sections"]["obsidian"]["target_status"] == "不存在，将创建"
        applied = run(package, root / "workspace", root / "obsidian", root / "faith", "新负责人", "apply", "确认迁移", None)
        assert applied["projects"][0]["status"] == "已迁移"
        info = (root / "obsidian/P-001_测试知识库_v0.6/01_工作台/10_项目基础信息.md").read_text(encoding="utf-8")
        assert f"- 项目根目录：{root / 'workspace/测试项目'}" in info
        assert f"- 客户原始资料路径：{root / 'workspace/测试项目/客户资料'}" in info
        verified = run(package, root / "workspace", root / "obsidian", root / "faith", None, "verify", None, None)
        assert verified["projects"][0]["handoff_review"].endswith("_接收后项目交接审核.md")
        assert Path(verified["projects"][0]["handoff_review"]).is_file()
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--obsidian-root", type=Path)
    parser.add_argument("--faithfulness-root", type=Path)
    parser.add_argument("--new-owner")
    parser.add_argument("--project-id", action="append")
    parser.add_argument("--mode", choices=("preview", "apply", "verify"), default="preview")
    parser.add_argument("--confirm")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.package:
        raise SystemExit("--package is required")
    result = run(args.package, args.workspace_root, args.obsidian_root, args.faithfulness_root, args.new_owner, args.mode, args.confirm, set(args.project_id) if args.project_id else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if any(item.get("errors") for item in result["projects"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
