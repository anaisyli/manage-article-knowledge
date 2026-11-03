"""PR-2: one merged 20 file holds knowledge preparation and the pre-writing review.

New tasks (10 declares ``知识准备记录协议：PR-2``) keep a single
``20_文章前知识审核.md``.  Mechanical fields that the agent used to copy by
hand - page URL, block, date and excerpt, source paths, SHA-256, run IDs,
derived counts and cross-file links - are read from the current evidence
manifest, source index and ledgers instead.

Existing gates were written against the separate 15 and 20 files.  Rather than
re-implementing them, :func:`read_record` gives those gates an in-memory legacy
view of 15 and 20 built from the merged file.  The view is never written to
disk.  Tasks that still have a real 15 (PR-1 and older) are read unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path

REQUEST = "10_文章知识需求.md"
RETRIEVAL = "15_检索与知识准备记录.md"
AUDIT = "20_文章前知识审核.md"
MANIFEST = "官网正文抓取凭证.json"
PROTOCOL = "PR-2"
TITLE = "# 知识准备与文章前审核"
VIEW_MARKER = "<!-- PR-2 legacy view -->"
# outline_refresh declaration the PR-1 gate looks for in 15; a merged 20 may put it in any section.
FRESH_CONTEXT = "本轮知识上下文从空白开始"

FIELDS = (
    "文章ID", "文章版本", "模板版本", "知识准备记录协议", "知识准备模式", "大纲ID", "大纲版本",
    "重写模式", "基线文章版本", "官网正文抓取凭证", "MAT依赖处理", "审核日期", "结论",
    "明确排除", "未解决但不阻塞事项", "计划写作素材", "计划写作素材来源索引",
)
H_LAYERS = "## 一、固定检索层状态"
H_CANDIDATES = "## 二、候选事实"
H_OUTLINE = "## 三、大纲逐项覆盖与审核"
H_GOVERNANCE = "## 四、CUS / ANM核验与审核"
H_DETECTION = "### 检测结果"
H_CHECKS = "### 逐项核验"
H_SPECIAL = "## 五、缺口与特殊资料"
H_GAPS = "### 本轮待调研缺口"
H_MAT = "### MAT依赖与资料选择"
H_COMPLEX = "### 复杂资料处理与原件核对"
H_CONCLUSION = "## 六、结论说明"
HEADINGS = (H_LAYERS, H_CANDIDATES, H_OUTLINE, H_GOVERNANCE, H_SPECIAL, H_CONCLUSION)

LAYER_HEADER = ("检索层", "当前状态", "结果或未查原因", "下一步")
CANDIDATE_HEADER = ("候选事实ID", "独立事实摘要", "来源", "支持的大纲问题", "处置结果",
                    "Formal Claim或排除/治理入口", "当前归类模块", "Claim动作", "处置依据")
OUTLINE_HEADER = ("大纲章节", "覆盖状态", "候选事实ID", "覆盖说明与边界", "缺口或治理事项", "审核结论", "本篇写法")
DETECTION_HEADER = ("检测对象", "分类结论", "事项入口", "本篇处理")
CHECK_HEADER = ("核验ID", "检测对象", "检测类别", "核验对象与范围", "来源指针", "核对结论",
                "判断依据", "事项入口", "本篇处理")
GAP_HEADER = ("GAP ID", "本轮具体公共知识问题", "与当前大纲关系", "本轮处理和证据", "审核结论")
MAT_HEADER = ("MAT ID", "候选SRC ID", "关系/处理问题", "决定", "选取或排除范围", "决定依据", "决定方", "当前状态")
COMPLEX_HEADER = ("资料ID", "与本篇关系判断", "实际处理范围与方法", "提取稿入口", "原件核对位置与结论",
                  "MAT/ANM/CUS入口", "最终状态")
# A subsection with nothing to record is a single "- 标签：无" line (a reason is optional).
NONE_LABELS = {H_GAPS: "本轮待调研缺口", H_MAT: "MAT依赖与资料选择", H_COMPLEX: "复杂资料处理与原件核对"}
SUBTABLES = {H_GAPS: GAP_HEADER, H_MAT: MAT_HEADER, H_COMPLEX: COMPLEX_HEADER}

# Compact layout (SK-V064-011, SK-V064-012).  The agent writes only what a script cannot know: the
# candidate facts and where each goes, the coverage of each outline item, the CUS/ANM
# categories that have a signal, and exceptions.  Everything else is derived below and
# the gates still run against the same in-memory PR-1 view.  The full layout stays valid.
CANDIDATE_HEADER_COMPACT = CANDIDATE_HEADER[:6]
OUTLINE_HEADER_COMPACT = OUTLINE_HEADER[:5]
LAYERS = ("已有正式Claim", "客户源资料索引", "客户官网", "客户关联网站", "已有外部公共Claim", "新外部调研")
# 20 header fields that only repeat 10; 20 may omit them.
REQUEST_FIELDS = {"文章ID": "文章ID", "文章版本": "当前版本", "知识准备模式": "任务模式", "大纲ID": "大纲ID",
                  "大纲版本": "大纲版本", "重写模式": "重写模式", "基线文章版本": "基线文章版本"}
FIELD_DEFAULTS = {"明确排除": "无", "未解决但不阻塞事项": "无", "官网正文抓取凭证": MANIFEST,
                  "计划写作素材": "30_本篇知识库资料.md", "计划写作素材来源索引": "35_写作素材来源索引.md"}
EMPTY_CELLS = {"", "无", "—", "-", "待补充", "待填写"}
SEARCH_LOG = "02_源资料/source-search-log.jsonl"
PROJECT_INFO = "01_工作台/10_项目基础信息.md"

OUTLINE_STATUSES = {"已覆盖", "部分覆盖", "未覆盖", "无需事实支持"}
REVIEW_RESULTS = {"充分", "有明确边界", "无需事实支持"}
ADOPTED = {"已沉淀Formal Claim", "复用已有Formal Claim"}
NOT_INVOLVED = "本篇不涉及"
EV_RE = re.compile(r"(?a:\b)EV-\d{3,}(?a:\b)")
CLAIM_RE = re.compile(r"(?a:\b)CLM-[A-Za-z0-9-]+(?a:\b)")
CF_RE = re.compile(r"(?a:\b)CF-\d{3}(?a:\b)")
SRC_POINTER_RE = re.compile(r"^(SRC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)@(.+?)(（视觉）)?$")
REQUEST_POINTER_RE = re.compile(r"^10#(.+)$")
RES_POINTER_RE = re.compile(r"^RES:([^@\s]+)@(\[\[[^\]]+\]\])$")
UNFETCHED_CLAIM_RE = re.compile(r"^(CLM-[A-Za-z0-9-]+)（复用，未回源）$")
# A reused Claim whose page was also read this run: the two source states are different facts about
# the fact, and each needs one spelling (P-005-ART-20261030-001 CF-002 mixed four).
VERIFIED_CLAIM_RE = re.compile(r"^(CLM-[A-Za-z0-9-]+)（复用，本轮回源核验：(EV-\d{3,}(?:、EV-\d{3,})*)）$")
ENHANCED_LAYER_RE = re.compile(r"证据层级[：:]\s*(?:定义|事实|方法|条件|限制|效果)")

_cache: dict[tuple, tuple[str, str]] = {}


def split_pointers(value: str) -> list[str]:
    """Pointers are separated by "；"; a run of EV IDs may use "、" or ","."""
    items: list[str] = []
    for piece in re.split(r"[；;]", value):
        piece = piece.strip()
        if not piece:
            continue
        if re.fullmatch(r"EV-\d{3,}(?:\s*[、,，]\s*EV-\d{3,})*", piece):
            items.extend(EV_RE.findall(piece))
        else:
            items.append(piece)
    return items


def same_evidence(record: dict, other: dict) -> bool:
    """One page block captured again for another question is the same evidence."""
    keys = ("final_url", "block_id", "excerpt_sha256", "refresh_run_id")
    return all(str(record.get(k, "")) == str(other.get(k, "")) for k in keys)


# ---------------------------------------------------------------- basics

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def _field(text: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text, re.M)
    return match.group(1).strip() if match else ""


def _table(text: str, heading: str) -> tuple[tuple[str, ...], list[list[str]]]:
    """Header and rows of the first table directly under ``heading``."""
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.M)
    if not match:
        return (), []
    lines: list[str] = []
    for line in text[match.end():].splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        # Outer pipes are optional in Markdown: a row may omit the trailing one or, inside a table, the leading one.
        if stripped.startswith("|") or (lines and "|" in stripped):
            lines.append(stripped)
        elif lines and stripped:
            break
    if not lines:
        return (), []
    cells = [[c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", re.sub(r"^\||(?<!\\)\|$", "", line))]
             for line in lines]
    body = [row for row in cells[1:] if not all(re.fullmatch(r":?-{3,}:?", c) for c in row)]
    return tuple(cells[0]), body


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.M)
    if not match:
        return ""
    level = len(heading) - len(heading.lstrip("#"))
    tail = text[match.end():]
    end = re.search(rf"^#{{1,{level}}} ", tail, re.M)
    return tail[:end.start()] if end else tail


def _fresh_context_lines(text: str) -> str:
    """The outline_refresh declaration wherever the merged 20 states it, as plain view text.

    The view renders only the tables of sections 一–五, so a declaration written as prose
    under 一 was dropped and the legacy gate reported it missing although 20 had it.
    """
    lines = []
    for line in (line.strip() for line in text.splitlines() if FRESH_CONTEXT in line):
        # From a table row keep only the cell that states it, so the view gains no stray row.
        cells = [cell.strip() for cell in line.strip("|").split("|")] if line.startswith("|") else [line]
        lines.extend(cell for cell in cells if FRESH_CONTEXT in cell)
    return "\n\n".join(dict.fromkeys(lines)) + "\n\n" if lines else ""


def _render(header, rows) -> str:
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
                      *["| " + " | ".join(cell.replace("|", "／") for cell in row) + " |" for row in rows]])


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project(task: Path) -> Path:
    try:
        from governance_source_check import _source_project
        return _source_project.get() or task.parents[2]
    except ImportError:  # pragma: no cover
        return task.parents[2]


def is_merged(task: Path) -> bool:
    """Whether this task's records are one merged PR-2 20.

    The merged 20 declares PR-2 itself.  Before any record exists, 10's
    declaration decides.  Records already written in the 15+20 layout keep
    their legacy rules, so older tasks are never re-graded.
    """
    audit = task / AUDIT
    if audit.is_file():
        return _field(_read(audit), "知识准备记录协议") == PROTOCOL
    return not (task / RETRIEVAL).is_file() and _field(_read(task / REQUEST), "知识准备记录协议") == PROTOCOL


def record_is_file(path: Path) -> bool:
    """``path.is_file()`` for 15/20 that treats 15 as present inside a merged 20."""
    if path.name in {RETRIEVAL, AUDIT} and is_merged(path.parent):
        return (path.parent / AUDIT).is_file()
    return path.is_file()


def missing_records(task: Path, names) -> list[str]:
    """Required task files that are absent; a PR-2 task never reports 15.

    In a merged task 15 lives inside 20, so asking for a separate 15 would send
    the agent to create a file the format no longer has.
    """
    merged = is_merged(task)
    return [name for name in names
            if not (merged and name == RETRIEVAL) and not record_is_file(task / name)]


def read_record(path: Path) -> str:
    """Read 15/20; for a PR-2 task return the in-memory legacy view."""
    if path.name in {RETRIEVAL, AUDIT} and is_merged(path.parent) and (path.parent / AUDIT).is_file():
        retrieval, audit = legacy_views(path.parent)
        return retrieval if path.name == RETRIEVAL else audit
    return path.read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------- lookups

def manifest_records(task: Path) -> list[dict]:
    """Current website evidence, each with a stable ``evidence_id``."""
    name = _field(_read(task / AUDIT), "官网正文抓取凭证") or MANIFEST
    path = task / name
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(records, list):
        return []
    output = []
    for index, record in enumerate(records, 1):
        if isinstance(record, dict):
            record = dict(record)
            record.setdefault("evidence_id", f"EV-{index:03d}")
            output.append(record)
    return output


def _source_rows(project: Path) -> dict[str, dict]:
    db = project / "02_源资料/source-index.sqlite"
    if not db.is_file():
        return {}
    try:
        connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            rows = connection.execute(
                "SELECT source_id, relative_path, absolute_path, sha256, searchability FROM sources").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    return {row[0]: {"relative_path": row[1], "absolute_path": row[2], "sha256": row[3], "searchability": row[4]}
            for row in rows}


def _gap_ledger(project: Path) -> dict[str, dict]:
    path = project / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return {row.get("gap_key", ""): row for row in csv.DictReader(stream) if row.get("gap_key")}


def _special_rows(text: str, heading: str) -> tuple[list[list[str]], str]:
    """Rows of a 五-subsection, or ([], reason) for its "无（理由）" line; a bare "无" gives no reason."""
    body = _section(text, heading)
    reason = _field(body, NONE_LABELS[heading])
    if reason:
        return [], "" if reason == "无" else reason
    return _table(text, heading)[1], ""


# ---------------------------------------------------------------- compact layout

def _run_file(task: Path, mode: str) -> dict:
    name = "知识重整运行.json" if mode == "outline_refresh" else "知识检索运行.json"
    try:
        payload = json.loads((task / name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def meta_values(task: Path, text: str) -> tuple[dict[str, str], str, str]:
    """20 header fields with the ones that only repeat 10 or a fixed name filled in; plus run label and ID."""
    request = _read(task / REQUEST)
    meta = {label: _field(text, label) for label in FIELDS}
    for label, source in REQUEST_FIELDS.items():
        meta[label] = meta[label] or _field(request, source)
    for label, value in FIELD_DEFAULTS.items():
        meta[label] = meta[label] or value
    if not meta["模板版本"]:
        from template_contract import TEMPLATE_VERSION
        meta["模板版本"] = TEMPLATE_VERSION
    if meta["MAT依赖处理"] not in {"无", "待决定", "已决定"}:
        # A controlled value the 五 MAT table already decides; agents wrote a description here instead
        # (P-005-ART-20261029-002: “已处理并核对；仅采用页3、4…”) and delivery stayed blocked.
        mat_rows = _special_rows(text, H_MAT)[0]
        pending = any("待" in cells[3] or "待" in cells[7] for cells in ((list(row) + [""] * 8)[:8] for row in mat_rows))
        meta["MAT依赖处理"] = "无" if not mat_rows else "待决定" if pending else "已决定"
    mode = meta["知识准备模式"]
    run_label = "本轮知识重整运行ID" if mode == "outline_refresh" else "本轮知识检索运行ID"
    run = _run_file(task, mode)
    run_id = (_field(text, run_label) or _field(text, "本轮知识检索运行ID")
              or str(run.get("refresh_run_id") or run.get("research_run_id") or ""))
    return meta, run_label, run_id


def candidate_rows(task: Path, text: str) -> list[list[str]]:
    """二 as nine columns.  A compact row omits 归类模块, Claim动作 and 处置依据, which follow from
    the Claim it names and its disposition; an exclusion carries its reason in the entry column."""
    header, rows = _table(text, H_CANDIDATES)
    if header != CANDIDATE_HEADER_COMPACT:
        return [list(row) for row in rows]
    project = _project(task)
    output = []
    used: dict[str, list[str]] = {}
    for line in _table(text, H_OUTLINE)[1]:  # 三 decides which section uses a fact; 二 follows it
        for cf in CF_RE.findall(line[2] if len(line) > 2 else ""):
            used.setdefault(cf, []).append(line[0])
    for row in rows:
        row = list(row) + [""] * (6 - len(row))
        cf, _summary, source, questions, disposition, entry = row[:6]
        questions = questions.strip() or "；".join(used.get(cf, []))
        row[3] = questions
        claims = CLAIM_RE.findall(entry)
        if disposition in ADOPTED:
            module = _claim_module(project, claims[0]) if claims else ""
            action = "复用" if disposition == "复用已有Formal Claim" else "新建"
            basis = f"本轮核验：{source}支持{questions}"
        elif disposition == "排除":
            module, action, basis = "不适用", "排除", entry
        else:
            module, action, basis = "不适用", "治理", entry
        output.append(row[:6] + [module or ("外部公共知识" if any("-EXT-" in c for c in claims) else "不适用"),
                                 action, basis])
    return output


_modules: dict[tuple[str, str], str] = {}


def _claim_module(project: Path, claim_id: str) -> str:
    key = (str(project), claim_id)
    if key not in _modules:
        from batch_knowledge_run import _claim_path
        path = _claim_path(project, claim_id)
        module = ""
        if path is not None:
            from record_claim_reuse import claim_block
            module = _field(claim_block(path.read_text(encoding="utf-8-sig"), claim_id), "归类模块")
        _modules[key] = module
    return _modules[key]


def outline_rows(text: str) -> list[list[str]]:
    """三 as seven columns.  A compact row omits 审核结论 and 本篇写法, which follow from the coverage
    status; a covered item may also leave its explanation out."""
    header, rows = _table(text, H_OUTLINE)
    if header != OUTLINE_HEADER_COMPACT:
        return [list(row) for row in rows]
    output = []
    for row in rows:
        row = list(row) + [""] * (5 - len(row))
        label, status, refs, note, issue = (cell.strip() for cell in row[:5])
        if status == "已覆盖":
            note = note if note not in EMPTY_CELLS else f"{refs}支持该问题"
            result, usage = "充分", "按候选事实对应Claim的范围写"
        elif status == "无需事实支持":
            result, usage = "无需事实支持", f"不写事实性内容：{note}"
        else:
            result = "有明确边界"
            usage = (f"只写已覆盖部分：{note}" if status == "部分覆盖" else f"不写该节事实：{note}")
        output.append([label, status, refs or "无", note, issue or "无", result, usage])
    return output


def _search_window_start(task: Path, project: Path, run: dict) -> str:
    """Searches since the batch began count for this article; without a ledger, since the run file."""
    batch = str(run.get("batch_id", ""))
    if batch and batch != "不适用":
        try:
            from run_knowledge_workflow import resolve_ledger
            created = json.loads(resolve_ledger(project, batch).read_text(encoding="utf-8-sig")).get("created_at")
            if created:
                return str(created)
        except (OSError, ValueError, ImportError, AttributeError):
            pass
    for name in ("知识检索运行.json", "知识重整运行.json"):
        path = task / name
        if path.is_file():
            from datetime import datetime, timezone
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return ""


def _searches(task: Path, project: Path, run: dict) -> list[str]:
    from datetime import datetime
    start = _search_window_start(task, project, run)
    try:
        # The log keeps whole seconds; a search in the window's first second must still count.
        since = datetime.fromisoformat(start).replace(microsecond=0) if start else None
    except ValueError:
        since = None
    queries = []
    for line in _read(project / SEARCH_LOG).splitlines():
        try:
            entry = json.loads(line)
            when = datetime.fromisoformat(str(entry.get("time", "")))
        except (ValueError, TypeError):
            continue
        if since is None or when >= since:
            queries.append(str(entry.get("query", "")))
    return queries


def layer_rows(task: Path, text: str, candidates: list[list[str]], outline: list[list[str]],
               records: list[dict], gaps: list[list[str]]) -> tuple[list[list[str]], list[str]]:
    """一 with every layer the agent did not write derived from what this run left behind.

    A layer is derived only from evidence a script can see: reused Claims, captured page
    evidence, SRC pointers and the source search log, RES pointers and registered gaps.
    A layer with nothing to show and not covered by reused Claims is an error: the agent
    either runs that layer or writes its row with the reason.
    """
    written = {row[0].strip(): (list(row) + [""] * 4)[:4] for row in _table(text, H_LAYERS)[1] if row and row[0].strip()}
    project = _project(task)
    meta, _, _ = meta_values(task, text)
    run = _run_file(task, meta["知识准备模式"])
    pointers = [item for row in candidates if len(row) > 2 for item in split_pointers(row[2])]
    adopted = [row for row in candidates if len(row) > 5 and row[4] in ADOPTED]
    reused = sorted({c for row in adopted if row[4] == "复用已有Formal Claim" for c in CLAIM_RE.findall(row[5])})
    external = sorted({c for row in adopted for c in CLAIM_RE.findall(row[5]) if "-EXT-" in c})
    reuse_cfs = {row[0] for row in adopted if row[4] == "复用已有Formal Claim"}
    claims_cover = bool(outline) and all(
        row[1] == "无需事实支持" or (row[1] == "已覆盖" and set(CF_RE.findall(row[2])) <= reuse_cfs
                                  and CF_RE.findall(row[2]))
        for row in outline)
    primary = [str(r["evidence_id"]) for r in records if str(r.get("website_id", "PRIMARY-WEBSITE")) == "PRIMARY-WEBSITE"]
    related = [str(r["evidence_id"]) for r in records if str(r.get("website_id", "")).startswith("WEB-")]
    files = sorted({p.split("@", 1)[0] for p in pointers if p.startswith("SRC-")})
    research = sorted({m.group(1) for p in pointers for m in [RES_POINTER_RE.match(p)] if m})
    rows, errors = [], []
    # SK-V064-023: with a body section left partly or wholly uncovered, a hand-written row may not claim a
    # search that left no trace (P-005-ART-20261029-001 wrote 已检索 with no search logged for it, and
    # “复用Claim、未抓取” for the website while five H2s lacked facts).
    from template_contract import BODY_SECTION_RE, standard_depth_applies
    open_body = standard_depth_applies(task) and any(
        BODY_SECTION_RE.match(row[0]) and row[1] in {"部分覆盖", "未覆盖"} for row in outline if len(row) > 1)
    for layer in LAYERS:
        if layer in written:
            rows.append(written[layer])
            status = " ".join(written[layer][1:3])
            if open_body and layer == "客户源资料索引" and not files and not _searches(task, project, run):
                errors.append(f"{AUDIT}：一、固定检索层状态的客户源资料索引写了“{written[layer][1]}”，但本轮没有检索记录，"
                              "而本篇有部分/未覆盖的正文章节：用search_source_index.py检索这些章节的问题（检索会自动留痕）")
            elif (open_body and layer == "客户官网" and not primary
                  and not (("未命中" in status and re.search(r"https?://", status)) or re.search(r"无法访问|访问失败|拒绝访问", status))):
                errors.append(f"{AUDIT}：一、固定检索层状态的客户官网写了“{written[layer][1]}”，而本篇有部分/未覆盖的正文章节："
                              "读取相关产品或说明页并用capture_website_evidence.py登记凭证；读了但没有可用事实时写“已检索未命中”和具体URL，"
                              "无法访问时写原因")
            continue
        row, problem = None, ""
        if layer == "已有正式Claim":
            row = (["已检索并命中", f"复用有效Claim：{'、'.join(reused)}", "按Claim范围复用"] if reused else
                   ["已检索未命中", "本篇候选事实没有复用既有Formal Claim", "无"])
        elif layer == "客户源资料索引":
            queries = _searches(task, project, run)
            if files:
                row = ["已检索并命中", f"采用客户原件：{'、'.join(files)}", "按原件位置核验"]
            elif queries:
                shown = "、".join(dict.fromkeys(q for q in queries if q))
                row = ["已检索未命中", f"本轮检索{len(queries)}次未采用原件：{shown[:120]}", "无"]
            elif claims_cover:
                row = ["未检索（有效Claim已覆盖全部大纲问题）", "已有有效Claim覆盖，不重读来源层", "无"]
            else:
                problem = ("没有本轮检索记录：先用search_source_index.py检索未被有效Claim覆盖的问题"
                           "（检索会自动留痕），或在一、固定检索层状态写该层的实际状态和原因")
        elif layer == "客户官网":
            if primary:
                row = ["已检索并命中", f"读取官网正文凭证：{'、'.join(primary)}", "按凭证核验"]
            elif claims_cover:
                row = ["不适用（有效Claim已覆盖，未触发回源）", "无本轮抓取，沿用Claim已保存的证据", "无"]
            else:
                problem = ("本轮没有官网正文凭证：读取官网正文后用capture_website_evidence.py登记，"
                           "或在一、固定检索层状态写该层的实际状态（已检索未命中须写具体URL，无法访问须写原因）")
        elif layer == "客户关联网站":
            if related:
                row = ["已检索并命中", f"读取关联网站正文凭证：{'、'.join(related)}", "按凭证核验"]
            elif not re.search(r"(?a:\b)WEB-[A-Za-z0-9-]+-\d{3}", _read(project / PROJECT_INFO)):
                row = ["无已登记站点", "项目未登记关联网站", "无"]
            elif claims_cover:
                row = ["不适用（有效Claim已覆盖，未触发回源）", "无本轮抓取，沿用Claim已保存的证据", "无"]
            else:
                problem = ("项目已登记关联网站但本轮没有正文凭证：读取后登记凭证，"
                           "或在一、固定检索层状态写该层的实际状态和原因")
        elif layer == "已有外部公共Claim":
            row = (["已检索并命中", f"采用外部公共Claim：{'、'.join(external)}", "按Claim范围使用"] if external else
                   ["已检索未命中", "本篇没有采用外部公共Claim", "无"])
        else:
            gap_ids = [g[0] for g in gaps if g and g[0] not in EMPTY_CELLS]
            if research:
                row = ["已开展", f"本轮外部调研：{'、'.join(research)}", "按RES核验结果使用"]
            elif gap_ids:
                row = ["未开展（缺口已登记）", f"已登记缺口：{'、'.join(gap_ids)}", "按缺口台账推进"]
            else:
                row = ["未触发", "本篇没有登记待外部调研的公共知识缺口", "无"]
        if problem:
            errors.append(f"{AUDIT}：一、固定检索层状态的{layer}{problem}")
            row = ["待检索", problem, "按提示补齐"]
        rows.append([layer, *row])
    return rows, errors


def _signal_inputs(task: Path, text: str, candidates: list[list[str]], outline: list[list[str]],
                   records: list[dict]) -> dict:
    project = _project(task)
    request = _read(task / REQUEST)
    by_ev = {str(r["evidence_id"]): r for r in records}
    # Every 10 outline item, not only the rows 三 already has: a missing row must not hide its
    # signal until a later run.  An item 三 marks 无需事实支持 (opening, CTA placement) states no
    # fact, so its text is skipped.  H1/H2 markers are not numbers the article states.
    from template_contract import outline_labels
    written = {row[0].strip(): row[1].strip() for row in outline if len(row) > 1}
    no_facts = lambda label: any(status == "无需事实支持" and (name == label or name in label or label in name)  # noqa: E731
                                 for name, status in written.items())
    items = outline_labels(request) or [row[0] for row in outline if row and row[0] not in {"标题", "主问题"}]
    labels = [re.sub(r"(?<![A-Za-z0-9])H[1-6](?![0-9])\s*[:：]?\s*", "", label.lstrip("-*+ "))
              for label in items if not no_facts(label)]
    facts = [row[1] for row in candidates if len(row) > 1] + labels
    facts.append(_field(request, "标题"))
    pointers = [item for row in candidates if len(row) > 2 for item in split_pointers(row[2])]
    roots: dict[str, set[str]] = {}
    for row in candidates:
        # Two sources can only disagree on a value: count facts that state a number.
        if len(row) < 4 or not re.search(r"\d", row[1]):
            continue
        sources = set()
        for item in split_pointers(row[2]):
            record = by_ev.get(item)
            sources.add(str(record.get("final_url", item)) if record else item.split("@", 1)[0])
        for question in re.split(r"[、；;，,]", row[3]):
            if question.strip():
                roots.setdefault(question.strip(), set()).update(sources)
    language = _field(request, "目标语言")
    translated = []
    if language and not re.search(r"中文|汉语|Chinese|zh", language, re.I):
        from evidence_identity import original_evidence
        from batch_knowledge_run import _claim_path
        from record_claim_reuse import claim_block
        for claim in sorted({c for row in candidates if len(row) > 5 and row[4] in ADOPTED
                             for c in CLAIM_RE.findall(row[5])}):
            path = _claim_path(project, claim)
            if path is not None and re.search(r"[㐀-鿿]", original_evidence(
                    claim_block(path.read_text(encoding="utf-8-sig"), claim))):
                translated.append(claim)
    return dict(fact_texts=[f for f in facts if f], sources=pointers,
                partial_sections=[row[0] for row in outline if len(row) > 1 and row[1] == "部分覆盖"],
                multi_source_sections=[q for q, s in roots.items() if len(s) > 1],
                translated_claims=translated)


def check_rows(task: Path, text: str, candidates: list[list[str]], outline: list[list[str]],
               records: list[dict]) -> tuple[list[list[str]], list[str]]:
    """四 逐项核验 with a not-involved row added by the code for each category without a signal.

    The agent writes rows only for categories whose signal the code found (or that it checked
    anyway).  A signalled category without a row is an error naming the signal; the agent then
    checks it against a source, or writes 本篇不涉及/不适用 with its own reason.
    """
    from governance_signals import ANM, CUS, detect, not_involved_reason
    from prewrite_governance import CATEGORIES
    written = [(list(row) + [""] * 9)[:9] for row in _table(text, H_CHECKS)[1]]
    present = {(row[1], row[2]) for row in written}
    signals = detect(**_signal_inputs(task, text, candidates, outline, records))
    rows, errors = list(written), []
    number = 900
    for detector in (CUS, ANM):
        for category in CATEGORIES[detector]:
            if (detector, category) in present:
                continue
            signal = signals.get((detector, category))
            if signal:
                errors.append(f"{AUDIT}：{detector}/{category}有信号（{signal}），须在四、逐项核验写一行："
                              "带来源指针核对，或本篇确实不写该类事实时写“本篇不涉及”、结论“不适用”并说明不写什么")
                continue
            number += 1
            rows.append([f"GC-{number}", detector, category, NOT_INVOLVED, "—", "不适用",
                         not_involved_reason(category), "无", f"不涉及：本篇不写{category}相关内容"])
    return rows, errors


def detection_rows(text: str, checks: list[list[str]]) -> list[list[str]]:
    """四 检测结果; derived from 逐项核验 when the agent did not write it."""
    _, rows = _table(text, H_DETECTION)
    if rows:
        return [list(row) for row in rows]
    from prewrite_governance import ISSUE_RE
    output = []
    for detector in ("CUS候选检测", "ANM异常检测"):
        mine = [row for row in checks if row[1] == detector]
        issues = list(dict.fromkeys(i for row in mine for i in ISSUE_RE.findall(row[7])))
        fixed = [row for row in mine if row[5] == "自动修复并留痕"]
        pending = [row for row in mine if row[5] == "待核对"]
        if pending:
            output.append([detector, "待核对", "无", "仍有类别待核对"])
        elif issues:
            output.append([detector, "已登记", "、".join(issues), "按事项处理结果使用或排除"])
        elif fixed and detector == "ANM异常检测":
            output.append([detector, "自动修复并留痕", fixed[0][7], "按修复后的核验结果使用"])
        else:
            checked = [row[2] for row in mine if row[5] != "不适用"]
            output.append([detector, "未触发", "无",
                           f"已核对：{'、'.join(checked)}" if checked else "各类别均无信号，本篇不涉及"])
    return output


def conclusion_text(text: str, candidates: list[list[str]], outline: list[list[str]], checks: list[list[str]]) -> str:
    written = _section(text, H_CONCLUSION).strip()
    if written:
        return written
    count = lambda value: sum(1 for row in candidates if len(row) > 4 and row[4] == value)
    adopted = sum(1 for row in candidates if len(row) > 4 and row[4] in ADOPTED)
    statuses = {s: sum(1 for row in outline if len(row) > 1 and row[1] == s) for s in sorted(OUTLINE_STATUSES)}
    checked = [f"{row[1][:3]}/{row[2]}" for row in checks if row[3] != NOT_INVOLVED]
    return (f"本轮候选事实{len(candidates)}条：采用{adopted}条、排除{count('排除')}条、进入治理{count('进入治理')}条。"
            f"大纲覆盖：" + "，".join(f"{k}{v}项" for k, v in statuses.items() if v) + "。"
            + (f"CUS/ANM逐项核验：{'、'.join(checked)}。" if checked else "CUS/ANM各类别均无信号。")
            + "此记录不是Faithfulness判断。")


def native(task: Path) -> dict:
    """The merged 20 with derived parts filled in, and the problems found while deriving them."""
    key = ("native", *_fingerprint(task))
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        text = _read(task / AUDIT)
        records = manifest_records(task)
        candidates = candidate_rows(task, text)
        outline = outline_rows(text)
        gaps, _ = _special_rows(text, H_GAPS)
        layers, layer_errors = layer_rows(task, text, candidates, outline, records, gaps)
        checks, check_errors = check_rows(task, text, candidates, outline, records)
        meta, run_label, run_id = meta_values(task, text)
        _cache[key] = dict(meta=meta, run_label=run_label, run_id=run_id, candidates=candidates, outline=outline,
                           layers=layers, checks=checks, detection=detection_rows(text, checks),
                           conclusion=conclusion_text(text, candidates, outline, checks),
                           errors=layer_errors + check_errors)
    return _cache[key]


# ---------------------------------------------------------------- views

def _fingerprint(task: Path) -> tuple:
    project = _project(task)
    paths = [task / REQUEST, task / AUDIT, task / MANIFEST, project / "02_源资料/source-index.sqlite",
             project / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv", project / SEARCH_LOG,
             project / PROJECT_INFO]
    return (str(task.resolve()), str(project.resolve()),
            *[(p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else None for p in paths])


def legacy_views(task: Path) -> tuple[str, str]:
    key = _fingerprint(task)
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = _build_views(task)
    return _cache[key]


def _build_views(task: Path) -> tuple[str, str]:
    text = _read(task / AUDIT)
    project = _project(task)
    records = manifest_records(task)
    by_ev = {str(r["evidence_id"]): r for r in records}
    sources = _source_rows(project)
    record = native(task)
    meta, run_label, run_id = record["meta"], record["run_label"], record["run_id"]
    mode = meta["知识准备模式"]
    date = meta["审核日期"]
    layers, candidates, outline = record["layers"], record["candidates"], record["outline"]
    detection, checks = record["detection"], record["checks"]
    gaps, gap_reason = _special_rows(text, H_GAPS)
    mats, mat_reason = _special_rows(text, H_MAT)
    materials, material_reason = _special_rows(text, H_COMPLEX)
    conclusion = record["conclusion"]
    claims_of = {row[0]: set(CLAIM_RE.findall(row[5])) if len(row) > 5 and row[4] in ADOPTED else set()
                 for row in candidates if row}

    def source_text(pointer: str) -> str:
        parts = []
        for item in split_pointers(pointer):
            record = by_ev.get(item.strip())
            verified = VERIFIED_CLAIM_RE.match(item.strip())
            if verified:
                # The reuse is the fact's Claim; this run's read supplies the page the old table needs.
                records_read = [by_ev[ev] for ev in EV_RE.findall(verified.group(2)) if ev in by_ev]
                parts.extend(f"{r.get('final_url', '')}；{r.get('block_id', '')}；{r.get('position', '')}" for r in records_read)
                if not records_read:
                    parts.append(item.strip())
            elif record:
                parts.append(f"{record.get('final_url', '')}；{record.get('block_id', '')}；{record.get('position', '')}")
            else:
                parts.append(item.strip())
        return "；".join(p for p in parts if p)

    # 15 · fixed layers: an executed website layer must name its URLs.
    layer_rows = []
    for row in layers:
        row = list(row) + [""] * (4 - len(row))
        if row[0] in {"客户官网", "客户关联网站"} and row[1].startswith("已检索"):
            wanted = "PRIMARY-WEBSITE" if row[0] == "客户官网" else "WEB-"
            urls = list(dict.fromkeys(str(r.get("final_url", "")) for r in records
                                      if str(r.get("website_id", "PRIMARY-WEBSITE")).startswith(wanted)))
            if urls:
                row[2] = f"{row[2]}（{'；'.join(urls)}）"
        layer_rows.append(row[:4])

    # 15 · website rows come from the manifest, not from hand copies.
    website_rows = []
    covered_questions: list[str] = []
    for record in records:
        ev = str(record["evidence_id"])
        twins = {str(r["evidence_id"]) for r in records if same_evidence(r, record)}
        refs = [row for row in candidates if len(row) >= 9 and twins & set(EV_RE.findall(row[2]))]
        website_id = str(record.get("website_id", "PRIMARY-WEBSITE"))
        page = f"{record.get('title', '') or record.get('page_title', '') or '官网页面'}；{record.get('final_url', '')}"
        if website_id != "PRIMARY-WEBSITE":
            page += f"；{website_id}"
        if refs:
            result = "、".join(row[0] for row in refs)
            # The candidate's "支持的大纲问题" is the support scope the old
            # per-question website table had to restate row by row.
            disposition = "；".join(
                f"采用：{row[0]} {row[4]} {row[5]}：{row[8]}"
                + (f"；同一候选事实明确支持多个问题：{row[3]}" if re.search(r"[、；;]", row[3]) else "")
                for row in refs)
        else:
            result, disposition = "未命中（本轮读取但未采用）", "本轮读取的正文未形成候选事实，不采用"
        question = str(record.get("question", ""))
        covered_questions.append(question)
        website_rows.append([question, page, str(record.get("fetched_date", "")), str(record.get("position", "")),
                             str(record.get("excerpt", "")), result, disposition])
    reuse_claims = []
    for row in candidates:
        match = UNFETCHED_CLAIM_RE.match(row[2].strip()) if len(row) >= 9 and row[4] in ADOPTED else None
        if match:
            reuse_claims.append(match.group(1))
            website_rows.append([row[3] or row[0], f"Formal Claim {match.group(1)}", date, "Formal Claim已存证据",
                                 "复用Formal Claim已保存的最小原文证据，本轮未回源读取网页", row[0],
                                 f"复用有效Formal Claim（未回源）：{match.group(1)}"])
            covered_questions.append(row[3] or row[0])
    # A page read without a usable fact leaves no capture; the URL the 20 names in 一 is that read
    # (SK-V064-023 asks for exactly this row), so the view must not report the website as never visited.
    for row in layers:
        if row and row[0] == "客户官网" and not any(str(r.get("website_id", "PRIMARY-WEBSITE")) == "PRIMARY-WEBSITE"
                                                for r in records) and "未命中" in " ".join(row[1:3]):
            for url in dict.fromkeys(re.findall(r"https?://[^\s|；，、（）()]+", " ".join(row[1:4]))):
                website_rows.append(["官网检索（本轮未命中）", f"官网页面；{url}", date, "页面正文（未命中）",
                                     "本轮读取该页面正文，没有找到本篇大纲所需的事实，不采用网页内容", "未命中（本轮读取但未采用）",
                                     "本轮读取的正文未形成候选事实，不采用"])
    for row in outline:
        label = row[0].strip().strip("*`# ") if row else ""
        if not label or any(label == q or label in q or q in label for q in covered_questions if q):
            continue
        refs = CF_RE.findall(row[2]) if len(row) > 2 else []
        claims = sorted({c for ref in refs for c in claims_of.get(ref, set())} & set(reuse_claims))
        marker = claims[0] if claims else (reuse_claims[0] if not records and reuse_claims else "")
        disposition = (f"复用有效Formal Claim（未回源）：{marker}" if marker
                       else "不适用：该问题不使用本轮官网正文事实")
        website_rows.append([label, "不适用（该问题未读取官网正文）", date, "该问题无官网正文区块",
                             "该问题本轮官网正文未命中或不需要官网事实，不采用网页内容", "未命中", disposition])

    def counts(refs: set[str]) -> tuple[str, str]:
        claims = {c for ref in refs for c in claims_of.get(ref, set())}
        return str(len(refs)), str(len(claims))

    matrix = []
    for row in outline:
        row = list(row) + [""] * (7 - len(row))
        refs = set(CF_RE.findall(row[2]))
        candidate_count, claim_count = counts(refs)
        omitted = row[3] if row[4] in {"", "无"} else f"{row[4]}；{row[3]}"
        matrix.append([row[0], row[3], "、".join(sorted(refs)) or "未命中", row[2] or "无",
                       candidate_count, claim_count, omitted, row[6]])

    pr1_candidates = [[row[0], row[1], source_text(row[2]), row[4], row[5], row[8], row[6], row[7], row[8]]
                      for row in candidates if len(row) >= 9]

    gc_rows = []
    for row in checks:
        row = list(row) + [""] * (9 - len(row))
        resolved = pointer_rows(task, row, run_id)
        first = resolved[0] if resolved else None
        gc_rows.append(first[0] if first else [row[0], row[1], row[2], row[3], "不涉及", "无", "无", "无",
                                               "0" * 64, NOT_INVOLVED, run_id, row[6]])

    ledger = _gap_ledger(project)
    gap_rows = [[g[0], f"当前台账；{ledger.get(g[0], {}).get('status', '未登记')}", g[1], g[2], g[3]]
                for g in gaps if len(g) >= 5] or [["无"] * 5]
    mat_rows = []
    for m in mats:
        m = list(m) + [""] * (8 - len(m))
        paths = [sources.get(s, {}).get("absolute_path", s) for s in re.findall(r"SRC-[A-Za-z0-9-]+", m[1])]
        mat_rows.append([m[0], m[1], "；".join(paths) or "无", *m[2:8]])
    if not mat_rows:
        mat_rows = [["无", "无", "无", mat_reason or "本篇无版本候选", "无", "无", "无需选择", "Codex自动处理", "不适用"]]
    complex_rows = []
    for m in materials:
        m = list(m) + [""] * (7 - len(m))
        info = sources.get(m[0], {})
        path = info.get("absolute_path", "") or m[0]
        extraction = path if m[3] in {"同原件", ""} else m[3]
        complex_rows.append([m[0], path, info.get("searchability", "") or "按复杂资料流程处理",
                             m[1], m[2], extraction, m[4], m[5], m[6]])
    if not complex_rows:
        complex_rows = [["无", "无", material_reason or "本篇没有可能相关复杂资料", "不适用", "不适用",
                         "不适用", "不适用", "无", "不适用"]]

    adopted = [row for row in pr1_candidates if row[3] in ADOPTED]
    summary = [["本轮候选事实数", str(len(pr1_candidates))], ["采用事实数", str(len(adopted))],
               ["排除事实数", str(sum(r[3] == "排除" for r in pr1_candidates))],
               ["进入治理事实数", str(sum(r[3] == "进入治理" for r in pr1_candidates))],
               ["中文结论", re.sub(r"\s+", " ", conclusion) or "未填写"]]
    extra = "".join(f"- {label}：{_field(text, label)}\n" for label in ("证据模板版本", "知识准备规则版本", "批次ID")
                    if _field(text, label))
    retrieval = (
        "# 检索与知识准备记录\n\n"
        f"- 文章ID：{meta['文章ID']}\n- 文章版本：{meta['文章版本']}\n- 模板版本：{meta['模板版本']}\n"
        f"- 最近更新：{date}\n- MAT依赖处理：{meta['MAT依赖处理']}\n- 知识准备模式：{mode}\n"
        f"- 大纲ID：{meta['大纲ID']}\n- 大纲版本：{meta['大纲版本']}\n- 重写模式：{meta['重写模式']}\n"
        f"- 基线文章版本：{meta['基线文章版本']}\n- {run_label}：{run_id}\n"
        f"- 官网正文抓取凭证：{meta['官网正文抓取凭证']}\n{extra}- 知识准备记录协议：PR-1\n\n"
        f"## 固定检索层状态\n\n{_render(LAYER_HEADER, layer_rows)}\n\n"
        f"### 官网正文核验\n\n{_render(_website_header(), website_rows)}\n\n"
        f"## 大纲逐项检索与候选事实覆盖\n\n{_render(_matrix_header(), matrix)}\n\n"
        f"## 候选事实处置明细\n\n{_render(_pr1_candidate_header(), pr1_candidates)}\n\n"
        f"## CUS / ANM来源核验记录\n\n{_render(_gc_header(), gc_rows)}\n\n"
        "## 缺口与特殊资料处理\n\n"
        f"### 本轮待调研缺口复核\n\n{_render(_gap_legacy_header(), gap_rows)}\n\n"
        f"### MAT依赖与资料选择\n\n{_render(_mat_legacy_header(), mat_rows)}\n\n"
        f"### 复杂资料处理与原件核对\n\n{_render(_complex_legacy_header(), complex_rows)}\n\n"
        f"## 本轮知识准备结论\n\n{_render(('项目', '本轮结果'), summary)}\n\n"
        + (conclusion + "\n\n" if FRESH_CONTEXT in conclusion else _fresh_context_lines(text))
        + VIEW_MARKER + "\n"
    )

    claim_ids = sorted({c for row in adopted for c in CLAIM_RE.findall(row[4])})
    external = [c for c in claim_ids if "-EXT-" in c]
    link = "[[20_文章前知识审核.md#{}]]"
    revision = [[item, link.format(anchor), "已在合并记录中逐项记录", "无"] for item, anchor in (
        ("本轮六层检索", "一、固定检索层状态"), ("本轮官网正文与凭证", "二、候选事实"),
        ("本轮Claim盘点", "二、候选事实"), ("本轮知识准备结论", "六、结论说明"),
        ("30/35重新生成", "二、候选事实"))]
    coverage, sufficiency = [], []
    for row in outline:
        row = list(row) + [""] * (7 - len(row))
        refs = set(CF_RE.findall(row[2]))
        candidate_count, claim_count = counts(refs)
        claims = sorted({c for ref in refs for c in claims_of.get(ref, set())})
        omitted = row[4] if row[4] not in {"", "无"} else row[3]
        coverage.append([row[0], row[0], row[1], "、".join(claims) or "无", row[4] or "无", row[6]])
        sufficiency.append([row[0], candidate_count, claim_count, claim_count, row[5], omitted or "无"])
    complex_review = [[r[0], link.format("五、缺口与特殊资料"), r[8], r[6], f"已复核：{r[8]}"]
                      for r in complex_rows]
    signals = {"CUS候选检测": "已逐项核对客户能力、规格、认证、案例、商业条件、公开授权（见逐项核验）",
               "ANM异常检测": "已逐项核对版本、定位、提取、数值与单位、OCR、翻译与规范化、来源冲突、残缺与外推（见逐项核验）"}
    detection_rows = [[r[0], signals.get(r[0], r[0]), r[1], r[2], r[3]] for r in detection if len(r) >= 4]
    detail_rows = []
    for row in checks:
        row = list(row) + [""] * (9 - len(row))
        resolved = pointer_rows(task, row, run_id)
        quote = "；".join(r[0][9] for r in resolved) if resolved else NOT_INVOLVED
        detail_rows.append([row[1], row[2], row[3],
                            f"[[15_检索与知识准备记录.md#CUS / ANM来源核验记录]] {row[0]}",
                            re.sub(r"\s+", " ", quote)[:400], row[5], row[6], row[7], row[8]])
    audit = (
        "# 文章前知识审核\n\n"
        f"- 文章ID：{meta['文章ID']}\n- 文章版本：{meta['文章版本']}\n- 审核模板版本：{meta['模板版本']}\n"
        f"- 审核日期：{date}\n- 结论：{meta['结论']}\n- 可用Claim数：{len(claim_ids)}\n"
        f"- 客户来源：{len(claim_ids) - len(external)}\n- 外部来源：{len(external)}\n"
        f"- 明确排除：{meta['明确排除']}\n- 未解决但不阻塞事项：{meta['未解决但不阻塞事项']}\n"
        f"- 计划写作素材：{meta['计划写作素材']}\n- 计划写作素材来源索引：{meta['计划写作素材来源索引']}\n"
        f"- 知识准备模式：{mode}\n- 大纲ID：{meta['大纲ID']}\n- 大纲版本：{meta['大纲版本']}\n"
        f"- 重写模式：{meta['重写模式']}\n- 基线文章版本：{meta['基线文章版本']}\n- {run_label}：{run_id}\n{extra}\n"
        f"## 本轮知识准备复核\n\n{_render(('复核项', '15记录入口', '审核结论', '阻塞或排除'), revision)}\n\n"
        "## 大纲知识覆盖检查\n\n" + _render(("大纲章节", "知识问题", "覆盖状态", "已有证据/Claim", "缺口或治理事项", "本篇处理"), coverage) + "\n\n"
        "## 知识准备充分性复核\n\n" + _render(("大纲章节", "候选事实数", "已沉淀Claim数", "计划纳入30的事实块数", "覆盖结论", "未采用事实/缺口及入口"), sufficiency) + "\n\n"
        "## 复杂资料与原件核对复核\n\n" + _render(("资料ID", "15处理记录入口", "最终状态", "对当前事实/Claim影响", "本篇审核结论"), complex_review) + "\n\n"
        "## CUS / ANM检测结果\n\n" + _render(("检测对象", "已检查信号与来源", "分类结论", "事项与证据入口", "本篇处理"), detection_rows) + "\n\n"
        "## CUS / ANM逐项核对明细\n\n" + _render(("检测对象", "检测类别", "本篇事实或适用范围", "已核对来源与定位", "核对依据原文", "核对结论", "判断依据", "事项与证据入口", "本篇处理"), detail_rows) + "\n\n"
        + VIEW_MARKER + "\n"
    )
    return retrieval, audit


def _website_header():
    from template_contract import WEBSITE_EVIDENCE_HEADER
    return WEBSITE_EVIDENCE_HEADER


def _matrix_header():
    return ("大纲章节", "六层检索范围与结果", "命中来源与精确入口", "候选事实ID", "候选事实数",
            "已沉淀Claim数", "未采用事实/缺口及原因", "下一步")


def _pr1_candidate_header():
    from preparation_record import CANDIDATE_HEADER as pr1
    return pr1


def _gc_header():
    from governance_source_check import HEADER
    return HEADER


def _gap_legacy_header():
    from template_contract import CURRENT_GAP_REVIEW_HEADER
    return CURRENT_GAP_REVIEW_HEADER


def _mat_legacy_header():
    from preparation_record import MAT_HEADER as legacy
    return legacy


def _complex_legacy_header():
    from template_contract import COMPLEX_MATERIAL_HEADER
    return COMPLEX_MATERIAL_HEADER


# ---------------------------------------------------------------- GC pointers

def pointer_rows(task: Path, row: list[str], run_id: str) -> list[tuple[list[str], str]]:
    """Expand one merged GC row into legacy 12-column source rows.

    Returns ``(legacy_row, error)`` pairs; ``error`` is empty when the pointer
    resolved.  The legacy row carries the mechanically derived source type,
    entry, location, fingerprint and quote, so the existing source verifier
    can re-read the real source.
    """
    gc, detector, category, scope, pointer, _, reason = (row + [""] * 9)[:7]
    pointer = pointer.strip()
    if pointer in {"", "—", "-", "无"}:
        return []
    project = _project(task)
    output: list[tuple[list[str], str]] = []
    records = {str(r["evidence_id"]): r for r in manifest_records(task)}
    sources = None
    for item in split_pointers(pointer):
        base = [gc, detector, category, scope]
        if EV_RE.fullmatch(item):
            record = records.get(item)
            if not record:
                output.append((base + ["官网正文", "无", item, "无", "0" * 64, "", run_id, reason],
                               f"{item}不在当前官网正文抓取凭证中"))
                continue
            output.append((base + ["官网正文", str(record.get("website_id", "PRIMARY-WEBSITE")),
                                   str(record.get("final_url", "")), str(record.get("block_id", "")),
                                   str(record.get("excerpt_sha256", "")), str(record.get("excerpt", "")),
                                   run_id, reason], ""))
            continue
        match = REQUEST_POINTER_RE.match(item)
        if match:
            anchor = match.group(1).strip()
            request = task / REQUEST
            try:
                from governance_source_check import section as heading_section
                body = heading_section(request, anchor) if request.is_file() else ""
            except ValueError:
                body = ""
            quote = re.sub(r"\s+", " ", body).strip() or anchor
            output.append((base + ["需求范围", "不适用", f"[[{REQUEST}#{anchor}]]", anchor,
                                   _sha(request.read_bytes()) if request.is_file() else "0" * 64,
                                   quote, run_id, reason], "" if body.strip() else f"10中没有章节：{anchor}"))
            continue
        match = SRC_POINTER_RE.match(item)
        if match:
            sources = sources if sources is not None else _source_rows(project)
            source_id, location, visual = match.group(1), match.group(2).strip(), bool(match.group(3))
            info = sources.get(source_id)
            if not info:
                output.append((base + ["客户原件", source_id, source_id, location, "0" * 64, "", run_id, reason],
                               f"{source_id}未在来源索引登记"))
                continue
            quote = ""
            if not visual:
                try:
                    from build_source_index import extract_file
                    chunks, *_ = extract_file(Path(info["absolute_path"]))
                    quote = "\n".join(t for loc, t in chunks if loc == location)
                except Exception:  # noqa: BLE001 - reported by the source verifier
                    quote = ""
            output.append((base + ["客户原件视觉" if visual else "客户原件", source_id,
                                   f"[[{info['absolute_path']}]]", location, info["sha256"],
                                   quote or location, run_id, reason], ""))
            continue
        match = RES_POINTER_RE.match(item)
        if match:
            links = re.findall(r"\[\[([^\]|]+)", match.group(2))
            raw, _, anchor = links[0].partition("#")
            candidates = [Path(raw)] if Path(raw).is_absolute() else [task / raw, project / raw]
            found = next((p for p in candidates if p.is_file()), None)
            sha = _sha(found.read_bytes()) if found else "0" * 64
            output.append((base + ["外部RES原文", match.group(1), match.group(2), anchor, sha,
                                   _section(_read(found), "## " + anchor).strip() if found else "", run_id, reason],
                           "" if found else f"RES原文不存在：{raw}"))
            continue
        match = UNFETCHED_CLAIM_RE.match(item)
        if match:
            output.append(claim_reuse_row(task, project, base, match.group(1), run_id, reason))
            continue
        hint = "；复用未回源的Claim写CLM-ID（复用，未回源）" if CLAIM_RE.fullmatch(item) else ""
        output.append((base + ["未知", "无", item, "无", "0" * 64, "", run_id, reason],
                       f"无法识别的来源指针：{item}（可用EV-编号、10#章节、SRC-ID@位置、RES:来源ID@[[路径#章节]]、"
                       f"CLM-ID（复用，未回源）{hint}）"))
    return output


def claim_reuse_row(task: Path, project: Path, base: list[str], claim_id: str, run_id: str,
                    reason: str) -> tuple[list[str], str]:
    """Resolve a reused Formal Claim to its saved minimal original evidence.

    The Claim stands in for re-reading the source only when the reuse check
    rates it "可直接复用"; the row then carries the Claim's own saved excerpt
    and its fingerprint, never a fabricated reading of this run.
    """
    from batch_knowledge_run import _claim_path
    from evidence_identity import original_evidence
    from governance_source_check import claim_reuse_state, digest, normalized

    path = _claim_path(project, claim_id)
    evidence = ""
    if path is not None:
        from record_claim_reuse import claim_block
        evidence = original_evidence(claim_block(path.read_text(encoding="utf-8-sig"), claim_id))
    state = claim_reuse_state(task, project, claim_id)
    row = base + ["正式Claim复用", claim_id, f"[[{path}]]" if path else claim_id, claim_id,
                  digest(normalized(evidence).encode("utf-8")) if evidence else "0" * 64,
                  evidence, run_id, reason]
    if state["status"] != "可直接复用":
        problems = "；".join(state["problems"][:3])
        return row, f"{claim_id}不能作为未回源复用依据（{state['status']}：{problems}）；{state['action']}"
    return row, ""


# ---------------------------------------------------------------- native checks

def source_pointer_errors(rows: list[list[str]]) -> list[str]:
    """An adopted candidate's source is parsed, so it holds pointers only, each stating one source state."""
    errors = []
    for row in rows:
        if len(row) < 5 or row[4] not in ADOPTED:
            continue
        bad = [item for item in split_pointers(row[2])
               if not (EV_RE.fullmatch(item) or UNFETCHED_CLAIM_RE.match(item) or VERIFIED_CLAIM_RE.match(item)
                       or SRC_POINTER_RE.match(item) or REQUEST_POINTER_RE.match(item) or RES_POINTER_RE.match(item))]
        if bad or not row[2].strip():
            errors.append(f"{AUDIT}：{row[0]}的来源只写指针，不写网址或说明（{'、'.join(bad)[:60] or '空'}）。"
                          "未回源写“CLM-…（复用，未回源）”；已有Claim本轮又读了原页写“CLM-…（复用，本轮回源核验：EV-001）”；"
                          "本轮新事实写“EV-001”；原件写“SRC-…@位置”；外部写“RES:…@[[…]]”")
    return errors


