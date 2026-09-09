#!/usr/bin/env python3
"""Build a read-only source inventory and searchable SQLite index."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from html.parser import HTMLParser
import re
import sqlite3
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from mat_lifecycle import current_table, formalize_scan_candidates
from source_topic_mapping import classify_role, derive_mappings, mapping_status_summary


TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
    ".xml", ".yaml", ".yml", ".ini", ".log",
}
HTML_EXTS = {".html", ".htm"}
OFFICE_EXTS = {".docx", ".pptx", ".xlsx"}
LEGACY_OFFICE_EXTS = {".doc", ".ppt", ".xls", ".wps", ".et", ".dps", ".rtf"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"}
DEFAULT_USE_SCOPE = "项目级通用（默认）"
DEFAULT_RELATED_ARTICLES = "全部文章（默认）"
FORMAL_MODULE_DIRS = {
    "公司概述": Path("03_正式知识/10_客户知识/10_公司概述"),
    "产品介绍": Path("03_正式知识/10_客户知识/20_产品介绍"),
    "解决方案": Path("03_正式知识/10_客户知识/30_解决方案"),
    "合作案例": Path("03_正式知识/10_客户知识/40_合作案例"),
    "行业知识与洞察": Path("03_正式知识/10_客户知识/50_行业知识与洞察"),
    "FAQ": Path("03_正式知识/10_客户知识/60_FAQ"),
    "其他": Path("03_正式知识/10_客户知识/70_其他"),
}


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_source_id(relative_path: str) -> str:
    value = hashlib.sha1(relative_path.casefold().encode("utf-8")).hexdigest()[:12]
    return f"SRC-{value.upper()}"


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def split_chunk(locator: str, text: str, maximum: int = 2200) -> list[tuple[str, str]]:
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= maximum:
        return [(locator, text)]
    result: list[tuple[str, str]] = []
    start = 0
    part = 1
    while start < len(text):
        end = min(len(text), start + maximum)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end), text.rfind(". ", start, end))
            if boundary > start + maximum // 2:
                end = boundary + 1
        result.append((f"{locator} · part {part}", text[start:end].strip()))
        start = end
        part += 1
    return [item for item in result if item[1]]


def xml_text(data: bytes, text_tag_suffix: str = "}t") -> list[str]:
    root = ET.fromstring(data)
    return [node.text or "" for node in root.iter() if node.tag.endswith(text_tag_suffix) and (node.text or "").strip()]


def extract_docx(path: Path) -> tuple[list[tuple[str, str]], bool]:
    chunks: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        root = ET.fromstring(archive.read("word/document.xml"))
        index = 0
        for paragraph in root.iter():
            if not paragraph.tag.endswith("}p"):
                continue
            text = "".join(node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")).strip()
            if text:
                index += 1
                chunks.extend(split_chunk(f"paragraph {index}", text))
        has_media = any(name.startswith("word/media/") and not name.endswith("/") for name in names)
    return chunks, has_media


def slide_number(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def extract_pptx(path: Path) -> tuple[list[tuple[str, str]], bool]:
    chunks: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        slides = sorted(
            (name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=slide_number,
        )
        for name in slides:
            text = "\n".join(xml_text(archive.read(name)))
            chunks.extend(split_chunk(f"slide {slide_number(name)}", text))
        has_media = any(name.startswith("ppt/media/") and not name.endswith("/") for name in names)
    return chunks, has_media


def extract_xlsx(path: Path) -> tuple[list[tuple[str, str]], bool]:
    chunks: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root:
                shared.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
        sheets = sorted(name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
        for sheet_index, name in enumerate(sheets, 1):
            root = ET.fromstring(archive.read(name))
            for row in (node for node in root.iter() if node.tag.endswith("}row")):
                values: list[str] = []
                for cell in (node for node in row if node.tag.endswith("}c")):
                    cell_type = cell.attrib.get("t")
                    value_node = next((node for node in cell if node.tag.endswith("}v")), None)
                    inline = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
                    value = inline
                    if value_node is not None and value_node.text is not None:
                        value = value_node.text
                        if cell_type == "s":
                            try:
                                value = shared[int(value)]
                            except (ValueError, IndexError):
                                pass
                    if value:
                        ref = cell.attrib.get("r", "")
                        values.append(f"{ref}={value}" if ref else value)
                if values:
                    row_no = row.attrib.get("r", "?")
                    chunks.extend(split_chunk(f"sheet {sheet_index}, row {row_no}", " | ".join(values)))
        has_media = any(name.startswith("xl/media/") and not name.endswith("/") for name in names)
    return chunks, has_media


def extract_pdf(path: Path) -> tuple[list[tuple[str, str]], str | None]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], "未安装PDF文字提取组件"
    try:
        reader = PdfReader(str(path))
        chunks: list[tuple[str, str]] = []
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            chunks.extend(split_chunk(f"page {index}", text))
        return chunks, None
    except Exception as exc:
        return [], f"PDF提取失败：{type(exc).__name__}：{exc}"


def extract_archive_listing(path: Path) -> tuple[list[tuple[str, str]], str | None]:
    if path.suffix.lower() != ".zip":
        return [], "archive registered without member extraction"
    try:
        with zipfile.ZipFile(path) as archive:
            members = [info.filename for info in archive.infolist() if not info.is_dir()]
        text = "\n".join(members)
        return split_chunk("archive member names", text), None
    except Exception as exc:
        return [], f"archive listing failed: {type(exc).__name__}: {exc}"


def office_container_counts(path: Path) -> tuple[int, int]:
    """Return media/structure and embedded-object counts without extracting payloads."""
    if path.suffix.lower() not in OFFICE_EXTS:
        return 0, 0
    with zipfile.ZipFile(path) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
    media_prefixes = (
        "word/media/", "ppt/media/", "xl/media/", "word/charts/",
        "ppt/charts/", "xl/charts/", "word/diagrams/", "ppt/diagrams/",
    )
    embedded_prefixes = ("word/embeddings/", "ppt/embeddings/", "xl/embeddings/")
    return (
        sum(name.startswith(media_prefixes) for name in names),
        sum(name.startswith(embedded_prefixes) for name in names),
    )


def media_duration(path: Path) -> str:
    """Read duration only when a cheap local method is available; never transcribe."""
    if path.suffix.lower() != ".wav":
        return "未取得"
    try:
        with wave.open(str(path), "rb") as stream:
            rate = stream.getframerate()
            seconds = stream.getnframes() / rate if rate else 0
        return f"{seconds:.1f}秒"
    except (wave.Error, OSError):
        return "未取得"


def possible_transcript(path: Path, all_paths: list[Path]) -> str:
    if path.suffix.lower() not in AUDIO_EXTS | VIDEO_EXTS:
        return "不适用"
    stem = normalized_version_key(path)
    candidates = []
    for other in all_paths:
        if other == path or other.suffix.lower() not in TEXT_EXTS | OFFICE_EXTS | {".pdf"}:
            continue
        other_key = normalized_version_key(other)
        if stem and other_key and (stem in other_key or other_key in stem):
            candidates.append(other.name)
    return "疑似存在：" + "、".join(candidates[:5]) if candidates else "未发现"


def sampled_terms(chunks: list[tuple[str, str]]) -> set[str]:
    if not chunks:
        return set()
    selected = [chunks[0], chunks[len(chunks) // 2], chunks[-1]]
    text = " ".join(item[1] for item in selected).casefold()
    return set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{3,}", text))


def term_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def extract_file(path: Path) -> tuple[list[tuple[str, str]], str, str, str]:
    ext = path.suffix.lower()
    chunks: list[tuple[str, str]] = []
    indexed_scope = ""
    excluded_scope = ""
    note = ""
    try:
        if ext in TEXT_EXTS:
            chunks = split_chunk("text", read_text(path))
            indexed_scope = "确定性文本提取"
        elif ext in HTML_EXTS:
            parser = TextHTMLParser()
            parser.feed(read_text(path))
            chunks = split_chunk("HTML可见文字", "\n".join(parser.parts))
            indexed_scope = "HTML可见文字"
            excluded_scope = "脚本、样式和交互状态"
        elif ext == ".docx":
            chunks, has_media = extract_docx(path)
            indexed_scope = "主文档段落和表格文字"
            excluded_scope = "页眉、页脚、批注和绘图文字"
            if has_media:
                excluded_scope += "；嵌入图片和对象"
        elif ext == ".pptx":
            chunks, has_media = extract_pptx(path)
            indexed_scope = "幻灯片文字"
            excluded_scope = "演讲者备注、母版和部分图表结构"
            if has_media:
                excluded_scope += "；嵌入图片、图表和对象"
        elif ext == ".xlsx":
            chunks, has_media = extract_xlsx(path)
            indexed_scope = "单元格值"
            excluded_scope = "公式、批注、样式和图表结构"
            if has_media:
                excluded_scope += "；嵌入图片和图表"
        elif ext == ".pdf":
            chunks, note = extract_pdf(path)
            indexed_scope = "含文字的PDF页面" if chunks else ""
            excluded_scope = "页面图像和无法提取的结构"
        elif ext in ARCHIVE_EXTS:
            chunks, note = extract_archive_listing(path)
            indexed_scope = "压缩包成员名称" if chunks else ""
            excluded_scope = "压缩包成员正文"
        elif ext in AUDIO_EXTS or ext in VIDEO_EXTS:
            note = "仅基础信息，内容未检索"
            excluded_scope = "音频/视频内容"
        elif ext in IMAGE_EXTS:
            note = "仅图像元数据"
            excluded_scope = "视觉内容"
        elif ext in LEGACY_OFFICE_EXTS:
            note = "旧版Office格式，需要专员批准处理"
            excluded_scope = "文档正文"
        else:
            note = "格式不支持，仅登记文件信息"
            excluded_scope = "文件正文"
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        note = f"提取失败：{type(exc).__name__}：{exc}"
        chunks = []

    if chunks:
        status = "部分内容可搜索" if excluded_scope else "全文文字可搜索"
    elif ext in AUDIO_EXTS | VIDEO_EXTS | IMAGE_EXTS | ARCHIVE_EXTS:
        status = "仅文件信息可搜索"
    else:
        status = "未建立正文索引"
    return chunks, status, indexed_scope, excluded_scope or note


def normalized_version_key(path: Path) -> str:
    value = path.stem.casefold()
    value = re.sub(r"(?:copy|副本|final|最终|最新版|new|old)", "", value)
    value = re.sub(r"(?:v(?:er)?\.?\s*)?\d+(?:\.\d+){0,3}", "", value)
    value = re.sub(r"20\d{2}[-_.]?\d{1,2}(?:[-_.]?\d{1,2})?", "", value)
    value = re.sub(r"[\s_\-().（）]+", "", value)
    return value


def create_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        DROP TABLE IF EXISTS metadata;
        DROP TABLE IF EXISTS sources;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS chunks_fts;
        DROP TABLE IF EXISTS relationships;
        DROP TABLE IF EXISTS source_topic_mappings;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE sources (
            source_id TEXT PRIMARY KEY,
            relative_path TEXT NOT NULL,
            absolute_path TEXT NOT NULL,
            extension TEXT,
            size_bytes INTEGER NOT NULL,
            modified_time TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            searchability TEXT NOT NULL,
            indexed_scope TEXT,
            excluded_scope TEXT,
            duplicate_of TEXT,
            relation_note TEXT,
            mat_candidate TEXT,
            mat_id TEXT,
            mat_disposition TEXT,
            media_duration TEXT,
            transcript_status TEXT,
            office_media_count INTEGER,
            office_embedded_count INTEGER,
            source_role TEXT NOT NULL,
            role_basis TEXT NOT NULL,
            role_confidence TEXT NOT NULL,
            role_status TEXT NOT NULL
        );
        CREATE TABLE chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            locator TEXT NOT NULL,
            text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            source_id UNINDEXED,
            locator UNINDEXED,
            text,
            tokenize='unicode61'
        );
        CREATE TABLE relationships (
            source_id TEXT NOT NULL,
            related_source_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            basis TEXT NOT NULL
        );
        CREATE TABLE source_topic_mappings (
            source_id TEXT NOT NULL,
            module TEXT NOT NULL,
            topic TEXT NOT NULL,
            basis TEXT NOT NULL,
            confidence TEXT NOT NULL,
            status TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            PRIMARY KEY (source_id, module, topic)
        );
        """
    )
    return connection


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def load_ledger_human_fields(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header: list[str] = []
    result: dict[str, dict[str, str]] = {}
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip().replace("\\|", "|") for cell in line.strip().strip("|").split("|")]
        if not header:
            header = cells
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        source_id = row.get("资料ID", "")
        if source_id:
            result[source_id] = {
                "sha256": row.get("SHA-256", ""),
                "relative_path": row.get("原始相对路径", ""),
                "size_bytes": row.get("大小", ""),
                "modified_time": row.get("修改时间", ""),
                "use_scope": row.get("使用范围", ""),
                "related_articles": row.get("关联文章", ""),
                "handling": row.get("当前处理状态", ""),
                "mat": row.get("MAT", ""),
                "mat_disposition": row.get("MAT处置说明", ""),
                "source_role": row.get("资料角色", ""),
            }
    return result


