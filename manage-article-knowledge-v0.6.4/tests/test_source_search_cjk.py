"""Chinese sub-phrase search in the source index (SK-V064-013).

unicode61 kept a whole run of Chinese as one token, so “自动化营销” inside a
longer sentence found nothing by FTS and only appeared, unranked, through the
LIKE fallback.  The index now stores Chinese runs as overlapping bigrams.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from search_source_index import SEARCH_LOG, fts_query, search, segment  # noqa: E402

SENTENCE = "我们为跨境电商客户提供自动化营销方案，并支持多渠道投放。"


def build(root: Path) -> Path:
    sources = root / "src"
    sources.mkdir()
    (sources / "方案.md").write_text(f"# 方案\n\n{SENTENCE}\n\nDrawer boxes ship flat.\n", encoding="utf-8")
    (root / "ws").mkdir()
    project = root / "P-T_v0.6"
    subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPTS / "initialize_project.py"), "--project", str(project),
         "--project-name", "检索测试", "--workspace-project-root", str(root / "ws"), "--source-root", str(sources),
         "--website", "https://example.test/", "--content-owner", "test"],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    index = project / "02_源资料"
    db = index / "source-index.sqlite"
    subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPTS / "build_source_index.py"), "--source-root", str(sources),
         "--db", str(db), "--ledger", str(index / "01_源资料台账.md"),
         "--description", str(index / "源资料搜索索引说明.md")],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return db


class ChineseSubPhraseTests(unittest.TestCase):
    def test_segment_and_query(self) -> None:
        self.assertEqual(segment("自动化营销").split(), ["自动", "动化", "化营", "营销"])
        self.assertEqual(segment("PE袋 drawer").split(), ["PE", "袋", "drawer"])
        self.assertEqual(fts_query("自动化营销 drawer", segmented=True), '"自动 动化 化营 营销" AND "drawer"')
        self.assertEqual(fts_query("自动化营销"), '"自动化营销"')  # indexes built before the change

    def test_sub_phrase_is_found_by_ranked_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = build(Path(temp))
            connection = sqlite3.connect(db)
            try:
                for query in ("自动化营销", "营销方案", "多渠道", "drawer boxes"):
                    hits = search(connection, query, 5)
                    methods = {item["search_method"] for item in hits}
                    self.assertIn("fts", methods, query)
                    fts = next(item for item in hits if item["search_method"] == "fts")
                    self.assertIn(query.split()[0].lower(), str(fts["snippet"]).lower())  # original text, not bigrams
                self.assertEqual([h for h in search(connection, "无关词语", 5) if h["search_method"] == "fts"], [])
            finally:
                connection.close()

    def test_old_unsegmented_index_still_searches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "old.sqlite"
            connection = sqlite3.connect(db)
            connection.executescript(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                "CREATE TABLE sources (source_id TEXT, relative_path TEXT, absolute_path TEXT, searchability TEXT,"
                " indexed_scope TEXT, excluded_scope TEXT);"
                "CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, source_id TEXT, locator TEXT, text TEXT);"
                "CREATE VIRTUAL TABLE chunks_fts USING fts5(source_id UNINDEXED, locator UNINDEXED, text,"
                " tokenize='unicode61');")
            connection.execute("INSERT INTO sources VALUES ('SRC-1', 'a.md', 'D:/a.md', 'full', '', '')")
            connection.execute("INSERT INTO chunks(source_id, locator, text) VALUES ('SRC-1', 'paragraph 1', ?)", (SENTENCE,))
            connection.execute("INSERT INTO chunks_fts VALUES ('SRC-1', 'paragraph 1', ?)", (SENTENCE,))
            # Before the rebuild a sub-phrase is only found literally, as before this change.
            self.assertEqual({h["search_method"] for h in search(connection, "自动化营销", 5)}, {"literal"})
            connection.close()

    def test_cli_logs_each_search_beside_the_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = build(Path(temp))
            for query in ("自动化营销", "不存在的词"):
                subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "search_source_index.py"), "--db", str(db),
                                "--query", query, "--format", "json"], check=True, capture_output=True)
            entries = [json.loads(line) for line in (db.parent / SEARCH_LOG).read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["query"] for e in entries], ["自动化营销", "不存在的词"])
            self.assertGreater(entries[0]["result_count"], 0)
            self.assertEqual(entries[1]["result_count"], 0)


if __name__ == "__main__":
    unittest.main()
