# 企业知识库 Skill v0.6.1 版本说明与更新记录

| 项目 | 说明 |
|---|---|
| 当前状态 | 开发与回归中 |
| 版本基线 | v0.6.1 为 `manage-article-knowledge-v0.6` 的完整副本；v0.6 保持不变 |
| 主要变化 | 将同批文章的知识准备改为一次批次检索、统一证据核验、统一 Claim 沉淀和按文章渲染 |
| 未列规则 | 本文未明确修改的 v0.6 规则全部继承 |

## 一、版本原则

| 原则 | 说明 |
|---|---|
| 版本隔离 | v0.6.1 在独立目录开发、测试和回归；不覆盖 v0.6，不直接改写现有客户项目 |
| 批次优先 | 同一批次一起写的文章共享一次来源读取、候选事实、正式 Claim 和治理判断 |
| 证据先行 | 只有正式 Claim 与本轮来源证据逐条核验通过后，才生成文章级 `15/20/30/35` |
| 幂等恢复 | 中断后复用已成功的来源读取、Claim 核验和治理事项，不重复访问官网或重复生成文件 |
| 旧文重整 | `knowledge_refresh_and_rewrite` 只是不重新生成大纲，其余知识准备步骤与新文章相同 |

## 二、基线与继承证明

| 校验项 | 记录 |
|---|---|
| v0.6冻结位置 | `versions/manage-article-knowledge-v0.6/` |
| v0.6兼容活动位置 | `manage-article-knowledge-v0.6/` |
| v0.6.1活动位置 | `manage-article-knowledge-v0.6.1/` |
| v0.6.1建立方式 | 完整复制 v0.6 后增加批次运行合同和证据账本入口 |
| v0.6原有客户兼容 | v0.6 项目仍按原版本运行；v0.6.1 项目需单独确认升级和回归 |

## 三、明确保留

| 保留项 | 规则 |
|---|---|
| 写作Skill边界 | 不修改写作Skill；写作侧只接收批次完成后按文章生成的当前 `30` |
| 来源权重 | 客户原始资料、客户官网、已确认关联网站和客户明确确认继续按同等一方证据处理 |
| 竞品隔离 | 竞品名称、型号、特殊产品、参数、价格、案例和比较结论仍不得进入正式Claim或 `30/35` |
| 治理分流 | 冲突、缺失和高风险事实继续进入 ANM/CUS/MAT/知识缺口，不由知识库自行选边 |
| 终稿和Faithfulness | `40/50`、Faithfulness导入和最终完成事件规则继续继承 v0.6 |

## 四、本轮修改与新增

