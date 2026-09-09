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
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

from archive_project_version import create_archive
from article_state import article_package_ready
from handoff_contract import HandoffContractError, current_version, validate_event, validate_version
from check_integration import project_id_for_root
from check_skill_update import check_project as check_skill_version
from record_writing_task import RELATIVE_LEDGER, load, record
from template_contract import TEMPLATE_VERSION
from update_integration_status import update as update_integration_status


ARTICLE_BODY_START = "<!-- ARTICLE_BODY_START -->"
ARTICLE_BODY_END = "<!-- ARTICLE_BODY_END -->"
EXTERNAL_BODY_HEADINGS = {"最终正文", "正文", "article body", "final article body"}
EXTERNAL_ADMIN_HEADINGS = {"最终文章", "final article", "article package", "delivery package"}
EXTERNAL_TRAILING_ADMIN_HEADINGS = {
    "seo metadata", "tdk", "metadata", "image plan", "image list", "delivery notes",
    "交付说明", "交付信息", "图片计划", "图片清单", "审核说明",
}
EXTERNAL_ADMIN_LABELS = {
    "文章id", "article id", "文章版本", "article version", "文章标题", "article title",
    "最终标题", "final title", "完成日期", "completed date", "completion date",
    "目标语言", "target language", "关键词", "keywords", "keyword", "slug",
    "meta title", "meta description", "交接合同版本", "handoff contract version",
}


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


def extract_external_body(value: str) -> str:
    """Keep only the writer's article body before creating managed 40."""
    start_count = value.count(ARTICLE_BODY_START)
    end_count = value.count(ARTICLE_BODY_END)
    if start_count or end_count:
        if start_count != 1 or end_count != 1:
            raise ValueError("外部终稿正文边界必须各出现一次")
        before, tail = value.split(ARTICLE_BODY_START, 1)
        body, after = tail.split(ARTICLE_BODY_END, 1)
        if value.index(ARTICLE_BODY_START) >= value.index(ARTICLE_BODY_END):
            raise ValueError("外部终稿正文边界顺序无效")
        if not body.strip():
            raise ValueError("外部终稿正文边界内没有正文")
        return body.strip()

    lines = value.splitlines()
    body_heading_index: int | None = None
    for index, raw in enumerate(lines):
        match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", raw)
        if match and re.sub(r"\s+", " ", match.group(1).strip().lower()) in EXTERNAL_BODY_HEADINGS:
            body_heading_index = index
            break
    if body_heading_index is not None:
        end_index = len(lines)
        for index in range(body_heading_index + 1, len(lines)):
            match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", lines[index])
            heading = re.sub(r"\s+", " ", match.group(1).strip().lower()) if match else ""
            if heading in EXTERNAL_TRAILING_ADMIN_HEADINGS:
                end_index = index
                break
        body = "\n".join(lines[body_heading_index + 1:end_index]).strip()
        if not body:
            raise ValueError("外部终稿正文标题后没有正文")
        return body

    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    prefix: list[str] = []
    if index < len(lines):
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", lines[index])
        normalized_heading = re.sub(r"\s+", " ", heading.group(1).strip().lower()) if heading else ""
        if normalized_heading in EXTERNAL_ADMIN_HEADINGS:
            index += 1
        elif heading:
            # Writer packages commonly put the real article H1 before a block
            # of Article ID / version / language fields. Keep that H1 while
            # removing the adjacent administrative block.
            prefix = [lines[index].strip(), ""]
            index += 1
    saw_admin = False
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            index += 1
            continue
        match = re.match(r"^\s*(?:[-*]\s*)?([^：:]{1,40})[：:]\s*.*$", raw)
        label = re.sub(r"\s+", " ", match.group(1).strip().lower()) if match else ""
        if match and label in EXTERNAL_ADMIN_LABELS:
            saw_admin = True
            index += 1
            continue
        break
    if saw_admin:
        body_lines = lines[index:]
        end_index = len(body_lines)
        for candidate_index, raw in enumerate(body_lines):
            match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", raw)
            heading = re.sub(r"\s+", " ", match.group(1).strip().lower()) if match else ""
            if heading in EXTERNAL_TRAILING_ADMIN_HEADINGS:
                end_index = candidate_index
                break
        body = "\n".join(prefix + body_lines[:end_index]).strip()
    else:
        body = value.strip()
    if not body:
        raise ValueError("外部终稿只包含管理字段，没有可审核正文")
    return body


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


