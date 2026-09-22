#!/usr/bin/env python3
"""Deterministically close structural gaps in knowledge-refresh article tasks.

The helper repairs only derived Markdown tables and public-gap lifecycle fields.
It never invents research evidence, source findings, Claim judgments, or a human
exclusion decision.  Semantic work that is still required is returned as a
blocking reason for the caller to continue processing.
"""

from __future__ import annotations

import argparse
import csv
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from template_contract import (
    CLAIM_RECHECK_HEADER,
    REFRESH_SUMMARY_HEADER,
    REFRESH_SUMMARY_ITEMS,
    REVISION_REVIEW_HEADER,
    parse_field,
    table_rows,
)


GAP_RELATIVE = Path("05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv")
GAP_FIELDS = (
    "gap_key", "gap_topic", "gap_type", "trigger_basis", "article_ids",
    "article_count", "current_article_ids", "current_article_count",
    "status", "current_impact", "next_action", "first_seen",
    "last_seen", "related_governance_ref",
)
LEGACY_GAP_FIELDS = tuple(
    field for field in GAP_FIELDS if field not in {"current_article_ids", "current_article_count"}
)
DIRECT_RESEARCH_BASES = {"核心章节首次", "高风险事实首次", "重复文章"}
BASELINE_GAP_REVIEW_HEADER = (
    "缺口ID", "基线Faithfulness入口", "当前台账状态", "与原大纲关系", "本轮处理",
)
REVIEW_ITEMS = (
    "六层重新检索", "旧Claim逐条复核", "Claim重新归类", "本轮知识刷新结论", "30/35重新生成",
)


@dataclass
class FinalizeResult:
    repaired: list[Path] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    inherited_gaps: list[str] = field(default_factory=list)
    research_required: list[str] = field(default_factory=list)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def atomic_write_text(path: Path, text: str) -> bool:
    normalized = text.rstrip() + "\n"
    if path.is_file() and read_text(path) == normalized:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False, suffix=".tmp"
    ) as stream:
        stream.write(normalized)
        temporary = Path(stream.name)
    temporary.replace(path)
    return True


def atomic_write_rows(path: Path, rows: list[dict[str, str]]) -> bool:
    current = read_text(path) if path.is_file() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="", dir=path.parent, delete=False, suffix=".tmp"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=GAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(stream.name)
    generated = read_text(temporary)
    if generated == current:
        temporary.unlink()
        return False
    temporary.replace(path)
    return True


def split_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_line(cells: list[str] | tuple[str, ...]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "／").replace("\r", " ").replace("\n", " ") for cell in cells) + " |"


def table_block(heading: str, header: tuple[str, ...], rows: list[list[str]]) -> list[str]:
    return [
        heading,
        "",
        table_line(header),
        "|" + "---|" * len(header),
        *(table_line(row) for row in rows),
    ]


def replace_section(text: str, heading: str, replacement: list[str], *, before: str | None = None) -> str:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        insert_at = len(lines)
        if before:
            insert_at = next(
                (index for index, line in enumerate(lines) if line.strip() == before), len(lines)
            )
        prefix = [] if insert_at == 0 or not lines[insert_at - 1].strip() else [""]
        suffix = [] if insert_at >= len(lines) or not lines[insert_at].strip() else [""]
        lines[insert_at:insert_at] = prefix + replacement + suffix
    else:
        end = next(
            (index for index in range(start + 1, len(lines)) if lines[index].strip().startswith("## ")),
            len(lines),
        )
        lines[start:end] = replacement + ([""] if end < len(lines) else [])
    return "\n".join(lines).rstrip() + "\n"


def read_gap_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = tuple(reader.fieldnames or ())
        if fieldnames not in {GAP_FIELDS, LEGACY_GAP_FIELDS}:
            raise ValueError(f"知识缺口CSV字段不符合v0.6：{path}")
        rows = [{name: row.get(name, "") for name in GAP_FIELDS} for row in reader]
        if fieldnames == LEGACY_GAP_FIELDS:
            for row in rows:
                row["current_article_ids"] = row["article_ids"]
                row["current_article_count"] = row["article_count"]
        return rows


def article_ids(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.split(";") if item.strip()))


def research_next_action() -> str:
    return "按本篇已批准范围开展定向外部调研；形成RES证据和正式公共Claim后更新缺口状态"


