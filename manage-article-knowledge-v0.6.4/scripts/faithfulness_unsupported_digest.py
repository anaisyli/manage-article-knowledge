#!/usr/bin/env python3
"""Print a compact view of unsupported Faithfulness claims for disposition grouping.

Before ``import_faithfulness.py --disposition`` Codex must group every
unsupported claim.  Reading the full prepared, judgments and adversarial-review
artifacts for that repeats data the importer already validates mechanically
(hashes, review rows, identity keys) and costs far more than the grouping work.
This view keeps only what grouping needs: each unsupported claim with its
article quote, first-pass reason, recorded evidence locations, reconciliation
outcome, the current ``30`` evidence body, and the project's knowledge-gap rows.

It also flags, per claim, the importer's own rejection rules (customer markers
that forbid a public gap, protected domains that forbid ``writing_only``, and
``audit_process_limitation`` eligibility) so a disposition is not rejected
after it has been written.  The script never judges claims, never writes a
disposition and never changes any artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from import_faithfulness import (  # noqa: E402
    CUSTOMER_MARKER_RE,
    WRITING_ONLY_RISK_PATTERNS,
    customer_markers_for_project,
    read_text,
)

SCHEMA = "MAK-UNSUPPORTED-DIGEST-1"
GAP_RELATIVE = Path("05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv")
QUOTE_LIMIT = 220
# Same record-defect signals load_disposition() accepts for audit_process_limitation.
PROCESS_RECORD_SIGNALS = ("没有对应证据原文片段", "没有对应主张原文片段", "未被证据覆盖",
                          "检查缺失", "检查字段不完整", "状态无效", "理由过短", "重复模板")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_artifact(result_dir: Path, pattern: str) -> Path:
    matches = sorted(path for path in result_dir.glob(pattern) if path.is_file())
    if len(matches) != 1:
        raise ValueError(f"结果目录中应恰好有一个{pattern}，实际{len(matches)}个：{result_dir}")
    return matches[0]


def project_root_for(article_file: str) -> Path | None:
    """Derive the knowledge project from the managed 40 path recorded in prepared."""
    for parent in Path(article_file).parents:
        if (parent / "04_文章任务").is_dir() and (parent / "01_工作台").is_dir():
            return parent
    return None


def clip(text: Any, limit: int = QUOTE_LIMIT) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def compact_reason(reason: str, claim_id: str, claim: str) -> str:
    """Drop the restated claim text the auditor embeds in its reason."""
    value = str(reason or "")
    if claim:
        value = value.replace(f"（{claim_id}：{claim}）", "").replace(f"{claim_id}：{claim}", claim_id)
        value = value.replace(claim, "〈主张〉")
    return " ".join(value.split())


def process_limitation_candidate(claim: dict[str, Any]) -> bool:
    reconciliation = claim.get("reconciliation") or {}
    reasons = reconciliation.get("reasons")
    return bool(
        claim.get("semantic_status") == "unknown"
        and reconciliation.get("first_pass_semantic_status") == "entailed"
        and reconciliation.get("independent_semantic_status") == "entailed"
        and reconciliation.get("final_semantic_status") == "unknown"
        and isinstance(reasons, list) and reasons
        and all(isinstance(reason, str) and any(token in reason for token in PROCESS_RECORD_SIGNALS)
                for reason in reasons)
    )


# Same signals load_disposition() requires for audit_unresolved (SK-V064-031).
AUDIT_UNRESOLVED_SIGNALS = ("双轮结论不一致", "多个独立命题", "复合信号")


def audit_unresolved_candidate(claim: dict[str, Any]) -> bool:
    """One pass entailed from cited evidence; the audit's own conclusion left the claim unknown."""
    reconciliation = claim.get("reconciliation") or {}
    reasons = [str(reason) for reason in reconciliation.get("reasons") or []]
    return bool(
        claim.get("semantic_status") == "unknown" and claim.get("evidence")
        and "entailed" in {reconciliation.get("first_pass_semantic_status"),
                           reconciliation.get("independent_semantic_status")}
        and any(token in reason for reason in reasons for token in AUDIT_UNRESOLVED_SIGNALS)
    )


