# Faithfulness结果交接规范

## 1. Skill边界

Faithfulness由独立文章审核Skill产生。本Skill不抽取文章原子事实、不判断supported或unsupported，也不生成其审核报告，只验证并导入结果。

除非结果确由官方DeepEval运行并清楚标识，否则评价模式必须写：DeepEval Faithfulness 规则复现（Codex 评审，非 DeepEval 官方运行）。

## 2. 审核上下文

标准manage-article-knowledge v0.5模式只使用实际交给写作Codex的`30_本篇知识库资料.md`。随文事实文件必须先进入来源层、Formal Claim和`30/35`，不能作为平行知识文件直接加入审核。写作要求、SEO/GEO、风格和结构参考不是事实证据。`35`只供知识库追溯和导入后的确定性映射，绝不能加入Faithfulness retrieval context；否则结果会因为使用了写作时不可见的证据而虚高。

不能因为资料包链接了知识库，就把整个知识库放入retrieval context。写作提示、SEO/GEO规则和文章评价指令都不是证据。`30`中的直接写作事实、英文表达、控制、建议、缺口处理和审计说明都不是可引用的正向证据；审核Skill只提取第一至第三节中明确标明为“证据正文”的连续来源正文或已核验目标语言翻译。直接写作事实可以指导作者，但外部审核的证据引文必须落在对应证据正文。

Faithfulness只报告“终稿事实被实际交付事实附件支持的比例”。它不是SEO/GEO质量、搜索表现、可发布性、文风或模型能力的总分，不设置100%门槛，也不要求每句话都有附件证据。模型可以为文章完整性补充行业常识、一般原理、解释、结构和过渡；这些内容若没有进入事实附件，可能被标为`unsupported`，但仅表示本次上下文未覆盖，不能单独视为写错或要求重写。单篇结果用于记录本次覆盖，并在完成本地检索后触发轻量公共知识缺口登记：核心章节或高风险公共事实首次出现即进入`待外部调研`；普通公共知识首次为`观察中`，第二个不同文章ID出现时升级。客户专属、未处理本地资料和来源异常仍分别进入CUS、MAT、ANM，不由外部调研替代。

## 3. 可接收文件

当前deepeval-article-audit可交接：文章ID-prepared.json、文章ID-judgments.json和faithfulness_summary.md。详细Markdown和HTML仍由审核Skill管理，不是知识台账导入必需文件。

judgments中的claim_id，例如C001，是文章原子事实ID，不是正式知识Claim ID。

## 4. 结果取得方式

支持两种等价入口：内容运营提交本篇审核结果的具体文件或专属目录；或者在`50`中登记本篇受管审核结果目录，由Codex后续读取。推荐目录为`D:\article-faithfulness-audits\[项目短码]\[文章ID]\v[文章版本]\`，其中保存当前版本的prepared、judgments和summary。

不得递归扫描用户文档、下载目录或整个审核根目录来猜测结果。目录必须精确对应本篇文章版本；目录缺文件、存在多个无法唯一判断的候选版本或哈希不一致时，`50`保持`等待Faithfulness结果`并写明原因。读取目录不等于无条件导入，仍须通过下面的版本、内容和哈希校验。内容运营不需要重复提交终稿，也不需要再说“继续”。

## 5. 导入校验

导入前验证：

1. prepared和judgment schema受支持；
2. 文章ID一致；
3. verdict只含supported或unsupported；
4. supported判断含证据；
5. prepared中的文章内容仍与40_最终文章.md一致；
6. prepared中的知识块仍与实际资料文件一致；
7. summary的计数和百分比与judgments一致；
8. 保存文章和当前`30`的SHA-256，并确认prepared中只有这一个manage-v0.5事实输入。

这些只是兼容性和完整性校验，不是重新做语义评价。本Skill不得因为另一来源更有说服力而改写外部结论。

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

导入器执行以下硬校验：每个unsupported claim_id恰好出现一次；supported ID不得出现；`group_id`唯一；分类和必填字段有效；人工管理字段包含中文人话；`existing_gap/new_public_gap`的`issue_key`已经存在于知识缺口CSV且关联当前文章ID；`cus/mat/anm`的ID前缀正确，且现有项目台账中确有该ID；资料包覆盖遗漏必须写具体分类依据。没有unsupported时不需要本文件。校验失败时不得写指标、`50`、台账或完成文章迁移。

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

## 7. 缺失、失效与后续

结果缺失时不虚构分数，任务保持未完成，并在月度和交接审核中报告。终稿任何修改前先归档修改前的完整文章版本，随后递增文章版本；旧结果保留历史并标记`superseded`，新当前版本必须重新审核。

unsupported只表示给定知识上下文没有支持该文章事实。它可能来自知识缺口、写作者使用了未交接来源、范围扩张或评价限制，不能自动判定为假。导入前按[知识缺口与CUS/ANM检测协议](governance-detection-and-lifecycle.md)对全部unsupported claim_id做穷尽且互斥的归组：每个ID恰好进入一组，优先匹配文章前已有事项，再判断资料包覆盖遗漏、CUS、MAT、ANM、公共知识缺口或无需治理的写作内容。不得按原子事实逐条建缺口；公共问题写入唯一`10_知识缺口记录.csv`并按不同文章ID去重。核心章节指删去后文章标题、主问题或一级/二级主要章节无法完成；高风险公共事实指法规、标准、认证、安全、限值、检测有效性、采购选型或随地区、时间变化的事实。纯过渡、结构、CTA、修辞、不可复用观点或非事实写作通过`writing_only`硬门禁后只记录排除理由。一般原理、行业常识、技术解释、方法判断和采购建议只要可以判断真假或跨文章复用，就不是纯写作内容，必须进入公共知识缺口、资料包覆盖遗漏或其他适用治理类别。

不得用终稿作为证据，也不得从终稿建立Claim。只有完成信号检测且理由明确时才建立后续：客户确认用CUS、复杂客户资料用MAT、冲突或危险范围扩张用ANM、公共事实先复查前五层再登记稳定`gap_key`。普通非关键公共问题首次仍为`观察中`；核心/高风险首次或第二篇不同文章重复时进入`待外部调研`。Faithfulness导入和登记完成后，只对未被本篇禁止的新增`待外部调研`项执行独立知识维护；`观察中`不调研。后续调研更新RES证据、正式公共Claim、缺口、覆盖视图、运行账本和`50`中的治理状态/回链；不得改变原Faithfulness判断、分数、哈希或当前`30/40`，也不自动改写文章。只有通过`writing_only`硬门禁的纯写作内容可以只记录排除理由。`50`必须逐组把分类、分类依据、关联事项/入口、当前处理和下一步拆列显示，不得把全部unsupported合并成默认“无后续动作”。