def reconcile_gap_lifecycle(project: Path, article_id: str) -> tuple[dict[str, dict[str, str]], Path | None]:
    path = project / GAP_RELATIVE
    rows = read_gap_rows(path)
    changed = False
    by_key: dict[str, dict[str, str]] = {}
    for row in rows:
        ids = article_ids(row.get("article_ids", ""))
        recorded_count = str(len(ids))
        if row.get("article_count") != recorded_count:
            row["article_count"] = recorded_count
            changed = True
        current_ids = article_ids(row.get("current_article_ids", ""))
        current_count = str(len(current_ids))
        if row.get("current_article_count") != current_count:
            row["current_article_count"] = current_count
            changed = True
        if row.get("gap_key") and article_id in ids:
            by_key[row["gap_key"]] = row
        needs_research = len(current_ids) >= 2 or row.get("trigger_basis") in {"核心章节首次", "高风险事实首次"}
        if needs_research and row.get("status") == "观察中":
            row["status"] = "待外部调研"
            if len(current_ids) >= 2:
                row["trigger_basis"] = "重复文章"
            row["next_action"] = research_next_action()
            changed = True
        elif row.get("status") == "待外部调研" and "外部调研" not in row.get("next_action", ""):
            row["next_action"] = research_next_action()
            changed = True
    changed_path = path if changed and atomic_write_rows(path, rows) else None
    return by_key, changed_path


def set_current_gap_presence(path: Path, gap_key: str, article_id: str, present: bool) -> bool:
    """Update current-version impact without changing historical article linkage."""
    rows = read_gap_rows(path)
    changed = False
    for row in rows:
        if row.get("gap_key") != gap_key:
            continue
        ids = article_ids(row.get("current_article_ids", ""))
        if present and article_id not in ids:
            ids.append(article_id)
            changed = True
        elif not present and article_id in ids:
            ids.remove(article_id)
            changed = True
        count = str(len(ids))
        if row.get("current_article_ids") != ";".join(ids) or row.get("current_article_count") != count:
            row["current_article_ids"] = ";".join(ids)
            row["current_article_count"] = count
            changed = True
        break
    return changed and atomic_write_rows(path, rows)


def archive_root(project: Path, request_text: str) -> Path | None:
    entry = parse_field(request_text, "旧版本归档入口")
    if not entry or entry == "不适用":
        return None
    relative = Path(entry)
    if relative.is_absolute():
        return None
    candidate = (project / relative).resolve()
    try:
        candidate.relative_to(project.resolve())
    except ValueError:
        return None
    return candidate


def claim_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return set(re.findall(r"\bCLM-[A-Za-z0-9-]+\b", read_text(path)))


def baseline_gap_ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return list(dict.fromkeys(re.findall(r"\bGAP-[A-Za-z0-9-]+\b", read_text(path))))


def normalize_disposition(value: str) -> str:
    value = value.strip()
    aliases = (
        (("复用", "保留"), "复用"),
        (("更新",), "更新"),
        (("拆分",), "拆分"),
        (("迁移",), "迁移"),
        (("失效",), "失效"),
        (("不适用",), "不适用"),
    )
    for prefixes, normalized in aliases:
        if value.startswith(prefixes):
            return normalized
    return value


def specific_exclusion(relationship: str, handling: str) -> bool:
    excluded = any(marker in relationship for marker in ("无关", "已排除", "不再需要"))
    vague = handling.strip() in {"中性表达", "一般原理", "缩小范围", "省略"}
    return excluded and len(handling.strip()) >= 12 and not vague


def research_forbidden(request_text: str) -> bool:
    scope = " ".join(
        parse_field(request_text, label)
        for label in ("特殊限制", "原始写作要求", "原始写作请求")
    )
    return any(
        marker in scope
        for marker in ("本篇不开展新的外部调研", "禁止外部调研", "不使用任何外部来源")
    )


def existing_gap_reviews(text: str) -> dict[str, list[str]]:
    return {
        row[0].strip(): row
        for row in table_rows(text, "## 基线知识缺口复核")
        if len(row) >= len(BASELINE_GAP_REVIEW_HEADER) and row[0].strip()
    }


