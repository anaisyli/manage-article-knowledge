"""Offline end-to-end scenario harness.

Each scenario writes a minimal synthetic project like writing_bridge.self_test
and then drives one article through the same entry points an agent uses, each
in its own process:

    writing_bridge.py prepare -> record_claim_reuse.py -> (20 written here)
    -> run_knowledge_workflow.py -> issue_writing_ready.py

Project metadata, Claims, evidence captures and the 20 record are fixtures,
standing in for offline input and the agent's judgement. 10, ledger rows, 30/35 and receipts come from the
Skill's own scripts, so a scenario fails exactly where a real run would.
No model, no network, no real project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

SKILL = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evidence_identity import evidence_digest  # noqa: E402
from handoff_contract import current_version  # noqa: E402

# Recovery stages a full copy of the project beside it, so keep the base path short
# (Windows MAX_PATH): <base>/<id>/P/.mak-recovery-*/P/04_文章任务/10_进行中/<task>.
BASE = Path(__import__("tempfile").gettempdir()) / "mak-sc"
PROJECT = "P-T_v0.6"
TEMPLATE_VERSION = "v0.6-20260907.1"

CUS = ("客户能力", "规格", "认证", "案例", "商业条件", "公开授权")
ANM = ("版本", "定位", "提取", "数值与单位", "OCR", "翻译与规范化", "来源冲突", "残缺与外推")
# ANM categories that a reused text Claim is actually checked for; the rest do not apply.
ANM_CHECKED = {"版本", "定位", "提取", "来源冲突", "残缺与外推"}


@dataclass
class Result:
    code: int
    out: str
    err: str

    def values(self, key: str) -> list[str]:
        return [line.split("=", 1)[1] for line in self.out.splitlines() if line.startswith(key + "=")]

    def value(self, key: str) -> str:
        found = self.values(key)
        return found[0] if found else ""

    def json(self) -> dict:
        return json.loads(self.out)


@dataclass
class Claim:
    claim_id: str
    title: str
    excerpt: str
    subject: str = "Demo Packaging"
    obj: str = "Demo drawer box"
    source_type: str = "客户官网"
    url: str = "https://example.test/drawer-box/"
    position: str = "Description / paragraph 2"
    verified: str = "2026-10-20"
    review: str = "否"
    state: str = "有效"
    folder: str = "10_客户知识/20_产品介绍"
    research: str = ""           # RES id when the Claim came from external research
    # Names every we/our/this… the excerpt uses (SK-V064-030); "This drawer box…" needs "This".
    coreference: str = "This and it refer only to the object named in the page heading."

    def text(self) -> str:
        head = (
            f"# {self.title}\n\n- 项目ID：P-T\n- 知识版本：v1\n- 正式知识类型：客户产品\n"
            f"- 知识状态：{self.state}\n- 最近核验日期：{self.verified}\n- 使用前复核：{self.review}\n"
            + (f"- 关联调研：{self.research}\n" if self.research else "") + "\n"
            f"## 已核验Claim\n\n### {self.claim_id}｜{self.title}\n\n"
            f"- Claim ID：{self.claim_id}\n- Claim：{self.title}\n- 适用范围：{self.obj}这一具体对象；不外推\n"
            f"- 来源类型：{self.source_type}\n- 来源链接：{self.url}\n- 原文证据：本文件最小原文证据\n"
            f"- 调研核验：{self.verified}已回读来源正文\n- 精确位置：{self.position}\n- 日期或版本：{self.verified}\n"
            "- 归类模块：产品介绍\n- 归类依据：描述具体对象的事实\n- 使用边界：不外推到其他产品或结果\n"
            "- 竞品信息筛查：通过\n- 证据模板版本：EC-1\n"
            f"- 证据归属主体：{self.subject}\n- 证据归属对象：{self.obj}\n"
            f"- 指代解析：{self.coreference}\n"
            "- 归属核验依据：来源页面标题与同一连续段落\n"
            f"- 归属核验日期：{self.verified}\n- 归属核验状态：已核验\n- 归属证据SHA-256：{{digest}}\n- 状态：可用\n\n"
            f"### 最小原文证据\n\n> {self.excerpt}\n"
        )
        return head.replace("{digest}", evidence_digest(head))


@dataclass
class Candidate:
    cf: str
    claim: Claim
    sections: list[str]          # outline labels (or 标题/主问题) this fact supports
    evidence: str = ""           # EV-xxx when read this run; empty means the Claim is reused

    @property
    def pointer(self) -> str:
        return self.evidence or f"{self.claim.claim_id}（复用，未回源）"

    @property
    def disposition(self) -> str:
        return "已沉淀Formal Claim" if self.evidence else "复用已有Formal Claim"


@dataclass
class Article:
    key: str
    title: str
    outline: str                 # submitted text, exactly as the writer sends it
    sections: list[str]          # the 20 rows the agent would write, one per section
    candidates: list[Candidate] = field(default_factory=list)
    gaps: dict[str, str] = field(default_factory=dict)   # section -> 未覆盖 reason
    no_facts: list[str] = field(default_factory=list)    # sections the 20 marks 无需事实支持 (opening, CTA ...)

    @property
    def outline_items(self) -> list[str]:
        return [line.strip().lstrip("-*+ ").strip() for line in self.outline.splitlines() if line.strip()]


def run(script: str, *args: object) -> Result:
    # The agent-facing entry points; a scenario never imitates one of their outputs by hand.
    if script not in {"initialize_project.py", "writing_bridge.py", "record_claim_reuse.py",
                      "capture_website_evidence.py", "record_knowledge_gap.py", "search_source_index.py", "build_source_index.py",
                      "run_knowledge_workflow.py", "issue_writing_ready.py",
                      "create_faithfulness_record.py", "faithfulness_unsupported_digest.py",
                      "record_governance_item.py", "import_faithfulness.py", "handoff_contract.py",
                      "check_integration.py", "check_skill_update.py", "scaffold_preparation_record.py"}:
        raise AssertionError(f"scenario entry point is outside the offline contract: {script}")
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPTS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return Result(proc.returncode, proc.stdout, proc.stderr)


class Scenario:
    """One isolated project; call ``close`` (or use as a context manager) to remove it."""

    def __init__(self) -> None:
        self.root = BASE / uuid.uuid4().hex[:8]
        self.project = self.root / PROJECT
        (self.root / "src").mkdir(parents=True)
        self.tasks_entry = self.root / "ws" / "写作任务"
        self.tasks_entry.mkdir(parents=True)
        init = run("initialize_project.py", "--project", self.project, "--project-name", "场景测试",
                   "--workspace-project-root", self.root / "ws", "--source-root", self.root / "src",
                   "--website", "https://example.test/", "--content-owner", "scenario")
        if init.code:
            raise RuntimeError(f"initialize_project failed: {init.err or init.out}")

    def __enter__(self) -> "Scenario":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    # --- knowledge base -------------------------------------------------
    def add_claim(self, claim: Claim) -> Path:
        path = self.project / "03_正式知识" / claim.folder / f"{claim.claim_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(claim.text(), encoding="utf-8")
        return path

    # --- writer side ----------------------------------------------------
    def submit(self, article: Article, batch: str, *, revision_mode: str | None = None,
               article_id: str | None = None, base_article_version: str | None = None,
               base_outline_id: str | None = None, base_outline_version: str | None = None,
               request_text: str = "写一篇场景测试文章") -> Result:
        record = self.tasks_entry / f"{article.key}.md"
        if not record.exists():
            record.write_text(f"# 写作需求\n\n- 任务唯一键：{article.key}\n- 标题：{article.title}\n\n## 大纲\n\n{article.outline}\n",
                              encoding="utf-8")
        args = ["writing_bridge.py", "prepare", "--handoff-contract-version", current_version(),
                   "--project", self.project, "--external-task-key", article.key, "--source-path", record,
                   "--source-locator", f"任务唯一键：{article.key}", "--title", article.title,
                   "--request-text", request_text, "--product-or-content-object", "抽屉盒",
                   "--topic-direction", "采购评估", "--keywords", "drawer box", "--outline", article.outline,
                   "--outline-id", f"{article.key}-v1", "--outline-version", "v1", "--outline-status", "已确认",
                   "--target-language", "English", "--constraints", "不写未核验事实",
                   "--original-writing-requirements", "只用已核验事实", "--current-status", "可准备知识",
                   "--writing-skill", "scenario-writer", "--batch-id", batch, "--date", "2026-10-28"]
        if revision_mode:
            args += ["--revision-mode", revision_mode, "--article-id", article_id or "",
                     "--base-article-version", base_article_version or "v1",
                     "--base-outline-id", base_outline_id or f"{article.key}-v1",
                     "--base-outline-version", base_outline_version or "v1"]
        return run(*args)

    # --- knowledge side -------------------------------------------------
    def task(self, article_id: str) -> Path:
        found = [p for p in (self.project / "04_文章任务").glob(f"*/{article_id}_*") if p.is_dir()]
        if len(found) != 1:
            raise AssertionError(f"expected one task dir for {article_id}, found {found}")
        return found[0]

    def reuse(self, batch: str, article_id: str, claim: Claim) -> Result:
        return run("record_claim_reuse.py", "--project", self.project, "--batch-id", batch,
                   "--article-id", article_id, "--claim-id", claim.claim_id,
                   "--basis", f"{claim.title}的有效记录覆盖本篇对应问题，范围限于{claim.obj}")

    def capture(self, article_id: str, claim: Claim, question: str) -> str:
        """Read the Claim's page this run from a saved browser capture, via the real capture script."""
        task = self.task(article_id)
        run_file = task / "知识检索运行.json"
        run_key = "research_run_id"
        if not run_file.is_file():
            run_file = task / "知识重整运行.json"
            run_key = "refresh_run_id"
        run_id = json.loads(run_file.read_text(encoding="utf-8-sig"))[run_key]
        saved = self.root / "captures" / f"{claim.claim_id}.json"
        saved.parent.mkdir(exist_ok=True)
        saved.write_text(json.dumps({
            "url": claim.url, "title": claim.title, "captured_at": "2026-10-28T10:00:00+08:00",
            "capture_method": "scenario browser capture",
            "blocks": [{"text": claim.title, "tag": "h1"}, {"text": claim.excerpt, "tag": "p", "heading_path": [claim.title]}],
        }, ensure_ascii=False), encoding="utf-8")
        result = run("capture_website_evidence.py", "--manifest", task / "官网正文抓取凭证.json", "--run-id", run_id,
                     "--browser-capture", saved, "--question", question, "--position", claim.position,
                     "--excerpt", claim.excerpt)
        if result.code:
            raise AssertionError(f"capture failed: {result.err or result.out}")
        records = json.loads((task / "官网正文抓取凭证.json").read_text(encoding="utf-8-sig"))
        return records[-1]["evidence_id"]

    def gap(self, article_id: str, topic: str) -> str:
        """Register a high-risk public question as 待外部调研 through the real gap ledger script."""
        result = run("record_knowledge_gap.py", "--csv", self.project / "05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv",
                     "--gap-key", "auto", "--topic", topic, "--article-id", article_id, "--article-date", "2026-10-28",
                     "--trigger-basis", "高风险事实首次", "--next-action", "按本篇具体问题开展定向外部调研，核验公共规则")
        if result.code:
            raise AssertionError(f"record_knowledge_gap failed: {result.err or result.out}")
        return result.value("gap_key")

    def write_20(self, article_id: str, article: Article, *, compact: bool = False, **options) -> Path:
        task = self.task(article_id)
        text = render_20_compact(task, article, **options) if compact else render_20(task, article)
        (task / "20_文章前知识审核.md").write_text(text, encoding="utf-8")
        return task

    def workflow(self, batch: str) -> dict:
        result = run("run_knowledge_workflow.py", "--project", self.project, "--batch-id", batch)
        try:
            return result.json()
        except json.JSONDecodeError as exc:
            raise AssertionError(f"workflow printed no JSON: {result.out[-800:]} {result.err[-800:]}") from exc

    def gate(self, article_id: str) -> Result:
        return run("issue_writing_ready.py", "--handoff-contract-version", current_version(),
                   "--project", self.project, "--article-id", article_id)


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: tuple[str, ...], rows: list[list[str]]) -> str:
    return "\n".join([_row(list(header)), "|" + "---|" * len(header), *(_row(r) for r in rows)])


