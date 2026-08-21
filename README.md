# 企业文章知识库管理 Skill

`manage-article-knowledge` 是一套面向内容运营的企业文章知识库管理 Skill。它负责把客户原始材料、企业网站、正式 Claim、单篇写作素材、外部 Faithfulness 结果和长期治理记录连接成一条可追溯的证据链。

当前活动开发版本：`v0.5`（开发与回归中，仅用于新项目）。冻结的 `v0.4` 及更早版本保留在 `versions/`，不会被新规则覆盖。

## v0.5 的核心变化

v0.5 从“初始化时全量整理全部材料”改为“先建立可搜索来源层，文章命中后再按需核验”：

```text
只读扫描客户材料并建立来源台账与 SQLite 索引
→ 接收文章标题、关键词、大纲、目标语言和限制
→ 按六层顺序检索已有 Claim、客户材料和网站等证据
→ 仅对真实的公共知识缺口开展新外部调研
→ 回到原始证据，提取或复用本篇需要的最小 Formal Claim
→ 后台完成文章前知识审核
→ 成对生成 30_本篇知识库资料.md 与 35_写作素材来源索引.md
→ 接收 40_最终文章.md，并创建等待审核的 50 记录
→ 导入独立审核 Skill 的 Faithfulness 结果
→ 更新 Claim 文章支撑、覆盖视图、月度审核和负责人交接
```

常规索引、检索、格式整理和台账更新由主 Agent 完成。只有高风险 Claim、来源冲突，或可能改变结论的复杂资料，才需要独立审核 Agent。

## 职责边界

本 Skill 管理知识、证据和治理记录，不负责：

- 撰写或修改文章；
- 执行 SEO/GEO、文风、发布或文章整体质量评价；
- 把最终文章反向当作事实来源；
- 在 Skill 内部自行计算 Faithfulness；
- 自动转写音频、视频，或把技术提取工作交给内容运营。

各运营组继续使用自己的写作流程。`30_本篇知识库资料.md`只是写作流程可选使用的事实附件，不替代文章要求，也不要求文章每句话都逐句引用知识库。

## 主要能力

### 1. 建立可搜索来源层

- 只读登记客户文件的身份、路径、SHA-256、版本、使用范围和可检索状态；
- 使用 `source-index.sqlite` 建立机器搜索索引，不在初始化阶段批量生成清稿、翻译、摘要或正式知识；
- SHA-256 完全相同才自动判定完全重复，疑似版本只生成复核候选；
- 支持 PDF、Office、图片、扫描页、网页、压缩包及复杂视觉证据的追溯；
- MinerU 仅在本地提取无法满足当前文章时按需调用；Token 不写入项目或运行记录；
- 明确禁止读取正文的材料写入 `source-index-exclusions.json`，仅保留文件身份，不进入正文索引。

音视频只登记基础信息；当前文章确实依赖时，统一进入 MAT，由 AI 知识库专员决定处理方式。

### 2. 管理企业网站与官网画像

- 官网已知时，初始化或刷新会读取首页、About/Company、产品或服务目录、Contact/Locations 和可用站点地图；
- 自动回写官网能够证明的英文名、行业/业务类别、主要业务、产品、语言和市场信息，并保留页面 URL、日期、原文依据和判断方式；
- 内容运营提交的子品牌站、集团站、区域站、平台店铺或企业主页单独登记，不混入 Codex 外部调研；
- 网站暂时不可访问时记录失败层级和重试条件，恢复后更新当前状态，不把临时失败写成永久不存在。

### 3. 按文章需求提取最小 Formal Claim

文章需求提交后，正常路径会自动连续完成 `10 → 15 → 20 → 30 → 35`，不会要求内容运营反复确认“继续”。只有真实人工决定、访问或工具失败、缺少不可替代材料时才暂停。

检索顺序固定为：

1. 已有正式 Claim；
2. 客户源资料索引；
3. 客户官网；
4. 内容运营提交且企业关系已确认的其他相关网站；
5. 已有外部调研 Claim；
6. 满足触发条件时的新外部调研。

命中材料后才回到原始证据，建立本篇实际需要的最小 Claim。每条 Claim 保留稳定 ID、正文、适用范围、来源类型、链接、精确位置、最小原文证据、日期或版本、使用边界和状态。

### 4. 分离写作素材与内部追溯

每篇文章固定生成两个职责不同、必须成对维护的文件：

| 文件 | 用途 | 是否交给写作模型 |
|---|---|---|
| `30_本篇知识库资料.md` | 六节式“本篇写作素材包”；提供已核验事实、表达、数据、使用建议和简短生成边界 | 是，且是标准 v0.5 唯一事实附件 |
| `35_写作素材来源索引.md` | 保存 `30` 的 SHA-256，以及“证据正文”行范围到 Formal Claim 和原始来源的确定性映射 | 否，仅供内部追溯和结果导入 |

`30` 第 1 至第 3 节的可核验事实或数据必须配套连续的“证据正文（供 Faithfulness 核验）”。`30` 不显示 Claim ID、来源 URL、精确位置或详细审核推理；`35` 也不作为写作输入或 Faithfulness 的 retrieval context。

随文章提交的事实文件必须先进入来源层、Formal Claim 和当前 `30/35`；写作要求、SEO/GEO、风格和结构参考只登记在文章需求中，不进入事实证据链。

### 5. 接收并导入独立 Faithfulness 结果

