# 企业知识库 Skill v0.6 版本说明与更新记录

| 项目 | 说明 |
|---|---|
| 当前状态 | 开发与回归中 |
| 版本基线 | v0.6以v0.5完整版本为直接基线 |
| 主要变化 | 在保留原有知识治理流程的基础上，增加与各组写作Skill、Faithfulness Skill的项目级接入能力 |
| 未列规则 | 本文未明确修改的v0.5规则全部继承 |

## 一、版本原则

| 原则 | 说明 |
|---|---|
| 版本基线 | v0.6由v0.5完整复制建立，不从空白重新设计，也不批量改造各组已有写作项目。 |
| 各组自主性 | 各组继续保留自己的建项方式、周任务格式、文章目录、SEO/GEO规则、文风要求和发布流程。 |
| 知识库职责 | 只负责项目身份、客户证据、文章知识准备、唯一`30`事实附件、Faithfulness结果导入、Claim支撑记录和月度治理。 |
| 写作与审核职责 | 写作Skill负责大纲、文章写作和终稿生成；Faithfulness Skill负责独立审核；知识库Skill不自行判断Faithfulness。 |
| 接入确认 | 分两阶段确认：先完成原有五项建库信息，再单独接入写作任务、终稿和Faithfulness三个接口。 |
| 自动匹配 | 必须依赖文章ID、文章版本、外部任务唯一键、已确认精确路径和文件SHA-256；不按标题相似度、最新修改时间或目录顺序猜测。 |
| 自动化边界 | 自动化只表示Skill被调用或被调度器唤醒后连续执行，不表示Skill是常驻后台目录监控服务。 |

## 二、基线与继承证明

