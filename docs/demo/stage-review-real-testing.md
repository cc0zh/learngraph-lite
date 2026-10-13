# 阶段总结与真实测试

当前停在“学习包生成与事件 HTTP”切片结束处。整体开发按用户要求暂停，等待阶段总结和真实测试；完整 P0/P1/M5 尚未验收。实现和验证证据集中维护在[执行计划](../exec-plans/active/learngraph-lite-implementation.md)，本次变更见[history](../histories/2026-10/20261013-2020-lesson-generation-http.md)。

## 可测试的能力与边界

| 范围 | 当前状态 |
| --- | --- |
| 独立 Agent 内核 | 原生工具回合、严格参数、共享调用预算、取消；无 token/context/deadline 完整预算 |
| 目标与图谱 | 目标确认、最多两轮澄清、资料型草稿生成、人工编辑和发布 HTTP |
| 节点学习 | 上下文、资料问答、引用定位、练习生成/作答、掌握度与下一步推荐 |
| 资料 | TXT/Markdown/文本型 PDF 上传、解析、绑定、jieba/FTS5 BM25；无 OCR |
| 学习包 | 固定四类组件、资料 grounding、公共题卡、包版本、列表/详情/引用、事件 ACK；request_explanation 仅记录 ACK |
| SQLite | 目标/当前图谱、资料、题目/成绩、学习包/事件可重开；session/run/root 仍在进程内 |
| 尚待后续 | 解释任务原子关联与 HTTP、session/run 恢复、提案 HTTP、React、浏览器 E2E、发布恢复/成绩迁移和 M5 真实评估交接 |

离线验证已通过104个Python、19个Node测试、20/20 fixture评估及三个fixture/demo命令。模型测试使用模拟gateway；不代表真实供应商兼容、生成质量或引用语义支持。真实调用本次未执行。关闭测试主动触发的graceful timeout/CancelledError、TestClient弃用提示与smoke终端中文乱码仍有记录。

## 先验证供应商和资料问答

使用支持 Chat Completions、function tool calling 和 max_tokens 的模型。配置只放当前终端环境变量；脚本使用真实请求，可能产生费用。

```powershell
$env:MODEL_API_KEY = '<你的 API Key>'
$env:MODEL_NAME = '<模型名>'
# 可选：$env:MODEL_BASE_URL = 'https://供应商地址/v1'
npm.cmd run smoke:real
npm.cmd run demo:learning-agent -- --real
```

第一条只验证普通回答与原生 echo 工具回合；第二条用fixture初始化的临时SQLite数据进行真实资料问答，不测试图谱、出题或学习包生成。成功后仍需下面的业务手测。

## 启动 API 并测试学习包

快速使用独立演示数据（数据库路径必须尚不存在）：

```powershell
npm.cmd run demo:learning-agent -- --database .local/stage-review.sqlite3
$env:LEARNGRAPH_DATABASE_PATH = '.local/stage-review.sqlite3'
npm.cmd run dev:api:real
```

这个初始化命令不调用供应商。浏览器打开 http://127.0.0.1:8000/docs；fixture API 的 dev:api 仅演示run协议，不能替代这个业务入口。也可按[README](../../README.md)创建自己的目标、生成并审核图谱、发布、上传并绑定真实资料。用自己的资料更能检验学习价值。

另开终端，生成不带题卡的学习包：

```powershell
$body = @{session_id='review-lesson'; request_id='lesson-1'; purpose='解释资料清洗与引用定位'; exercise_ids=@()} | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
  -Uri http://127.0.0.1:8000/api/goals/demo-goal/nodes/document-loading/lessons
curl.exe -N "http://127.0.0.1:8000/api/runs/$($run.run_id)/events"
$result = Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$($run.run_id)"
$result | ConvertTo-Json -Depth 30
```

只有 status=completed 才继续；失败时记录公开error、usage与模型配置（不含Key），检查输出截断/不兼容参数/schema修复等实际原因。生成不保证每次包含四类组件；schema允许空components，仅章节也有效。

```powershell
$package = $result.output.lesson
$url = "http://127.0.0.1:8000/api/goals/demo-goal/lessons/$($package.id)"
Invoke-RestMethod $url
Invoke-RestMethod http://127.0.0.1:8000/api/goals/demo-goal/nodes/document-loading/lessons
# 仅当包确实列出 C1 时执行。
Invoke-RestMethod "$url/citations/C1"
$event = @{event_id='read-1'; package_version=$package.version; component_id='chapter'; action='mark_read'; payload=@{}} | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $event -Uri "$url/events"
# 再发同一个 event，预期返回首次 ACK；该操作不调用模型、不计入成绩。
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $event -Uri "$url/events"
```

题卡测试：在OpenAPI先调用该节点的POST exercises，等待run完成，取公共题目ID放入POST lessons的exercise_ids，并使用新的session/request。检查quiz_choice只保存exercise_id，包与题目公共数据无答案；通过POST exercises/{id}/attempts提交自己的选项，反馈才包含答案/解析。不要假设真实题目的正确选项恒为b。通过GET context观察成绩，仅ACK不应改变成绩。

教学工具测试：POST sessions/{id}/runs，body带request_id、user_text、goal_id=demo-goal、node_id=document-loading、mode=teaching，明确要求先生成练习，再调用create_lesson引用该题。检查工具是否实际执行、run输出与usage；不要把模型口头声称“已生成”当作保存证据。

## 人工验收与记录

| 场景 | 检查结果 |
| --- | --- |
| 生成与来源 | 内容适合当前节点，引用原文实际支持相邻论点；general/documents标记准确，空召回明确失败 |
| 组件与题卡 | 无可执行字段、未知组件或内嵌答案；题卡ID能读取同节点当前版本题目 |
| 复用与版本 | 同session/request相同输入复用run；新request生成新包ID与递增version，旧包仍可读 |
| ACK与成绩 | chapter mark_read空payload；step_changed仅用于实际存在的stepper，step从0开始；ACK不变成绩 |
| 恢复与降级 | 重启后用package ID可读包/事件，旧run ID不可恢复；在独立测试资料上解绑/删除后引用定位409 |
| 真实内容质量 | 记录错误引用、无依据结论、题目歧义、组件重复与学习目标偏离；程序校验通过不代表内容合格 |

记录供应商、模型名、测试日期、非敏感配置、run/package ID、状态/usage和具体问题即可；区分真实调用与fixture数据，说明哪些业务未测。该阶段没有React页面，测试入口为OpenAPI、HTTP/SSE和命令行；暂缓事项不计作已完成。