def evidence_rows(items: Any, aliases: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_file", ""))
        rows.append({
            "file": aliases.get(source.casefold(), Path(source).name),
            "lines": f"{item.get('line_start', '')}-{item.get('line_end', item.get('line_start', ''))}",
            "quote": clip(item.get("quote")),
        })
    return rows


def gap_rows(project: Path, article_id: str) -> list[dict[str, Any]]:
    from record_knowledge_gap import read_rows

    path = project / GAP_RELATIVE
    rows = []
    for row in read_rows(path):
        if row.get("status") == "已关闭":
            continue  # cannot be used or reopened as an existing gap for this import
        linked = article_id in [value.strip() for value in row.get("article_ids", "").split(";")]
        rows.append({
            "gap_key": row.get("gap_key", ""),
            "topic": row.get("gap_topic", ""),
            "type": row.get("gap_type", ""),
            "status": row.get("status", ""),
            "linked_to_article": linked,
            "current_article_count": row.get("current_article_count", ""),
        })
    return rows


def build_digest(result_dir: Path, project: Path | None = None) -> dict[str, Any]:
    prepared_path = unique_artifact(result_dir, "*-prepared.json")
    judgments_path = unique_artifact(result_dir, "*-judgments.json")
    prepared = json.loads(read_text(prepared_path))
    judgments = json.loads(read_text(judgments_path))
    article_id = str(judgments.get("article_id") or prepared.get("article_id") or "")
    if project is None:
        project = project_root_for(str(prepared.get("article_file", "")))

    files = [str(path) for path in prepared.get("knowledge_files", [])]
    aliases = {path.casefold(): f"F{index}" for index, path in enumerate(files, 1)}
    markers = customer_markers_for_project(project)
    marker_re = re.compile("|".join(re.escape(item) for item in markers), re.IGNORECASE) if markers else None

    claims = [claim for claim in judgments.get("claims", []) if isinstance(claim, dict)]
    unsupported = [claim for claim in claims if claim.get("verdict") == "unsupported"]
    counts: dict[str, int] = {"total": len(claims), "supported": 0, "unsupported": len(unsupported)}
    for claim in claims:
        if claim.get("verdict") == "supported":
            counts["supported"] += 1
        status = str(claim.get("semantic_status", ""))
        if status:
            counts[status] = counts.get(status, 0) + 1

    units: dict[str, dict[str, Any]] = {}
    reason_ids: dict[str, str] = {}
    reason_texts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for claim in unsupported:
        claim_id = str(claim.get("claim_id", ""))
        text = str(claim.get("claim", ""))
        unit_id = str(claim.get("unit_id", ""))
        quote = str(claim.get("article_quote", ""))
        unit = units.setdefault(unit_id, {"line": claim.get("article_line"), "quote": quote})
        reason = compact_reason(str(claim.get("reason", "")), claim_id, text)
        reason_texts[reason] = reason_texts.get(reason, 0) + 1
        reconciliation = claim.get("reconciliation") or {}
        row: dict[str, Any] = {
            "id": claim_id,
            "unit": unit_id,
            # "@quote": the claim is verbatim the unit's article quote.
            "claim": "@quote" if text == unit["quote"] else text,
            "status": claim.get("semantic_status", ""),
            "reason": reason,
        }
        if quote and quote != unit["quote"]:
            row["quote"] = quote
        depth = str(reconciliation.get("review_depth", ""))
        if depth and depth != "first_pass_unknown":
            row["review"] = {
                "depth": depth,
                "first": reconciliation.get("first_pass_semantic_status", ""),
                "second": reconciliation.get("independent_semantic_status", ""),
                "final": reconciliation.get("final_semantic_status", ""),
                "reasons": list(reconciliation.get("reasons") or []),
            }
        evidence = evidence_rows(claim.get("evidence"), aliases)
        if evidence:
            row["evidence"] = evidence
        coreference = evidence_rows(claim.get("coreference_evidence"), aliases)
        if coreference:
            row["coreference_lines"] = [item["file"] + ":" + item["lines"] for item in coreference]
        flags: dict[str, Any] = {}
        hits = sorted({match.group(0) for match in CUSTOMER_MARKER_RE.finditer(text)}
                      | ({match.group(0) for match in marker_re.finditer(text)} if marker_re else set()))
        if hits:
            flags["public_gap_blocked_by"] = hits
        risks = [label for label, pattern in WRITING_ONLY_RISK_PATTERNS if pattern.search(text)]
        if risks:
            flags["writing_only_blocked_by"] = risks
        if process_limitation_candidate(claim):
            flags["audit_process_limitation_candidate"] = True
        elif audit_unresolved_candidate(claim):
            flags["audit_unresolved_candidate"] = True
        if flags:
            row["flags"] = flags
        rows.append(row)

    # Repeated template reasons are listed once and referenced by id.
    templates = {}
    for reason, count in reason_texts.items():
        if count > 1 and reason:
            reason_ids[reason] = f"R{len(reason_ids) + 1}"
            templates[reason_ids[reason]] = reason
    for row in rows:
        if row["reason"] in reason_ids:
            row["reason"] = reason_ids[row["reason"]]

    digest: dict[str, Any] = {
        "schema": SCHEMA,
        "article_id": article_id,
        "article_version": prepared.get("article_version", ""),
        "review_policy": (judgments.get("reconciliation") or {}).get("policy", ""),
        "source": {
            "result_dir": str(result_dir),
            "judgments_sha256": sha256_file(judgments_path),
            "prepared_sha256": sha256_file(prepared_path),
        },
        "counts": counts,
        "files": {alias: path for path, alias in ((path, aliases[path.casefold()]) for path in files)},
        "knowledge_evidence": [
            {"chunk": chunk.get("chunk_id", ""),
             "file": aliases.get(str(chunk.get("source_file", "")).casefold(), ""),
             "lines": f"{chunk.get('line_start', '')}-{chunk.get('line_end', '')}",
             "text": clip(chunk.get("text"), 600)}
            for chunk in prepared.get("knowledge_chunks", []) if isinstance(chunk, dict)
        ],
        "customer_markers": ["JERL/our products/客户专属等通用标记"] + markers,
        "reason_templates": templates,
        "units": units,
        "unsupported": rows,
    }
    if project is not None and (project / GAP_RELATIVE).is_file():
        digest["project"] = str(project)
        digest["gaps"] = gap_rows(project, article_id)
    digest["next_action"] = (
        "claim为@quote时主张即units中该单元原句。按knowledge_question逐条归组全部unsupported，写处置JSON后用import_faithfulness.py --disposition导入。"
        "带public_gap_blocked_by的主张不得归existing_gap/new_public_gap；带writing_only_blocked_by的不得归writing_only；"
        "existing_gap须先用record_knowledge_gap.py把本篇关联到该gap_key（linked_to_article=true）。"
        "需要逐字核对某条证据时，只按evidence中的文件别名与行号回读当前30，不整份读取judgments/prepared/adversarial-review。"
    )
    return digest


def dumps(digest: dict[str, Any], ensure_ascii: bool) -> str:
    """One top-level key per line and one claim per line: compact yet line-readable."""
    def encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=ensure_ascii, separators=(",", ":"))

    lines = ["{"]
    keys = list(digest)
    for index, key in enumerate(keys):
        value = digest[key]
        tail = "," if index < len(keys) - 1 else ""
        if isinstance(value, list) and value:
            lines.append(f"{encode(key)}:[")
            lines.extend(encode(item) + ("," if n < len(value) - 1 else "") for n, item in enumerate(value))
            lines.append("]" + tail)
        elif isinstance(value, dict) and len(value) > 1 and key in {"units", "reason_templates"}:
            lines.append(f"{encode(key)}:{{")
            items = list(value.items())
            lines.extend(f"{encode(k)}:{encode(v)}" + ("," if n < len(items) - 1 else "") for n, (k, v) in enumerate(items))
            lines.append("}" + tail)
        else:
            lines.append(f"{encode(key)}:{encode(value)}{tail}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mak-digest-") as temp:
        root = Path(temp)
        knowledge = root / "30_本篇知识库资料.md"
        knowledge.write_text("x\n", encoding="utf-8")
        claim = "Our products ship in rigid boxes."
        (root / "ART-1-prepared.json").write_text(json.dumps({
            "article_id": "ART-1", "article_version": "v1", "article_file": str(root / "40.md"),
            "knowledge_files": [str(knowledge)],
            "knowledge_chunks": [{"chunk_id": "K0001", "source_file": str(knowledge), "line_start": 1,
                                  "line_end": 1, "text": "x"}],
        }), encoding="utf-8")
        (root / "ART-1-judgments.json").write_text(json.dumps({
            "article_id": "ART-1", "reconciliation": {"policy": "decisive_recheck_v1"},
            "claims": [
                {"claim_id": "C001", "unit_id": "U001", "article_line": 3, "article_quote": claim,
                 "claim": claim, "verdict": "unsupported", "semantic_status": "unknown",
                 "reason": f"未找到证据（C001：{claim}）。",
                 "reconciliation": {"review_depth": "first_pass_unknown"}},
                {"claim_id": "C002", "unit_id": "U002", "claim": "Supported.", "verdict": "supported",
                 "semantic_status": "entailed"},
            ],
        }), encoding="utf-8")
        digest = build_digest(root)
        assert digest["counts"] == {"total": 2, "supported": 1, "unsupported": 1, "unknown": 1, "entailed": 1}
        row = digest["unsupported"][0]
        assert row["id"] == "C001" and row["claim"] == "@quote" and claim not in row["reason"]
        assert row["flags"]["public_gap_blocked_by"] == ["Our products"]
        assert json.loads(dumps(digest, ensure_ascii=False)) == json.loads(json.dumps(digest))
    print("self-test=passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result-dir", type=Path, help="[结果总目录]/[项目ID]/[文章ID]/v[版本]/")
    parser.add_argument("--project", type=Path, help="知识库项目根目录；省略时从prepared中的40路径推断")
    parser.add_argument("--output", type=Path, help="写入UTF-8文件；省略时打印到标准输出")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.result_dir:
        parser.error("需要 --result-dir")
    digest = build_digest(args.result_dir, args.project)
    if args.output:
        args.output.write_text(dumps(digest, ensure_ascii=False), encoding="utf-8")
        print(f"digest={args.output} unsupported={digest['counts']['unsupported']}")
        return 0
    # Keep the receipt parseable when a Windows host uses a legacy code page.
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    sys.stdout.write(dumps(digest, ensure_ascii=not encoding.startswith("utf")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
