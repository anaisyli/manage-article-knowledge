# Faithfulness结果交接规范

## 1. Skill边界

Faithfulness由独立文章审核Skill产生。本Skill不抽取文章原子事实、不判断supported或unsupported，也不生成其审核报告，只验证并导入结果。

除非结果确由官方DeepEval运行并清楚标识，否则评价模式必须写：DeepEval Faithfulness 规则复现（Codex 评审，非 DeepEval 官方运行）。

## 2. 审核上下文

标准manage-article-knowledge v0.6模式只使用实际交给写作Codex的`30_本篇知识库资料.md`。随文事实文件必须先进入来源层、Formal Claim和`30/35`，不能作为平行知识文件直接加入审核。写作要求、SEO/GEO、风格和结构参考不是事实证据。`35`只供知识库追溯和导入后的确定性映射，绝不能加入Faithfulness retrieval context；否则结果会因为使用了写作时不可见的证据而虚高。

不能因为资料包链接了知识库，就把整个知识库放入retrieval context。写作提示、SEO/GEO规则和文章评价指令都不是证据。`30`中的直接写作事实、英文表达、控制、建议、缺口处理和审计说明都不是可引用的正向证据；审核Skill只提取第一至第三节中明确标明为“证据正文”的连续来源正文或已核验目标语言翻译。直接写作事实可以指导作者，但外部审核的证据引文必须落在对应证据正文。

受管v0.6的`40_最终文章.md`必须且只能包含一组`<!-- ARTICLE_BODY_START -->`与`<!-- ARTICLE_BODY_END -->`。审核器只解析两标记之间的正文文字、列表和表格；标题、关键词、TDK、图片说明、交付管理字段和审核文字不进入文章单元。知识库导入器复核prepared时必须使用同一行解析规则：`![alt]`和`![alt](url)`均不计作正文，普通`[text](url)`保留`text`。标记缺失、重复或倒置时硬失败，并要求知识库桥接器重新规范化`40`，不得由审核器猜测正文范围。

外部终稿为DOCX时，`writing_bridge.py`必须读取段落样式并把明确的Word`Title`、`Heading 1-6`、段落/样式`outlineLvl`和已登记的`Section Label/Section Title/Subheading`类样式转换为Markdown标题，同时留下`MAK_DOCX_HEADING_STYLE`来源标记。普通正文不得因粗体、字号、短句或空行外观被猜成标题。Word表格必须输出标准Markdown表头分隔行；明确的`w:tblHeader`或首行表格样式作为结构表头，没有表头时生成空结构表头并保留全部原始数据行。Faithfulness在prepared中保留结构标题和表格表头的原顺序，但不给候选证据、不给claim，并在分母冻结前确定性排除；该结构排除不能被`heading_override_reason`恢复。

Faithfulness只报告“终稿事实被实际交付事实附件支持的比例”。它不是SEO/GEO质量、搜索表现、可发布性、文风或模型能力的总分，不设置100%门槛，也不要求每句话都有附件证据。模型可以为文章完整性补充行业常识、一般原理、解释、结构和过渡；这些内容若没有进入事实附件，可能被标为`unsupported`，但仅表示本次上下文未覆盖，不能单独视为写错或要求重写。单篇结果用于记录本次覆盖，并在完成本地检索后触发轻量公共知识缺口登记：核心章节或高风险公共事实首次出现即进入`待外部调研`；普通公共知识首次为`观察中`，第二个不同文章ID出现时升级。客户专属、未处理本地资料和来源异常仍分别进入CUS、MAT、ANM，不由外部调研替代。

## 3. 可接收文件

当前deepeval-article-audit可交接：文章ID-prepared.json、文章ID-judgments.json和faithfulness_summary.md。协议2.0受管结果还必须在同目录提供`文章ID-adversarial-review.json`作为独立语义复核审计件；导入器必须验证它与judgments逐条一致。详细Markdown和HTML仍由审核Skill管理，不是知识台账导入必需文件。

judgments中的claim_id，例如C001，是文章原子事实ID，不是正式知识Claim ID。