def render_20(task: Path, article: Article) -> str:
    """The merged PR-2 fixture for current reads, reused Claims or both."""
    request = (task / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
    meta = {label: re.search(rf"^- {label}：(.*)$", request, re.M).group(1).strip()
            for label in ("文章ID", "当前版本", "任务模式", "大纲ID", "大纲版本", "重写模式", "基线文章版本")}
    run_file = task / ("知识重整运行.json" if meta.get("任务模式") == "outline_refresh" and
                       (task / "知识重整运行.json").is_file() else "知识检索运行.json")
    run_payload = json.loads(run_file.read_text(encoding="utf-8-sig"))
    run_id = run_payload.get("refresh_run_id") or run_payload.get("research_run_id")
    fresh = any(c.evidence for c in article.candidates)
    candidates = [[c.cf, c.claim.title, c.pointer, "；".join(c.sections), c.disposition,
                   c.claim.claim_id, "产品介绍", "复用", f"有效Claim范围限于{c.claim.obj}"] for c in article.candidates]
    outline_rows = []
    for section in ["标题", "主问题", *article.sections]:
        refs = [c.cf for c in article.candidates if section in c.sections]
        if section in article.no_facts:
            outline_rows.append([section, "无需事实支持", "无", "只是写作框架或版式要求，不陈述事实", "",
                                 "无需事实支持", "按写作要求执行"])
        elif section in article.gaps or not refs:
            outline_rows.append([section, "未覆盖", "无", "本节没有已核验事实", article.gaps.get(section, "待补充事实"),
                                 "有明确边界", "不写该节事实"])
        else:
            claims = "、".join(c.claim.claim_id for c in article.candidates if c.cf in refs)
            outline_rows.append([section, "已覆盖", "、".join(refs), f"{claims}支持本节，范围限于具体对象", "无",
                                 "有明确边界", "按Claim范围写"])
    lead = article.candidates[0] if article.candidates else None
    first = lead.claim if lead else None
    checks = []
    for number, (detector, category) in enumerate([("CUS候选检测", c) for c in CUS] + [("ANM异常检测", c) for c in ANM], 1):
        checked = first and (category == "客户能力" or (detector == "ANM异常检测" and category in ANM_CHECKED))
        if checked:
            checks.append([f"GC-{number:03d}", detector, category, f"{first.obj}的{category}核对", lead.pointer,
                           "已核验", f"有效Claim连续原文直接陈述，{category}与Claim一致", "无", f"按证据使用：仅限{first.obj}"])
        else:
            checks.append([f"GC-{number:03d}", detector, category, f"本篇不涉及{category}相关事实", "10#大纲",
                           "不适用", f"{category}：当前大纲不需要该类事实", "无", f"不涉及：本篇不写{category}相关内容"])
    gaps = "- 本轮待调研缺口：无（已有有效Claim覆盖）" if not article.gaps else _table(
        ("GAP ID", "本轮具体公共知识问题", "与当前大纲关系", "本轮处理和证据", "审核结论"),
        [["GAP-T-001", reason, section, "待外部调研", "未解决"] for section, reason in article.gaps.items()])
    return (
        "# 知识准备与文章前审核\n\n"
        f"- 文章ID：{meta['文章ID']}\n- 文章版本：{meta['当前版本']}\n- 模板版本：{TEMPLATE_VERSION}\n"
        f"- 知识准备记录协议：PR-2\n- 知识准备模式：{meta['任务模式']}\n"
        f"- 大纲ID：{meta['大纲ID']}\n- 大纲版本：{meta['大纲版本']}\n- 重写模式：{meta['重写模式']}\n"
        f"- 基线文章版本：{meta['基线文章版本']}\n"
        f"- {'本轮知识重整运行ID' if meta.get('任务模式') == 'outline_refresh' else '本轮知识检索运行ID'}：{run_id}\n"
        + ("- 官网正文抓取凭证：官网正文抓取凭证.json\n" if fresh else
           "- 官网正文抓取凭证：无（产品Claim均为有效复用且未触发回源）\n")
        + ("- 本轮知识上下文从空白开始\n" if meta.get("任务模式") == "outline_refresh" else "")
        + "- MAT依赖处理：无\n- 审核日期：2026-10-28\n"
        "- 结论：带明确排除通过\n- 明确排除：不写认证、商业条件或未核验的效果\n- 未解决但不阻塞事项：无\n"
        "- 计划写作素材：30_本篇知识库资料.md\n- 计划写作素材来源索引：35_写作素材来源索引.md\n\n"
        "## 一、固定检索层状态\n\n" + _table(("检索层", "当前状态", "结果或未查原因", "下一步"), [
            ["已有正式Claim", "已检索并命中", f"{len(article.candidates)}项有效Claim", "按范围复用"],
            ["客户源资料索引", "已检索未命中", "无相关原件", "无"],
            ["客户官网", "已检索并命中", "本轮读取产品页正文", "按凭证核验"] if fresh else
            ["客户官网", "不适用（有效Claim覆盖，未触发回源）", "无本轮抓取", "沿用Claim范围"],
            ["客户关联网站", "无已登记站点", "项目未登记关联网站", "无"],
            ["已有外部公共Claim", "已检索未命中", "本篇不需要", "无"],
            ["新外部调研", "未触发", "已有Claim覆盖", "无"],
        ]) + "\n\n"
        "## 二、候选事实\n\n" + _table(("候选事实ID", "独立事实摘要", "来源", "支持的大纲问题", "处置结果",
                                     "Formal Claim或排除/治理入口", "当前归类模块", "Claim动作", "处置依据"), candidates) + "\n\n"
        "## 三、大纲逐项覆盖与审核\n\n" + _table(("大纲章节", "覆盖状态", "候选事实ID", "覆盖说明与边界", "缺口或治理事项",
                                           "审核结论", "本篇写法"), outline_rows) + "\n\n"
        "## 四、CUS / ANM核验与审核\n\n### 检测结果\n\n" + _table(("检测对象", "分类结论", "事项入口", "本篇处理"), [
            ["CUS候选检测", "未触发", "无", "已逐类检查，仅按有效Claim使用具体对象事实"],
            ["ANM异常检测", "未触发", "无", "已逐类检查，当前无未处理异常"],
        ]) + "\n\n### 逐项核验\n\n" + _table(("核验ID", "检测对象", "检测类别", "核验对象与范围", "来源指针", "核对结论",
                                         "判断依据", "事项入口", "本篇处理"), checks) + "\n\n"
        "## 五、缺口与特殊资料\n\n### 本轮待调研缺口\n\n" + gaps + "\n\n"
        "### MAT依赖与资料选择\n\n- MAT依赖与资料选择：无（本篇无版本候选）\n\n"
        "### 复杂资料处理与原件核对\n\n- 复杂资料处理与原件核对：无（本篇不引用复杂资料）\n\n"
        "## 六、结论说明\n\n本篇事实均由有效Formal Claim按原范围复用，不写认证、商业条件或效果。此记录不是Faithfulness判断。\n"
    )


def render_20_compact(task: Path, article: Article, *, checked: tuple[str, ...] = ("规格",),
                      layers: list[list[str]] | None = None) -> str:
    """The compact merged 20 (SK-V064-011): only what a script cannot derive.

    Header fields that repeat 10, the retrieval layers, the CUS/ANM summary, review results,
    the categories without a signal and the conclusion are all left to the Skill.
    ``checked`` names the CUS categories the agent checks against the lead source;
    ``layers`` are exception rows for 一.
    """
    lead = article.candidates[0] if article.candidates else None
    candidates = [[c.cf, c.claim.title, c.pointer, "；".join(c.sections), c.disposition, c.claim.claim_id]
                  for c in article.candidates]
    outline_rows = []
    for section in ["标题", "主问题", *article.sections]:
        refs = [c.cf for c in article.candidates if section in c.sections]
        if section in article.no_facts:
            outline_rows.append([section, "无需事实支持", "无", "只是写作框架或版式要求，不陈述事实", ""])
        elif section in article.gaps or not refs:
            outline_rows.append([section, "未覆盖", "无", "本节没有已核验事实，不写该节事实",
                                 article.gaps.get(section, "待补充事实")])
        else:
            outline_rows.append([section, "已覆盖", "、".join(refs), "", ""])
    checks = [[f"GC-{n:03d}", "CUS候选检测", category, f"{lead.claim.obj}的{category}", lead.pointer, "已核验",
               f"有效Claim连续原文直接陈述{category}，范围限于{lead.claim.obj}", "无", f"按证据使用：仅限{lead.claim.obj}"]
              for n, category in enumerate(checked, 1)] if lead else []
    gaps = "- 本轮待调研缺口：无" if not article.gaps else _table(
        ("GAP ID", "本轮具体公共知识问题", "与当前大纲关系", "本轮处理和证据", "审核结论"),
        [["GAP-T-001", reason, section, "待外部调研", "未解决"] for section, reason in article.gaps.items()])
    return (
        "# 知识准备与文章前审核\n\n"
        "- 知识准备记录协议：PR-2\n- 审核日期：2026-10-28\n- 结论：带明确排除通过\n"
        "- 明确排除：不写认证、商业条件或未核验的效果\n\n"
        "## 一、固定检索层状态\n\n"
        + (_table(("检索层", "当前状态", "结果或未查原因", "下一步"), layers) + "\n\n" if layers else "")
        + "## 二、候选事实\n\n" + _table(("候选事实ID", "独立事实摘要", "来源", "支持的大纲问题", "处置结果",
                                       "Formal Claim或排除/治理入口"), candidates) + "\n\n"
        "## 三、大纲逐项覆盖与审核\n\n" + _table(("大纲章节", "覆盖状态", "候选事实ID", "覆盖说明与边界", "缺口或治理事项"),
                                           outline_rows) + "\n\n"
        "## 四、CUS / ANM核验与审核\n\n"
        + ("### 逐项核验\n\n" + _table(("核验ID", "检测对象", "检测类别", "核验对象与范围", "来源指针", "核对结论",
                                      "判断依据", "事项入口", "本篇处理"), checks) + "\n\n" if checks else "")
        + "## 五、缺口与特殊资料\n\n### 本轮待调研缺口\n\n" + gaps + "\n\n"
        "### MAT依赖与资料选择\n\n- MAT依赖与资料选择：无\n\n"
        "### 复杂资料处理与原件核对\n\n- 复杂资料处理与原件核对：无\n\n"
        "## 六、结论说明\n"
    )
