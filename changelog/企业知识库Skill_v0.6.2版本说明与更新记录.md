# 企业知识库 Skill v0.6.2 版本说明与更新记录

| 项目 | 说明 |
|---|---|
| 当前状态 | v0.6.2 原版回归结果保留；已修正文章包恢复的占位记录死循环，并明确既有Formal Claim按条件复用；本次Claim复用相关定向回归64项通过；安装 Junction 指向当前目录 |
| 版本基线 | 完整复制 v0.6.1；v0.6.1 保持为冻结版本 |
| 主要变化 | 按任务读取参考资料，合并重复覆盖复查、减少 15/20 重复叙述，为写作接入增加项目范围锁，补充不依赖钩子的批次续接基础模式，并避免对有效既有Claim重复回源 |
| 未列规则 | 本文未明确修改的 v0.6.1 规则全部继承 |

## 一、版本原则

| 原则 | 说明 |
|---|---|
| 版本隔离 | v0.6.2 在独立目录开发和回归，不覆盖 v0.6 或 v0.6.1，不直接改写客户项目 |
| 结论不变 | 保留来源边界、治理门禁和Faithfulness分母；新风险策略仅调整二次证据判断范围 |
| 按需读取 | 只在对应任务触发时加载初始化、接入、月度和交接操作细则；同一任务不重复读取同一参考 |
| 批次复用 | 同批来源读取和证据记录只建立一次，文章级文件引用共享记录 |

## 二、基线与继承证明

| 校验项 | 记录 |
|---|---|
| v0.6冻结位置 | `versions/manage-article-knowledge-v0.6/` |
| v0.6.1冻结位置 | `versions/manage-article-knowledge-v0.6.1/` |
| v0.6.2活动位置 | `manage-article-knowledge-v0.6.2/` |
| v0.6.2建立方式 | 完整复制 v0.6.1 后进行本记录列明的定点精简 |
| 项目兼容 | 项目版本仍以项目版本门禁和实际 Skill 合同为准；本次不迁移客户项目 |

## 三、明确保留

| 保留项 | 规则 |
|---|---|
| 批次知识准备 | 来源读取、候选事实、正式 Claim 和治理事项继续按批次合同统一处理 |
| 文章前审核 | 15 的来源与候选明细、20 的独立审核结论、30/35 映射和原有交付门禁继续保留 |
| Faithfulness审核 | 两轮独立主张清单、并集冻结和完整覆盖复查保留；`risk_weighted_v1`只对高风险主张做二次证据判断，标准风险主张保留一次主判断 |
| 证据与导入 | 证据正文、精确引文、来源追溯、三态映射和历史结果保护不变 |

## 四、本轮修改与新增