def candidate_sync_errors(task: Path, rows: list[list[str]], outline: list[list[str]]) -> list[str]:
    """二 stays one row per fact, level with the ledger, and every adopted fact serves a named outline item.

    P-005-ART-20261030-001 reached 30/35 with eight facts while 三 cited two.  Which section uses a fact
    is a judgment, so this names what is unmapped and never fills it in.
    """
    from batch_knowledge_run import fact_key
    from scaffold_preparation_record import _ledger_rows
    ledger = {str(r.get("candidate_id")): fact_key(r.get("claim_id"), r.get("verified_target_excerpt") or r.get("original_excerpt"))
              for r in _ledger_rows(task, _read(task / REQUEST))}
    ids = {row[0] for row in rows if row}
    adopted = [row[0] for row in rows if len(row) > 4 and row[4] in ADOPTED]
    errors, holder, repeated = [], {}, set()
    for cf in adopted:
        key = ledger.get(cf)
        if key and key in holder:
            repeated.add(cf)
            errors.append(f"{AUDIT}：{cf}与{holder[key]}是同一事实（同一Claim、同一段原文），合并为一行，"
                          "本轮核验写进来源指针，不单列候选")
        elif key:
            holder[key] = cf
    held = {ledger[cf] for cf in ids if cf in ledger}
    for cf, key in sorted(ledger.items()):
        if cf not in ids and key not in held:
            errors.append(f"{AUDIT}：批次账本的{cf}没有进入二、候选事实；补一行并判断它支持哪个大纲项，或写明排除理由")
    mapped = {cf for row in outline if len(row) > 2 for cf in CF_RE.findall(row[2])}
    for cf in adopted:
        if cf not in mapped and cf not in repeated:
            errors.append(f"{AUDIT}：{cf}已采用，但三没有任何大纲项引用它：写进实际用到它的大纲项；"
                          "本篇不用时把处置改为“排除”并写理由，它就不进30/35")
    return errors