REVISION_MODES = {"new_article", "knowledge_refresh_and_rewrite", "article_rewrite_only"}


def normalized_version(value: str) -> str:
    value = value.strip() or "v1"
    return value if value.lower().startswith("v") else "v" + value


def next_version(value: str) -> str:
    match = re.fullmatch(r"v(\d+)", normalized_version(value), re.IGNORECASE)
    if not match:
        raise ValueError(f"文章版本必须使用v加整数：{value}")
    return f"v{int(match.group(1)) + 1}"


def replace_field(text: str, label: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*[-*]\s*{re.escape(label)}[：:]\s*).*?$", re.MULTILINE)
    if not pattern.search(text):
        raise ValueError(f"文件缺少版本更新所需字段：{label}")
    return pattern.sub(lambda match: match.group(1) + value, text, count=1)


def append_request_field(text: str, label: str, value: str) -> str:
    pattern = re.compile(rf"^\s*[-*]\s*{re.escape(label)}[：:]", re.MULTILINE)
    if pattern.search(text):
        return replace_field(text, label, value)
    marker = "\n## 外部写作任务接入"
    if marker not in text:
        raise ValueError("10_文章知识需求.md缺少外部写作任务接入章节")
    return text.replace(marker, f"\n- {label}：{value}\n{marker}", 1)


def request_document(
    args: argparse.Namespace,
    *,
    article_id: str,
    article_version: str,
    contract_version: str,
    source: Path,
    title: str,
    revision_mode: str = "new_article",
    base_version: str = "不适用",
    archive_entry: str = "不适用",
) -> str:
    body = [
        "# 文章知识需求", "", f"- 文章ID：{article_id}", f"- 当前版本：{article_version}",
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
        f"- 任务模式：{revision_mode}",
        f"- 基线文章版本：{base_version}",
        f"- 旧版本归档入口：{archive_entry}",
        "", "## 外部写作任务接入", "",
        "- 接入方式：已确认写作任务入口",
        f"- 外部任务唯一键：{args.external_task_key.strip()}",
        f"- 原任务文件：{source}", f"- 原任务位置或块键：{args.source_locator}",
        f"- 原任务SHA-256：{sha256(source) if source.is_file() else '未记录'}",
        f"- 读取时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        "- 字段映射结果：标题、关键词、目标语言、限制和简要大纲由桥接参数写入",
        "", "## 大纲", "", args.outline.strip(),
        "", "## 随文章提交文件分类", "",
        "| 文件名 | 原始路径 | SHA-256 | 文件性质 | 使用范围 | 处理结果 |",
        "|---|---|---|---|---|---|",
        "| 无 | 无 | 无 | 无随文文件 | 不适用 | 不适用 |",
    ]
    return "\n".join(body) + "\n"


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


def current_task(project: Path, article_id: str) -> Path:
    matches = [
        path.parent
        for path in (project / "04_文章任务").glob(f"*/{article_id}_*/10_文章知识需求.md")
        if "90_归档" not in path.parts
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"既有任务映射无法唯一定位文章目录：{article_id}（候选数：{len(matches)}）。"
            "请修复任务身份后从当前节点重试；不得按标题猜测或临时覆盖定位逻辑。"
        )
    return matches[0]


def cleanup_transient_directory(path: Path) -> str | None:
    """Best-effort cleanup after a committed task switch.

    OneDrive and other sync providers can deny deletion after a rename even
    though the new current task is already committed. Cleanup failure must not
    roll back or invalidate that committed state; the validator ignores the
    named transient directory and a later maintenance run can remove it.
    """
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f"临时目录清理失败（不影响已提交任务）：{path}；{exc}"
    return None


