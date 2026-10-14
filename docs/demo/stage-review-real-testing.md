# 阶段总结与真实测试

## P0 基线收口

本轮已隔离缺配置测试对项目 `.env` 的读取，新增临时配置与进程变量优先级回归，并修复未确认请求/刷新竞态、超长 session、规划未保存编辑和 Markdown 图片外连。当前离线基线复验为 119 Python、19 Node、web build、11 P0 E2E、20/20 fixture 和仓库检查通过；真实供应商与真实 P0 验证单独记录在[执行计划](../exec-plans/active/learngraph-lite-implementation.md)文首。

React P0 主要流程已实现并有 fixture 验收。P0 的实现与验证证据集中维护在执行计划；本轮变更见[history](../histories/2026-10/20261013-2115-react-p0.md)。P1 资料原文页、学习包固定组件前端、提案 HTTP/前端与 M5 完整真实评估/最终交接未完成。

## 可测试的能力与边界

| 范围 | 当前状态 |
| --- | --- |
| 独立 Agent 内核 | 原生工具回合、严格参数、六次共享模型调用/八步/十二次工具调用；12,000 估算输入 token 上限与 120 秒协作 deadline 已具备，无硬中断/独立 tool timeout/完整累计 token 预算 |
| 目标与图谱 | 目标确认、最多两轮澄清、资料型草稿生成、人工编辑和发布 HTTP |
| 节点学习 | 上下文、资料问答、引用定位、练习生成/作答、掌握度与下一步推荐 |
| 资料 | TXT/Markdown/文本型 PDF 上传、解析、绑定、jieba/FTS5 BM25；无 OCR |
| 学习包 | 后端固定四类组件、资料 grounding、公共题卡、包版本、列表/详情/引用、事件 ACK 与解释 HTTP；ACK 与解释请求分开，React 固定组件与事件交互未完成 |
| SQLite | 目标/当前图谱、资料、题目/成绩、学习包/事件，以及 real API 的 session作用域/run/root/输入/结果/事件可重开；未完成run转interrupted |
| P0 浏览器验收 | 上轮 React fixture 主流程：目标创建→澄清→确认→图谱生成/编辑/发布→节点流式对话→按钮练习作答→反馈→刷新恢复→停止/重试；375/768/1024/1440 响应式。对话实际工具出题与模型失败/显式重试为本轮补测，2 E2E 已通过；失败场景用 mock DTO，仅证明 UI/重试协议 |

模型协议测试使用 MockTransport，失败/重试与部分浏览器边界使用 mock DTO，浏览器主闭环使用 fixture；这些离线证据不代表真实供应商兼容、生成质量或引用语义支持。新增回归覆盖未送达/响应丢失、同 ID 恢复、查询门禁、旧历史竞态、422/409解锁、超长节点和 dirty 编辑；真实验证另列，不混算到11个离线 E2E。

## 先启动业务 UI（无需 Key）

运行 `npm run dev`（Windows 可用 `npm.cmd run dev`），打开 <http://127.0.0.1:5173>。它同时启动 Vite 和 SQLite 业务 fixture API，页面必须标记 fixture；独立 `npm run dev:api` 仅演示 echo run 协议，不提供业务 UI 验收。配置好下面的真实模型变量后，可用 `npm run dev -- --real` 启动付费真实业务 UI；真实供应商尚未验证。

本轮浏览器补测重点：节点聊天 body 使用 mode: teaching，界面恢复 teaching 会话；要求出题后检查实际 create_exercise 工具活动和已保存题目，不接受仅口头答复；模型失败时明确显示 failed，并用新 request_id、原 retry_of_run_id/session/输入显式重试，刷新后仍能看到教学对话与题目/反馈。专项结果已记入计划；失败场景使用 mock 失败/完成 DTO，不等价于真实模型证据，其余验收仍待补录。

按 session、同 mode 恢复 completed 回合的完整协议历史；不是只保存最终文本，也不恢复半截流。最近运行窗口和 12k 估算输入预算限制模型输入，裁剪按完整用户回合进行。120 秒 deadline 只在协作检查点阻止继续，不能硬打断阻塞工具/网络；供应商 timeout 与单次输出上限不等于完整 run token/time 硬预算。

## 先验证供应商和资料问答

使用支持 Chat Completions、function tool calling 和 max_tokens 的模型。配置只放当前终端环境变量；脚本使用真实请求，可能产生费用。

```powershell
$env:MODEL_API_KEY = '<你的 API Key>'
$env:MODEL_NAME = '<模型名>'
# 可选：$env:MODEL_BASE_URL = 'https://供应商地址/v1'
npm.cmd run smoke:real
npm.cmd run smoke:p0:real
npm.cmd run demo:learning-agent -- --real
```

