#!/usr/bin/env python3
"""Read-only inventory of embedded objects and relationships in Office ZIP files.

The script never extracts or modifies payloads. It is an omission detector, not a
content parser: unresolved OLE objects are intentionally reported for follow-up.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


INTERESTING_PREFIXES = (
    "word/embeddings/",
    "ppt/embeddings/",
    "xl/embeddings/",
    "word/media/",
    "ppt/media/",
    "xl/media/",
    "word/charts/",
    "ppt/charts/",
    "xl/charts/",
    "word/diagrams/",
    "ppt/diagrams/",
    "word/activeX/",
    "ppt/activeX/",
    "xl/activeX/",
)

KNOWN_EXTENSIONS = (
    "pdf", "doc", "docx", "docm", "xls", "xlsx", "xlsm", "ppt", "pptx",
    "pptm", "csv", "txt", "rtf", "zip", "png", "jpg", "jpeg", "tif",
    "tiff", "bmp", "gif", "svg", "emf", "wmf",
)

SIGNATURES = (
    (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP/OOXML"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE/CFB"),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_signatures(data: bytes) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for signature, label in SIGNATURES:
        offset = data.find(signature)
        if offset >= 0:
            found.append({"type": label, "offset": offset})
    return found


def candidate_filenames(data: bytes) -> list[str]:
    ext_group = "|".join(KNOWN_EXTENSIONS)
    ascii_pattern = re.compile(
        rb"[A-Za-z0-9_ .()\[\]{}+&,@#%\-]{1,180}\.(?:" + ext_group.encode() + rb")",
        re.IGNORECASE,
    )
    text_pattern = re.compile(
        r"[A-Za-z0-9_ .()\[\]{}+&,@#%\-]{1,180}\.(?:" + ext_group + r")",
        re.IGNORECASE,
    )

    names: set[str] = set()
    for match in ascii_pattern.finditer(data):
        value = match.group(0).decode("latin-1", errors="ignore").strip(" \x00")
        names.add(Path(value.replace("\\", "/")).name)
    utf16_text = data.decode("utf-16le", errors="ignore")
    for match in text_pattern.finditer(utf16_text):
        value = match.group(0).strip(" \x00")
        names.add(Path(value.replace("\\", "/")).name)

    return sorted((name for name in names if name), key=lambda value: (len(value), value.lower()))


def inspect_relationships(archive: zipfile.ZipFile) -> list[dict[str, str]]:
    relationships: list[dict[str, str]] = []
    for name in archive.namelist():
        if not name.endswith(".rels"):
            continue
        try:
            root = ElementTree.fromstring(archive.read(name))
        except (ElementTree.ParseError, KeyError):
            relationships.append({"relationship_file": name, "status": "unreadable"})
            continue
        for node in root:
            target = node.attrib.get("Target", "")
            target_mode = node.attrib.get("TargetMode", "Internal")
            rel_type = node.attrib.get("Type", "").rsplit("/", 1)[-1]
            if (
                target_mode == "External"
                or "embeddings/" in target
                or "media/" in target
                or rel_type in {"oleObject", "package", "hyperlink", "image", "chart", "diagramData"}
            ):
                relationships.append(
                    {
                        "relationship_file": name,
                        "id": node.attrib.get("Id", ""),
                        "type": rel_type,
                        "target": target,
                        "target_mode": target_mode,
                    }
                )
    return relationships


def inspect_nested_zip(data: bytes) -> dict[str, Any] | None:
    try:
        stream = io.BytesIO(data)
        if not zipfile.is_zipfile(stream):
            return None
        with zipfile.ZipFile(stream) as nested:
            return {
                "entry_count": len(nested.infolist()),
                "sample_entries": nested.namelist()[:20],
            }
    except (OSError, zipfile.BadZipFile):
        return None


def inspect(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    if not zipfile.is_zipfile(path):
        raise ValueError("The file is not a ZIP-based Office document or ZIP archive.")

    result: dict[str, Any] = {
        "file": str(path.resolve()),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "embedded_objects": [],
        "media_and_structures": [],
        "relationships": [],
        "unresolved_embedded_objects": [],
        "summary": {},
    }

    with zipfile.ZipFile(path) as archive:
        result["relationships"] = inspect_relationships(archive)
        for info in archive.infolist():
            if info.is_dir():
                continue
            normalized = info.filename.replace("\\", "/")
            if not normalized.startswith(INTERESTING_PREFIXES):
                continue
            data = archive.read(info)
            record: dict[str, Any] = {
                "package_path": normalized,
                "compressed_size": info.compress_size,
                "size": info.file_size,
                "sha256": sha256_bytes(data),
                "candidate_filenames": candidate_filenames(data),
                "payload_signatures": payload_signatures(data),
            }
            nested = inspect_nested_zip(data)
            if nested:
                record["nested_zip"] = nested

            if "/embeddings/" in normalized:
                result["embedded_objects"].append(record)
                useful_name = bool(record["candidate_filenames"])
                useful_payload = any(item["offset"] > 0 for item in record["payload_signatures"])
                if not useful_name and not useful_payload:
                    result["unresolved_embedded_objects"].append(normalized)
            else:
                result["media_and_structures"].append(record)

    result["summary"] = {
        "embedded_object_count": len(result["embedded_objects"]),
        "unresolved_embedded_object_count": len(result["unresolved_embedded_objects"]),
        "media_and_structure_count": len(result["media_and_structures"]),
        "relationship_count": len(result["relationships"]),
        "external_relationship_count": sum(
            1 for item in result["relationships"] if item.get("target_mode") == "External"
        ),
        "ready_for_content_processing": len(result["unresolved_embedded_objects"]) == 0,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only inventory of Office ZIP embedded objects, media, and relationships."
    )
    parser.add_argument("file", type=Path, help="DOCX, PPTX, XLSX, DOCM, PPTM, XLSM, or ZIP file")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON")
    args = parser.parse_args()

    try:
        result = inspect(args.file)
    except (FileNotFoundError, PermissionError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    indent = None if args.compact else 2
    print(json.dumps(result, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
