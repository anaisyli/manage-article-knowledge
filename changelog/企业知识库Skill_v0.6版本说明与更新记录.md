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
| 项目目录兼容 | 新建项目使用`[项目ID]_[企业中文名称]知识库`；既有`_v0.6`目录原地兼容。Skill版本由项目内部版本入口、结构和schema判断，不因升级重命名项目目录。 |

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
| SK-V06-062 | 正式Claim虽然已有七模块目录，但单条Claim可能只按文件名归档，没有可检查的事实归类依据 | 新增逐Claim的“归类模块/归类依据”记录和七模块决策顺序；校验器核验记录、固定目录与Claim命名空间一致。旧Claim先提示升级警告，不自动改写项目；新建或更新Claim必须补齐 | `SKILL.md`、`project-structure-and-templates.md`、`validate_v06_project.py` |
| SK-V06-063 | 从写作Skill进入项目时可能跳过Skill版本检测，版本入口长期不更新 | `writing_bridge.py prepare/finalize`先执行当前实际运行Skill的指纹检测；检测到变化时同步`01_工作台/30_版本与变更入口.md`和Skill反馈台账，缺少版本入口则停止。文章运行事件仍写运行记录和接入配置状态，不混入版本流水 | `writing_bridge.py`、`check_skill_update.py`、项目版本入口 |
| SK-V06-064 | MinerU初始化说明写死某台电脑的盘符和安装位置 | 运营手册改为先定位当前已安装Skill根目录，再运行其相对路径下的初始化脚本，不假定盘符 | `operator-guide.md`、`initialize_mineru.cmd` |
| SK-V06-065 | “重做”既可能要求重新整理知识，也可能只要求文章重写；旧流程没有强制区分，容易继续复用少量旧Claim或覆盖当前任务 | 合同新增`knowledge_refresh_and_rewrite`与`article_rewrite_only`。两种模式都完整归档旧任务、保留文章ID并递增版本；前者重新检索、逐条复核和归类旧Claim并重建`15/20/30/35`，后者只在完整校验当前知识文件后复用。运营手册提供两句短提示词，人工不填写脚本参数 | `README.md`、`handoff-contract.json`、`handoff_contract.py`、`writing_bridge.py`、`template_contract.py`、`version-and-archive-contract.md`、`operator-guide.md` |
| SK-V06-066 | 旧的一次性接入Prompt过长，可能让写作Skill复制知识库内部规则或压缩原有写作、图片、表格、DOCX与QA流程 | 接入和升级Prompt改为最小适配器：保存需求和简要大纲、提交`writing_request`、等待并读取当前`30`、完整执行原流程、返回终稿并交回控制权。明确禁止桥接失败后用临时脚本替代原写作Skill | `operator-guide.md`、`skill-integration-handoff.md`、`SKILL.md` |
| SK-V06-067 | 外部终稿的Article ID、版本、关键词、TDK和交付说明可能被包进`40`正文并进入Faithfulness文章单元 | `40`固定使用唯一正文开始/结束标记；桥接器清除H1附近管理字段、图片和已知尾部管理章节，只把正文文字、列表和表格放入边界；受管审核器只读取边界内内容，边界缺失、重复或倒置时拒绝审核 | `README.md`、`writing_bridge.py`、`template_contract.py`、`project-structure-and-templates.md`、`faithfulness-result-contract.md`、Faithfulness v1.3 |
| SK-V06-068 | 当前Codex可能在`writing_completed`或`faithfulness_completed`后停止，或找不到审核Skill时只输出机器字段 | 合同固定非终止事件与唯一成功终点`article_completed`；知识库检测已安装`deepeval-article-audit`后立即调用并导入，未检测到时保留`30_等待Faithfulness`并显示中文原因和安装/指定目录下一步；中断恢复按当前状态继续 | `handoff-contract.json`、`create_faithfulness_record.py`、`skill-integration-handoff.md`、`runtime-checklist.md`、`SKILL.md` |
| SK-V06-069 | 重做字段虽然出现在文档模板中，但基础模板校验未全部强制；直接机器交接可漏掉基线文章身份；知识不变重写只检查文件模板，仍可能复用与正式Claim断开的`30/35`，且自测曾用mock绕过真实校验 | 将任务模式、基线版本、旧版归档入口、旧Claim复核和重做复核纳入固定模板合同；非新文章`writing_request`强制提供基线文章ID和合法`vN`；知识不变重写锁定影响知识范围的需求字段，并同时校验模板、正式Claim存在性、证据正文行、35映射和SHA-256。重写桥接自测改用真实合法知识包连续验证文章重写v2和知识重整v3，不再mock模板校验；Faithfulness Skill缺失分支只输出一个`handoff_error`事件 | `template_contract.py`、`handoff_contract.py`、`article_state.py`、`writing_bridge.py`、`create_faithfulness_record.py`、`advance_ready_tasks.py`、`operator-guide.md` |
| SK-V06-070 | 已接入写作Skill的升级Prompt按某次合同变化写死步骤，后续更新仍要重写Prompt；月度自动化创建Prompt重复复制Skill内全部审核规则且没有要求明确运行时刻 | 运营手册改为可反复使用的合同驱动“适配器同步Prompt”：运行时读取当前安装Skill的唯一合同，只保留写作方职责和项目入口，不复制版本、字段或终止事件；首次接入和后续升级使用同一段。月度总控Prompt缩为知识库根路径、明确`HH:MM`、时区和当前合同调用，具体审核项与失败边界统一由月度reference维护 | `operator-guide.md` |
| SK-V06-071 | 写作交付包按原规则生成标题文件夹，但交接过程又留下根目录Markdown正文；版本重做还可能覆盖原同名DOCX，导致正式交付包和交接正文难以区分 | 保留写作Skill的文件夹交付；明确包内文章DOCX是唯一`final_path`，文件夹或ZIP只能作为`final_package_path`，禁止为交接另建正文副本；版本化重做使用版本化文件夹/文件名，保留旧包不覆盖。知识库桥接器继续从DOCX提取正文并生成内部`40` | 写作Skill `SKILL.md`、`references/delivery.md`、知识库`skill-integration-handoff.md`、`operator-guide.md`、终稿桥接规则 |
| SK-V06-072 | 公共知识缺口按文章分别登记，导致同一知识问题在覆盖视图中重复；`package_omission`的固定8条上限也把相关事实机械拆组，`gap_topic`过于笼统时人工无法判断缺什么 | 公共缺口按具体可回答的稳定知识问题复用同一`gap_key`并合并文章关联；登记脚本拒绝笼统主题并在同主题新键出现时复用旧键；覆盖视图兼容旧CSV并去重展示；`package_omission`按知识问题组织，不设Claim数量上限，只有问题不同才拆组 | `record_knowledge_gap.py`、`build_coverage_view.py`、`import_faithfulness.py`、`SKILL.md`、`governance-detection-and-lifecycle.md`、`faithfulness-result-contract.md`、`project-structure-and-templates.md` |
| SK-V06-073 | 运营手册仍把`50`描述成“引用率”记录，容易让内容运营把Faithfulness、Claim支撑和旧式SEO/RAG引用率混为一谈 | `50`只记录Faithfulness结果、Claim事后支撑和治理事项；旧式引用率不再属于知识库文章记录 | `operator-guide.md` |
| SK-V06-074 | GitHub直接安装时Skill根目录可能就是安装目录，Faithfulness合同定位器却只检查固定的`manage-article-knowledge-v0.6`嵌套子目录；知识库版本检测还可能把直接安装根目录记成`unknown` | 运行时同时识别直接安装根目录、维护仓库嵌套版本目录和显式`SKILL.md`路径；Faithfulness合同始终从实际Skill根目录的`references/handoff-contract.json`读取；知识库版本检测在目录名没有版本号时回读`SKILL.md`标题 | Faithfulness `manage_handoff_contract.py`、Faithfulness回归测试、知识库 `check_skill_update.py` / `record_project_run.py`、README |
| SK-V06-075 | 多个客户原始资料和写作目录尚未建库时，逐项目填写五项信息、手动建内部目录和一次性读取全部资料会消耗过多时间与Token | 新增首次工作区只读盘点与批量建库模式；统一使用“工作区扫描范围”“Obsidian知识库统一根目录”“Faithfulness结果统一根目录”“默认负责人”和接入范围；支持单个、指定多个、全部可识别项目及本次初始化上限。先输出项目映射和缺失项，人工确认后只初始化选定项目；原始资料不复制，外部写作目录需单独同意建立 | `workspace-onboarding.md`、`discover_workspace.py`、`SKILL.md`、`operator-guide.md`、`runtime-checklist.md`、README |
| SK-V06-076 | 工作区盘点脚本没有把默认负责人纳入机器报告，指定范围可能静默返回空结果，人工明确指定但暂时没有标准目录的项目也可能被过滤掉 | 盘点接口强制接收并回显默认内容运营负责人；`单个项目/指定项目`只扫描已指定且位于工作区范围内的候选，找不到、同名歧义或缺少`--project`直接报错；明确指定但未识别为v0.6的项目保留在报告并标记“未识别项目”，不自动初始化 | `discover_workspace.py`、`workspace-onboarding.md`、`runtime-checklist.md`、本更新记录 |
| SK-V06-077 | 批量建库虽然复用同一初始化器，但人工Prompt、盘点表和授权口令没有固定，容易出现不同人用不同说法或误以为批量建库会生成简化模板 | 固定一段可复制的批量建库Prompt、固定项目盘点表和两种批量授权回执；批量确认后不逐项目重复索要`确认建库`，但每个项目仍调用与单项目相同的`initialize_project.py`和完整v0.6模板 | `SKILL.md`、`workspace-onboarding.md`、`operator-guide.md`、`runtime-checklist.md` |
| SK-V06-078 | 运营手册先写建库再写写作Skill接入，容易让内容运营把“改造写作Skill”和“登记项目外部入口”当成同一件事，并在日常写作中重复发送接入Prompt | 手册前置写作Skill的一次性接入、升级和重做规则；随后按批量建库、单项目建库、项目写作流程入口确认的顺序组织。项目入口确认只登记写作任务入口、终稿入口和Faithfulness结果总目录；附录同步为同一顺序，不改变其余日常流程 | `operator-guide.md` |
| SK-V06-079 | 文章运行期间检查SKFB修复状态会拖慢写作，还容易把“已登记”误当成“已修复”；桥接器清理OneDrive临时目录失败时会把已提交任务报告成失败，项目校验器还会把临时目录当正式任务 | 将SKFB修复判断固定移出文章链路：维护窗口运行`manage_skill_feedback.py --audit`，月度审核只读复核并汇总新增、自测、待项目验证、已关闭和重开事项；没有Skill专项自测和原复现项目验证不得关闭。桥接器清理`.retired-*`失败只输出警告，不回滚已提交切换；项目校验器忽略`.retired-*`和`.revision-*`临时目录 | `monthly-and-handoff.md`、`runtime-checklist.md`、`operator-guide.md`、`writing_bridge.py`、`validate_v06_project.py` |
| SK-V06-080 | 批量盘点把项目根目录、内部资料目录和临时渲染目录混成大量候选，人工要为二十个项目逐项判断，可能比单项目建库更费事 | `全部可识别项目`只把扫描根目录的直接子目录视为项目边界，嵌套目录归入项目；输出改为逐项目卡片，固定说明五项建库和三项写作接入信息的已确定、自动建立、Codex继续核对和人工补充状态；临时目录自动排除，人工只一次确认可建库整组并补充少数异常项目 | `discover_workspace.py`、`workspace-onboarding.md`、`SKILL.md`、`operator-guide.md`、`runtime-checklist.md` |
| SK-V06-081 | 新建项目卡片把尚未存在的Obsidian项目目录直接当成人工输入，容易让人误以为需要先手动建目录，或把统一根目录重复套成项目目录 | 新建项目统一只收集`Obsidian知识库统一根目录`；初始化时由Codex按项目命名合同生成独立项目目录，完成后再登记实际Obsidian项目路径；既有项目接入仍使用实际项目路径 | `SKILL.md`、`workspace-onboarding.md`、`operator-guide.md`、`discover_workspace.py`、README |
| SK-V06-082 | 盘点脚本未把“知识库”目录名识别为客户原始资料候选，导致资料实际存在时退回到整个项目根目录，卡片无法给出明确来源路径；缺失外部入口也容易被误读为已存在 | 将非v0.6项目命名的“知识库”目录纳入源资料候选，并排除标准v0.6项目目录；缺失写作任务/终稿统一标记为`待建立入口（确认后自动创建）`，需人工一次授权后才建立 | `discover_workspace.py`、`workspace-onboarding.md`、`operator-guide.md` |
| SK-V06-083 | 批量项目卡片仍可能把缺少写作任务或终稿候选概括成“写作任务/终稿：未发现”，导致人工看不到实际的待建立路径或已有终稿候选 | 固定卡片展示：写作任务首次接入默认按重建，主字段显示`待建立入口（确认后自动创建）`和拟建立路径，旧目录只作备注；终稿有候选时直接列出完整绝对路径供选择，无候选时才显示同一待建立状态；不再用“写作任务/终稿：未发现”替代字段 | `SKILL.md`、`workspace-onboarding.md` |
| SK-V06-084 | 批量建库授权后仍需手动启动第二阶段，缺失写作入口也未同步建立；多终稿候选容易被自动选错 | 新增批量接入执行器：一次授权同时允许建立缺失写作任务/终稿默认目录并登记配置；无样例入口保持`部分接入`，多终稿候选必须人工选择且只阻塞对应项目 | `onboard_workspace.py`、`discover_workspace.py`、`SKILL.md`、`workspace-onboarding.md` |
| SK-V06-085 | 来源扫描会标记“建议建立MAT”，但正式MAT主表、来源台账、文章处理单、当前待办和月度/交接之间没有统一的强制闭环，可能留下候选存在而MAT台账为空，或文章已阻塞却未推送的状态 | 来源索引完成后按相同处理原因自动建立或复用正式MAT并回写SQLite与来源台账；无需建立时必须保留中文处置理由。正式MAT默认不推送，只有当前文章依赖、确实阻塞且无法唯一处理时才进入待推送/已推送/已升级；校验器交叉核对正式MAT、来源引用、开放处理单和当前待办，月度审核与交接分别读取当前行动项和全部未关闭事项 | `mat_lifecycle.py`、`build_source_index.py`、`validate_v06_project.py`、`initialize_project.py`、`SKILL.md`、`source-index-and-materials.md`、`article-knowledge-workflow.md`、`human-readable-control-artifacts.md`、`monthly-and-handoff.md`、`operator-guide.md`、`project-structure-and-templates.md`、`runtime-checklist.md` |
| SK-V06-086 | 来源台账的“可能主题”不能区分资料角色和七大模块候选，覆盖页无法区分有候选来源与确实缺少材料 | 技术登记表移除“可能主题”，来源索引在同一台账追加“来源主题与模块候选”表；先区分客户事实资料、写作运营资料、疑似文章或终稿、待确认，再按确定性信号生成可多选的七模块候选。覆盖页仅在原有“尚未定向处理材料”和“明确缺少材料或事实”两列消费结果，并增加“未纳入七模块候选”统计行；其他表格结构和内容保持不变 | `source_topic_mapping.py`、`build_source_index.py`、`build_coverage_view.py`、`initialize_project.py`、`validate_v06_project.py`、`SKILL.md`、`source-index-and-materials.md`、`project-structure-and-templates.md` |
| SK-V06-087 | CUS检测和月度/交接报告依赖人工记忆，可能漏检客户专属事实或把开放事项写成“无未完成事项” | 每篇文章前审核固定检查客户能力、规格、认证、案例、商业条件和公开授权；Faithfulness低于80%时自动在审核记录标记六类复核。项目校验器读取当前MAT/CUS/ANM、知识缺口和来源MAT候选，逐项核对月报与交接小节；开放事项不得写空结论，MAT候选必须有正式MAT或明确无需建立理由 | `template_contract.py`、`writing_bridge.py`、`import_faithfulness.py`、`validate_v06_project.py`、`governance-detection-and-lifecycle.md`、`monthly-and-handoff.md` |
| SK-V06-088 | 批量建库脚本只创建骨架和接入配置，却返回“已初始化”，执行Agent可能在官网画像和来源索引前提前收尾；画像恢复后又缺少统一状态回写入口 | `onboard_workspace.py`固定返回未完成和必须继续标记；新增`record_website_profile.py`，将官网画像成功、失败和来源索引后的状态收口作为确定性事务，同步项目基础信息、当前待办、版本入口和运行账本；官网失败继续本地建库，恢复后自动清除过期失败状态 | `onboard_workspace.py`、`record_website_profile.py`、`website-profile-state.md`、`SKILL.md`、`runtime-checklist.md`、`workspace-onboarding.md`、`initialize_project.py` |
| SK-V06-089 | 公共知识缺口登记或Faithfulness导入后只更新机器台账，`01_知识库覆盖与缺口.md`可能继续显示旧内容 | 抽出统一原子覆盖页重建函数；直接登记公共缺口、Faithfulness导入完成和文章任务推进共用该函数，确保覆盖页随当前知识缺口与任务状态同步刷新；覆盖页重建失败时不报告Faithfulness成功事件 | `record_knowledge_gap.py`、`import_faithfulness.py`、`advance_ready_tasks.py`、`build_coverage_view.py` |
| SK-V06-090 | 中文来源Claim只保存中文原文，英文`30`可能在每次生成时重新翻译，造成同一证据出现多个英文版本 | 中文最小原文证据形成正式Claim时固定保存经核验英文严格翻译；英文`30`必须完整复用该译文，校验器同时拦截中文Claim缺译文和英文`30`临时重译。英文来源无需重复译文，中文文章仍可使用中文原文 | `SKILL.md`、`article-knowledge-workflow.md`、`project-structure-and-templates.md`、`runtime-checklist.md`、`validate_v06_project.py` |
| SK-V06-091 | 新Codex任务只收到项目名称时无法稳定定位既有知识库，交接和补充操作可能依赖上一任务的目录记忆，或把无访问权限误报为项目不存在 | 既有项目操作统一先取得Obsidian定位：单项目填写实际项目路径，按名称或多项目操作填写统一根目录；定位后从项目配置读取原始资料和Faithfulness等路径。交接包Prompt和三类补充Prompt同步增加定位字段，并区分项目不存在与路径不可访问 | `SKILL.md`、`operator-guide.md`、`monthly-and-handoff.md`、`runtime-checklist.md` |
| SK-V06-092 | `项目根目录`新增为外部运营目录后，脚本示例仍用`<项目根路径>`或`<Obsidian项目根路径>`表示知识库目录，容易把外部目录误传给知识库脚本 | 所有知识库脚本示例统一使用`<Obsidian项目路径>`；`项目根目录`只表示外部运营项目文件夹；相关脚本的路径不存在和命名警告明确指出Obsidian知识库路径 | `SKILL.md`、运行清单、官网画像规则、月度与交接规则、项目模板、运营手册、相关脚本 |
| SK-V06-093 | 交接包脚本未读取v0.6标准字段`项目中文名称`，清单可能回退显示知识库目录名 | 企业名称优先读取`项目中文名称`，并继续兼容旧项目的`企业名称`和`项目名称`；自测覆盖两份人工清单和两份JSON机器清单 | `package_handoff.py` |
| SK-V06-094 | 写作桥接器和标准模板把`大纲状态`保存在文章需求顶层字段，项目校验器却只在`## 大纲`小节内读取，导致已有非空且已确认大纲的任务被误判为不合规，并使月度项目校验失败 | 项目校验统一优先读取标准顶层`大纲状态`，同时兼容旧文件放在大纲小节内的状态；自测样例改用与正式模板及桥接器一致的顶层字段位置 | `validate_v06_project.py` |
| SK-V06-095 | 所有`_failure`事件都会把接入状态改为异常，导致月度审核失败和已导入Faithfulness结果的重复提交污染三个入口状态 | 只把写作任务、终稿和Faithfulness的真实接口失败标为异常；月度审核失败只记运行异常；同一Audit且输入身份一致时幂等成功；有效接入检查会按路径、规则和样例恢复历史假异常 | `update_integration_status.py`、`check_integration.py`、`import_faithfulness.py`、`SKILL.md`、`runtime-checklist.md`、`faithfulness-result-contract.md` |
| SK-V06-096 | 交付方和接收方都使用泛称“项目交接审核”，旧脚本也没有强制两阶段审核落盘，导致交接包中审核来源和接收结果容易混淆 | 交付方`package_handoff.py`固定生成`YYYY-MM-DD_交付前项目交接审核.md`；接收方`handoff_migration.py --mode verify`固定生成`YYYY-MM-DD_接收后项目交接审核.md`。两份审核分别写入对应知识库、不得覆盖；`verify`有问题时仍生成接收后审核并报告不能交接，目标不可写时报告未落盘。 | `handoff_review.py`、`package_handoff.py`、`handoff_migration.py`、`SKILL.md`、`monthly-and-handoff.md`、`runtime-checklist.md`、`operator-guide.md` |

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
| 2026-09-07 | 合同、桥接、模板、归档与项目校验自测 | 通过；覆盖`MAK-HANDOFF-1.1`、两种重做模式的完整归档与版本递增、知识不变模式的`30/35`哈希更新、固定模板`v0.6-20260907.1`和项目校验。 |
| 2026-09-07 | Faithfulness v1.3单元测试 | 通过13项中的12项；1项既有v0.5外部导入测试因未配置外部路径按设计跳过。覆盖受管40正文边界、管理字段排除、合同/版本不兼容和既有结果拒绝覆盖。 |
| 2026-09-07 | 二组实际v2 Markdown跨Skill正文边界回归 | 通过；文章H1、正文和表格保留，`Article ID`、`Article Version`、`Target Language`、`Keywords`未进入51个Faithfulness文章单元。原终稿和项目文件未修改。 |
| 2026-09-07 | 重做与固定模板debug回归 | 通过；合同、模板、桥接、迁移及其余13个知识库脚本自测通过；真实合法`30/35`与正式Claim整包依次完成知识不变重写v2、知识重整v3和完整旧版归档；Faithfulness 12项通过、1项外部v0.5路径测试按设计跳过。 |
| 2026-09-08 | 首次工作区盘点与范围选择、固定批量入口自测 | 通过；只读发现脚本支持统一工作区/Obsidian/Faithfulness根目录、默认负责人、单个/指定/全部范围和本次上限；指定范围缺失或不存在时明确报错，暂未建成v0.6的明确项目保留为“未识别项目”；批量Prompt、固定盘点表、授权回执和单项目完整模板已统一；未创建目录、未访问官网、未覆盖已有报告。 |
| 2026-09-08 | 逐项目卡片批量盘点回归 | 通过；`全部可识别项目`按工作区直接子目录归组，测试范围从19个混合候选收敛为6个项目；项目内部资料、写作、终稿和渲染目录不再重复列为项目，官网线索过滤工具站点，缺失外部入口统一归为一次性建立建议。 |
| 2026-09-08 | SKFB维护窗口与月度只读复核、桥接临时目录回归 | 通过；文章运行只登记SKFB并继续原任务，Skill维护窗口负责专项审计和阶段推进，月度审核汇总维护证据；月度模板升级为`v0.6-20260908`；桥接清理临时目录失败不再使已提交任务失败，项目校验忽略`.retired-*`和`.revision-*`；知识库与已安装Skill逐文件哈希一致。 |
| 2026-09-09 | 批量建库授权与首轮接入隔离模拟回归 | 通过；无终稿候选自动建立默认入口，单候选直接登记，多候选明确保持“待人工选择”且不阻塞其它项目；未带`--confirm-batch`不写入；`check_integration.py`、`writing_bridge.py`和`validate_v06_project.py`自测通过。 |
| 2026-09-09 | `SK-V06-085` MAT正式化、推送与交叉校验回归 | 通过；来源索引自测验证扫描候选自动生成稳定正式MAT且重复扫描不重复建项；项目校验自测验证正式MAT与来源关联一致，进入内容运营推送状态时必须同时存在开放文章前处理单和当前待办，缺失任一入口会被拦截；全部现有脚本`--self-test`通过。 |
| 2026-09-10 | `SK-V06-090` 中文Claim双语证据与英文`30`复用回归 | 通过；英文来源无需重复译文，中文最小原文证据缺少有效英文严格翻译会被拦截，英文`30`即使同步更新SHA-256也不能使用临时重译；覆盖页自测继续通过。Skill Creator快速校验因当前Python环境缺少PyYAML未能启动。 |
| 2026-09-10 | `SK-V06-091` 既有项目定位与交接Prompt回归 | 通过；单项目与按名称/多项目两种定位入口已写入主Skill、运行清单和交接规则；运营手册正文与附录中的交接、补充文件、补充网站和更新主官网Prompt同步；`validate_v06_project.py`、`package_handoff.py`和`handoff_migration.py`自测通过。 |
| 2026-09-10 | `SK-V06-092` 项目路径术语回归 | 通过；知识库脚本示例统一使用`<Obsidian项目路径>`，外部运营目录继续只称`项目根目录`；三个交接相关脚本自测和四个受影响脚本语法检查通过。Skill Creator快速校验因当前Python环境缺少PyYAML未能启动。 |
| 2026-09-10 | `SK-V06-093` 交接包企业名称字段回归 | 通过；交接包优先读取v0.6标准字段`项目中文名称`，兼容旧字段，并验证总清单、项目清单及两份机器清单名称一致。 |
| 2026-09-10 | `SK-V06-094` 大纲状态位置兼容回归 | 通过；`validate_v06_project.py`、`writing_bridge.py`和`template_contract.py`自测通过；P-005三篇标准桥接任务不再被误判，大纲相关错误由3项降为0，项目校验结果为0项错误、8项警告。Skill Creator快速校验因当前Python环境缺少PyYAML未能启动。 |
| 2026-09-10 | `SK-V06-095` 接入状态误报与重复Audit幂等回归 | 待本次脚本自测、重复导入专项验证和P-005只读项目校验完成后补充。 |
| 2026-09-11 | `SK-V06-096` 两阶段项目交接审核回归 | 已补齐交付方和接收方的固定审核文件名、脚本落盘门禁和Prompt说明；`package_handoff.py --self-test`、`handoff_migration.py --self-test`、`validate_v06_project.py --self-test`、AST检查和`git diff --check`通过；Skill Creator快速校验因当前Python环境缺少PyYAML未能启动。 |

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
