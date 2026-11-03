---
name: manage-article-knowledge
description: 面向文章生产的轻量企业知识库管理Skill。用于初始化或接入既有Obsidian客户项目，把各组写作任务转换为可治理的文章知识任务，按需生成唯一写作事实附件，接收终稿，导入独立Faithfulness审核结果，记录Claim文章支撑，并执行月度审核与项目交接。不要用本Skill写文章、执行SEO/GEO评价或自行完成Faithfulness判断。
---

# 企业文章知识库管理 v0.6.4

本文件只保留每次运行都需要的边界、主流程命令和硬规则。各步骤的完整规则在[主流程细则](references/article-flow-details.md)（按`3.1`–`3.8`分节），其他场景的规则在对应参考文件中；进入该步骤或场景时才读，同一任务内已读的不重复加载。长参考只读当前需要的小节：用`scripts/reference_section.py <参考文件> <标题开头>…`打印指定小节，不整份读取，也不临时拼PowerShell/Python读取命令。

| 阶段 | 必读小节 |
|---|---|
| 收到`writing_request`、知识准备 | `runtime-checklist.md`的“文章任务”；`skill-integration-handoff.md`的“交接合同版本”“0.1”“0.2”“3.”；`article-flow-details.md`的“3.1”“3.2”“3.3”，做到对应步骤时再读“3.4”–“3.7” |
| 终稿接收 | `skill-integration-handoff.md`的“0.3”“5.”；`article-flow-details.md`的“3.8” |
| Faithfulness导入 | 只读[`faithfulness-import-card.md`](references/faithfulness-import-card.md)；导入器报错点名的规则卡片未覆盖时，才读`faithfulness-result-contract.md`对应小节 |
| 中断、换会话后续跑 | 先运行`workflow_progress.py status`，只按其`next_action`读取所需文件；不重读本文件或各参考来判断进度 |

## 省时规则

每次运行都适用，目的是少调用、少读：

- **不读脚本源码，不先读`--help`**：回执或报错的`next_action`给出完整命令就原样运行；报错点名了文件、行或字段就只改那里。同一报错按提示修改两次仍不变时，才读源码中报错所在的函数，并在SKFB登记“报错不自明”后继续。
- **不打开文件查状态**：进度看`workflow_progress.py status`和入口回执，不为确认进度打开`10/20/30/35/50`、批次账本、回执JSON或审核结果JSON。`run_knowledge_workflow.py`回执的`fill_todo`列出`20`里每个待填写单元格及其行号和对应的`10`原文，填写时按它改，不整份重读`10`和`20`。
- **校验只在阶段末尾跑一次**：改完一组记录再运行门禁或`validate_v06_project.py`，不每改一处跑一次；输入没变不重跑。`validate_v06_project.py`默认只打印比上次新增和已解决的问题（全部问题加`--all`）。
- **图片每张只看一次**：PDF页、渲染页和截图在同一任务内只查看一次，看完把结论写进记录；普通提取或MinerU文字已能唯一判断的不看图。
- **子Agent带上它要的东西**：只在规则要求独立审核时启动子Agent或分叉；任务说明直接写明它要读的参考小节、要读写的文件路径和“不必重读SKILL.md”，不让它自行加载整份Skill或参考。

## 〇、默认继续：能修就修，修完接着做

**本节先于其他所有规则。** 检查脚本、门禁或回执报出的问题，绝大多数是本Skill自己能修的待办，不是停下来问人的理由。遇到问题先对照下面两张清单：在“直接处理”里就处理后继续；不在“暂停”清单里的，同样修复后继续。

**直接处理，然后继续（不问人、不停下）：**

