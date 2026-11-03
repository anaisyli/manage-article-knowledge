"""Offline stand-in for the deepeval-article-audit judge, driving the audit Skill's real scripts.

Matches deepeval-article-audit v1.10.0.  The judge's and the blind reviewer's work is
model output (first pass, coverage review, verdicts, review rows); a scenario writes
exactly those files, the way ``harness.render_20`` stands in for the knowledge agent.
Every mechanical step is the audit Skill's own CLI in its own process:

    prepare -> freeze -> assemble-judgments -> recheck-list -> assemble-review
    -> check -> reconcile -> render

so the result directory the knowledge importer reads is the one a real run produces.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

from harness import Result

AUDIT_SKILL = Path(os.environ.get("MAK_AUDIT_SKILL", r"D:\deepeval-article-audit\deepeval-article-audit-v1.10.0"))
AUDIT_VERSION = "1.10.0"
AUDIT_SCRIPTS = AUDIT_SKILL / "scripts"


def audit_run(script: str, *args: object) -> Result:
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(AUDIT_SCRIPTS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return Result(proc.returncode, proc.stdout, proc.stderr)


def _required(result: Result, step: str) -> Result:
    if result.code:
        raise AssertionError(f"audit {step} failed ({result.code}): {result.err[-1500:] or result.out[-1500:]}")
    return result


@dataclass
class Judged:
    """One factual sentence of the final article and the judge's conclusion about it."""
    text: str                    # the sentence exactly as it appears in 40
    evidence: str = ""           # exact substring of a 30 evidence line when supported; empty = unknown
    support: str = ""            # the judge's own short reason (unique per claim; the audit rejects stamped text)
    second: str = ""             # "unknown": the blind reviewer disagrees with a supported first pass


def required_checks(claim: str) -> set[str]:
    sys.path.insert(0, str(AUDIT_SCRIPTS))
    from audit_compact import required_checks as audit_required
    return set(audit_required(claim))


