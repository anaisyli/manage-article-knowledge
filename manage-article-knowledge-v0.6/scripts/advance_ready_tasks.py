#!/usr/bin/env python3
"""Move all unblocked, delivery-ready v0.6 article tasks to 20_等待终稿."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from datetime import date
from pathlib import Path

from article_state import parse_field, task_ready_for_delivery, transition_task
from build_coverage_view import OUTPUT_RELATIVE, build_view
from handoff_contract import current_version
from template_contract import ARTICLE_AUDIT_TEMPLATE_VERSION, TEMPLATE_VERSION


def rebuild_coverage(project: Path) -> Path:
    """Refresh coverage after article state changes, using the same atomic write contract."""
    output = project / OUTPUT_RELATIVE
    output.parent.mkdir(parents=True, exist_ok=True)
    text = build_view(project)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(output)
    return output


def advance_project(project: Path, *, updated: str | None = None) -> list[Path]:
    project = project.resolve()
    source_root = project / "04_文章任务/10_进行中"
    if not source_root.is_dir():
        return []
    moved: list[Path] = []
    updated = updated or date.today().isoformat()
    for task_dir in sorted(path for path in source_root.iterdir() if path.is_dir()):
        if not task_ready_for_delivery(task_dir):
            continue
        request = task_dir / "10_文章知识需求.md"
        text = request.read_text(encoding="utf-8-sig")
        article_id = parse_field(text, "文章ID")
        if not article_id:
            raise ValueError(f"交付就绪文章缺少文章ID：{request}")
        title = parse_field(text, "标题") or parse_field(text, "文章标题") or task_dir.name
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
    if moved:
        rebuild_coverage(project)
    return moved


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
            "# Demo\n\n- Claim ID：CLM-DEMO-001\n- Claim：测试事实。\n",
            encoding="utf-8",
        )
        material_text = (
            "# 本篇写作素材包\n\n"
            "- 文章ID：DEMO-ART-001\n- 文章版本：v1\n"
            f"- 模板版本：{TEMPLATE_VERSION}\n"
            "- 资料视图：写作素材包\n- 资料版本：v1\n- 生成日期：2026-08-25\n"
            "- 目标语言：中文\n- 对应大纲：[[10_文章知识需求.md#大纲]]\n"
            "- 使用对象：写作流程；本文件为唯一写作事实输入。\n\n"
            "## 一、可直接用于正文的事实\n\n##### 证据正文（供Faithfulness核验）\n\n> 测试事实。\n\n"
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
                "- 产品或内容对象：测试对象\n- 选题方向：测试方向\n- 原始写作要求：测试要求\n- 当前状态：可准备知识\n- 写作Skill：测试写作Skill\n\n## 外部写作任务接入\n\n"
                "- 接入方式：显式提交\n- 外部任务唯一键：DEMO-001\n\n## 大纲\n\n- 测试\n\n"
                "## 随文章提交文件分类\n\n| 文件名 | 原始路径 | SHA-256 | 文件性质 | 使用范围 | 处理结果 |\n"
                "|---|---|---|---|---|---|\n| 无 | 无 | 无 | 无随文文件 | 不适用 | 不适用 |\n"
            ),
            "15_检索与知识准备记录.md": (
                "# 检索与知识准备记录\n\n- 文章ID：DEMO-ART-001\n- 文章版本：v1\n"
                f"- 模板版本：{TEMPLATE_VERSION}\n- 最近更新：2026-08-25\n- MAT依赖处理：无\n\n"
                "## 固定检索层状态\n\n| 检索层 | 当前状态 | 结果或未查原因 | 下一步 |\n|---|---|---|---|\n"
                "| 已有正式Claim | 已检索并命中 | CLM-DEMO-001 | 使用 |\n\n"
                "## 来源命中记录\n\n| 知识问题 | 命中Claim/资料名称与入口 | 相关理由 | 处理结果 |\n|---|---|---|---|\n"
                "| 测试问题 | CLM-DEMO-001 | 直接支持 | 使用 |\n\n"
                "## 候选事实处置明细\n\n| 候选事实ID | 独立事实摘要 | 来源与精确位置 | 处置结果 | Formal Claim或排除/治理入口 |\n|---|---|---|---|---|\n"
                "| CF-001 | 测试独立事实 | demo.md第1段 | 已沉淀Formal Claim | CLM-DEMO-001 |\n\n"
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
                "- 计划写作素材：审核通过后生成30_本篇知识库资料.md\n- 计划写作素材来源索引：审核通过后生成35_写作素材来源索引.md\n\n"
                "## 大纲知识覆盖检查\n\n| 大纲章节 | 知识问题 | 覆盖状态 | 已有证据/Claim | 缺口或治理事项 | 本篇处理 |\n"
                "|---|---|---|---|---|---|\n| 标题 | 标题是否有事实支撑 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |\n"
                "| 主问题 | 测试问题 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |\n"
                "| 测试 | 测试问题 | 已覆盖 | CLM-DEMO-001 | 无 | 使用 |\n\n"
                "## 知识准备充分性复核\n\n| 大纲章节 | 候选事实数 | 已沉淀Claim数 | 计划纳入30的事实块数 | 覆盖结论 | 未采用事实/缺口及入口 |\n|---|---:|---:|---:|---|---|\n"
                "| 标题 | 1 | 1 | 1 | 充分 | 无 |\n| 主问题 | 1 | 1 | 1 | 充分 | 无 |\n| 测试 | 1 | 1 | 1 | 充分 | 无 |\n\n"
                "## 复杂资料与原件核对复核\n\n| 资料ID | 15处理记录入口 | 最终状态 | 对当前事实/Claim影响 | 本篇审核结论 |\n"
                "|---|---|---|---|---|\n| 无 | [[15_检索与知识准备记录.md#复杂资料处理与原件核对]] | 不适用 | 无复杂资料不影响Claim | 本篇无可能相关复杂资料，复核通过 |\n\n"
                "## CUS / ANM检测结果\n\n| 检测对象 | 已检查信号与来源 | 分类结论 | 事项与证据入口 | 本篇处理 |\n"
                "|---|---|---|---|---|\n| CUS候选检测 | 已核对正式Claim与来源 | 未触发 | [[demo.md]] | 无需处理 |\n"
                "| ANM异常检测 | 已核对版本、定位与数值 | 未触发 | [[demo.md]] | 无需处理 |\n"
            ),
            "30_本篇知识库资料.md": material_text,
            "35_写作素材来源索引.md": (
                "# 写作素材来源索引\n\n- 文章ID：DEMO-ART-001\n- 文章版本：v1\n"
                f"- 模板版本：{TEMPLATE_VERSION}\n- 索引版本：v1\n- 生成日期：2026-08-25\n"
                "- 对应写作素材：[[30_本篇知识库资料.md]]\n- 写作素材SHA-256：__MATERIAL_HASH__\n"
                "- 用途：仅供内部追溯与Faithfulness映射；不得交给写作模型。\n\n"
                "## 写作素材到正式知识映射\n\n| 证据正文行开始 | 证据正文行结束 | 素材主题 | 正式Claim ID | Claim通俗标题 | 正式知识文件 | 原始来源与精确位置 |\n"
                "|---:|---:|---|---|---|---|---|\n| 17 | 17 | 测试事实 | CLM-DEMO-001 | 测试事实 | [[03_正式知识/10_客户知识/demo.md]] | demo.md |\n\n"
                "## 写作事实输入确认\n\n- 唯一事实输入：[[30_本篇知识库资料.md]]\n- 其他事实附件：无；随文事实文件必须先进入来源层、Formal Claim和当前30/35。\n"
            ),
        }
        for name, content in files.items():
            (task / name).write_text(content, encoding="utf-8")
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
    moved = advance_project(args.project, updated=args.updated)
    for path in moved:
        print(f"moved={path}")
    print(f"moved_count={len(moved)}")


if __name__ == "__main__":
    main()