| 情况 | 怎么做 |
|---|---|
| 门禁或回执列出`15/20`的章节、表格、大纲行、检测类别、来源指针或格式错误 | 按报错只改被点名的业务记录，再原样运行回执`next_action`里的命令；PR-2任务还没有`20`时，入口会先写好骨架（见3.6），只填“待填写” |
| 缺`30/35`，或映射、行号、哈希、身份字段不一致 | 运行`run_knowledge_workflow.py`，恢复器从现有有效记录生成或重建 |
| `check_skill_update.py`报告版本变化 | 已自动同步版本入口，继续当前任务，不重做已完成的选题、Claim或记录 |
| 接入状态不是四个规定值之一（如被手改成“待重新确认”） | 运行`check_integration.py`，按已确认入口自动推出正确状态并继续 |
| `30`只差换行或文末空行 | 门禁和导入器自动恢复为写作许可绑定的原字节 |
| 旧Claim需要补齐登记或回源核验（含按当前规则重写：原文的we/our/this等须在指代解析中写明指谁） | 按`record_claim_reuse.py`给出的`claim_complete_draft`或`claim_next`处理后登记；本轮新沉淀的Claim直接改写其指代解析 |
| 回执`next_action`给出完整命令 | 原样运行，不另拼参数、不先读`--help` |
| 审核结果已交付（`faithfulness_completed`，或回执`stage=faithfulness_import`）但未导入 | 结果在50的“指定审核结果目录”，不在批次账本里；按导入速查卡生成unsupported摘要、逐条归组写处置JSON（需要时先登记缺口/CUS/ANM）并导入。unsupported再多也不是暂停理由；只有确需客户回答或业务决定的那几条写成CUS待问，其余照常导入；一轮判支持、审核自身留为未确认的（双轮分歧、复合主张）归`audit_unresolved`，不硬套其他类别 |
| 临时超时或连接失败 | 同一方法最多重试2次，再改用已获准的读取方法 |

**只有下列情况才暂停（完整清单）：**

1. 回执为`state=needs_human`或`handoff_error`，或处理单在等人回答；
2. 需要人做的业务决定，或只有客户能提供的事实（CUS），且本篇不能删减或中性改写绕开；
3. 权限、登录或外部访问在重试和替代方法后仍失败；
4. 缺少不可替代的材料；
5. 用户主动要求停止。

暂停只停受影响的文章：用`workflow_progress.py pause`写明原因、下一责任人和恢复条件，同批其他文章继续。不能把“报错很多”“没见过的状态”“版本不一致”“不确定格式”当作暂停理由；这些都是先修复的待办。

## 一、职责边界

- 只管理知识、证据和治理记录。不撰写或修改文章，不判断文章怎样写，不融合各运营组的写作指令、SEO/GEO规则、文风、质量评价或发布决定。`30`只是独立写作流程可选使用的知识附件。
- **一方证据同等权重**：客户原始文件、客户主官网、关系已确认的客户关联网站和客户明确确认具有同等证据权重；检索顺序不代表可信度。认证、交期、性能、规格、价格和其他数字在一方来源之间冲突时，并列保留来源、日期、适用范围和差异，进入ANM或人工核验；未解决前不得选一方写入正式Claim或`30/35`。
- **不是证据的东西**：提取文字、机器索引、AI摘要、翻译、未确认OCR和最终文章只能用于发现线索，永远不能成为事实来源。
- **竞品隔离**：项目级`竞品信息限制`默认禁止搜索、保存或沉淀具体竞品品牌、型号、特殊产品、参数、价格、案例、排名和比较结论，文章只能继承或收紧。偶然出现的竞品特定信息不得进入RES、Claim、`30/35`、覆盖页、月报或交接文件；只有不指向具体品牌/型号、能独立支持通用结论的连续原文才可去品牌化保留，否则只记“竞品特定信息，未采用”及类别。
- 普通任务由主Agent完成；只有高风险Claim、来源冲突或可能改变结论的复杂资料才启动独立审核Agent。
- **变更控制**：运行客户项目时只修改该项目自己的文件、机器数据和运行记录，不得修改Skill本体、references、scripts、agents配置或changelog。发现疑似Skill缺陷时，在项目SKFB查重登记后立即回到原步骤继续（查重读`manage_skill_feedback.py --project <项目> --audit`的列表输出，不整份读取SKFB台账），不得因此暂停或把登记当作终点；只有维护负责人或用户明确同意后才改Skill。完整规则见[知识库维护](references/knowledge-base-maintenance.md)。测试和演示只在临时项目目录进行，禁止向真实客户项目写入测试数据。

## 二、每次运行的前置动作

