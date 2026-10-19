#!/usr/bin/env python3
"""Fetch a customer website page and append auditable body evidence.

The Markdown retrieval table is a human-readable report.  This sidecar is the
machine-verifiable proof that the reported URL was actually fetched during the
current knowledge-preparation run. It stores semantic text blocks from static
HTML, not a flattened whole-page DOM. JavaScript-only content must be read with
a browser-capable tool; this fetcher intentionally rejects an empty app shell.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, object]] = []
        self._stack: list[dict[str, object]] = []
        self._skip_depth = 0
        self._primary_stack: list[str] = []
        self._heading_path: list[str] = []
        self._table_rows: list[tuple[list[str], list[str], bool]] = []
        self._table_row: list[str] | None = None
        self._cell_text: list[str] | None = None
        self._table_heading_path: list[str] = []

    # Keep content as semantic blocks. Never use an entire-page flattened text
    # string as evidence; <main>/<article> wins, with a conservative body
    # fallback only when the page has no semantic main container.
    _SKIP_TAGS = {
        "script", "style", "noscript", "template", "svg", "head",
        "nav", "header", "footer", "aside", "form", "button",
    }
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
    _PRIMARY_TAGS = {"main", "article"}
    _BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "figcaption"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): value or "" for key, value in attrs}
        classes = f" {attr.get('class', '').lower()} "
        if (
            "hidden" in attr
            or attr.get("aria-hidden", "").lower() == "true"
            or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attr.get("style", ""), re.I)
            or any(marker in classes for marker in (" cookie ", " consent ", " modal ", " popup "))
        ):
            if tag not in self._VOID_TAGS:
                self._skip_depth += 1
                self._stack.append({"tag": tag, "skip": True})
            return
        if tag in self._SKIP_TAGS:
            if tag not in self._VOID_TAGS:
                self._skip_depth += 1
                self._stack.append({"tag": tag, "skip": True})
            return
        if self._skip_depth:
            if tag not in self._VOID_TAGS:
                self._stack.append({"tag": tag, "skip": False})
            return
        if tag in self._PRIMARY_TAGS:
            self._primary_stack.append(tag)
            self._stack.append({"tag": tag, "skip": False, "primary": True})
            return
        self._stack.append({"tag": tag, "skip": False})
        if tag in self._VOID_TAGS:
            return
        if tag == "tr":
            self._table_row = []
        elif tag in {"td", "th"} and self._table_row is not None:
            self._cell_text = []
        elif tag in self._BLOCK_TAGS:
            self._stack[-1]["text"] = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        entry_index = next(
            (index for index in range(len(self._stack) - 1, -1, -1) if self._stack[index]["tag"] == tag),
            None,
        )
        if entry_index is None:
            return
        closing = self._stack[entry_index:]
        del self._stack[entry_index:]
        for entry in reversed(closing):
            item_tag = str(entry["tag"])
            if entry.get("skip"):
                self._skip_depth = max(0, self._skip_depth - 1)
                continue
            was_primary = bool(entry.get("primary"))
            if item_tag in {"td", "th"} and self._cell_text is not None:
                cell = normalized(" ".join(self._cell_text))
                if cell and self._table_row is not None:
                    self._table_row.append(cell)
                self._cell_text = None
            if item_tag == "tr" and self._table_row is not None:
                if any(self._table_row):
                    self._table_rows.append((self._table_row, list(self._heading_path), bool(self._primary_stack)))
                    self._table_heading_path = list(self._heading_path)
                self._table_row = None
            if item_tag in self._BLOCK_TAGS:
                value = normalized(" ".join(entry.get("text", [])))
                if value:
                    level = int(item_tag[1]) if item_tag.startswith("h") else 0
                    if level:
                        self._heading_path = self._heading_path[: level - 1]
                        self._heading_path.append(value)
                        self._heading_path = self._heading_path[:level]
                    self.blocks.append({
                        "tag": item_tag,
                        "text": value,
                        "heading_path": list(self._heading_path),
                        "order": len(self.blocks) + 1,
                        "source_scope": "main/article" if self._primary_stack or was_primary else "body_fallback",
                    })
            if was_primary:
                if self._primary_stack and self._primary_stack[-1] == item_tag:
                    self._primary_stack.pop()
                elif item_tag in self._primary_stack:
                    del self._primary_stack[len(self._primary_stack) - 1 - self._primary_stack[::-1].index(item_tag):]

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = normalized(data)
        if not value:
            return
        for entry in self._stack:
            if "text" in entry:
                entry["text"].append(value)
        if self._cell_text is not None:
            self._cell_text.append(value)


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def fetch(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"URL必须是http(s)绝对地址：{url}")
    request = Request(url, headers={"User-Agent": "manage-article-knowledge/0.6"})
    with urlopen(request, timeout=30) as response:
        payload = response.read()
        final_url = response.geturl()
        content_type = response.headers.get_content_type()
        content_type_header = response.headers.get("Content-Type", "")
    if content_type != "text/html":
        raise ValueError(f"响应不是HTML正文（Content-Type={content_type or 'unknown'}）：{final_url}")
    charset = re.search(r"charset\s*=\s*['\"]?([\w.-]+)", content_type_header, re.I)
    encoding = charset.group(1) if charset else "utf-8"
    try:
        codecs.lookup(encoding)
    except LookupError:
        encoding = "utf-8"
    decoded = payload.decode(encoding, errors="replace")
    parser = _TextParser()
    parser.feed(decoded)
    parser.close()
    has_primary = any(block["source_scope"] == "main/article" for block in parser.blocks)
    blocks = [
        block for block in parser.blocks
        if (block["source_scope"] == "main/article") == has_primary
    ]
    for index, (row, heading_path, in_primary) in enumerate(parser._table_rows, 1):
        if has_primary and not in_primary:
            continue
        text = " | ".join(row)
        if text:
            blocks.append({
            "tag": "table_row", "text": text, "heading_path": heading_path,
                "order": len(blocks) + 1, "table_row": index,
                "source_scope": "main/article" if has_primary else "body_fallback",
            })
    if not blocks:
        if re.search(r"<script\b|type\s*=\s*['\"]module['\"]", decoded, re.I):
            raise ValueError(f"页面可能是JavaScript动态壳，需用浏览器读取渲染正文：{final_url}")
        raise ValueError(f"页面没有可核验正文：{final_url}")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", decoded, re.I | re.S)
    title = normalized(title_match.group(1)) if title_match else ""
    now = datetime.now().astimezone()
    body_digest = hashlib.sha256()
    for block in blocks:
        body_digest.update(json.dumps(block, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        body_digest.update(b"\n")
    return {
        "requested_url": url,
        "final_url": final_url,
        "fetched_at": now.isoformat(timespec="seconds"),
        "fetched_date": now.date().isoformat(),
        "http_content_type": content_type,
        "response_sha256": hashlib.sha256(payload).hexdigest(),
        "body_sha256": body_digest.hexdigest(),
        "title": title,
        "content_scope": "main/article" if has_primary else "body_fallback",
        "blocks": blocks,
    }


def append_record(
    manifest: Path,
    page: dict[str, object],
    question: str,
    position: str,
    excerpt: str,
    website_id: str,
    source_type: str,
    run_id: str,
) -> dict[str, object]:
    excerpt = normalized(excerpt)
    if len(excerpt) < 20:
        raise ValueError("官网证据摘录至少需要12个字符")
    matching_blocks = [
        block for block in page["blocks"]
        if excerpt in str(block["text"])
    ]
    if not matching_blocks:
        raise ValueError("证据摘录必须是本次抓取的单个正文语义区块内的连续原文")
    block = matching_blocks[0]
    block_text = str(block["text"])
    excerpt_start = block_text.find(excerpt)
    record = {key: value for key, value in page.items() if key != "blocks"}
    record.update({
        "refresh_run_id": normalized(run_id),
        "question": normalized(question),
        "position": normalized(position),
        "excerpt": excerpt,
        "website_id": normalized(website_id) or "PRIMARY-WEBSITE",
        "source_type": normalized(source_type) or "客户官网",
        "block_id": f"B{int(block['order']):03d}",
        "block_tag": str(block["tag"]),
        "heading_path": list(block.get("heading_path", [])),
        "block_text": str(block["text"]),
        "excerpt_start": excerpt_start,
        "excerpt_end": excerpt_start + len(excerpt),
        "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    })
    existing: list[dict[str, object]] = []
    if manifest.is_file():
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            raise ValueError("官网抓取凭证必须是JSON数组")
    if not record["refresh_run_id"]:
        raise ValueError("本轮检索/重整运行ID不能为空")
    existing.append(record)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest.with_name(manifest.name + ".tmp")
    temporary.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True, help="本轮知识检索/重整运行ID")
    parser.add_argument("--url", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--excerpt", required=True)
    parser.add_argument("--website-id", default="PRIMARY-WEBSITE")
    parser.add_argument("--source-type", default="客户官网")
    args = parser.parse_args()
    try:
        record = append_record(
            args.manifest, fetch(args.url), args.question, args.position, args.excerpt,
            args.website_id, args.source_type,
            args.run_id,
        )
    except Exception as exc:
        print(f"website_fetch_error={exc}", file=sys.stderr)
        return 1
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