| 校验项 | 记录 |
|---|---|
| v0.5冻结位置 | `versions/manage-article-knowledge-v0.5/` |
| v0.6活动位置 | `manage-article-knowledge-v0.6/` |
| Faithfulness审核Skill | `D:\deepeval-article-audit\` |
| v0.6更新日志 | `changelog/企业知识库Skill_v0.6版本说明与更新记录.md` |
| 建立日期 | 2026-08-31 |
| 本轮修复日期 | 2026-09-01 |
| 建立方式 | 完整复制v0.5后进行项目级接入和回归修复 |
| 继承范围 | 来源治理、Formal Claim、`10/15/20/30/35/40/50`、版本归档、四类异常台账、月度审核、项目交接和v0.4稳定性约束 |
| 迁移边界 | 不移动、重命名、覆盖或批量改造各组外部写作目录；每个知识库项目单独确认接入配置 |

| 继承说明 | 内容 |
|---|---|
| 继续有效的规则 | v0.5的来源证据、Claim生命周期、文章知识准备、版本归档、运行账本、月度维护、项目交接、MAT/CUS/ANM/SKFB和机器文件原子写入规则。 |
| v0.6新增范围 | 仅增加下文列出的接入边界和结果契约。 |

## 三、明确保留

| 保留项 | 规则 |
|---|---|
| 首次建库输入 | 新项目首次只收集项目名称、官网、客户原始资料路径、Obsidian项目路径、内容运营负责人。 |
| 建库前门禁 | 收到明确的`确认建库`前，不扫描客户资料、不访问官网、不读取旧库、不运行初始化、不修改项目文件。 |
| 证据权威性 | 客户原始文件仍是权威证据；索引、OCR、翻译、摘要和终稿不能反向证明事实。 |
| Claim时机 | 初始化只建立来源索引层，文章命中后才提取、核验和沉淀最小Formal Claim。 |
| 写作规则边界 | 写作Skill规则、SEO/GEO、文风、结构、图片和发布决定不进入知识库事实Claim或`30`。 |
| 写作附件 | 当前写作事实附件唯一使用`30_本篇知识库资料.md`；`35_写作素材来源索引.md`只供确定性映射，不交给写作Skill。 |
| Skill职责 | 知识库Skill不写文章、不执行SEO/GEO评价、不把Claim支撑记录描述成模型内部真实调用轨迹。 |
| Faithfulness输入 | 只审核写作实际使用的当前`40_最终文章.md`和当前`30_本篇知识库资料.md`，结果由外部Skill独立生成。 |
| 导入后更新 | 继续更新`50`、文章支撑记录、Claim支撑总表、unsupported归组、知识缺口、覆盖视图、月度数据和文章状态。 |
| 结果完整性 | 终稿或知识附件内容、文章ID、版本、SHA-256不匹配时，结果失效或拒绝导入，不静默修复。 |
| 治理边界 | CUS、MAT、ANM、SKFB、外部调研、竞品排除、敏感正文排除、版本归档和月度交接规则不因接入写作Skill而放宽。 |

## 四、本轮修改与新增

| 变更ID | 问题 | v0.6规则 | 主要落点 |
|---|---|---|---|
| SK-V06-001 | 各组已有不同写作项目和路径，无法统一硬编码 | 每个知识库项目单独维护一份写作与Faithfulness接入配置，不改造外部写作目录 | `SKILL.md`、项目结构、命名合同 |
| SK-V06-002 | 原五项建库信息与写作接线路径混在一起，容易重复建项 | 原五项先确认；初始化完成后再确认写作任务、终稿和Faithfulness三个接口 | 主Skill、操作手册、接入配置模板 |
| SK-V06-003 | 自动读取每周任务可能重复建文章 | 外部任务必须有稳定唯一键，使用受管CSV保存唯一键到文章ID的映射 | `record_writing_task.py`、`10_写作任务接入记录.csv` |
| SK-V06-004 | 各组任务字段不同 | 在项目配置中登记字段映射、可接收状态和原任务精确位置，不把某一组格式写成全局规则 | 接入配置、三方交接规范 |
| SK-V06-005 | 写作Skill不清楚怎样使用知识库资料 | 固定交付项目ID、文章ID、版本、`30`路径和终稿回传位置；写作Skill只把`30`当作事实附件 | `skill-integration-handoff.md`、操作手册、主Skill |
| SK-V06-006 | 终稿目录不统一，容易错配文章 | 依次使用文章ID/版本、外部任务映射或已确认精确Output path；禁止标题相似度和最新文件匹配 | 主Skill、交接规范、运行清单 |
| SK-V06-007 | Faithfulness Skill不清楚输入、输出和结果位置 | 只接收当前`40`和当前`30`；结果进入本篇文章版本专属目录，输出唯一prepared、judgments和summary | 三方交接规范、Faithfulness结果合同 |
| SK-V06-008 | 结果路径需要人工逐篇传递 | `create_faithfulness_record.py`读取项目接入配置，自动计算`[结果根目录]\\[文章ID]\\v[文章版本]` | `create_faithfulness_record.py`、`check_integration.py` |
| SK-V06-009 | 接入配置可能只有说明，没有执行门禁 | 初始化器创建配置；集成检查和项目校验器检查状态、绝对路径、字段映射和唯一映射 | `initialize_project.py`、`check_integration.py`、`validate_v06_project.py` |
| SK-V06-010 | “自动监测”容易被误解为常驻后台服务 | 明确Skill只在被调用或由外部调度器唤醒时运行；不虚构无人调用时持续监控 | 主Skill、交接规范、操作手册 |
| SK-V06-011 | 月度审核时间不明确 | 计划日期固定为每月最后一个周五；错过时下次启动补做，并记录实际日期和逾期原因 | 主Skill、月度合同、运行清单 |
| SK-V06-012 | 月报和交接看不到跨Skill积压 | 增加“任务未生成30、终稿未创建50、审核结果未导入”三类积压和三个接口健康检查 | 月度与交接模板 |
| SK-V06-013 | Faithfulness派生Claim总表失败时，CSV可能已经写入 | 导入前先把Claim总表写入临时`.preflight`文件并完成校验，成功后才提交CSV、`50`和状态迁移 | `import_faithfulness.py`、Faithfulness结果合同 |
| SK-V06-014 | 结果目录写成`vv1`或跨文章目录仍可能被接受 | 受管目录必须严格为`[结果根目录]\\[文章ID]\\v[文章版本]`，三个核心结果必须在同一目录 | `prepare_article_audit.py`、`render_article_audit.py`、`import_faithfulness.py` |
| SK-V06-015 | 文章移动到`40_已完成`后，旧审核路径无法复核 | 渲染器允许用移动后的当前`40/30`覆盖旧prepared中的路径别名，并重新校验内容和SHA-256；复核报告输出到新目录，原结果不改写 | `render_article_audit.py`、接入合同 |
| SK-V06-016 | 文章ID、版本和输入内容变化可能让旧结果误导入 | prepared必须保存并由导入器复核文章ID、文章版本、文章SHA-256、知识文件SHA-256、受管模式和当前输入文件 | `prepare_article_audit.py`、`import_faithfulness.py`、结果合同 |
| SK-V06-017 | 管理性一级标题会被误当成文章标题 | Faithfulness报告按`文章标题`、`最终标题`、一级标题、文件名的顺序取标题 | `import_faithfulness.py`、Faithfulness测试 |
| SK-V06-018 | 各组写作Skill未必维护统一的文章ID和版本 | 写作方提供时优先沿用；缺失时只要任务映射或终稿绝对路径能唯一确定归属，知识库按`[项目短码]-ART-[YYYYMMDD]-[三位流水]`生成文章ID、以`v1`开始并在实质修订时递增版本，再把完整身份写入内部`40`后交给Faithfulness；不得按标题、最新文件或目录顺序猜测 | 三方交接规范、主Skill、工作流、操作手册、命名合同 |
| SK-V06-019 | 人工原本只说“帮我写一篇”，后台步骤容易被各Skill当成手工指令 | 把自然语言写作请求定义为总入口：写作Skill先读交接规范并提交`writing_request`，等待知识库返回`writing_ready`和`30`，完成原有写作后返回`writing_completed`和终稿精确路径；知识库自动接收、补齐`40`并触发Faithfulness，正常路径不要求人工重复说“读取30/请审核/请导入” | `skill-integration-handoff.md`、`SKILL.md`、Faithfulness接入合同 |
| SK-V06-020 | handoff要求写作Skill跳转操作手册，单独读取handoff时规则不完整 | 将写作所需固定Prompt和`30`使用边界直接写入handoff；写作Skill只需读取handoff和当前`30`，不依赖`operator-guide.md`才能开始写作 | `skill-integration-handoff.md` |
| SK-V06-021 | 人工不知道怎样把现有写作Skill接入handoff | 在人工操作手册增加一次性接入SOP：人工把启动规则发给各组写作Skill，验证其先读handoff、等待30并返回终稿绝对路径；详细交接规则仍只维护在handoff | `operator-guide.md` |
| SK-V06-022 | 月度审核虽规定最后一个周五，但没有人工可照做的调度配置 | 在人工操作手册增加Codex周期自动化配置步骤、项目级提示词、测试运行和逾期补做检查；自动化只负责唤醒，审核内容仍由知识库Skill执行 | `operator-guide.md`、`monthly-and-handoff.md` |
| SK-V06-023 | 人工接入SOP把知识库Skill写成固定D盘绝对路径，不适用于不同电脑 | 改为先定位当前已安装的`manage-article-knowledge v0.6` Skill根目录，再用`references/skill-integration-handoff.md`相对路径读取；月度自动化提示词同样不绑定安装盘符 | `operator-guide.md` |
| SK-V06-024 | 第二阶段接线没有像首轮建库一样的固定提示格式 | 在主Skill中定义写作流程接入的Codex展示模板、确认分支和接入完成回执；人工手册只说明人工看到提示后的回复边界，不复制执行模板 | `SKILL.md`、`operator-guide.md` |
| SK-V06-025 | 第二阶段模板只写在人工手册，Skill本身不一定主动提醒客户 | 将第二阶段接入模板和主动展示、确认、写回配置、校验及状态分支写入主`SKILL.md`；项目结构文件明确该模板是Codex固定输出，人工手册作为解释和操作补充 | `SKILL.md`、`project-structure-and-templates.md`、`operator-guide.md` |
| SK-V06-026 | 人工手册重复放置Codex执行模板，容易让人工误以为要自行填写全部字段 | 删除手册中的2A/2B/2C和固定回执，仅保留“Codex主动提示、人工确认三个路径、按提示回复”的SOP说明；详细模板唯一维护在主`SKILL.md` | `operator-guide.md`、`SKILL.md` |
| SK-V06-027 | 人工操作手册信息完整但长段落密集，难以快速判断“什么时候看、自己做什么、Codex会做什么” | 保留原有十二个主题、固定Prompt、路径和规则；增加阅读导航与分工说明，按场景拆分小标题，并突出人工动作、Codex动作和关键边界，不改变流程含义 | `operator-guide.md` |
| SK-V06-028 | `50`先写入、任务迁移后失败会留下不可重试的半成品 | 迁移前先校验目标目录和当前待办；失败时不写入新结果或指标，重复调用可恢复 | `article_state.py`、`create_faithfulness_record.py`、`import_faithfulness.py` |
| SK-V06-029 | 外部写作终稿没有文章ID/版本/完成日期时，既有入口直接拒绝 | 新增窄桥接入口，按任务键或文章ID唯一定位任务，按知识库命名规则补齐内部`40`身份，外部原件保持不动 | `writing_bridge.py`、主Skill、交接规范 |
| SK-V06-030 | 接入配置只检查路径存在，空目录或错误字段也可能被标为已确认 | `已确认`时读取真实样例，探测唯一键、标题和状态；样例不满足则阻止确认并指出字段映射问题 | `check_integration.py`、项目模板 |
| SK-V06-031 | 一次性接入后，写作Skill可能把需求只留在对话中或写完后才补记，知识库无法稳定查重和恢复 | 一次性改造写作Skill时，必须建立可持久化的需求记录入口；每篇先保存核心身份和原始请求，再由AI按原有流程填入或标记其他需求字段，随后提交`writing_request`并传递记录路径和定位信息；日常不要求人工重复粘贴Prompt | `operator-guide.md`、`skill-integration-handoff.md` |
| SK-V06-032 | 同一交接概念在文档和配置中出现“写作任务路径、终稿路径、精确终稿路径”等多种叫法，人工和脚本容易误解 | 统一使用“写作任务入口/写作任务入口路径”“终稿入口/终稿入口路径”“本次写作需求记录”“终稿绝对路径”；`10_文章知识需求.md`保留为知识库内部文件名。接入校验读取新字段，同时兼容旧配置字段，不破坏既有项目 | `SKILL.md`、`operator-guide.md`、`skill-integration-handoff.md`、`naming-and-layout-contract.md`、`initialize_project.py`、`check_integration.py`、`article-knowledge-workflow.md` |
| SK-V06-033 | 不同写作Skill的选题确认顺序和终稿格式不同，统一交接提示可能跳过原有人工选题门，或无法接收DOCX终稿 | 明确`writing_request`应接在各组原有选题/排重确认之后；保留原流程。交接新增可选`final_package_path`，要求`final_path`指向文章正文文件；`writing_bridge.py finalize`增加DOCX正文提取，仍保持外部原件不变；Reviewer、审计器、Packager和发布器不接收写作交接规则 | `skill-integration-handoff.md`、`operator-guide.md`、`writing_bridge.py` |
| SK-V06-034 | 写作交付常含图片、DOCX或ZIP，若直接复制可能污染知识库任务目录并扩大Faithfulness输入 | 内部`40_最终文章.md`只保存终稿文字和表格；不复制图片。`final_path`必须是文章正文文件，交付包另用`final_package_path`；桥接器提取DOCX文字/表格并过滤Markdown/HTML图片引用 | `skill-integration-handoff.md`、`operator-guide.md`、`writing_bridge.py` |
| SK-V06-035 | 一次性接入改造完成时尚未必有具体项目路径，回执容易把“规则位置”误报成“实际文件位置” | 区分接入改造回执与实际写作回执：改造时报告预定规则或“未配置”；写作完成后才返回本次写作需求记录和终稿绝对路径 | `operator-guide.md` |
| SK-V06-036 | 接入配置中的最近状态需要人工手工维护，容易与运行事实脱节 | 新增接入配置状态自动更新器，维护最近检查、任务读取、终稿接收、Faithfulness导入、月度自动化、最近事件和最近异常 | `update_integration_status.py`、项目接入配置 |
| SK-V06-037 | 失败后接入配置仍显示正常，无法快速发现接口异常 | 写作任务、终稿桥接和Faithfulness入口的常见失败路径尽力回写失败事件并记录错误原因；失败时标记`异常，待重新确认`，原始错误仍正常返回 | `record_writing_task.py`、`writing_bridge.py`、`create_faithfulness_record.py`、`import_faithfulness.py` |
| SK-V06-038 | 自动摘要字段与入口说明字段重复，可能出现两份互相冲突的状态 | 初始化模板将动态时间和触发器集中到“自动状态摘要”，写作任务、终稿、Faithfulness和调度小节只保留引用 | `initialize_project.py`、接入配置模板 |
| SK-V06-039 | 月度自动化说明容易被误解为每个项目都要单独配置 | 操作手册统一为一条可覆盖知识库根目录的总控自动化；明确自动化只负责唤醒，项目审核由v0.6 Skill执行 | `operator-guide.md`、`runtime-checklist.md` |
| SK-V06-040 | 需求记录中的大纲有时未同步到`10`，导致`20/30`出现另一份大纲；Faithfulness完成后流程容易被误认为已经结束 | `writing_request`前必须在需求记录中保存非空简要大纲并标记`大纲状态：已确认`；大纲只需说明主题、主要问题或基本组织方向，不要求完整H1/H2/H3；`10/15/20/30/35`只使用该大纲。新增`faithfulness_completed`（中间交接）与`article_completed`（进入`40_已完成`后的最终事件）语义，知识库必须继续导入结果并完成收尾后才停止 | `skill-integration-handoff.md`、`article-knowledge-workflow.md`、`runtime-checklist.md`、`SKILL.md`、`writing_bridge.py` |
| SK-V06-041 | 一次性写作Skill接入Prompt对需求字段和大纲要求不够统一，人工难以判断记录是否完整 | 固定需求记录至少保存任务唯一键、项目、原始写作请求、当前状态、记录绝对路径与定位信息、标题或主题、产品或内容对象、选题方向、关键词、非空简要大纲、大纲状态、目标语言、限制和原始写作要求；大纲不要求完整H1/H2/H3 | `operator-guide.md`、`skill-integration-handoff.md` |
| SK-V06-042 | Faithfulness导入成功后任务虽已迁移到`40_已完成`，但命令行回执没有明确最终完成事件 | `import_faithfulness.py`在导入、治理更新和任务迁移成功后输出`handoff_event=article_completed`；`faithfulness_completed`仍只表示审核结果已生成的中间事件 | `import_faithfulness.py`、`skill-integration-handoff.md` |
| SK-V06-043 | 初始化接入配置模板仍把大纲写成可选字段，和新的写作任务门禁不一致 | 接入配置模板明确要求标题、非空简要大纲和大纲状态作为任务字段基础；其他需求字段继续由Codex从真实样例识别 | `initialize_project.py` |
| SK-V06-044 | 桥接脚本默认把大纲状态视为已确认，可能绕过写作Skill的确认门禁 | `writing_bridge.py prepare`必须显式接收`--outline-status 已确认`，否则拒绝提交`writing_request`；空大纲同样拒绝 | `writing_bridge.py` |
| SK-V06-045 | 实际任务中的`30/35`和大纲可能偏离固定模板，但原校验器只检查文件存在，无法阻止不完整资料进入交付状态 | 强化项目校验和迁移前门禁：交付前`10`必须有非空且已确认的大纲；`30`必须具备固定元数据、六节结构及表达/数据/组织/缺口表格或明确“无”；`35`必须具备固定元数据、真实Formal Claim和具体正式知识文件；修正Markdown表格和Obsidian相对链接解析；`advance_ready_tasks.py`不得把不完整`30/35`迁移为等待终稿 | `validate_v06_project.py`、`article_state.py`、`advance_ready_tasks.py`、`project-structure-and-templates.md` |
| SK-V06-046 | 三个Skill各自描述交接规则且没有统一合同版本，写作或审核端可能使用旧字段；知识库配置中的“独立Skill/外部流程”也可能让流程停在等待Faithfulness | 新增唯一机器合同`handoff-contract.json`，六个交接事件统一携带`MAK-HANDOFF-1.0`；知识库固定绑定`deepeval-article-audit`并发出`faithfulness_request`，Faithfulness运行时读取知识库唯一合同并返回同版本`faithfulness_completed`，知识库导入后才返回`article_completed`；缺少合同、版本不兼容或执行器不存在时硬失败且保留当前状态 | `handoff-contract.json`、`handoff_contract.py`、`skill-integration-handoff.md`、`writing_bridge.py`、`create_faithfulness_record.py`、`import_faithfulness.py`、Faithfulness受管脚本、操作手册、二组写作Skill |
| SK-V06-047 | 监测不到Faithfulness Skill时只返回`faithfulness_skill_not_found`等机器字段，内容运营不知道发生了什么、任务停在哪里以及下一步怎么做 | 未发现`deepeval-article-audit`时，除机器错误外必须在对话中给出中文人话说明：审核无法继续、任务保留在`30_等待Faithfulness`、当前没有审核结论，并明确要求安装Skill或提供目录；`handoff_error`合同新增必填`human_message`和`next_action`，提供目录后先校验其中`SKILL.md`名称再继续 | `SKILL.md`、`skill-integration-handoff.md`、`operator-guide.md`、`handoff-contract.json`、`handoff_contract.py`、`create_faithfulness_record.py` |
| SK-V06-048 | 旧任务产物只保留文件名或简版章节，容易绕过固定模板和证据边界 | 统一模板校验增加真实记录行、非空已确认大纲、20覆盖状态及CUS/ANM实际检查信号、30证据正文标记和35映射行；交付门禁复用同一完整模板校验，旧简版产物不能进入`20_等待终稿` | `template_contract.py`、`article_state.py`、`advance_ready_tasks.py` |
| SK-V06-049 | Faithfulness旧格式`## 正文`会把40的管理元数据当成文章单元，降低事实内容诊断并污染审核上下文 | 解析器兼容`## 正文`并从正文标题后开始；有管理元数据但无正文标题时跳过元数据和管理性一级标题；标准桥接终稿继续使用`## 最终正文` | `audit_common.py`、`prepare_article_audit.py`、Faithfulness测试 |
| SK-V06-050 | 外部判断可能把FAQ问题或其他句子的主张挂到当前文章引文 | 审核渲染器和知识库导入器都要求原子Claim与自身`article_quote`存在可解释的最小文字对应；无共享词语时必须提供具体`derivation_note`，否则拒绝渲染或导入；新增错配回归测试 | `render_article_audit.py`、`import_faithfulness.py`、`method.md`、Faithfulness测试 |
| SK-V06-051 | 桥接器生成的10文件缺少标准接入章节和随文文件表，无法与固定模板一致 | `writing_bridge.py prepare`现在生成完整`10_文章知识需求.md`字段、外部写作任务接入章节、大纲状态和随文提交文件分类表 | `writing_bridge.py` |
| SK-V06-052 | 少量泛化Claim可能被重复用于全部大纲，形式上有30/35但知识准备仍过窄 | 交付门禁要求20固定包含标题、主问题，并将10中的实际简要大纲逐项对应检查；30全部证据正文必须被35覆盖，20声明的可用Claim数必须等于35映射的唯一正式Claim数；项目总校验执行相同检查，不能用同一泛化事实替代互不相关的问题 | `template_contract.py`、`article_state.py`、`validate_v06_project.py`、文章模板、运行清单 |
| SK-V06-053 | 大量行业常识、选型和运营判断可能被笼统归为`package_omission`，导致50看不到真实知识缺口 | `package_omission`仅允许已有正式客户知识漏入30，必须声明customer_fact并指出已核对的正式知识；跨文章复用公共知识必须登记公共缺口，超大混合组必须拆分，否则拒绝导入和完成迁移 | `import_faithfulness.py`、Faithfulness结果合同、治理协议 |
| SK-V06-054 | Faithfulness分数已导入或任务已完成，但50仍可能保留“等待结果”占位表 | 已导入状态的50不得出现“等待结果”；导入器在迁移到`40_已完成`前重新执行完整50模板校验，未通过时保留等待状态并明确报错 | `template_contract.py`、`import_faithfulness.py` |
| SK-V06-055 | 原始资料和官网画像可能命中多组独立事实，但知识准备只沉淀少量泛化Claim，导致30过窄、Faithfulness事实支撑率偏低，且无法区分“未检索到”和“检索到但未沉淀” | 新增`15`大纲逐项检索与候选事实覆盖表，按标题、主问题及每个简要大纲项记录六层检索范围、精确来源入口、候选事实数、已沉淀Claim数和每项未采用原因；新增`20`知识准备充分性复核表并与`15`计数交叉校验；独立数字、认证、交期、MOQ、流程、案例和能力边界必须拆分核验；数量差异无理由或治理入口时禁止生成可交付`30/35`。不设置统一最低Claim数量，也不把官网访问失败误写成官网无相关资料 | `article-knowledge-workflow.md`、`runtime-checklist.md`、`project-structure-and-templates.md`、`template_contract.py`、`validate_v06_project.py`、`advance_ready_tasks.py` |
| SK-V06-056 | 仅依赖索引摘要、搜索片段或第一条命中，仍可能漏掉同一来源连续上下文中的MOQ、交期、打样、付款、认证、案例、流程和能力边界等事实 | 规定命中后必须回源读取连续上下文；采购决策相关显式事实必须主动检查并进入候选事实明细；未沉淀项必须写具体排除、治理或不进入本篇依据，不得静默归为行业常识 | `article-knowledge-workflow.md`、`runtime-checklist.md`、`SKILL.md` |
| SK-V06-057 | 官网访问失败时可能被误写成“官网没有相关内容”，也可能只返回机器错误而不告诉内容运营如何恢复 | 登录、验证码、权限、反爬、付费墙或内容读取受限时，必须在`15`和运行记录写明失败层级，并在对话中请求访问授权、登录态、白名单、导出文件或可访问镜像；请求解决前保持“无法访问/待重试”，只有正文检查完成后才可记“已检索未命中” | `article-knowledge-workflow.md`、`runtime-checklist.md`、`SKILL.md` |
| SK-V06-058 | `20_文章前知识审核`可能只有简短结论，来源台账标为“部分内容可搜索”的PDF/Office复杂内容未被实际处理，仍能生成`30/35`并造成知识附件过窄 | `15`新增“复杂资料处理与原件核对”固定表，记录实际处理范围、MinerU/提取稿入口、原件位置核对和治理结论；`20`新增逐项复核表。引用部分内容可搜索资料却无处理记录、或仍等待材料/工具/知识库专员判断时，模板、项目校验和交付状态均拒绝`writing_ready`；`20`不能用复核表替代资料处理 | `SKILL.md`、`article-knowledge-workflow.md`、`source-index-and-materials.md`、`runtime-checklist.md`、`project-structure-and-templates.md`、`template_contract.py`、`article_state.py`、`validate_v06_project.py` |
| SK-V06-059 | `20`前的六层检查、问题分流和正式Claim归档规则虽已分散存在，但容易被误读为“生成审核文件即可”，也不易判断客户资料、官网和内容运营提交网址是否真的核对过 | 明确`20`是已完成核验后的结论：每个知识问题必须先回读客户原件连续上下文、官网或已登记关联网站正文，再分流到自动处理、MAT、ANM、CUS或唯一公共知识缺口；无法安全缩小的权限/资料/事实问题必须在`20`以等待结论和处理单停止。新增正式Claim的来源分区、七个客户模块和外部公共知识归类表，并固定新增、更新、失效的回源、版本、运行账本与覆盖视图维护 | `SKILL.md`、`article-knowledge-workflow.md`、`runtime-checklist.md`、`project-structure-and-templates.md`、`template_contract.py` |
| SK-V06-060 | 旧流程把`20`置于`30/35`之前，却要求它填写当前`30`事实块和链接尚未生成的`30/35`，形成循环依赖，可能诱导提前生成资料包、填写虚假数量或未来文件链接 | 固定顺序为：`15`实际检索和分流 → 必要外部调研及正式Claim沉淀 → `20`审核本篇可用范围与计划素材 → `30/35`成对生成和映射校验 → `writing_ready`。`20`字段改为“计划纳入30的事实块数”，只说明审核通过后将生成的文件；任何阻塞结论均不得交付`30/35`或返回`writing_ready` | `SKILL.md`、`article-knowledge-workflow.md`、`skill-integration-handoff.md`、`runtime-checklist.md`、`project-structure-and-templates.md`、`human-readable-control-artifacts.md`、`template_contract.py`、`validate_v06_project.py`、`advance_ready_tasks.py` |
| SK-V06-061 | `writing_bridge.py prepare`此前只创建内部`10`和任务映射，机器合同没有强制外部任务唯一键，需求记录路径也可不存在；同一任务键的实质变化会静默复用旧`10`，造成“已接入”但实际任务身份或大纲已漂移 | 交接合同升级为`MAK-HANDOFF-1.1`，将`external_task_key`纳入`writing_request`必填项。桥接命令现在校验真实存在的需求记录文件、精确定位信息、非空唯一键、已确认简要大纲和完整需求字段；同键标题、基本大纲、限制或原始要求发生实质变化时拒绝静默复用，要求按文章版本合同重新提交。新增桥接正反向自测；初始化模板动态读取当前合同版本。已接入但仍发送`1.0`的写作Skill会明确报错，需要按运营手册的一次性升级Prompt更新后再交接 | `handoff-contract.json`、`handoff_contract.py`、`writing_bridge.py`、`advance_ready_tasks.py`、`initialize_project.py`、`skill-integration-handoff.md`、`operator-guide.md`、Faithfulness回归测试 |