1. **版本门禁**：所有读写已接入项目的动作（新增文章、两种重写、终稿接收、Faithfulness导入、维护、月度审核、项目交接）都先运行`scripts/check_skill_update.py --project <Obsidian项目路径>`，早于读取任务、旧文章、旧大纲或知识附件。纯只读问答不触发。版本变化由脚本自动同步，同步后继续当前任务；项目缺版本入口时按报错用`initialize_project.py`补齐缺失文件（不覆盖已有文件）后继续，不得跳过或伪造同步。`writing_bridge.py prepare/finalize`内部已执行该检测，写作Skill不得绕过桥接直接读取项目文件。
2. **运行清单**：执行任何阶段前，读取[内部运行清单](references/runtime-checklist.md)中对应部分；它只用于后台防漏，不形成人工步骤。
3. **当前入口与归档**：修改当前文章、正式知识、来源版本记录、控制文件或机器数据前，按[当前版本与历史归档合同](references/version-and-archive-contract.md)执行“一个当前入口，替换前归档”：文章按完整任务快照归档，`30/35/40/50`不得拆开留历史；正式知识在事实或结构变化前归档；普通台账状态变化不制造快照；追加型JSONL和Faithfulness历史行不得覆盖。
4. **人工可读**：所有面向人工的入口、台账和处理单除ID外须写明中文人话说明、文件名称、可点击链接、当前状态、下一步责任人和重开条件；同一原因、责任人和关闭条件的对象合并为一个治理事项。完整规范见[人工可读控制项规范](references/human-readable-control-artifacts.md)。

## 三、文章知识准备主流程

一次提交就是一次完整的自动知识准备事务：每篇连续完成`10 → 检索与分流 → 必要的外部调研和Claim沉淀 → 20 → 30 → 35 → writing_ready`，不在步骤之间询问是否继续。每步的完整规则在`article-flow-details.md`的同号小节，做到该步时读。

| 步骤 | 命令与要点 | 细则 |
|---|---|---|
| 接收需求 | 收到`writing_request`前不读项目知识；收到后`writing_bridge.py prepare --handoff-contract-version <当前合同版本>`登记，必须有真实需求记录、任务唯一键和`大纲状态：已确认`的简要大纲，没有就只停在写作任务入口、不生成`10/15/20/30/35`。桥接失败时保持状态返回错误，不改脚本、不猜任务、不伪造`40` | 3.1 |
| 批次准备 | 唯一入口`run_knowledge_workflow.py --project <Obsidian项目路径> --batch-id <批次ID>`，不手拼`batch_knowledge_run.py`。读回执：`terminal=false`就按`next_action`做；文章`state=needs_human`暂停该篇；`beyond_knowledge_stage`不重跑准备，其`stage=faithfulness_import`立即导入。每篇证据完成即单独签发，不等整批；每个来源同批只读一次 | 3.2、3.3 |
| 检索与复用 | 顺序：正式Claim → 客户源资料索引 → 客户官网 → 已确认关联网站 → 已有外部Claim → 满足触发条件才做新外部调研。有效Claim用`record_claim_reuse.py`登记复用、不回源；补齐登记或回源核验按脚本输出的`claim_complete_draft`/`claim_next`本轮完成，不以“不可用”跳过。网页正文用`capture_website_evidence.py`（JS页面加`--browser-capture <JSON>`）登记EV；公共缺口用`record_knowledge_gap.py`登记`gap_key`。写作请求含“知识准备：加强”时按3.4加强深度 | 3.4 |
| Claim建立 | 只为本篇问题建立最小正式Claim，回源核验并带完整EC-1字段；中文原文另存经核验的英文严格翻译；客户`CLM-[项目]-[主题]-NNN`、外部`CLM-EXT-[项目]-[主题]-NNN` | 3.5 |
| 写20 | PR-2任务只写一个`20_文章前知识审核.md`：入口先写骨架，按回执`fill_todo`只填“待填写”的单元格，不增删章节和表格；机械字段（URL、原文、SHA、计数）写指针由脚本取。逐题分流到直接处理/MAT/ANM/CUS/`gap_key`；`20`通过前不生成可交付`30/35` | 3.6 |
| 30/35与许可 | `30`是唯一交给写作方的附件（六节，EC-1顺序，不含Claim ID、URL、位置和审核语言）；`35`是内部索引、不交给写作模型，二者成对重建。`issue_writing_ready.py --handoff-contract-version <当前合同版本> --project <Obsidian项目路径> --article-id <文章ID>`签发；读`writing_gate_result.json`的`terminal/workflow_state/next_action`，没有`writing_ready.json`不得开始正文 | 3.7 |
| 终稿与导入 | `writing_bridge.py finalize --handoff-contract-version <本次链路版本>`生成`40`，原样运行它输出的`next`命令创建`50`，并调用`deepeval-article-audit`；收到`faithfulness_completed`后按导入速查卡运行`import_faithfulness.py --task-dir <任务目录>`。本Skill不复核、不修改审核三态或分数，不手工修补审核JSON | 3.8 |

