# 官网画像与初始化状态回写

官网读取由 Codex 的浏览器或 HTTP 工具完成；`scripts/record_website_profile.py`不访问网络，只负责把已经核验的结果确定性写回项目。不要手工分别修改项目基础信息、当前待办、版本入口和运行账本。

主官网地址发生变化时，必须先运行`scripts/manage_project_websites.py update-primary`记录新旧地址和“待重新画像”，然后重新运行本文件规定的成功或失败回写命令。只更新URL而不执行画像回写属于未完成事务，不得关闭官网待办。

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

画像已经完成时，初始化待办关闭并进入“等待写作任务”；画像仍失败时，待办保留为不阻塞本地建库的“官网画像待重试”。项目启动、来源刷新、文章官网检索或月度审核发现官网恢复后，重新生成画像 JSON 并执行成功回写；脚本会清除过期失败状态并同步全部控制入口。每次成功/失败画像、来源索引、主官网变更和关联网站登记完成后，必须刷新`01_工作台/20_当前待办.md`。项目级收口由`scripts/todo_sync.py`执行；关联网站关系待确认或可访问性待检查时，网站ID必须在当前待办留下对应动作，直到核验完成。