| 变更ID | 问题 | v0.6.2规则 | 主要落点 |
|---|---|---|---|
| SK-V062-001 | 日常文章运行会加载初始化、接入、月度和交接长流程 | 主 Skill 保留触发条件和必需门禁；详细模板按任务路由到参考文件，避免普通文章任务加载不相关细节 | `SKILL.md`、`references/project-integration-setup.md` |
| SK-V062-002 | 同一任务在多个阶段重复完整读取相同工作流和模板 | 按当前阶段读取所需章节；一次任务内复用已读取参考，批次内复用 source_reads 和候选事实 | `SKILL.md` |
| SK-V062-003 | 15 已保存证据与候选处置，20 又重复写入来源过程和原文 | 15 成为证据明细入口；20 保留规定的计数、审核结论、差异和指向15/治理事项的链接，不复制原文和过程说明 | `references/article-knowledge-workflow.md` |
| SK-V062-004 | Faithfulness 的盲审 coverage_review 后又要求另做一次独立覆盖扫描 | 盲审第二轮的完整 coverage_review 同时满足第二次覆盖复查；禁止额外第三遍全文扫描。两轮清单和分母并集保持；原始逐条双审要求已由后续 SK-V062-005 调整为风险分层 | `D:\deepeval-article-audit\SKILL.md`、审核方法文件 |
| SK-V062-005 | 风险分层审核结果对高风险主张保留复核行，对普通建议不生成逐条复核 | 导入器兼容 `risk_weighted_v1`，校验风险标签、复核深度和元数据；普通风险单审不要求复核行，高风险缺少实际复核时以 `review_status: missing` 占位并以 `unknown` 导入；历史 `two_pass_consensus` 规则不变 | `references/faithfulness-result-contract.md`、`scripts/import_faithfulness.py` |
| 后续说明 | v0.6.3（SK-V063-028）起，审核Skill v1.7.0 的新运行改用 `decisive_recheck_v1`，不再做风险分层；本版本的 `risk_weighted_v1` 结果仍可导入 | — | 见 v0.6.3 版本说明 |
| SK-V062-006 | 写作端可能跨项目搜索或读取其他客户知识库，造成项目身份、入口或事实附件混用 | 首次接入及已接入升级 Prompt 必须写入当前项目范围锁，绑定 `project_id`、唯一知识库根目录、当前项目资料根目录和已确认的任务/终稿入口；禁止扫描或读取其他客户知识库、项目配置及任务目录。仅可读取当前请求明确指定且项目身份相符的历史记录；身份、路径或回执不匹配时停止，不搜索替代项目 | `references/operator-guide.md`、`references/skill-integration-handoff.md` |
| SK-V062-007 | `terminal=false` 回执只能提示“下一步”，编排层可能在中间阶段直接结束；临时读取失败也可能让操作者只能看到错误码 | 保留按Codex会话绑定的Stop/Interrupt工作流守卫，作为可选结束拦截增强；实际效果仍取决于客户端加载、信任和验收，不视为跨平台基础保障 | `scripts/workflow_guard.py`、`scripts/install_workflow_guard.py`、`references/workflow-continuation.md` |
| SK-V062-008 | 仅靠Skill文字或结束钩子不能跨平台保存和恢复批次进度 | 增加不依赖会话身份/钩子的续接指针和只读状态核对；批次入口、写作桥接和审核导入登记真实进度，按当前项目与文章身份复核旧回执；明确能力检查、范围锁、实际执行`next_action`、单篇暂停、真实中断证据和人话诊断要求。进度指针不签发许可、不代替统一完成校验，也不唤醒已结束的Agent | `scripts/workflow_progress.py`、`scripts/run_knowledge_workflow.py`、`scripts/writing_bridge.py`、`scripts/import_faithfulness.py`、`references/workflow-continuation.md`、`references/operator-guide.md`、`references/skill-integration-handoff.md` |
| SK-V062-009 | 大纲逐项记录可能重复粘贴同一来源内容，且把后续来源层误解为必须新增Claim | 检索仅围绕已确认大纲问题；矩阵逐题保留六层结果、覆盖结论和CF引用，来源路径、原文及核验细节集中放在对应事实/正文记录中。同一网页正文区块被多题复用时只保留一条核验记录，并在记录与凭证中列出全部关联问题；保持既有来源顺序，后续层补充未答问题、适用范围或冲突，不要求每层都产生新Claim | `references/article-knowledge-workflow.md`、`references/project-structure-and-templates.md`、`references/batch-knowledge-workflow.md`、相关模板自测与恢复/交付检查 |
| SK-V062-010 | 证据尚未闭环时过早生成可交付资料包，或恢复时笼统重做全部检索 | 检索期间保存`15`及来源检查点；本篇证据闭环后由`20`复核，再生成`30/35`。恢复按回执修复具体缺项；已有来源凭证但Claim未闭环时继续处理候选，不退回整套检索 | `SKILL.md`、`references/article-knowledge-workflow.md`、`references/batch-knowledge-workflow.md`、`references/workflow-continuation.md` |
| SK-V062-011 | 恢复时可能重复人工计算，或把审核后新发现的公共知识缺口变成当前文章阻塞 | 仅按明确CF→Claim关系同步可确定的计数；映射缺失或歧义时不猜。审后新调研缺口进入既有维护待办，不作为当前文章完成条件，不自动改写或重审已完成文章 | `scripts/run_knowledge_workflow.py`、相关恢复与回归测试、`references/article-knowledge-workflow.md` |
| SK-V062-012 | 批次已有证据但文章级15/20缺失或仍是占位内容时，门禁早退只报30/35缺失；恢复器生成空壳15/20后，依赖这些记录的派生步骤无法推进，模型容易重复检查或重做检索 | 门禁一次报告15/20/30/35具体缺项；恢复器不再创建带“待补充/待核对”的语义占位文件。回执要求当前Agent按已确认大纲完成真实15逐题映射和20审核，先复用批次账本、source_reads及已核验Claim，仅对无答案、证据不完整或冲突的问题补查；记录完成后再派生30/35并签发许可 | `scripts/article_state.py`、`scripts/recover_article_package.py`、`scripts/run_knowledge_workflow.py`、`tests/test_run_knowledge_workflow.py`、`tests/test_workflow_resume_regressions.py`、`references/article-knowledge-workflow.md`、`references/batch-knowledge-workflow.md`、`references/workflow-continuation.md` |
| SK-V062-013 | 新文章和`outline_refresh`可能把既有Formal Claim也视为必须本轮回源的候选，并要求每个大纲问题都有本轮网页抓取凭证，造成重复检索 | 当前Claim状态可用、原始来源/证据链完整、适用范围覆盖且无“使用前复核”触发条件时，直接引用已保存的原文、译文、来源位置和最近核验日期；不伪造本轮读取凭证。仅新建或实质更新Claim，以及范围、状态、来源关系、时效或证据链触发明确复核时回源。同步修正总门禁、`15`记录和`outline_refresh`中的旧强制读取要求。批次账本增加既有Claim复用处置，并校验其状态、来源、精确位置、最近核验日期和引文；网页校验允许在无需本轮读取时记录Claim复用，不要求空造抓取记录 | `SKILL.md`、`references/article-knowledge-workflow.md`、`references/batch-knowledge-workflow.md`、`references/runtime-checklist.md`、`references/project-structure-and-templates.md`、`references/formal-claim-and-evidence-context.md`、`scripts/batch_knowledge_run.py`、`scripts/template_contract.py`、`tests/test_claim_reuse.py`及相关恢复/账本回归测试 |