**人工升级**只在以下情况：来源冲突或重大事实异常；敏感信息能否公开；不可缺少的客户专属事实缺失；当前文章依赖的资料无法确定处理；核心问题的网站无法取得正文且不能删减或中性改写；复杂资料经MinerU和原件核对后仍不能唯一决定。顺序为内容运营 → 项目负责人 → 其指定的AI知识库专员；正常时只记录“自动通过”。

## 四、其他场景（触发时读取对应参考）

完整入口说明见`article-flow-details.md`的“四、其他场景详细入口”。

| 场景 | 入口与参考 |
|---|---|
| 新项目首轮信息收集、批量盘点建库 | `workspace-onboarding.md`：首轮只收集五项并等待用户回复`确认建库`，之前不得扫描资料、访问官网或写入项目 |
| 来源层、复杂资料、MAT、MinerU | `source-index-and-materials.md`；`build_source_index.py`、`search_source_index.py`；MinerU只在普通提取不可靠时调用，Token不得写入项目、Skill或对话 |
| 官网画像、地址变更、关联网站 | `website-profile-state.md`；`record_website_profile.py`、`manage_project_websites.py`，事务结束后`todo_sync.py` |
| 首次接入、入口变化或接入异常 | `project-integration-setup.md`、`skill-integration-handoff.md` |
| 整理或修复既有项目、SKFB | `knowledge-base-maintenance.md` |
| 登记或更新CUS/ANM/SKFB | `record_governance_item.py`（自动编号查重，不手工编辑台账）；SKFB阶段推进用`manage_skill_feedback.py` |
| 月度审核、项目交接 | `monthly-and-handoff.md`；`package_handoff.py`、`handoff_migration.py`；普通文章任务不加载 |
| 外部调研与缺口关联 | `external-research-contract.md`；`external_research_links.py` |
| 覆盖与缺口视图 | `build_coverage_view.py` |
| 三方事件合同、目录命名模板、内容运营手册 | `handoff_contract.py`；`naming-and-layout-contract.md`、`project-structure-and-templates.md`；`operator-guide.md` |

## 五、人工岗位

- 内容运营：提交文章要求和最终文章，决定业务范围、公开权限，以及是否禁止本篇新外部调研。
- AI知识库专员：只在项目负责人明确指定后，处理复杂资料、不确定版本和未解决知识风险。
- Skill维护负责人：处理通用Skill缺陷和SKFB关闭。
- Codex：执行索引、检索、Claim准备、台账更新、校验和报告；不把技术提取、压缩包检查、OCR、音视频处理或版本比较交给内容运营。

## 六、不可违反的规则

- 不根据文件名或语义相似度自动合并、删除或替换资料；只有SHA-256完全相同才判定为完全重复。
- 不自动转写音频或视频，只登记基础信息；当前文章依赖时转入MAT。
- 不用外部调研证明客户专属产能、规格、认证、案例、MOQ、价格或承诺。
- 不为普通检索、Claim提取、公开信息调研或正常文章前审核设置固定人工确认。
- MAT未决时不得从候选组任意文件建立Claim或写入`30`；命中MAT后同步来源台账、MAT详情、`15/20`和当前待办，不得只改一处。
- 客户明确禁止使用的正文不得进入索引正文、Claim或文章资料包，按`source-index-exclusions.json`登记排除。
- 不建立第二套任务队列；不批量改造各组既有写作项目，接入不得移动、重命名或覆盖写作方原文件。
- “自动”不等于按标题相似度、修改时间或目录顺序猜任务、终稿或审核结果；无法唯一归属时只暂停对应接口。
- 不承诺常驻监控：无人调用且没有外部调度器时Skill不会自行运行。
- 不直接覆盖已交付文章版本、会改变事实含义的正式知识或高影响控制文件；归档失败时保留当前文件并停止替换。
