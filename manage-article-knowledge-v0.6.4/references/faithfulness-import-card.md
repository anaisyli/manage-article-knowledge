# Faithfulness导入速查卡

收到同合同版本的`faithfulness_completed`，或批次入口回执中该篇`stage=faithfulness_import`后，由知识库立即导入，只读本卡。审核结果在50的“指定审核结果目录”，不在批次账本里；账本里没有结果载荷不是停止理由。导入器会机械校验文件身份、哈希、三态、复核行、收敛元数据和处置映射，并在报错里点名不匹配项；只有报错点名某条规则而本卡不够用时，才用`scripts/reference_section.py`读[Faithfulness结果合同](faithfulness-result-contract.md)的对应小节。导入阶段不读`runtime-checklist.md`、交接规范第6–7节或治理协议，也不整份读取prepared、judgments、adversarial-review、缺口CSV或SKFB台账。

## 1. 命令

`<任务>`取`faithfulness_completed`回执里的`task_dir`；回执没有该字段时，用`04_文章任务/30_等待Faithfulness/`下的本篇任务目录。

1. 先预检：`python scripts/import_faithfulness.py --task-dir <任务> --check-only`。它核对身份、哈希、当前`30`是否就是写作许可绑定的字节、`30/35`映射，在读取处置之前停止，不写任何记录。只有换行符或文末空行不同时会自动恢复为写作许可绑定的原字节；其他不一致说明写作者看到的不是当前`30`，停止并按版本与归档合同递增文章版本，不改`35`指纹、不让审核方重新准备。
2. 预检通过且无unsupported：去掉`--check-only`重跑同一条命令。
3. 有unsupported：先运行`python scripts/faithfulness_unsupported_digest.py --result-dir <50中的指定审核结果目录> --output <工作目录>/unsupported-digest.json`，按第2–3节写处置JSON，再运行`python scripts/import_faithfulness.py --task-dir <任务> --disposition <处置JSON>`。
4. 成功输出`completion_receipt=<路径>`后，运行`python scripts/handoff_contract.py --event article_completed --payload <completion_receipt> --verify-completion --expected-article-id <文章ID> --expected-article-version <文章版本>`。只有`completion_verified=true`才算完成。

`--task-dir`会从`40/50`记录和项目布局推出文章、`30`、`50`、版本、合同版本、终稿接收日期、三个Faithfulness数据文件和结果目录，不必手拼这些参数。`50_文章知识使用与Faithfulness记录.md`就是导入器所说的receipt，不是审核结果目录`_work`里的check回执。

新公共缺口要先登记、再导入：`python scripts/record_knowledge_gap.py --csv <项目>/05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv --gap-key auto --topic <中文知识问题> --article-id <文章ID> --article-date <YYYY-MM-DD> --trigger-basis 首篇普通缺口|核心章节首次|高风险事实首次|重复文章`。已有缺口关联本文时用原`--gap-key`。

写作者新增的客户事实（`cus`）或来源冲突、危险范围扩张（`anm`）在台账里还没有编号时，也先登记、再把输出的编号写进该组的`issue_key`：

`python scripts/record_governance_item.py --project <项目> --kind CUS --set 想确认什么=<…> --set 为什么需要=<…> --set 回复前怎么处理=<…> --set 相关文章/Claim入口=<文章ID的哪些主张>`

- 只写事项本身，每个值都要含中文人话。标题默认取“想确认什么”；`当前阶段`默认`待判断要不要问`，`下一责任人`默认内容运营，`重开条件`默认“客户补充或更正该事实、新证据与回复冲突，或其他文章再次依赖该事实”，需要时用`--title`、`--set`、`--detail`覆盖。CUS阶段可取：待判断要不要问、准备客户话术、等待发送、等待客户回复、收到回复，待核实、无需询问、已完成。
- ANM用`--kind ANM`，写`发生了什么`、`为什么有风险`、`现在怎么处理`、`证据包入口`；`当前阶段`默认`待判断`（可取等待材料、处理中、部分解决、已完成处置（原文未修复）、已解决），`下一责任人`默认Codex，`原文是否修复`默认否，`重开条件`有默认值。
- 同一事项已有编号时，脚本会拒绝新建并给出编号：改用`--item-id <编号> --append-note <本篇复现说明>`追加，不新建。

## 2. 处置JSON（schema 1.1）

每个unknown或contradicted的`claim_id`恰好进入一组；supported不得出现。**判断只在这几处**：`category`、`issue_key`、公共缺口的`scope_review`、`package_omission`的`classification_basis`（写遗漏的Formal Claim ID）、`writing_only`的`fact_check`、`audit_process_limitation`的`process_review`。`group_id`、`topic`、`classification_basis`（上述两类以外）、`status`（公共缺口取缺口台账当前状态）、`article_impact`、`handling`、`next_owner`、`entry`、`close_condition`都可省略，导入器按类别和台账补全；写了就照用，写的内容仍按下面的规则校验（中文人话、状态与台账一致等）。

