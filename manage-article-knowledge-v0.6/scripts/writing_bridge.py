#!/usr/bin/env python3
"""Bridge an arbitrary writing workflow to the v0.6 article task contract.

This helper does not write articles.  It creates the knowledge task before
writing and normalizes an externally produced final article after writing.
The normalized knowledge copy contains text/table content only; images remain
in the external writer delivery package and are never copied into the task.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

from handoff_contract import HandoffContractError, current_version, validate_event, validate_version
from check_integration import project_id_for_root
from check_skill_update import check_project as check_skill_version
from record_writing_task import RELATIVE_LEDGER, load, record
from template_contract import TEMPLATE_VERSION
from update_integration_status import update as update_integration_status


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件：{path}")


def read_article_text(path: Path) -> str:
    """Read a text article without mutating the externally delivered file.

    Most writing Skills return Markdown/TXT, but several deliver only a DOCX.
    DOCX is a ZIP package, so extract visible paragraphs and table cells with
    the standard library instead of requiring a project-specific dependency.
    """
    if path.suffix.lower() != ".docx":
        value = read_text(path)
        # Keep prose and Markdown tables, but remove embedded image syntax so
        # the knowledge copy never treats article artwork as article content.
        value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
        value = re.sub(r"<img\b[^>]*>", "", value, flags=re.IGNORECASE)
        return value
    try:
        with zipfile.ZipFile(path) as package:
            xml = package.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ValueError(f"无法读取DOCX正文：{path}") from exc
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"DOCX正文XML无效：{path}") from exc
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    body = root.find(".//w:body", ns)
    if body is None:
        return ""
    blocks: list[str] = []

    def paragraph_text(paragraph: ET.Element) -> str:
        return "".join(node.text or "" for node in paragraph.findall(".//w:t", ns)).strip()

    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            value = paragraph_text(child)
            if value:
                blocks.append(value)
        elif tag == "tbl":
            # Preserve table semantics as Markdown rows while ignoring all
            # drawing/media parts. Faithfulness receives text and table values,
            # never the article's image binaries.
            rows: list[str] = []
            for row in child.findall("./w:tr", ns):
                cells: list[str] = []
                for cell in row.findall("./w:tc", ns):
                    value = " ".join(
                        paragraph_text(paragraph)
                        for paragraph in cell.findall("./w:p", ns)
                        if paragraph_text(paragraph)
                    )
                    cells.append(value.replace("|", "\\|"))
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def field(text: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def project_code(project: Path) -> str:
    value = project_id_for_root(project)
    value = re.sub(r"[^A-Za-z0-9-]+", "", value).upper()
    return value or "PROJECT"


def clean_title(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", value).strip()
    return re.sub(r"\s+", " ", value)[:80] if value else "未命名文章"


def next_article_id(project: Path, today: str) -> str:
    prefix = f"{project_code(project)}-ART-{today.replace('-', '')}-"
    numbers: list[int] = []
    for path in (project / "04_文章任务").rglob("10_文章知识需求.md"):
        value = field(read_text(path), "文章ID")
        if value.startswith(prefix) and value[len(prefix):].isdigit():
            numbers.append(int(value[len(prefix):]))
    ledger = project / RELATIVE_LEDGER
    if ledger.is_file():
        with ledger.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                value = str(row.get("article_id", ""))
                if value.startswith(prefix) and value[len(prefix):].isdigit():
                    numbers.append(int(value[len(prefix):]))
    return prefix + f"{max(numbers, default=0) + 1:03d}"


def sync_skill_version(project: Path) -> dict[str, object]:
    """Run the project-start Skill fingerprint check used by the main Skill.

    The writing bridge is a real machine entry used by connected writing Skills,
    so it must not bypass the project's version/feedback synchronization.
    """
    try:
        result = check_skill_version(project)
    except FileNotFoundError as exc:
        raise SystemExit(
            "无法执行项目启动Skill版本检查："
            f"{exc}。请先用manage-article-knowledge v0.6初始化项目，生成01_工作台/30_版本与变更入口.md。"
        ) from exc
    print(
        "skill_version_check="
        + ("updated" if result.get("changed") else "current")
    )
    return result


def prepare(args: argparse.Namespace) -> None:
    try:
        contract_version = validate_version(args.handoff_contract_version)
    except HandoffContractError as exc:
        raise SystemExit(str(exc)) from exc
    project = args.project.resolve()
    sync_skill_version(project)
    external_task_key = args.external_task_key.strip()
    if not external_task_key:
        raise SystemExit("提交 writing_request 前必须提供非空外部任务唯一键")
    title = clean_title(args.title)
    if title == "未命名文章":
        raise SystemExit("提交 writing_request 前必须提供可识别的标题或主题")
    outline = (args.outline or "").strip()
    if not outline:
        raise SystemExit("提交 writing_request 前必须提供非空简要大纲；不得使用待定大纲")
    if args.outline_status != "已确认":
        raise SystemExit("提交 writing_request 前必须将 --outline-status 设置为：已确认")
    source = args.source_path.resolve()
    if not source.is_file():
        raise SystemExit(f"本次写作需求记录必须是已保存的文件：{source}")
    if not args.source_locator.strip() or args.source_locator.strip() == "未记录":
        raise SystemExit("提交 writing_request 前必须提供需求记录定位信息，不能使用“未记录”")
    request_payload = {
        "handoff_event": "writing_request",
        "handoff_contract_version": contract_version,
        "project": str(project),
        "external_task_key": external_task_key,
        "request_text": args.request_text.strip(),
        "request_record_path": str(source),
        "request_record_locator": args.source_locator.strip(),
        "title_or_topic": title,
        "product_or_content_object": args.product_or_content_object.strip(),
        "topic_direction": args.topic_direction.strip(),
        "keywords": (args.keywords or "未提供").strip(),
        "outline": outline,
        "outline_status": args.outline_status,
        "target_language": args.target_language.strip(),
        "constraints": (args.constraints or "未提供").strip(),
        "original_writing_requirements": args.original_writing_requirements.strip(),
        "current_status": args.current_status.strip(),
        "writing_skill": args.writing_skill.strip(),
    }
    try:
        validate_event("writing_request", request_payload)
    except HandoffContractError as exc:
        raise SystemExit(f"writing_request合同校验失败：{exc}") from exc
    ledger = project / RELATIVE_LEDGER
    existing = next((row for row in load(ledger) if row["external_task_key"] == external_task_key), None)
    article_id = args.article_id.strip() if args.article_id else (existing or {}).get("article_id", "") or next_article_id(project, args.date)
    item = {
        "external_task_key": external_task_key,
        "source_path": str(source), "source_locator": args.source_locator.strip(),
        "source_sha256": sha256(source) if source.is_file() else "未记录",
        "article_id": article_id, "article_version": (existing or {}).get("article_version", "1"),
        "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "current_status": "已接收",
    }
    task_dir = project / "04_文章任务/10_进行中" / f"{article_id}_{title}"
    if existing:
        matches = list((project / "04_文章任务").glob(f"*/{article_id}_*/10_文章知识需求.md"))
        if len(matches) != 1:
            raise SystemExit(f"既有任务映射无法唯一定位文章目录：{article_id}")
        existing_request = read_text(matches[0])
        compared = {
            "标题": title,
            "关键词": args.keywords or "待补充",
            "目标语言": args.target_language,
            "特殊限制": args.constraints or "未提供",
            "大纲状态": args.outline_status,
            "原始写作请求": args.request_text.strip(),
            "产品或内容对象": args.product_or_content_object.strip(),
            "选题方向": args.topic_direction.strip(),
            "原始写作要求": args.original_writing_requirements.strip(),
            "当前状态": args.current_status.strip(),
            "写作Skill": args.writing_skill.strip(),
        }
        changed = [label for label, value in compared.items() if field(existing_request, label) != value]
        existing_outline = existing_request.split("## 大纲", 1)[1].split("## 随文章提交文件分类", 1)[0].strip() if "## 大纲" in existing_request else ""
        if existing_outline != outline:
            changed.append("大纲")
        if changed:
            raise SystemExit(
                "同一外部任务唯一键的已登记写作需求发生实质变化："
                + "、".join(changed)
                + "。不得静默覆盖10；请按文章版本归档合同更新需求后重新提交。"
            )
        record(ledger, item)
        update_integration_status(
            project,
            "writing_task_success",
            article_id=article_id,
            article_version=item["article_version"],
            external_task_key=item["external_task_key"],
            detail="桥接入口复用既有文章任务",
        )
        print(f"article_id={article_id}")
        print(f"task_dir={matches[0].parent}")
        print("ledger_action=reused")
        print(f"handoff_contract_version={contract_version}")
        print("handoff_event=writing_request")
        return
    if task_dir.exists():
        raise SystemExit(f"文章任务目录已存在：{task_dir}")
    task_dir.mkdir(parents=True)
    body = [
        "# 文章知识需求", "", f"- 文章ID：{article_id}", "- 当前版本：v1",
        f"- 模板版本：{TEMPLATE_VERSION}",
        f"- 交接合同版本：{contract_version}",
        f"- 标题：{title}", f"- 关键词：{args.keywords or '待补充'}",
        f"- 目标语言：{args.target_language}", f"- 特殊限制：{args.constraints or '未提供'}",
        f"- 大纲状态：{args.outline_status}",
        f"- 原始写作请求：{args.request_text}",
        f"- 产品或内容对象：{args.product_or_content_object}",
        f"- 选题方向：{args.topic_direction}",
        f"- 原始写作要求：{args.original_writing_requirements}",
        f"- 当前状态：{args.current_status}",
        f"- 写作Skill：{args.writing_skill}",
        "", "## 外部写作任务接入", "",
        "- 接入方式：已确认写作任务入口",
        f"- 外部任务唯一键：{external_task_key}",
        f"- 原任务文件：{source}", f"- 原任务位置或块键：{args.source_locator}",
        f"- 原任务SHA-256：{sha256(source) if source.is_file() else '未记录'}",
        f"- 读取时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        "- 字段映射结果：标题、关键词、目标语言、限制和简要大纲由桥接参数写入",
        "", "## 大纲", "", outline,
        "", "## 随文章提交文件分类", "",
        "| 文件名 | 原始路径 | SHA-256 | 文件性质 | 使用范围 | 处理结果 |",
        "|---|---|---|---|---|---|",
        "| 无 | 无 | 无 | 无随文文件 | 不适用 | 不适用 |",
    ]
    (task_dir / "10_文章知识需求.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    try:
        action = record(ledger, item)
    except Exception:
        shutil.rmtree(task_dir)
        raise
    print(f"article_id={article_id}")
    print(f"task_dir={task_dir}")
    print(f"ledger_action={action}")
    print(f"handoff_contract_version={contract_version}")
    print("handoff_event=writing_request")
    update_integration_status(
        project,
        "writing_task_success",
        article_id=article_id,
        article_version=item["article_version"],
        external_task_key=item["external_task_key"],
        detail="桥接入口已建立文章知识需求",
    )


def self_test() -> None:
    """Exercise the bridge against an isolated task record and contract."""
    with tempfile.TemporaryDirectory(prefix="mak-writing-bridge-") as temp:
        root = Path(temp) / "DEMO_测试知识库_v0.6"
        (root / "04_文章任务/10_进行中").mkdir(parents=True)
        version_entry = root / "01_工作台/30_版本与变更入口.md"
        version_entry.parent.mkdir(parents=True)
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
        feedback = root / "05_数据与审核/30_异常与待决定/40_Skill运行反馈/01_Skill反馈台账.md"
        feedback.parent.mkdir(parents=True)
        feedback.write_text(
            "# Skill反馈台账\n\n## 当前反馈\n\n"
            "| SKFB ID | 提出来源 | 类型 | 通俗说明 | 复现依据 | 当前阶段 | 维护负责人 | 关联项目对象入口 | 最近更新 |\n"
            "|---|---|---|---|---|---|---|---|---|\n\n"
            "## 反馈详情\n",
            encoding="utf-8",
        )
        request_record = Path(temp) / "写作需求.md"
        request_record.write_text("# 写作需求\n\n- 任务：DEMO-001\n", encoding="utf-8")
        args = argparse.Namespace(
            handoff_contract_version=current_version(),
            project=root,
            external_task_key="DEMO-001",
            source_path=request_record,
            source_locator="第1个任务块",
            title="测试文章",
            request_text="请写一篇测试文章",
            product_or_content_object="测试产品",
            topic_direction="测试方向",
            keywords="测试关键词",
            outline="- 说明测试问题\n- 给出安全建议",
            outline_status="已确认",
            target_language="中文",
            constraints="无",
            original_writing_requirements="测试写作规则",
            current_status="可准备知识",
            writing_skill="测试写作Skill",
            article_id=None,
            date="2026-09-04",
        )
        prepare(args)
        task_files = list((root / "04_文章任务/10_进行中").rglob("10_文章知识需求.md"))
        if len(task_files) != 1:
            raise AssertionError("self-test failed: task was not created exactly once")
        from template_contract import validate_file
        if validate_file(task_files[0]):
            raise AssertionError("self-test failed: generated 10 does not meet template contract")
        prepare(args)
        changed = argparse.Namespace(**vars(args))
        changed.outline = "- 已改变的基本结构"
        try:
            prepare(changed)
        except SystemExit as exc:
            if "实质变化" not in str(exc):
                raise
        else:
            raise AssertionError("self-test failed: changed request was silently reused")
        missing_record = argparse.Namespace(**vars(args))
        missing_record.external_task_key = "DEMO-002"
        missing_record.source_path = Path(temp) / "不存在.md"
        try:
            prepare(missing_record)
        except SystemExit as exc:
            if "已保存的文件" not in str(exc):
                raise
        else:
            raise AssertionError("self-test failed: missing request record was accepted")
    print(f"self-test=passed\nhandoff_contract_version={current_version()}")


def locate_task(project: Path, article_id: str, external_key: str) -> Path:
    candidates = []
    for path in (project / "04_文章任务").rglob("10_文章知识需求.md"):
        text = read_text(path)
        if article_id and field(text, "文章ID") == article_id:
            candidates.append(path.parent)
        elif external_key and field(text, "外部任务唯一键") == external_key:
            candidates.append(path.parent)
    if len(candidates) != 1:
        raise SystemExit(f"无法唯一确定文章任务（候选数：{len(candidates)}），不按标题猜测")
    return candidates[0]


def finalize(args: argparse.Namespace) -> None:
    try:
        contract_version = validate_version(args.handoff_contract_version)
    except HandoffContractError as exc:
        raise SystemExit(str(exc)) from exc
    project = args.project.resolve()
    sync_skill_version(project)
    source = args.final_path.resolve()
    if not source.is_file():
        raise SystemExit(f"终稿绝对路径必须指向文章正文文件（不能是目录）：{source}")
    if source.suffix.lower() in {".zip", ".7z", ".rar"}:
        raise SystemExit(
            f"final_path不能指向压缩交付包：{source}；请把文章正文文件作为final_path，"
            "压缩包另报final_package_path"
        )
    task = locate_task(project, args.article_id or "", args.external_task_key or "")
    request = read_text(task / "10_文章知识需求.md")
    recorded_contract_version = field(request, "交接合同版本")
    if recorded_contract_version and recorded_contract_version != contract_version:
        raise SystemExit(
            "writing_completed合同版本与10_文章知识需求.md不一致："
            f"{contract_version} != {recorded_contract_version}"
        )
    article_id = field(request, "文章ID")
    version = field(request, "当前版本") or field(request, "文章版本") or "v1"
    if not version.lower().startswith("v"):
        version = "v" + version
    source_text = read_article_text(source)
    if not source_text.strip():
        raise SystemExit(f"终稿正文为空或无法提取：{source}")
    title = field(source_text, "文章标题") or field(source_text, "最终标题") or field(request, "标题") or field(request, "文章标题") or source.stem
    completed = field(source_text, "完成日期") or datetime.fromtimestamp(source.stat().st_mtime).date().isoformat()
    try:
        validate_event(
            "writing_completed",
            {
                "handoff_event": "writing_completed",
                "handoff_contract_version": contract_version,
                "project_id": project_id_for_root(project),
                "final_path": str(source),
                "title": title,
                "completed_at": completed,
            },
        )
    except HandoffContractError as exc:
        raise SystemExit(f"writing_completed合同校验失败：{exc}") from exc
    # Keep the external file untouched; the normalized file is the sole input
    # to Faithfulness and always contains the knowledge identity metadata.
    normalized = [
        "# 最终文章", "", f"- 文章ID：{article_id}", f"- 文章版本：{version}",
        f"- 模板版本：{TEMPLATE_VERSION}",
        f"- 交接合同版本：{contract_version}",
        f"- 文章标题：{title}", f"- 完成日期：{completed}",
        f"- 外部终稿原路径：{source}", f"- 外部终稿SHA-256：{sha256(source)}", "",
        "## 最终正文", "", source_text,
    ]
    target = task / "40_最终文章.md"
    target.write_text("\n".join(normalized) + "\n", encoding="utf-8")
    update_integration_status(
        project,
        "final_received_success",
        article_id=article_id,
        article_version=version,
        detail=f"已规范化终稿：{source.name}",
    )
    print(f"article_id={article_id}")
    print(f"article_version={version}")
    print(f"handoff_contract_version={contract_version}")
    print("handoff_event=writing_completed")
    print(f"normalized_article={target}")
    print("next=run create_faithfulness_record.py with this 40 and the current 30/35")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument(
        "--handoff-contract-version",
        required=True,
        help=f"必须与当前安装合同一致；当前为 {current_version()}",
    )
    p.add_argument("--project", type=Path, required=True)
    p.add_argument("--external-task-key", required=True)
    p.add_argument("--source-path", type=Path, required=True)
    p.add_argument("--source-locator", default="未记录")
    p.add_argument("--title", required=True)
    p.add_argument("--request-text", required=True, help="本次原始写作请求；不得只留在对话上下文")
    p.add_argument("--product-or-content-object", default="未提供")
    p.add_argument("--topic-direction", default="未提供")
    p.add_argument("--keywords", default="")
    p.add_argument("--outline", default="")
    p.add_argument("--outline-status", default="")
    p.add_argument("--target-language", default="待补充")
    p.add_argument("--constraints", default="未提供")
    p.add_argument("--original-writing-requirements", required=True, help="本组当前有效的原始写作要求")
    p.add_argument("--current-status", default="可准备知识")
    p.add_argument("--writing-skill", required=True)
    p.add_argument("--article-id")
    p.add_argument("--date", default=date.today().isoformat())
    p.set_defaults(func=prepare)
    f = sub.add_parser("finalize")
    f.add_argument(
        "--handoff-contract-version",
        required=True,
        help=f"必须与当前安装合同一致；当前为 {current_version()}",
    )
    f.add_argument("--project", type=Path, required=True)
    f.add_argument("--final-path", type=Path, required=True)
    f.add_argument("--article-id")
    f.add_argument("--external-task-key")
    f.set_defaults(func=finalize)
    args = parser.parse_args()
    if args.command == "finalize" and not (args.article_id or args.external_task_key):
        parser.error("finalize 至少需要 --article-id 或 --external-task-key")
    try:
        args.func(args)
    except SystemExit as exc:
        # The bridge uses SystemExit for user-facing validation failures.
        # Mirror those failures into the project summary before re-raising.
        event = "writing_task_failure" if args.command == "prepare" else "final_received_failure"
        update_integration_status(
            args.project,
            event,
            article_id=getattr(args, "article_id", "") or "",
            external_task_key=getattr(args, "external_task_key", "") or "",
            error=str(exc),
        )
        raise
    except Exception as exc:
        event = "writing_task_failure" if args.command == "prepare" else "final_received_failure"
        update_integration_status(
            args.project,
            event,
            article_id=getattr(args, "article_id", "") or "",
            external_task_key=getattr(args, "external_task_key", "") or "",
            error=str(exc),
        )
        raise


if __name__ == "__main__":
    main()
