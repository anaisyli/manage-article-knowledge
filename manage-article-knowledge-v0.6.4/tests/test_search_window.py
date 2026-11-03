"""A search logged in the window's first second counts: the log keeps whole seconds, the window start does not."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from task_records import SEARCH_LOG, _searches  # noqa: E402


class SearchWindowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.task = self.project / "task"
        self.task.mkdir()
        run_file = self.task / "知识检索运行.json"
        run_file.write_text("{}", encoding="utf-8")
        self.start = datetime(2026, 11, 3, 8, 0, 5, 700000, timezone.utc)
        os.utime(run_file, (self.start.timestamp(), self.start.timestamp()))
        (self.project / SEARCH_LOG).parent.mkdir(parents=True)

    def logged(self, moment: datetime) -> list[str]:
        entry = {"time": moment.isoformat(timespec="seconds"), "query": "insert thickness"}
        (self.project / SEARCH_LOG).write_text(json.dumps(entry) + "\n", encoding="utf-8")
        return _searches(self.task, self.project, {})

    def test_a_search_in_the_same_second_counts(self):
        self.assertEqual(self.logged(self.start + timedelta(milliseconds=100)), ["insert thickness"])

    def test_a_search_from_an_earlier_second_does_not(self):
        self.assertEqual(self.logged(self.start - timedelta(seconds=1)), [])


if __name__ == "__main__":
    unittest.main()