## 五、文件与目录落点

### 1. v0.6 Skill新增或调整的通用文件

| 类型 | 路径/文件 |
|---|---|
| v0.6主Skill | `manage-article-knowledge-v0.6/SKILL.md` |
| v0.6交接规范 | `manage-article-knowledge-v0.6/references/skill-integration-handoff.md` |
| v0.6结果合同 | `manage-article-knowledge-v0.6/references/faithfulness-result-contract.md` |
| 接入检查脚本 | `manage-article-knowledge-v0.6/scripts/check_integration.py` |
| 写作任务登记脚本 | `manage-article-knowledge-v0.6/scripts/record_writing_task.py` |
| Faithfulness记录脚本 | `manage-article-knowledge-v0.6/scripts/create_faithfulness_record.py` |
| Faithfulness导入脚本 | `manage-article-knowledge-v0.6/scripts/import_faithfulness.py` |
| 项目校验脚本 | `manage-article-knowledge-v0.6/scripts/validate_v06_project.py` |
| Faithfulness审核Skill | `D:\deepeval-article-audit\`，包含主Skill、接入参考、审核准备/渲染脚本和测试 |

### 2. 每个知识库项目的接入文件

| 配置文件 | 登记内容 |
|---|---|
| `01_工作台/40_写作与Faithfulness接入配置.md` | 写作任务入口、字段映射、外部任务唯一键、可接收状态和原任务精确位置 |
| 同上 | 终稿入口、文章ID/版本回传规则、外部Output path和当前`40_最终文章.md`映射方式 |
| 同上 | Faithfulness结果根目录、文章ID目录、版本目录规则和三个核心结果文件名 |
| 同上 | 最近成功时间、当前状态、异常原因、下一步责任人和重新确认条件 |

### 3. 文章和审核结果的固定关系

| 对象 | 固定位置或规则 |
|---|---|
| 进行中文章 | `04_文章任务/10_进行中/[文章ID]_[标题]/` |
| 等待终稿 | `04_文章任务/20_等待终稿/[文章ID]_[标题]/` |
| 等待Faithfulness | `04_文章任务/30_等待Faithfulness/[文章ID]_[标题]/` |
| 已完成文章 | `04_文章任务/40_已完成/[文章ID]_[标题]/` |
| 本篇知识库资料 | 已完成文章目录内的`30_本篇知识库资料.md` |
| 写作素材来源索引 | 已完成文章目录内的`35_写作素材来源索引.md` |
| 最终文章 | 已完成文章目录内的`40_最终文章.md` |
| Faithfulness记录 | 已完成文章目录内的`50_文章知识使用与Faithfulness记录.md` |
| Faithfulness结果 | `[Faithfulness结果根目录]/[文章ID]/v[文章版本]/`，包含prepared、judgments和summary |

| 补充规则 | `35`用于把Faithfulness结果中的证据行确定性映射回Formal Claim，但不进入写作模型上下文；Faithfulness结果目录不复制知识库项目，也不把整个客户知识库或原始资料加入审核输入。 |

## 六、首次接入行为

### 既有项目

| 步骤 | 行为 |
|---|---|
| 1 | 先确认或补齐原五项知识库身份。 |
| 2 | 只读扫描用户明确指出的现有项目范围，分别寻找周任务、终稿和Faithfulness结果候选入口。 |
| 3 | 展示候选路径、字段、状态和判断依据。 |
| 4 | 只有无法唯一确定的身份、唯一键、字段或路径才需要人工确认。 |
| 5 | 保存配置后，按外部任务唯一键、文章ID、文章版本和结果目录自动运行。 |

| 既有项目身份缺失 | 第一次没有稳定文章ID、版本或外部任务映射时不能猜测；只暂停该文章或接口，确认后再恢复，不阻塞其他文章。 |

### 新项目

| 步骤 | 行为 |
|---|---|
| 1 | 按五项信息和`确认建库`完成知识库初始化。 |
| 2 | 写作流程尚未建立时，配置状态保持`待写作流程建立`。 |
| 3 | 第一份真实周任务或终稿规则出现后，再完成一次接口确认。 |
| 4 | 不因等待写作路径而阻止来源索引、知识库初始化或其他已具备条件的工作。 |

## 七、三方完整自动链路

| 阶段 | 主要输入 | 自动产物或动作 | 失败时行为 |
|---|---|---|---|
| 写作任务接入 | 周任务文件、字段映射、外部唯一键 | `10`文章需求、任务接入CSV、文章ID | 唯一键缺失或重复时只暂停该任务 |
| 知识准备 | 客户资料、官网、既有Claim、必要外部调研 | `15/20/30/35`及覆盖视图 | 资料冲突、MAT或工具失败时记录责任人和恢复条件 |
| 写作交接 | `30`、文章ID、版本、终稿回传规则 | 写作Skill终稿、知识库接收的`40` | 无法确定身份时不按标题猜测 |
| Faithfulness审核 | 当前`40`和当前`30` | 版本专属prepared、judgments、summary | 输入或目录哈希不匹配时拒绝生成或导入 |
| 结果导入 | 三个核心审核结果和当前项目状态 | `50`、Claim支撑、缺口治理、月度数据 | 预检失败不得写CSV、迁移文章或覆盖旧结果 |
| 完成收尾 | 已导入且兼容的结果 | 原子移动到`40_已完成`、更新待办和运行账本 | 移动失败保留等待状态并报告失败 |

## 八、Faithfulness输入、输出与复核规则

### 输入

| 项目 | 规则 |
|---|---|
| 读取文件 | 当前任务的`40_最终文章.md`和唯一的`30_本篇知识库资料.md`。 |
| 参数 | 必要的文章ID、文章版本和结果目录参数。 |
| 禁止输入 | 不得把`35`、完整知识库、原始客户资料、SEO/GEO说明或写作规则加入Faithfulness事实上下文。 |

### 输出

| 项目 | 规则 |
|---|---|
| 结果目录 | `[Faithfulness结果根目录]\\[文章ID]\\v[文章版本]\\`。 |
| 核心结果 | 目录内必须有当前文章版本对应的`prepared`、`judgments`和`faithfulness_summary.md`。 |
| 覆盖规则 | 已有当前版本结果时拒绝覆盖，要求输出到新结果目录或先按版本规则处理。 |

### 文章移动后的复核

| 情况 | 处理 |
|---|---|
| 文章移动后 | 原prepared可能保存移动前的绝对路径。 |
| 复核方式 | 传入移动后的当前`40`和`30`，渲染器按prepared中的文件顺序建立路径别名并重新校验内容和SHA-256。 |
| 结果保存 | 复核报告写入新目录，原审核结果不改写。 |

## 九、明确不替换、不合并的v0.5规则

| 不替换项 | 规则 |
|---|---|
| Skill边界 | 不合并各组写作Skill，不把某组项目目录写成所有项目的固定目录。 |
| 写作规则 | 不把周大纲、文风、SEO/GEO和发布规则复制进知识库Skill。 |
| 职责边界 | 不把知识库Skill改成写作Skill或Faithfulness评价Skill。 |
| 首次门禁 | 不取消原有五项首次建库门禁，不把路径登记与五项建库信息混成一次无边界扫描。 |
| 扫描范围 | 不扫描整个磁盘、用户下载目录或全部项目来猜测任务、终稿或结果。 |
| 匹配规则 | 不按标题相似度、最新文件或目录顺序自动匹配。 |
| Faithfulness上下文 | 不把`30`以外的资料包、`35`或完整知识库加入上下文。 |
| 自动化含义 | 不把“自动”解释为无人调用时持续监控；定时器只负责唤醒，治理门禁仍由Skill执行。 |
| unsupported处理 | 不因单篇unsupported自动判定文章错误、改写终稿或强制外部调研，仍按v0.5规则分类。 |
| 项目改造 | 不修改真实客户项目来“适配”Skill格式；差异只进入项目级接入配置或异常记录。 |

## 十、迁移与变更边界

| 边界 | 规则 |
|---|---|
| 版本冻结 | v0.5冻结后不回写v0.6接入规则；v0.5完整包保存在`versions/`中。 |
| 项目升级 | 保留当前文章、正式知识、台账和历史版本，只增加接入配置、任务映射、版本声明和必要回链。 |
| 接入异常 | 接入确认只做一次；路径失效、字段漂移、唯一键重复、文章身份冲突或结果不兼容时，只冻结受影响接口。 |
| 文件保护 | 接入配置、项目文件和外部写作目录分开管理，知识库Skill不覆盖或重命名写作方原文件。 |
| Skill修改授权 | 修改Skill本体、参考文件、脚本、Agent配置或版本日志前，必须有维护负责人或用户明确授权。 |
| 事实版本 | 文章正文、知识附件或正式知识的事实变化必须遵循v0.5版本归档合同，不能通过重新导入旧结果绕过版本门禁。 |

## 十一、验证记录

| 日期 | 检查 | 结果 |
|---|---|---|
| 2026-08-31 | v0.5完整复制、v0.6文件结构和主Skill引用检查 | 通过；v0.5冻结包保留在`versions/`，v0.6独立活动目录建立 |
| 2026-08-31 | `check_integration.py --self-test` | 通过；覆盖未建立写作流程的合法初始状态 |
| 2026-08-31 | `record_writing_task.py --self-test` | 通过；覆盖首次建立、同文章更新和同键冲突拒绝 |
| 2026-08-31 | `validate_v06_project.py --self-test` | 通过；覆盖v0.5项目结构与v0.6接口门禁 |
| 2026-08-31 | 新建临时v0.6项目、接入配置、空来源索引、覆盖视图和项目校验 | 通过；只保留预期的空资料和官网画像待执行警告 |
| 2026-08-31 | 从接入配置计算Faithfulness目录并创建`50` | 通过；得到`[结果根目录]/DEMO-ART-20260831-001/v1`并进入`30_等待Faithfulness` |
| 2026-09-01 | 隔离模拟项目端到端闭环 | 通过；配置接入→任务→`30`→终稿→Faithfulness→导入→`40_已完成`→月度统计，Faithfulness为`100.00%`，映射正式Claim数为`1` |
| 2026-09-01 | 结果目录、版本、文章ID和文章/知识文件SHA-256负向回归 | 通过；错误目录、跨文章结果、版本不匹配和覆盖已有summary均被拒绝 |
| 2026-09-01 | 文章移动到`40_已完成`后的Faithfulness复核 | 通过；用移动后的当前`40/30`生成新复核报告，原结果保持不变 |
| 2026-09-01 | Faithfulness审核Skill `unittest discover -s tests -v` | 通过；8项测试通过，1项既有v0.5外部导入测试因未配置外部路径按设计跳过 |
| 2026-09-01 | 知识库Skill集成和项目自测 | 通过；`check_integration.py --self-test`和`validate_v06_project.py --self-test`均通过 |
| 2026-09-01 | `git diff --check` | 通过；仅有Windows换行符提示，无空白错误 |
| 2026-09-01 | Skill Creator `quick_validate.py` | 未运行成功；当前Python环境缺少该校验器依赖的PyYAML。已另外核对frontmatter、文件命名、参考路由，并完成实际脚本和模拟项目回归 |
| 2026-09-03 | `validate_v06_project.py --self-test`及JERL-01/JERL-02只读回归 | 自测通过；JERL-01的`30/35`结构和真实正式知识链接通过新增包校验（仍保留2项既有接入配置错误）；JERL-02被拦截，报告大纲/固定元数据/表格结构/Claim与正式知识文件缺失或无效 |
| 2026-09-04 | 模板/迁移/接入自测、Faithfulness单元测试及JERL-03只读负向回归 | 知识库5组自测通过；Faithfulness 11项通过、1项需外部v0.5路径而跳过；JERL-03旧简版产物被新版校验器拦截，项目文件未修改；旧宽泛`package_omission`处置被新版导入器拒绝 |
| 2026-09-04 | `SK-V06-062` 正式Claim模块归类门禁 | 新增逐Claim的“归类模块/归类依据”记录和七模块决策顺序；校验器核验记录、固定目录与Claim命名空间一致。旧Claim先提示升级警告，不自动改写项目；新建或更新Claim必须补齐。 |
| 2026-09-04 | `SK-V06-063` 写作桥接入口项目版本检测 | `writing_bridge.py prepare/finalize`现在先执行当前实际运行Skill的指纹检测；检测到Skill版本或文件指纹更新时同步`01_工作台/30_版本与变更入口.md`和Skill反馈台账，缺少版本入口则明确停止。版本入口仍只在Skill指纹变化时更新，文章运行事件继续写入运行记录和接入配置状态。 |
| 2026-09-04 | `SK-V06-064` MinerU初始化路径改为安装位置发现 | 运营手册不再写固定盘符；配置人员定位当前已安装的`manage-article-knowledge v0.6` Skill根目录后运行其`scripts/initialize_mineru.cmd`，适用于不同电脑和安装位置。 |

## 十二、已知限制

| 限制 | 说明 |
|---|---|
| 格式差异 | 不同组的周任务格式、终稿目录和状态命名仍需逐项目登记字段映射，本版本不提供假设格式相同的通用解析器。 |
| 身份缺失 | 既有项目没有稳定文章ID、版本或外部任务唯一键时，首次仍需人工确认身份。 |
| 运行条件 | 文件夹检查、周任务接入和月度审核都需要Skill被调用或由外部调度器唤醒。 |
| 月度调度 | 每月最后一个周五的唤醒需要在实际环境配置Codex自动化或团队批准的系统调度器。 |
| Faithfulness含义 | 结果只表示当前文章事实对当前`30`附件的支持情况，不等于文章质量、SEO/GEO得分、可发布性或事实绝对正确。 |
| 路径判断 | 路径存在不等于内容已经正确处理；月度和交接审核仍需核对接口状态、哈希、结果兼容性和积压。 |
| 校验依赖 | 官方快速校验依赖PyYAML；本轮缺少该依赖，因此以脚本自测、单元测试、项目校验和隔离模拟闭环作为验证依据。 |
