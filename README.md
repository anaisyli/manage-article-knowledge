# Manage Article Knowledge

`manage-article-knowledge` 是一套面向内容运营团队的企业知识库管理 Codex Skill。它以文章任务为主要驱动力，把企业资料盘点、证据处理、知识沉淀、文章写作输入、终稿使用核对、异常处理和长期维护连接成一套可追溯流程。

当前活动开发版本：**v0.4**

## Skill解决什么问题

企业资料通常分散在文件夹、官网、PDF、Office文件、网页、图片和历史文章中。内容运营需要的不只是“把资料转成Markdown”，而是持续回答：

- 现有资料是什么、版本关系如何、哪些内容已经处理；
- 某篇文章可以安全使用哪些事实、参数、案例和行业知识；
- 每条知识来自哪里，适用范围和不可外推边界是什么；
- 新处理的内容应沉淀到哪里，如何避免重复和冲突；
- 最终文章实际使用了哪些知识，哪些问题仍需补充或复核；
- 知识库换人、迁移或长期运行时，如何保持结构和数据一致。

这个Skill把上述工作放在同一套Obsidian知识库、固定模板和自动校验规则中完成。

## 适用场景

- 新建企业知识库并扫描客户资料；
- 在已有知识库中处理一篇或一批文章任务；
- 整理PDF、PPT、Word、Excel、网页、图片、音视频或压缩资料；
- 将可复用内容沉淀为CLAIM级正式知识；
- 为写文章Skill生成本篇唯一知识库附件；
- 接收终稿并核对正式知识的实际使用；
- 管理源文异常、客户补充事项、困难资料待办和Skill反馈；
- 执行月度维护、负责人交接、版本迁移和一致性检查。

## 完整工作流

```text
建立或打开知识库
→ 扫描来源、版本和现有处理结果
→ 接收文章要求、关键词、标题和大纲
→ 优先复用正式知识并检查缺失资料
→ 确认本篇提取范围、代表样本和调研边界
→ 完成原文提取、清理、翻译、结构处理和候选CLAIM校验
→ 完成文章前知识审核并修正受影响CLAIM
→ 原子沉淀全部来源合格CLAIM；文章达到可写状态时同批生成唯一写作输入
→ 内容运营完成文章
→ 接收终稿和正式引用率
→ 核对实际使用的CLAIM并更新使用数据
→ 持续维护异常、版本、月度数据和交接记录
```

知识沉淀不等待终稿，也不以文章最终是否使用或文章是否已经达到可写状态为条件。资料处理阶段先准备候选CLAIM和沉淀事务；文章前知识审核完成并修正受影响CLAIM后，全部来源合格CLAIM正式沉淀。只有文章达到可写状态时，唯一写作输入才在同一提交阶段生成。两条输出分别校验，写作输入和最终文章都不能反向成为正式知识的事实来源。

## 主要能力

### 1. 来源盘点与资料导航

- 建立源文件总表、指纹、版本关系、父子附件关系和处理状态；
- 扫描Office容器中的嵌入对象、媒体、关系文件和外链；
- 区分主文件、完全重复副本、相似内容和疑似新旧版本；
- 为每份资料建立可回溯的内容导航，不移动或覆盖客户原件。

### 2. 原文提取与证据治理

- 处理PDF、PPT、Word、Excel、网页、图片、音视频和压缩资料；
- 自动调用已批准的解析工具，失败或质量不足时才请求人工补交指定材料；
- 保存逐字原文、页码、标题路径、表格、公式、单位、脚注和视觉证据；
- 对动态网页登记分页、标签、按钮、折叠、型号切换和其他交互状态；
- 原文证据不静默修正，提取错误、表面语言问题、规范化和事实风险分层记录。

### 3. 清理、翻译与派生材料

- 一份源文件维护一份当前源语言清理稿，旧稿进入处理记录或历史；
- 恢复自然段、标题层级、Markdown表格、公式和原始结构；
- 非英语来源另建英语忠实翻译稿，英语来源直接保留原文；
- 统一官方英文术语、产品名、品牌名和固定表达，同时保留型号、参数、数据、单位和认证名称；
- 复杂表格、图示和必要派生稿保留来源映射与独立核验状态。

### 4. 正式知识与CLAIM沉淀

- 正式知识按稳定业务实体或知识主题维护，不按文章或抓取批次建库；
- 每个CLAIM独立记录事实或规则、适用范围、不可外推、来源和精确位置；
- 同一知识只有一个主维护位置，相关模块使用链接引用；
- 局部异常只挂起受影响的CLAIM，合格内容继续流转；
- 沉淀事务使用门禁预检、暂存、原子写入和失败回滚，避免文件与状态不一致。

### 5. 文章前审核与写作输入