def structure_errors(task: Path) -> list[str]:
    """Shape and value checks of the merged file that a legacy view would hide."""
    path = task / AUDIT
    if not path.is_file():
        return []
    text = _read(path)
    label = AUDIT
    errors: list[str] = []
    if VIEW_MARKER in text:
        errors.append(f"{label}：兼容校验视图只能在内存使用，不得保存")
    if (task / RETRIEVAL).is_file():
        errors.append(f"{label}：PR-2任务只保留合并后的20，请删除单独的15")
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first != TITLE:
        errors.append(f"{label}：固定标题应为{TITLE}")
    # scaffold_preparation_record.py leaves judgment cells as 待填写; none may reach the gate unfilled.
    unfilled = [line.split("|")[1].strip() if line.startswith("|") else line.strip()[:30]
                for line in text.splitlines() if "待填写" in line and not line.startswith("（")]
    if unfilled:
        errors.append(f"{label}：骨架中仍有“待填写”未完成（{'、'.join(dict.fromkeys(unfilled))}）；"
                      "只填这些单元格，不改章节、表头、大纲章节和检测类别")
    record = native(task)
    for field in FIELDS:
        if not record["meta"][field]:
            errors.append(f"{label}：缺少固定字段：{field}")
    if not record["run_id"]:
        errors.append(f"{label}：缺少固定字段：{record['run_label']}")
    actual = re.findall(r"^## .+?$", text, re.M)
    if tuple(h.strip() for h in actual) != HEADINGS:
        errors.append(f"{label}：PR-2必须依次只有六个主小节：" + "、".join(h[3:] for h in HEADINGS))
    # 一, 检测结果 and 逐项核验 may be left out or hold only exception rows; 二 may be empty.
    for heading, headers, required in ((H_LAYERS, (LAYER_HEADER,), False),
                                       (H_CANDIDATES, (CANDIDATE_HEADER, CANDIDATE_HEADER_COMPACT), False),
                                       (H_OUTLINE, (OUTLINE_HEADER, OUTLINE_HEADER_COMPACT), True),
                                       (H_DETECTION, (DETECTION_HEADER,), False), (H_CHECKS, (CHECK_HEADER,), False)):
        found, rows = _table(text, heading)
        if found and found not in headers:
            errors.append(f"{label}：{heading.lstrip('# ')}固定表头不符，应为"
                          + "，或".join(" | ".join(h) for h in headers))
        elif required and not rows:
            errors.append(f"{label}：{heading.lstrip('# ')}必须至少有一行真实记录")
    for heading, header in SUBTABLES.items():
        body = _section(text, heading)
        if not re.search(rf"^{re.escape(heading)}\s*$", text, re.M):
            errors.append(f"{label}：缺少小节{heading.lstrip('# ')}")
            continue
        reason = _field(body, NONE_LABELS[heading])
        if reason:
            # The template says the reason may be left out; when given it may follow in brackets or after
            # ordinary punctuation (“无（理由）”“无。理由”).  Anything else is a real record and needs the table.
            if not re.fullmatch(r"无(?:（.+）|[。；;，,：:.、\s].*)?", reason):
                errors.append(f"{label}：{NONE_LABELS[heading]}没有记录时写“无”")
            continue
        found, rows = _table(text, heading)
        if found != header or not rows:
            errors.append(f"{label}：{heading.lstrip('# ')}须为固定表头的表格，或写“- {NONE_LABELS[heading]}：无”")
    records = {str(r["evidence_id"]) for r in manifest_records(task)}
    candidate_header, candidates = _table(text, H_CANDIDATES)
    ids = [row[0] for row in candidates if row]
    for row in candidates:
        if len(row) != len(candidate_header):
            errors.append(f"{label}：候选事实存在列数错误的数据行")
            continue
        for ev in EV_RE.findall(row[2]):
            if ev not in records:
                errors.append(f"{label}：{row[0]}引用的{ev}不在当前官网正文抓取凭证中")
        if not row[3].strip() and candidate_header != CANDIDATE_HEADER_COMPACT:
            errors.append(f"{label}：{row[0]}缺少支持的大纲问题")
        if candidate_header == CANDIDATE_HEADER_COMPACT and row[4] in {"排除", "进入治理"} \
                and not re.search(r"[㐀-鿿]{4,}|(?:GAP|CUS|MAT|ANM)-", row[5]):
            errors.append(f"{label}：{row[0]}{row[4]}时在“Formal Claim或排除/治理入口”写排除理由或事项编号")
    outline_header, outline = _table(text, H_OUTLINE)
    compact = outline_header == OUTLINE_HEADER_COMPACT
    from template_contract import BODY_SECTION_RE, ENHANCED_MARKER, standard_depth_applies
    if standard_depth_applies(task):
        errors.extend(source_pointer_errors(candidates))
        errors.extend(candidate_sync_errors(task, candidates, outline))
        if ENHANCED_MARKER in _read(task / REQUEST):
            # 加强 means the evidence must fit what the reader's section asks: a definition does not
            # answer a method or an effect, and the gate cannot tell, so the record has to say it.
            errors.extend(
                f"{label}：{row[0]}（知识准备：加强）的覆盖说明须写“证据层级：定义/事实/方法/条件/限制/效果”和“仍缺：…”，"
                "定义性证据不能代替方法或效果证据；写法见模板"
                for row in outline if len(row) > 3 and BODY_SECTION_RE.match(row[0])
                and row[1] in {"部分覆盖", "未覆盖"} and not (ENHANCED_LAYER_RE.search(row[3]) and re.search(r"仍缺[：:]", row[3])))
    for row in outline:
        if len(row) != len(outline_header):
            errors.append(f"{label}：大纲逐项覆盖与审核存在列数错误的数据行")
            continue
        if row[1] not in OUTLINE_STATUSES:
            errors.append(f"{label}：{row[0]}的覆盖状态须为" + "/".join(sorted(OUTLINE_STATUSES)))
        if not compact and row[5] not in REVIEW_RESULTS:
            errors.append(f"{label}：{row[0]}的审核结论须为" + "/".join(sorted(REVIEW_RESULTS)))
        unknown = set(CF_RE.findall(row[2])) - set(ids)
        if unknown:
            errors.append(f"{label}：{row[0]}引用不存在的候选事实：{'、'.join(sorted(unknown))}")
        if not CF_RE.findall(row[2]) and row[2] != "无":
            errors.append(f"{label}：{row[0]}没有候选事实时候选事实ID写“无”")
        if compact:
            # Only an item that is not fully covered needs its boundary and where the gap went.
            if row[1] == "已覆盖" and not CF_RE.findall(row[2]):
                errors.append(f"{label}：{row[0]}标已覆盖时须写支持它的候选事实ID")
            if row[1] in {"部分覆盖", "未覆盖"} and (row[3].strip() in EMPTY_CELLS or row[4].strip() in EMPTY_CELLS):
                errors.append(f"{label}：{row[0]}{row[1]}时须写覆盖说明与边界，以及缺口或治理事项"
                              "（GAP/CUS/MAT/ANM编号，或“不构成知识问题：理由”）")
            if row[1] == "无需事实支持" and row[3].strip() in EMPTY_CELLS:
                errors.append(f"{label}：{row[0]}无需事实支持时须在覆盖说明写为什么不需要事实")
    _, checks = _table(text, H_CHECKS)
    seen: set[str] = set()
    for row in checks:
        if len(row) != len(CHECK_HEADER):
            errors.append(f"{label}：逐项核验存在列数错误的数据行")
            continue
        if not re.fullmatch(r"GC-\d{3,}", row[0]) or row[0] in seen:
            errors.append(f"{label}：核验ID须为唯一GC-三位流水号：{row[0] or '空'}")
        seen.add(row[0])
    errors.extend(record["errors"])
    return errors


