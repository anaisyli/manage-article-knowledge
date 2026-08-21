#!/usr/bin/env python3
"""Create the post-writing Faithfulness record as soon as a final article arrives."""

from __future__ import annotations

import argparse
import hashlib
import re
from datetime import datetime
from pathlib import Path

from article_state import transition_task


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--article", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, action="append", required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path)
    args = parser.parse_args()

    for path in [args.article, args.source_index, *args.knowledge]:
        if not path.is_file():
            raise SystemExit(f"Required file not found: {path}")
    if len(args.knowledge) != 1 or args.knowledge[0].name != "30_本篇知识库资料.md":
        raise SystemExit(
            "manage-article-knowledge v0.5 requires exactly one factual input: 30_本篇知识库资料.md"
        )
    if parse_field(read_text(args.knowledge[0]), "资料视图") != "写作素材包":
        raise SystemExit("30_本篇知识库资料.md must declare 资料视图：写作素材包")
    if args.receipt.exists():
        raise SystemExit(f"Record already exists; do not overwrite it: {args.receipt}")

    article_text = read_text(args.article)
    article_id = parse_field(article_text, "文章ID")
    article_version = parse_field(article_text, "文章版本")
    article_date = parse_field(article_text, "完成日期")
    article_title = parse_field(article_text, "文章标题") or parse_field(
        article_text, "最终标题"
    ) or args.article.stem
    if not article_id or not article_version or not article_date:
        raise SystemExit("Final article must contain 文章ID、文章版本 and 完成日期")

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
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.receipt.with_suffix(args.receipt.suffix + ".tmp")
    temporary.write_text(
        "\n".join(
            [
                "# 文章知识使用与Faithfulness记录",
                "",
                f"- 文章ID：{article_id}",
                f"- 文章标题：{article_title}",
                f"- 文章版本：{article_version}",
                "- 当前状态：等待Faithfulness结果",
                f"- 终稿：[[{args.article.name}]]",
                "- 本篇知识库资料：[[30_本篇知识库资料.md]]",
                f"- 写作素材来源索引：[[{args.source_index.name}]]",
                f"- 终稿接收日期：{article_date}",
                "- Faithfulness结果入口：指定审核结果目录" if args.result_dir else "- Faithfulness结果入口：内容运营提交",
                f"- 指定审核结果目录：{result_dir}",
                "- Faithfulness导入日期：未导入",
                "- 外部审核模式：未导入",
                "- 外部结果文件：未导入",
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
                "| 主题/类型 | 人能看懂的内容说明 | 本篇影响 | 处理方式 | 重开/升级条件 |",
                "|---|---|---|---|---|",
                "| 等待结果 | 等待结果 | 等待结果 | 等待结果 | 等待结果 |",
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
        ),
        encoding="utf-8",
    )
    temporary.replace(args.receipt)
    task_dir = args.article.parent
    article_title_for_todo = article_title
    transitioned = transition_task(
        task_dir,
        "30_等待Faithfulness",
        article_id=article_id,
        human_text=f"{article_title_for_todo}已收到终稿，等待外部Faithfulness审核",
        blocked="是",
        owner="内容运营提交或指定Faithfulness审核目录；Codex导入",
        condition="收到与当前终稿和30哈希匹配的外部结果后自动导入；终稿或30变化时重开",
        updated=created_at[:10],
        link_file="50_文章知识使用与Faithfulness记录.md",
    )
    print(f"article_id={article_id}")
    print("status=等待Faithfulness结果")
    print(f"task={transitioned}")
    print(f"receipt={transitioned / args.receipt.name}")


if __name__ == "__main__":
    main()
