"""PR-1 compact preparation record; no archived package is read here."""
from __future__ import annotations
import re
from pathlib import Path

PROTOCOL = "PR-1"
HEADINGS = ("固定检索层状态", "大纲逐项检索与候选事实覆盖",
            "候选事实处置明细", "CUS / ANM来源核验记录",
            "缺口与特殊资料处理", "本轮知识准备结论")
CANDIDATE_HEADER = ("候选事实ID", "独立事实摘要", "来源与精确位置", "处置结果",
                    "Formal Claim或排除/治理入口", "本轮核验结论", "当前归类模块", "Claim动作", "处置依据")
MATERIAL_HEADER = ("资料ID", "文件名与稳定路径", "未索引内容/处理原因", "与本篇关系判断",
                   "实际处理范围与方法", "MinerU/提取稿入口", "原件核对位置与结论", "MAT/ANM/CUS入口", "最终状态")
MAT_HEADER = ("MAT ID", "候选SRC ID", "文件名与稳定路径", "关系/处理问题", "决定", "选取或排除范围", "决定依据", "决定方", "当前状态")
SUMMARY_ITEMS = ("本轮候选事实数", "采用事实数", "排除事实数", "进入治理事实数", "中文结论")

def compact(text: str) -> bool:
    return bool(re.search(r"^\s*-\s*知识准备记录协议[：:]\s*PR-1\s*$", text, re.M))

def section(text: str, title: str) -> str:
    match = re.search(r"^#{2,3} " + re.escape(title) + r"\s*$", text, re.M)
    if not match:
        return ""
    tail = text[match.end():]
    return re.split(r"^#{2,3} ", tail, maxsplit=1, flags=re.M)[0].strip()

def rows(text: str, title: str) -> list[list[str]]:
    lines = [line.strip() for line in section(text, title).splitlines() if line.strip().startswith("|")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]

def table(header, data) -> str:
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
                      *["| " + " | ".join(row) + " |" for row in data]])

def counts(text: str) -> dict[str, int]:
    data = [row for row in rows(text, "候选事实处置明细") if len(row) >= 5 and re.fullmatch(r"CF-\d{3}", row[0])]
    return {"本轮候选事实数": len(data),
            "采用事实数": sum(row[3] in {"已沉淀Formal Claim", "复用已有Formal Claim"} for row in data),
            "排除事实数": sum(row[3] == "排除" for row in data),
            "进入治理事实数": sum(row[3] == "进入治理" for row in data)}

def validation_view(text: str) -> str:
    """Expand only in memory for existing source/evidence validators."""
    if not compact(text) or "<!-- PR-1 validation view -->" in text:
        return text
    expanded = re.sub(r"^### ", "## ", text, flags=re.M)
    candidates = rows(text, "候选事实处置明细")
    hits = [[r[0], r[2], r[1], r[3]] for r in candidates if len(r) >= 5]
    hits += [[r[0], r[1], r[4], r[6]] for r in rows(text, "官网正文核验") if len(r) == 7]
    # Project only the compatibility columns; never write this view to disk.
    def project_table(title, width):
        nonlocal expanded
        pattern = r"(^## " + re.escape(title) + r"\s*\n)(.*?)(?=^## |\Z)"
        def project(match):
            lines = match[2].splitlines()
            return match[1] + "\n".join(
                "| " + " | ".join(line.strip().strip("|").split("|")[:width]).strip() + " |"
                if line.strip().startswith("|") else line for line in lines) + "\n"
        expanded = re.sub(pattern, project, expanded, flags=re.M | re.S)
    project_table("候选事实处置明细", 5)
    inventory = [[r[0], r[2], r[5], r[6], r[7], r[8]] for r in candidates if len(r) == 9]
    inventory = inventory or [["无", "无", "无候选事实", "不适用", "不适用", "本轮未发现候选事实"]]
    expanded += "\n## 来源命中记录\n\n" + table(("知识问题", "命中Claim/资料名称与入口", "相关理由", "处理结果"), hits or [["无"] * 4])
    expanded += "\n## 本轮事实与Claim盘点\n\n" + table(("本轮候选事实ID/当前Claim ID", "本轮重新打开的来源与精确位置", "本轮证据结论", "当前归类模块", "本轮处置", "依据"), inventory)
    return expanded + "\n<!-- PR-1 validation view -->\n"