- 按文章大纲检查企业事实、参数、日期、型号、案例、公开权限和外部来源；
- 明确可以写、必须排除、需要补充和暂不能写的内容；
- 从证据层筛选完整语义块并按大纲重排，不压缩成知识点或无来源摘要；
- 不同来源分别成块，每个段落或连续知识块保留来源链接和精确位置；
- 生成单篇文章唯一的`30_文章写作输入.md`，作为写文章Skill的知识库附件。

### 6. 终稿核对与长期维护

- 将终稿主张映射到具体CLAIM，区分已确认使用、未使用、尚未核对和未追踪；
- 更新文章引用清单、知识块使用明细、累计次数和正式引用率数据；
- 管理待客户补充事项、源文与事实异常、困难资料待办和Skill运行反馈；
- 维护当前状态单一事实源、项目运行账本、月度简报和负责人交接审核；
- 打开已有知识库时核对Skill版本、指纹、控制结构和未关闭事项。

## 知识库分层

| 层级 | 作用 | 是否可作为事实来源 |
|---|---|---|
| 原始资料与官网 | 保存原始证据和版本现场 | 是 |
| Codex提取与运营提交 | 保存取得的逐字正文或结构 | 是，需核验 |
| 源语言清理稿与英语翻译稿 | 保真整理、翻译和复用 | 是，需对应核验状态 |
| 正式知识 | 登记已核验CLAIM、边界和逐块来源 | 是 |
| 文章写作输入 | 为单篇文章筛选并组织获准正文 | 否，不得反向证明正式知识 |
| 最终文章 | 核对实际使用和引用率 | 否，不得反向沉淀企业事实 |

## 人工与自动化边界

内容运营主要提供基础信息、文章要求、必要材料、范围确认和最终文章。AI知识库专员或维护负责人负责需要业务判断的决定。Codex主Agent负责流程调度和正式写入，资料处理Agent、调研Agent和审核Agent分别处理资料、外部调研和独立复核。

正常的扫描、提取、翻译、结构整理、候选登记、校验、沉淀、引用核对和数据更新由Codex完成。涉及范围批准、公开权限、客户事实、来源冲突、无法判断的语义或对外沟通时，才进入人工节点。

## 目录与版本

```text
manage-article-knowledge/
├── README.md                         # 整个Skill仓库总入口
├── manage-article-knowledge-v0.4/   # 当前活动开发版本
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   └── scripts/
├── versions/                        # 完整冻结历史版本
│   ├── manage-article-knowledge-v0.1/
│   ├── manage-article-knowledge-v0.2/
│   └── manage-article-knowledge-v0.3/
└── changelog/                       # 版本说明与记录索引
```

- 当前Skill入口：[v0.4 SKILL.md](manage-article-knowledge-v0.4/SKILL.md)
- 内容运营手册：[operator-quick-manual.md](manage-article-knowledge-v0.4/references/operator-quick-manual.md)
- 文章工作流：[article-workflow.md](manage-article-knowledge-v0.4/references/article-workflow.md)
- 项目与知识结构：[project-and-knowledge-structure.md](manage-article-knowledge-v0.4/references/project-and-knowledge-structure.md)
- 任务与输出模板：[task-and-output-templates.md](manage-article-knowledge-v0.4/references/task-and-output-templates.md)
- Skill内部运行清单：[runtime-execution-checklist.md](manage-article-knowledge-v0.4/references/runtime-execution-checklist.md)
- 版本记录索引：[版本记录索引.md](changelog/版本记录索引.md)
- 当前版本更新记录：[v0.4版本说明与更新记录](changelog/企业知识库Skill_v0.4版本说明与更新记录.md)

`versions/`中的历史版本保持冻结。每个新版本使用独立更新记录，不用新规则覆盖旧版本的设计说明。

## 校验与辅助脚本

- [validate_v04_project.py](manage-article-knowledge-v0.4/scripts/validate_v04_project.py)：检查目录、链接、状态、范围门禁、来源、语言、翻译、CLAIM、沉淀和数据一致性，并在自测中检查内部运行清单未失效；
- [run_mineru.py](manage-article-knowledge-v0.4/scripts/run_mineru.py)：调用MinerU并管理提取结果、失败回退和API生命周期；
- [inspect_office_container.py](manage-article-knowledge-v0.4/scripts/inspect_office_container.py)：只读检查Office容器内容；
- [record_project_run.py](manage-article-knowledge-v0.4/scripts/record_project_run.py)：写入项目唯一JSONL运行账本；
- [calculate_monthly_citation_kpi.py](manage-article-knowledge-v0.4/scripts/calculate_monthly_citation_kpi.py)：校验正式提供的文章引用率并计算月度均值。

校验器只负责可机器判断的结构和一致性，不代替人工事实审核、翻译质量审核、公开权限判断或网页状态穷尽判断。

## 数据与隐私

本仓库只保存Skill规则、模板、版本记录和辅助脚本，不应保存客户源文件、客户Obsidian知识库、文章生产数据、引用率明细或其他运行数据。实际业务数据应留在获授权的路径中，并遵守客户公开权限、保密和内部数据管理要求。
