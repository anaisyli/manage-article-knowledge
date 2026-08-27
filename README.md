# Manage Article Knowledge

manage-article-knowledge是面向内容运营的企业文章知识库管理Skill。当前活动开发版本是v0.5。

## v0.5核心方式

初始化时把客户材料登记为可搜索来源，但不做全量知识整理。具体文章命中某段材料后，才回到原始证据提取和核验正式Claim。普通任务由主Agent完成；只有高风险、冲突或复杂材料才独立审核。

流程为：

    初始化来源台账与机器索引
    → 接收文章标题、关键词、大纲、目标语言和限制
    → 搜索已有Claim、客户资料、客户官网和已有外部知识
    → 仅对具体公共知识缺口开展外部调研
    → 命中后按需核验Claim
    → 自动完成文章前知识审核
    → 交付30_本篇知识库资料.md
    → 接收40_最终文章.md
    → 导入独立审核Skill的Faithfulness结果
    → 执行月度审核与负责人交接

各运营组继续使用自己的写作和SEO/GEO流程。本Skill不写文章、不融合写作指令，也不在内部执行Faithfulness评价。

## 保留的治理能力

- 原始证据、精确定位、版本和使用边界；
- 完全重复与疑似版本关系；
- PDF、Office、图片、扫描页、网页、压缩包和复杂材料处理；
- MinerU API初始化、健康检查、到期提醒和按需解析；
- CUS、MAT、ANM、SKFB四类台账；
- 项目运行账本、五部分月度审核和负责人交接；
- 每篇终稿的外部Faithfulness结果和Claim文章支撑映射。

音频和视频不自动转写，只登记基础信息并由AI知识库专员通过MAT处理。其他无法可靠自动处理的复杂资料也走同一机制，不交给内容运营做技术处理。

## 目录

    manage-article-knowledge/
      README.md
      manage-article-knowledge-v0.5/   当前活动版本
        SKILL.md
        agents/
        references/
        scripts/
      versions/                       冻结历史版本
        manage-article-knowledge-v0.1/
        manage-article-knowledge-v0.2/
        manage-article-knowledge-v0.3/
        manage-article-knowledge-v0.4/
      changelog/

- [v0.5 Skill](manage-article-knowledge-v0.5/SKILL.md)
- [v0.5稳定性兼容清单](manage-article-knowledge-v0.5/references/v04-stability-compatibility.md)
- [内容运营最小操作说明](manage-article-knowledge-v0.5/references/operator-guide.md)
- [来源索引与复杂资料](manage-article-knowledge-v0.5/references/source-index-and-materials.md)
- [文章知识工作流](manage-article-knowledge-v0.5/references/article-knowledge-workflow.md)
- [Faithfulness结果交接规范](manage-article-knowledge-v0.5/references/faithfulness-result-contract.md)
- [月度审核与项目交接](manage-article-knowledge-v0.5/references/monthly-and-handoff.md)
- [逐步token记录脚本](manage-article-knowledge-v0.5/scripts/record_token_usage.py)
- [项目日常运行记录脚本](manage-article-knowledge-v0.5/scripts/record_project_run.py)
- [v0.5版本说明与更新记录](changelog/企业知识库Skill_v0.5版本说明与更新记录.md)

## 数据与隐私

仓库只保存Skill规则、模板、版本记录和辅助脚本，不应保存客户源文件、实际Obsidian知识库、文章数据、Faithfulness明细或Token。客户数据保留在授权路径中。MinerU仅按当前任务最小范围使用，Token不得写入项目、Skill、对话或运行账本。
