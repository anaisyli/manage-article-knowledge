# manage-article-knowledge

面向内容运营的企业文章知识库管理 Skill。当前活动版本是 `manage-article-knowledge v0.6`。

本 Skill 管理“文章需要什么知识、知识是否核验、写作使用了什么事实、文章完成后如何复核和治理”。它不写文章，不替代各组的 SEO/GEO 写作 Skill，也不自行完成 Faithfulness 语义判断。

## 一句话流程

```text
人工提出写作要求
→ 任意已接入的写作 Skill 保存本次写作需求并提交 writing_request
→ 知识库 Skill 检索来源、核验并沉淀正式 Claim
→ 知识库 Skill 完成 20_文章前知识审核
→ 知识库 Skill 成对生成 30_本篇知识库资料.md 和 35_写作素材来源索引.md
→ 返回 writing_ready 和当前 30 的绝对路径
→ 写作 Skill 只读取当前 30 并返回终稿绝对路径
→ 知识库 Skill 规范化终稿为 40_最终文章.md
→ 固定的 deepeval-article-audit 审核当前 40 + 30
→ 知识库 Skill 导入结果、更新 50 和治理记录
→ 任务进入 40_已完成并返回 article_completed
```

`writing_ready` 不是“找到几条资料”就可以发出。它要求检索、来源核验、合格正式 Claim、文章前审核、`30/35` 成对校验和项目门禁全部完成。

## 与任意写作 Skill 的交接

写作 Skill 只需进行一次接入改造，保留自己的选题、排重、SEO/GEO、文风、图片和交付流程。接入后每次运行都遵循同一条合同：

1. 保存本次写作需求记录；记录必须有任务唯一键、原始请求、项目、标题或主题和非空的已确认简要大纲。
2. 从当前已安装的知识库 Skill 读取 `references/handoff-contract.json`，按当前版本提交 `writing_request`。
3. 等待知识库返回同一兼容版本的 `writing_ready` 和当前 `30_本篇知识库资料.md` 绝对路径。
4. 只把当前 `30` 作为知识库事实附件，继续执行原有写作流程。
5. 返回终稿正文文件的绝对路径，形成 `writing_completed`。

写作 Skill 不创建或修改知识库项目内的 `10/15/20/30/35/40/50`、正式 Claim、来源台账、Faithfulness 结果或治理台账。知识库与写作 Skill 的详细字段、版本兼容和错误恢复规则只维护在：

- `manage-article-knowledge-v0.6/references/skill-integration-handoff.md`
- `manage-article-knowledge-v0.6/references/handoff-contract.json`

合同缺失、版本不兼容、任务身份不唯一或需求记录未保存时，必须停止并明确报错，不能猜测或降级运行。

## 知识库负责什么

### 文章前准备

- 读取并校验写作需求，建立唯一文章 ID 和文章版本。
- 按标题、主问题和简要大纲执行六层检索：已有正式 Claim、客户源资料、客户官网、已确认的企业相关网站、已有外部公共知识和必要的新外部调研。
- 对 PDF、扫描件、PPT、Office 图表和其他复杂资料实际提取并回到原件核对；未决 MAT、CUS 或 ANM 事项不得交付。
- 先回源核验，再沉淀正式 Claim；`20_文章前知识审核.md`审核已经完成的检索、Claim、缺口、复杂资料和异常处理。
- 只有 `20` 通过后才生成当前 `30/35`，并通过 Claim、文件、哈希和行映射门禁。

### 正式 Claim 归档

客户知识按七个模块归档：公司概述、产品介绍、解决方案、合作案例、企业提供行业知识、FAQ、其他。每条 Claim 都必须填写：

```text
归类模块
归类依据
```

归类依据说明这条事实主要回答什么对象；冲突的事实必须拆成多条 Claim。外部调研只能沉淀为去品牌化的外部公共知识，不能证明客户的产品、能力、案例、认证或承诺。正式知识文件按稳定中文实体或主题维护，不按文章标题、英文关键词、抓取批次或来源文件命名。

### 写后收尾

