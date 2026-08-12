# Manage Article Knowledge

面向内容运营团队的企业知识库管理 Codex Skill。它连接客户资料扫描、证据处理、CLAIM级知识沉淀、文章写作输入、实际使用核对、异常与客户事项处理、月度维护和Skill运行反馈。知识可以由文章任务触发整理，但是否沉淀不再取决于文章最终是否使用。

当前活动版本：**v0.3**

## 主要能力

- 根据项目基础信息自动建立知识库并扫描客户源文件；
- 为PDF、PPT、Office嵌入附件、网页、图片、音视频和表格建立可追溯的内容导航；
- 按单篇文章需求优先复用正式知识，再处理未提取资料和必要的外部调研；
- 生成带文件、页码、章节、网站覆盖和代表处理样本的提取范围确认；
- 由主Agent调度调研Agent、资料处理Agent和独立审核Agent；
- 完成提取、翻译、源文质量分类、结构整理和文章前知识审核；
- 将资料拆分为可独立核验的CLAIM，核验合格后自动沉淀；局部异常只挂起受影响的CLAIM；
- 从直接证据重建写作输入，保留完整来源语义、适用条件、链接、表格、公式和单位，不压缩成无来源摘要；
- 在提交最终文章和引用率后，逐个核对文章实际使用的CLAIM并更新引用、使用明细和月度数据；
- 用通俗说明与可回看原文证据管理源文异常、事实风险和待客户补充事项；
- 处理CSV编码、非Markdown机器文件入口、证据附件回链和Obsidian控制语法安全显示；
- 维护项目当前状态的单一事实源，避免当前待办与版本入口形成两套矛盾状态；
- 允许人工随时提出或Codex自动记录Skill运行反馈，并交由AI知识库专员判断是否纳入维护；
- 打开已有项目时自动核对版本与指纹、迁移新增控制结构，并逐条回归未关闭Skill反馈；
- 由AI知识库专员自动复现和修复通用Skill问题，不把维护工作交给内容运营；
- 生成不打分的月度维护简报和项目负责人交接审核，并用项目校验器检查结构、状态与互链一致性。

## 核心工作流

### 知识沉淀轨

```text
建立项目并自动扫描
→ 提交文章关键词、标题、大纲和其他要求
→ Codex列出必须提交的PDF/PPT Markdown稿和指定网页Web Clipper稿
→ 确认提取范围、网站覆盖和代表处理样本
→ 资料处理Agent批量处理，调研Agent按真实缺口保存外部原文证据
→ 按CLAIM分块并保存直接证据、范围和不可外推条件
→ 审核Agent独立查漏查错
→ 合格CLAIM自动进入正式知识，异常CLAIM单独挂起
```

### 文章使用轨

```text
按大纲检索正式知识和已核验证据
→ 从证据层筛选并重排完整语义块
→ 审核30_文章写作输入.md的来源、限定条件、表格、公式和单位
→ 交给写文章Skill
→ 提交最终文章和正式引用率
→ 逐个核对实际使用的CLAIM
→ 更新引用清单、使用明细和月度数据
```

文章使用与知识沉淀相互关联但不互为前提：文章未使用的合格CLAIM仍可沉淀，终稿中新出现但没有证据的内容也不会反向变成企业知识。

正常流程只保留必要的人工确认，不设置浅扫描/深扫描选择、逐链接审批、派生处理审批或正式知识存放位置审批。

## 异常、客户事项与Skill反馈

- 源文质量固定区分提取错误、英文源文表面问题、确定性规范化、语义或事实风险和来源冲突。客户英文原文保持不变；只有可确定、不改变原意的修正，才可生成带映射和审核记录的`source-normalized-english`派生稿。
- 参数、单位、公式、法规摘录或不同来源存在实质疑点时不猜测。异常记录先用通俗语言说明“发生了什么、现在怎么处理”，再保留可点击原文现场、精确位置、逐字原文或原始结构、审核结论和重开条件。
- 异常结束时区分“已解决”和“已完成处置（原文未修复）”。后者表示风险已被安全隔离，并不表示原资料已经改对；收到新材料后只重跑受影响范围。
- 待客户补充事项由知识库专员先判断是否确有必要询问客户，再由主Agent生成对客话术，交给优化师发送；状态使用一条阶段线，不在多个台账重复维护不同编号。
- Skill运行问题使用独立`SKFB`记录：人工可以随时提出并标记为`人工提出`；Codex也可以依据对话、文件矛盾或校验遗漏随时记录并标记为`Codex自动发现`，无需人工确认。自动记录不等于Bug已经确认；AI知识库专员会自动复现，确认属于通用问题后在授权维护源中修复并回归，但不会未经授权修改其他副本或向外发送反馈。

## 自动校验与数据治理

`manage-article-knowledge-v0.3/scripts/validate_v03_project.py`用于检查可机器判断的结构和一致性，包括：