class AuditRun:
    """One audit of one article version, in the result_dir the knowledge base named."""

    def __init__(self, request: Result, judged: list[Judged]) -> None:
        self.request = {key: request.value(key) for key in (
            "handoff_contract_version", "article_file", "knowledge_file", "project_id", "article_id",
            "article_version", "result_dir")}
        if request.value("handoff_event") != "faithfulness_request" or not all(self.request.values()):
            raise AssertionError(f"no complete faithfulness_request: {request.out[-1200:]}")
        self.result_dir = Path(self.request["result_dir"])
        self.work = self.result_dir / "_work"
        self.article_id = self.request["article_id"]
        self.judged = judged

    def path(self, name: str) -> Path:
        return self.result_dir / f"{self.article_id}-{name}.json"

    def write(self, name: str, payload: object) -> Path:
        target = self.work / name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return target

    def run(self) -> Result:
        r = self.request
        _required(audit_run("prepare_article_audit.py", "--article", r["article_file"], "--knowledge", r["knowledge_file"],
                            "--project-id", r["project_id"], "--article-id", self.article_id,
                            "--article-version", r["article_version"],
                            "--handoff-contract-version", r["handoff_contract_version"],
                            "--result-dir", self.result_dir), "prepare")
        prepared = json.loads(self.path("prepared").read_text(encoding="utf-8"))
        self.inventory(prepared)
        _required(audit_run("audit_preflight.py", "freeze", "--prepared", self.path("prepared"),
                            "--first-inventory", self.work / "first.json", "--coverage-review", self.work / "coverage.json",
                            "--output", self.work / "frozen.json"), "freeze")
        frozen = json.loads((self.work / "frozen.json").read_text(encoding="utf-8"))
        self.verdicts(frozen)
        _required(audit_run("audit_preflight.py", "assemble-judgments", "--prepared", self.path("prepared"),
                            "--frozen-inventory", self.work / "frozen.json", "--first-inventory", self.work / "first.json",
                            "--blind-inventory", self.work / "blind.json", "--verdicts", self.work / "verdicts-1.json",
                            "--output", self.path("judgments")), "assemble-judgments")
        _required(audit_run("audit_preflight.py", "recheck-list", "--judgments", self.path("judgments"),
                            "--output", self.work / "recheck.json"), "recheck-list")
        self.reviews(json.loads((self.work / "recheck.json").read_text(encoding="utf-8")))
        _required(audit_run("audit_preflight.py", "assemble-review", "--prepared", self.path("prepared"),
                            "--frozen-inventory", self.work / "frozen.json", "--blind-inventory", self.work / "blind.json",
                            "--recheck", self.work / "recheck.json", "--reviews", self.work / "reviews-1.json",
                            "--output", self.path("adversarial-review")), "assemble-review")
        _required(audit_run("audit_preflight.py", "check", "--prepared", self.path("prepared"),
                            "--judgments", self.path("judgments"), "--adversarial-review", self.path("adversarial-review"),
                            "--frozen-inventory", self.work / "frozen.json", "--receipt", self.work / "receipt.json"), "check")
        _required(audit_run("reconcile_article_audit.py", "--result-dir", self.result_dir, "--article-id", self.article_id),
                  "reconcile")
        return _required(audit_run("render_article_audit.py", "--result-dir", self.result_dir, "--article-id", self.article_id,
                                   "--article-version", r["article_version"]), "render")

    # --- the judge's files --------------------------------------------
    def by_text(self, text: str) -> Judged | None:
        return next((item for item in self.judged if item.text.strip() == text.strip()), None)

    def inventory(self, prepared: dict) -> None:
        claims, excluded = [], []
        for unit in prepared["article_units"]:
            if unit.get("unit_type") in {"title", "heading", "table_header"}:
                continue
            if self.by_text(unit["text"]):
                claims.append(dict(unit_id=unit["unit_id"], article_quote=unit["text"], claim=unit["text"]))
            else:
                excluded.append(dict(unit_id=unit["unit_id"], classification="non_factual", category="transition",
                                     reason="该单元只承上启下，不陈述可核验的关系。"))
        missing = [item.text for item in self.judged if not any(c["article_quote"] == item.text.strip() for c in claims)]
        if missing:
            raise AssertionError(f"judged sentences are not article units of 40: {missing}")
        self.write("first.json", dict(coverage_review=dict(unit_classifications=excluded), claim_inventory=claims))
        # The coverage reviewer agrees with every exclusion and adds no claim.
        agreed = [dict(row, reason="复查认同：这句只是过渡说明，没有断言。") for row in excluded]
        self.write("coverage.json", dict(coverage_review=dict(unit_classifications=agreed), claim_inventory=[]))

    def verdicts(self, frozen: dict) -> None:
        rows = []
        for claim in frozen["claims"]:
            item = self.by_text(claim["article_quote"])
            if item and item.evidence:
                rows.append(dict(claim_id=claim["claim_id"], semantic_status="entailed",
                                 support=item.support or f"证据正文逐字给出{claim['claim_id']}所述的同一事实",
                                 evidence=[dict(quote=item.evidence)]))
            else:
                rows.append(dict(claim_id=claim["claim_id"], semantic_status="unknown", gap_type="no_evidence"))
        self.write("verdicts-1.json", rows)

    def reviews(self, recheck: dict) -> None:
        rows = []
        for listed in recheck.get("claims", recheck.get("claim_reviews", [])):
            item = self.by_text(listed.get("article_quote", "")) or self.by_text(listed.get("claim", ""))
            claim = listed["claim"]
            if item and item.evidence and item.second != "unknown":
                checks = {name: dict(status="covered", claim_fragment=claim, evidence_fragment=item.evidence)
                          for name in required_checks(claim)}
                rows.append(dict(claim_id=listed["claim_id"], independent_semantic_status="entailed",
                                 challenge_reason=f"独立复核：允许证据逐字陈述{listed['claim_id']}的主体、关系与范围。",
                                 atomicity_review=dict(status="atomic", independent_proposition_count=1,
                                                       reason=f"{listed['claim_id']}只断言同一对象的一组并列选项。"),
                                 entailment_checks=checks))
            else:
                rows.append(dict(claim_id=listed["claim_id"], independent_semantic_status="unknown",
                                 challenge_reason=f"独立复核：允许证据没有提到{listed['claim_id']}所述事实。"))
        self.write("reviews-1.json", rows)