知识库接收终稿后只提取正文文字和表格，生成内部 `40_最终文章.md`，不复制文章配图。随后调用合同固定的 `deepeval-article-audit`，导入三个核心结果，更新 `50_文章知识使用与Faithfulness记录.md`、Claim 支撑、知识缺口和项目状态。只有导入成功并迁移到 `40_已完成` 后，才返回 `article_completed`。

## 人工需要确认什么

每个项目通常只需确认三个入口：

| 入口 | 用途 |
|---|---|
| 写作任务入口 | 读取外部写作需求和任务唯一键 |
| 写作终稿入口 | 查找写作 Skill 返回的正文终稿 |
| Faithfulness 结果根目录 | 保存各项目、文章和版本的审核结果 |

字段映射、文章 ID、版本目录、Claim 归类、结果子目录和运行状态由 Codex 根据当前项目样例和固定合同推断、校验并记录。只有无法唯一判断、需要客户事实或需要业务决定时才暂停请求人工处理。

## 项目目录中的关键文件

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

文章任务中的固定文件是：

| 文件 | 作用 |
|---|---|
| `10_文章知识需求.md` | 需求、身份、已确认简要大纲和来源入口 |
| `15_检索与知识准备记录.md` | 六层检索、候选事实、复杂资料和 MAT 记录 |
| `20_文章前知识审核.md` | 覆盖、Claim、缺口、复杂资料和 CUS/ANM 审核结论 |
| `30_本篇知识库资料.md` | 唯一交给写作 Skill 的事实附件 |
| `35_写作素材来源索引.md` | `30`证据正文到正式 Claim 的内部映射 |
| `40_最终文章.md` | 只含终稿文字和表格的知识库内部副本 |
| `50_文章知识使用与Faithfulness记录.md` | 写后结果、支撑关系和后续治理入口 |

## 常用机器入口

- `scripts/check_skill_update.py`：项目启动时检测当前 Skill 指纹变化。
- `scripts/check_integration.py`：校验三个项目接入入口。
- `scripts/writing_bridge.py`：任意写作 Skill 的 `prepare` 和 `finalize` 交接桥。
- `scripts/advance_ready_tasks.py`：通过交付门禁后将任务移入 `20_等待终稿`。
- `scripts/create_faithfulness_record.py`：创建 `50`、锁定 `40/30` 哈希并发出 `faithfulness_request`。
- `scripts/import_faithfulness.py`：导入审核结果、更新治理记录并完成状态迁移。
- `scripts/validate_v06_project.py`：校验项目结构、模板、Claim、映射、哈希和状态。

详细规则按需读取 `manage-article-knowledge-v0.6/references/` 下的 handoff、模板、来源、治理、版本和运行清单，不要在各写作 Skill 中复制第二套合同。

## 运行边界

- Skill 被调用或被外部自动化唤醒时才运行；自动化本身只负责唤醒，不承诺常驻监控。
- 客户原始资料、外部写作原件、配图和 Faithfulness 结果由各自入口保存，知识库不覆盖原件。
- 任何事实、来源、文章或控制文件的实质变化都遵循版本归档合同；失败时保留旧当前文件并报告阻塞原因。
- 本仓库只保存 Skill、参考文件、模板、脚本和更新记录，不保存客户项目或 Token。

## 入口文件

- [v0.6 Skill](manage-article-knowledge-v0.6/SKILL.md)
- [三方交接规范](manage-article-knowledge-v0.6/references/skill-integration-handoff.md)
- [机器交接合同](manage-article-knowledge-v0.6/references/handoff-contract.json)
- [内容运营操作手册](manage-article-knowledge-v0.6/references/operator-guide.md)
- [项目结构与模板](manage-article-knowledge-v0.6/references/project-structure-and-templates.md)
- [Faithfulness 结果交接规范](manage-article-knowledge-v0.6/references/faithfulness-result-contract.md)
- [版本与归档合同](manage-article-knowledge-v0.6/references/version-and-archive-contract.md)
- [v0.6 更新记录](changelog/企业知识库Skill_v0.6版本说明与更新记录.md)