def protocol_errors(text: str) -> list[str]:
    if not compact(text):
        return []
    errors = []
    if "<!-- PR-1 validation view -->" in text:
        errors.append("PR-1兼容校验视图只能在内存使用，不得保存到15")
    actual = re.findall(r"^## (.+?)\s*$", text, re.M)
    if tuple(actual) != HEADINGS:
        errors.append("PR-1必须仅有六个固定主小节，官网/GAP/特殊资料使用固定子小节")
    for title, header in (("候选事实处置明细", CANDIDATE_HEADER), ("复杂资料处理与原件核对", MATERIAL_HEADER), ("MAT依赖与资料选择", MAT_HEADER)):
        lines = [line for line in section(text, title).splitlines() if line.strip().startswith("|")]
        if not lines or tuple(c.strip() for c in lines[0].strip().strip("|").split("|")) != header:
            errors.append(f"PR-1的{title}固定表头不符")
    candidates = rows(text, "候选事实处置明细")
    seen = set()
    for row in candidates:
        if len(row) != 9 or any(not x.strip() for x in row):
            errors.append("PR-1候选事实须包含九列真实处置与核验记录")
            continue
        if not re.fullmatch(r"CF-\d{3}", row[0]) or row[0] in seen:
            errors.append("PR-1候选事实ID须为唯一CF三位流水号")
        seen.add(row[0])
        if row[3] not in {"已沉淀Formal Claim", "复用已有Formal Claim", "排除", "进入治理"}:
            errors.append(f"{row[0]}的处置结果无效")
        if row[7] not in {"新建", "复用", "更新", "拆分", "迁移", "失效", "排除", "治理"}:
            errors.append(f"{row[0]}的Claim动作无效")
        if re.search(r"90_归档|(?:^|[/\\])(?:15|20|30|35|50)_", row[2]):
            errors.append(f"{row[0]}的本轮来源不能是旧资料包")
        if row[3] == "进入治理" and not re.search(r"(?:GAP-|CUS-|MAT-|ANM-)", row[4]):
            errors.append(f"{row[0]}进入治理但缺少具体事项入口")
    summary = {r[0]: r[1] for r in rows(text, "本轮知识准备结论") if len(r) >= 2}
    for name, value in counts(text).items():
        if summary.get(name) != str(value):
            errors.append(f"PR-1本轮结论的{name}与明细不一致，应为{value}")
    if not re.search(r"[\u3400-\u9fff]", summary.get("中文结论", "")) or re.search(r"待.*补齐|待补充|占位", summary.get("中文结论", "")):
        errors.append("PR-1本轮结论须写中文实际结论")
    gap_rows = rows(text, "本轮待调研缺口复核")
    if not gap_rows:
        errors.append("PR-1须记录本轮GAP，未发现时填写完整无记录")
    for row in gap_rows:
        if len(row) != 5 or any(not x for x in row) or (row[0] != "无" and any(x in {"无", "不适用"} for x in row[1:])) or (row[0] == "无" and row != ["无"] * 5):
            errors.append("本轮GAP存在无关联编号或不完整问题/处理记录")
    gap_ids = {r[0] for r in gap_rows if r and r[0] != "无"}
    used_gaps = set(re.findall(r"\bGAP-[A-Za-z0-9-]+", section(text, "候选事实处置明细") + section(text, "大纲逐项检索与候选事实覆盖")))
    for gap in sorted(used_gaps - gap_ids):
        errors.append(f"{gap}在本轮候选/大纲中出现但缺少GAP复核记录")
    return errors

