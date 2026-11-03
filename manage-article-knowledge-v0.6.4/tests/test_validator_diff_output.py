"""validate_v06_project.py prints only what changed since its last run unless --all."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_v06_project as validator  # noqa: E402


class ValidatorDiffOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Path(temp.name) / "last.json"
        patch = mock.patch.object(validator, "last_run_path", lambda root, gate: self.store)
        patch.start()
        self.addCleanup(patch.stop)

    def report(self, errors: list[str], warnings: list[str], show_all: bool = False) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            validator.report_issues(Path("."), errors, warnings, show_all=show_all)
        return out.getvalue()

    def test_first_run_prints_everything(self):
        text = self.report(["甲", "乙"], ["丙"])
        self.assertIn("ERROR: 甲", text)
        self.assertIn("ERROR: 乙", text)
        self.assertIn("WARNING: 丙", text)
        self.assertIn("errors=2", text)

    def test_later_run_prints_only_new_and_counts_resolved(self):
        self.report(["甲", "乙"], ["丙"])
        text = self.report(["乙", "丁"], ["丙"])
        self.assertNotIn("甲", text)
        self.assertNotIn("ERROR: 乙", text)
        self.assertIn("NEW ERROR: 丁", text)
        self.assertNotIn("丙", text)
        self.assertIn("resolved_errors=1", text)
        self.assertIn("unchanged_errors=1", text)
        self.assertIn("errors=2", text)

    def test_all_flag_prints_everything_again(self):
        self.report(["甲"], [])
        text = self.report(["甲"], [], show_all=True)
        self.assertIn("ERROR: 甲", text)
        self.assertNotIn("NEW ERROR", text)


if __name__ == "__main__":
    unittest.main()
