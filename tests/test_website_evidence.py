from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "manage-article-knowledge-v0.6.1" / "scripts"))

import capture_website_evidence as website  # noqa: E402
import template_contract  # noqa: E402


class WebsiteEvidenceTests(unittest.TestCase):
    def test_related_website_url_scope_uses_host_and_path_boundaries(self) -> None:
        scope = "https://example.com/company"
        self.assertTrue(template_contract.url_within_registered_scope(
            "https://example.com/company/products/box", scope
        ))
        self.assertFalse(template_contract.url_within_registered_scope(
            "https://example.com.evil.test/company/products", scope
        ))
        self.assertFalse(template_contract.url_within_registered_scope(
            "https://example.com/company-evil/products", scope
        ))

    def test_parser_keeps_semantic_blocks_and_excludes_page_chrome(self) -> None:
        parser = website._TextParser()
        parser.feed(
            """
            <html><head><title>Example Company</title></head>
            <body>
              <header>Products Contact</header>
              <nav>Home Products Contact</nav>
              <main><h1>Custom packaging services</h1>
                <p>Example Company provides custom packaging services for brands.</p>
              </main>
              <footer>Copyright Example Company</footer>
            </body></html>
            """
        )
        primary = [item for item in parser.blocks if item["source_scope"] == "main/article"]
        self.assertEqual([item["tag"] for item in primary], ["h1", "p"])
        self.assertEqual(primary[0]["heading_path"], ["Custom packaging services"])
        self.assertIn("Example Company provides custom packaging services", primary[1]["text"])
        all_text = " ".join(str(item["text"]) for item in parser.blocks)
        self.assertNotIn("Home Products Contact", all_text)
        self.assertNotIn("Copyright Example Company", all_text)

    def test_evidence_excerpt_must_belong_to_one_semantic_block(self) -> None:
        page = {
            "requested_url": "https://example.com/about",
            "final_url": "https://example.com/about",
            "blocks": [
                {"order": 1, "tag": "p", "text": "Example Company provides custom packaging.", "heading_path": ["About"]},
                {"order": 2, "tag": "p", "text": "Its products include packaging boxes.", "heading_path": ["Products"]},
            ],
        }
        with self.assertRaisesRegex(ValueError, "语义区块"):
            website.append_record(
                Path("unused.json"), page, "包装能力", "About第1段",
                "Example Company provides custom packaging. Its products include packaging boxes.",
                "PRIMARY-WEBSITE", "客户官网",
                "run-001",
            )

    def test_semantic_blocks_keep_primary_scope_until_after_block_is_closed(self) -> None:
        parser = website._TextParser()
        parser.feed("<main><p>Body evidence remains in main scope.</p></main><footer>Footer text.</footer>")
        self.assertEqual(parser.blocks[0]["source_scope"], "main/article")
        self.assertEqual(len(parser.blocks), 1)

    def test_void_hidden_elements_do_not_hide_following_body(self) -> None:
        parser = website._TextParser()
        parser.feed(
            '<main><img hidden><p>Example Company provides custom packaging services for brands.</p>'
            '<p hidden>Invisible text must be excluded.</p></main>'
        )
        self.assertEqual(len(parser.blocks), 1)
        self.assertIn("Example Company", parser.blocks[0]["text"])

    def test_dynamic_shell_is_not_treated_as_body_text(self) -> None:
        from unittest.mock import patch

        class Headers(dict):
            def get_content_type(self) -> str:
                return "text/html"

        class Response:
            headers = Headers({"Content-Type": "text/html; charset=utf-8"})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'<html><head><title>Example</title></head><body><div id="app"></div><script src="app.js"></script></body></html>'

            def geturl(self) -> str:
                return "https://example.com/app"

        with patch.object(website, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "JavaScript"):
                website.fetch("https://example.com/app")

    def test_non_html_response_is_rejected(self) -> None:
        from unittest.mock import patch

        class Headers(dict):
            def get_content_type(self) -> str:
                return "application/pdf"

        class Response:
            headers = Headers({"Content-Type": "application/pdf"})

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b"pdf"

            def geturl(self) -> str:
                return "https://example.com/file.pdf"

        with patch.object(website, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "不是HTML"):
                website.fetch("https://example.com/file.pdf")

    def test_primary_content_excludes_non_primary_table_rows(self) -> None:
        parser = website._TextParser()
        parser.feed(
            "<body><table><tr><td>Chrome cell should not appear.</td></tr></table>"
            "<main><table><tr><td>Useful fact</td><td>Value 12</td></tr></table></main></body>"
        )
        self.assertEqual(
            [item for item in parser._table_rows if item[2]],
            [(["Useful fact", "Value 12"], [], True)],
        )

    def test_manifest_record_is_bound_to_run_and_semantic_block(self) -> None:
        from unittest.mock import patch
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "evidence.json"
            page = {
                "requested_url": "https://example.com/about",
                "final_url": "https://example.com/about",
                "fetched_date": "2026-09-23",
                "response_sha256": "response-hash",
                "blocks": [{
                    "order": 1, "tag": "p", "text": "Example Company provides custom packaging services for brands.",
                    "heading_path": ["About", "Services"], "source_scope": "main/article",
                }],
            }
            excerpt = "Example Company provides custom packaging services for brands."
            record = website.append_record(
                manifest, page, "包装能力", "About > Services / B001", excerpt,
                "PRIMARY-WEBSITE", "客户官网", "run-001",
            )
            self.assertEqual(record["refresh_run_id"], "run-001")
            self.assertEqual(record["block_tag"], "p")
            self.assertEqual(record["excerpt_sha256"], website.hashlib.sha256(excerpt.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
