# manage-article-knowledge

面向文章生产的轻量企业知识库管理 Skill，当前活动版本为 `manage-article-knowledge v0.6`。

本 Skill 负责把写作需求转换成可治理的知识任务：检索和核验来源、维护正式 Claim、生成本篇唯一知识附件、接收终稿、导入独立 Faithfulness 结果，并维护文章和项目治理状态。它不写文章，不执行 SEO/GEO 评价，也不自行完成 Faithfulness 判断。

## 先看手册

第一次使用、不清楚下一步怎么做，或需要人工操作提示时，先读：[内容运营操作手册](manage-article-knowledge-v0.6/references/operator-guide.md)。

手册是面向日常使用的入口；字段、状态、版本兼容和机器交接的硬规则以 [v0.6 Skill](manage-article-knowledge-v0.6/SKILL.md)、[三方交接规范](manage-article-knowledge-v0.6/references/skill-integration-handoff.md) 和 [机器交接合同](manage-article-knowledge-v0.6/references/handoff-contract.json) 为准。

## 最短用法

项目完成接入后，通常只需向已接入的写作 Skill 提出写作需求。写作 Skill 保存需求并提交 `writing_request`，知识库完成文章前准备后返回 `writing_ready` 和当前 `30_本篇知识库资料.md` 的绝对路径；写作完成后，知识库继续处理终稿和审核，直至返回 `article_completed`。

需要重做文章时，明确选择以下一种模式：

| 提示 | 处理方式 |
| --- | --- |
| 按原大纲重新整理知识并重写 | 重新检索、处理资料、复核 Claim，重建文章前文件后重写 |
| 知识不变，只按原大纲重写 | 校验并复用当前文章前文件，只重写并重新审核 |

没有明确选择时，先确认模式；不要人工填写 Claim、文章版本或脚本参数。

## 标准流程

```text
写作需求
→ writing_request
→ 15_检索与知识准备记录
→ 正式 Claim 与文章前审核
→ 20_文章前知识审核
→ 成对生成 30_本篇知识库资料.md / 35_写作素材来源索引.md
→ writing_ready
→ 写作 Skill 生成终稿
→ writing_completed
→ 规范化 40_最终文章.md
→ deepeval-article-audit
→ 导入 Faithfulness 结果并更新治理记录
→ article_completed
```

`writing_ready` 只有在检索、来源核验、正式 Claim、文章前审核、`30/35` 校验和项目门禁全部通过后才能发出。未决的资料处理、客户确认、异常或公共知识事项不能被跳过。

## 文章前工作

- 读取写作需求，确认项目、文章 ID、版本、标题或主题及非空简要大纲。
- 按标题、主问题和大纲执行分层检索：正式 Claim、客户源资料、客户官网、已确认的客户关联网站、已有外部公共知识，以及按门禁触发的外部调研。
- 对 PDF、扫描件、PPT、Office 图表和其他复杂资料实际提取，并回到原件核对；处理凭据写入 `15`，相关 CUS、MAT、ANM 或公共知识事项按现行合同留痕。
- 只把经过原件核验、范围清楚且状态可用的最小事实沉淀为正式 Claim。外部调研只能形成去品牌化的外部公共知识，不能证明客户专属事实。
- 文章前审核检查覆盖、Claim、缺口、复杂资料和项目状态；通过后才生成本篇附件。

## 写作附件与终稿

`30_本篇知识库资料.md` 是唯一交给写作 Skill 的知识事实附件；`35_写作素材来源索引.md` 保存 `30` 证据正文到正式 Claim 的内部映射。写作 Skill 不读取完整知识库，也不修改知识库内部文件。

知识库接收终稿后，提取正文文字、列表和表格，生成内部 `40_最终文章.md`。文章身份、关键词、TDK、图片清单和交付说明位于正文边界之外；Faithfulness 只审核 `ARTICLE_BODY_START` 与 `ARTICLE_BODY_END` 之间的正文。知识库随后接收审核结果，更新 `50_文章知识使用与Faithfulness记录.md`、Claim 支撑、缺口和任务状态，并把任务迁移到 `40_已完成`。