第一条只验证普通回答与原生 echo 工具回合；第二条使用全新独立 SQLite 验证真实 P0 HTTP 旅程（最多12次模型请求，报告默认留在 `.local`，不进入默认 CI）；第三条用 fixture 初始化的临时 SQLite 数据进行真实资料问答，不测试图谱、出题或学习包生成。P0 HTTP 不等于真实浏览器 E2E，也不包含 P1 引用/学习包质量；成功后仍需下面的业务手测。

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

## 测试解释与重启恢复

沿用上面的 `$package` 和 `$url`，先保存章节解释事件，再请求解释。解释 body 不包含 user_text；服务端使用第一次 ACK 保存的事件和包内容。

```powershell
$event = @{event_id='explain-event-1'; package_version=$package.version; component_id='chapter'; action='request_explanation'; payload=@{}} | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $event -Uri "$url/events"
$explanationBody = @{request_id='explain-1'; mode='explanation'; goal_id='demo-goal'; node_id='document-loading'; source_event_id='explain-event-1'; explanation_slot='initial'}
$json = $explanationBody | ConvertTo-Json
$explanation = Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $json `
  -Uri http://127.0.0.1:8000/api/sessions/review-explanation/runs
curl.exe -N "http://127.0.0.1:8000/api/runs/$($explanation.run_id)/events"
Invoke-RestMethod http://127.0.0.1:8000/api/sessions/review-explanation/runs
# 同事件/slot换request ID，预期复用最近attempt，不增加供应商调用。
$explanationBody.request_id = 'explain-duplicate'
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body ($explanationBody | ConvertTo-Json) `
  -Uri http://127.0.0.1:8000/api/sessions/review-explanation/runs
```

重启同一数据库的 API，GET 原 run 与 SSE 应显示保存的结果，重复提交应继续复用。正常 Ctrl+C 会协作取消未完成任务；要验证 interrupted，需在独立测试数据库的 run 为 queued/running 时让该 API 进程意外退出，再启动同一数据库。启动后检查状态为 interrupted、事件包含 run.interrupted，且供应商请求数量没有因启动增加。同一数据库不要并行启动两个 API。

仅当最近 attempt 为 failed/cancelled/budget_exceeded/interrupted 时显式重试：

```powershell
$explanationBody.request_id = 'explain-retry-1'
$explanationBody.retry_of_run_id = $explanation.run_id
$retry = Invoke-RestMethod -Method Post -ContentType 'application/json' -Body ($explanationBody | ConvertTo-Json) `
  -Uri http://127.0.0.1:8000/api/sessions/review-explanation/runs
$retry | ConvertTo-Json -Depth 20
```

重试产生新 run ID，root_task_id 保持最初 run ID；如果已完成则拒绝重试。要解释新的交互内容，先保存新事件，或去掉 retry_of_run_id、换 explanation_slot 和 request_id 创建新任务。原始 request ID 始终指向原 attempt；额外重复 request ID 不保存别名。stepper 测试必须使用实际组件 ID 和有效 step_changed payload；quiz_choice 解释只输入公共题干/选项，检查是否出现未作答答案泄漏或错误讲解。将这些内容质量问题记录为真实测试结果。

## 人工验收与记录

| 场景 | 检查结果 |
| --- | --- |
| 生成与来源 | 内容适合当前节点，引用原文实际支持相邻论点；general/documents标记准确，空召回明确失败 |
| 组件与题卡 | 无可执行字段、未知组件或内嵌答案；题卡ID能读取同节点当前版本题目 |
| 复用与版本 | 同session/request相同输入复用run；新request生成新包ID与递增version，旧包仍可读 |
| ACK与成绩 | chapter mark_read空payload；step_changed仅用于实际存在的stepper，step从0开始；ACK不变成绩 |
| 解释与重试 | 同事件/slot只执行一次；失败需显式retry，root不变；新slot新任务，换session冲突，客户端user_text被拒绝 |
| 恢复与降级 | 重启可读包/事件/旧run/SSE，未完成run转interrupted且不自动调用模型；在独立测试资料上解绑/删除后引用定位409 |
| 真实内容质量 | 记录错误引用、无依据结论、题目歧义、组件重复与学习目标偏离；程序校验通过不代表内容合格 |

记录供应商、模型名、测试日期、非敏感配置、run/package ID、状态/usage和具体问题即可；区分真实调用与 fixture 数据，说明哪些业务未测。React P0 的自动化入口是 npm.cmd run test:e2e，真实业务内容仍以 OpenAPI/HTTP/SSE 和人工检查为准；fixture E2E 不等价于真实模型验收。