| 变更ID | 问题 | v0.6.1规则 | 主要落点 |
|---|---|---|---|
| SK-V061-001 | 多篇文章分别重复读取同一官网、资料和Claim，流程慢且结果不一致 | 以 `batch_id` 合并同批文章的大纲问题，来源在批次内只读取一次，文章只引用批次证据 | `references/batch-knowledge-workflow.md`、`SKILL.md` |
| SK-V061-002 | Claim ID 存在但 `30` 证据可能来自临时段落或被改写文字 | 进入 `30` 前必须核对正式Claim文件、来源位置、连续原文、适用边界和本轮运行ID | `references/batch-knowledge-workflow.md` |
| SK-V061-003 | `15/20/30/35` 先生成，最后项目校验才发现来源和状态错误 | 批次证据清单先校验；未通过不得渲染文章文件或写入自动通过状态 | `scripts/batch_knowledge_run.py`、批次合同 |
| SK-V061-004 | 同一批次中断后反复抓官网、反复生成派生文件 | 运行账本按来源哈希、网页正文哈希和候选事实去重，重试只恢复未完成项 | `references/batch-knowledge-workflow.md`、`scripts/batch_knowledge_run.py` |
| SK-V061-005 | 新文章和同大纲重整被实现成两套流程，重整过程中混入旧版文件 | 两者共用同一批次知识准备流程；同大纲重整只复用已确认大纲身份，不读取旧版知识文件 | `SKILL.md`、批次合同 |
| SK-V061-006 | 官网冲突、竞品内容和缺失材料先进入 `30` 后再补治理 | 候选事实先分流到 ANM/CUS/MAT/公共知识缺口，未解决事项不得进入写作素材包 | `references/batch-knowledge-workflow.md` |
| SK-V061-007 | 语言清理掩盖了来源不明问题 | `30` 的事实正文必须回链批次证据记录；原文、核验翻译和管理说明分离，不能只做中文字符检查 | `references/batch-knowledge-workflow.md` |
| SK-V061-008 | 批次合同没有进入写作请求入口 | `writing_bridge.py prepare` 接收 `--batch-id`，将文章、大纲身份和批次成员写入项目批次账本 | `scripts/writing_bridge.py` |
| SK-V061-009 | 同一来源被多篇文章引用时被误判为重复 | 批次账本按来源键合并文章和知识问题引用，来源仍只读取一次 | `scripts/batch_knowledge_run.py` |
| SK-V061-010 | `35` 只验证 Claim ID，不能确认 `30` 段落是否来自正式知识 | 逐条把 `30` 引用块反查到映射的正式知识文件；正文不逐字存在时阻止交付 | `scripts/article_state.py` |
| SK-V061-011 | 批次未完成也可能进入等待终稿 | 文章迁移前必须找到对应批次账本、文章成员记录和 `evidence_ready` 状态 | `scripts/advance_ready_tasks.py` |
| SK-V061-012 | 同一来源包含多个候选事实时，按来源去重会静默丢掉后续事实 | 按“来源 + candidate_id”合并事实；来源读取单独写入 `source_reads`，同一候选跨文章只合并关联引用 | `scripts/batch_knowledge_run.py` |
| SK-V061-013 | 批次证据账本没有强制执行硬字段和核验目标原文要求 | 强制 `source_sha256`；“本轮核验通过”必须同时提供 `claim_id` 与 `verified_target_excerpt`；重复候选的事实正文、Claim、处置冲突时硬失败 | `scripts/batch_knowledge_run.py` |
| SK-V061-014 | `research_required`、模板校验失败或`moved_count=0`被误当成任务结束 | 新增统一终止判定；这些状态固定输出`terminal=false`和下一动作，只有`article_completed`、明确的`needs_human`或`handoff_error`允许结束 | `scripts/workflow_terminal.py`、`scripts/advance_ready_tasks.py` |
| SK-V061-015 | 一篇文章的问题可能使同批其他文章一起停止 | 交接规则明确按文章隔离恢复；单篇调研或模板失败不改变其他文章的继续状态 | `references/skill-integration-handoff.md`、`references/article-knowledge-workflow.md` |
| SK-V061-016 | 修模板时容易复制历史任务身份、官网凭证、大纲或Claim映射 | 当前任务只能按自身身份和当前合同生成与校验，历史任务不能作为当前字段来源 | `references/article-knowledge-workflow.md`、`references/runtime-checklist.md` |
| SK-V061-017 | 工具恢复后仍在“还需登记/复核/修复”处提前结束 | 运行清单要求依据终止判定继续推进，并在最终回复前验证终点事件 | `references/runtime-checklist.md`、`references/skill-integration-handoff.md` |
| SK-V061-018 | 已完成历史任务被当前模板整体重验，放大兼容提示并诱导改写历史文章 | 已完成任务按自身历史合同做兼容校验；保留文章身份、目录、正文边界、哈希、审核记录和真实证据风险检查，不套用当前完整模板 | `scripts/template_contract.py`、`scripts/validate_v06_project.py` |
| SK-V061-019 | 月度统计把仅序列化变化误判为正文变化 | 月度计算器比较解析后正文；仅格式/编码变化保留警告并计入有效结果，实质正文变化才失效 | `scripts/calculate_monthly_faithfulness.py` |
| SK-V061-020 | 月审只呈现错误总数，维护清单和错误性质无法追踪 | 校验失败的月报必须按任务状态、文件类型和根因归组，说明触发次数不等于事实错误，并链接同步维护清单 | `scripts/monthly_issue_grouping.py`、`references/monthly-and-handoff.md` |
| SK-V061-021 | 中间步骤、单篇研究失败或模板错误被误当成整批终点 | 终止判定固定返回 `terminal=false` 和下一动作；按文章隔离恢复，只有完成、明确人工阻塞或交接错误允许结束 | `scripts/workflow_terminal.py`、`references/skill-integration-handoff.md` |
| SK-V061-022 | 文章级 `30/35` 可能把其他产品主题的 Formal Claim 串入当前文章 | 按当前文章需求的标题、产品对象、选题方向和大纲，与 Formal Knowledge 的稳定实体/主题键执行产品主题门禁；混合应用 Claim 仅在当前产品被其原文列出时复用，通用 `service:*` Claim 可跨产品复用；`writing_ready` 单篇门禁与项目月审使用同一规则 | `scripts/validate_v06_project.py`、`scripts/article_state.py`、`references/batch-knowledge-workflow.md` |
| SK-V061-023 | 英文 `30` 证据块可能混入中文管理标签，导致引用内容和目标语言不一致 | 英文目标的证据正文引用块禁止中文混入；管理说明必须放在引用块外的独立字段；单篇 `writing_ready` 门禁同步拒绝 | `scripts/validate_v06_project.py`、`scripts/article_state.py`、`references/batch-knowledge-workflow.md` |
| SK-V061-024 | `35` 只检查中文来源的英文翻译，英文来源也可能只映射部分连续证据 | 每条 `35` 映射必须完整覆盖 Formal Claim 的“最小原文证据”；中文来源的英文文章完整覆盖已核验英文严格翻译；不完整时阻止 `writing_ready` | `scripts/validate_v06_project.py`、`scripts/article_state.py`、`references/batch-knowledge-workflow.md` |
| SK-V061-025 | 写作编排可以在 `writing_request`、`evidence_ready` 或校验失败后自行继续生成文章，绕过单篇 `writing_ready` 门禁 | 新增单篇 `scripts/issue_writing_ready.py`；仅该入口在当前交付门禁通过后迁移任务、生成绑定文章ID/版本/30哈希的 `writing_ready.json` 并发出 `writing_ready`；`writing_bridge.py finalize` 拒绝没有有效回执的终稿；一次性接入 Prompt 要求写作Skill等待并核对回执后才调用正文/DOCX/图片工具 | `scripts/issue_writing_ready.py`、`scripts/writing_bridge.py`、`references/skill-integration-handoff.md`、`references/operator-guide.md` |
| SK-V061-026 | 写作门禁阻塞后，编排把“资料未就绪/未生成文章”错误当成整条任务终点，未回到知识库继续修复 | `issue_writing_ready.py` 的阻塞输出固定带 `terminal=false`、`workflow_state=writing_ready_pending`、`blocked_step`、`next_owner`、`resume_condition` 和 `next_action`；接入规范明确按“门禁输出→知识库按当前文章修复→重新门禁”循环恢复，批次按文章隔离；不放宽写作门禁 | `scripts/issue_writing_ready.py`、`scripts/workflow_terminal.py`、`references/skill-integration-handoff.md`、`references/runtime-checklist.md`、`references/operator-guide.md` |
| SK-V061-027 | 官网抓取凭证被误当成 Formal Claim，或把网页候选事实与 PDF/DOCX Claim 串源；同一网页正文还可能被机械复制到多个大纲问题 | 新增网页凭证、候选事实、Formal Claim 和 `30/35` 的来源闭环门禁；网页 URL、候选事实来源、Claim 来源链接/精确位置必须一致；网页事实需要沉淀时必须先建立/复用正式 Claim；同一候选事实跨多个大纲问题时必须记录明确支持范围，否则阻止 `writing_ready` | `scripts/article_state.py`、`references/batch-knowledge-workflow.md`、`references/runtime-checklist.md`、`SKILL.md` |
| SK-V061-028 | 门禁脚本以退出码 `2` 表示未通过，但外部编排器可能把非零退出码误当成流程终点，导致小范围阻塞时整条链路停止 | `issue_writing_ready.py` 每次写入结构化 `writing_gate_result.json`；`terminal=false`、`writing_gate_status=blocked` 和 `workflow_state=writing_ready_pending` 固定表示可恢复状态；`workflow_terminal.py` 新增统一解析器，机器回执优先于退出码，缺失/异常回执按非终止处理 | `scripts/issue_writing_ready.py`、`scripts/workflow_terminal.py`、`references/skill-integration-handoff.md`、`references/runtime-checklist.md`、`SKILL.md` |
| SK-V061-029 | 批次账本只校验字段和来源链接，候选事实原文仍可能没有逐字沉淀到 Formal Claim，问题在 `30/35` 生成后才暴露 | “本轮核验通过”前置核对 Claim 文件、同源链接和 `verified_target_excerpt`/`original_excerpt` 逐字覆盖；不满足时账本失败并要求先修复或建立 Formal Claim，禁止继续渲染 `30/35` | `scripts/batch_knowledge_run.py`、`references/batch-knowledge-workflow.md` |
| SK-V061-030 | 外部调研、来源闭环或单篇模板错误发生时，模型可能在记录错误后提前结束，要求用户重复发送“继续” | 明确以结构化门禁结果驱动文章级恢复循环；单篇失败只保留该文章阻塞，其他无共享依赖文章继续；反馈台账是旁路记录，不改变状态，也不是流程终点 | `SKILL.md`、`references/skill-integration-handoff.md`、`references/runtime-checklist.md` |
| SK-V061-031 | 终止判定在事件字段缺失/错误时仍可能使用 `reason=needs_human` 或 `handoff_error` 误判终点；项目级迁移成功也没有明确说明仍需逐篇签发写作许可；桥接自测把终稿接收误认为会直接迁移到等待Faithfulness | 终止判定只接受明确的 `article_completed`、`needs_human` 或 `handoff_error` 事件，`reason` 不能单独终止；`advance_ready_tasks.py` 对迁移结果固定输出 `terminal=false` 和逐篇 `issue_writing_ready.py` 下一步；桥接自测按真实合同检查 `20_等待终稿` 中的规范化 `40`，后续由 `create_faithfulness_record.py` 负责迁移 | `scripts/workflow_terminal.py`、`scripts/advance_ready_tasks.py`、`scripts/writing_bridge.py`、`SKILL.md`、`references/skill-integration-handoff.md`、`references/runtime-checklist.md` |
| SK-V061-032 | 写作门禁在缺少必填参数或文章任务无法定位时，`argparse`/`SystemExit` 可能先于统一回执兜底直接退出，外部编排器仍可能把退出码误判为终点 | `issue_writing_ready.py` 将参数错误、任务定位异常和其他异常统一输出 `writing_gate_status=blocked`、`terminal=false` 的可恢复回执；新增缺参和未知任务命令行回归测试 | `scripts/issue_writing_ready.py`、`tests/test_workflow_terminal.py` |
| SK-V061-033 | 参数齐全但未提供文章ID或外部任务键时仍可能由`parser.error`直接退出，且Windows中文错误输出会使回归夹具无法读取回执 | 将身份参数校验也纳入统一非终止回执；命令行回归测试允许系统编码替换，覆盖缺少合同参数、缺少文章身份和未知任务，继续验证`terminal=false`而不依赖控制台编码 | `scripts/issue_writing_ready.py`、`tests/test_workflow_terminal.py` |
| SK-V061-034 | 门禁发现`15/20/30/35`的结构、证据正文、Claim映射或哈希问题后只写阻塞回执，常规错误需要人工再次发送“继续”；恢复器也可能因一个无法唯一确定的证据块而放弃其他可确定修复 | 门禁阻塞后自动在临时副本中同步当前文章身份和版本，局部重建可唯一确定的`30`证据、`35`映射/来源/哈希和`20`可用Claim数，自动重跑门禁并在通过后继续迁移、签发`writing_ready`；无法唯一确定Claim、来源冲突、事实语义不确定或缺少不可替代材料的块保留文章级`terminal=false`阻塞；正常退出码`2`不再被异常兜底覆盖 | `scripts/recover_article_package.py`、`scripts/issue_writing_ready.py`、`scripts/article_state.py`、`references/runtime-checklist.md`、`references/skill-integration-handoff.md`、`references/operator-guide.md`、`tests/test_validation_lifecycle.py` |
| SK-V061-035 | 批次运行依赖模型手工拼接 `batch_knowledge_run.py` 参数；漏传 `--ledger` 后普通参数错误被误判为流程终点 | 新增批次知识准备唯一入口，只接收项目路径和 `batch_id`，自动推导或精确查找账本，写入可恢复的结构化工作流回执；账本缺失、空证据、工具失败和单篇门禁失败均固定为 `terminal=false`，不得以退出码结束整批 | `scripts/run_knowledge_workflow.py`、`SKILL.md`、`README.md` |
| SK-V061-036 | 批次账本校验、文章包恢复和写作门禁之间没有统一的阶段状态，编排器在未完成知识准备时提前收尾 | 入口持久化 `workflow_state`、批次校验、文章级恢复、重试次数和下一动作；按文章隔离恢复，只有合同终点事件允许结束 | `scripts/run_knowledge_workflow.py`、`tests/test_run_knowledge_workflow.py` |
| SK-V061-037 | `20` 的 CUS/ANM 汇总可能只满足表格格式，未证明逐项读取来源；恢复器还会把缺少审核的任务直接写成“未触发” | 新增 `prewrite_governance.py` 逐项反查来源正文、固定类别、真实 CUS/ANM 主表与同ID详情，并接入文章包门禁；恢复和生成夹具改为写入“待核对”明细，不能伪造“未触发”；缺少明细、来源或治理闭环时保持 `terminal=false`，禁止签发 `writing_ready` | `scripts/prewrite_governance.py`、`scripts/article_state.py`、`scripts/recover_article_package.py`、`scripts/advance_ready_tasks.py`、`scripts/writing_bridge.py`、`SKILL.md` |
| SK-V061-038 | 写作测试只在 Obsidian 内生成 `10`，外部写作任务入口没有真实需求记录，导致两套任务来源不同步 | 明确外部写作任务入口是新任务唯一来源；写作方须先在已确认入口落盘需求与大纲，再提交 `writing_request`；知识库只读取和登记，内部 `10_文章知识需求.md` 不替代外部记录。桥接器已校验记录存在、可读取及首次登记 SHA-256，同一任务复用时哈希变化则拒绝静默交接；已接入写作 Skill 的升级 Prompt 同步上述职责，不直接修改写作 Skill。外部记录是否位于配置入口内的机器路径边界校验尚待补齐 | `references/skill-integration-handoff.md`、`references/operator-guide.md`、`scripts/writing_bridge.py`、`SKILL.md` |
| SK-V061-039 | `35` 写作素材索引哈希漂移修复后，旧 Faithfulness 结果可能被误视为当前有效 | 2026-10-08：自动恢复仍按当前 `30` 重建 `35` 哈希，但不因此恢复旧 Faithfulness 结果的有效性；`50` 仍引用旧知识附件哈希时门禁拒绝沿用，必须针对当前文章版本和知识附件重新审核并导入 | `scripts/article_state.py`、`scripts/recover_article_package.py` |
| SK-V061-040 | 原大纲重做同时使用“重新整理知识”和“复用当前知识”两种语义，旧模式名称与临时脚本容易把本应空白重建的知识包复制成 v1 改版本 | 保持稳定的 `new_article` 流程不变；将原大纲重做统一为 `outline_refresh`（原大纲身份 + 本轮新知识，禁止复制旧 `15/20/30/35`）和 `knowledge_reuse_rewrite`（原大纲身份 + 已通过整包校验的当前知识，才允许复制）；同步机器合同、桥接器、模板校验、门禁与运行说明，合同升级为 `MAK-HANDOFF-1.4` 并保留旧兼容输入 | `references/handoff-contract.json`、`scripts/handoff_contract.py`、`scripts/writing_bridge.py`、`scripts/template_contract.py`、`scripts/advance_ready_tasks.py`、`references/skill-integration-handoff.md`、`references/version-and-archive-contract.md`、`SKILL.md` |
| SK-V061-041 | 原大纲重新整理仍可能由临时脚本直接写入不完整的 `15/20/30/35`，最后才在 `writing_ready` 暴露结构错误，造成长时间重复修补 | 增加 `scripts/run_outline_refresh.py` 作为 `outline_refresh` 唯一逐篇接续入口；重整运行记录绑定入口、文章版本和 `refresh_run_id`，从空知识包开始；模板门禁逐文件核对本轮运行绑定、旧包复制标记和四份文件完整性，要求生成一份立即校验一份；`new_article` 原流程保持不变 | `scripts/run_outline_refresh.py`、`scripts/writing_bridge.py`、`scripts/template_contract.py`、`references/skill-integration-handoff.md`、`SKILL.md` |
| SK-V061-042 | 重整门禁在本轮事实盘点中读取错误的处置列；Windows 配置路径更新被正则替换语义误处理；已迁移到等待终稿的任务重复校验被状态门禁拒绝 | 按 `CLAIM_RECHECK_HEADER` 定位“本轮处置”列并修正明细计数；用函数式替换保留 Windows 路径字面值；交付门禁允许 `20_等待终稿` 重新核对当前 `15/20/30/35` 和回执，仍保留全部严格校验与恢复规则 | `scripts/template_contract.py`、`scripts/update_integration_status.py`、`scripts/article_state.py`；专项自测与全量56项测试通过 |
| SK-V061-043 | 2026-10-10 整体调试：原大纲重整入口直到四份文件齐全才校验，未知任务和参数错误缺少结构化恢复回执，导致错误延迟暴露或被误当作流程终点 | 每轮立即校验已存在文件的模板；整包齐全后再查来源与证据闭环。参数、身份和定位失败返回退出码2及 `terminal=false`、下一责任方、恢复条件与动作；不改变 `new_article` 流程，不绕过 `writing_ready` | `scripts/run_outline_refresh.py`、`tests/test_runtime_debug.py`；知识库全量65项回归通过，另验证等待终稿重复门禁与正式来源变化后阻塞 |
| SK-V061-044 | 2026-10-10 整体调试：反馈详情中历史“待验证”永久阻挡已完成验证的事项关闭；负责人中的 Windows 路径被正则替换解释为转义 | 关闭要求本次专项自测和项目验证明确通过且无负状态；审计以最后一条项目验证判断当前状态，完整保留旧记录。负责人字段改函数式替换，保留路径字面值；最新失败仍报告矛盾并拒绝关闭 | `scripts/manage_skill_feedback.py`、`tests/test_runtime_debug.py`；覆盖历史待验证后关闭、负结果拒绝且原文件不变、再次失败重开和 Windows 路径 |
| SK-V061-045 | 2026-10-10 GitHub发布检查：仓库根测试仍引用已迁出的v0.6活动目录，README与版本索引仍声称旧目录保留，缓存文件未排除 | 根测试入口改为当前v0.6.1，34项仓库级测试通过；README和索引说明当前活动目录与冻结v0.6的位置；Git忽略Python缓存，发布当前Skill、历史版本与更新记录，不改变生产流程 | `tests/`、`README.md`、`changelog/版本记录索引.md`、`.gitignore` |
| SK-V061-046 | 官网抓取凭证落在单篇任务目录，但没有同步到批次账本；模型需要自行发现下一步，容易在来源抓取后把内部待办误交人工；未决凭证也可能被批次整理器忽略 | 批次唯一入口先幂等同步当前文章、当前`batch_id`凭证；只有当前可用Formal Claim来源URL唯一匹配且连续原文逐字存在时自动登记为证据，其他凭证进入`capture_inbox`并阻止`evidence_ready`。运行说明和写作适配器升级Prompt要求`terminal=false`内部知识步骤自动继续并按同一身份重跑，不要求人工重复发送“继续”；保持`new_article`业务顺序和严格写作门禁 | `scripts/sync_website_evidence.py`、`scripts/run_knowledge_workflow.py`、`scripts/batch_knowledge_run.py`、`references/batch-knowledge-workflow.md`、`references/operator-guide.md`、`SKILL.md`、`tests/test_sync_website_evidence.py`；全量68项测试通过 |
| SK-V061-047 | 2026-10-12 资料包遗漏与主体归属不清分类可能被用于没有实际证据的主张；主体说明等元数据也可能进入审核证据 | `package_omission`须逐主张核对已有Formal Claim完整覆盖并列出具体ID；`evidence_context_gap`须回读当前`30`第1至第3节证据正文，核对文件、行号和逐字引文，排除主体/来源元数据。知识准备保留确定主体所需的连续来源上下文，先沉淀到Formal Claim再逐字进入`30`，不临时替换代词、不改变历史Faithfulness结论；审核Skill同步证据边界和同义改写规则 | `scripts/import_faithfulness.py`、`SKILL.md`、`references/governance-detection-and-lifecycle.md`、`references/faithfulness-result-contract.md`、`tests/test_evidence_context_disposition.py`；知识库73项与审核68项回归通过，包含跨Skill导入测试 |
| SK-V061-048 | 2026-10-12 全量回归发现Windows默认编码输出中文重整JSON时，UTF-8接收方解析失败，可能误认为恢复入口失效 | 重整机器回执使用ASCII兼容JSON转义，解析后的中文内容与结构化恢复条件不变；不依赖调用方临时设置编码，也不放宽任何门禁 | `scripts/run_outline_refresh.py`；缺参和未知任务回执测试及知识库全量73项回归通过 |
| SK-V061-049 | 2026-10-13 `we/our/this`的归属只在管理说明中，来源证据与主体可能无法闭环；新沉淀/复用Claim和恢复30缺少统一归属模板，跨块绑定与模板漂移可能漏检 | 新建Claim同事务保存EC-1归属主体、对象、指代、核验依据/日期/状态及原文SHA-256；旧Claim首次用于当前任务前回源核验，缺字段先归档补齐再生成30/35，不能猜主体。30固定四级归属/正文板块和四字段顺序；恢复器同时重建归属、正文、35映射和哈希；拒绝空/重复字段、哈希漂移、错层级及跨块/章节绑定。审核仅用归属解析指代，各含指代证据块须分别绑定coreference_evidence与同块普通证据；普通unknown继续报告与治理，不降低事实判断门禁 | `references/formal-claim-and-evidence-context.md`、`references/project-structure-and-templates.md`、`SKILL.md`、`scripts/evidence_identity.py`、`scripts/recover_article_package.py`、`scripts/batch_knowledge_run.py`、`scripts/writing_bridge.py`、`tests/test_evidence_identity*.py`；知识库93项、审核88项回归通过（跨Skill导入启用，无跳过），批次/模板/迁移/桥接/编排自测通过。两套解析器一致，安装版Junction同步；不修改写作Skill、真实文章、历史Claim或审核结果 |
| SK-V061-050 | 2026-10-13 重新测试自行新增“本轮原件核验现场.md”并用其证明自身引文，CUS/ANM排除理由可机械复用；重检阻塞后旧写作许可仍可能被沿用，历史Claim无独立原文小节时单纯35哈希漂移也可能停顿 | 新请求使用GC-1固定来源核验模板：15记录来源ID、真实入口、精确位置、原文、当前运行ID及SHA-256，20按GC-ID逐类回读受管原件/视觉提取稿、官网凭证或RES；需求范围只支持对应类别不适用，事实冲突引用双方，禁止任务自建笔记或Formal Claim代替回源。旧无标记任务保持合法入口兼容，未知协议不降级；显式知识复用只在原需求引文未变时更新需求指纹，恢复暂存副本只读真实项目源资料。blocked撤销旧writing_ready；写作前和交稿前核对当前门禁、身份、版本与30哈希，已有终稿时按版本合同重建，只有全部证据与映射门禁通过的单纯35指纹漂移才自动更新并重签；内部核验继续由知识库执行，不要求人工填写或反复说继续 | `scripts/governance_source_check.py`、`prewrite_governance.py`、`template_contract.py`、`writing_bridge.py`、`issue_writing_ready.py`、`recover_article_package.py`、`tests/test_governance_sources.py`、`test_runtime_debug.py`；`SKILL.md`、模板、治理协议、handoff及operator-guide两段接入Prompt同步。知识库106项回归、审核88项兼容回归无跳过通过；批次/模板/迁移/桥接/编排5项自测通过，含合法来源、旧run/错来源/错指纹、视觉提取绑定、RES、需求复用、旧许可撤销、单纯哈希恢复及错误门禁拒收终稿。D盘与安装Junction同步；不修改写作/审核Skill本体、真实文章/Claim/审核结果，不删除真实额外笔记 |
| SK-V061-051 | 2026-10-13 GAP缺口、外部RES调研与正式Claim难以互相定位；调研前/审核后发现同题缺口关联分散，有Claim容易被误当作整个缺口解决 | RES核验20增加GR-1固定六列表，每行一个GAP，支持多对多关联及本次已回答/尚缺范围；受管登记器幂等维护20、配对10导航字段及CSV的RES/Claim回链并重建覆盖页，原文不改、状态不自动关闭。覆盖页提供RES与真实正式Claim直达入口，按各次调研显示范围；只有完整覆盖且无剩余才已解决，部分覆盖须保留剩余范围。新GAP自动同题复用或按项目短码从全部历史数字末段最大值续号，新RES使用稳定中文主题；历史ID和目录不改名，无新表只按明确引用兼容导航，复用时由知识库回源补表，纯Claim复核用无/仅复核行 | `scripts/external_research_links.py`、`build_coverage_view.py`、`record_knowledge_gap.py`、`validate_v06_project.py`、`tests/test_external_research_links.py`；SKILL及外部调研/命名/模板参考同步。117项回归、6项流程自测及脚本语法检查通过，覆盖多对多、幂等、未知协议、假Claim拒绝、解决范围约束、配对10/20、旧记录兼容及流水续号。P-005的11份RES关联只读校验0错误，GAP-021/022内存视图可直达RES；整体项目仍有38项既有文章证据格式错误，不在本次修改范围。安装Junction同步，不修改写作/审核Skill及真实文章/Claim/审核/GAP记录 |
| SK-V061-052 | 2026-10-13 SKFB-011：schema 1历史账本partial_success被专用校验拒绝，而全项目门禁未报告同一错误 | 读取时只把明确的历史partial_success兼容为partial，原JSONL不覆盖；新建/追加仍限当前合法枚举。项目门禁调用同一账本校验器，真实非法状态、缺字段、未知schema、重复运行ID与坏JSON继续报错 | `scripts/record_project_run.py`、`validate_v06_project.py`、`references/project-structure-and-templates.md`、`SKILL.md`、`tests/test_feedback_011_012_regressions.py`；知识库124项回归及账本/项目校验器自测通过，原P-005两种账本校验一致且历史原行保持 |
| SK-V061-053 | 2026-10-13 SKFB-012：控制快照内SRC-EXT-*等管理说明被扫描为缺失来源，归档合法操作反而新增3条误报 | 来源ID解析不截取通配模式；控制/机器历史快照不按当前事实来源重验管理说明，归档清单与SHA-256校验仍执行。当前正式知识、文章及正式知识历史中的具体来源缺失继续报错，外部RES身份校验保持 | `scripts/validate_v06_project.py`、项目模板和Skill说明、`tests/test_feedback_011_012_regressions.py`；知识库124项正反回归通过，原项目3条快照来源误报消失且原快照哈希保持；协调审核SKFB-010升级为v1.6.11，审核91项含跨Skill导入测试通过，无跳过。D盘及安装Junction同步，不修改写作Skill或历史文章/审核 |
| SK-V061-054 | 2026-10-13 ANM-001/005复核：旧流程把审核记录限制与真实知识缺口混登记，并把审核两轮清单来源误当成固定unknown；证据组件漏列时直接降黄 | 新增`audit_process_limitation`受管分类及逐Claim固定模板，只接收双轮原始语义均为entailed、最终仅因组件记录校验降黄的结果；真实unknown、语义分歧、证据缺失和源文异常继续走原GAP/CUS/MAT/ANM路径。审核Skill新增冻结并集与有界预检：保留两轮独有命题，先取得两轮独立证据判断；仅验证过的证据列表遗漏自动补齐，未解决项继续unknown，历史结果不原地修改。维护规则立即复核失效程序类ANM，保留历史50/分数/哈希，不新增任意说明文件 | `scripts/import_faithfulness.py`、`references/faithfulness-result-contract.md`、`references/knowledge-base-maintenance.md`、`references/project-structure-and-templates.md`；审核侧`audit_preflight.py`、`references/audit-preflight.md`及接入规则；知识库124项、审核100项测试通过，安装版Junction同步，不修改写作Skill、真实文章或历史审核结果 |
| SK-V061-055 | 2026-10-13 整体调试发现：旧文章30没有EC-1模板，但复用的Formal Claim已升级为EC-1，映射校验错误地按Claim模板强制旧30使用四级归属板块，导致历史任务批量报错 | EC-1兼容判断以当前30是否声明EC-1为准；旧30与EC-1 Claim可继续只读核验，不自动改写历史文件。当前30声明EC-1时仍严格要求四级归属、相邻正文和字段顺序；新任务门禁不放宽 | `scripts/evidence_identity.py`、审核Skill同源解析器、`tests/test_evidence_identity.py`；P-005历史格式错误不再作为新任务兼容规则误报，知识库回归测试更新；不修改历史文章/30/35/Claim |
| SK-V061-056 | 2026-10-13 整体调试发现：正式Claim后续补充或扩展原文证据后，全项目校验把当前Claim文本倒套到已完成且已导入的历史文章包，错误地要求重写旧30/35 | 只有40已完成、50已导入且30/35/40/50文章ID和版本一致的文章，才把当前Claim摘录差异作为兼容警告；仍校验历史包身份、哈希、来源和映射，不回写历史文件。未完成、未导入和writing_ready门禁继续要求完整满足当前Formal Claim证据。同步修正审核Skill的v0.5互操作测试夹具，移除v0.5初始化器不支持的参数，不改审核运行逻辑 | `scripts/validate_v06_project.py`、`tests/test_validation_lifecycle.py`；审核Skill `tests/test_audit_pipeline.py`；知识库127项、审核100项回归通过（显式启用v0.5导入互操作测试，无跳过），专项自测及56个Python脚本AST检查通过；P-005旧Claim差异降为警告，覆盖视图指纹过期仍待知识库正常维护时重建，不修改Obsidian文章或Formal Claim |
| SK-V061-057 | 2026-10-14：15重复盘点冗余、无关联GAP残留；20可能机械复用Claim却标充分；原大纲重整缺少当前包完成后才可查看旧包的明确约束 | 新建和outline_refresh使用PR-1固定六节；来源命中与Claim核验/动作合并到九列明细，五项结论按明细计算，官网主动搜索和连续正文凭证、GC-1及特殊资料核验保持。20逐问题校验CF→Claim→35映射与覆盖/充分性一致；无GAP五列均无，审核后GAP不倒填15，新GAP只能auto，历史键可更新。run_outline_refresh在已有运行JSON登记当前需求及四文件哈希绑定的后置只读对照许可，文件变更失效，正常不加资料包变化表；内部可恢复项由知识库重建继续，不放宽writing_ready | `scripts/preparation_record.py`、`scripts/template_contract.py`、`scripts/writing_bridge.py`、`scripts/run_outline_refresh.py`、`scripts/article_state.py`、`scripts/recover_article_package.py`、`scripts/record_knowledge_gap.py`、`scripts/validate_v06_project.py`、15固定模板/工作流/清单/交接与命名说明、`tests/test_preparation_record.py`；知识库138项、审核106项回归全部通过（跨Skill导入已启用）；桥接器、模板与推进专项自测通过；两套79个脚本/测试AST检查通过，安装版Junction与D盘一致；未修改写作Skill、真实文章/Claim/历史审核或项目台账，Skill quick_validate因本机缺少PyYAML未运行成功，另行检查frontmatter基本字段与安装关联 |