def prepare_revision(
    args: argparse.Namespace,
    *,
    project: Path,
    existing: dict[str, str],
    contract_version: str,
    source: Path,
    title: str,
    outline: str,
) -> None:
    mode = args.revision_mode
    if mode not in {"knowledge_refresh_and_rewrite", "article_rewrite_only"}:
        raise SystemExit(f"无效重做模式：{mode}")
    article_id = existing["article_id"]
    task = current_task(project, article_id)
    request_path = task / "10_文章知识需求.md"
    request_text = read_text(request_path)
    old_outline = (
        request_text.split("## 大纲", 1)[1].split("## 随文章提交文件分类", 1)[0].strip()
        if "## 大纲" in request_text else ""
    )
    if old_outline != outline:
        raise SystemExit(
            "两个重做模式都默认锁定原简要大纲；当前提交的大纲与基线版本不同。"
            "请先单独确认大纲变更，再按知识重整模式建立新版本。"
        )
    if mode == "article_rewrite_only":
        locked_fields = {
            "标题": title,
            "关键词": args.keywords or "待补充",
            "目标语言": args.target_language,
            "特殊限制": args.constraints or "未提供",
            "产品或内容对象": args.product_or_content_object,
            "选题方向": args.topic_direction,
        }
        changed = [
            label for label, value in locked_fields.items()
            if field(request_text, label) != value
        ]
        if changed:
            raise SystemExit(
                "知识不变重写不能改变会影响知识范围的需求字段："
                + "、".join(changed)
                + "。请保持这些字段不变，或改用重新整理知识并重写模式。"
            )
    old_version = normalized_version(
        field(request_text, "当前版本") or existing.get("article_version", "v1")
    )
    new_version = next_version(old_version)
    if existing.get("article_version") and normalized_version(existing["article_version"]) != old_version:
        raise SystemExit("任务映射中的文章版本与当前10_文章知识需求.md不一致，不能开始重做")

    if mode == "article_rewrite_only":
        from template_contract import validate_task_templates

        required = [task / name for name in (
            "10_文章知识需求.md", "15_检索与知识准备记录.md",
            "20_文章前知识审核.md", "30_本篇知识库资料.md",
            "35_写作素材来源索引.md",
        )]
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise SystemExit("知识不变重写缺少可复用的当前文件：" + "、".join(missing))
        template_errors = validate_task_templates(task)
        if template_errors:
            raise SystemExit(
                "当前知识文件未通过模板与语义校验，不能按知识不变模式复用："
                + "；".join(template_errors[:8])
            )
        if not article_package_ready(task):
            raise SystemExit(
                "当前30/35未通过正式Claim、证据正文、映射范围与SHA-256整包校验，"
                "不能按知识不变模式复用；请改用重新整理知识并重写模式。"
            )

    archive = create_archive(
        project=project,
        target=task,
        kind="article",
        reason=("重新整理知识并按原大纲重写" if mode == "knowledge_refresh_and_rewrite" else "知识不变，仅按原大纲重写文章"),
        replacement_version=new_version,
    )
    target_state = "10_进行中" if mode == "knowledge_refresh_and_rewrite" else "20_等待终稿"
    destination = project / "04_文章任务" / target_state / task.name
    if destination.exists() and destination.resolve() != task.resolve():
        raise SystemExit(f"重做目标目录已存在，未替换当前任务：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".revision-{uuid.uuid4().hex[:8]}"
    retired = task.parent / f".retired-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    archive_entry = archive.relative_to(project).as_posix()
    new_request = request_document(
        args,
        article_id=article_id,
        article_version=new_version,
        contract_version=contract_version,
        source=source,
        title=title,
        revision_mode=mode,
        base_version=old_version,
        archive_entry=archive_entry,
    )
    (staging / "10_文章知识需求.md").write_text(new_request, encoding="utf-8")

    if mode == "article_rewrite_only":
        for name in (
            "15_检索与知识准备记录.md", "20_文章前知识审核.md",
            "30_本篇知识库资料.md", "35_写作素材来源索引.md",
        ):
            shutil.copy2(task / name, staging / name)
        for name in ("15_检索与知识准备记录.md", "20_文章前知识审核.md", "30_本篇知识库资料.md", "35_写作素材来源索引.md"):
            path = staging / name
            text = replace_field(read_text(path), "文章版本", new_version)
            path.write_text(text, encoding="utf-8")
        material_hash = sha256(staging / "30_本篇知识库资料.md")
        source_index = staging / "35_写作素材来源索引.md"
        source_index.write_text(
            replace_field(read_text(source_index), "写作素材SHA-256", material_hash),
            encoding="utf-8",
        )
        from template_contract import validate_task_templates

        staged_errors = validate_task_templates(staging)
        if staged_errors:
            shutil.rmtree(staging)
            raise SystemExit("知识不变重写的新版本文件校验失败：" + "；".join(staged_errors[:8]))
        if not article_package_ready(staging):
            shutil.rmtree(staging)
            raise SystemExit("知识不变重写的新版本30/35整包校验失败，未替换当前任务")

    task.rename(retired)
    try:
        staging.rename(destination)
        item = dict(existing)
        item.update(
            source_path=str(source),
            source_locator=args.source_locator.strip(),
            source_sha256=sha256(source),
            article_version=new_version.lstrip("vV"),
            imported_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            current_status=("需重新准备知识" if mode == "knowledge_refresh_and_rewrite" else "等待重写终稿"),
        )
        record(project / RELATIVE_LEDGER, item)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        if retired.exists():
            retired.rename(task)
        raise
    else:
        cleanup_warning = cleanup_transient_directory(retired)

    update_integration_status(
        project,
        "writing_task_success",
        article_id=article_id,
        article_version=new_version,
        external_task_key=existing["external_task_key"],
        detail=f"已按{mode}建立重做版本；旧版归档：{archive_entry}",
    )
    print(f"article_id={article_id}")
    print(f"article_version={new_version}")
    print(f"revision_mode={mode}")
    print(f"archive={archive}")
    print(f"task_dir={destination}")
    if cleanup_warning:
        print(f"cleanup_warning={cleanup_warning}")
    print(f"handoff_contract_version={contract_version}")
    if mode == "knowledge_refresh_and_rewrite":
        print("handoff_event=writing_request")
        print("next=重新执行六层检索、旧Claim复核、15/20/30/35生成与writing_ready门禁")
    else:
        print("handoff_event=writing_ready")
        print(f"knowledge_file={destination / '30_本篇知识库资料.md'}")
        print("next=调用原写作Skill完整重写；不得使用临时脚本替代")


def prepare(args: argparse.Namespace) -> None:
    try:
        contract_version = validate_version(args.handoff_contract_version)
    except HandoffContractError as exc:
        raise SystemExit(str(exc)) from exc
    project = args.project.resolve()
    sync_skill_version(project)
    revision_mode = (args.revision_mode or "new_article").strip()
    if revision_mode not in REVISION_MODES:
        raise SystemExit(f"无效revision_mode：{revision_mode}")
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
        "revision_mode": revision_mode,
    }
    if revision_mode != "new_article":
        request_payload["base_article_id"] = (args.article_id or "").strip()
        request_payload["base_article_version"] = (args.base_article_version or "").strip()
        if not request_payload["base_article_id"] or not request_payload["base_article_version"]:
            raise SystemExit("重做请求必须提供--article-id和--base-article-version")
    try:
        validate_event("writing_request", request_payload)
    except HandoffContractError as exc:
        raise SystemExit(f"writing_request合同校验失败：{exc}") from exc
    ledger = project / RELATIVE_LEDGER
    existing = next((row for row in load(ledger) if row["external_task_key"] == external_task_key), None)
    if revision_mode != "new_article":
        if not existing:
            raise SystemExit("重做请求没有找到既有外部任务映射；不得猜测文章身份")
        if existing.get("article_id") != request_payload["base_article_id"]:
            raise SystemExit("重做请求的article_id与既有任务映射不一致")
        prepare_revision(
            args,
            project=project,
            existing=existing,
            contract_version=contract_version,
            source=source,
            title=title,
            outline=outline,
        )
        return
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
        matches = [current_task(project, article_id) / "10_文章知识需求.md"]
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
    (task_dir / "10_文章知识需求.md").write_text(
        request_document(
            args,
            article_id=article_id,
            article_version="v1",
            contract_version=contract_version,
            source=source,
            title=title,
        ),
        encoding="utf-8",
    )
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
    real_writer_shape = (
        "# Test Article\n\n"
        "- Article ID: DEMO-ART-001\n"
        "- Article Version: v2\n"
        "- Article Title: Test Article\n"
        "- Completed Date: 2026-09-07\n"
        "- Target Language: English\n"
        "- Keywords: test, article\n\n"
        "Opening paragraph.\n\n## Main section\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "## SEO Metadata\n\n- Meta Title: should not be audited\n"
    )
    cleaned = extract_external_body(real_writer_shape)
    if "# Test Article" not in cleaned or "| 1 | 2 |" not in cleaned:
        raise AssertionError("self-test failed: article H1 or body table was removed")
    for admin_value in ("Article ID", "Article Version", "Target Language", "Keywords", "SEO Metadata"):
        if admin_value in cleaned:
            raise AssertionError(f"self-test failed: writer metadata remained in body: {admin_value}")
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
            revision_mode="new_article",
            base_article_version=None,
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
        task = task_files[0].parent
        article_id = field(read_text(task_files[0]), "文章ID")
        claim_id = "CLM-DEMO-PROD-001"
        formal = root / "03_正式知识/20_产品介绍/测试正式知识.md"
        formal.parent.mkdir(parents=True)
        formal.write_text(
            f"# 测试正式知识\n\n- Claim ID：{claim_id}\n- Claim状态：有效\n\n测试证据正文。\n",
            encoding="utf-8",
        )
        outline_rows = ("标题", "主问题", "说明测试问题", "给出安全建议")
        retrieval_rows = "\n".join(
            f"| {label} | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | 03_正式知识/20_产品介绍/测试正式知识.md | CF-001 | 1 | 1 | 无 | 纳入30 |"
            for label in outline_rows
        )
        (task / "15_检索与知识准备记录.md").write_text(
            "# 检索与知识准备记录\n\n"
            f"- 文章ID：{article_id}\n- 文章版本：v1\n- 模板版本：{TEMPLATE_VERSION}\n"
            "- 最近更新：2026-09-07\n- MAT依赖处理：无\n- 知识准备模式：new_article\n- 基线文章版本：不适用\n\n"
            "## 固定检索层状态\n\n| 检索层 | 当前状态 | 结果或未查原因 | 下一步 |\n|---|---|---|---|\n"
            "| 已有正式Claim | 已检索并命中 | 命中测试正式知识 | 进入候选事实核验 |\n\n"
            "## 来源命中记录\n\n| 知识问题 | 命中Claim/资料名称与入口 | 相关理由 | 处理结果 |\n|---|---|---|---|\n"
            f"| 测试文章所需事实 | {claim_id}；03_正式知识/20_产品介绍/测试正式知识.md | 直接回答大纲问题 | 复用当前Claim |\n\n"
            "## 候选事实处置明细\n\n| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n|---|---|---|---|---|\n"
            f"| CF-001 | 测试证据正文 | 03_正式知识/20_产品介绍/测试正式知识.md正文 | 复用已有Formal Claim | {claim_id} |\n\n"
            "## 旧Claim重新核验\n\n| 旧Claim ID | 旧版本归档入口 | 重新核对来源与位置 | 当前证据结论 | 当前归类模块 | 处置 | 依据 |\n|---|---|---|---|---|---|---|\n"
            "| 无 | 不适用 | 不适用 | 不适用 | 不适用 | 不适用 | 新文章无旧Claim |\n\n"
            "## 大纲逐项检索与候选事实覆盖\n\n| 大纲章节 | 六层检索范围与结果 | 命中来源与精确入口 | 候选事实ID | 候选事实数 | 已沉淀Claim数 | 未采用事实/缺口及原因 | 下一步 |\n|---|---|---|---|---:|---:|---|---|\n"
            f"{retrieval_rows}\n\n"
            "## MAT依赖与资料选择\n\n| MAT ID | 候选SRC ID | 文件名与稳定路径 | 关系/处理问题 | 决定 | 选取或排除范围 | 决定依据 | 决定方 | 当前状态 |\n|---|---|---|---|---|---|---|---|---|\n"
            "| 无 | 无 | 无 | 本篇无版本候选 | 无 | 无 | 无需选择 | Codex自动处理 | 不适用 |\n\n"
            "## 复杂资料处理与原件核对\n\n| 资料ID | 文件名与稳定路径 | 未索引内容/处理原因 | 与本篇关系判断 | 实际处理范围与方法 | MinerU/提取稿入口 | 原件核对位置与结论 | MAT/ANM/CUS入口 | 最终状态 |\n|---|---|---|---|---|---|---|---|---|\n"
            "| 无 | 无 | 本篇没有可能相关复杂资料 | 不适用 | 不适用 | 不适用 | 不适用 | 无 | 不适用 |\n",
            encoding="utf-8",
        )
        review_rows = "\n".join(
            f"| {label} | 1 | 1 | 1 | 充分 | 无 |" for label in outline_rows
        )
        coverage_rows = "\n".join(
            f"| {label} | {label}成立所需测试事实 | 已覆盖 | {claim_id} | 无 | 使用 |"
            for label in outline_rows
        )
        (task / "20_文章前知识审核.md").write_text(
            "# 文章前知识审核\n\n"
            f"- 文章ID：{article_id}\n- 文章版本：v1\n- 审核模板版本：{TEMPLATE_VERSION}\n"
            "- 审核日期：2026-09-07\n- 结论：自动通过\n- 可用Claim数：1\n- 客户来源：1\n- 外部来源：0\n"
            "- 明确排除：无\n- 未解决但不阻塞事项：无\n- 计划写作素材：30_本篇知识库资料.md\n- 计划写作素材来源索引：35_写作素材来源索引.md\n"
            "- 知识准备模式：new_article\n- 基线文章版本：不适用\n\n"
            "## 重做检索复核\n\n| 复核项 | 15记录入口 | 审核结论 | 阻塞或排除 |\n|---|---|---|---|\n"
            "| 六层重新检索 | 不适用 | 新文章不适用 | 无 |\n| 旧Claim逐条复核 | 不适用 | 新文章不适用 | 无 |\n"
            "| Claim重新归类 | 不适用 | 新文章不适用 | 无 |\n| 30/35重新生成 | 不适用 | 新文章不适用 | 无 |\n\n"
            "## 大纲知识覆盖检查\n\n| 大纲章节 | 知识问题 | 覆盖状态 | 已有证据/Claim | 缺口或治理事项 | 本篇处理 |\n|---|---|---|---|---|---|\n"
            f"{coverage_rows}\n\n"
            "## 知识准备充分性复核\n\n| 大纲章节 | 候选事实数 | 已沉淀Claim数 | 计划纳入30的事实块数 | 覆盖结论 | 未采用事实/缺口及入口 |\n|---|---:|---:|---:|---|---|\n"
            f"{review_rows}\n\n"
            "## 复杂资料与原件核对复核\n\n| 资料ID | 15处理记录入口 | 最终状态 | 对当前事实/Claim影响 | 本篇审核结论 |\n|---|---|---|---|---|\n"
            "| 无 | [[15_检索与知识准备记录.md#复杂资料处理与原件核对]] | 不适用 | 本篇无复杂资料 | 已复核，本篇无复杂资料 |\n\n"
            "## CUS / ANM检测结果\n\n| 检测对象 | 已检查信号与来源 | 分类结论 | 事项与证据入口 | 本篇处理 |\n|---|---|---|---|---|\n"
            "| CUS候选检测 | 已核对客户能力、规格、认证、案例、商业条件、公开授权，以及Formal Claim和来源范围 | 未触发 | 无 | 无需处理 |\n"
            "| ANM异常检测 | 已核对版本、定位、提取、数值、单位和外推信号 | 未触发 | 无 | 无需处理 |\n",
            encoding="utf-8",
        )
        material = task / "30_本篇知识库资料.md"
        material.write_text(
            "# 本篇写作素材包\n\n"
            f"- 文章ID：{article_id}\n- 文章版本：v1\n- 模板版本：{TEMPLATE_VERSION}\n- 资料视图：写作素材包\n"
            "- 资料版本：v1\n- 生成日期：2026-09-07\n- 目标语言：中文\n- 对应大纲：10_文章知识需求.md\n- 使用对象：本篇写作Skill\n\n"
            "## 一、可直接用于正文的事实\n\n### 测试事实\n\n- 事实素材：测试证据正文。\n\n### 证据正文（供Faithfulness核验）\n\n测试证据正文。\n\n"
            "## 二、可直接采用的英文表达\n\n| 使用场景/大纲章节 | 可采用表达 | 使用条件 |\n|---|---|---|\n| 无 | 无 | 本篇目标语言为中文 |\n\n"
            "## 三、可使用的数据表\n\n无\n\n"
            "## 四、按大纲使用\n\n| 大纲章节 | 可用事实/表达/数据表 | 推荐写作角度 |\n|---|---|---|\n"
            + "\n".join(f"| {label} | 测试事实 | 围绕已核验事实展开 |" for label in outline_rows)
            + "\n\n## 五、仅供生成控制（不得写入正文）\n\n不得扩写未提供的参数。\n\n"
            "## 六、缺少资料的章节及建议处理方式\n\n| 原大纲章节 | 建议处理 | 可保留的安全写作方向 |\n|---|---|---|\n| 无 | 无需处理 | 使用现有事实 |\n",
            encoding="utf-8",
        )
        evidence_line = read_text(material).splitlines().index("测试证据正文。") + 1
        (task / "35_写作素材来源索引.md").write_text(
            "# 写作素材来源索引\n\n"
            f"- 文章ID：{article_id}\n- 文章版本：v1\n- 模板版本：{TEMPLATE_VERSION}\n- 索引版本：v1\n- 生成日期：2026-09-07\n"
            f"- 对应写作素材：30_本篇知识库资料.md\n- 写作素材SHA-256：{sha256(material)}\n- 用途：内部来源映射，不交给写作Skill\n\n"
            "## 写作素材到正式知识映射\n\n| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |\n|---:|---:|---|---|---|---|---|\n"
            f"| {evidence_line} | {evidence_line} | 测试事实 | {claim_id} | 测试正式知识 | 03_正式知识/20_产品介绍/测试正式知识.md | 测试正式知识正文 |\n\n"
            "## 写作事实输入确认\n\n- 当前30是本篇唯一知识库事实附件。\n",
            encoding="utf-8",
        )
        from template_contract import validate_task_templates
        bundle_errors = validate_task_templates(task)
        if bundle_errors or not article_package_ready(task):
            raise AssertionError(f"self-test failed: valid reusable bundle was rejected: {bundle_errors}")

        rewrite = argparse.Namespace(**vars(args))
        rewrite.revision_mode = "article_rewrite_only"
        rewrite.article_id = article_id
        rewrite.base_article_version = "v1"
        rewrite.request_text = "知识不变，只按原大纲重写"
        prepare(rewrite)
        rewritten = list((root / "04_文章任务/20_等待终稿").rglob("10_文章知识需求.md"))
        if len(rewritten) != 1 or field(read_text(rewritten[0]), "当前版本") != "v2":
            raise AssertionError("self-test failed: article-only rewrite did not create v2")
        rewritten_task = rewritten[0].parent
        for name in ("15_检索与知识准备记录.md", "20_文章前知识审核.md", "30_本篇知识库资料.md", "35_写作素材来源索引.md"):
            if field(read_text(rewritten_task / name), "文章版本") != "v2":
                raise AssertionError(f"self-test failed: {name} version was not updated")
        expected_hash = sha256(rewritten_task / "30_本篇知识库资料.md")
        actual_hash = field(read_text(rewritten_task / "35_写作素材来源索引.md"), "写作素材SHA-256")
        if actual_hash != expected_hash:
            raise AssertionError("self-test failed: reused 35 does not match current 30 hash")
        if (rewritten_task / "40_最终文章.md").exists() or (rewritten_task / "50_文章知识使用与Faithfulness记录.md").exists():
            raise AssertionError("self-test failed: old final or Faithfulness current state leaked into rewrite")
        changed_scope = argparse.Namespace(**vars(rewrite))
        changed_scope.base_article_version = "v2"
        changed_scope.title = "已改变知识范围的标题"
        try:
            prepare(changed_scope)
        except SystemExit as exc:
            if "知识范围" not in str(exc):
                raise
        else:
            raise AssertionError("self-test failed: article-only rewrite accepted changed knowledge scope")

        refresh = argparse.Namespace(**vars(args))
        refresh.revision_mode = "knowledge_refresh_and_rewrite"
        refresh.article_id = article_id
        refresh.base_article_version = "v2"
        refresh.request_text = "按原大纲重新整理知识并重写"
        prepare(refresh)
        refreshed = list((root / "04_文章任务/10_进行中").rglob("10_文章知识需求.md"))
        if len(refreshed) != 1 or field(read_text(refreshed[0]), "当前版本") != "v3":
            raise AssertionError("self-test failed: knowledge refresh revision did not create v3")
        if field(read_text(refreshed[0]), "任务模式") != "knowledge_refresh_and_rewrite":
            raise AssertionError("self-test failed: revision mode was not persisted")
        if any((refreshed[0].parent / name).exists() for name in (
            "15_检索与知识准备记录.md", "20_文章前知识审核.md",
            "30_本篇知识库资料.md", "35_写作素材来源索引.md",
        )):
            raise AssertionError("self-test failed: knowledge refresh reused old knowledge files")
        archives = list((root / "04_文章任务/90_归档/10_文章历史版本").rglob("00_版本说明.md"))
        if len(archives) != 2:
            raise AssertionError("self-test failed: both rewrite modes did not archive prior versions")

        # A current task must win over same-ID historical snapshots.
        archived_task = root / "04_文章任务/90_归档/10_文章历史版本/DEMO-ART-001/v1_20260904-120000"
        archived_task.mkdir(parents=True)
        (archived_task / "10_文章知识需求.md").write_text(
            "# 文章知识需求\n\n- 文章ID：DEMO-ART-001\n- 外部任务唯一键：DEMO-001\n",
            encoding="utf-8",
        )
        current = root / "04_文章任务/40_已完成/DEMO-ART-001_测试文章"
        current.mkdir(parents=True)
        (current / "10_文章知识需求.md").write_text(
            "# 文章知识需求\n\n- 文章ID：DEMO-ART-001\n- 外部任务唯一键：DEMO-001\n",
            encoding="utf-8",
        )
        if locate_task(root, "DEMO-ART-001", "") != current:
            raise AssertionError("self-test failed: current task did not outrank archived task")

        # Sync-provider deletion denial is a warning, not a failed commit.
        denied = root / "04_文章任务/40_已完成/.retired-denied"
        denied.mkdir(parents=True)
        original_rmtree = shutil.rmtree
        try:
            def deny_retired(path, *args, **kwargs):
                if Path(path).name == denied.name:
                    raise PermissionError(5, "access denied")
                return original_rmtree(path, *args, **kwargs)
            shutil.rmtree = deny_retired
            warning = cleanup_transient_directory(denied)
        finally:
            shutil.rmtree = original_rmtree
        if not warning or not denied.is_dir():
            raise AssertionError("self-test failed: transient cleanup denial was not downgraded to warning")
    print(f"self-test=passed\nhandoff_contract_version={current_version()}")