## 项目接入与目录

首次接入时可选择单个项目、指定项目或全部可识别项目。先扫描和确认路径，再初始化独立的 `[项目ID]_[企业中文名称]知识库_v0.6` 项目目录；扫描不会访问官网、复制原始资料或直接创建未授权项目。

每次开始既有 v0.6 项目时，后台先运行 `scripts/check_skill_update.py --project <项目根路径>`。项目接入配置确认写作任务入口、终稿入口和 Faithfulness 结果根目录；无法唯一判断或需要业务决定时才请求人工处理。

标准项目结构：

```text
01_工作台/
├── 10_项目基础信息.md
├── 20_当前待办.md
├── 30_版本与变更入口.md
└── 40_写作与Faithfulness接入配置.md
02_源资料/
03_正式知识/
04_文章任务/
└── 10_进行中 → 20_等待终稿 → 30_等待Faithfulness → 40_已完成
05_数据与审核/
```

文章任务的固定文件为：

| 文件 | 用途 |
| --- | --- |
| `10_文章知识需求.md` | 需求、身份、简要大纲和来源入口 |
| `15_检索与知识准备记录.md` | 检索、候选事实、复杂资料和处理记录 |
| `20_文章前知识审核.md` | 覆盖、Claim、缺口和交付门禁 |
| `30_本篇知识库资料.md` | 交给写作 Skill 的唯一事实附件 |
| `35_写作素材来源索引.md` | 证据正文到正式 Claim 的内部映射 |
| `40_最终文章.md` | 知识库内部终稿副本 |
| `50_文章知识使用与Faithfulness记录.md` | 写后支撑、审核和治理入口 |

## 常用机器入口

- `scripts/discover_workspace.py`：只读盘点待接入项目。
- `scripts/onboard_workspace.py`：按已确认范围批量初始化和接入项目。
- `scripts/writing_bridge.py`：写作 Skill 的 `prepare` / `finalize` 交接桥。
- `scripts/advance_ready_tasks.py`：通过门禁后移入等待终稿。
- `scripts/create_faithfulness_record.py`：创建 `50`、锁定 `40/30` 哈希并发出审核请求。
- `scripts/import_faithfulness.py`：导入结果、更新治理记录并迁移状态。
- `scripts/validate_v06_project.py`：校验项目结构、模板、Claim、映射、哈希和状态。

## 边界与维护

客户原始资料、外部终稿、配图和 Faithfulness 结果由各自入口保存，知识库不覆盖原件。项目运行时默认只修改项目自己的 Obsidian 文件、机器数据和运行记录；发现通用规则或工具问题时记录 Skill 反馈，不在客户任务中顺手修改 Skill 本体。修改本 Skill、references、scripts 或 agents 配置前，需获得维护负责人或用户明确授权，并同步更新更新记录和测试。

本仓库保存 Skill、参考文件、模板、脚本和更新记录，不保存客户项目或 Token。详细规则按需读取 `manage-article-knowledge-v0.6/references/` 下的运行清单、工作流、模板、交接、版本和治理文档。

## 入口文件

- [v0.6 Skill](manage-article-knowledge-v0.6/SKILL.md)
- [内容运营操作手册](manage-article-knowledge-v0.6/references/operator-guide.md)
- [文章知识工作流](manage-article-knowledge-v0.6/references/article-knowledge-workflow.md)
- [项目结构与模板](manage-article-knowledge-v0.6/references/project-structure-and-templates.md)
- [三方交接规范](manage-article-knowledge-v0.6/references/skill-integration-handoff.md)
- [机器交接合同](manage-article-knowledge-v0.6/references/handoff-contract.json)
- [Faithfulness 结果交接规范](manage-article-knowledge-v0.6/references/faithfulness-result-contract.md)
- [版本与归档合同](manage-article-knowledge-v0.6/references/version-and-archive-contract.md)
- [v0.6 更新记录](changelog/企业知识库Skill_v0.6版本说明与更新记录.md)