## 五、回归范围

| 回归项 | 预期 |
|---|---|
| 普通文章任务 | 不加载仅用于初始化、首次接入、月度审核或交接的细节 |
| 同批多篇文章 | 同一来源只读取一次；文章级记录引用共享来源证据 |
| 大纲逐项记录 | 每个问题仍有独立覆盖结论；共用网页正文证据集中记录一次并关联多个问题 |
| 有效Formal Claim复用 | 有效Claim及其存储证据覆盖大纲问题时不重新读取原始来源；来源更新、范围变化、时效或显式复核条件命中时只复核受影响Claim |
| 15/20复核 | 20 仍保留必要计数和判断；来源原文、定位与处理过程可从15回溯 |
| 受管Faithfulness | 保留双轮独立清单、并集冻结、完整单位分类和覆盖复查，不增加第三轮全文扫描；高风险双审、标准风险单审 |
| 写作接入范围隔离 | 接入/升级 Prompt 与交接规则绑定当前项目身份和路径白名单；项目身份、路径或回执不匹配时停止，不跨客户搜索或自动改选知识库 |
| 跨平台基础接续 | 批次入口在无`CODEX_THREAD_ID`时仍保存续接指针；新进程可只读核对进度，完成回执须重新校验，版本改变时不复用旧动作；钩子缺失不阻止基础模式 |

## 六、验证结果与已知限制

| 项目 | 结果 |
|---|---|
| 文档和版本入口核验 | 通过；README、版本索引、归档目录和安装入口一致 |
| 原版本知识库全量回归 | 通过：174 项 unittest 全部通过；这是本轮续接兼容更新之前的基线结果，本次未重跑完整套件 |
| Faithfulness审核回归 | 通过：106 项运行，105 项通过；1 项可选 v0.5 导入兼容测试按默认配置跳过 |
| 风险策略兼容专项 | 新增导入器风险分层单/双审与缺失复核测试通过；旧 `two_pass_consensus` 导入测试通过；审核端两项风险策略交接断言通过 |
| 写作范围锁文档复核 | 通过：接入手册的写作接入 Prompt 与交接文件均包含项目身份/路径白名单及不匹配停止规则；本次未新增自动化回归测试 |
| 全量审核测试限制 | 标准测试夹具的临时目录写入被 Windows ACL 拒绝；直接运行风险策略交接断言通过，未将其记为全套审核回归 |
| 续接相关定向回归 | 通过：40 项 unittest 覆盖无会话身份建指针、新进程只读恢复、旧版本回执隔离、真实导入回执复核、单篇暂停与恢复、可选Hook以及批次入口/写作桥接恢复 |
| 本轮全量自动化回归 | 通过：完整测试目录运行 198 项 unittest，全部通过；覆盖批次证据闭环、来源复用、定向恢复和计数同步 |
| Claim复用与相关流程定向回归 | 通过：5组测试共64项全部通过，覆盖既有Claim复用不新增本轮来源读取、来源位置/核验日期校验、无需空造网页凭证、批次恢复、文章门禁、15/20计数和网页凭证；74个Python文件`py_compile`通过 |
| SK-V062-012恢复回归 | 通过：`tests.test_run_knowledge_workflow` 6项、`MissingSemanticRecordRecoveryTests` 2项全部通过；确认门禁同时报告15/20/30/35缺项、恢复器不创建语义占位文件、回执要求复用现有账本证据且不默认重做六层检索；5个修改文件`py_compile`通过 |
| 补充恢复/记录测试限制 | `test_preparation_record`共15项中7项通过、8项因Windows `WinError 5`无法创建/清理测试临时目录；`test_evidence_identity_recovery`的3个用例同样在临时项目创建阶段受ACL阻止，未到达断言。核心恢复修正测试已独立通过，未把受阻用例记为通过 |
| 本次全量回归尝试 | 未通过环境限制：完整测试共199项，其中多项在Windows临时目录清理阶段被ACL拒绝（`PermissionError: WinError 5`）；改用获准的`D:\01 测试项目`作为临时目录后仍有相同清理限制。本次恢复修正未重跑全量；对应的8项定向测试及修改文件语法检查通过，未把全量测试记为通过 |
| Skill 结构校验 | `quick_validate.py`未能运行：当前Python环境缺少`PyYAML`；本次未修改`SKILL.md` frontmatter |
| 安装入口 | 已更新：Codex 安装 Junction 指向 v0.6.2；Stop/Interrupt Hook 配置已合并到当前用户配置并保留原配置备份 |

本次兼容更新保持 `v0.6.2` 版本号；旧审核结果仍按原双审规则导入，新风险策略不放宽高风险、证据、治理或导入门禁。通用续接指针供后续Agent核对和恢复进度，不是唤醒器；只有实际具备并验证了平台调度能力，才能承诺会话间自动接续。Codex结束钩子仍是可选增强，WorkBuddy客户端尚未实测，本机脚本测试不代表跨平台验收通过。

