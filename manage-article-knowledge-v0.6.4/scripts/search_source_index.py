#!/usr/bin/env python3
"""Search a v0.6 source index and return discovery clues with locators."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


def compact(value: str, maximum: int = 320) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= maximum:
        return value
    return value[: maximum - 1].rstrip() + "…"


CJK_RUN_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+")
# Index metadata naming how chunks_fts was tokenised; absent in indexes built before it.
SEGMENTATION_KEY = "fts_segmentation"
SEGMENTATION = "cjk-bigram-1"
SEARCH_LOG = "source-search-log.jsonl"


def segment(text: str) -> str:
    """Split each run of Chinese into overlapping two-character tokens.

    unicode61 keeps a whole run of Chinese as one token, so a sub-phrase such
    as \u201c\u81ea\u52a8\u5316\u8425\u9500\u201d inside a longer sentence never matched.  Indexing bigrams
    lets a phrase query of the same bigrams match anywhere and be ranked by bm25.
    """
    def bigrams(match: re.Match[str]) -> str:
        run = match.group(0)
        if len(run) == 1:
            return f" {run} "
        return " " + " ".join(run[i:i + 2] for i in range(len(run) - 1)) + " "
    return CJK_RUN_RE.sub(bigrams, text)


def fts_query(query: str, segmented: bool = False) -> str:
    terms = re.findall(r"[\w\u3400-\u9fff]+", query, flags=re.UNICODE)
    if segmented:
        phrases = [" ".join(segment(term).split()) for term in terms]
        return " AND ".join(f'"{phrase}"' for phrase in phrases if phrase)
    return " AND ".join(f'"{term.replace(chr(34), "")}"' for term in terms if term)


def is_segmented(connection: sqlite3.Connection) -> bool:
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", (SEGMENTATION_KEY,)).fetchone()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] == SEGMENTATION


def log_search(db: Path, query: str, results: list[dict[str, object]]) -> None:
    """Append this search to the project's search log, which records that the source layer was searched.

    The merged 20 derives its \u5ba2\u6237\u6e90\u8d44\u6599\u7d22\u5f15 layer from this log instead of a hand-written row.
    A read-only project only loses the log entry, never the search.
    """
    from datetime import datetime, timezone
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "query": query,
             "result_count": len(results),
             "source_ids": sorted({str(item["source_id"]) for item in results})[:20]}
    try:
        with (db.parent / SEARCH_LOG).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def search(connection: sqlite3.Connection, query: str, limit: int) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    expression = fts_query(query, is_segmented(connection))
    if expression:
        try:
            rows = connection.execute(
                """
                SELECT f.source_id, s.relative_path, s.absolute_path, f.locator, f.text,
                       bm25(chunks_fts) AS rank
                FROM chunks_fts AS f
                JOIN sources AS s ON s.source_id = f.source_id
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
            for source_id, relative_path, absolute_path, locator, text, rank in rows:
                key = (source_id, locator, text)
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    {
                        "source_id": source_id,
                        "relative_path": relative_path,
                        "absolute_path": absolute_path,
                        "locator": locator,
                        "snippet": compact(text),
                        "search_method": "fts",
                        "rank": rank,
                    }
                )
        except sqlite3.OperationalError:
            pass

    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        terms = [query.casefold()]
    where = " AND ".join("lower(c.text) LIKE ?" for _ in terms)
    parameters: list[object] = [f"%{term}%" for term in terms]
    parameters.append(limit * 3)
    rows = connection.execute(
        f"""
        SELECT c.source_id, s.relative_path, s.absolute_path, c.locator, c.text
        FROM chunks AS c
        JOIN sources AS s ON s.source_id = c.source_id
        WHERE {where}
        LIMIT ?
        """,
        parameters,
    ).fetchall()
    for source_id, relative_path, absolute_path, locator, text in rows:
        key = (source_id, locator, text)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "source_id": source_id,
                "relative_path": relative_path,
                "absolute_path": absolute_path,
                "locator": locator,
                "snippet": compact(text),
                "search_method": "literal",
                "rank": None,
            }
        )

    filename_rows = connection.execute(
        """
        SELECT source_id, relative_path, absolute_path, searchability,
               indexed_scope, excluded_scope
        FROM sources
        WHERE lower(relative_path) LIKE ?
        LIMIT ?
        """,
        (f"%{query.casefold()}%", limit),
    ).fetchall()
    for source_id, relative_path, absolute_path, searchability, indexed_scope, excluded_scope in filename_rows:
        key = (source_id, "file metadata", relative_path)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "source_id": source_id,
                "relative_path": relative_path,
                "absolute_path": absolute_path,
                "locator": "file metadata",
                "snippet": compact(f"{searchability}; {indexed_scope}; {excluded_scope}"),
                "search_method": "filename",
                "rank": None,
            }
        )
    return results[:limit]


def main() -> None:
    # Windows default consoles may use GBK; force UTF-8 so source text cannot
    # abort an otherwise valid search result.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    if not args.db.is_file():
        raise SystemExit(f"Index not found: {args.db}")
    connection = sqlite3.connect(args.db)
    try:
        results = search(connection, args.query, max(1, args.limit))
    finally:
        connection.close()
    log_search(args.db, args.query, results)

    if args.format == "json":
        print(json.dumps({"query": args.query, "results": results}, ensure_ascii=False, indent=2))
        return

    print(f"# 搜索结果：{args.query}")
    print()
    print("以下结果只是发现线索，创建 Claim 前必须回到原始资料核验。")
    print()
    if not results:
        print("- 未找到匹配结果")
        return
    for index, item in enumerate(results, 1):
        print(f"## {index}. {item['source_id']} · {item['relative_path']}")
        print()
        print(f"- 原始路径：{item['absolute_path']}")
        print(f"- 位置：{item['locator']}")
        print(f"- 匹配方式：{item['search_method']}")
        print(f"- 片段：{item['snippet']}")
        print()


if __name__ == "__main__":
    main()
