#!/usr/bin/env python3
"""Move all unblocked, delivery-ready v0.6 article tasks to 20_等待终稿."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import date
from pathlib import Path

from article_state import article_package_errors, parse_field, task_ready_for_delivery, transition_task
from build_coverage_view import OUTPUT_RELATIVE, rebuild_view
from handoff_contract import current_version
from workflow_terminal import decide
from template_contract import (
    ARTICLE_AUDIT_TEMPLATE_VERSION,
    TEMPLATE_VERSION,
    validate_task_templates,
    table_rows,
)
from prewrite_governance import verified_self_test_details


def rebuild_coverage(project: Path) -> Path:
    """Refresh coverage after article state changes, using the same atomic write contract."""
    return rebuild_view(project)


def normalize_task_tables(task_dir: Path) -> list[Path]:
    """Compatibility helper for callers that explicitly request table cleanup.

    The advance command deliberately does not call this function.  Keeping it
    as an opt-in helper preserves the D-drive test/API contract without making
    delivery progression mutate task evidence.
    """
    changed: list[Path] = []
    for path in sorted(task_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        normalized = re.sub(r"(\|[^\n]*\|\n\|[-:| ]+\|)\n\n(?=\|)", r"\1\n", text)
        if normalized != text:
            path.write_text(normalized, encoding="utf-8")
            changed.append(path)
    return changed


def delivery_blockers(task_dir: Path) -> list[str]:
    required = (
        "10_文章知识需求.md", "15_检索与知识准备记录.md",
        "20_文章前知识审核.md", "30_本篇知识库资料.md",
        "35_写作素材来源索引.md",
    )
    missing = [name for name in required if not (task_dir / name).is_file()]
    if missing:
        return ["缺少交付文件：" + "、".join(missing)]
    errors = list(validate_task_templates(task_dir))
    retrieval = (task_dir / "15_检索与知识准备记录.md").read_text(encoding="utf-8-sig")
    material = (task_dir / "30_本篇知识库资料.md").read_text(encoding="utf-8-sig")
    audit = (task_dir / "20_文章前知识审核.md").read_text(encoding="utf-8-sig")
    request_text = (task_dir / "10_文章知识需求.md").read_text(encoding="utf-8-sig")
    knowledge_mode = parse_field(request_text, "任务模式")
    batch_id = parse_field(request_text, "批次ID")
    if batch_id and batch_id != "不适用":
        batch_safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", batch_id)
        batch_path = task_dir.parents[2] / "04_文章任务" / "批次运行" / f"{batch_safe}.json"
        if not batch_path.is_file():
            errors.append(f"批次账本不存在：{batch_id}")
        else:
            try:
                batch = json.loads(batch_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"批次账本无法读取：{exc}")
            else:
                article_id = parse_field(request_text, "文章ID")
                members = {str(row.get("article_id")) for row in batch.get("articles", [])}
                if article_id not in members:
                    errors.append(f"文章未登记在批次账本：{batch_id}")
                if batch.get("status") != "evidence_ready":
                    errors.append(f"批次证据尚未审核通过：{batch_id}")
    if knowledge_mode in {"new_article", "outline_refresh"}:
        # Both a new article and a fixed-outline rewrite must prove that the
        # website was checked per outline question.  A single homepage row is
        # not evidence of a complete website pass.
        website_rows = table_rows(retrieval, "## 官网正文核验")
        matrix_rows = table_rows(retrieval, "## 大纲逐项检索与候选事实覆盖")
        matrix_questions = [row[0].strip() for row in matrix_rows if row and row[0].strip()]
        website_questions = [row[0].strip() for row in website_rows if row]
        for question in matrix_questions:
            if not any(question == actual or question in actual or actual in question for actual in website_questions):
                errors.append(f"官网正文核验未覆盖大纲问题：{question}")
        if knowledge_mode == "outline_refresh" and "本轮知识上下文从空白开始" not in retrieval:
            errors.append("固定大纲重写必须声明知识输入仅来自当前大纲和本轮重新检索")
    if knowledge_mode == "outline_refresh":
        required_layers = ("已有正式Claim", "客户源资料", "客户官网", "关联网站", "已有外部公共Claim", "新外部调研")
        missing_layers = [layer for layer in required_layers if layer not in retrieval]
        if missing_layers:
            errors.append("知识重整未完成六层重新检索，缺少：" + "、".join(missing_layers))
        candidate_section = retrieval.split("## 候选事实处置明细", 1)[-1].split("## ", 1)[0]
        has_candidate = any(line.lstrip().startswith("|") and "---" not in line and "候选事实ID" not in line for line in candidate_section.splitlines())
        no_new_reason = any(mark in retrieval + material for mark in ("本轮无新增候选事实", "未形成可采纳的新Claim", "未采纳原因"))
        if not has_candidate and not no_new_reason:
            errors.append("知识重整未登记本轮候选事实，也未记录无新增/不采纳原因，禁止按重写完成")
    # 外部调研不能停留在15：必须形成35中的正式Claim映射，或明确记录未采纳原因。
    research_done = any(mark in retrieval for mark in ("外部调研已完成", "新外部调研：已完成", "RES已完成"))
    if research_done:
        source_index_text = (task_dir / "35_写作素材来源索引.md").read_text(encoding="utf-8-sig")
        imported = "CLM-EXT-" in source_index_text and "写作素材到正式知识映射" in source_index_text
        explained = any(
            mark in retrieval + audit
            for mark in ("未形成可采纳的新Claim", "未采纳原因", "不采纳原因")
        )
        if not (imported or explained):
            errors.append("外部调研已完成但未形成35中的外部正式Claim映射，且15/20未记录明确的不采纳原因")
    mat_state = parse_field(retrieval, "MAT依赖处理")
    if mat_state not in {"无", "已决定"}:
        errors.append(f"MAT依赖处理仍为{mat_state or '空'}")
    conclusion = parse_field(audit, "结论")
    if conclusion not in {"自动通过", "带明确排除通过"}:
        errors.append(f"文章前审核结论尚不可交付：{conclusion or '空'}")
    problem = task_dir / "文章前问题与处理单.md"
    if problem.is_file() and parse_field(problem.read_text(encoding="utf-8-sig"), "当前状态") != "已关闭":
        errors.append("文章前问题与处理单尚未关闭")
    errors.extend(article_package_errors(task_dir))
    return list(dict.fromkeys(errors))


def advance_project_detailed(project: Path, *, updated: str | None = None) -> dict[str, object]:
    project = project.resolve()
    source_root = project / "04_文章任务/10_进行中"
    if not source_root.is_dir():
        return {"moved": [], "repaired": [], "blocked": [], "research_required": []}
    moved: list[Path] = []
    blocked: list[tuple[Path, list[str]]] = []
    research_required: list[tuple[Path, list[str]]] = []
    updated = updated or date.today().isoformat()
    for task_dir in sorted(path for path in source_root.iterdir() if path.is_dir()):
        request = task_dir / "10_文章知识需求.md"
        reasons = delivery_blockers(task_dir)
        if reasons:
            blocked.append((task_dir, reasons))
            continue
        if not task_ready_for_delivery(task_dir):
            blocked.append((task_dir, ["交付门禁出现未分类错误；请登记SKFB，不要猜测修改10/15/20/30/35"]))
            continue
        text = request.read_text(encoding="utf-8-sig")
        article_id = parse_field(text, "文章ID")
        if not article_id:
            blocked.append((task_dir, [f"交付就绪文章缺少文章ID：{request}"]))
            continue
        title = parse_field(text, "标题") or parse_field(text, "文章标题") or task_dir.name
        try:
            moved.append(
                transition_task(
                    task_dir,
                    "20_等待终稿",
                    article_id=article_id,
                    human_text=f"{title}知识库资料已就绪，等待终稿",
                    blocked="否",
                    owner="内容运营负责人提交终稿；Codex接收后导入Faithfulness",
                    condition="文章要求、客户资料、30或35发生实质变化时归档并递增文章版本",
                    updated=updated,
                    link_file="30_本篇知识库资料.md",
                )
            )
        except Exception as exc:
            blocked.append((task_dir, [f"任务迁移失败：{exc}"]))
    if moved:
        rebuild_coverage(project)
    return {
        "moved": moved,
        "repaired": [],
        "blocked": blocked,
        "research_required": research_required,
    }


def advance_project(project: Path, *, updated: str | None = None) -> list[Path]:
    """Backward-compatible wrapper returning only successfully moved tasks."""
    return list(advance_project_detailed(project, updated=updated)["moved"])


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="v05-advance-ready-") as temp:
        root = Path(temp) / "DEMO_测试知识库_v0.6"
        task = root / "04_文章任务/10_进行中/DEMO-ART-001_测试文章"
        (root / "01_工作台").mkdir(parents=True)
        for state in ("10_进行中", "20_等待终稿", "30_等待Faithfulness", "40_已完成"):
            (root / "04_文章任务" / state).mkdir(parents=True, exist_ok=True)
        task.mkdir()
        (root / "01_工作台/20_当前待办.md").write_text(
            "# 当前待办\n\n| 对象ID | 人能看懂的事项 | 当前阶段 | 是否阻塞 | 下一步由谁做 | 直达链接 | 更新/重开条件 | 最近更新 |\n"
            "|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
        formal = root / "03_正式知识/10_客户知识/demo.md"
        formal.parent.mkdir(parents=True)
        formal.write_text(
            "# Demo\n\n- Claim ID：CLM-DEMO-001\n- Claim：Example Company provides custom packaging services.\n- Claim状态：有效\n- 来源链接：https://example.com/about-us/\n- 精确位置：About Us；Company Introduction第1段\n- 最小原文证据：Example Company provides custom packaging services.\n\nExample Company provides custom packaging services.\n",
            encoding="utf-8",
        )
        material_text = (
            "# 本篇写作素材包\n\n"
            "- 文章ID：DEMO-ART-001\n- 文章版本：v1\n"
            f"- 模板版本：{TEMPLATE_VERSION}\n"
            "- 资料视图：写作素材包\n- 资料版本：v1\n- 生成日期：2026-08-25\n"
            "- 目标语言：中文\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：not_applicable\n- 对应大纲：[[10_文章知识需求.md#大纲]]\n"
            "- 使用对象：写作流程；本文件为唯一写作事实输入。\n\n"
            "## 一、可直接用于正文的事实\n\n##### 证据正文（供Faithfulness核验）\n\n> Example Company provides custom packaging services.\n\n"
            "## 二、可直接采用的英文表达\n\n| 使用场景/大纲章节 | 可采用表达 | 使用条件 |\n|---|---|---|\n| 无 | 无 | 无 |\n\n"
            "## 三、可使用的数据表\n\n无\n\n"
            "## 四、按大纲使用\n\n| 大纲章节 | 可用事实/表达/数据表 | 推荐写作角度 |\n|---|---|---|\n| 测试 | 测试事实 | 直接说明 |\n\n"
            "## 五、仅供生成控制（不得写入正文）\n\n- 仅使用已提供事实。\n\n"
            "## 六、缺少资料的章节及建议处理方式\n\n| 原大纲章节 | 建议处理 | 可保留的安全写作方向 |\n|---|---|---|\n| 无 | 无需调整 | 按已提供素材写作 |\n"
        )
        files = {
            "10_文章知识需求.md": (
                "# 文章知识需求\n\n- 文章ID：DEMO-ART-001\n- 当前版本：v1\n"
                f"- 模板版本：{TEMPLATE_VERSION}\n- 交接合同版本：{current_version()}\n- 标题：测试文章\n- 关键词：测试\n"
                "- 目标语言：中文\n- 特殊限制：无\n- 大纲状态：已确认\n- 原始写作请求：测试写作请求\n"
                "- 产品或内容对象：测试对象\n- 选题方向：测试方向\n- 原始写作要求：测试要求\n- 当前状态：可准备知识\n- 写作Skill：测试写作Skill\n"
                "- 任务模式：new_article\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：not_applicable\n- 基线文章ID：不适用\n- 基线文章版本：不适用\n- 基线大纲ID：不适用\n- 基线大纲版本：不适用\n- 旧版本归档入口：不适用\n\n## 外部写作任务接入\n\n"
                "- 接入方式：显式提交\n- 外部任务唯一键：DEMO-001\n\n## 大纲\n\n- 测试\n\n"
                "## 随文章提交文件分类\n\n| 文件名 | 原始路径 | SHA-256 | 文件性质 | 使用范围 | 处理结果 |\n"
                "|---|---|---|---|---|---|\n| 无 | 无 | 无 | 无随文文件 | 不适用 | 不适用 |\n"
            ),
            "15_检索与知识准备记录.md": (
                "# 检索与知识准备记录\n\n- 文章ID：DEMO-ART-001\n- 文章版本：v1\n"
                f"- 模板版本：{TEMPLATE_VERSION}\n- 最近更新：2026-08-25\n- MAT依赖处理：无\n"
                "- 知识准备模式：new_article\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：not_applicable\n- 基线文章版本：不适用\n\n"
                "- 本轮知识检索运行ID：search-self-test-001\n- 官网正文抓取凭证：官网正文抓取凭证.json\n\n"
                "## 固定检索层状态\n\n| 检索层 | 当前状态 | 结果或未查原因 | 下一步 |\n|---|---|---|---|\n"
                "| 已有正式Claim | 已检索并命中 | CLM-DEMO-001 | 使用 |\n"
                "| 客户官网 | 已检索并命中 | About正文 https://example.com/about-us/ | CF-001已建立客户官网Claim |\n\n"
                "## 来源命中记录\n\n| 知识问题 | 命中Claim/资料名称与入口 | 相关理由 | 处理结果 |\n|---|---|---|---|\n"
                "| 测试问题 | CLM-DEMO-001；https://example.com/about-us/ Company Introduction第1段 | 直接支持 | 使用 |\n\n"
                "## 官网正文核验\n\n| 大纲章节/知识问题 | 页面名称与最终具体URL | 获取日期 | 正文位置 | 最小连续原文 | 候选事实ID或未命中 | 处置结果 |\n|---|---|---|---|---|---|---|\n"
                "| 标题 | About Us；https://example.com/about-us/ | 2026-08-25 | About Us；Company Introduction第1段 | Example Company provides custom packaging services. | CF-001 | 已读取并复用Formal Claim；同一候选事实明确支持多个问题（标题、主问题和测试） |\n"
                "| 主问题 | About Us；https://example.com/about-us/ | 2026-08-25 | About Us；Company Introduction第1段 | Example Company provides custom packaging services. | CF-001 | 已读取并复用Formal Claim；同一候选事实明确支持多个问题（标题、主问题和测试） |\n"
                "| 测试 | About Us；https://example.com/about-us/ | 2026-08-25 | About Us；Company Introduction第1段 | Example Company provides custom packaging services. | CF-001 | 已读取并复用Formal Claim；同一候选事实明确支持多个问题（标题、主问题和测试） |\n\n"
                "## 候选事实处置明细\n\n| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n|---|---|---|---|---|\n"
                "| CF-001 | Example Company provides custom packaging services. | https://example.com/about-us/ Company Introduction第1段 | 复用已有Formal Claim | CLM-DEMO-001 |\n\n"
                "## 本轮事实与Claim盘点\n\n| 本轮候选事实ID/当前Claim ID | 本轮重新打开的来源与精确位置 | 本轮证据结论 | 当前归类模块 | 本轮处置 | 依据 |\n"
                "|---|---|---|---|---|---|\n| CF-001 / CLM-DEMO-001 | https://example.com/about-us/ Company Introduction第1段 | 本轮新证据 | 客户知识 | 新建 | 本轮官网正文核验 |\n\n"
                "## 大纲逐项检索与候选事实覆盖\n\n| 大纲章节 | 六层检索范围与结果 | 命中来源与精确入口 | 候选事实ID | 候选事实数 | 已沉淀Claim数 | 未采用事实/缺口及原因 | 下一步 |\n|---|---|---|---|---:|---:|---|---|\n"
                "| 标题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | demo.md第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |\n"
                "| 主问题 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | demo.md第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |\n"
                "| 测试 | 已逐层检查正式Claim、源资料、官网、关联网站、外部Claim和新调研 | demo.md第1段 | CF-001 | 1 | 1 | 无 | 纳入30 |\n\n"
                "## MAT依赖与资料选择\n\n"
                "| MAT ID | 候选SRC ID | 文件名与稳定路径 | 关系/处理问题 | 决定 | 选取或排除范围 | 决定依据 | 决定方 | 当前状态 |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 无 | 无 | 无 | 无 | 无 | 无 | 无 | Codex自动处理 | 不适用 |\n\n"
                "## 复杂资料处理与原件核对\n\n| 资料ID | 文件名与稳定路径 | 未索引内容/处理原因 | 与本篇关系判断 | 实际处理范围与方法 | MinerU/提取稿入口 | 原件核对位置与结论 | MAT/ANM/CUS入口 | 最终状态 |\n"
                "|---|---|---|---|---|---|---|---|---|\n| 无 | 无 | 本篇无可能相关复杂资料 | 不适用 | 不适用 | 不适用 | 不适用 | 无 | 不适用 |\n"
            ),
            "20_文章前知识审核.md": (
                "# 文章前知识审核\n\n- 文章ID：DEMO-ART-001\n- 文章版本：v1\n"
                f"- 审核模板版本：{ARTICLE_AUDIT_TEMPLATE_VERSION}\n- 审核日期：2026-08-25\n"
                "- 结论：自动通过\n- 可用Claim数：1\n- 客户来源：1\n- 外部来源：0\n"
                "- 明确排除：无\n- 未解决但不阻塞事项：无\n"
                "- 计划写作素材：审核通过后生成30_本篇知识库资料.md\n- 计划写作素材来源索引：审核通过后生成35_写作素材来源索引.md\n"
                "- 知识准备模式：new_article\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：not_applicable\n- 基线文章版本：不适用\n\n"
                "## 本轮知识准备复核\n\n| 复核项 | 15记录入口 | 审核结论 | 阻塞或排除 |\n|---|---|---|---|\n"
                "| 本轮六层检索 | [[15_检索与知识准备记录.md#固定检索层状态]] | 新文章从空白上下文执行 | 无 |\n"
                "| 本轮官网正文与凭证 | [[15_检索与知识准备记录.md#官网正文核验]] | 标题、主问题和每个大纲问题均有当前凭证 | 无 |\n"
                "| 本轮Claim盘点 | [[15_检索与知识准备记录.md#本轮事实与claim盘点]] | 逐候选事实记录新建或复用 | 无 |\n"
                "| 30/35重新生成 | [[15_检索与知识准备记录.md#候选事实处置明细]] | 已按本轮事实生成 | 无 |\n\n"
                "## 大纲知识覆盖检查\n\n| 大纲章节 | 知识问题 | 覆盖状态 | 已有证据/Claim | 缺口或治理事项 | 本篇处理 |\n"
                "|---|---|---|---|---|---|\n| 标题 | 标题是否有事实支撑 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |\n"
                "| 主问题 | 测试问题 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |\n"
                "| 测试 | 测试问题 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |\n\n"
                "## 知识准备充分性复核\n\n| 大纲章节 | 候选事实数 | 已沉淀Claim数 | 计划纳入30的事实块数 | 覆盖结论 | 未采用事实/缺口及入口 |\n|---|---:|---:|---:|---|---|\n"
                "| 标题 | 1 | 1 | 1 | 充分 | 无 |\n| 主问题 | 1 | 1 | 1 | 充分 | 无 |\n| 测试 | 1 | 1 | 1 | 充分 | 无 |\n\n"
                "## 复杂资料与原件核对复核\n\n| 资料ID | 15处理记录入口 | 最终状态 | 对当前事实/Claim影响 | 本篇审核结论 |\n"
                "|---|---|---|---|---|\n| 无 | [[15_检索与知识准备记录.md#复杂资料处理与原件核对]] | 不适用 | 无复杂资料不影响Claim | 本篇无可能相关复杂资料，复核通过 |\n\n"
                "## CUS / ANM检测结果\n\n| 检测对象 | 已检查信号与来源 | 分类结论 | 事项与证据入口 | 本篇处理 |\n"
                "|---|---|---|---|---|\n| CUS候选检测 | 已核对客户能力、规格、认证、案例、商业条件、公开授权，以及Formal Claim和来源范围 | 未触发 | [[demo.md]] | 无需处理 |\n"
                "| ANM异常检测 | 已核对版本、定位与数值 | 未触发 | [[demo.md]] | 无需处理 |\n\n"
                + verified_self_test_details()
            ),
            "30_本篇知识库资料.md": material_text,
            "35_写作素材来源索引.md": (
                "# 写作素材来源索引\n\n- 文章ID：DEMO-ART-001\n- 文章版本：v1\n- 大纲ID：DEMO-OUT-001\n- 大纲版本：v1\n- 重写模式：not_applicable\n"
                f"- 模板版本：{TEMPLATE_VERSION}\n- 索引版本：v1\n- 生成日期：2026-08-25\n"
                "- 对应写作素材：[[30_本篇知识库资料.md]]\n- 写作素材SHA-256：__MATERIAL_HASH__\n"
                "- 用途：仅供内部追溯与Faithfulness映射；不得交给写作模型。\n\n"
                "## 写作素材到正式知识映射\n\n| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |\n"
                "|---:|---:|---|---|---|---|---|\n| 20 | 20 | 测试事实 | CLM-DEMO-001 | 测试事实 | [[03_正式知识/10_客户知识/demo.md]] | https://example.com/about-us/ Company Introduction第1段 |\n\n"
                "## 写作事实输入确认\n\n- 唯一事实输入：[[30_本篇知识库资料.md]]\n- 其他事实附件：无；随文事实文件必须先进入来源层、Formal Claim和当前30/35。\n"
            ),
        }
        for name, content in files.items():
            (task / name).write_text(content, encoding="utf-8")
        (task / "官网正文抓取凭证.json").write_text(
            json.dumps([
                {
                    "refresh_run_id": "search-self-test-001", "question": question,
                    "final_url": url, "fetched_date": "2026-08-25", "position": "About Us；Company Introduction第1段",
                    "excerpt": "Example Company provides custom packaging services.",
                    "website_id": "PRIMARY-WEBSITE", "source_type": "客户官网",
                    "block_id": "B001", "block_tag": "p", "heading_path": ["About"],
                    "block_text": "Example Company provides custom packaging services.",
                    "excerpt_sha256": hashlib.sha256(
                        "Example Company provides custom packaging services.".encode()
                    ).hexdigest(),
                    "response_sha256": "demo",
                }
                for question, url in (
                    ("标题", "https://example.com/about-us/"),
                    ("主问题", "https://example.com/about-us/"),
                    ("测试", "https://example.com/about-us/"),
                )
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        material_hash = hashlib.sha256((task / "30_本篇知识库资料.md").read_bytes()).hexdigest()
        source_index_path = task / "35_写作素材来源索引.md"
        source_index_path.write_text(
            source_index_path.read_text(encoding="utf-8").replace("__MATERIAL_HASH__", material_hash),
            encoding="utf-8",
        )
        if not task_ready_for_delivery(task):
            from template_contract import validate_task_templates
            raise AssertionError(
                "delivery-ready task was not recognized by the strict gate: "
                + repr(validate_task_templates(task))
                + " package=" + repr(article_package_errors(task))
            )
        retrieval_path = task / "15_检索与知识准备记录.md"
        retrieval_text = retrieval_path.read_text(encoding="utf-8")
        retrieval_path.write_text(
            retrieval_text.replace("| 无 | 无 | 本篇无可能相关复杂资料 | 不适用 | 不适用 | 不适用 | 不适用 | 无 | 不适用 |", "| SRC-DEMO001 | 资料.pdf | 第2页图表待处理 | 可能相关 | 待处理 | 待处理 | 待处理 | MAT-DEMO-001 | 等待材料或工具 |"),
            encoding="utf-8",
        )
        if task_ready_for_delivery(task):
            raise AssertionError("task with unresolved complex material passed the delivery gate")
        retrieval_path.write_text(retrieval_text, encoding="utf-8")
        moved = advance_project(root, updated="2026-08-25")
        if len(moved) != 1 or not (root / "04_文章任务/20_等待终稿/DEMO-ART-001_测试文章").is_dir():
            raise AssertionError("delivery-ready task was not moved")
        coverage = root / OUTPUT_RELATIVE
        if not coverage.is_file() or "覆盖数据指纹：" not in coverage.read_text(encoding="utf-8"):
            raise AssertionError("coverage view was not rebuilt after migration")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--updated")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if not args.project:
        raise SystemExit("--project is required unless --self-test is used")
    outcome = advance_project_detailed(args.project, updated=args.updated)
    moved = list(outcome["moved"])
    repaired = list(outcome["repaired"])
    blocked = list(outcome["blocked"])
    research_required = list(outcome["research_required"])
    for path in moved:
        print(f"moved={path}")
    for path in repaired:
        print(f"repaired={path}")
    for task, reasons in blocked:
        print(f"blocked_task={task}")
        for reason in reasons:
            print(f"blocked_reason={reason}")
    for task, gap_ids in research_required:
        print(f"research_task={task}")
        for gap_id in gap_ids:
            print(f"research_required={gap_id}")
        print("next_action=当前Agent继续按external-research-contract.md完成定向外部调研和RES/正式Claim沉淀；完成后重新运行本脚本，不得把本次输出当作任务终点")
        print("terminal=false")
    if blocked:
        print("next_action=逐项修复当前任务门禁并重新运行本脚本；门禁失败不是文章完成状态")
        print("terminal=false")
    if moved:
        # Project-level migration is bookkeeping, not the article-level
        # writing authorization.  Make the required next handoff explicit so
        # an outer orchestrator cannot treat a successful move as completion.
        print("next_action=已迁移就绪任务；逐篇运行 issue_writing_ready.py 并读取 writing_gate_result.json，再交给写作Skill")
        print("terminal=false")
    if not moved and not blocked and not research_required:
        decision = decide(reason="moved_count_zero")
        print(f"terminal={str(decision.terminal).lower()}")
        print(f"next_action={decision.next_action}")
    print(f"moved_count={len(moved)}")
    print(f"repaired_count={len(repaired)}")
    print(f"blocked_count={len(blocked)}")
    print(f"research_required_count={sum(len(gap_ids) for _, gap_ids in research_required)}")


if __name__ == "__main__":
    main()