def governance_rows(task: Path) -> list[tuple[list[str], list[str]]]:
    """Merged GC rows (written plus code-recorded not-involved) as legacy 20 detail rows plus their source errors."""
    record = native(task)
    run_id = record["run_id"]
    project = _project(task)
    output = []
    from governance_source_check import source_excerpt
    for row in record["checks"]:
        row = list(row) + [""] * (9 - len(row))
        gc, detector, category, scope, pointer, result, reason, entry, handling = row[:9]
        label = f"{detector}/{category}/{gc}"
        errors: list[str] = []
        resolved = pointer_rows(task, row, run_id)
        if not resolved:
            if scope != NOT_INVOLVED or result != "不适用":
                errors.append(f"{label}：只有核验对象写“{NOT_INVOLVED}”且结论为不适用时才可不写来源指针")
        for legacy, error in resolved:
            if error:
                errors.append(f"{label}：{error}")
                continue
            if legacy[4] == "需求范围" and result != "不适用":
                errors.append(f"{label}：需求范围只能支持不适用，不能证明事实已核验或安全排除")
            try:
                source_excerpt(task, project, legacy)
            except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
                errors.append(f"{label}：{exc}；由知识库继续回源核验")
        if result == "不适用" and category not in reason + handling:
            errors.append(f"{label}：不适用须说明该类别的具体范围，不得复用无关排除理由")
        excerpt = "；".join(r[0][9] for r in resolved) or NOT_INVOLVED
        output.append(([detector, category, scope, pointer or NOT_INVOLVED, excerpt, result, reason, entry, handling],
                       errors))
    return output