def load_ledger_topic_mappings(path: Path) -> dict[str, list[dict[str, str]]]:
    """Read the generated mapping table so verified mappings survive index rebuilds."""
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == "## 来源主题与模块候选")
    except StopIteration:
        return {}
    header_index = next(
        (index for index in range(start + 1, len(lines)) if lines[index].strip().startswith("|") and "资料ID/资料名称" in lines[index]),
        None,
    )
    if header_index is None:
        return {}
    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    result: dict[str, list[dict[str, str]]] = {}
    for line in lines[header_index + 2:]:
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip().replace("\\|", "|") for cell in line.strip().strip("|").split("|")]
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        source_id = row.get("资料ID/资料名称", "").split("，", 1)[0].strip()
        if source_id:
            result.setdefault(source_id, []).append(row)
    return result


def verified_modules_for_source(project: Path, source_id: str, absolute_path: Path) -> set[str]:
    """Return modules whose current Formal Claims explicitly cite this source."""
    identifiers = (source_id, str(absolute_path), absolute_path.as_posix())
    result: set[str] = set()
    for module, relative in FORMAL_MODULE_DIRS.items():
        directory = project / relative
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.md"):
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if any(identifier and identifier in text for identifier in identifiers):
                result.add(module)
                break
    return result


def resolve_source_scope(preserved: dict[str, str]) -> tuple[str, str]:
    return (
        preserved.get("use_scope", "") or DEFAULT_USE_SCOPE,
        preserved.get("related_articles", "") or DEFAULT_RELATED_ARTICLES,
    )


