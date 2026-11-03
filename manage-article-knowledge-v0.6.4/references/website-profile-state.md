# 官网画像与初始化状态回写

官网读取由 Codex 的浏览器或 HTTP 工具完成；`scripts/record_website_profile.py`不访问网络，只负责把已经核验的结果确定性写回项目。不要手工分别修改项目基础信息、当前待办、版本入口和运行账本。

主官网地址发生变化时，必须先运行`scripts/manage_project_websites.py update-primary`记录新旧地址和“待重新画像”，然后无论成功还是失败都必须重新运行本文件规定的成功或失败回写命令。只更新URL而不执行画像回写属于未完成事务，不得关闭官网待办。

## 画像范围与项目基础信息

项目基础信息保留项目中英文名、运营组、内容运营负责人、官网、行业、目标市场与语言、客户原始资料路径、Obsidian项目路径和AI知识库专员，并保留其他企业相关网站的固定登记表。项目级`竞品信息限制`默认固定为“禁止搜索、保存或沉淀具体竞品品牌、型号、特殊产品、参数、价格、案例、排名和比较结论；仅允许保留去品牌化通用行业知识、一般原理、方法说明和公开标准”，文章只能继承或进一步收紧，不能放宽。

初始化或刷新时只要官网已知，必须先完成一次官网画像：读取官网首页、About/Company、产品或服务目录、Contact/Locations及可用站点地图，把官网明确写出的英文名称、行业/业务类别、主要业务与产品、网站实际使用语言和明确展示的市场/服务区域写回项目基础信息，并在“官网初步画像”中记录页面名称、具体URL、获取日期、原文依据和“官网明确/根据官网推定”。行业至少恢复v0.4的`Codex根据官网推定`路径；官网不足以判断的字段才写待补充并说明缺口。运营组、内容运营负责人、公开限制、竞品信息限制和AI知识库专员等官网不能证明的字段不得猜测。

官网或已登记关联网站暂时打不开时记录失败URL、时间、错误层级和重试条件，但不得把失败写成永久“网站不存在”；若因登录、验证码、权限、反爬、付费墙或内容读取限制无法完成检索，必须在对话中向内容运营明确说明失败层级并请求访问授权、登录态、白名单、导出文件或可访问镜像，请求解决前保持“无法访问/待重试”，不得写成“官网未命中”。

## 成功回写

把核验结果保存为临时 UTF-8 JSON。四个字段必须全部存在；官网不足以判断时，`value`明确写`官网不足以判断`，`judgment`写`官网不足`，不得用外部常识补齐。

```json
{
  "profiled_at": "2026-09-09",
  "website_status": "可访问",
  "fields": {
    "项目英文名称": {
      "value": "Example Company",
      "source": "About；https://example.com/about",
      "evidence": "页面明确显示的名称",
      "judgment": "官网明确",
      "boundary": "不证明法定注册名称"
    },
    "行业或业务类别": {
      "value": "示例制造业",
      "source": "About；https://example.com/about",
      "evidence": "页面对业务的原文描述",
      "judgment": "根据官网推定",
      "boundary": "不替代行业分类人工决定"
    },
    "主要业务与产品": {
      "value": "官网明确展示的业务和产品",
      "source": "Products；https://example.com/products",
      "evidence": "产品目录原文",
      "judgment": "官网明确",
      "boundary": "只保留官网展示范围"
    },
    "市场、服务区域与网站语言": {
      "value": "网站为英语；未明确具体服务区域",
      "source": "Home；https://example.com/",
      "evidence": "页面实际语言；官网未列出服务国家",
      "judgment": "官网明确",
      "boundary": "不推定销售国家或客户覆盖"
    }
  }
}
```

画像完成后立即运行：

```text
scripts/record_website_profile.py --project <Obsidian项目路径> --status success --profile-file <临时画像JSON> --local-build-status auto
```

`auto`以`02_源资料/source-index.sqlite`是否已经建立判断本地建库状态。若来源索引尚未完成，当前待办会推进为“来源索引与项目校验”，不会错误宣告完整初始化完成。

## 失败回写

官网暂时失败时立即运行：

```text
scripts/record_website_profile.py --project <Obsidian项目路径> --status failed --failure-stage <DNS/连接/HTTP/页面读取/内容不足> --error <错误摘要> --retry-when <恢复条件> --local-build-status auto
```

脚本保留官网 URL 和已有画像字段，写入失败层级、时间、错误摘要和重试条件。失败事件以`partial`状态进入项目运行账本，表示官网子步骤失败而非整轮建库失败；本地来源索引继续执行。

## 来源索引后的收口

来源台账、SQLite、覆盖视图和项目校验完成后运行：

```text
scripts/record_website_profile.py --project <Obsidian项目路径> --status reconcile --local-build-status complete
```

画像已经完成时，初始化待办关闭并进入“等待写作任务”；画像仍失败时，待办保留为不阻塞本地建库的“官网画像待重试”。项目启动、来源刷新、文章官网检索或月度审核发现官网恢复后，重新生成画像 JSON 并执行成功回写；脚本会清除过期失败状态并同步全部控制入口和受影响对象，失败事件仍保留在运行账本。每次成功/失败画像、来源索引、主官网变更、关联网站登记或其他项目级维护事务完成后，必须调用`scripts/todo_sync.py`刷新`01_工作台/20_当前待办.md`；待办只保留当前仍需动作的事项，完成事项必须收口，禁止只更新基础信息或覆盖页而留下旧阶段描述。关联网站登记后必须继续核验关系和可访问性；补充项目文件按[来源索引与复杂资料](source-index-and-materials.md)的增量维护完成条件执行。关联网站关系待确认或可访问性待检查时，网站ID必须在当前待办留下对应动作，直到核验完成。
