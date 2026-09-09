#!/usr/bin/env python3
"""Shared MAT formalization, parsing, and lifecycle helpers for v0.6."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


MAT_LEDGER_RELATIVE = Path(
    "05_数据与审核/30_异常与待决定/20_源资料处理/01_源资料处理台账.md"
)
MAT_STATUSES = {
    "待知识库专员判断",
    "知识库专员处理中",
    "等待材料或工具",
    "暂不处理",
    "已处理",
}
MAT_PUSH_STATUSES = {"不需要推送", "待推送", "已推送", "已升级"}
MAT_DEPENDENCY_VALUES = {"否", "是"}
MAT_BLOCKING_VALUES = {"否", "是"}
MAT_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z0-9][A-Za-z0-9_-]*)-MAT-\d{3,}(?!\d)"
)
SOURCE_ID_RE = re.compile(r"\bSRC-[A-Za-z0-9]+\b")
MAT_LIFECYCLE_COLUMNS = (
    "是否有当前文章依赖",
    "是否阻塞当前文章",
    "内容运营推送状态",
)


def markdown_escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def split_cells(line: str) -> list[str]:
    """Split a simple Markdown row while respecting escaped pipes."""
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|") and not raw.endswith("\\|"):
        raw = raw[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in raw:
        if char == "|" and not escaped:
            cells.append("".join(current).strip().replace("\\|", "|"))
            current = []
            continue
        current.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    cells.append("".join(current).strip().replace("\\|", "|"))
    return cells


def table_row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(markdown_escape(cell) for cell in cells) + " |"


def table_separator(width: int) -> str:
    return "|" + "|".join("---" for _ in range(width)) + "|"


def is_table_separator(line: str) -> bool:
    cells = split_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def current_table(path: Path, heading: str = "## 当前事项") -> dict[str, object] | None:
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    heading_index = next(
        (index for index, line in enumerate(lines) if line.strip() == heading), None
    )
    if heading_index is None:
        return None
    header_index = next(
        (
            index
            for index in range(heading_index + 1, len(lines))
            if lines[index].strip().startswith("|")
            and index + 1 < len(lines)
            and is_table_separator(lines[index + 1])
        ),
        None,
    )
    if header_index is None:
        return None
    separator_index = header_index + 1
    end_index = separator_index + 1
    while end_index < len(lines) and lines[end_index].strip().startswith("|"):
        end_index += 1
    header = split_cells(lines[header_index])
    rows: list[list[str]] = []
    for line in lines[separator_index + 1 : end_index]:
        cells = split_cells(line)
        if len(cells) == len(header) and any(cells):
            rows.append(cells)
    return {
        "lines": lines,
        "heading_index": heading_index,
        "header_index": header_index,
        "separator_index": separator_index,
        "end_index": end_index,
        "header": header,
        "rows": rows,
    }


def project_id(project_root: Path) -> str:
    profile = project_root / "01_工作台/10_项目基础信息.md"
    if profile.is_file():
        match = re.search(r"(?m)^\s*[-*]\s*项目ID[：:]\s*(\S+)\s*$", profile.read_text(encoding="utf-8-sig"))
        if match and match.group(1) not in {"待填写", "[项目ID]"}:
            return match.group(1).strip()
    name = project_root.name.split("_", 1)[0].strip()
    return name or "PROJECT"


def valid_mat_id(value: str) -> bool:
    return bool(MAT_ID_RE.fullmatch(value.strip()))


def candidate_reason(row: Mapping[str, object]) -> tuple[str, str]:
    """Return a stable machine grouping key and a Chinese human explanation."""
    relation = str(row.get("relation_note", ""))
    extension = "." + str(row.get("extension", "")).lstrip(".").lower()
    searchability = str(row.get("searchability", ""))
    embedded = int(row.get("office_embedded_count", 0) or 0)
    if "疑似跨格式或版本关系" in relation:
        return "version-candidates", "疑似跨格式或版本关系，需要先判断哪些版本可以作为当前依据"
    if extension in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"}:
        return "audio-video", "音视频尚未转写或核对，文章命中时需要确认可用内容"
    if extension in {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}:
        return "archives", "压缩包成员尚未展开核验，文章命中时只检查必要成员"
    if extension in {".doc", ".ppt", ".xls", ".wps", ".et", ".dps", ".rtf"} or embedded > 0:
        return "complex-office", "Office复杂结构、图片或嵌入对象尚未可靠处理"
    if searchability == "未建立正文索引":
        return "unindexed-text", "正文尚未建立可靠索引，文章命中时需要按需处理"
    return "complex-material", "资料需要按文章问题进行原件核验或额外处理"


def _detail_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    pattern = re.compile(r"(?ms)^###\s+([^\n]+)\n(.*?)(?=^###\s+|^##\s+|\Z)")
    for match in pattern.finditer(text):
        item_id_match = MAT_ID_RE.search(match.group(1))
        if item_id_match:
            blocks[item_id_match.group(0)] = match.group(0)
    return blocks


def _field(block: str, label: str) -> str:
    match = re.search(rf"(?m)^-\s*{re.escape(label)}[：:]\s*(.*?)\s*$", block)
    return match.group(1).strip() if match else ""


def _source_ids_for_block(block: str) -> set[str]:
    return set(SOURCE_ID_RE.findall(block))


def _existing_metadata(path: Path) -> dict[str, object]:
    table = current_table(path)
    if table is None:
        return {
            "text": "",
            "table": None,
            "rows_by_id": {},
            "details": {},
            "group_to_id": {},
            "source_to_id": {},
            "ids": set(),
        }
    text = path.read_text(encoding="utf-8-sig")
    header = list(table["header"])
    rows_by_id: dict[str, dict[str, str]] = {}
    ids: set[str] = set()
    for row in table["rows"]:
        if not row or row[0].startswith("[") or not valid_mat_id(row[0]):
            continue
        record = {header[index]: row[index] for index in range(min(len(header), len(row)))}
        rows_by_id[row[0]] = record
        ids.add(row[0])
    details = _detail_blocks(text)
    source_to_id: dict[str, str] = {}
    group_to_id: dict[str, str] = {}
    for item_id, block in details.items():
        for source_id in _source_ids_for_block(block):
            source_to_id[source_id] = item_id
        group = _field(block, "归组键（机器维护）") or _field(block, "机器归组键")
        if group:
            group_to_id[group] = item_id
    for item_id, record in rows_by_id.items():
        for source_id in _source_ids_for_block(" ".join(record.values())):
            source_to_id.setdefault(source_id, item_id)
    return {
        "text": text,
        "table": table,
        "rows_by_id": rows_by_id,
        "details": details,
        "group_to_id": group_to_id,
        "source_to_id": source_to_id,
        "ids": ids,
    }


def _next_mat_id(project: str, ids: set[str]) -> str:
    highest = 0
    for item_id in ids:
        match = re.search(r"-MAT-(\d+)$", item_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{project}-MAT-{highest + 1:03d}"


def _representative(rows: list[Mapping[str, object]]) -> str:
    names: list[str] = []
    for row in rows[:4]:
        path = str(row.get("relative_path", ""))
        name = Path(path).name or str(row.get("source_id", ""))
        names.append(f"{name}（{path}）")
    suffix = "" if len(rows) <= 4 else "等"
    return f"共{len(rows)}份资料，代表：" + "；".join(names) + suffix


def _default_mat_row(
    item_id: str,
    issue_name: str,
    reason: str,
    rows: list[Mapping[str, object]],
    updated: str,
    *,
    missing_existing: bool = False,
) -> dict[str, str]:
    if missing_existing:
        impact = "当前文章依赖待核对；文章命中且无法唯一判断时阻塞"
        next_action = "Codex补齐资料范围、处理依据和关闭条件；文章命中时先核验"
        stage = "待知识库专员判断"
    else:
        impact = "当前无文章依赖；文章命中且无法唯一处理时阻塞相关事实使用"
        next_action = "Codex在文章命中时按需核验；无法唯一判断再交内容运营"
        stage = "暂不处理"
    return {
        "MAT ID": item_id,
        "事项名称": issue_name,
        "代表文件/资料范围": _representative(rows),
        "资料数量": str(len(rows)),
        "通俗问题": reason,
        "当前文章影响": impact,
        "当前阶段": stage,
        "下一责任人/动作": next_action,
        "重开条件": "新文章命中、文件变化、工具变化或风险变化",
        "详情入口": f"[[#{item_id}｜{issue_name}]]",
        "最近更新": updated[:10],
        "是否有当前文章依赖": "否",
        "是否阻塞当前文章": "否",
        "内容运营推送状态": "不需要推送",
        "_reason": reason,
    }


def _detail_for(record: Mapping[str, str], source_ids: list[str], group_key: str, *, auto: bool) -> str:
    item_id = record["MAT ID"]
    issue_name = record.get("事项名称", "资料处理事项")
    source_list = "、".join(source_ids) if source_ids else "待补齐"
    auto_line = "是" if auto else "否"
    return (
        f"### {item_id}｜{issue_name}\n\n"
        "#### 先看结论\n\n"
        f"- 归组范围：{record.get('代表文件/资料范围', '')}\n"
        f"- 代表文件/资料范围：{record.get('代表文件/资料范围', '')}\n"
        f"- 资料数量：{record.get('资料数量', '')}\n"
        f"- 为什么合并为一项：这些资料具有相同的处理原因、责任人和关闭条件。\n"
        f"- 现在为什么不能正常处理：{record.get('通俗问题', '')}\n"
        f"- 是否影响当前文章：{record.get('当前文章影响', '')}\n"
        f"- 是否有当前文章依赖：{record.get('是否有当前文章依赖', '否')}\n"
        f"- 是否阻塞当前文章：{record.get('是否阻塞当前文章', '否')}\n"
        f"- 内容运营推送状态：{record.get('内容运营推送状态', '不需要推送')}\n"
        f"- 当前阶段：{record.get('当前阶段', '')}\n"
        f"- 下一责任人/动作：{record.get('下一责任人/动作', '')}\n"
        "- 关闭条件：已完成必要的提取、原件核对、版本选择和文章回写。\n"
        f"- 重开条件：{record.get('重开条件', '')}\n\n"
        "#### 资料与关联\n\n"
        "- 源资料总表：[[../../../02_源资料/源资料与可检索性台账.md]]\n"
        "- 稳定源资料根路径与相对路径：见来源台账对应资料行\n"
        f"- 完整资料ID清单：{source_list}\n"
        f"- 归组键（机器维护）：{group_key}\n"
        f"- 自动扫描生成：{auto_line}\n\n"
        "#### 处理与核验\n\n"
        "- 触发来源：初始化扫描 / 文章需求 / 月度维护 / 工具失败 / 其他\n"
        "- 已尝试方法与结果：待文章命中后按需处理\n"
        "- 当前处理稿（有才写）：\n"
        "- 覆盖范围和未处理范围：\n"
        "- 来源映射和审核结果：\n"
    )


def _ensure_mat_ledger(path: Path, project: str) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 源资料处理台账\n\n"
        f"- 项目ID：{project}\n"
        "- 文件用途：登记需要处理或判断的源资料；正式MAT不自动推送内容运营。\n"
        "- 当前待办入口：[[../../../01_工作台/20_当前待办.md]]\n"
        "- 来源总表：[[../../../02_源资料/源资料与可检索性台账.md]]\n\n"
        "## 当前事项\n\n"
        "| MAT ID | 事项名称 | 代表文件/资料范围 | 资料数量 | 通俗问题 | 当前文章影响 | 当前阶段 | 下一责任人/动作 | 重开条件 | 详情入口 | 最近更新 | 是否有当前文章依赖 | 是否阻塞当前文章 | 内容运营推送状态 |\n"
        "|---|---|---|---:|---|---|---|---|---|---|---|---|---|---|\n\n"
        "## 事项详情\n\n",
        encoding="utf-8",
    )


def formalize_scan_candidates(
    project_root: Path,
    rows: list[Mapping[str, object]],
    preserved_source_fields: Mapping[str, Mapping[str, str]],
    built_at: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Create/reuse formal MATs for scan candidates and return source mappings.

    The function is idempotent. It only creates missing scan-generated entries and
    never overwrites a human-maintained status, push decision, or next action.
    """
    project_root = project_root.resolve()
    mat_path = project_root / MAT_LEDGER_RELATIVE
    _ensure_mat_ledger(mat_path, project_id(project_root))
    metadata = _existing_metadata(mat_path)
    table = metadata["table"]
    if table is None:
        return {}, {}
    built_at = built_at or datetime.now().astimezone().isoformat(timespec="seconds")
    header = list(table["header"])
    for column in MAT_LIFECYCLE_COLUMNS:
        if column not in header:
            header.append(column)
    rows_by_id: dict[str, dict[str, str]] = dict(metadata["rows_by_id"])
    details: dict[str, str] = dict(metadata["details"])
    group_to_id: dict[str, str] = dict(metadata["group_to_id"])
    source_to_id: dict[str, str] = dict(metadata["source_to_id"])
    ids: set[str] = set(metadata["ids"])
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    dispositions: dict[str, str] = {}
    source_mat_map: dict[str, str] = {}

    for row in rows:
        source_id = str(row.get("source_id", ""))
        if not source_id:
            continue
        preserved = dict(preserved_source_fields.get(source_id, {}))
        explicit_id = preserved.get("mat", "").strip()
        if valid_mat_id(explicit_id):
            source_mat_map[source_id] = explicit_id
        candidate = bool(str(row.get("mat_candidate", "")).strip())
        duplicate_of = str(row.get("duplicate_of", "")).strip()
        disposition = preserved.get("mat_disposition", "").strip()
        if duplicate_of:
            dispositions[source_id] = disposition or f"完全重复，复用代表资料 {duplicate_of}，不建立MAT"
            continue
        if not candidate:
            if explicit_id and valid_mat_id(explicit_id):
                source_mat_map[source_id] = explicit_id
                dispositions[source_id] = disposition or f"已保留正式MAT：{explicit_id}"
            else:
                dispositions[source_id] = disposition or "当前无复杂处理风险，暂不建立MAT；文章命中时按需核验"
            continue
        if disposition.startswith(("无需建立MAT", "不建立MAT", "完全重复", "已复用")) and not explicit_id:
            dispositions[source_id] = disposition
            continue
        group_key, reason = candidate_reason(row)
        existing_id = explicit_id if valid_mat_id(explicit_id) else source_to_id.get(source_id, "")
        if not existing_id:
            existing_id = group_to_id.get(group_key, "")
        key = (existing_id or "scan", existing_id or group_key)
        grouped.setdefault(key, []).append(row)
        if existing_id:
            source_mat_map[source_id] = existing_id

    for (kind, key), candidate_rows in grouped.items():
        group_key, reason = candidate_reason(candidate_rows[0])
        item_id = key if kind != "scan" else _next_mat_id(project_id(project_root), ids)
        if kind == "scan":
            ids.add(item_id)
        existing = rows_by_id.get(item_id)
        if existing:
            record = dict(existing)
            if not record.get("是否有当前文章依赖"):
                record["是否有当前文章依赖"] = "否"
            if not record.get("是否阻塞当前文章"):
                record["是否阻塞当前文章"] = "否"
            if not record.get("内容运营推送状态"):
                record["内容运营推送状态"] = "不需要推送"
            if not record.get("最近更新"):
                record["最近更新"] = built_at[:10]
            # Auto-generated groups may grow when new files arrive. Human rows retain
            # their wording and status, but the machine-visible file count stays current.
            block = details.get(item_id, "")
            if "- 自动扫描生成：是" in block:
                record["代表文件/资料范围"] = _representative(candidate_rows)
                record["资料数量"] = str(len(candidate_rows))
            rows_by_id[item_id] = record
        else:
            reason_title = {
                "version-candidates": "疑似版本资料选择",
                "audio-video": "音视频资料按需核验",
                "archives": "压缩包成员按需核验",
                "complex-office": "复杂Office资料核验",
                "unindexed-text": "正文索引不足的资料处理",
                "complex-material": "复杂资料按需处理",
            }.get(group_key, "源资料按需处理")
            record = _default_mat_row(
                item_id,
                reason_title,
                reason,
                candidate_rows,
                built_at,
                missing_existing=False,
            )
            rows_by_id[item_id] = record
        source_ids = [str(item.get("source_id", "")) for item in candidate_rows]
        for source_id in source_ids:
            source_mat_map[source_id] = item_id
            dispositions[source_id] = f"已建立正式MAT：{item_id}"
        group_to_id[group_key] = item_id
        if item_id not in details:
            details[item_id] = _detail_for(rows_by_id[item_id], source_ids, group_key, auto=True)

    # Repair any source-ledger reference that points to a missing formal MAT.
    for source_id, preserved in preserved_source_fields.items():
        item_id = preserved.get("mat", "").strip()
        if valid_mat_id(item_id) and item_id not in rows_by_id:
            synthetic = _default_mat_row(
                item_id,
                "已登记MAT事项（需补齐处理依据）",
                "来源台账已有MAT引用，但正式MAT主表缺少记录，需要补齐归组和关闭条件",
                [],
                built_at,
                missing_existing=True,
            )
            rows_by_id[item_id] = synthetic
            ids.add(item_id)
            details[item_id] = _detail_for(synthetic, [source_id], "repaired-reference", auto=False)
            source_mat_map[source_id] = item_id
            dispositions.setdefault(source_id, f"已补齐正式MAT：{item_id}")

    # Rebuild only the current MAT table and append missing details; all other text
    # (including manual notes) stays byte-for-byte outside those controlled regions.
    lines = list(table["lines"])
    old_header = list(table["header"])
    old_rows = list(table["rows"])
    rebuilt_rows: list[list[str]] = []
    for old_row in old_rows:
        if not old_row or old_row[0].startswith("[") or not valid_mat_id(old_row[0]):
            continue
        item_id = old_row[0]
        record = rows_by_id.get(item_id, {old_header[index]: old_row[index] for index in range(min(len(old_header), len(old_row)))})
        rebuilt_rows.append([record.get(column, "") for column in header])
    existing_row_ids = {row[0] for row in rebuilt_rows if row}
    for item_id, record in rows_by_id.items():
        if item_id in existing_row_ids:
            continue
        rebuilt_rows.append([record.get(column, "") for column in header])
    replacement = [table_row(header), table_separator(len(header))]
    replacement.extend(table_row(row) for row in rebuilt_rows)
    start = int(table["header_index"])
    end = int(table["end_index"])
    lines[start:end] = replacement
    text = "\n".join(lines) + "\n"
    existing_detail_text = text
    for item_id, block in details.items():
        if re.search(rf"(?m)^###\s+{re.escape(item_id)}(?:[｜|]|\s)", existing_detail_text):
            continue
        existing_detail_text += "\n" + block.rstrip() + "\n"
    if existing_detail_text != mat_path.read_text(encoding="utf-8-sig"):
        mat_path.write_text(existing_detail_text, encoding="utf-8")
    return source_mat_map, dispositions


def source_ledger_fields(path: Path) -> dict[str, dict[str, str]]:
    """Read source ledger rows, including the MAT disposition column."""
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header: list[str] = []
    result: dict[str, dict[str, str]] = {}
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        if not header:
            header = cells
            continue
        if is_table_separator(line) or len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        source_id = row.get("资料ID", "").strip()
        if source_id:
            result[source_id] = row
    return result
