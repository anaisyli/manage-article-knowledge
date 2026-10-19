"""Trace fixed 15 governance records to current managed source evidence."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

HEADING = "## CUS / ANM来源核验记录"
HEADER = ("核验ID", "检测对象", "检测类别", "核验对象与范围", "来源类型", "来源ID", "来源入口", "精确位置", "来源SHA-256", "核对原文", "本轮运行ID", "核验说明")
PROTOCOL = "GC-1"
_source_project: ContextVar[Path | None] = ContextVar("governance_source_project", default=None)


@contextmanager
def original_sources(project: Path):
    """Trusted staging callers keep original managed sources read-only."""
    token = _source_project.set(project.resolve())
    try:
        yield
    finally:
        _source_project.reset(token)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def link_path(value: str, task: Path, project: Path) -> tuple[Path, str]:
    links = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", value)
    if len(links) != 1:
        raise ValueError("需要唯一明确的文件链接")
    raw, _, anchor = links[0].partition("#")
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [task / path, project / path]
    found = {p.resolve() for p in candidates if p.is_file()}
    if len(found) != 1:
        raise ValueError("来源文件不存在或入口不唯一")
    return found.pop(), anchor


def section(path: Path, anchor: str) -> str:
    text = path.read_text(encoding="utf-8-sig")
    if not anchor:
        return text
    headings = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    for index, h in enumerate(headings):
        if h.group(2).casefold() == anchor.casefold():
            end = next((n.start() for n in headings[index + 1:] if len(n.group(1)) <= len(h.group(1))), len(text))
            return text[h.end():end]
    raise ValueError("来源定位章节不存在")


def current_run(task: Path) -> str:
    from template_contract import parse_field
    path = task / "15_检索与知识准备记录.md"
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    return parse_field(text, "本轮知识检索运行ID") or parse_field(text, "本轮知识重整运行ID")


def source_excerpt(task: Path, project: Path, row: list[str]) -> str:
    """Re-read the specified source; a 15 summary cannot prove its own quote."""
    _, _, _, scope, kind, source_id, entry, location, fingerprint, quote, run, explanation = row
    project = _source_project.get() or project
    if not run or run != current_run(task):
        raise ValueError("核验记录不属于当前15运行ID")
    if not all(v.strip() and v not in {"待填写", "待核对", "待补充"} for v in (scope, location, quote, explanation)):
        raise ValueError("核验记录缺少对象、定位、原文或说明")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("来源SHA-256不是有效指纹")
    if kind == "需求范围":
        path, anchor = link_path(entry, task, project)
        if path != (task / "10_文章知识需求.md").resolve():
            raise ValueError("需求范围只能回读当前10，不能引用自建核验笔记")
        if digest(path.read_bytes()) != fingerprint:
            raise ValueError("需求范围原件指纹已变化")
        return section(path, anchor)
    if kind == "官网正文":
        path = task / "官网正文抓取凭证.json"
        records = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(records, list):
            raise ValueError("官网凭证必须为记录数组")
        candidates = [r for r in records if isinstance(r, dict) and
                      r.get("refresh_run_id") == run and r.get("website_id") == source_id and
                      r.get("final_url") == entry and r.get("block_id") == location and
                      normalized(str(r.get("excerpt", ""))) == normalized(quote)]
        if not candidates:
            raise ValueError("当前官网凭证的来源、区块、运行ID或引文不匹配")
        for r in candidates:
            block = normalized(str(r.get("block_text", "")))
            if (normalized(quote) in block and fingerprint == r.get("excerpt_sha256") == digest(normalized(quote).encode())
                    and re.fullmatch(r"[0-9a-f]{64}", str(r.get("response_sha256", "")))):
                return str(r["excerpt"])
        raise ValueError("官网引文指纹、原始响应指纹或连续区块不成立")
    path, anchor = link_path(entry, task, project)
    if kind == "外部RES原文":
        root = (project / "02_源资料/50_外部调研证据").resolve()
        if not path.is_relative_to(root) or path.name != "10_来源原文证据.md":
            raise ValueError("外部证据必须来自固定RES原文入口")
        if not (path.parent / "20_调研核验记录.md").is_file():
            raise ValueError("RES缺少受管调研核验记录")
        if digest(path.read_bytes()) != fingerprint:
            raise ValueError("RES原文指纹已变化")
        from template_contract import table_rows
        if not any(r and r[0] == source_id for r in table_rows(path.read_text(encoding="utf-8-sig"), "## 来源身份")):
            raise ValueError("外部来源ID未在RES来源身份表登记")
        return section(path, location)
    if kind not in {"客户原件", "客户原件视觉"}:
        raise ValueError("未知来源类型；不接受任意任务笔记或Formal Claim代替回源")
    db = project / "02_源资料/source-index.sqlite"
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        registered = conn.execute("SELECT absolute_path,sha256 FROM sources WHERE source_id=?", (source_id,)).fetchone()
    finally:
        conn.close()
    if not registered or Path(registered[0]).resolve() != path or registered[1] != fingerprint or digest(path.read_bytes()) != fingerprint:
        raise ValueError("原件路径、来源登记或当前SHA-256不一致")
    if kind == "客户原件视觉":
        from template_contract import table_rows
        retrieval = (task / "15_检索与知识准备记录.md").read_text(encoding="utf-8-sig")
        matches = [r for r in table_rows(retrieval, "## 复杂资料处理与原件核对") if len(r) == 9 and r[0] == source_id and r[8] == "已处理并核对" and location in r[6]]
        if len(matches) != 1:
            raise ValueError("视觉核验缺少15中对应原件位置及已处理并核对记录")
        extracted, extracted_anchor = link_path(matches[0][5], task, project)
        if not extracted.is_relative_to((project / "02_源资料").resolve()) or extracted == path:
            raise ValueError("视觉提取稿必须保存在受管源资料入口，不能用任务笔记")
        match = re.search(r"提取稿SHA-256[：:]\s*([0-9a-f]{64})", matches[0][6])
        if not match or digest(extracted.read_bytes()) != match.group(1):
            raise ValueError("视觉核验缺少已绑定的提取稿SHA-256或提取稿已变化")
        return section(extracted, extracted_anchor)
    from build_source_index import extract_file
    chunks, *_ = extract_file(path)
    selected = [text for loc, text in chunks if loc == location]
    if not selected:
        raise ValueError("原件提取中找不到精确位置；视觉内容须按复杂资料流程核验")
    return "\n".join(selected)


def record_errors(task: Path, project: Path, detector: str, category: str, source: str,
                  excerpt: str, result: str, scope: str, reason: str) -> list[str]:
    from template_contract import table_header, table_rows
    label = f"{detector}/{category}"
    path = task / "15_检索与知识准备记录.md"
    if not path.is_file():
        return [f"{label}缺少15来源核验记录"]
    text = path.read_text(encoding="utf-8-sig")
    if tuple(table_header(text, HEADING)) != HEADER:
        return [f"{label}15来源核验记录表头不符合固定模板"]
    ids = re.findall(r"\bGC-\d{3,}\b", source)
    if not ids or len(ids) != len(set(ids)):
        return [f"{label}20必须引用15中的唯一核验ID（来源冲突可引用双方ID）"]
    if category == "来源冲突" and result == "事实异常" and len(ids) < 2:
        return [f"{label}真实来源冲突须分别引用双方核验ID"]
    try:
        linked, anchor = link_path(source, task, project)
        if linked != path.resolve() or anchor != HEADING.removeprefix("## "):
            raise ValueError("20核验入口必须指向15固定来源核验表")
    except ValueError as exc:
        return [f"{label}：{exc}"]
    rows = table_rows(text, HEADING)
    errors = []
    for record_id in ids:
        selected = [r for r in rows if r and r[0] == record_id]
        if len(selected) != 1 or len(selected[0]) != len(HEADER):
            errors.append(f"{label}/{record_id}核验记录不存在、重复或列数错误")
            continue
        row = selected[0]
        if row[1:3] != [detector, category] or row[3] != scope:
            errors.append(f"{label}/{record_id}核验对象、类别或范围与20不一致")
        if row[4] == "需求范围" and result != "不适用":
            errors.append(f"{label}/{record_id}需求范围只能支持不适用，不能证明事实已核验或安全排除")
        if result == "不适用" and (category not in reason or category not in row[11]):
            errors.append(f"{label}/{record_id}不适用须说明该类别的具体范围，不得复用无关排除理由")
        try:
            evidence = source_excerpt(task, project, row)
            if normalized(row[9]) not in normalized(evidence) or normalized(row[9]) not in normalized(excerpt):
                raise ValueError("核验原文不在真实来源或20对应引文中")
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
            errors.append(f"{label}/{record_id}：{exc}；由知识库继续回源核验")
    return errors


def rebind_reused_scope(task: Path) -> None:
    """Explicit knowledge reuse may rebind unchanged scope quotes to new 10.

    This does not change source facts, review conclusions, or the old run.
    A changed/missing quoted requirement still fails the ordinary source gate.
    """
    from template_contract import table_rows
    retrieval = task / "15_检索与知识准备记录.md"
    text = retrieval.read_text(encoding="utf-8-sig")
    request = task / "10_文章知识需求.md"
    for row in table_rows(text, HEADING):
        if len(row) != len(HEADER) or row[4] != "需求范围":
            continue
        path, anchor = link_path(row[6], task, task.parents[2])
        if path != request.resolve() or normalized(row[9]) not in normalized(section(path, anchor)):
            raise ValueError("知识复用范围已改变，必须重新核验，不能只更新需求指纹")
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if re.match(rf"^\|\s*{re.escape(row[0])}\s*\|", line):
                lines[index] = line.replace(row[8], digest(request.read_bytes()))
        text = "\n".join(lines) + "\n"
    retrieval.write_text(text, encoding="utf-8")