## 4. 结果取得方式

支持两种等价入口：内容运营提交本篇审核结果的具体文件或专属目录；或者根据`01_工作台/40_写作与Faithfulness接入配置.md`中的已确认结果总目录，为本篇计算`[结果总目录]\[项目ID]\[文章ID]\v[文章版本]\`并由Faithfulness Skill自动创建缺失目录，再登记到`50`，由Codex后续读取。项目ID来自知识库交接，不按客户名称、标题或目录顺序猜测。该目录保存当前版本的prepared、judgments和summary等审核产物，不把知识库项目复制进去。

不得递归扫描用户文档、下载目录或整个审核根目录来猜测结果。目录必须精确对应本篇文章版本；受管自动调用必须由固定的`deepeval-article-audit`执行，并携带当前`handoff_contract_version`通过唯一`references/handoff-contract.json`校验。目录缺文件、存在多个无法唯一判断的候选版本或哈希不一致时，`50`保持`等待Faithfulness结果`并写明原因。读取目录不等于无条件导入，仍须通过下面的版本、内容和哈希校验。内容运营不需要重复提交终稿，也不需要再说“继续”。

## 5. 导入校验

导入前验证：

1. prepared和judgment schema受支持；
2. 文章ID一致；
3. 旧协议verdict只含supported或unsupported；协议2.0还必须包含并一致映射`deepeval_verdict=yes/no/idk`与`semantic_status=entailed/contradicted/unknown`，且只有entailed可映射为supported；
4. supported判断含证据；
5. prepared中的文章内容仍与40_最终文章.md一致；
6. prepared中的知识块仍与实际资料文件一致；
7. summary的计数和百分比与judgments一致；
8. 保存文章和当前`30`的SHA-256，并确认prepared中只有这一个manage-v0.6事实输入；
9. 协议2.0的独立adversarial-review覆盖每条claim，且judgments已通过`reconciliation.gate_version=1.0`双轮自动收敛；每条claim和复核行的最终语义状态一致。每条复核行必须携带并匹配`unit_id + article_quote + 完整规范化claim`命题身份，`claim_id`只作显示和逐行覆盖检查，不能单独证明两轮审核的是同一命题；`article_line`保留用于定位但不作为稳定身份键。`claim_fragment`只解释本行关注的词或语义成分，可以很短、也可以在多条claim中重复，但不得用于绑定、重绑或跨命题迁移。若`claim_inventory.matched_claim_id`存在，也必须指向相同完整命题身份。收敛器只能保留或降级，不能升级第一轮判断；分歧、覆盖不全、模板化复核或未解决原子性时自动落为unknown，不建立人工审核队列。

知识库正式指标始终是知识附件明确支撑率：`entailed ÷ (entailed + unknown + contradicted)`。该指标没有目标值；0%、低分或仅一条明确支持都可作为正常结果，不表示文章质量、发布资格，也不触发写作重试。DeepEval默认兼容率仅保留在机器JSON/CSV中用于接口诊断，不展示在HTML、Markdown、`50`、月报或交接页。按GitHub默认行为，`penalize_ambiguous_claims=false`时`idk`可能计入兼容分子；这只表示“未被明确否定”，绝不能解释为“得到支持”或写入正式Claim支撑关系。

人读记录固定使用四态：灰色非主张不计入、绿色`entailed`写“明确支持”、黄色`unknown`写“尚未确认（证据不足）”、红色`contradicted`写“明确冲突”。红色只用于允许证据在同一对象、范围、条件和时间/版本下明确不相容且双轮均确认冲突；证据缺失、部分覆盖、版本无法对齐或双轮分歧只能是黄色。项目机器明细继续保留兼容字段：`unsupported = unknown + contradicted`。协议2.0的`10_文章Faithfulness明细.csv`分别保存`unknown_claims`和`contradicted_claims`，`50_文章知识使用与Faithfulness记录.md`、月度审核和交接审核分别展示两项数量。旧协议没有三态字段时写`N/A（旧协议未记录）`，不得把全部unsupported推断为明确冲突。

审核器必须先执行两轮相互独立的全文原子主张识别并取并集：除prepared已结构化标记的标题外，任一轮识别为可验证主张即进入分母；只有两轮都确认是纯问题、CTA、纯过渡、纯修辞或无可验证关系的纯偏好时才排除。分母在查证据和判绿黄红前冻结。规则信号兜底只能恢复漏项，不能替代第二轮；若只能把复合单元整体恢复为一条黄色主张，必须保留coverage warning，不能借此签发100%。不得通过漏提、扩大证据含义或把建议误归非主张来抬分。

同质并列成员共享主体、谓词/操作关系、范围、条件、时间和语气时，Faithfulness按一条集合值主张计数；成员仅仅可以逐项枚举不构成拆分理由。不同对象、关系、条件、数量/时间、效果或因果可能得到不同证据/verdict时仍须拆分。该边界在查看证据前确定：集合值需全部实质成员被覆盖才可为`entailed`，部分覆盖为`unknown`；同范围证据明确否定某成员时可整体为`contradicted`并定位冲突成员。知识库导入器不得为改善比例或与旧结果对齐而重拆、重并或重判；同一文章的新审核可能因当前抽取规则形成与旧结果不同的claim inventory，旧结果继续按原审计件留存，不强制批量重算。

受管结果目录必须严格是`[结果总目录]/[项目ID]/[文章ID]/v[文章版本]/`；导入器会核对prepared中的项目ID、文章ID、文章版本、文章/知识文件SHA-256、受管标记、`handoff_contract_version`和核心文件是否都在该目录。旧协议1.0要求prepared、judgments和summary三个核心文件；协议2.0还必须核对同目录的独立`[文章ID]-adversarial-review.json`，且judgments使用schema 1.1并完成reconciliation gate 1.0。审核器产生的`audit_quality: warning`与`audit_warnings`属于过程提示，不改变知识附件明确支撑率，也不创建人工逐条队列；但协议2.0独立复核文件缺失、损坏、身份不一致、Claim行不全或语义状态不一致属于导入硬错误。派生的Claim总表会在CSV提交前预检；预检失败不得留下新的Faithfulness CSV记录或文章状态迁移。

这些只是兼容性和完整性校验，不是重新做语义评价。本Skill不得因为另一来源更有说服力而改写外部结论，也不得按月报、交接或历史比例需要调整审计器的主张边界。

不兼容时拒绝导入，任务继续等待外部Faithfulness结果，并明确指出不匹配项。

### unsupported归组处置文件

只要judgments含一个或多个`unsupported`，Codex必须在调用导入器前生成UTF-8 JSON，并用`--disposition <文件>`提交。该文件是语义分类的交接件，不是第五类台账；导入成功后由`50`提供人读结果。格式固定为：

处置JSON虽然使用英文机器字段名和分类枚举，但会直接进入`50`的人读内容。`topic`、`classification_basis`、`status`、`article_impact`、`handling`和`close_condition`必须填写中文人话；`next_owner`填写中文岗位名或`Codex`；`issue_key`和`entry`可保留ID、路径或URL。文章原句和来源证据仍保留原语言，不属于这些管理字段。导入器对上述人工字段执行中文门禁，不能用英文处置说明绕过。

```json
{
  "schema_version": "1.1",
  "article_id": "项目-ART-YYYYMMDD-001",
  "groups": [
    {
      "group_id": "UG-001",
      "claim_ids": ["C001", "C002"],
      "topic": "可复用的知识问题或内容主题",
      "category": "existing_gap | new_public_gap | cus | mat | anm | package_omission | writing_only",
      "classification_basis": "完成了哪些检测，为什么归到这里",
      "issue_key": "gap_key、CUS/MAT/ANM ID；package_omission和writing_only写空字符串",
      "status": "当前真实状态",
      "article_impact": "对本篇的影响",
      "handling": "已经完成或确定的处理",
      "next_owner": "下一责任人；无需动作写无",
      "entry": "现有事项或证据入口；writing_only可写无",
      "close_condition": "更新、关闭或重新评估条件",
      "scope_review": {
        "knowledge_question": "这一组能够由同一组证据回答的具体知识问题",
        "claim_matches": {"C001": "C001与该问题的具体关系", "C002": "C002与该问题的具体关系"}
      },
      "fact_check": {
        "contains_factual_judgment": true,
        "reusable_across_articles": true,
        "knowledge_domains": ["technical", "method"],
        "why_not_knowledge_issue": ""
      }
    }
  ]
}
```

`knowledge_domains`只使用：`none / customer_fact / technical / method / regulation_standard / safety_limit / detection_validity / procurement_selection / dynamic_fact / other_public_knowledge`。一组涉及多个领域时列多个值；`none`不能与其他值并存。

导入器执行以下硬校验：每个unsupported claim_id恰好出现一次；supported ID不得出现；`group_id`唯一；同一公共缺口`issue_key`在本篇只能有一个归组；分类和必填字段有效；人工管理字段包含中文人话；`existing_gap/new_public_gap`的`issue_key`已经存在于知识缺口CSV且关联当前文章ID，且当前状态不得为`已解决/已关闭`；处置中的`status`必须与缺口CSV当前状态完全一致，且人话字段不得引用另一个GAP-ID或把活动缺口写成已解决；`cus/mat/anm`的ID前缀正确，且现有项目台账中确有该ID。公共缺口组还必须提供一个具体的`scope_review.knowledge_question`和覆盖全部claim_id的`claim_matches`，逐条说明每条主张怎样落入同一个可由同组证据回答的问题。品牌、结构、材料、验证、物流或采购等多个维度可以共同构成同一方法问题；关键词数量、维度数量或Claim数量都不是拆组依据。只有主张实际需要不同证据问题、适用边界或解决范围时才拆组。若claim文本含客户名称、客户专属能力或`customer_fact`，不得归为`existing_gap/new_public_gap`，必须先走`package_omission/CUS/MAT/ANM`分流。机器校验只检查映射完整性，Codex仍须逐Claim核对语义，不能填批量模板。`package_omission`仅用于经核验的客户或公共正式知识确能覆盖当前主张但漏进`30`；公共知识须列具体且存在的Formal Claim ID，主题相近不够。没有unsupported时不需要本文件。校验失败时不得写指标、`50`、台账或完成文章迁移。

`writing_only`还执行独立硬门禁：`contains_factual_judgment`和`reusable_across_articles`都必须为`false`，`knowledge_domains`必须恰好为`["none"]`，`why_not_knowledge_issue`必须具体说明其纯结构、过渡、CTA、修辞或一次性观点作用。任一claim含事实而同组另有纯写作内容时必须拆组。法规、标准、认证、安全、限值、检测有效性、采购选型或动态事实的实质判断禁止归为`writing_only`；导入器对judgments原文中的明显高风险信号再做一层拒绝检查。其他类别必须至少声明“含事实判断”或“可跨文章复用”，且`knowledge_domains`不能为`none`。

新处置文件必须使用schema `1.1`。为兼容已经生成但尚未导入的旧结果，导入器只在schema `1.0`完全不含`writing_only`时接受；旧文件一旦使用`writing_only`就必须按`1.1`重新分类。

## 6. Claim文章支撑映射

对每条外部判定为supported的文章事实：

1. 读取其证据文件与行号；
2. 新格式中自动读取同目录`35_写作素材来源索引.md`，先校验文章ID和其中记录的`30` SHA-256，再按“写作素材到正式知识映射”表中的行范围映射正式Claim ID；旧混合格式`30`仅为兼容既有项目，仍可按其中显示的Claim ID块映射；
3. 写入20_Claim文章支撑记录.csv；
4. 无法确定时写未映射并保留证据定位。

不得按语义相似度猜Claim ID。新格式缺少`35`、哈希不匹配、映射行无效或文章ID不一致时拒绝导入并要求重建`30/35`文件对，不得把supported结果静默记成未映射。一篇文章可以关联多个正式Claim；同一正式Claim在单篇汇总中只计一次。

名称必须是Claim文章支撑记录，不是Claim实际调用记录。它证明事后证据支撑，不证明写作模型内部检索轨迹。

导入后重算`30_Claim文章支撑总表.md`。累计口径是当前有效结果中由某个Formal Claim支撑的不同文章ID数；同一文章多处出现、同一文章多个版本或重复导入不得重复计数。总表必须从正式知识文件的Claim标题或`Claim ID`元数据定位每个Claim，同时显示中文通俗标题、正式知识文件、支持文章数、最近支撑文章及日期和当前状态；不得因为Claim采用描述性标题就显示“未在正式知识目录定位”。无法定位真实Claim时导入失败或项目校验报错，不能把兜底语当成正常结果。

同一`audit_id`已经成功导入，且文章ID、文章版本、终稿SHA-256和知识文件SHA-256均一致时，重复提交必须作为幂等成功返回：不得重复写入指标或支撑记录、不得重复迁移文章任务、不得重复计数，也不得记录Faithfulness接入失败或改变接入状态。同一`audit_id`但上述输入身份不一致时才是结果冲突，必须拒绝导入并记录真实接口异常。

## 7. 缺失、失效与后续

结果缺失时不虚构分数，任务保持未完成，并在月度和交接审核中报告。受管 v0.6 审核成功后，Faithfulness返回`handoff_event: faithfulness_completed`；这只是结果交回知识库的中间事件，不是文章流程完成。知识库仍须导入结果、更新治理记录并把任务迁移到`40_已完成`，之后才返回`article_completed`。终稿解析后的正文内容发生实质修改前先归档修改前的完整文章版本，随后递增文章版本；仅换行、编码或表格边框等序列化变化不使结果失效，但项目校验保留格式变化警告。实质修改时旧结果保留历史并标记`superseded`，新当前版本必须重新审核。

unsupported只表示给定知识上下文没有支持该文章事实。它可能来自知识缺口、写作者使用了未交接来源、范围扩张或评价限制，不能自动判定为假。导入前按[知识缺口与CUS/ANM检测协议](governance-detection-and-lifecycle.md)对全部unsupported claim_id做穷尽且互斥的归组：每个ID恰好进入一组，优先匹配文章前已有事项，再判断资料包覆盖遗漏、CUS、MAT、ANM、公共知识缺口或无需治理的写作内容。不得按原子事实逐条建缺口；公共问题写入唯一`10_知识缺口记录.csv`并按不同文章ID去重。核心章节指删去后文章标题、主问题或一级/二级主要章节无法完成；高风险公共事实指法规、标准、认证、安全、限值、检测有效性、采购选型或随地区、时间变化的事实。纯过渡、结构、CTA、修辞、不可复用观点或非事实写作通过`writing_only`硬门禁后只记录排除理由。一般原理、行业常识、技术解释、方法判断和采购建议只要可以判断真假或跨文章复用，就不是纯写作内容，必须进入公共知识缺口、资料包覆盖遗漏或其他适用治理类别。

不得用终稿作为证据，也不得从终稿建立Claim。只有完成信号检测且理由明确时才建立后续：客户确认用CUS、复杂客户资料用MAT、冲突或危险范围扩张用ANM、公共事实先复查前五层再登记稳定`gap_key`。普通非关键公共问题首次仍为`观察中`；核心/高风险首次或第二篇不同文章重复时进入`待外部调研`。Faithfulness导入和登记完成后，新增`待外部调研`项进入独立知识维护队列；`观察中`不调研。`待外部调研`尚未有RES是正常状态，不能被报告为证据缺失、文章错误或导入失败；只有`部分解决`或`已解决`才必须关联RES。后续调研更新RES证据、正式公共Claim、缺口、覆盖视图、运行账本和`50`中的治理状态/回链；不得改变原Faithfulness判断、分数、哈希或当前`30/40`，也不自动改写文章。只有通过`writing_only`硬门禁的纯写作内容可以只记录排除理由。`50`必须逐组把分类、分类依据、关联事项/入口、当前处理和下一步拆列显示，不得把全部unsupported合并成默认“无后续动作”。
