#!/usr/bin/env python3
"""Convert a PR-1 15 plus its 20 into one PR-2 20 (知识准备与文章前审核).

Only the layout changes: every judgment, conclusion and governance entry is
carried over.  Hand-copied source details become pointers that the gates
re-read (EV-编号 for website evidence, 10#章节, SRC-ID@位置, RES:来源ID@[[路径]]).
Run on an in-progress task; completed tasks keep their historical files.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from preparation_record import compact, rows
from task_records import (
    AUDIT, CANDIDATE_HEADER, CHECK_HEADER, COMPLEX_HEADER, DETECTION_HEADER, FIELDS, GAP_HEADER,
    H_CANDIDATES, H_CHECKS, H_COMPLEX, H_CONCLUSION, H_DETECTION, H_GAPS, H_GOVERNANCE, H_LAYERS,
    H_MAT, H_OUTLINE, H_SPECIAL, LAYER_HEADER, MAT_HEADER, NONE_LABELS, NOT_INVOLVED, OUTLINE_HEADER,
    PROTOCOL, REQUEST, RETRIEVAL, TITLE, _render, _source_rows, _project, manifest_records,
)
from template_contract import parse_field, table_rows


def _link_target(value: str) -> tuple[str, str]:
    match = re.search(r"\[\[([^\]|]+)", value)
    raw = match.group(1) if match else ""
    path, _, anchor = raw.partition("#")
    return path, anchor


def _evidence_id(records: list[dict], url: str, block: str = "", excerpt: str = "") -> str:
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
    hits = [r for r in records if str(r.get("final_url", "")) == url
            and (not block or str(r.get("block_id", "")) == block)
            and (not excerpt or norm(str(r.get("excerpt", ""))) == norm(excerpt))]
    from task_records import same_evidence
    # The same block may have been captured once per question; those copies
    # are one piece of evidence.
    if hits and all(same_evidence(hits[0], other) for other in hits[1:]):
        return str(hits[0]["evidence_id"])
    return ""


def _gc_pointer(row: list[str], records: list[dict], task: Path, sources: dict) -> str:
    kind, source_id, entry, location, _sha, quote = row[4:10]
    if kind == "官网正文":
        return _evidence_id(records, entry, location, quote) or ""
    if kind == "需求范围":
        _path, anchor = _link_target(entry)
        return f"10#{anchor or location}"
    if kind in {"客户原件", "客户原件视觉"}:
        return f"{source_id}@{location}" + ("（视觉）" if kind == "客户原件视觉" else "")
    if kind == "外部RES原文":
        return f"RES:{source_id}@{entry.strip()}"
    if kind == "正式Claim复用":
        return f"{source_id}（复用，未回源）"
    return ""


def merged_text(task: Path) -> str:
    retrieval = (task / RETRIEVAL).read_text(encoding="utf-8-sig")
    audit = (task / AUDIT).read_text(encoding="utf-8-sig")
    if not compact(retrieval):
        raise ValueError("15还不是PR-1六节记录；先由知识库按PR-1整理后再合并")
    records = manifest_records_for(task, retrieval)
    sources = _source_rows(_project(task))
    mode = parse_field(retrieval, "知识准备模式") or parse_field(audit, "知识准备模式")
    run_label = "本轮知识重整运行ID" if mode == "outline_refresh" else "本轮知识检索运行ID"
    values = {
        "文章ID": parse_field(audit, "文章ID") or parse_field(retrieval, "文章ID"),
        "文章版本": parse_field(audit, "文章版本") or parse_field(retrieval, "文章版本"),
        "模板版本": parse_field(retrieval, "模板版本") or parse_field(audit, "审核模板版本"),
        "知识准备记录协议": PROTOCOL,
        "知识准备模式": mode,
        "大纲ID": parse_field(retrieval, "大纲ID"), "大纲版本": parse_field(retrieval, "大纲版本"),
        "重写模式": parse_field(retrieval, "重写模式"), "基线文章版本": parse_field(retrieval, "基线文章版本"),
        "官网正文抓取凭证": parse_field(retrieval, "官网正文抓取凭证") or "官网正文抓取凭证.json",
        "MAT依赖处理": parse_field(retrieval, "MAT依赖处理"),
        "审核日期": parse_field(audit, "审核日期") or parse_field(retrieval, "最近更新"),
        **{label: parse_field(audit, label) for label in ("结论", "明确排除", "未解决但不阻塞事项",
                                                          "计划写作素材", "计划写作素材来源索引")},
    }
    header = [TITLE, ""] + [f"- {label}：{values[label]}" for label in FIELDS]
    header.append(f"- {run_label}：{parse_field(retrieval, run_label) or parse_field(retrieval, '本轮知识检索运行ID')}")
    for label in ("证据模板版本", "知识准备规则版本", "批次ID"):
        value = parse_field(retrieval, label) or parse_field(audit, label)
        if value:
            header.append(f"- {label}：{value}")

    layers = table_rows(retrieval, "## 固定检索层状态")
    matrix = rows(retrieval, "大纲逐项检索与候选事实覆盖")
    questions: dict[str, list[str]] = {}
    for row in matrix:
        for ref in re.findall(r"CF-\d{3}", row[3] if len(row) > 3 else ""):
            questions.setdefault(ref, []).append(row[0])
    website = rows(retrieval, "官网正文核验")
    from sync_website_evidence import formal_claims
    claim_blocks = {item["claim_id"]: item["block"] for item in formal_claims(_project(task))}

    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
    candidates = []
    for row in rows(retrieval, "候选事实处置明细"):
        if len(row) < 9:
            continue
        pointer = ""
        reuse = re.search(r"复用有效Formal Claim（未回源）：(CLM-[A-Za-z0-9-]+)", " ".join(
            w[6] for w in website if len(w) == 7 and row[0] in w[5]))
        url = re.search(r"https?://[^\s；;|]+", row[2])
        claim = re.fullmatch(r"\s*(CLM-[A-Za-z0-9-]+)\s*", row[4])
        if reuse:
            # A reused Claim was not read this run, even when another candidate's capture shares its page.
            pointer = f"{reuse.group(1)}（复用，未回源）"
        elif url:
            page = url.group(0).rstrip("。，")
            block = re.search(r"(?a:\b)B\d{3,}(?a:\b)", row[2])
            claim_text = claim_blocks.get(claim.group(1), "") if claim else ""
            if block:
                pointer = _evidence_id(records, page, block.group(0))
            elif claim_text:
                # Two Claims can come from one page: take only a capture that quotes this candidate's Claim.
                quoted = {norm(str(r.get("excerpt", ""))) for r in records if str(r.get("final_url", "")) == page
                          and norm(str(r.get("excerpt", ""))) and norm(str(r.get("excerpt", ""))) in norm(claim_text)}
                pointer = _evidence_id(records, page, "", quoted.pop()) if len(quoted) == 1 else ""
            else:
                pointer = _evidence_id(records, page)
            if not pointer:
                hits = [w for w in website if len(w) == 7 and row[0] in w[5]]
                for hit in hits:
                    page_url = re.search(r"https?://[^\s；;|]+", hit[1])
                    pointer = _evidence_id(records, page_url.group(0) if page_url else "", "", hit[4]) or pointer
        basis = row[8] if row[5] in row[8] else f"{row[8]}；{row[5]}"
        candidates.append([row[0], row[1], pointer or row[2], "、".join(questions.get(row[0], [])) or "无",
                           row[3], row[4], row[6], row[7], basis])

    coverage = {r[0]: r for r in table_rows(audit, "## 大纲知识覆盖检查") if len(r) >= 6}
    sufficiency = {r[0]: r for r in table_rows(audit, "## 知识准备充分性复核") if len(r) >= 6}
    outline = []
    for row in matrix:
        if len(row) < 8:
            continue
        cov = coverage.get(row[0], [""] * 6)
        suf = sufficiency.get(row[0], [""] * 6)
        refs = re.findall(r"CF-\d{3}", row[3])
        outline.append([row[0], cov[2] or "部分覆盖", "、".join(refs) or "无",
                        row[1] if row[6] in {"", "无"} else f"{row[1]}；{row[6]}",
                        cov[4] or "无", suf[4] or "有明确边界", cov[5] or row[7]])

    detection = [[r[0], r[2], r[3], r[4]] for r in table_rows(audit, "## CUS / ANM检测结果") if len(r) >= 5]
    details = table_rows(audit, "## CUS / ANM逐项核对明细")
    gc_rows = {r[0]: r for r in table_rows(retrieval, "## CUS / ANM来源核验记录") if len(r) == 12}
    checks = []
    for index, detail in enumerate(details, 1):
        if len(detail) < 9:
            continue
        ids = re.findall(r"(?a:\b)GC-\d{3,}(?a:\b)", detail[3])
        pointers = [p for p in (_gc_pointer(gc_rows[i], records, task, sources) for i in ids if i in gc_rows) if p]
        gc = ids[0] if ids else f"GC-{index:03d}"
        scope = detail[2]
        if not pointers and detail[5] == "不适用":
            scope = NOT_INVOLVED
        checks.append([gc, detail[0], detail[1], scope, "；".join(dict.fromkeys(pointers)) or "—",
                       detail[5], detail[6], detail[7], detail[8]])

    def special(heading: str, legacy: str, convert) -> str:
        legacy_rows = rows(retrieval, legacy)
        real = [r for r in legacy_rows if r and r[0] != "无"]
        if not real:
            reason = next((r[3] if heading == H_MAT and len(r) > 3 else r[2] if len(r) > 2 else "" for r in legacy_rows), "")
            reason = reason if reason and reason not in {"无", "不适用"} else "本篇没有需要记录的事项"
            return f"{heading}\n\n- {NONE_LABELS[heading]}：无（{reason}）"
        header_map = {H_GAPS: GAP_HEADER, H_MAT: MAT_HEADER, H_COMPLEX: COMPLEX_HEADER}
        return f"{heading}\n\n" + _render(header_map[heading], [convert(r) for r in real])

    def complex_row(r):
        extraction = "同原件" if r[5].strip() == r[1].strip() else r[5]
        return [r[0], r[3], r[4], extraction, r[6], r[7], r[8]]

    summary = {r[0]: r[1] for r in rows(retrieval, "本轮知识准备结论") if len(r) >= 2}
    parts = [
        "\n".join(header), "",
        H_LAYERS, "", _render(LAYER_HEADER, [r[:4] for r in layers]), "",
        H_CANDIDATES, "", _render(CANDIDATE_HEADER, candidates), "",
        H_OUTLINE, "", _render(OUTLINE_HEADER, outline), "",
        H_GOVERNANCE, "", H_DETECTION, "", _render(DETECTION_HEADER, detection), "",
        H_CHECKS, "", _render(CHECK_HEADER, checks), "",
        H_SPECIAL, "",
        special(H_GAPS, "本轮待调研缺口复核", lambda r: [r[0], r[2], r[3], r[4], "已复核"]), "",
        special(H_MAT, "MAT依赖与资料选择", lambda r: [r[0], r[1], *r[3:9]]), "",
        special(H_COMPLEX, "复杂资料处理与原件核对", complex_row), "",
        H_CONCLUSION, "", summary.get("中文结论", ""), "",
    ]
    return "\n".join(parts)


def manifest_records_for(task: Path, retrieval: str) -> list[dict]:
    del retrieval  # the manifest name is the fixed task file
    return manifest_records(task)


def merge_task(task: Path, *, write: bool = True) -> str:
    text = merged_text(task)
    if write:
        (task / AUDIT).write_text(text, encoding="utf-8")
        (task / RETRIEVAL).unlink()
        request = task / REQUEST
        if request.is_file():
            request_text = request.read_text(encoding="utf-8-sig")
            if "知识准备记录协议：" in request_text:
                request_text = re.sub(r"(知识准备记录协议：)\S+", r"\g<1>" + PROTOCOL, request_text)
                request.write_text(request_text, encoding="utf-8")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="只打印合并后的20，不改文件")
    args = parser.parse_args()
    text = merge_task(args.task, write=not args.dry_run)
    if args.dry_run:
        print(text)
    else:
        print(f"merged={(args.task / AUDIT).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
