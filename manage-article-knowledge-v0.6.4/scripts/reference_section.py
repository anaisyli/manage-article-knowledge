#!/usr/bin/env python3
"""Print only the named sections of a reference file.

SKILL.md tells each stage which sections of a long reference it needs.  Reading
the whole file every run repeats rules for other stages; this prints just the
requested heading blocks (each heading through the next heading of the same or
higher level) without shell quoting.

    python scripts/reference_section.py references/runtime-checklist.md "文章任务"
    python scripts/reference_section.py references/skill-integration-handoff.md "交接合同版本" "0.2" "3."
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def sections(text: str, wanted: list[str]) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    headings = [(index, len(match.group(1)), match.group(2))
                for index, line in enumerate(lines) if (match := HEADING_RE.match(line))]
    output: list[str] = []
    missing: list[str] = []
    for key in wanted:
        found = [(index, level) for index, level, title in headings
                 if title.startswith(key) or re.sub(r"^[\d.]+\s*", "", title).startswith(key)]
        if not found:
            missing.append(key)
            continue
        start, level = found[0]
        end = next((index for index, other, _ in headings if index > start and other <= level), len(lines))
        output.extend(lines[start:end])
        output.append("")
    return output, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="参考文件；相对路径按本Skill根目录解析")
    parser.add_argument("heading", nargs="+", help="标题开头文字，或去掉编号后的标题开头文字")
    args = parser.parse_args()
    path = args.file if args.file.is_absolute() or args.file.is_file() else Path(__file__).resolve().parents[1] / args.file
    output, missing = sections(path.read_text(encoding="utf-8-sig"), args.heading)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.write("\n".join(output))
    if missing:
        print("missing_heading=" + "；".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