```json
{"schema_version": "1.1", "article_id": "<文章ID>", "groups": [
  {"claim_ids": ["C001", "C002"], "category": "new_public_gap", "issue_key": "<gap_key>",
   "scope_review": {"knowledge_question": "", "claim_matches": {"C001": "", "C002": ""}},
   "fact_check": {"contains_factual_judgment": true, "reusable_across_articles": true,
                  "knowledge_domains": ["method"], "why_not_knowledge_issue": ""}},
  {"claim_ids": ["C003"], "category": "package_omission", "issue_key": "",
   "classification_basis": "已核验的CLM-…完整覆盖该主张但未进入30",
   "fact_check": {"contains_factual_judgment": true, "reusable_across_articles": false,
                  "knowledge_domains": ["customer_fact"], "why_not_knowledge_issue": ""}}]}
```

- `scope_review`：公共缺口组（`existing_gap`、`new_public_gap`）必填，写一个具体知识问题，并逐条说明每个`claim_id`怎样落入这个问题。其他类别可以省略。
- 最短长度（导入器按此拒绝，写之前自查）：`knowledge_question` 至少12个字符且含中文；`claim_matches` 每条至少12个字符；`writing_only` 的 `why_not_knowledge_issue` 至少8个字符且不能只写“无/不适用”；`audit_process_limitation` 的 `source_review` 至少20个字符。
- `knowledge_domains`的可选值：`none / customer_fact / technical / method / regulation_standard / safety_limit / detection_validity / procurement_selection / dynamic_fact / other_public_knowledge`。`none`不能与其他值并存。
- 分组：一个公共缺口只问一个能用同一批证据回答、能调研也能关闭的具体问题，同一问题下主张数量不限。同一行业、同属“一般包装方法”或“选型流程”不能单独成组；结构适配、陈列、材料工艺、样品验证、简报规格这类不同问题分到各自的缺口。不为凑数按关键词或字数拆。
- `claim_matches`逐条写这条主张说了什么、为什么属于这个问题；去掉编号后同一句话用在3条及以上主张上，导入器拒绝。说不出具体关系，说明这条主张属于别的问题。

## 3. 分类（按顺序判断）

1. `existing_gap`：**先看摘要`gaps`**，台账里状态不是已解决/已关闭、问题能覆盖该主张的缺口都用它，优先于新建；同一篇的主张可分进多个已有缺口。尚未关联本文的，先用原编号关联：`python scripts/record_knowledge_gap.py --csv <项目>/05_数据与审核/20_知识库覆盖与缺口/10_知识缺口记录.csv --gap-key <原gap_key> --topic <台账原问题> --article-id <文章ID> --article-date <YYYY-MM-DD> --trigger-basis 重复文章`（第二篇起自动转待外部调研）。`issue_key`写gap_key，`status`可省略，由导入器取台账当前状态。
2. `package_omission`：经核验存在的Formal Claim能完整覆盖该主张，但没进`30`。在`classification_basis`列出具体Claim ID；只是主题相近或部分覆盖不能用。`issue_key`写空。
3. `evidence_context_gap`：`30`已有逐字证据正文，但主体或来源归属无法唯一确认。每条写出当前`30`的逐字quote、行号和文件路径。`issue_key`写空。没有`30`证据时不能用。
4. `cus` / `mat` / `anm`：写作者新增的客户事实走CUS，未处理的本地资料走MAT，来源冲突或危险范围扩张走ANM。`issue_key`写台账中已存在的ID。
5. `new_public_gap`：摘要`gaps`里确实没有能覆盖的缺口时才新建。能判断真假或可跨文章复用的一般原理、技术、方法、选型、法规等公共知识问题，先按第1节登记。主张含客户名称或客户专属能力时不能用，回到第2–4项分流。
6. `writing_only`：只用于纯结构、过渡、CTA、修辞或一次性观点。必须满足`contains_factual_judgment=false`、`reusable_across_articles=false`、`knowledge_domains=["none"]`，并在`why_not_knowledge_issue`写具体理由。法规、标准、认证、安全、限值、检测有效性、采购选型和动态事实一律不能用。
7. `audit_process_limitation`：仅限两轮原始判断都是entailed、最终为unknown、收敛原因只有组件记录问题的主张。追加`process_review.claim_records`，其中`validation_reasons`与该主张的`reconciliation.reasons`逐字一致。
8. `audit_unresolved`：审核结论未定。一轮审核据当前`30`的逐字证据判为entailed，最终因双轮结论不一致或复合主张未拆分而为unknown（摘要标`audit_unresolved_candidate`）。知识库没有缺什么，不登记缺口、CUS或ANM；只写`category`和空`issue_key`，其余字段与`fact_check`由导入器补全，导入器核对收敛原因和`30`中的逐字证据。两轮都未确认的主张不能用；两轮都支持、只因记录问题降级的用第7项或请审核方`reopen-review`。不能诚实归入任何类别时，不要暂停整篇或硬套类别，先看是否属于本项

摘要里的`public_gap_blocked_by`、`writing_only_blocked_by`、`audit_process_limitation_candidate`、`audit_unresolved_candidate`就是导入器的拒绝规则，按它们分流可以避免重试。

## 4. 报错后

只修正报错点名的组或参数，用同一条命令重试；不重新生成整份处置，不重复执行已成功的缺口登记。导入是事务式的：失败时不写指标、`50`、台账，也不迁移任务；同一审核结果重复提交按幂等成功返回。导入阶段不运行项目级校验，项目级历史错误不属于本篇导入。遇到`PermissionError`时按平台方式提权，原样重跑同一条命令。不改审核三态或分数，不手工拼`article_completed`。