def locate_task(project: Path, article_id: str, external_key: str) -> Path:
    candidates = []
    archived = []
    for path in (project / "04_文章任务").rglob("10_文章知识需求.md"):
        text = read_text(path)
        if article_id and field(text, "文章ID") == article_id:
            target = archived if "90_归档" in path.parts else candidates
            target.append(path.parent)
        elif external_key and field(text, "外部任务唯一键") == external_key:
            target = archived if "90_归档" in path.parts else candidates
            target.append(path.parent)
    if not candidates:
        candidates = archived
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
    raw_source_text = read_article_text(source)
    if not raw_source_text.strip():
        raise SystemExit(f"终稿正文为空或无法提取：{source}")
    title = (
        field(raw_source_text, "文章标题") or field(raw_source_text, "最终标题")
        or field(raw_source_text, "Article Title") or field(raw_source_text, "Final Title")
        or field(request, "标题") or field(request, "文章标题") or source.stem
    )
    completed = (
        field(raw_source_text, "完成日期") or field(raw_source_text, "Completed Date")
        or datetime.fromtimestamp(source.stat().st_mtime).date().isoformat()
    )
    try:
        source_text = extract_external_body(raw_source_text)
    except ValueError as exc:
        raise SystemExit(f"无法确定终稿正文边界：{exc}") from exc
    if ARTICLE_BODY_START in source_text or ARTICLE_BODY_END in source_text:
        raise SystemExit("终稿正文中残留嵌套正文边界，不能生成40_最终文章.md")
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
        "## 最终正文", "", ARTICLE_BODY_START, source_text, ARTICLE_BODY_END,
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
    p.add_argument(
        "--revision-mode",
        choices=sorted(REVISION_MODES),
        default="new_article",
        help="新文章或两种明确重做模式；重做时还要提供article-id和base-article-version",
    )
    p.add_argument("--base-article-version")
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