def load_exclusions(path: Path) -> dict[str, dict[str, str]]:
    """Load project-level body exclusions keyed by source ID."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"排除清单无法读取：{path}：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SystemExit(f"排除清单schema_version必须为1：{path}")
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise SystemExit(f"排除清单entries必须是数组：{path}")
    result: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit(f"排除清单存在非对象条目：{path}")
        source_id = str(entry.get("source_id", "")).strip()
        relative_path = str(entry.get("relative_path", "")).replace("\\", "/").strip()
        checksum = str(entry.get("sha256", "")).strip().lower()
        reason = str(entry.get("reason", "")).strip()
        if not source_id or not relative_path or not re.fullmatch(r"[0-9a-f]{64}", checksum) or not reason:
            raise SystemExit(f"排除清单条目字段不完整：{path}：{entry}")
        if entry.get("exclude_body") is not True:
            continue
        if source_id in result:
            raise SystemExit(f"排除清单存在重复source_id：{source_id}")
        result[source_id] = {
            "relative_path": relative_path,
            "sha256": checksum,
            "reason": reason,
        }
    return result


def append_source_version_events(
    path: Path,
    events: list[dict[str, str | int]],
) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    known: set[str] = set()
    if path.is_file():
        with path.open("r", encoding="utf-8-sig") as stream:
            for raw in stream:
                if not raw.strip():
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"源资料版本记录不是有效JSONL：{path}") from exc
                event_id = str(item.get("event_id", ""))
                if event_id:
                    known.add(event_id)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for event in events:
            event_id = str(event["event_id"])
            if event_id in known:
                continue
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            known.add(event_id)


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v05-source-version-test-") as temp:
        ledger = Path(temp) / "ledger.md"
        if resolve_source_scope({}) != (DEFAULT_USE_SCOPE, DEFAULT_RELATED_ARTICLES):
            print(json.dumps({"ok": False, "stage": "source-scope-defaults"}, ensure_ascii=False))
            return 1
        ledger.write_text(
            "| 资料ID | 原始相对路径 | SHA-256 | 大小 | 修改时间 | 使用范围 | 关联文章 | 当前处理状态 | MAT |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| SRC-SELFTEST | sample.txt | " + "a" * 64 + " | 1 | 2026-08-19 | 仅本篇：ART-001 | [[ART-001]] | 已登记 | |\n",
            encoding="utf-8",
        )
        human_fields = load_ledger_human_fields(ledger).get("SRC-SELFTEST", {})
        if resolve_source_scope(human_fields) != ("仅本篇：ART-001", "[[ART-001]]"):
            print(json.dumps({"ok": False, "stage": "source-scope-preservation", "fields": human_fields}, ensure_ascii=False))
            return 1
        mapping_ledger = Path(temp) / "mapping-ledger.md"
        mapping_ledger.write_text(
            "## 来源主题与模块候选\n\n"
            "| 资料ID/资料名称 | 资料角色 | 标准模块候选 | 主题候选 | 判断依据 | 归类状态 |\n"
            "|---|---|---|---|---|---|\n"
            "| SRC-SELFTEST，示例资料.docx | 客户事实资料 | 产品介绍 | 示例产品 | 人工核验原件 | 已核验 |\n",
            encoding="utf-8",
        )
        preserved_mapping = load_ledger_topic_mappings(mapping_ledger)
        if preserved_mapping.get("SRC-SELFTEST", [{}])[0].get("归类状态") != "已核验":
            print(json.dumps({"ok": False, "stage": "source-topic-preservation"}, ensure_ascii=False))
            return 1
        factual = Path(temp) / "Catalog for Watch Box 2026.pdf"
        role = classify_role(factual, [("page 1", "Product catalog with packaging box specifications and materials")])
        mappings = derive_mappings(factual, [("page 1", "Product catalog with packaging box specifications and materials")], role)
        if role["role"] != "客户事实资料" or not any(item["module"] == "产品介绍" for item in mappings):
            print(json.dumps({"ok": False, "stage": "source-topic-product", "role": role, "mappings": mappings}, ensure_ascii=False))
            return 1
        operational = Path(temp) / "杰睿文章要求.docx"
        role = classify_role(operational, [("paragraph 1", "SEO、CTA与文章内链要求")])
        if role["role"] != "写作运营资料" or derive_mappings(operational, [], role):
            print(json.dumps({"ok": False, "stage": "source-role-exclusion", "role": role}, ensure_ascii=False))
            return 1
        project = Path(temp) / "TEST_Project"
        mat_path = project / "05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md"
        mat_path.parent.mkdir(parents=True, exist_ok=True)
        mat_path.write_text(
            "# 源资料处理台账\n\n## 当前事项\n\n"
            "| MAT ID | 事项名称 | 代表文件/资料范围 | 资料数量 | 通俗问题 | 当前文章影响 | 当前阶段 | 下一责任人/动作 | 重开条件 | 详情入口 | 最近更新 |\n"
            "|---|---|---|---:|---|---|---|---|---|---|---|\n\n## 事项详情\n",
            encoding="utf-8",
        )
        candidate_rows = [{
            "source_id": "SRC-MATSELF",
            "relative_path": "资料/sample.zip",
            "extension": "zip",
            "mat_candidate": "建议建立MAT",
            "duplicate_of": "",
            "relation_note": "",
            "searchability": "仅文件信息可搜索",
            "office_embedded_count": 0,
        }]
        first_map, _ = formalize_scan_candidates(project, candidate_rows, {}, "2026-08-25T00:00:00+08:00")
        second_map, _ = formalize_scan_candidates(project, candidate_rows, {"SRC-MATSELF": {"mat": first_map["SRC-MATSELF"]}}, "2026-08-25T00:00:00+08:00")
        table = current_table(mat_path)
        if first_map.get("SRC-MATSELF") != "TEST-MAT-001" or second_map != first_map or table is None:
            print(json.dumps({"ok": False, "stage": "mat-formalization", "first": first_map, "second": second_map}, ensure_ascii=False))
            return 1
        ids = [row[0] for row in table["rows"] if row and row[0].endswith("-MAT-001")]
        if ids != ["TEST-MAT-001"]:
            print(json.dumps({"ok": False, "stage": "mat-idempotence", "ids": ids}, ensure_ascii=False))
            return 1
        history = Path(temp) / "source_version_history.jsonl"
        event = {
            "schema_version": 1,
            "event_id": "SRCVER-SELFTEST",
            "detected_at": "2026-08-19T00:00:00+00:00",
            "source_id": "SRC-SELFTEST",
            "relative_path": "sample.txt",
            "old_sha256": "a" * 64,
            "new_sha256": "b" * 64,
            "old_size_bytes": 1,
            "new_size_bytes": 2,
            "old_modified_time": "2026-08-18T00:00:00+00:00",
            "new_modified_time": "2026-08-19T00:00:00+00:00",
            "old_content_retained": False,
        }
        append_source_version_events(history, [event])
        append_source_version_events(history, [event])
        rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines() if line]
        if rows != [event]:
            print(json.dumps({"ok": False, "stage": "source-version-history", "rows": rows}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--description", type=Path)
    parser.add_argument(
        "--exclusions",
        type=Path,
        help="项目级正文排除清单；默认使用DB所在目录的source-index-exclusions.json",
    )
    parser.add_argument(
        "--version-history",
        type=Path,
        help="同一路径源文件旧/新指纹JSONL；默认写入项目的固定版本归档目录",
    )
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(run_self_test())
    if not args.source_root or not args.db or not args.ledger or not args.description:
        raise SystemExit("--source-root, --db, --ledger and --description are required")

    source_root = args.source_root.resolve()
    db_path = args.db.resolve()
    ledger_path = args.ledger.resolve()
    description_path = args.description.resolve()
    exclusions_path = (args.exclusions or (db_path.parent / "source-index-exclusions.json")).resolve()
    default_version_history = (
        db_path.parent.parent
        / "05_数据与审核/60_版本归档/40_源资料版本记录/source_version_history.jsonl"
        if db_path.parent.name == "02_源资料"
        else db_path.parent / "source_version_history.jsonl"
    )
    version_history_path = (args.version_history or default_version_history).resolve()
    if not source_root.is_dir():
        raise SystemExit(f"Source root not found: {source_root}")

    existing_human_fields = load_ledger_human_fields(ledger_path)
    existing_topic_mappings = load_ledger_topic_mappings(ledger_path)
    exclusions = load_exclusions(exclusions_path)
    excluded_outputs = {db_path, ledger_path, description_path, version_history_path}
    paths = sorted(
        (
            path for path in source_root.rglob("*")
            if path.is_file()
            and path.resolve() not in excluded_outputs
            and not any(part.startswith(".") for part in path.relative_to(source_root).parts)
        ),
        key=lambda path: str(path.relative_to(source_root)).casefold(),
    )

    connection = create_database(db_path)
    built_at = utc_now()
    connection.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        (
            ("schema_version", "1.4"),
            ("built_at", built_at),
            ("source_root", str(source_root)),
            ("exclusions_path", str(exclusions_path)),
        ),
    )

    project_root = db_path.parent.parent if db_path.parent.name == "02_源资料" else db_path.parent
    rows: list[dict[str, str | int]] = []
    rows_by_id: dict[str, dict[str, str | int]] = {}
    first_by_hash: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    samples_by_id: dict[str, set[str]] = {}
    mappings_by_id: dict[str, list[dict[str, str]]] = {}
    for path in paths:
        relative = path.relative_to(source_root).as_posix()
        source_id = stable_source_id(relative)
        stat = path.stat()
        checksum = sha256_file(path)
        duplicate_of = first_by_hash.get(checksum, "")
        if not duplicate_of:
            first_by_hash[checksum] = source_id
        exclusion = exclusions.get(source_id)
        exclusion_state = ""
        if exclusion:
            path_matches = exclusion["relative_path"].casefold() == relative.casefold()
            hash_matches = exclusion["sha256"] == checksum.lower()
            if path_matches and hash_matches:
                exclusion_state = "approved"
            else:
                exclusion_state = "stale"
        chunks: list[tuple[str, str]] = []
        if exclusion_state == "approved":
            status = "仅文件信息可搜索"
            indexed_scope = "仅登记文件身份、路径、格式、大小、修改时间和SHA-256"
            excluded_scope = f"正文排除：{exclusion['reason']}"
        elif exclusion_state == "stale":
            status = "未建立正文索引"
            indexed_scope = ""
            excluded_scope = (
                f"排除清单未匹配当前相对路径或SHA-256，正文暂不索引，需重新确认"
                f"（清单路径：{exclusion['relative_path']}，清单SHA-256：{exclusion['sha256']}）"
            )
            duplicate_of = ""
        elif duplicate_of:
            original = rows_by_id[duplicate_of]
            status = str(original["searchability"])
            indexed_scope = f"复用完全重复资料 {duplicate_of} 的索引"
            excluded_scope = str(original["excluded_scope"])
        else:
            chunks, status, indexed_scope, excluded_scope = extract_file(path)

        ext = path.suffix.lower()
        try:
            office_media_count, office_embedded_count = office_container_counts(path)
        except (OSError, KeyError, zipfile.BadZipFile):
            office_media_count, office_embedded_count = 0, 0
        duration = media_duration(path) if ext in AUDIO_EXTS | VIDEO_EXTS else "不适用"
        transcript_status = possible_transcript(path, paths)
        complex_material = (
            ext in AUDIO_EXTS
            or ext in VIDEO_EXTS
            or ext in ARCHIVE_EXTS
            or ext in LEGACY_OFFICE_EXTS
            or status == "未建立正文索引"
            or office_embedded_count > 0
        )
        mat_candidate = "建议建立MAT" if complex_material and not duplicate_of else ""
        verified_modules = verified_modules_for_source(project_root, source_id, path.resolve())
        previous_same_file = bool(
            existing_human_fields.get(source_id, {}).get("sha256")
            and existing_human_fields[source_id]["sha256"].lower() == checksum.lower()
        )
        previous_mappings = existing_topic_mappings.get(source_id, [])
        if previous_same_file and previous_mappings and any(item.get("归类状态", "").startswith("已核验") for item in previous_mappings):
            role = {
                "role": existing_human_fields.get(source_id, {}).get("source_role", "客户事实资料"),
                "basis": "沿用来源台账已核验资料角色",
                "confidence": "高",
                "status": "已核验",
            }
            topic_mappings = [
                {
                    "module": item.get("标准模块候选", ""),
                    "topic": item.get("主题候选", ""),
                    "basis": item.get("判断依据", "") or "来源台账已核验",
                    "confidence": "高",
                    "status": "已核验",
                }
                for item in previous_mappings
                if item.get("标准模块候选", "")
            ]
        elif duplicate_of and not verified_modules:
            role = {
                key: str(rows_by_id[duplicate_of][key])
                for key in ("source_role", "role_basis", "role_confidence", "role_status")
            }
            role = {
                "role": role["source_role"],
                "basis": "完全重复，复用代表资料的资料角色判断",
                "confidence": role["role_confidence"],
                "status": role["role_status"],
            }
            topic_mappings = [dict(item) for item in mappings_by_id.get(duplicate_of, [])]
        else:
            role = classify_role(path, chunks, bool(verified_modules))
            topic_mappings = derive_mappings(path, chunks, role, verified_modules)
        row = {
            "source_id": source_id,
            "relative_path": relative,
            "absolute_path": str(path.resolve()),
            "extension": ext.lstrip(".") or "(none)",
            "size_bytes": stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            "sha256": checksum,
            "searchability": status,
            "indexed_scope": indexed_scope,
            "excluded_scope": excluded_scope,
            "duplicate_of": duplicate_of,
            "relation_note": "",
            "mat_candidate": mat_candidate,
            "media_duration": duration,
            "transcript_status": transcript_status,
            "office_media_count": office_media_count,
            "office_embedded_count": office_embedded_count,
            "source_role": role["role"],
            "role_basis": role["basis"],
            "role_confidence": role["confidence"],
            "role_status": role["status"],
        }
        rows.append(row)
        rows_by_id[source_id] = row
        mappings_by_id[source_id] = topic_mappings
        connection.execute(
            """
            INSERT INTO sources(
                source_id, relative_path, absolute_path, extension, size_bytes,
                modified_time, sha256, searchability, indexed_scope, excluded_scope,
                duplicate_of, relation_note, mat_candidate, mat_id, mat_disposition, media_duration,
                transcript_status, office_media_count, office_embedded_count,
                source_role, role_basis, role_confidence, role_status
            ) VALUES (
                :source_id, :relative_path, :absolute_path, :extension, :size_bytes,
                :modified_time, :sha256, :searchability, :indexed_scope, :excluded_scope,
                :duplicate_of, :relation_note, :mat_candidate, NULL, NULL, :media_duration,
                :transcript_status, :office_media_count, :office_embedded_count,
                :source_role, :role_basis, :role_confidence, :role_status
            )
            """,
            row,
        )
        for mapping in topic_mappings:
            connection.execute(
                """
                INSERT INTO source_topic_mappings(
                    source_id, module, topic, basis, confidence, status, source_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id, mapping["module"], mapping["topic"], mapping["basis"],
                    mapping["confidence"], mapping["status"], checksum,
                ),
            )
        if not duplicate_of and exclusion_state not in {"approved", "stale"}:
            for locator, text in chunks:
                connection.execute(
                    "INSERT INTO chunks(source_id, locator, text) VALUES (?, ?, ?)",
                    (source_id, locator, text),
                )
                connection.execute(
                    "INSERT INTO chunks_fts(source_id, locator, text) VALUES (?, ?, ?)",
                    (source_id, locator, text),
                )
        samples_by_id[source_id] = sampled_terms(chunks) if not duplicate_of else samples_by_id.get(duplicate_of, set())
        key = normalized_version_key(path)
        if key:
            groups.setdefault(key, []).append(source_id)

    by_id = {str(row["source_id"]): row for row in rows}
    for members in groups.values():
        members = list(dict.fromkeys(
            str(by_id[item]["duplicate_of"] or item) for item in members
        ))
        distinct_hashes = {str(by_id[item]["sha256"]) for item in members}
        if len(members) < 2 or len(distinct_hashes) < 2:
            continue
        qualified_pairs: set[tuple[str, str]] = set()
        for index, source_id in enumerate(members):
            for other in members[index + 1:]:
                left = by_id[source_id]
                right = by_id[other]
                if left["sha256"] == right["sha256"]:
                    continue
                overlap = term_overlap(samples_by_id.get(source_id, set()), samples_by_id.get(other, set()))
                maximum_size = max(int(left["size_bytes"]), int(right["size_bytes"]))
                structure_signal = (
                    left["extension"] == right["extension"]
                    and maximum_size > 0
                    and min(int(left["size_bytes"]), int(right["size_bytes"])) / maximum_size >= 0.85
                )
                if overlap >= 0.10 or structure_signal:
                    qualified_pairs.add((source_id, other))
        for source_id in members:
            related = sorted({
                right if left == source_id else left
                for left, right in qualified_pairs
                if source_id in {left, right}
            })
            if not related:
                continue
            note = "疑似跨格式或版本关系：" + ", ".join(related)
            by_id[source_id]["relation_note"] = note
            by_id[source_id]["mat_candidate"] = "建议建立MAT"
            connection.execute(
                "UPDATE sources SET relation_note=?, mat_candidate=? WHERE source_id=?",
                (note, "建议建立MAT", source_id),
            )
            for other in related:
                connection.execute(
                    "INSERT INTO relationships VALUES (?, ?, ?, ?)",
                    (
                        source_id, other, "疑似版本或内容关系",
                        "规范化文件名相同，且文本样本重合或同格式结构/大小接近；SHA-256不同",
                    ),
                )

    connection.commit()

    mat_mapping, mat_dispositions = formalize_scan_candidates(
        project_root,
        rows,
        existing_human_fields,
        built_at,
    )
    for row in rows:
        source_id = str(row["source_id"])
        mat_id = mat_mapping.get(source_id, "")
        disposition = mat_dispositions.get(source_id, "")
        connection.execute(
            "UPDATE sources SET mat_id=?, mat_disposition=? WHERE source_id=?",
            (mat_id, disposition, source_id),
        )
    connection.commit()
    connection.close()

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_lines = [
        "# 源资料与可检索性台账",
        "",
        f"- 源资料根路径：{source_root}",
        f"- 最近扫描：{built_at}",
        f"- 机器索引：[[{db_path.name}]]",
        "",
        "| 资料ID | 资料名称 | 原始相对路径 | 格式 | 大小 | 修改时间 | SHA-256 | 可检索状态 | 已索引范围 | 未索引内容 | 媒体时长 | 疑似文字稿 | Office媒体/结构数 | Office嵌入对象数 | 重复/版本关系 | 使用范围 | 关联文章 | 当前处理状态 | MAT | MAT处置说明 |",
        "|---|---|---|---:|---:|---|---|---|---|---|---|---|---:|---:|---|---|---|---|---|---|",
    ]
    for row in rows:
        relationship = str(row["relation_note"])
        if row["duplicate_of"]:
            relationship = f"完全重复→{row['duplicate_of']}"
        preserved = existing_human_fields.get(str(row["source_id"]), {})
        use_scope, related_articles = resolve_source_scope(preserved)
        handling = preserved.get("handling", "") or str(row["mat_candidate"] or "已登记")
        mat_id = mat_mapping.get(str(row["source_id"]), preserved.get("mat", ""))
        mat_disposition = preserved.get("mat_disposition", "") or mat_dispositions.get(str(row["source_id"]), "")
        if row["mat_candidate"] and handling in {"已登记", "建议建立MAT"} and mat_id:
            handling = f"已建立正式MAT：{mat_id}"
        if not row["mat_candidate"] and handling == "建议建立MAT" and not mat_id:
            handling = "已登记"
        if preserved.get("sha256") and preserved["sha256"] != str(row["sha256"]):
            handling = "资料已变化，需复核"
        fields = (
            row["source_id"],
            Path(str(row["relative_path"])).name,
            row["relative_path"],
            row["extension"],
            row["size_bytes"],
            row["modified_time"],
            row["sha256"],
            row["searchability"],
            row["indexed_scope"],
            row["excluded_scope"],
            row["media_duration"],
            row["transcript_status"],
            row["office_media_count"],
            row["office_embedded_count"],
            relationship,
            use_scope,
            related_articles,
            handling,
            mat_id,
            mat_disposition,
        )
        ledger_lines.append("| " + " | ".join(markdown_escape(str(value)) for value in fields) + " |")
    ledger_lines.extend([
        "",
        "## 来源主题与模块候选",
        "",
        "> 本表用于来源导航。模块和主题候选不代表已经回源核验或形成正式Claim；同一来源可以对应多个模块。",
        "",
        "| 资料ID/资料名称 | 资料角色 | 标准模块候选 | 主题候选 | 判断依据 | 归类状态 |",
        "|---|---|---|---|---|---|",
    ])
    for row in rows:
        source_id = str(row["source_id"])
        mappings = mappings_by_id.get(source_id, [])
        modules = "；".join(dict.fromkeys(item["module"] for item in mappings)) or "不适用"
        topics = "；".join(dict.fromkeys(item["topic"] for item in mappings)) or "不适用"
        bases = "；".join(dict.fromkeys(item["basis"] for item in mappings)) or str(row["role_basis"])
        mapping_fields = (
            f"{source_id}，{Path(str(row['relative_path'])).name}",
            row["source_role"], modules, topics, bases,
            mapping_status_summary(mappings, {
                "status": str(row["role_status"]),
                "confidence": str(row["role_confidence"]),
            }),
        )
        ledger_lines.append("| " + " | ".join(markdown_escape(str(value)) for value in mapping_fields) + " |")
    version_events: list[dict[str, str | int]] = []
    for row in rows:
        source_id = str(row["source_id"])
        previous = existing_human_fields.get(source_id, {})
        old_hash = previous.get("sha256", "").lower()
        new_hash = str(row["sha256"]).lower()
        if not old_hash or old_hash == new_hash:
            continue
        event_key = f"{source_id}\0{old_hash}\0{new_hash}"
        event_id = "SRCVER-" + hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:20].upper()
        version_events.append(
            {
                "schema_version": 1,
                "event_id": event_id,
                "detected_at": built_at,
                "source_id": source_id,
                "relative_path": str(row["relative_path"]),
                "old_sha256": old_hash,
                "new_sha256": new_hash,
                "old_size_bytes": previous.get("size_bytes", ""),
                "new_size_bytes": int(row["size_bytes"]),
                "old_modified_time": previous.get("modified_time", ""),
                "new_modified_time": str(row["modified_time"]),
                "old_content_retained": False,
            }
        )
    append_source_version_events(version_history_path, version_events)
    ledger_path.write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["searchability"])
        counts[key] = counts.get(key, 0) + 1
    description_path.parent.mkdir(parents=True, exist_ok=True)
    description_path.write_text(
        "\n".join(
            [
                "# 源资料搜索索引说明",
                "",
                f"- 索引文件：[[{db_path.name}]]",
                f"- 最近构建：{built_at}",
                "- 构建工具：manage-article-knowledge v0.6",
                f"- 原始资料根路径：{source_root}",
                f"- 正文排除清单：[[{exclusions_path.name}]]",
                f"- 已登记文件数：{len(rows)}",
                f"- 全文文字可搜索：{counts.get('全文文字可搜索', 0)}",
                f"- 部分内容可搜索：{counts.get('部分内容可搜索', 0)}",
                f"- 仅文件信息可搜索：{counts.get('仅文件信息可搜索', 0)}",
                f"- 未建立正文索引：{counts.get('未建立正文索引', 0)}",
                "",
                "## 使用边界",
                "",
                "机器索引只用于发现可能相关的原始资料，不是事实证据。",
                "正式 Claim 必须回到原始文件或可靠固定件核验。",
                "",
                "## 已知限制",
                "",
                "- 音频和视频仅登记基础信息，不检索内容。",
                "- 压缩包默认只登记成员名，不处理成员正文。",
                "- Office媒体、图表和嵌入对象已做只读计数，但正文内容默认未进入索引；需要细查时使用inspect_office_container.py。",
                "- 带复杂资料风险的非重复来源必须在本次构建后关联正式MAT，或在来源台账写明无需建立MAT的中文理由；正式MAT默认不推送内容运营，只有当前文章阻塞且无法唯一处理时才推送。",
                "- 明确禁止正文的文件必须登记在source-index-exclusions.json；构建器按资料ID、相对路径和SHA-256核对，匹配时只保留文件身份，不写入chunks。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"indexed_files={len(rows)}")
    print(f"database={db_path}")
    print(f"ledger={ledger_path}")


if __name__ == "__main__":
    main()
