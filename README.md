# Manage Article Knowledge

面向内容运营团队的企业知识库管理 Codex Skill。它以文章需求为触发点，连接客户资料扫描、知识提取、文章前审核、写作输入生成、正式知识沉淀、知识使用记录和月度维护。

当前活动版本：**v0.2**

## 主要能力

- 根据项目基础信息自动建立知识库并扫描客户源文件；
- 为PDF、PPT、网页、音视频和表格建立可追溯的内容导航；
- 按单篇文章需求优先复用正式知识，再处理未提取资料和必要的外部调研；
- 生成带文件、页码、章节和网页直达链接的提取范围确认；
- 完成提取、翻译、结构整理和文章前知识审核；
- 生成可直接交给写文章Skill的`30_文章写作输入.md`；
- 在提交最终文章和引用率后，自动记录引用、知识块使用情况并沉淀可复用知识；
- 生成不打分的月度维护简报和项目负责人交接审核。

## 核心工作流

```text
建立项目并自动扫描
→ 提交文章关键词、标题、大纲和其他要求
→ 按清单补齐MinerU稿、转写稿或网页正文
→ 确认源文件提取范围
→ Codex自动提取、整理、调研和处理知识
→ 完成文章前知识审核
→ 上传30_文章写作输入.md进行写作
→ 提交最终文章和引用率
→ Codex自动完成引用、使用记录、知识沉淀和月度数据更新
```

正常流程只保留必要的人工确认，不设置浅扫描/深扫描选择、逐链接审批、派生处理审批或正式知识存放位置审批。

## 仓库结构

```text
manage-article-knowledge/
├── README.md
├── 企业知识库Skill_v0.2功能更新总结.md
├── manage-article-knowledge-v0.2/
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   └── scripts/
└── versions/
    └── manage-article-knowledge-v0.1/
```

- `manage-article-knowledge-v0.2/`：当前活动版本；
- `versions/manage-article-knowledge-v0.1/`：保留的历史版本；
- `企业知识库Skill_v0.2功能更新总结.md`：v0.2功能说明和维护记录。

## 使用入口

- Skill主入口：[SKILL.md](manage-article-knowledge-v0.2/SKILL.md)
- 内容运营操作手册：[operator-quick-manual.md](manage-article-knowledge-v0.2/references/operator-quick-manual.md)
- 文章工作流：[article-workflow.md](manage-article-knowledge-v0.2/references/article-workflow.md)
- 项目与知识结构：[project-and-knowledge-structure.md](manage-article-knowledge-v0.2/references/project-and-knowledge-structure.md)
- 任务与输出模板：[task-and-output-templates.md](manage-article-knowledge-v0.2/references/task-and-output-templates.md)
- v0.2功能更新总结：[企业知识库Skill_v0.2功能更新总结.md](企业知识库Skill_v0.2功能更新总结.md)

在Codex中使用时，让Codex读取当前活动版本的`SKILL.md`。内容运营需要了解实际操作步骤时，读取`references/operator-quick-manual.md`。

## 设计原则

- 客户源文件与客户官网并列作为可信的客户一手来源；
- 来源可信性和内容公开权限分开判断；
- 没有可识别文字的图片不登记、不导航、不提取；
- 本地客户资料优先，确认真实缺口后才进行外部调研；
- 正式知识按稳定业务对象或知识主题维护，不按文章或抓取批次建文件；
- 企业提供的行业知识与Codex外部调研知识分开保存；
- 已有知识被文章使用时只记录使用，不重复沉淀；
- 价格、库存、阶梯价等高频变化内容进入动态快照；
- 月度维护和负责人交接均不打分。

## 数据与隐私

本仓库只保存Skill规则、模板和辅助脚本，不应提交客户源文件、客户Obsidian知识库、文章生产数据、引用率明细或其他项目运行数据。

实际项目数据应保存在各自授权的项目路径中，并遵守客户的公开权限、保密要求和内部数据管理规定。