def finalize_task(task_dir: Path) -> FinalizeResult:
    task_dir = task_dir.resolve()
    result = FinalizeResult()
    required = {
        "10": task_dir / "10_文章知识需求.md",
        "15": task_dir / "15_检索与知识准备记录.md",
        "20": task_dir / "20_文章前知识审核.md",
    }
    missing = [path.name for path in required.values() if not path.is_file()]
    if missing:
        result.blocked_reasons.append("知识重整缺少派生文件：" + "、".join(missing))
        return result

    request_text = read_text(required["10"])
    if parse_field(request_text, "任务模式") != "knowledge_refresh_and_rewrite":
        return result
    project = task_dir.parents[2]
    article_id = parse_field(request_text, "文章ID")
    base_version = parse_field(request_text, "基线文章版本")
    if not article_id or not re.fullmatch(r"v[1-9]\d*", base_version):
        result.blocked_reasons.append("知识重整的文章ID或基线文章版本缺失，不能自动收口")
        return result
    archive = archive_root(project, request_text)
    if archive is None or not archive.is_dir():
        result.blocked_reasons.append("知识重整的旧版本归档入口无效，不能自动收口")
        return result

    old_claims = claim_ids(archive / "35_写作素材来源索引.md")
    if not (archive / "35_写作素材来源索引.md").is_file():
        result.blocked_reasons.append("旧版本归档缺少35_写作素材来源索引.md，不能计算基线Claim")
    inherited_gaps = baseline_gap_ids(archive / "50_文章知识使用与Faithfulness记录.md")
    result.inherited_gaps = inherited_gaps
    try:
        gap_rows, changed_gap = reconcile_gap_lifecycle(project, article_id)
    except ValueError as exc:
        result.blocked_reasons.append(str(exc))
        gap_rows, changed_gap = {}, None
    if changed_gap:
        result.repaired.append(changed_gap)

    retrieval_text = read_text(required["15"])
    claim_rows = table_rows(retrieval_text, "## 旧Claim重新核验")
    recorded_claims = {row[0].strip() for row in claim_rows if row and row[0].strip() != "无"}
    missing_claims = sorted(old_claims - recorded_claims)
    if missing_claims:
        result.blocked_reasons.append("旧Claim尚未逐条复核：" + "、".join(missing_claims))
    normalized_claim_rows: list[list[str]] = []
    for row in claim_rows:
        if len(row) < len(CLAIM_RECHECK_HEADER):
            result.blocked_reasons.append("旧Claim重新核验存在列数不足的数据行")
            continue
        current = list(row[: len(CLAIM_RECHECK_HEADER)])
        current[5] = normalize_disposition(current[5])
        if current[0] != "无" and current[5] not in {"复用", "更新", "拆分", "迁移", "失效", "不适用"}:
            result.blocked_reasons.append(f"{current[0]}缺少可识别的复核处置")
        normalized_claim_rows.append(current)
    if normalized_claim_rows:
        retrieval_text = replace_section(
            retrieval_text,
            "## 旧Claim重新核验",
            table_block("## 旧Claim重新核验", CLAIM_RECHECK_HEADER, normalized_claim_rows),
            before="## 大纲逐项检索与候选事实覆盖",
        )

    candidates = table_rows(retrieval_text, "## 候选事实处置明细")
    candidate_ids = {
        row[0].strip() for row in candidates if row and re.fullmatch(r"CF-\d{3}", row[0].strip())
    }
    new_claims = {
        claim_id
        for row in candidates if len(row) >= 5 and row[3].strip() == "已沉淀Formal Claim"
        for claim_id in re.findall(r"\bCLM-[A-Za-z0-9-]+\b", row[4])
        if claim_id not in old_claims
    }
    counts = {
        "基线Claim数": len(old_claims),
        "本轮候选事实数": len(candidate_ids),
        "保留": sum(1 for row in normalized_claim_rows if len(row) >= 6 and row[5] == "复用"),
        "新增": len(new_claims),
        "更新": sum(1 for row in normalized_claim_rows if len(row) >= 6 and row[5] == "更新"),
        "拆分": sum(1 for row in normalized_claim_rows if len(row) >= 6 and row[5] == "拆分"),
        "迁移": sum(1 for row in normalized_claim_rows if len(row) >= 6 and row[5] == "迁移"),
        "失效": sum(1 for row in normalized_claim_rows if len(row) >= 6 and row[5] == "失效"),
        "转入gap/CUS/MAT/ANM": sum(
            1 for row in candidates if len(row) >= 4 and row[3].strip() == "进入治理"
        ),
    }
    old_summary = {
        row[0].strip(): row[1].strip()
        for row in table_rows(retrieval_text, "## 本轮知识刷新结论") if len(row) >= 2
    }
    scope = old_summary.get("重新检索范围", "")
    if scope in {"", "已检索", "检索完成", "无", "不适用"}:
        fixed_layers = table_rows(retrieval_text, "## 固定检索层状态")
        layer_summary = "、".join(
            f"{row[0].strip()}（{row[1].strip()}）" for row in fixed_layers if len(row) >= 2
        )
        scope = "已重新检查" + (layer_summary or "正式Claim、客户源资料、客户官网、关联网站、已有外部公共Claim、新外部调研和治理队列")
    conclusion = old_summary.get("中文结论", "")
    if not re.search(r"[\u3400-\u9fff]", conclusion) or "不阻塞文章重写" not in conclusion:
        conclusion = (
            f"已重新核验{len(old_claims)}条基线Claim和{len(candidate_ids)}条候选事实；"
            "现有证据结论与明细一致，本结论不阻塞文章重写。"
        )
    summary_values: dict[str, str] = {
        "基线版本": base_version,
        "重新检索范围": scope,
        **{key: str(value) for key, value in counts.items()},
        "中文结论": conclusion,
    }
    summary_rows = [[item, summary_values[item]] for item in REFRESH_SUMMARY_ITEMS]
    retrieval_text = replace_section(
        retrieval_text,
        "## 本轮知识刷新结论",
        table_block("## 本轮知识刷新结论", REFRESH_SUMMARY_HEADER, summary_rows),
        before="## 大纲逐项检索与候选事实覆盖",
    )

    old_reviews = existing_gap_reviews(retrieval_text)
    gap_review_rows: list[list[str]] = []
    forbidden = research_forbidden(request_text)
    for gap_id in inherited_gaps:
        row = gap_rows.get(gap_id)
        prior = old_reviews.get(gap_id, [])
        if row is None:
            result.blocked_reasons.append(f"基线Faithfulness关联的{gap_id}未在知识缺口台账中登记")
            status = "台账缺失"
        else:
            status = row.get("status", "")
        relationship = prior[3].strip() if len(prior) >= 5 else "相关（原大纲未变，基线Faithfulness已关联）"
        if len(prior) >= 5:
            handling = prior[4].strip()
        elif status == "待外部调研" and not forbidden:
            handling = "必须先开展正式外部调研并形成RES证据；不能只用一般原理或中性表达关闭旧缺口"
        elif status == "待外部调研":
            handling = "本篇明确禁止新外部调研；保留缺口状态，并在大纲覆盖表写明缩小或排除范围"
        elif status == "已解决":
            handling = "复用已形成的RES证据和正式公共Claim，并在本轮检索记录中核对适用范围"
        elif status == "已关闭":
            handling = "按台账关闭依据复核本篇不再需要该知识问题"
        else:
            handling = "继续观察；本轮已继承并复核，不因文章版本增加重复计数"
        gap_review_rows.append([
            gap_id,
            (archive / "50_文章知识使用与Faithfulness记录.md").relative_to(project).as_posix(),
            status,
            relationship,
            handling,
        ])
        if row is not None and specific_exclusion(relationship, handling):
            gap_path = project / GAP_RELATIVE
            if set_current_gap_presence(gap_path, gap_id, article_id, False):
                result.repaired.append(gap_path)
            row["current_article_ids"] = ";".join(
                item for item in article_ids(row.get("current_article_ids", "")) if item != article_id
            )
            row["current_article_count"] = str(len(article_ids(row["current_article_ids"])))
        if status == "待外部调研" and not forbidden and not specific_exclusion(relationship, handling):
            result.research_required.append(gap_id)
            result.blocked_reasons.append(
                f"{gap_id}已达到待外部调研门槛；知识重整必须先消费调研队列，不能以一般原理或中性表达跳过"
            )
    if inherited_gaps:
        retrieval_text = replace_section(
            retrieval_text,
            "## 基线知识缺口复核",
            table_block("## 基线知识缺口复核", BASELINE_GAP_REVIEW_HEADER, gap_review_rows),
            before="## 大纲逐项检索与候选事实覆盖",
        )
    if atomic_write_text(required["15"], retrieval_text):
        result.repaired.append(required["15"])

    audit_text = read_text(required["20"])
    old_review_rows = {
        row[0].strip(): row for row in table_rows(audit_text, "## 重做检索复核") if len(row) >= 4
    }
    review_defaults = {
        "六层重新检索": ["[[15_检索与知识准备记录.md#固定检索层状态]]", "已完成六层重新检索并保留实际范围", "无"],
        "旧Claim逐条复核": ["[[15_检索与知识准备记录.md#旧Claim重新核验]]", f"已逐条复核{len(old_claims)}条基线Claim", "无"],
        "Claim重新归类": ["[[15_检索与知识准备记录.md#旧Claim重新核验]]", "已按当前七模块复核归类和处置", "无"],
        "本轮知识刷新结论": ["[[15_检索与知识准备记录.md#本轮知识刷新结论]]", "已复核明细与汇总计数一致", "不阻塞"],
        "30/35重新生成": ["[[15_检索与知识准备记录.md#候选事实处置明细]]", "已按当前知识重新生成30/35", "无"],
    }
    rebuilt_review_rows: list[list[str]] = []
    for item in REVIEW_ITEMS:
        prior = old_review_rows.get(item)
        if prior and all(cell.strip() for cell in prior[1:4]):
            rebuilt_review_rows.append([item, *prior[1:4]])
        else:
            rebuilt_review_rows.append([item, *review_defaults[item]])
    audit_text = replace_section(
        audit_text,
        "## 重做检索复核",
        table_block("## 重做检索复核", REVISION_REVIEW_HEADER, rebuilt_review_rows),
        before="## 大纲知识覆盖检查",
    )
    if atomic_write_text(required["20"], audit_text):
        result.repaired.append(required["20"])
    return result


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v06-finalize-refresh-") as temp:
        project = Path(temp) / "DEMO_测试知识库_v0.6"
        task = project / "04_文章任务/10_进行中/DEMO-ART-001_测试文章"
        archive = project / "04_文章任务/90_归档/10_文章历史版本/DEMO-ART-001/v1_20260914-100000"
        task.mkdir(parents=True)
        archive.mkdir(parents=True)
        (project / GAP_RELATIVE).parent.mkdir(parents=True)
        atomic_write_rows(project / GAP_RELATIVE, [{
            "gap_key": "GAP-DEMO-001", "gap_topic": "包装规划中缺少可复用的公开方法和适用边界",
            "gap_type": "公共知识", "trigger_basis": "重复文章",
            "article_ids": "DEMO-ART-001;DEMO-ART-002;DEMO-ART-003", "article_count": "3",
            "current_article_ids": "DEMO-ART-001;DEMO-ART-002;DEMO-ART-003", "current_article_count": "3",
            "status": "观察中", "current_impact": "影响后续同主题知识覆盖",
            "next_action": "继续观察", "first_seen": "2026-09-10", "last_seen": "2026-09-14",
            "related_governance_ref": "当前文章Faithfulness记录",
        }])
        (archive / "35_写作素材来源索引.md").write_text(
            "CLM-DEMO-001\nCLM-DEMO-002\n", encoding="utf-8"
        )
        (archive / "50_文章知识使用与Faithfulness记录.md").write_text(
            "# 记录\n\n| 事项 | 入口 |\n|---|---|\n| 公共知识缺口 | GAP-DEMO-001 |\n", encoding="utf-8"
        )
        (task / "10_文章知识需求.md").write_text(
            "# 文章知识需求\n\n- 文章ID：DEMO-ART-001\n- 当前版本：v2\n"
            "- 任务模式：knowledge_refresh_and_rewrite\n- 基线文章版本：v1\n"
            "- 旧版本归档入口：04_文章任务/90_归档/10_文章历史版本/DEMO-ART-001/v1_20260914-100000\n"
            "- 特殊限制：无\n- 原始写作要求：按原大纲重写\n- 原始写作请求：测试\n",
            encoding="utf-8",
        )
        (task / "15_检索与知识准备记录.md").write_text(
            "# 检索与知识准备记录\n\n- 文章ID：DEMO-ART-001\n- 文章版本：v2\n"
            "- 知识准备模式：knowledge_refresh_and_rewrite\n- 基线文章版本：v1\n\n"
            "## 固定检索层状态\n\n| 检索层 | 当前状态 | 结果或未查原因 | 下一步 |\n|---|---|---|---|\n"
            "| 新外部调研 | 未触发 | 没有核心缺口 | 不开展 |\n\n"
            "## 候选事实处置明细\n\n| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n|---|---|---|---|---|\n"
            "| CF-001 | 事实一 | 来源一 | 复用已有Formal Claim | CLM-DEMO-001 |\n"
            "| CF-002 | 事实二 | 来源二 | 复用已有Formal Claim | CLM-DEMO-002 |\n\n"
            "## 旧Claim重新核验\n\n| 旧Claim ID | 旧版本归档入口 | 重新核对来源与位置 | 当前证据结论 | 当前归类模块 | 处置 | 依据 |\n|---|---|---|---|---|---|---|\n"
            "| CLM-DEMO-001 | v1/35 | 来源一 | 仍有效 | 产品介绍 | 保留并重新纳入v2 | 证据一致 |\n"
            "| CLM-DEMO-002 | v1/35 | 来源二 | 仍有效 | 解决方案 | 保留并重新纳入v2 | 证据一致 |\n\n"
            "## 本轮知识刷新结论\n\n| 项目 | 本轮结果 |\n|---|---|\n| 基线Claim数 | 0 |\n| 本轮候选事实数 | 0 |\n| 保留 | 0 |\n| 中文结论 | 已检查，不阻塞文章重写。 |\n\n"
            "## 大纲逐项检索与候选事实覆盖\n\n占位\n",
            encoding="utf-8",
        )
        (task / "20_文章前知识审核.md").write_text(
            "# 文章前知识审核\n\n- 知识准备模式：knowledge_refresh_and_rewrite\n- 基线文章版本：v1\n\n"
            "## 重做检索复核\n\n| 复核项 | 15记录入口 | 审核结论 | 阻塞或排除 |\n|---|---|---|---|\n"
            "| 六层重新检索 | 15 | 已完成 | 无 |`n| 30/35重新生成 | 15 | 已完成 | 无 |\n\n"
            "## 大纲知识覆盖检查\n\n占位\n",
            encoding="utf-8",
        )
        outcome = finalize_task(task)
        retrieval = read_text(task / "15_检索与知识准备记录.md")
        audit = read_text(task / "20_文章前知识审核.md")
        summary = {row[0]: row[1] for row in table_rows(retrieval, "## 本轮知识刷新结论")}
        assert summary["基线版本"] == "v1"
        assert summary["基线Claim数"] == "2"
        assert summary["本轮候选事实数"] == "2"
        assert summary["保留"] == "2"
        assert "`n" not in audit
        assert {row[0] for row in table_rows(audit, "## 重做检索复核")} == set(REVIEW_ITEMS)
        gap = read_gap_rows(project / GAP_RELATIVE)[0]
        assert gap["status"] == "待外部调研" and gap["next_action"].find("外部调研") >= 0
        assert "GAP-DEMO-001" in retrieval
        assert outcome.research_required == ["GAP-DEMO-001"]
        assert any("必须先消费调研队列" in reason for reason in outcome.blocked_reasons)

        incomplete = project / "04_文章任务/10_进行中/DEMO-ART-002_语义不足"
        incomplete.mkdir(parents=True)
        for name in ("10_文章知识需求.md", "15_检索与知识准备记录.md", "20_文章前知识审核.md"):
            source = task / name
            text = read_text(source).replace("DEMO-ART-001", "DEMO-ART-002")
            if name == "10_文章知识需求.md":
                text = text.replace(
                    "10_文章历史版本/DEMO-ART-002/v1_20260914-100000",
                    "10_文章历史版本/DEMO-ART-001/v1_20260914-100000",
                )
            if name == "15_检索与知识准备记录.md":
                text = "\n".join(
                    line for line in text.splitlines()
                    if not line.strip().startswith("| CLM-DEMO-002 |")
                ) + "\n"
            (incomplete / name).write_text(text, encoding="utf-8")
        missing = finalize_task(incomplete)
        assert any("旧Claim尚未逐条复核" in reason for reason in missing.blocked_reasons)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if not args.task:
        raise SystemExit("--task is required unless --self-test is used")
    result = finalize_task(args.task)
    for path in result.repaired:
        print(f"repaired={path}")
    for gap_id in result.inherited_gaps:
        print(f"inherited_gap={gap_id}")
    for gap_id in result.research_required:
        print(f"research_required={gap_id}")
    for reason in result.blocked_reasons:
        print(f"blocked_reason={reason}")
    if result.research_required:
        print("next_action=按external-research-contract.md在当前运行中完成定向外部调研和RES/正式Claim沉淀，然后重新运行advance_ready_tasks.py")
    print(f"repaired_count={len(result.repaired)}")
    print(f"blocked_count={len(result.blocked_reasons)}")


if __name__ == "__main__":
    main()