| SK-V061-058 | 2026-10-15：原大纲重整长时间重复恢复；当前10已升版，批次可能登记旧版本或默认new_article；官网同步把文章运行ID当成批次ID，哈希候选编号又不符合PR-1；30/35同时缺失无法首次生成；未闭环来源读取丢失、整批阻塞和迁移后未签许可可能反复空转 | 批次身份统一从提交后的10和运行JSON读取；省略模式沿用当前任务，同一请求重放幂等恢复及补登记，不再次归档或升版，显式冲突模式拒绝。官网凭证严格绑定本篇当前research/refresh运行，旧run明示跳过、版本/指纹冲突报具体恢复条件；CF使用三位流水号，capture_id独立存指纹。source_reads在Claim闭环前保存，校验失败不清空；非采用候选须有同源同run处置和具体依据，治理须有真实入口，不要求伪造Claim。恢复器从当前15逐问题映射与本轮已核验完整Claim生成缺失30/35并重算归属、行号、哈希；不读取旧包，不伪造六层检索、官网访问或GC-1通过。批次按文章独立校验和推进，保留pending_steps，已迁移任务也可恢复签许可；无输入变化的语义失败只校验一次，真实I/O失败仍有限重试 | `scripts/writing_bridge.py`、`sync_website_evidence.py`、`batch_knowledge_run.py`、`recover_article_package.py`、`run_knowledge_workflow.py`、`article_state.py`、`advance_ready_tasks.py`、`SKILL.md`、批次合同和两份恢复回归测试；知识库145项通过，审核106项兼容回归通过（含真实v0.5导入互操作）；66个脚本/测试AST通过，批次与工作流自测通过。临时项目实跑new_article/outline_refresh从缺失30/35至writing_ready、重复恢复moved_count=0、同批另一篇未完成仍逐篇推进、旧run/旧版本/错指纹拒绝、候选排除闭环及中断补登记；D盘与安装Junction一致。通用quick_validate因运行时缺PyYAML未完成，未安装额外依赖。Git最后提交为2026-09-22，不能据此归因于10月14单次更新；PR-1表格解析已有兼容，未认定其为根因。不修改写作/审核Skill、真实Obsidian文章、Claim或历史结果 |
| SK-V061-059 | 2026-10-16：同一批次文章从v2切换到v3/新research或refresh运行后，旧evidence、capture_inbox和source_reads仍留在活动账本；当前运行没有官网凭证时，入口只重复门禁，无法继续真实来源检索，导致“候选事实未绑定当前运行ID”持续阻塞 | 提交已确认的当前10和运行JSON后，按文章身份比较版本、模式及当前research/refresh运行；发生切换时把旧文章成员、evidence、capture_inbox、source_reads和问题记录写入run_history，活动区只保留当前运行，无法唯一归属的共享来源拒绝覆盖。严格门禁覆盖三类活动记录并按文章独立推进；当前凭证为空时回执为`terminal=false`的`source_collection`，明确继续来源检索、写入当前凭证、重建证据并重跑门禁；`knowledge_reuse_rewrite`沿用旧证据，不误触发新运行隔离 | `scripts/batch_revision.py`、`writing_bridge.py`、`sync_website_evidence.py`、`batch_knowledge_run.py`、`run_knowledge_workflow.py`、`run_outline_refresh.py`、`archive_project_version.py`、`SKILL.md`、批次/归档合同、`tests/test_batch_revision.py`及工作流续跑回归；156项Skill回归通过，批次/归档/工作流self-test通过，68个Python脚本/测试AST通过；通用quick_validate因运行时缺PyYAML未执行；D盘活动版与安装Junction一致，未修改真实客户项目、写作Skill或审核Skill |
| SK-V061-060 | 2026-10-19：PR #10 的更新分支采用根目录 Skill 布局，与 main 的版本目录、历史包及更新记录产生合并冲突 | 保留 main 的版本目录、README、历史更新记录与冻结版本；最新活动 Skill 放入 `manage-article-knowledge-v0.6.1/`。保留双方测试，修正仓库测试的脚本定位，补回 main 独有的客户标记回归；同步正式 v0.6.1 更新记录，修正导航，不修改运行规则 | PR #10 合并冲突修复；仓库入口 166 项、活动包内 157 项单元测试全部通过，两套存在重复覆盖，不合计为独立用例数；不修改真实客户数据、写作 Skill 或审核 Skill |

