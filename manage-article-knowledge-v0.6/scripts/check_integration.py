#!/usr/bin/env python3
"""Validate one project's writing and Faithfulness integration configuration."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import csv
from pathlib import Path

from update_integration_status import update as update_integration_status


CONFIG_RELATIVE = Path("01_工作台/40_写作与Faithfulness接入配置.md")
ALLOWED_STATES = {"待写作流程建立", "部分接入", "已确认", "异常，待重新确认"}
PLACEHOLDERS = {"", "待确认", "待扫描", "未接入", "无"}


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


def field_alias(text: str, *labels: str) -> str:
    """Read the current label while accepting pre-v0.6 terminology aliases."""
    for label in labels:
        value = field(text, label)
        if value:
            return value
    return ""


def project_id_for_root(project_root: Path) -> str:
    """Return the confirmed project identity, with a legacy path-name fallback."""
    root = project_root.resolve()
    info = root / "01_工作台/10_项目基础信息.md"
    project_id = field(read_text(info), "项目ID") if info.is_file() else ""
    project_id = project_id or root.name.split("_", 1)[0].strip()
    if not project_id:
        raise ValueError("无法从项目基础信息或项目路径确定项目ID")
    return project_id


def usable(value: str) -> bool:
    return value not in PLACEHOLDERS and not value.startswith("待确认")


def _task_candidates(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    return sorted(
        item for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in {".md", ".txt", ".csv", ".tsv", ".json"}
    )


def _sample_fields(path: Path) -> tuple[bool, bool, bool]:
    """Return whether a sample exposes a stable key, title and status."""
    if path.suffix.lower() in {".csv", ".tsv"}:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter="\t" if path.suffix.lower() == ".tsv" else ","))
            if not rows:
                return False, False, False
            headers = " ".join(rows[0].keys()).lower()
            return (
                any(token in headers for token in ("任务编号", "任务id", "task_id", "id", "编号")),
                any(token in headers for token in ("标题", "title", "主题", "topic")),
                any(token in headers for token in ("状态", "status", "stage")),
            )
        except (OSError, UnicodeError, csv.Error):
            return False, False, False
    try:
        text = read_text(path)
    except (OSError, ValueError):
        return False, False, False
    labels = [m.group(1).lower() for m in re.finditer(r"^\s*[-*|]?\s*([^：:|]+)[：:]", text, re.MULTILINE)]
    lowered = " ".join(labels) + " " + text.lower()
    return (
        bool(re.search(r"任务(编号|id)|task[_ -]?id|外部任务唯一键|\b编号\b", lowered, re.I)),
        bool(re.search(r"标题|title|主题|topic", lowered, re.I)),
        bool(re.search(r"状态|status|待写作|待开始|ready", lowered, re.I)),
    )


def probe_task_entry(raw_path: str, status_rule: str) -> list[str]:
    path = Path(raw_path)
    candidates = _task_candidates(path)
    if not candidates:
        return [f"写作任务入口没有可读取的样例文件：{raw_path}"]
    errors: list[str] = []
    found = [False, False, False]
    for sample in candidates[:20]:
        flags = _sample_fields(sample)
        found = [left or right for left, right in zip(found, flags)]
        if all(found):
            break
    labels = ("外部任务唯一键", "标题/主题", "状态")
    for flag, label in zip(found, labels):
        if not flag:
            errors.append(f"任务样例未能识别{label}，请检查字段映射或重新确认")
    if usable(status_rule):
        token = re.split(r"[：:=]", status_rule, maxsplit=1)[-1].strip().strip("[]()")
        if token and token not in PLACEHOLDERS:
            sample_parts = []
            for sample in candidates[:20]:
                if sample.suffix.lower() in {".csv", ".tsv"}:
                    try:
                        sample_parts.append(sample.read_text(encoding="utf-8-sig"))
                    except (OSError, UnicodeError):
                        continue
                else:
                    sample_parts.append(read_text(sample))
            sample_text = "\n".join(sample_parts)
            if token.lower() not in sample_text.lower():
                errors.append(f"任务样例中未找到可接收状态规则指定的值：{token}")
    return errors


def validate(config: Path, check_paths: bool = True) -> dict[str, object]:
    if not config.is_file():
        return {"status": "invalid", "errors": [f"缺少接入配置：{config}"], "warnings": []}

    text = read_text(config)
    state = field(text, "接入状态")
    errors: list[str] = []
    warnings: list[str] = []
    if state not in ALLOWED_STATES:
        errors.append(f"接入状态无效：{state or '未填写'}")

    values = {
        # New configurations use “写作任务入口路径/终稿入口路径”.
        # Keep the former labels as read-only aliases for existing projects.
        "task_path": field_alias(text, "写作任务入口路径", "写作任务路径"),
        "task_key": field(text, "外部任务唯一键规则"),
        "task_status": field(text, "可接收状态规则"),
        "task_mapping": field(text, "任务字段映射"),
        "final_path": field_alias(text, "终稿入口路径", "终稿路径"),
        "final_match": field(text, "终稿识别规则"),
        "identity": field(text, "文章身份回传规则"),
        "faithfulness_root": field(text, "Faithfulness结果根目录"),
    }

    required_when_confirmed = {
        "task_path": "写作任务入口路径",
        "task_key": "外部任务唯一键规则",
        "task_status": "可接收状态规则",
        "task_mapping": "任务字段映射",
        "final_path": "终稿入口路径",
        "final_match": "终稿识别规则",
        "identity": "文章身份回传规则",
        "faithfulness_root": "Faithfulness结果根目录",
    }
    if state == "已确认":
        for key, label in required_when_confirmed.items():
            if not usable(values[key]):
                errors.append(f"接入状态为已确认，但{label}尚未确认")
        identity = values["identity"]
        identity_has_fields = "文章ID" in identity and "文章版本" in identity
        identity_has_kb_fallback = (
            "知识库" in identity
            and ("生成" in identity or "补齐" in identity or "兜底" in identity)
            and "文章ID" in identity
            and "文章版本" in identity
        )
        if usable(identity) and not (identity_has_fields or identity_has_kb_fallback):
            errors.append(
                "文章身份回传规则必须说明文章ID和文章版本由写作Skill回传，"
                "或缺失时由知识库按命名规则生成/补齐"
            )
    elif state == "部分接入":
        if not any(usable(values[key]) for key in ("task_path", "final_path", "faithfulness_root")):
            errors.append("部分接入至少要有一个已确认的外部入口")

    if check_paths:
        for key, label in (
            ("task_path", "写作任务入口路径"),
            ("final_path", "终稿入口路径"),
            ("faithfulness_root", "Faithfulness结果根目录"),
        ):
            raw = values[key]
            if not usable(raw):
                continue
            path = Path(raw)
            if not path.is_absolute():
                errors.append(f"{label}必须是绝对路径：{raw}")
            elif not path.exists():
                message = f"{label}当前不存在：{raw}"
                if state == "已确认":
                    errors.append(message)
                else:
                    warnings.append(message)

    if state == "已确认" and usable(values["task_path"]):
        errors.extend(probe_task_entry(values["task_path"], values["task_status"]))

    if state == "异常，待重新确认" and not warnings:
        warnings.append("接入已标记异常；请根据配置中的重新确认条件处理")

    return {
        "status": "valid" if not errors else "invalid",
        "integration_state": state,
        "errors": errors,
        "warnings": warnings,
        "config": str(config.resolve()),
    }


def faithfulness_result_dir(
    config: Path, article_id: str, article_version: str, project_id: str | None = None
) -> Path:
    text = read_text(config)
    root_value = field(text, "Faithfulness结果根目录")
    if not usable(root_value):
        raise ValueError("Faithfulness结果根目录尚未确认")
    root = Path(root_value)
    if not root.is_absolute():
        raise ValueError(f"Faithfulness结果根目录必须是绝对路径：{root_value}")
    if not article_id.strip() or not article_version.strip():
        raise ValueError("计算Faithfulness结果目录需要文章ID和文章版本")
    if not project_id:
        project_root = config.resolve().parents[1]
        project_id = project_id_for_root(project_root)
    if not project_id:
        raise ValueError("无法从项目路径确定项目ID，不能建立Faithfulness结果目录")
    cleaned_project = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", project_id).strip(" .-")
    if not cleaned_project:
        raise ValueError("项目ID无效，不能建立Faithfulness结果目录")
    target = root / cleaned_project / article_id.strip() / f"v{article_version.strip().lstrip('vV')}"
    target.mkdir(parents=True, exist_ok=True)
    return target


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config = root / CONFIG_RELATIVE
        config.parent.mkdir(parents=True)
        config.write_text(
            "\n".join(
                [
                    "# 写作与Faithfulness接入配置",
                    "",
                    "- 接入状态：待写作流程建立",
                    "- 写作任务入口路径：待确认",
                    "- 外部任务唯一键规则：待确认",
                    "- 可接收状态规则：待确认",
                    "- 任务字段映射：待确认",
                    "- 终稿入口路径：待确认",
                    "- 终稿识别规则：待确认",
                    "- 文章身份回传规则：写作Skill回传文章ID和文章版本；缺失时由知识库按命名规则生成并补齐",
                    "- Faithfulness结果根目录：待确认",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        task = root / "tasks.md"
        task.write_text("- 任务编号：T-001\n- 标题：示例\n- 状态：待写作\n", encoding="utf-8")
        final_root = root / "final"
        result_root = root / "results"
        final_root.mkdir()
        result_root.mkdir()
        config.write_text(
            "\n".join([
                "# 写作与Faithfulness接入配置",
                "- 接入状态：已确认",
                f"- 写作任务入口路径：{task}",
                "- 外部任务唯一键规则：任务编号",
                "- 可接收状态规则：状态=待写作",
                "- 任务字段映射：任务编号、标题、状态",
                f"- 终稿入口路径：{final_root}",
                "- 终稿识别规则：精确Output path",
                "- 文章身份回传规则：缺失时由知识库按命名规则生成并补齐文章ID和文章版本",
                f"- Faithfulness结果根目录：{result_root}",
            ]) + "\n",
            encoding="utf-8",
        )
        result = validate(config)
        if result["status"] != "valid":
            raise SystemExit(f"self-test failed: {result}")
        config.write_text(read_text(config).replace("- 接入状态：已确认", "- 接入状态：异常，待重新确认"), encoding="utf-8")
        result = validate(config)
        if result["status"] != "valid":
            raise SystemExit(f"self-test failed: legacy abnormal state should validate: {result}")
        update_integration_status(config.parents[1], "integration_check_success", at="2026-09-03T10:00:00+08:00")
        if "- 接入状态：已确认" not in read_text(config):
            raise SystemExit("self-test failed: successful check should restore valid state")
    print("self-test=passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--no-path-check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if bool(args.project) == bool(args.config):
        raise SystemExit("请提供且只提供 --project 或 --config")
    config = args.config if args.config else args.project.resolve() / CONFIG_RELATIVE
    result = validate(config.resolve(), check_paths=not args.no_path_check)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "valid":
        raise SystemExit(1)
    if args.project and result["status"] == "valid":
        update_integration_status(args.project.resolve(), "integration_check_success")


if __name__ == "__main__":
    main()
