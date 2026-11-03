#!/usr/bin/env python3
"""Write the skeleton of a PR-2 20_文章前知识审核.md, so the agent fills judgments, not structure.

Hand-typed 20s failed the gate on structure, not on judgment: outline rows missing or reworded,
invented CUS/ANM category names, legacy 15/20 tables added under 六, “无” written in a form the gate
does not read.  Everything mechanical comes from the current task instead:

* the six sections in order, with the compact PR-2 table headers;
* 二: one row per batch-ledger fact of this article, with its source pointer, disposition and Claim;
* 三: 标题、主问题 and every item of the 10 outline, copied verbatim;
* 四: one row per CUS/ANM category the gate detects a signal for, under its standard name;
* 五: the three “- 标签：无” lines.

Cells only the agent can decide are left as ``待填写``; the gate rejects them until filled.  An
existing 20 is never overwritten: ``--print`` shows the skeleton instead.  ``run_knowledge_workflow.py``
calls this automatically for a PR-2 task that has no 20 yet.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import task_records as tr  # noqa: E402
from template_contract import outline_labels  # noqa: E402

TODO = "待填写"
# How to fill the 20 travels in the receipt, only while something is unfilled; the file holds content.
FILL_RULES = {
    "写法": "只填“待填写”的格，不改章节、表头、大纲章节和检测类别；一节和六节由脚本写。",
    "结论": "写 自动通过 / 带明确排除通过 / 等待内容运营处理 / 等待项目负责人决定 / 等待知识库专员处理 之一。",
    "候选事实": "一个事实一行；同一段原文读第二次不新增行。支持的大纲问题不用填，由三推出。本篇不用的事实把处置改为“排除”，在入口列写理由。",
    "大纲覆盖": "状态只用 已覆盖 / 部分覆盖 / 未覆盖 / 无需事实支持。已覆盖只写候选事实ID；部分或未覆盖写边界和缺口入口；"
                "H2–H6未覆盖部分会写成事实或方法时写已登记的GAP/CUS编号，只写成待确认问题时写“不构成知识问题：其余只列待确认问题（…）”；"
                "无需事实支持写为什么。",
    "加强": "“知识准备：加强”的H2–H6部分或未覆盖行，覆盖说明再写“证据层级：定义/事实/方法/条件/限制/效果”和“仍缺：…”。",
    "逐项核验": "按右侧signal核对，来源写指针；本篇确实不写该类事实时，核验对象写“本篇不涉及……”、来源写10#大纲、结论写“不适用”、"
                "判断依据写出该类别名和本篇为什么不涉及、本篇处理以“不涉及：”开头。本篇处理以 按证据使用 / 不涉及 / 已排除 / 已缩小 / 等待 开头。",
}
OLD_TEMPLATE_NOTES = ("（通常留空：检索层由脚本推出", "（一个事实一行：", "（每行的覆盖状态只能是：", "（下列是脚本检测到信号的类别")


def _ledger_rows(task: Path, request: str) -> list[dict]:
    batch_id = tr._field(request, "批次ID")
    if not batch_id or batch_id == "不适用":
        return []
    from run_knowledge_workflow import resolve_ledger
    ledger = resolve_ledger(tr._project(task), batch_id)
    if not ledger.is_file():
        return []
    article_id = tr._field(request, "文章ID")
    payload = json.loads(ledger.read_text(encoding="utf-8-sig"))
    rows = [row for row in payload.get("evidence", []) if article_id in row.get("article_ids", [])
            and row.get("disposition") in {"本轮核验通过", "复用已有Formal Claim"}]
    return sorted(rows, key=lambda row: str(row.get("candidate_id", "")))


def _pointer(row: dict, records: list[dict]) -> str:
    excerpt = re.sub(r"\s+", " ", str(row.get("original_excerpt", ""))).strip()
    ids = [str(r["evidence_id"]) for r in records if str(r.get("final_url", "")) == str(row.get("source_path_or_url", ""))
           and re.sub(r"\s+", " ", str(r.get("excerpt", ""))).strip() == excerpt and r.get("evidence_id")]
    ids = list(dict.fromkeys(ids))
    if row.get("disposition") == "复用已有Formal Claim":
        if row.get("verifications") and ids:
            return f"{row['claim_id']}（复用，本轮回源核验：{'、'.join(ids)}）"
        return f"{row['claim_id']}（复用，未回源）"
    return "、".join(ids) or TODO


def _fact_rows(task: Path, request: str) -> list[dict]:
    """One row per fact, whatever an older ledger holds (a repeated read adds no candidate)."""
    from batch_knowledge_run import fact_key
    seen, rows = set(), []
    for row in _ledger_rows(task, request):
        key = fact_key(row.get("claim_id"), row.get("verified_target_excerpt") or row.get("original_excerpt"))
        if key not in seen:
            seen.add(key)
            rows.append(row)
    return rows


def _claim_sentence(project: Path, claim_id: str) -> str:
    """The fact as the Formal Claim states it: real content for the summary cell."""
    from record_claim_reuse import _claim_path, claim_block, field
    path = _claim_path(project, claim_id)
    text = field(claim_block(path.read_text(encoding="utf-8-sig"), claim_id), "Claim") if path else ""
    return text.replace("|", "／") or TODO


def candidates(task: Path, request: str) -> list[list[str]]:
    records = tr.manifest_records(task)
    project = tr._project(task)
    output = []
    for row in _fact_rows(task, request):
        disposition = "复用已有Formal Claim" if row.get("disposition") == "复用已有Formal Claim" else "已沉淀Formal Claim"
        # 支持的大纲问题 stays blank: 三 decides which section uses a fact, and this cell is derived from it.
        output.append([str(row.get("candidate_id") or TODO), _claim_sentence(project, str(row.get("claim_id", ""))),
                       _pointer(row, records), "", disposition, str(row.get("claim_id") or TODO)])
    return output


def signal_rows(task: Path, request: str, facts: list[list[str]]) -> list[list[str]]:
    from governance_signals import detect
    from prewrite_governance import CATEGORIES
    signals = detect(**tr._signal_inputs(task, "", facts, [], tr.manifest_records(task)))
    rows = []
    for detector, categories in CATEGORIES.items():
        for category in categories:
            signal = signals.get((detector, category))
            if signal:
                hits = [word for word in re.split(r"[、：]", signal)[1:] if word]
                pointers = list(dict.fromkeys(fact[2] for fact in facts if any(word in fact[1] for word in hits)))
                rows.append([f"GC-{len(rows) + 1:03d}", detector, category, TODO,
                             "；".join(pointers) or TODO, TODO, TODO, "无", TODO])
    return rows


def render(task: Path) -> str:
    request = tr._read(task / tr.REQUEST)
    facts = candidates(task, request)
    outline = [["标题", TODO, TODO, TODO, ""], ["主问题", TODO, TODO, TODO, ""]]
    outline += [[label, TODO, TODO, TODO, ""] for label in outline_labels(request)]
    checks = signal_rows(task, request, facts)
    blocks = [
        tr.TITLE, "",
        f"- 知识准备记录协议：{tr.PROTOCOL}",
        f"- 审核日期：{date.today().isoformat()}",
        f"- 结论：{TODO}",
        "",
        tr.H_LAYERS, "",
        tr.H_CANDIDATES, "",
        tr._render(tr.CANDIDATE_HEADER_COMPACT, facts or [["CF-001", TODO, TODO, TODO, TODO, TODO]]),
        "",
        tr.H_OUTLINE, "",
        tr._render(tr.OUTLINE_HEADER_COMPACT, outline),
        "",
        tr.H_GOVERNANCE, "",
        tr.H_CHECKS, "",
        *([tr._render(tr.CHECK_HEADER, checks), ""] if checks else []),
        tr.H_SPECIAL, "",
        tr.H_GAPS, "", f"- {tr.NONE_LABELS[tr.H_GAPS]}：无", "",
        tr.H_MAT, "", f"- {tr.NONE_LABELS[tr.H_MAT]}：无", "",
        tr.H_COMPLEX, "", f"- {tr.NONE_LABELS[tr.H_COMPLEX]}：无", "",
        tr.H_CONCLUSION, "",
    ]
    return "\n".join(blocks).rstrip() + "\n"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def fill_todo(task: Path, limit: int = 80) -> dict:
    """List every ``待填写`` left in the task's 20 with its line, table, row and column.

    The workflow receipt carries this list, so the agent edits the named cells instead of
    rereading the whole 10 and 20 to find them.  标题/主问题 rows also get the 10 text they
    must cover; outline rows are themselves the verbatim 10 item.
    """
    path = task / tr.AUDIT
    if not path.is_file():
        return {}
    request = tr._read(task / tr.REQUEST)
    context = {"标题": ("10#标题", tr._field(request, "标题")),
               "主问题": ("10#选题方向", tr._field(request, "选题方向"))}
    items: list[dict] = []
    section, header = "", []
    lines = tr._read(path).splitlines()
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            section, header = stripped.lstrip("# ").strip(), []
            continue
        if stripped.startswith("|"):
            cells = _cells(stripped)
            if not header:
                header = cells
                continue
            if set("".join(cells)) <= set("-: "):
                continue
            columns = [header[index] if index < len(header) else f"第{index + 1}列"
                       for index, cell in enumerate(cells) if TODO in cell]
            if not columns:
                continue
            item = {"line": number, "section": section, "row": cells[0], "columns": columns}
            if cells[0] in context and context[cells[0]][1]:
                item["ten"] = "{}：{}".format(*context[cells[0]])
            items.append(item)
        elif TODO in stripped:
            header = []
            items.append({"line": number, "section": section, "text": stripped[:160]})
        elif stripped:
            header = []
    if not items:
        return {}
    # What the script detected belongs beside the cell to fill, not inside the record.
    from governance_signals import detect
    facts = tr.candidate_rows(task, tr._read(path))
    signals = detect(**tr._signal_inputs(task, tr._read(path), facts, tr.outline_rows(tr._read(path)), tr.manifest_records(task)))
    for item in items:
        if item.get("section") == "逐项核验":
            row = next((line for line in lines if line.strip().startswith(f"| {item.get('row')} |")), "")
            found = signals.get(tuple(_cells(row)[1:3])) if row else None
            if found:
                item["signal"] = found
    result = {"file": str(path), "count": len(items), "rules": FILL_RULES, "cells": items[:limit]}
    if len(items) > limit:
        result["more"] = len(items) - limit
    return result


def normalize_table_pipes(task: Path) -> bool:
    """Give every table row of the 20 its outer pipes, the one form scripts write.

    A row without the closing pipe is legal Markdown and reads the same (the parser takes both); this only
    makes the file uniform.  Cells and line endings are untouched.
    """
    path = task / tr.AUDIT
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines(keepends=True)
    changed = False
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        stripped = body.strip()
        if not stripped.startswith("|") or re.search(r"(?<!\\)\|$", stripped):
            continue
        neighbours = [lines[i].strip() for i in (index - 1, index + 1) if 0 <= i < len(lines)]
        if any(item.startswith("|") for item in neighbours):
            lines[index] = body.rstrip() + " |" + line[len(body):]
            changed = True
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def strip_template_notes(task: Path) -> bool:
    """Remove the fill-in guidance older skeletons wrote into the record; the receipt carries it now."""
    path = task / tr.AUDIT
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8-sig")
    kept = [line for line in raw.splitlines(keepends=True) if not line.strip().startswith(OLD_TEMPLATE_NOTES)]
    text = "".join(kept)
    if text == raw:
        return False
    path.write_text(re.sub(r"\n{3,}", "\n\n", text), encoding="utf-8")
    return True


def materialize_record(task: Path) -> bool:
    """Once the gate passes, write what the script derived, so the 20 reads as a finished record."""
    path = task / tr.AUDIT
    from template_contract import task_mode
    if (not path.is_file() or not tr.is_merged(task) or task_mode(task) == "knowledge_reuse_rewrite"
            or (task / "writing_ready.json").is_file()):
        return False  # a carried-over or already permitted record stays as it is
    text = tr._read(path)
    record = tr.native(task)
    lines = text.splitlines()
    changed = False
    outline = record["outline"]
    used: dict[str, list[str]] = {}
    for row in outline:
        for cf in tr.CF_RE.findall(row[2] if len(row) > 2 else ""):
            used.setdefault(cf, []).append(row[0])
    start = lines.index(tr.H_CANDIDATES)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            break
        cells = lines[index].split("|")
        if lines[index].startswith("| CF-") and len(cells) > 4 and not cells[4].strip():
            cells[4] = f" {'；'.join(used.get(cells[1].strip(), [])) or '无'} "
            lines[index] = "|".join(cells)
            changed = True
    if not tr._table(text, tr.H_LAYERS)[1]:
        at = lines.index(tr.H_LAYERS) + 1
        lines[at:at] = ["", tr._render(tr.LAYER_HEADER, [row[:4] for row in record["layers"]])]
        changed = True
    if not tr._section(text, tr.H_CONCLUSION).strip() and record["conclusion"]:
        lines += ["", record["conclusion"]]
        changed = True
    if changed:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return changed


def append_new_candidates(task: Path) -> list[str]:
    """Add ledger facts that reached the batch after the 20 was written; their judgment stays 待填写."""
    from batch_knowledge_run import fact_key
    path = task / tr.AUDIT
    if not path.is_file():
        return []
    text = tr._read(path)
    header, rows = tr._table(text, tr.H_CANDIDATES)
    if not header:
        return []
    request = tr._read(task / tr.REQUEST)
    ledger = {str(r.get("candidate_id")): r for r in _ledger_rows(task, request)}
    held = {fact_key(ledger[row[0]].get("claim_id"), ledger[row[0]].get("verified_target_excerpt")
                     or ledger[row[0]].get("original_excerpt")) for row in rows if row and row[0] in ledger}
    placeholder = {row[0] for row in rows if row and row[0] == "CF-001" and TODO in row and "CF-001" not in ledger}
    added = [row for row in candidates(task, request) if row[0] not in {r[0] for r in rows if r}
             and fact_key(row[5], ledger[row[0]].get("verified_target_excerpt") or ledger[row[0]].get("original_excerpt")) not in held]
    if not added and not placeholder:
        return []
    lines = text.splitlines()
    start = lines.index(tr.H_CANDIDATES)
    first = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("|"))
    end = next((i for i in range(first, len(lines)) if not lines[i].strip().startswith("|")), len(lines))
    width = len(header)
    new = ["| " + " | ".join((row + [TODO] * width)[:width]) + " |" for row in added]
    lines[end:end] = new
    if placeholder:
        lines = [line for line in lines if not (line.strip().startswith("| CF-001 |") and TODO in line and "CF-001" not in ledger)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [row[0] for row in added]


def scaffold(task: Path, *, write: bool = True) -> tuple[str, bool]:
    """Return the skeleton and whether it was written (only when the task has no 20 and no 15)."""
    text = render(task)
    target = task / tr.AUDIT
    if write and not target.exists() and not (task / tr.RETRIEVAL).exists():
        target.write_text(text, encoding="utf-8")
        return text, True
    return text, False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", type=Path, required=True, help="10_进行中下的文章任务目录")
    parser.add_argument("--print", dest="print_only", action="store_true", help="只打印骨架，不写文件")
    args = parser.parse_args()
    task = args.task.resolve()
    if tr._field(tr._read(task / tr.REQUEST), "知识准备记录协议") != tr.PROTOCOL:
        print("scaffold=skipped\nreason=该任务不是PR-2；旧任务按原15/20继续")
        return 0
    text, written = scaffold(task, write=not args.print_only)
    if written:
        print(f"scaffold=written\nfile={task / tr.AUDIT}\n"
              "next_action=只填写骨架中的“待填写”单元格，不改动章节、表头、大纲章节和检测类别；填完后运行run_knowledge_workflow.py")
    else:
        if not args.print_only and (task / tr.AUDIT).exists():
            print("scaffold=not_written\nreason=20已存在，不覆盖；以下骨架供逐项对照")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