def normalize(task: Path) -> bool:
    """Consolidate this run only; do not fabricate missing checks or evidence."""
    request = task / "10_文章知识需求.md"
    path = task / "15_检索与知识准备记录.md"
    if not request.is_file() or not path.is_file():
        return False
    req = request.read_text(encoding="utf-8-sig")
    if "知识准备记录协议：PR-1" not in req:
        return False
    text = path.read_text(encoding="utf-8-sig")
    if compact(text):
        return False
    allowed = set(HEADINGS) | {"来源命中记录", "官网正文核验", "本轮事实与Claim盘点", "MAT依赖与资料选择", "复杂资料处理与原件核对", "本轮待调研缺口复核"}
    # An unrecognised section or unmerged source record requires a deliberate
    # edit rather than a lossy automatic conversion.
    if any(h not in allowed for h in re.findall(r"^## (.+?)\s*$", text, re.M)):
        return False
    pieces = re.split(r"^## ", text, flags=re.M)
    metadata = pieces[0].rstrip() + "\n- 知识准备记录协议：PR-1\n"
    data = rows(text, "候选事实处置明细")
    inventory = rows(text, "本轮事实与Claim盘点")
    consolidated = []
    for row in data:
        if len(row) < 5:
            return False
        if len(row) == 9:
            consolidated.append(row)
            continue
        match = next((r for r in inventory if len(r) >= 6 and (row[0] in r[0] or any(c in r[0] for c in re.findall(r"CLM-[A-Za-z0-9-]+", row[4])))), None)
        if match is None:
            return False
        consolidated.append(row[:5] + [match[2], match[3], match[4], match[5]])
    known = " ".join(" ".join(r) for r in consolidated)
    if any(r and r[0] != "无" and not any(key in known for key in re.findall(r"CF-\d{3}|CLM-[A-Za-z0-9-]+", r[0])) for r in inventory):
        return False
    if rows(text, "来源命中记录"):
        # Source-hit notes can include inspected-but-unused sources. Do not
        # discard those notes merely because candidate IDs were consolidated.
        for r in rows(text, "来源命中记录"):
            if r and r[0] != "无" and not all(cell in known for cell in r):
                return False
    if not rows(text, "本轮待调研缺口复核"):
        return False
    old_summary = {r[0]: r[1] for r in rows(text, "本轮知识准备结论") if len(r) >= 2}
    if not old_summary.get("中文结论"):
        return False
    def body(title):
        return section(text, title)
    result = metadata + "\n## 固定检索层状态\n\n" + body("固定检索层状态")
    result += "\n\n### 官网正文核验\n\n" + body("官网正文核验")
    result += "\n\n## 大纲逐项检索与候选事实覆盖\n\n" + body("大纲逐项检索与候选事实覆盖")
    result += "\n\n## 候选事实处置明细\n\n" + table(CANDIDATE_HEADER, consolidated)
    result += "\n\n## CUS / ANM来源核验记录\n\n" + body("CUS / ANM来源核验记录")
    result += "\n\n## 缺口与特殊资料处理\n\n### 本轮待调研缺口复核\n\n" + (body("本轮待调研缺口复核") or table(("GAP ID", "当前台账入口与状态", "本轮具体公共知识问题", "与当前大纲关系", "本轮处理和证据"), [["无"] * 5]))
    result += "\n\n### MAT依赖与资料选择\n\n" + body("MAT依赖与资料选择")
    result += "\n\n### 复杂资料处理与原件核对\n\n" + body("复杂资料处理与原件核对")
    conclusion = old_summary["中文结论"]
    result += "\n\n## 本轮知识准备结论\n\n" + table(("项目", "本轮结果"), [[k, str(v)] for k, v in counts(result).items()] + [["中文结论", conclusion]]) + "\n"
    path.write_text(result, encoding="utf-8")
    audit = task / "20_文章前知识审核.md"
    if audit.is_file():
        a = audit.read_text(encoding="utf-8-sig")
        a = re.sub(r"#(?:本轮claim盘点与历史参考仅作审计不作本轮输入|本轮事实与claim盘点|本轮事实与Claim盘点)", "#候选事实处置明细", a)
        a = a.replace("#既有缺口与当前知识问题处理", "#本轮待调研缺口复核")
        audit.write_text(a, encoding="utf-8")
    return True
