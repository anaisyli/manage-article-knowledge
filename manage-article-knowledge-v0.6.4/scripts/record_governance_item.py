#!/usr/bin/env python3
"""Create or update one CUS/ANM/SKFB governance item as a paired table row and detail.

The three ledgers are human-readable Markdown, but the main-table row and the
same-ID detail block form one control transaction.  Writing them through this
script keeps IDs sequential, statuses legal, tables contiguous and both halves
in sync; the result is checked with the project validator rules before it
replaces the ledger.  SKFB stage changes stay with manage_skill_feedback.py.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid
from datetime import date
from pathlib import Path
from atomic_replace import replace_with_retry

from validate_v06_project import HUMAN_LEDGER_FIELDS, LEDGER_RULES, validate_feedback_details, validate_ledgers


DETAIL_SECTIONS = {"CUS": "## 事项详情", "ANM": "## 异常详情", "SKFB": "## 反馈详情"}
STAGE_COLUMN = "当前阶段"
DATE_COLUMN = "最近更新"
# 详情必须能说明何时重新打开；SKFB还要求关闭条件（与校验器同口径）。
REQUIRED_DETAIL_FIELDS = {"CUS": ("重开条件",), "ANM": ("重开条件",), "SKFB": ("关闭条件", "重开条件")}
# A new CUS/ANM starts at the first stage with the usual owner; the caller writes only what the item is about.
CREATE_DEFAULTS = {"CUS": {STAGE_COLUMN: "待判断要不要问", "下一责任人": "内容运营"},
                   "ANM": {STAGE_COLUMN: "待判断", "下一责任人": "Codex", "原文是否修复": "否"}}
DETAIL_DEFAULTS = {"CUS": {"重开条件": "客户补充或更正该事实、新证据与回复冲突，或其他文章再次依赖该事实"},
                   "ANM": {"重开条件": "来源出现新版本或新材料、同类冲突再次出现，或其他文章再次依赖该事实"}}


def cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [part.strip().replace("\\|", "|") for part in cells]


def normalized(value: str) -> str:
    return re.sub(r"[^0-9a-z㐀-鿿]+", "", value.casefold())


def table_span(lines: list[str], section: str) -> tuple[int, int, int]:
    """Return (header index, first row index, end index) of the section's main table.

    Blank lines between data rows are treated as part of the table so a row
    that was separated by an accidental blank line is not lost.
    """
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == section)
    except StopIteration as exc:
        raise SystemExit(f"台账缺少“{section[3:]}”小节") from exc
    header = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("|")),
        None,
    )
    if header is None or header + 1 >= len(lines) or not re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[header + 1]):
        raise SystemExit(f"“{section[3:]}”小节缺少标准主表")
    end = header + 2
    probe = end
    while probe < len(lines):
        text = lines[probe].strip()
        if text.startswith("|"):
            end = probe + 1
        elif text and not text.startswith("|"):
            break
        probe += 1
    return header, header + 2, end


def project_prefix(rows: list[list[str]], kind: str, project: Path) -> str:
    for row in rows:
        match = re.match(rf"^(.+)-{kind}-\d+$", row[0])
        if match:
            return match.group(1)
    info = project / "01_工作台/10_项目基础信息.md"
    text = info.read_text(encoding="utf-8-sig") if info.is_file() else ""
    match = re.search(r"(?m)^\s*-\s*项目ID[：:]\s*(\S+)", text)
    if not match:
        raise SystemExit("无法确定项目ID，不能自动分配编号")
    return match.group(1)


def next_id(rows: list[list[str]], kind: str, prefix: str, text: str) -> str:
    numbers = [
        int(match.group(1))
        for match in re.finditer(rf"{re.escape(prefix)}-{kind}-(\d+)", text)
    ]
    return f"{prefix}-{kind}-{max(numbers, default=0) + 1:03d}"


def detail_span(lines: list[str], item_id: str) -> tuple[int, int] | None:
    start = next((i for i, line in enumerate(lines) if line.startswith(f"### {item_id}｜")), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^#{2,3}\s", lines[i])),
        len(lines),
    )
    return start, end


def parse_pairs(values: list[str], option: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"{option} 必须写成 字段=内容：{item}")
        key, value = item.split("=", 1)
        if not key.strip() or not value.strip():
            raise SystemExit(f"{option} 的字段和内容都不能为空：{item}")
        if not re.search(r"[㐀-鿿]", value) and key.strip() not in {DATE_COLUMN}:
            raise SystemExit(f"{option} {key.strip()} 必须包含中文人话说明")
        pairs[key.strip()] = value.strip()
    return pairs


def check_written(project: Path, kind: str, candidate: str) -> list[str]:
    """Validate the candidate ledger text in a scratch copy of the project layout.

    The scratch directory is a plain mkdir next to the project, not ``tempfile``: since the
    CVE-2024-4030 fix tempfile directories get an owner-only ACL on Windows, and a sandboxed
    agent can create one but not write inside it (WinError 5; see recover_article_package._Staging).
    """
    root = project / f".mak-governance-check-{uuid.uuid4().hex[:8]}"
    root.mkdir()
    try:
        target = root / str(LEDGER_RULES[kind]["path"])
        target.parent.mkdir(parents=True)
        target.write_text(candidate, encoding="utf-8")
        errors: list[str] = []
        validate_ledgers(root, errors)
        if kind == "SKFB":
            validate_feedback_details(root, errors)
        return [error.replace(str(target), "台账") for error in errors]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def apply(args: argparse.Namespace) -> tuple[str, str]:
    kind = args.kind
    rule = LEDGER_RULES[kind]
    project = args.project.resolve()
    path = project / str(rule["path"])
    if not path.is_file():
        raise SystemExit(f"台账不存在：{path}")
    original = path.read_text(encoding="utf-8-sig")
    lines = original.splitlines()
    header_index, first_row, end = table_span(lines, str(rule["section"]))
    header = split_row(lines[header_index])
    rows = [split_row(line) for line in lines[first_row:end] if line.strip()]
    columns = parse_pairs(args.set, "--set")
    details = parse_pairs(args.detail, "--detail")
    unknown = sorted(set(columns) - set(header))
    if unknown:
        raise SystemExit(f"主表没有这些列：{'、'.join(unknown)}；可用列：{'、'.join(header[1:])}")
    stage = columns.get(STAGE_COLUMN, "")
    if stage and stage not in rule["statuses"]:
        raise SystemExit(f"{kind}阶段无效：{stage}；可用：{'、'.join(sorted(rule['statuses']))}")
    today = args.date

    if args.item_id == "auto":
        # SK-V064-014: the stage, owner and reopen condition of a new CUS/ANM follow from its kind.
        for name, value in CREATE_DEFAULTS.get(kind, {}).items():
            if name in header and not columns.get(name):
                columns[name] = value
        for name, value in DETAIL_DEFAULTS.get(kind, {}).items():
            details.setdefault(name, value)
        if not args.title:
            args.title = columns.get(HUMAN_LEDGER_FIELDS[kind][0], "")
        missing = [name for name in header[1:] if name != DATE_COLUMN and not columns.get(name)]
        if missing:
            raise SystemExit(f"新建{kind}必须填写主表列：{'、'.join(missing)}")
        if not args.title or not re.search(r"[㐀-鿿]", args.title):
            raise SystemExit("新建事项必须用 --title 给出中文人话详情标题")
        missing_detail = [name for name in REQUIRED_DETAIL_FIELDS[kind] if not details.get(name)]
        if missing_detail:
            raise SystemExit(f"新建{kind}详情必须填写：{'、'.join(missing_detail)}")
        # 同一问题复用原编号：主表第一个人话字段相同即视为同一事项。
        key_column = HUMAN_LEDGER_FIELDS[kind][0]
        key_index = header.index(key_column)
        duplicate = next(
            (row[0] for row in rows if len(row) > key_index and normalized(row[key_index]) == normalized(columns[key_column])),
            None,
        )
        if duplicate:
            raise SystemExit(f"已有同一事项 {duplicate}；请用 --item-id {duplicate} 追加复现或更新，而不是新建")
        item_id = next_id(rows, kind, project_prefix(rows, kind, project), original)
        values = {**columns, header[0]: item_id, DATE_COLUMN: today}
        new_row = "| " + " | ".join(cell(values.get(name, "")) for name in header) + " |"
        table = [line for line in lines[first_row:end] if line.strip()] + [new_row]
        lines[first_row:end] = table
        section = DETAIL_SECTIONS[kind]
        try:
            detail_start = next(i for i, line in enumerate(lines) if line.strip() == section)
        except StopIteration as exc:
            raise SystemExit(f"台账缺少“{section[3:]}”小节") from exc
        insert_at = next(
            (i for i in range(detail_start + 1, len(lines)) if re.match(r"^##\s", lines[i])),
            len(lines),
        )
        while insert_at > detail_start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        block = ["", f"### {item_id}｜{cell(args.title)}", "", f"- 当前阶段：{values[STAGE_COLUMN]}"]
        block += [f"- {name}：{value}" for name, value in details.items() if name != STAGE_COLUMN]
        block += [f"- 最近更新：{today}"]
        lines[insert_at:insert_at] = block
        action = "created"
    else:
        item_id = args.item_id.strip()
        index = next((i for i, row in enumerate(rows) if row and row[0] == item_id), None)
        if index is None:
            raise SystemExit(f"主表中没有 {item_id}；新事项请使用 --item-id auto")
        if kind == "SKFB" and stage:
            raise SystemExit("SKFB阶段变化请使用 manage_skill_feedback.py --set-stage，以同步验证依据")
        row = rows[index] + [""] * (len(header) - len(rows[index]))
        for name, value in columns.items():
            row[header.index(name)] = value
        row[header.index(DATE_COLUMN)] = today
        table = [line for line in lines[first_row:end] if line.strip()]
        table[index] = "| " + " | ".join(cell(value) for value in row[: len(header)]) + " |"
        lines[first_row:end] = table
        span = detail_span(lines, item_id)
        if span is None:
            raise SystemExit(f"{item_id} 缺少同ID详情区块，请先由维护流程补齐")
        start, stop = span
        block = lines[start:stop]
        while block and not block[-1].strip():
            block.pop()
        updates = dict(details)
        if stage:
            updates[STAGE_COLUMN] = stage
        for name, value in updates.items():
            pattern = re.compile(rf"^-\s*{re.escape(name)}[：:]")
            position = next((i for i, line in enumerate(block) if pattern.match(line)), None)
            if position is None:
                block.append(f"- {name}：{value}")
            else:
                block[position] = f"- {name}：{value}"
        if args.append_note:
            block.append(f"- {today}补充：{' '.join(args.append_note.split())}")
        update_position = next((i for i, line in enumerate(block) if re.match(r"^-\s*最近更新[：:]", line)), None)
        if update_position is None:
            block.append(f"- 最近更新：{today}")
        else:
            block[update_position] = f"- 最近更新：{today}"
        lines[start:stop] = block + ([""] if stop < len(lines) else [])
        action = "updated"

    candidate = "\n".join(lines) + "\n"
    # 只拦截本次写入新引入的问题；台账里原有的其他问题照常留给维护流程。
    introduced = sorted(set(check_written(project, kind, candidate)) - set(check_written(project, kind, original)))
    if introduced:
        raise SystemExit("写入前校验失败，台账未修改：" + "；".join(introduced[:6]))
    if path.read_text(encoding="utf-8-sig") != original:
        raise SystemExit("台账在本次写入期间被其他流程修改，未覆盖；请重新运行")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(candidate, encoding="utf-8")
    replace_with_retry(temporary, path)
    return item_id, action


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--kind", choices=("CUS", "ANM", "SKFB"), required=True)
    parser.add_argument("--item-id", default="auto", help="auto新建；已有编号则更新同一事项")
    parser.add_argument("--title", default="", help="新建时的人话详情标题")
    parser.add_argument("--set", action="append", default=[], help="主表列=内容，可重复")
    parser.add_argument("--detail", action="append", default=[], help="详情字段=内容，可重复")
    parser.add_argument("--append-note", default="", help="同一事项再次复现或补充时追加到详情")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    item_id, action = apply(args)
    print(f"item_id={item_id}")
    print(f"action={action}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc.code, file=sys.stderr)
            raise SystemExit(2) from None
        raise