## 五、回归范围

| 回归项 | 预期 |
|---|---|
| 三篇文章同批运行 | 官网和共享资料只读取一次，候选事实和Claim共享 |
| 新文章 | 先批次证据，再按文章生成 `15/20/30/35` |
| 同大纲知识重整 | 不生成新大纲，其余步骤与新文章一致 |
| 官网访问失败 | 保留失败状态和恢复条件，不写成未命中，不重复抓取 |
| 正式Claim不存在或来源不匹配 | 阻止进入 `30`，生成对应治理事项 |
| 单篇审核失败 | 只阻塞关联文章；共享证据和其他文章不重复生成 |

本次同步更新 D 盘 v0.6.1 源目录和安装版 `C:\Users\DELL\.codex\skills\manage-article-knowledge`；不修改写作 Skill。

## 六、当前验证结果与已知限制

| 项目 | 结果 |
|---|---|
| `writing_bridge.py`、`article_state.py`、`advance_ready_tasks.py`、批次账本脚本语法检查 | 已通过 |
| `advance_ready_tasks.py --self-test` | 已通过 |
| `tests/test_workflow_terminal.py` | 通过；覆盖中间状态、终止事件字段矛盾、缺参和未知任务回执均不能误终止 |
| `template_contract.py --self-test` | 已通过 |
| `batch_knowledge_run.py --self-test` | 已通过；验证同源多候选不丢失、来源读取去重和核验字段门禁 |
| `issue_writing_ready.py` 门禁回归 | 已通过；未通过模板/证据门禁时返回 `writing_gate_status=blocked`，通过后才生成 `writing_ready.json`；终稿接收无回执时拒绝 |
| 写作门禁阻塞恢复回归 | 已通过；阻塞后由知识库在临时副本自动修复当前文章的`15/20/30/35`确定性问题并重跑门禁，成功后自动继续签发`writing_ready`；歧义Claim、来源冲突和不可替代材料缺失仍明确保留`terminal=false`；正常退出码`2`不会覆盖详细回执；安装版为 D 盘 v0.6.1 目录的 junction，同步生效 |
| v0.6.1 完整单元测试 | 68项通过；覆盖终止事件、文章包自动恢复、Formal Claim来源闭环、主题/语言/连续证据门禁、批次入口以及官网凭证同步的幂等、旧批次隔离和未决Claim阻塞 |
| `advance_ready_tasks.py --self-test` / `writing_bridge.py --self-test` | 均通过；自测夹具与实际目录迁移和来源闭环合同一致，未放宽生产门禁 |
| `run_knowledge_workflow.py --self-test` / `tests/test_run_knowledge_workflow.py` | 通过；覆盖账本自动定位、旧账本精确匹配、空证据非终止、缺失批次非终止和结构化工作流回执 |
| Faithfulness审核Skill现有单元测试 | 60项通过，1项按原条件跳过；配置 v0.6.1 后兼容导入测试通过 |
| 正式 Claim 证据逐字反查 | 已接入文章级交付门禁 |
| 批次成员登记 | 已接入 `writing_bridge.py --batch-id` |
| 同一来源跨文章合并 | 已接入批次账本 |
| P-005 当前项目 | 2026-10-13重新只读运行完成门禁：1个错误、13个警告。已完成文章对当前Formal Claim摘录的历史版本差异作为警告，不再阻断；剩余唯一错误是覆盖视图指纹过期，属于待正常重建的项目派生视图。8篇旧任务竞品信息字段、SQLite WAL/SHM临时文件和2篇Markdown序列化变化为兼容/运行警告；未修改Obsidian项目文件 |
| 月度统计口径 | P-005 2026-09：应审核 6 篇、有效 6 篇、平均明确支撑率 57.31%；002/003 仅序列化变化保留警告 |
| 尚未完成 | 对不能与唯一可用Formal Claim严格匹配的凭证，候选事实判断、Formal Claim新建/更新及按批次生成`15/20/30/35`仍由知识库Skill继续执行；本次新增同步器不替代事实判断器。来源冲突、Claim范围不明、事实语义不确定或不可替代材料缺失时保留明确文章级阻塞，但不得把可由知识库继续处理的内部步骤要求人工接手 |

本次修复不修改写作 Skill。调用方以后应使用：

```text
python scripts/run_knowledge_workflow.py --project <Obsidian项目路径> --batch-id <批次ID>
```

该入口解决参数漏传和错误误终止问题，并自动同步当前批次网页凭证；它不会把未核验候选变成有效证据，也不会绕过 Formal Claim、`30/35` 或 `writing_ready` 门禁。无法自动闭环的候选必须由知识库流程继续核验、沉淀或治理后再运行同一入口。