- 项目目录、链接、状态迁移、CLAIM结构与知识落位；
- 候选分流、沉淀事件、文章使用明细和累计次数；
- 客户事项、源文与事实异常、Skill反馈的阶段、证据与关联入口；
- `20_当前待办.md`作为当前状态唯一正文，与版本入口、文章闭环、月度维护和交接记录保持一致；
- 项目登记指纹与实际运行Skill一致；发布或安装检查可同时比较维护源和运行副本；
- 受管CSV使用UTF-8 with BOM，非Markdown机器文件有Markdown数据说明入口，证据附件有回链；
- 逐字原文中的`%%`等Obsidian或Markdown控制语法使用`text`围栏安全承载，避免后续内容变灰或隐藏；
- 孤立文件、脚本、缓存和临时文件不进入受管知识库。

自动校验只检查结构、状态和一致性，不代替资料处理Agent与审核Agent的事实判断。

## 仓库结构

```text
manage-article-knowledge/
├── README.md
├── 企业知识库Skill_v0.2版本说明与更新记录.md
├── 企业知识库Skill_v0.3版本说明与更新记录.md
├── manage-article-knowledge-v0.3/
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   └── scripts/
└── versions/
    ├── manage-article-knowledge-v0.1/
    └── manage-article-knowledge-v0.2/
```

- `manage-article-knowledge-v0.3/`：当前活动版本；
- `versions/manage-article-knowledge-v0.2/`：固定保留的上一版本；
- `versions/manage-article-knowledge-v0.1/`：保留的历史版本；
- `企业知识库Skill_v0.2版本说明与更新记录.md`：固定保留的v0.2版本定位、功能说明和历史变更；
- `企业知识库Skill_v0.3版本说明与更新记录.md`：当前v0.3版本原则、允许修改项、实际改动和校验记录。

## 使用入口

- Skill主入口：[SKILL.md](manage-article-knowledge-v0.3/SKILL.md)
- 内容运营操作手册：[operator-quick-manual.md](manage-article-knowledge-v0.3/references/operator-quick-manual.md)
- 文章工作流：[article-workflow.md](manage-article-knowledge-v0.3/references/article-workflow.md)
- 项目与知识结构：[project-and-knowledge-structure.md](manage-article-knowledge-v0.3/references/project-and-knowledge-structure.md)
- 任务与输出模板：[task-and-output-templates.md](manage-article-knowledge-v0.3/references/task-and-output-templates.md)
- 多Agent分工：[multi-agent-orchestration.md](manage-article-knowledge-v0.3/references/multi-agent-orchestration.md)
- 源文件处理规则：[source-processing-rules.md](manage-article-knowledge-v0.3/references/source-processing-rules.md)
- 逐字证据与写作输入保真：[verbatim-evidence-rules.md](manage-article-knowledge-v0.3/references/verbatim-evidence-rules.md)
- Obsidian与数据治理：[obsidian-governance-details.md](manage-article-knowledge-v0.3/references/obsidian-governance-details.md)
- 知识沉淀规则：[knowledge-research-and-deposition.md](manage-article-knowledge-v0.3/references/knowledge-research-and-deposition.md)
- 月度维护与交接：[readiness-and-maintenance.md](manage-article-knowledge-v0.3/references/readiness-and-maintenance.md)
- 版本迁移与Skill自动维护：[version-migration-and-skill-maintenance.md](manage-article-knowledge-v0.3/references/version-migration-and-skill-maintenance.md)
- 项目校验器：[validate_v03_project.py](manage-article-knowledge-v0.3/scripts/validate_v03_project.py)
- v0.3版本说明与更新记录：[企业知识库Skill_v0.3版本说明与更新记录.md](企业知识库Skill_v0.3版本说明与更新记录.md)
- v0.2版本说明与更新记录：[企业知识库Skill_v0.2版本说明与更新记录.md](企业知识库Skill_v0.2版本说明与更新记录.md)

在Codex中使用时，让Codex读取当前活动版本的`SKILL.md`。内容运营需要了解实际操作步骤时，读取`references/operator-quick-manual.md`。

## 设计原则

- 客户源文件与客户官网并列作为可信的客户一手来源；
- 来源可信性和内容公开权限分开判断；
- 纯装饰图不进知识正文；附件图标、关键截图和复杂图示必须登记检查；
- 本地客户资料优先，确认真实缺口后才进行外部调研；
- 外部调研分别保留网页/文章原文证据与Codex整理稿；
- 正式知识按稳定业务对象或知识主题维护，不按文章或抓取批次建文件；
- 企业提供的行业知识与Codex外部调研知识分开保存；
- 正式知识按可独立核验的CLAIM沉淀；文章是否使用不影响沉淀资格；
- 已沉淀CLAIM再次被文章使用时只更新使用关系，不复制知识；
- 原文、规范化派生稿、事实判断和对外表达分层保存，不静默改写客户证据；
- 局部问题局部挂起，合格知识继续流转；任何安全处置都不等于原文已被修复；
- 价格、库存、阶梯价等高频变化内容进入动态快照；
- 项目当前状态只在一个正文入口维护，版本记录、反馈和专项台账通过链接关联；
- 新版应用到已有项目时先迁移控制结构并回归未关闭反馈，不用版本号变化代替项目验证；
- 月度维护和负责人交接均不打分，自动校验不替代人工事实审核。

## 数据与隐私

本仓库只保存Skill规则、模板和辅助脚本，不应提交客户源文件、客户Obsidian知识库、文章生产数据、引用率明细或其他项目运行数据。

实际项目数据应保存在各自授权的项目路径中，并遵守客户的公开权限、保密要求和内部数据管理规定。
