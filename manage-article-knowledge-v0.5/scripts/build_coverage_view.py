#!/usr/bin/env python3
"""Rebuild the human-readable current knowledge coverage view."""

from __future__ import annotations

import argparse
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path


OUTPUT_RELATIVE = Path("05_数据与审核/20_知识库覆盖与缺口/01_知识库覆盖与缺口.md")
MODULES = (
    ("客户知识", "公司概述", Path("03_正式知识/10_客户知识/10_公司概述")),
    ("客户知识", "产品介绍", Path("03_正式知识/10_客户知识/20_产品介绍")),
    ("客户知识", "解决方案", Path("03_正式知识/10_客户知识/30_解决方案")),
    ("客户知识", "合作案例", Path("03_正式知识/10_客户知识/40_合作案例")),
    ("客户知识", "行业知识与洞察", Path("03_正式知识/10_客户知识/50_行业知识与洞察")),
    ("客户知识", "FAQ", Path("03_正式知识/10_客户知识/60_FAQ")),
    ("客户知识", "其他", Path("03_正式知识/10_客户知识/70_其他")),
    ("外部公共知识", "行业知识与洞察", Path("03_正式知识/20_外部公共知识/50_行业知识与洞察")),
)
ARTICLE_STATES = ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成")
STATE_LABELS = {
    "10_进行中": "知识准备中",
    "20_等待终稿": "等待终稿",
    "30_等待Faithfulness": "等待Faithfulness",
    "40_已完成": "已完成",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def parse_field(text: str, label: str) -> str:
    match = re.search(rf"(?m)^\s*-\s*{re.escape(label)}[：:]\s*(.*?)\s*$", text)
    return match.group(1).strip() if match else ""


def parse_project_id(root: Path) -> str:
    path = root / "01_工作台/10_项目基础信息.md"
    if path.is_file():
        value = parse_field(read_text(path), "项目ID")
        if value:
            return value
    return root.name.split("_", 1)[0]


def markdown_cell(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split()) or "无"


def wikilink(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return f"[[../../{relative}|{path.stem}]]"


def source_counts(root: Path) -> tuple[dict[str, int], int]:
    db = root / "02_源资料/source-index.sqlite"
    counts = {"全文文字可搜索": 0, "部分内容可搜索": 0, "仅文件信息可搜索": 0, "未建立正文索引": 0}
    total = 0
    if not db.is_file():
        return counts, total
    connection = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    try:
        for status, count in connection.execute("SELECT searchability, COUNT(*) FROM sources GROUP BY searchability"):
            counts[str(status)] = int(count)
            total += int(count)
    finally:
        connection.close()
    return counts, total


def formal_files(root: Path, relative: Path) -> list[Path]:
    directory = root / relative
    if not directory.is_dir():
        return []
    return [path for path in sorted(directory.rglob("*.md")) if not path.name.startswith("00_")]


def claim_ids(text: str) -> set[str]:
    return set(re.findall(r"\bCLM-[A-Za-z0-9_.-]+", text))


def source_ids(text: str) -> set[str]:
    return set(re.findall(r"\bSRC-[A-Fa-f0-9]{8,}\b", text))


def knowledge_summary(path: Path) -> str:
    text = read_text(path)
    status = parse_field(text, "知识状态") or "状态未登记"
    kind = parse_field(text, "正式知识类型") or "类型未登记"
    titles = re.findall(r"(?m)^###\s+(CLM-[^｜\s]+)｜(.+?)\s*$", text)
    title_text = "、".join(title.strip() for _, title in titles[:3])
    if len(titles) > 3:
        title_text += f"等{len(titles)}条Claim"
    elif titles:
        title_text += f"（{len(titles)}条Claim）"
    else:
        title_text = "未识别到标准Claim标题"
    scopes = list(dict.fromkeys(re.findall(r"(?m)^- 适用范围[：:]\s*(.+?)\s*$", text)))
    scope_text = "；".join(scopes[:2]) if scopes else "具体范围见文件内Claim"
    return f"{kind}，{status}；覆盖{title_text}；适用：{scope_text}"


def source_summary(path: Path) -> list[str]:
    text = read_text(path)
    section = re.search(r"(?ms)^## 来源登记\s*\n(.*?)(?=^## |\Z)", text)
    if not section:
        return ["来源登记见正式知识文件"]
    names: list[str] = []
    for line in section.group(1).splitlines():
        if not line.strip().startswith("|") or re.match(r"\s*\|?\s*:?-{3,}", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] not in {"来源", "无"}:
            names.append(cells[0])
    return names or ["来源登记见正式知识文件"]


def parse_markdown_table(path: Path, heading: str) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    text = read_text(path)
    section = re.search(rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)", text)
    if not section:
        return []
    lines = [line.strip() for line in section.group(1).splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    return rows


def first_table_after_current_heading(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    text = read_text(path)
    match = re.search(r"(?ms)^## 当前[^\n]*\n(.*?)(?=^## |\Z)", text)
    if not match:
        return []
    lines = [line.strip() for line in match.group(1).splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    return rows


def open_mat_items(root: Path) -> list[dict[str, str]]:
    path = root / "05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md"
    rows = first_table_after_current_heading(path)
    text = read_text(path) if path.is_file() else ""
    result: list[dict[str, str]] = []
    for row in rows:
        if row.get("当前阶段", "") in {"已关闭", "已完成"}:
            continue
        item = dict(row)
        item_id = item.get("MAT ID", "")
        detail = re.search(rf"(?ms)^###\s+{re.escape(item_id)}(?:｜|\s).*?\n(.*?)(?=^###\s|\Z)", text) if item_id else None
        item["_detail"] = detail.group(1) if detail else ""
        result.append(item)
    return result


def governance_gaps(root: Path) -> list[dict[str, str]]:
    specs = (
        ("CUS", root / "05_数据与审核/30_异常与待决定/10_待客户补充/01_待客户补充事项.md"),
        ("ANM", root / "05_数据与审核/30_异常与待决定/30_源文与事实异常/01_源文与事实异常台账.md"),
    )
    result: list[dict[str, str]] = []
    for kind, path in specs:
        for row in first_table_after_current_heading(path):
            if row.get("当前阶段", "") not in {"已关闭", "已完成", "已解决"}:
                row = dict(row)
                row["kind"] = kind
                result.append(row)
    return result


def article_records(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for state in ARTICLE_STATES:
        directory = root / "04_文章任务" / state
        if not directory.is_dir():
            continue
        for task in sorted(path for path in directory.iterdir() if path.is_dir()):
            need = task / "10_文章知识需求.md"
            index = task / "35_写作素材来源索引.md"
            audit = task / "20_文章前知识审核.md"
            need_text = read_text(need) if need.is_file() else ""
            audit_text = read_text(audit) if audit.is_file() else ""
            records.append({
                "id": parse_field(need_text, "文章ID") or task.name,
                "title": parse_field(need_text, "标题") or task.name,
                "state": state,
                "claims": claim_ids(read_text(index)) if index.is_file() else set(),
                "excluded": parse_field(audit_text, "明确排除"),
            })
    return records


def related_articles(files: list[Path], articles: list[dict[str, object]]) -> list[dict[str, object]]:
    module_claims: set[str] = set()
    for path in files:
        module_claims.update(claim_ids(read_text(path)))
    return [article for article in articles if module_claims.intersection(article["claims"])] if module_claims else []


def related_mat(files: list[Path], mats: list[dict[str, str]]) -> list[dict[str, str]]:
    identifiers: set[str] = set()
    for path in files:
        identifiers.update(source_ids(read_text(path)))
    return [item for item in mats if identifiers.intersection(source_ids(" ".join(item.values())))]


def related_gaps(files: list[Path], gaps: list[dict[str, str]]) -> list[dict[str, str]]:
    identifiers: set[str] = set()
    for path in files:
        current = read_text(path)
        identifiers.update(claim_ids(current))
        identifiers.update(source_ids(current))
    return [item for item in gaps if any(identifier in " ".join(item.values()) for identifier in identifiers)]


def build_view(root: Path) -> str:
    project_id = parse_project_id(root)
    rebuilt_at = datetime.now().astimezone().isoformat(timespec="seconds")
    counts, total = source_counts(root)
    articles = article_records(root)
    mats = open_mat_items(root)
    gaps = governance_gaps(root)
    lines = [
        "# 知识库覆盖与缺口", "", f"- 项目ID：{project_id}", f"- 最近重建：{rebuilt_at}",
        "- 数据依据：正式知识、来源索引与台账、MAT/CUS/ANM、文章来源映射和文章前审核",
        "- 用途：当前知识覆盖和缺口的人话导航；不代表完备度评分，不替代Formal Claim或四类异常台账",
        "- 维护方式：由Codex在来源刷新、正式知识变更、文章知识准备完成、Faithfulness收尾和月度审核前自动重建；人工不直接改当前表",
        "", "## 来源可检索性", "", "| 项目 | 数量/状态 | 主要限制 | 依据 |", "|---|---:|---|---|",
        f"| 已登记源文件 | {total} | 具体文件名、路径、使用范围和关联文章见来源台账 | [[../../02_源资料/源资料与可检索性台账.md]] |",
        f"| 全文文字可搜索 | {counts.get('全文文字可搜索', 0)} | 可用于发现线索，Claim仍须回源核验 | [[../../02_源资料/source-index.sqlite]] |",
        f"| 部分内容可搜索 | {counts.get('部分内容可搜索', 0)} | 图片、嵌入对象或部分结构未进入正文索引 | [[../../02_源资料/源资料与可检索性台账.md]] |",
        f"| 仅文件信息可搜索 | {counts.get('仅文件信息可搜索', 0)} | 文章依赖时进入MAT，不把文件名当作证据 | [[../../02_源资料/源资料与可检索性台账.md]] |",
        f"| 未建立正文索引 | {counts.get('未建立正文索引', 0)} | 需按文章依赖和工具条件决定是否处理 | [[../../02_源资料/源资料与可检索性台账.md]] |",
        "", "## 知识库覆盖与缺口", "",
        "| 知识分区/标准模块 | 已有正式知识与可安全使用范围 | 已覆盖来源 | 尚未定向处理材料 | 明确缺少材料或事实 | 当前文章影响 |",
        "|---|---|---|---|---|---|",
    ]
    for partition, module, relative in MODULES:
        files = formal_files(root, relative)
        module_articles = related_articles(files, articles)
        module_mats = related_mat(files, mats)
        module_gaps = related_gaps(files, gaps)
        if files:
            knowledge = "；".join(f"{wikilink(root, path)}：{knowledge_summary(path)}" for path in files)
            sources = "；".join(dict.fromkeys(name for path in files for name in source_summary(path)))
        else:
            knowledge = "暂无正式知识；当前没有经核验Claim落入本模块"
            sources = "尚无正式知识对应来源；不代表来源台账中没有相关候选资料"
        if module_mats:
            unprocessed = "；".join(f"{item.get('MAT ID', 'MAT')} {item.get('事项名称', '')}（{item.get('代表文件/资料范围', '详见MAT台账')}）" for item in module_mats[:4])
        elif files:
            unprocessed = "未发现与当前正式知识来源直接关联的开放MAT；其他未命中资料仍按文章需要处理"
        else:
            unprocessed = "尚无材料被确定性归入本模块；需要时从来源台账按文章问题定向检索"
        explicit: list[str] = []
        for item in module_gaps[:3]:
            description = item.get("想确认什么") or item.get("发生了什么") or item.get("通俗问题") or "详见治理台账"
            explicit.append(f"{item.get('kind')}：{description}")
        for article in module_articles:
            if article["excluded"]:
                explicit.append(f"{article['title']}明确排除：{article['excluded']}")
        missing = "；".join(explicit[:4]) if explicit else "尚无该模块明确登记的CUS、ANM或文章前事实缺口"
        if module_articles:
            impact = "；".join(f"{article['title']}（{STATE_LABELS[str(article['state'])]}）" for article in module_articles)
        elif files:
            impact = "当前没有文章通过35映射使用本模块Claim"
        else:
            impact = "当前没有文章证据映射到本模块；不因空模块自动阻塞文章"
        lines.append("| " + " | ".join(map(markdown_cell, (f"{partition}／{module}", knowledge, sources, unprocessed, missing, impact))) + " |")
    return "\n".join(lines) + "\n"


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v05-coverage-test-") as temp:
        root = Path(temp) / "DEMO_示例知识库_v0.5"
        (root / "01_工作台").mkdir(parents=True)
        (root / "01_工作台/10_项目基础信息.md").write_text("# 项目基础信息\n\n- 项目ID：DEMO\n", encoding="utf-8")
        db = root / "02_源资料/source-index.sqlite"
        db.parent.mkdir(parents=True)
        connection = sqlite3.connect(db)
        connection.execute("CREATE TABLE sources (searchability TEXT)")
        connection.execute("INSERT INTO sources VALUES ('部分内容可搜索')")
        connection.commit()
        connection.close()
        formal = root / "03_正式知识/10_客户知识/50_行业知识与洞察/10_企业提供/示例行业知识.md"
        formal.parent.mkdir(parents=True)
        formal.write_text(
            "# 示例行业知识\n\n- 正式知识类型：企业提供行业知识\n- 知识状态：有效\n\n"
            "## 已核验Claim\n\n### CLM-DEMO-IND-001｜示例结构\n\n- Claim ID：CLM-DEMO-IND-001\n"
            "- 来源类型：客户源文件\n- 精确位置：SRC-ABCDEF123456\n\n## 来源登记\n\n"
            "| 来源 | 版本/日期 | 精确位置 | 证据类型 | 当前状态 |\n|---|---|---|---|---|\n"
            "| SRC-ABCDEF123456，示例培训资料.pptx | v1 | slide 2 | 客户源文件 | 已核验 |\n", encoding="utf-8")
        task = root / "04_文章任务/40_已完成/DEMO-ART-20260821-001_示例文章"
        task.mkdir(parents=True)
        (task / "10_文章知识需求.md").write_text("- 文章ID：DEMO-ART-20260821-001\n- 标题：示例行业文章\n", encoding="utf-8")
        (task / "35_写作素材来源索引.md").write_text("| 正式Claim ID |\n|---|\n| CLM-DEMO-IND-001 |\n", encoding="utf-8")
        (task / "20_文章前知识审核.md").write_text("- 明确排除：不得外推企业能力\n", encoding="utf-8")
        output = build_view(root)
        required = ("示例行业知识", "企业提供行业知识", "示例培训资料.pptx", "示例行业文章（已完成）", "不得外推企业能力")
        if any(value not in output for value in required):
            print("coverage self-test failed")
            return 1
        company_row = next(line for line in output.splitlines() if line.startswith("| 客户知识／公司概述"))
        if "示例行业文章" in company_row:
            print("coverage self-test failed: unrelated article repeated")
            return 1
    print("coverage self-test ok")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(run_self_test())
    if not args.project:
        raise SystemExit("--project is required")
    root = args.project.resolve()
    if not root.is_dir():
        raise SystemExit(f"Project not found: {root}")
    output = (args.output or (root / OUTPUT_RELATIVE)).resolve()
    text = build_view(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False, suffix=".tmp") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(output)
    print(f"output={output}")
    print(f"project={root}")


if __name__ == "__main__":
    main()