本 Skill 不执行 Faithfulness 语义评价。收到终稿后，它会：

1. 创建 `50_文章知识使用与Faithfulness记录.md`；
2. 锁定当前终稿和事实附件的 SHA-256；
3. 将文章从 `20_等待终稿`迁移到 `30_等待Faithfulness`；
4. 接收 `deepeval-article-audit` 的 prepared JSON、judgments JSON 和 `faithfulness_summary.md`；
5. 校验文章、知识文件、版本、哈希、证据边界和结果契约；
6. 导入成功后更新 Claim 文章支撑，并迁移到 `40_已完成`。

终稿或事实附件发生变化时，旧结果立即失效，必须重新审核。Faithfulness 只表示“实际交付的事实附件对终稿事实主张的支持比例”，不是 SEO/GEO 总分、可发布性结论或 100% 合规门槛。单篇普通未覆盖项只记录；同一主题跨文章或跨周期反复出现时，才进入月度重复缺口观察。

### 6. 持续治理、覆盖视图与交接

- `CUS`：待客户确认；
- `MAT`：复杂源资料处理；
- `ANM`：事实异常；
- `SKFB`：通用 Skill 反馈。

所有人工入口除 ID 外，还必须给出人话说明、对象名称、链接或稳定路径、状态、下一责任人和重开条件。同一处理原因、责任人和关闭条件的对象归为一个事项，不按文件机械拆成重复待办。

`build_coverage_view.py` 会重建当前知识覆盖与缺口视图，汇总来源、正式知识、未处理材料、明确缺口和真实文章影响，不再维护重复的逐 Claim 沉淀台账。月度审核分别呈现客户文件、客户主官网、内容运营提交的其他企业相关网站，并按七个知识模块说明当前覆盖；项目交接则单独检查入口、环境、未完成任务和责任是否清楚。

## 与审核 Skill 的衔接

两个 Skill 的职责严格分开：

```text
manage-article-knowledge
  生成当前 30/35，并接收终稿
        ↓
deepeval-article-audit
  只用 40 作为文章、30 作为唯一事实上下文完成独立评审
        ↓
manage-article-knowledge
  校验并导入 prepared + judgments + summary，更新 50 与项目治理数据
```

审核时不要把 `35`、Formal Claim、整个项目知识库或原始随文事实文件追加为并列知识文件，否则会改变真实写作上下文并虚高结果。

## 在 Codex 中使用

初始化新项目时可以直接说明：

```text
使用 $manage-article-knowledge v0.5。
客户原始资料路径是：D:\客户资料
Obsidian 项目路径是：D:\企业知识库
项目名称、官网、运营组和负责人如下：……
请初始化可搜索来源层并完成官网画像，不修改客户原文件。
```

处理文章时可以提供：

```text
使用 $manage-article-knowledge 处理这篇文章需求。
标题：……
关键词：……
大纲：……
目标语言：……
特殊限制：……
```

可选字段缺失时，Skill 会继续完成仍可完成的检索，不会把普通候选文件、页码范围或调研链接交给内容运营审批。

## 目录与文档

```text
manage-article-knowledge/
├── README.md
├── manage-article-knowledge-v0.5/   # 当前活动版本
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   └── scripts/
├── versions/                        # 冻结历史版本 v0.1–v0.4
└── changelog/
```

常用入口：

- [v0.5 Skill](manage-article-knowledge-v0.5/SKILL.md)
- [内容运营操作手册](manage-article-knowledge-v0.5/references/operator-guide.md)
- [文章知识工作流](manage-article-knowledge-v0.5/references/article-knowledge-workflow.md)
- [来源索引与复杂资料](manage-article-knowledge-v0.5/references/source-index-and-materials.md)
- [项目结构与模板](manage-article-knowledge-v0.5/references/project-structure-and-templates.md)
- [目录、命名与模板合同](manage-article-knowledge-v0.5/references/naming-and-layout-contract.md)
- [Faithfulness 结果交接规范](manage-article-knowledge-v0.5/references/faithfulness-result-contract.md)
- [当前版本与历史归档合同](manage-article-knowledge-v0.5/references/version-and-archive-contract.md)
- [月度审核与项目交接](manage-article-knowledge-v0.5/references/monthly-and-handoff.md)
- [v0.4 稳定性兼容清单](manage-article-knowledge-v0.5/references/v04-stability-compatibility.md)
- [v0.5 版本说明与更新记录](changelog/企业知识库Skill_v0.5版本说明与更新记录.md)

关键脚本包括项目初始化、来源索引与搜索、官网/项目运行记录、文章状态迁移、版本归档、覆盖视图重建、Faithfulness 等待记录与导入、月度均值、SKFB 状态事务和项目校验。脚本的具体参数与执行时机以 `SKILL.md` 和对应 reference 为准。

## 数据、隐私与版本安全

仓库只保存 Skill 规则、模板、版本记录和辅助脚本，不应保存客户源文件、实际 Obsidian 知识库、文章数据、Faithfulness 明细或 Token。客户数据只保留在用户授权路径中。

Skill 本体是受保护的通用资产。运行客户项目时默认只修改项目文件；发现通用问题先登记 SKFB，只有维护负责人或用户明确授权后才修改 Skill 并执行专项自测和项目回归。

当前文章、正式知识或高影响控制文件在实质替换前必须归档。文章按完整任务快照保存，`30/35/40/50` 不拆开留历史；归档失败时停止替换并保留当前文件。
