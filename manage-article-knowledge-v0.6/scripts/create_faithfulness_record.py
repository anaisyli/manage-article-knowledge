#!/usr/bin/env python3
"""Create the post-writing Faithfulness record as soon as a final article arrives."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from article_state import transition_task, validate_transition_inputs
from check_integration import faithfulness_result_dir, project_id_for_root
from handoff_contract import HandoffContractError, load_contract, validate_event, validate_version
from template_contract import TEMPLATE_VERSION
from update_integration_status import update as update_integration_status


class FaithfulnessSkillUnavailable(SystemExit):
    """The final was accepted, but the configured audit executor is unavailable."""


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode text file: {path}")


def parse_field(text: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*]\s*{re.escape(label)}[：:]\s*(.*?)\s*$",
        text,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def declared_skill_name(skill_root: Path) -> str:
    skill_file = skill_root / "SKILL.md"
    if not skill_file.is_file():
        return ""
    match = re.search(r"^name:\s*([^\r\n]+)$", read_text(skill_file), re.MULTILINE)
    return match.group(1).strip() if match else ""


def resolve_faithfulness_skill(explicit: Path | None = None) -> Path | None:
    name = "deepeval-article-audit"
    if explicit:
        root = explicit.expanduser().resolve()
        if declared_skill_name(root) != name:
            raise ValueError(f"指定目录不是{name} Skill：{root}")
        return root
    candidates: list[Path] = []
    configured_home = os.environ.get("CODEX_HOME", "").strip()
    if configured_home:
        candidates.append(Path(configured_home) / "skills" / name)
    home = Path.home()
    candidates.extend((home / ".codex" / "skills" / name, home / ".agents" / "skills" / name))
    for root in candidates:
        if declared_skill_name(root) == name:
            return root.resolve()
    return None


def faithfulness_handoff_lines(skill_root: Path | None) -> list[str]:
    if skill_root:
        return [
            "handoff_event=faithfulness_request",
            f"faithfulness_skill_path={skill_root}",
            "next_action=invoke_installed_skill_now",
        ]
    return [
        "handoff_event=handoff_error",
        "error_code=faithfulness_skill_not_found",
        "blocked_step=faithfulness_request",
        "human_message=当前未安装 deepeval-article-audit Skill，无法继续本篇文章的 Faithfulness 审核。",
        "next_action=请安装该 Skill，或提供其所在目录的绝对路径；任务已保留在30_等待Faithfulness，当前没有审核结论。",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--article", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, action="append", required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--integration-config", type=Path)
    parser.add_argument("--handoff-contract-version", required=True)
    parser.add_argument(
        "--faithfulness-skill-path",
        type=Path,
        help="仅在Skill未安装到标准目录时显式提供；不会写入通用合同",
    )
    args = parser.parse_args()

    try:
        contract = load_contract()
        contract_version = validate_version(args.handoff_contract_version, contract)
    except HandoffContractError as exc:
        raise SystemExit(str(exc)) from exc

    for path in [args.article, args.source_index, *args.knowledge]:
        if not path.is_file():
            raise SystemExit(f"Required file not found: {path}")
    if len(args.knowledge) != 1 or args.knowledge[0].name != "30_本篇知识库资料.md":
        raise SystemExit(
            "manage-article-knowledge v0.6 requires exactly one factual input: 30_本篇知识库资料.md"
        )
    if parse_field(read_text(args.knowledge[0]), "资料视图") != "写作素材包":
        raise SystemExit("30_本篇知识库资料.md must declare 资料视图：写作素材包")
    receipt_exists = args.receipt.exists()

    article_text = read_text(args.article)
    article_id = parse_field(article_text, "文章ID")
    article_version = parse_field(article_text, "文章版本")
    article_date = parse_field(article_text, "完成日期")
    article_title = parse_field(article_text, "文章标题") or parse_field(
        article_text, "最终标题"
    ) or args.article.stem
    if not article_id or not article_version or not article_date:
        raise SystemExit("Final article must contain 文章ID、文章版本 and 完成日期")

    if args.result_dir and args.integration_config:
        raise SystemExit("Do not combine --result-dir with --integration-config")
    if args.integration_config:
        if not args.integration_config.is_file():
            raise SystemExit(f"Integration config not found: {args.integration_config}")
        try:
            args.result_dir = faithfulness_result_dir(
                args.integration_config.resolve(), article_id, article_version
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if args.result_dir:
        # The configured root may be the only directory supplied at onboarding.
        # Create the article-version directory now so the external auditor has a
        # deterministic destination before it starts writing artifacts.
        args.result_dir.resolve().mkdir(parents=True, exist_ok=True)

    source_text = read_text(args.source_index)
    if parse_field(source_text, "文章ID") != article_id:
        raise SystemExit("Article ID mismatch between final article and source index")
    if parse_field(source_text, "文章版本") != article_version:
        raise SystemExit("Article version mismatch between final article and source index")

    knowledge_hashes = [sha256_file(path) for path in args.knowledge]
    knowledge_text = "；".join(
        f"{path.resolve()} = {checksum}"
        for path, checksum in zip(args.knowledge, knowledge_hashes)
    )
    result_dir = str(args.result_dir.resolve()) if args.result_dir else "未指定"
    if not args.result_dir:
        raise SystemExit(
            "faithfulness_request requires a version-specific result_dir; "
            "configure Faithfulness结果根目录 or supply --result-dir"
        )
    project_root = args.article.resolve().parents[3]
    try:
        project_id = project_id_for_root(project_root)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    result_root = args.result_dir.resolve().parents[2]
    faithfulness_skill = str(contract["faithfulness_executor"]["skill_name"])
    try:
        faithfulness_skill_root = resolve_faithfulness_skill(args.faithfulness_skill_path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    request_payload = {
        "handoff_event": "faithfulness_request",
        "handoff_contract_version": contract_version,
        "faithfulness_skill": faithfulness_skill,
        "article_file": str(args.article.resolve()),
        "knowledge_file": str(args.knowledge[0].resolve()),
        "project_id": project_id,
        "article_id": article_id,
        "article_version": article_version,
        "result_root": str(result_root),
        "result_dir": result_dir,
    }
    try:
        validate_event("faithfulness_request", request_payload, contract)
    except HandoffContractError as exc:
        raise SystemExit(str(exc)) from exc
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    task_dir = args.article.parent
    article_title_for_todo = article_title
    try:
        validate_transition_inputs(task_dir, "30_等待Faithfulness")
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        raise SystemExit(f"状态迁移预检查失败，未创建或修改Faithfulness记录：{exc}") from exc
    receipt_text = (
        "\n".join(
            [
                "# 文章知识使用与Faithfulness记录",
                "",
                f"- 文章ID：{article_id}",
                f"- 文章标题：{article_title}",
                f"- 文章版本：{article_version}",
                f"- 模板版本：{TEMPLATE_VERSION}",
                f"- 交接合同版本：{contract_version}",
                "- 当前状态：等待Faithfulness结果",
                f"- 终稿：[[{args.article.name}]]",
                "- 本篇知识库资料：[[30_本篇知识库资料.md]]",
                f"- 写作素材来源索引：[[{args.source_index.name}]]",
                f"- 终稿接收日期：{article_date}",
                "- Faithfulness结果入口：指定审核结果目录" if args.result_dir else "- Faithfulness结果入口：内容运营提交",
                f"- 指定审核结果目录：{result_dir}",
                "- Faithfulness导入日期：未导入",
                f"- Faithfulness执行器：{faithfulness_skill}",
                "- 外部审核模式：未导入",
                "- 外部结果文件：未导入",
                "- unsupported归组处置文件：等待结果 / 不适用（无unsupported）",
                f"- 终稿SHA-256：{sha256_file(args.article)}",
                f"- 本篇知识库资料及SHA-256：{knowledge_text}",
                "",
                "## 一、Faithfulness结果",
                "",
                "| 支持事实主张数 | 全部事实主张数 | 不支持事实主张数 | Faithfulness | 正式Claim映射数 | 未映射的支持主张数 |",
                "|---:|---:|---:|---:|---:|---:|",
                "| 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 |",
                "",
                "## 二、正式知识对文章事实的支撑",
                "",
                "以下是审核后的事后证据支撑关系，不代表写作模型内部实际调用轨迹。",
                "",
                "| 文章事实/位置 | Formal Claim及通俗标题 | 正式知识文件 | 原始来源与位置 | 支撑判断 |",
                "|---|---|---|---|---|",
                "| 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 |",
                "",
                "## 三、未被本次知识附件覆盖的内容",
                "",
                "| 归组及claim_id | 知识问题/内容 | 分类 | 分类依据 | 本篇影响 | 关联事项/入口 | 当前处理 | 下一步 |",
                "|---|---|---|---|---|---|---|---|",
                "| 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 |",
                "",
                "## 四、后续动作",
                "",
                "| 事项 | 当前状态 | 下一责任人 | 关联入口 | 更新/关闭条件 |",
                "|---|---|---|---|---|",
                "| 无 | 无需处理 | 无 | 无 | 同类主题跨文章或连续月份反复出现时月度重评 |",
                "",
                "## 五、更新记录",
                "",
                "| 日期 | 事件 | 结果/状态 | 相关文件 |",
                "|---|---|---|---|",
                f"| {created_at} | 收到终稿并创建记录 | 等待Faithfulness结果 | [[{args.article.name}]] |",
                "",
            ]
        )
    )
    if not receipt_exists:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.receipt.with_suffix(args.receipt.suffix + ".tmp")
        temporary.write_text(receipt_text, encoding="utf-8")
        temporary.replace(args.receipt)
    transitioned = transition_task(
        task_dir,
        "30_等待Faithfulness",
        article_id=article_id,
        human_text=f"{article_title_for_todo}已收到终稿，等待外部Faithfulness审核",
        blocked="是",
                owner="Codex自动调用deepeval-article-audit；仅缺失或失败时通知内容运营",
                condition="已安装或校验通过的审核Skill返回结果后自动导入；终稿或30变化时重开",
        updated=created_at[:10],
        link_file="50_文章知识使用与Faithfulness记录.md",
    )
    update_integration_status(
        project_root,
        "final_received_success",
        article_id=article_id,
        article_version=article_version,
        detail="已创建50_文章知识使用与Faithfulness记录",
    )
    if receipt_exists:
        print("receipt=existing (recovery)")
    print(f"article_id={article_id}")
    print(f"article_version={article_version}")
    print(f"handoff_contract_version={contract_version}")
    print("status=等待Faithfulness结果")
    print(f"task={transitioned}")
    print(f"receipt={transitioned / args.receipt.name}")
    print(f"faithfulness_skill={faithfulness_skill}")
    for line in faithfulness_handoff_lines(faithfulness_skill_root):
        print(line)
    print(f"article_file={transitioned / args.article.name}")
    print(f"knowledge_file={transitioned / args.knowledge[0].name}")
    print(f"project_id={project_id}")
    print(f"result_root={result_root}")
    print(f"result_dir={args.result_dir.resolve()}")
    if not faithfulness_skill_root:
        update_integration_status(
            project_root,
            "faithfulness_import_failure",
            article_id=article_id,
            article_version=article_version,
            error="faithfulness_skill_not_found",
            detail="任务保留在30_等待Faithfulness；等待安装或指定审核Skill目录",
        )
        raise FaithfulnessSkillUnavailable(
            "当前未安装 deepeval-article-audit Skill，无法继续本篇文章的Faithfulness审核；"
            "请安装该Skill或使用--faithfulness-skill-path指定目录。"
        )


if __name__ == "__main__":
    try:
        main()
    except FaithfulnessSkillUnavailable:
        # The final article has already been accepted and the task is safely
        # waiting for the missing audit Skill; do not relabel it as a final failure.
        raise
    except SystemExit as exc:
        # Best-effort failure telemetry; never hide the original CLI error.
        try:
            if "--article" in sys.argv:
                article = Path(sys.argv[sys.argv.index("--article") + 1]).resolve()
                if article.is_file() and len(article.parents) >= 4:
                    update_integration_status(
                        article.parents[3],
                        "final_received_failure",
                        error=str(exc),
                    )
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            if "--article" in sys.argv:
                article = Path(sys.argv[sys.argv.index("--article") + 1]).resolve()
                if article.is_file() and len(article.parents) >= 4:
                    update_integration_status(
                        article.parents[3],
                        "final_received_failure",
                        error=str(exc),
                    )
        except Exception:
            pass
        raise
