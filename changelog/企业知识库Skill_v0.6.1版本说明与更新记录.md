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
| v0.6.1 完整单元测试 | 56项通过；新增终止事件字段矛盾、自动恢复证据/映射/哈希/Claim数、歧义Claim保留阻塞回归，并覆盖网页候选事实与Formal Claim来源闭环、主题串篇、混合应用Claim、通用服务Claim、英文证据中文混入、连续证据覆盖、writing_ready门禁和批次唯一入口回归 |
| `advance_ready_tasks.py --self-test` / `writing_bridge.py --self-test` | 均通过；自测夹具与实际目录迁移和来源闭环合同一致，未放宽生产门禁 |
| `run_knowledge_workflow.py --self-test` / `tests/test_run_knowledge_workflow.py` | 通过；覆盖账本自动定位、旧账本精确匹配、空证据非终止、缺失批次非终止和结构化工作流回执 |
| Faithfulness审核Skill现有单元测试 | 60项通过，1项按原条件跳过；配置 v0.6.1 后兼容导入测试通过 |
| 正式 Claim 证据逐字反查 | 已接入文章级交付门禁 |
| 批次成员登记 | 已接入 `writing_bridge.py --batch-id` |
| 同一来源跨文章合并 | 已接入批次账本 |
| P-005 当前项目 | 只读复验 270 个文章级错误、15 个警告；新增主题、语言和连续证据门禁已命中对应串篇文件；历史模板兼容提示已与当前交付错误分开，不修改文章或历史审核结果 |
| 月度统计口径 | P-005 2026-09：应审核 6 篇、有效 6 篇、平均明确支撑率 57.31%；002/003 仅序列化变化保留警告 |
| 尚未完成 | 批次证据采集、Formal Claim自动沉淀和按批次渲染 `15/20/30/35` 的完整编排器仍需继续开发；当前已完成单篇门禁后的确定性恢复闭环，来源冲突、无法唯一确定Claim、事实语义不确定和不可替代材料缺失仍按合同保留人工阻塞，不能把恢复器当作事实判断器或把账本校验器当作完整采集器 |

本次修复不修改写作 Skill。调用方以后应使用：

```text
python scripts/run_knowledge_workflow.py --project <Obsidian项目路径> --batch-id <批次ID>
```

该入口解决参数漏传和错误误终止问题；它不会把空证据变成有效证据，也不会绕过 Formal Claim、`30/35` 或 `writing_ready` 门禁。网页抓取、Claim沉淀和文章素材渲染仍必须按批次合同完成后才能进入后续阶段。
