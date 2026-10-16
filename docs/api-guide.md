# 本地 API 与调用示例

本文承接 [README](../README.md) 的接口与高级操作细节，不维护阶段测试计数。当前质量状态见[质量与验收](QUALITY_SCORE.md)，真实测试步骤见[测试指南](demo/stage-review-real-testing.md)。运行前先完成 README 的依赖安装。业务接口的完整 schema 以服务启动后的 <http://127.0.0.1:8000/docs> 为准。

> 下文手工节点 run 示例是兼容 session 接口，不会创建工作台会话元数据；工作台会话接口另见下一节。业务 fixture 与 real 都提供业务接口，独立 echo fixture 只演示 run 协议。

## 工作台目标与会话

工作台通过 `POST /api/workbench/goals` 使用客户端 UUID 幂等创建目标，再以独立 request_id 发起规划；创建本身不调用模型。`GET /api/conversations` 读取会话目录，`POST /api/conversations` 创建带固定类型及目标/节点作用域的会话，`GET /api/conversations/{session_id}` 恢复元数据。节点学习会话使用 teaching，兼容 runner 续聊保持原模式。浏览其他节点不修改会话作用域；教材、题目和成绩按节点共享，transcript 不合并。请求字段、幂等冲突与状态以 OpenAPI 和[架构说明](ARCHITECTURE.md)为准。

## 启动独立 echo fixture API

Windows PowerShell：

```powershell
npm.cmd run dev:api
```

macOS/Linux：

```bash
npm run dev:api
```

服务绑定 `127.0.0.1:8000`，OpenAPI 交互文档在 <http://127.0.0.1:8000/docs>。`GET /api/model/status` 明确返回 `mode: fixture`、`configured: false`；此入口使用确定性演示模型，不调用供应商。

在另一个 PowerShell 终端提交并查询一次 run：

```powershell
$body = @{request_id='demo-1'; user_text='开始学习'} | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
  -Uri http://127.0.0.1:8000/api/sessions/demo/runs
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$($run.run_id)"
curl.exe -N "http://127.0.0.1:8000/api/runs/$($run.run_id)/events"
```

提交返回 202；同 session/request_id 和相同输入复用原 run，不同输入返回 409。停止使用 `POST /api/runs/:id/cancel`。同 session 只允许一个正在执行的 run，全应用最多两个。取消会结束公开状态；阻塞调用实际退出前仍占用名额。关闭入口给活跃 HTTP/SSE 连接最多 2 秒结束，再进入应用协作取消并等待后台调用退出。

HTTP 只接受 localhost、127.0.0.1 和 ::1 的 Host；浏览器写请求必须同源。没有 Origin 的本地命令行请求可用。React 前端通过 Vite 代理同源调用；当前不启用跨源访问。

SSE 首帧为 `run.snapshot`，随后接收有界 token/tool 状态和生命周期事件；事件带递增 cursor，重连可按 cursor 补发缺口并获取当前快照。连接断开不取消任务。fixture API 使用内存运行状态，业务 fixture 入口使用 SQLite；real API 持久化运行状态与 session 作用域。

## 启动真实模型 API

使用独立入口，后端从当前进程环境变量和项目根目录 `.env` 读取配置；进程环境变量优先，缺少 Key 或模型名时启动失败。`.env` 不提交 Git。先完成 [README](../README.md) 的依赖安装，再编辑 `.env`：

```dotenv
MODEL_API_KEY=<你的 API Key>
MODEL_NAME=<支持 Chat Completions 和 function tool calling 的模型名>
# 可选：MODEL_BASE_URL=https://供应商地址/v1
```

另在终端执行：

```powershell
npm.cmd run dev:api:real
```

macOS/Linux 对应设置 `export MODEL_API_KEY='...'` 和 `export MODEL_NAME='...'`，然后运行 `npm run dev:api:real`。`OPENAI_API_KEY` 可作为 Key 备用变量；`MODEL_BASE_URL` 未设置时使用 SDK 默认 OpenAI endpoint。`MODEL_TIMEOUT_SECONDS` 默认 30 秒，为 SDK 网络操作超时，并非整个 run 的硬截止时间；`MODEL_MAX_OUTPUT_TOKENS` 默认 4096，经 `max_tokens` 传递，给结构化图谱更多输出空间。历史三节点真实 P0 样例在该上限通过；更多节点、资料型生成或较长解释仍需验证，截断会记录为失败。仅支持接受该参数的 Chat Completions 模型；不宣称所有兼容 endpoint 或模型均可用。

real API 使用相同的提交/查询/SSE 路径，`/api/model/status` 返回 `mode: real`、`configured: true`，只表示配置已装配，不表示供应商连通或认证成功。不带目标/节点的请求使用普通回答与协议验证 `echo`；带作用域的请求装配节点上下文，注册 `get_learning_context`、`get_next_action`、`search_documents` 和 `read_document_chunk`。SDK 隐式重试关闭，应用关闭会先等待工作线程退出再关闭客户端；fixture API 仍只用于协议演示。

real API 将请求输入、session 作用域、root task、结果/usage 与递增事件保存到同一 SQLite。`GET /api/sessions/{session_id}/runs` 可查询该会话的运行记录，旧 run ID 在重启后仍可查询并获取 SSE 快照。启动把遗留 queued/running 标为 interrupted，不自动重新调用模型；显式 retry 使用新 request_id 和原 retry_of_run_id，并保持原 session、作用域与输入。已完成任务不能 retry。节点对话按同 session、同 mode 恢复已完成回合的完整 user/assistant/tool 协议历史；仅取最近运行窗口并按输入预算裁剪，不自动续跑未完成任务。同数据库只支持一个 API 进程。

配置完成后可手动运行 `npm.cmd run smoke:real`（macOS/Linux 使用 `npm run smoke:real`）。它会产生真实 API 请求和费用，依次验证普通回答、原生 echo 调用及工具结果后的回答；不进入默认 CI。2026-10-14 曾在 DeepSeek/deepseek-flash 执行并通过（历史协议证据）；离线 SDK 测试不能替代真实证据，该结果也不保证所有配置/供应商兼容。

供应商协议通过后，可用 `npm.cmd run smoke:p0:real` 验证一条真实 P0 HTTP 旅程：澄清、确认、三节点图谱生成/人工编辑发布、教学工具出题、正式作答/掌握度/推荐、按钮出题、请求/交卷去重和 SQLite 重开。它实际调用模型，整条旅程最多12次请求；使用新建 `.local/real-p0-*.sqlite3`，不修改日常数据库，重开阶段禁止模型调用。脱敏 JSON 证据在 `.local/real-p0-*.json`，不保存 Key 或模型原文。可传 `-- --database .local/my-real-p0.sqlite3 --report .local/my-real-p0.json`，已有文件会拒绝覆盖。旧版本教学输入明确指定工具名和参数，当前已改为自然需求但未真实复验；历史通过不能证明自主工具选择。此入口不是浏览器 E2E，也不是生成质量/稳定性评估。

`npm.cmd run smoke:p0:browser:real` 是**付费opt-in**：Playwright/Chromium从默认工作台输入点击完成 P0，不预置接口结果、不mock模型、不自动重跑。自然目标/出题输入版已实际完成一次真实小样本；链路断言通过，人工审查仍发现答案提前提示、概念错误与自由回复露出内部名，不记教学质量合格。最新结果与旧受提示样本的限制见[质量与验收](QUALITY_SCORE.md)。固定8010/5183，新建`.local/p0-browser-real-*.sqlite3/json`，拒绝已有数据库，全旅程最多14次真实请求。JSON记录ID/状态/工具名/usage/provider host；失败断言可能含模型文本差异，原报告与截图/trace/数据库都留本地不提交，只发布脱敏摘要。默认CI/E2E不执行此入口，P1真实语义质量须另评估。

## 复现节点学习 Agent

无需 Key 的 SQLite 演示：

```powershell
npm.cmd run demo:learning-agent
```

脚本创建临时数据库，确认 fixture 目标、发布 8 节点图谱并记录 3 次示例作答，绑定一份资料清洗笔记。随后通过原生工具协议读取上下文、十分钟下一步推荐，检索并读取资料片段，生成带 `[C1]` 的回答及来源表，演示空召回，再完成按钮/教学工具出题、提交答案和推荐闭环。输出标记 `mode: fixture` 和 `data: fixture-seeded SQLite`。这验证应用调用链，不代表真实模型能力；演示输出的 `validation_scope: call-and-completion-demo`、`quality_assessed: false` 也适用于 `--real`，完成状态不是检索或语义支持验收。

要把演示数据留给 real API，先使用一个尚不存在的数据库文件：

```powershell
npm.cmd run demo:learning-agent -- --database .local/learning-demo.sqlite3
$env:LEARNGRAPH_DATABASE_PATH = '.local/learning-demo.sqlite3'
npm.cmd run dev:api:real
```

脚本拒绝覆盖已有文件。real API 默认数据库为 `.local/learngraph.sqlite3`；启动仅初始化表，不创建目标或重置成绩。可通过下述规划 HTTP 创建自己的目标，也可用上述脚本初始化独立演示数据。

服务启动后读取上下文并提交节点请求：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/goals/demo-goal/nodes/document-loading/context
Invoke-RestMethod 'http://127.0.0.1:8000/api/goals/demo-goal/nodes/document-loading/next-action?available_minutes=10'
$body = @{request_id='node-1'; user_text='解释当前节点，并给我十分钟下一步建议'; goal_id='demo-goal'; node_id='document-loading'} | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
  -Uri http://127.0.0.1:8000/api/sessions/node-demo/runs
curl.exe -N "http://127.0.0.1:8000/api/runs/$($run.run_id)/events"
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$($run.run_id)/citations/C1"
```

`goal_id` / `node_id` 必须一起提供，同 session 绑定同一个目标/节点；换节点需新 session。上下文包含已确认目标、发布版本、当前节点、直接前置依赖与练习表现，不包含私有答案。推荐针对整个目标，使用已有服务端规则；`available_minutes` 可省略，提供时必须为正整数。节点不存在返回 404，未发布/未初始化/版本过期的只读请求返回 409；run 内装配失败记录为 `failed`。只读请求不重置成绩；提案接受显式原子迁移，语义/依赖改变全局内容版本，priority/minutes只改计划版本。

每轮独立装配工具与上下文，工具参数不接受目标/节点改写。资料只检索当前目标和节点均显式绑定的文档；`read_document_chunk` 只接受本轮检索返回的 `citation_id`。默认 `mode: runner` 使用只读工具，real API 的显式 `mode: teaching` 增加 `create_exercise`、`create_lesson` 和 `propose_graph_change`。同 session、同 mode 的 completed 回合可恢复完整协议历史（保留 assistant tool_calls/tool_call_id 配对），失败、取消或未完成回合不纳入下一轮历史；模型输入会裁剪最旧的完整回合。可手动使用 `npm.cmd run demo:learning-agent -- --real` 调配置好的供应商，可能产生费用，业务数据仍是 fixture；真实模式只执行资料问答，本次未执行。

完成的节点回答在 GET run 与 SSE 中返回 `output.citation_map` 和 `output.unverified_citation_ids`。C1 等编号仅在本轮有效，来源记录含文档/片段 ID、版本、引用位置、内容摘要值、是否被引用及 `valid/stale/unavailable` 状态。未知编号保留为未验证，不提供来源；引用原文接口未知返回 404，内容变化或解绑返回 409。上面原文命令仅在本轮确实返回 C1 时可用。GET run 保留完成时快照，点击原文重新校验当前绑定和内容；无绑定/空召回要求明确说明资料不足，普通知识解释标注“非基于上传资料”。

当前检索使用 jieba search 分词和 SQLite FTS5 BM25，默认 top 5、每块最多 320 字符；分值用于排序，不是可信度。来源有效性只证明片段可定位，不证明原文支持回答语义；旧 upload_text 同版本覆盖通过片段摘要值和位置检测失效。HTTP 上传文件内容固定为 revision 1，重试不变更内容；更新资料需重新上传、重新绑定。React原文页已实现，完整资料版本历史仍未实现。

## 上传资料与检索

以下接口由real和业务fixture API装配，但上传、解析和直接搜索不调用模型。支持 UTF-8/BOM TXT、Markdown 和文本型 PDF，最多 10 MB、100 页、200,000 字符。PDF 使用 pypdf；解析在有 20 秒超时的子进程执行，最多两个同时解析、四个活动或排队任务。Markdown 按 ATX 标题切块，代码围栏内的 `#` 不作为标题；PDF 保留页码。原 bytes、状态、文本、chunk 和哈希保存在本地 SQLite 中，文件名只展示，上传接口不接收服务端路径。

PowerShell 示例（已有目标 demo-goal 和节点 document-loading）：

```powershell
# 把 .\notes.md 替换为自己的 UTF-8 文件。
$doc = curl.exe -s -F 'file=@notes.md' http://127.0.0.1:8000/api/documents | ConvertFrom-Json
Invoke-RestMethod "http://127.0.0.1:8000/api/documents/$($doc.document_id)"
# 等 GET 状态为 ready 后，查看原文并分别绑定目标和节点。
Invoke-RestMethod "http://127.0.0.1:8000/api/documents/$($doc.document_id)/chunks?offset=0&limit=50"
$binding = @{document_id=$doc.document_id} | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $binding `
  -Uri http://127.0.0.1:8000/api/goals/demo-goal/document-bindings
$binding = @{document_id=$doc.document_id; node_id='document-loading'} | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $binding `
  -Uri http://127.0.0.1:8000/api/goals/demo-goal/document-bindings
$query = @{query='检索'; node_id='document-loading'; limit=5} | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($query)) `
  -Uri http://127.0.0.1:8000/api/goals/demo-goal/document-search
```

上传返回 202，状态依次为 uploaded、parsing，终态为 ready/failed/unsupported。扫描 PDF 为 unsupported/needs_ocr；加密、坏 PDF、坏编码和不可读文本也明确拒绝，不支持 OCR、Office 文件。重启把未完成解析标为 failed/interrupted；`POST /api/documents/{id}/reparse` 复用原文件，ready 时返回已有结果。解析成功状态与全文/chunk/FTS 在同一事务提交，只有 ready 上传可检索。

`DELETE /api/goals/{goal_id}/document-bindings` 使用相同 JSON body 解绑；解绑目标也移除它的节点绑定。`DELETE /api/documents/{id}` 删除原文件、索引及所有绑定，晚到解析结果不会恢复已删除资料，历史来源点击降级为 unavailable。chunk 接口每页最多 50 块，返回页码或 heading、原文 offsets 和 SHA256；节点 Agent、图谱、练习和学习包复用这些资料，各自保存来源表。React「我的资料」已实现；GET /api/documents?offset=0&limit=50 读取持久列表，GET /api/documents/{id}/bindings 与 GET /api/goals/{goal_id}/document-bindings?node_id=... 读取关联和显式绑定。

启动必须有 SQLite FTS5。若报错 `SQLite FTS5 is required`，安装 Python 3.13+ 的官方发行版（含 FTS5）并用该解释器重新创建项目虚拟环境、执行 `uv sync --locked --group dev`；可用 `uv run --locked python -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table probe using fts5(text)'); print('FTS5 OK')"` 验证。当前解析恢复按单个 API 进程使用同一数据库设计。

## 目标澄清与图谱规划

默认 UI 从一句意图开始，由专用规划 Agent 主导连续对话：先提取已知信息，再按需发出最多三题的动态问题卡，或直接提出目标审核卡；支持选项、自定义、跳过及提问理由。问题回答保留原问题 ID，与目标修改一起进入当前会话的有限协议历史。发问和目标审核后由程序结束本轮，不占用运行名额等待用户。

目标摘要区分用户自述与默认假设，可就地修改。点击「确认目标并生成图谱」先明确确认，再授权 Agent 推进生成；模型无确认/发布工具。路线按依赖顺序展示成果、必要性和预计投入。用户可在同一对话中追问原因、纠正目标或调整路线；修改展示实际节点/投入差异，Agent 解释依据。节点数由 Agent 选择（1–30），反馈不强制保持原数量；图谱仍须用户点击「确认路线，开始学习」，生成不会自动发布。

刷新只恢复目标、图谱和已保存的对话/卡片，不自动执行模型。旧卡/旧版本只读，网络不确定时先查询、显式重发同一请求。已有基础始终为自述、未验证；基础未知不假设已具备能力，缺失成果面向通用概念和练习，缺失投入仅参考 240 分钟而不补填字段。直接目标表单、高级编辑与提案审核在工作台 `/?goal=:id&tool=graph`，资料管理为 `tool=documents`，原文为 `tool=document&document=:id`。工具保留 `goal/session`，资料来源和绑定范围使用 `source_goal/source_node`，不是新的 API 参数；旧 UI 地址只读定位，后端 API 不变。

当前 Agent 规划与工作台的离线证据、历史真实测试的适用范围统一见[质量与验收](QUALITY_SCORE.md)。本手册不重复各阶段测试数量。

以下路由由real和业务fixture API 装配。保留的模型澄清 API 仅保存问题，不代填字段、不自动确认；最多两轮，已提供或已跳过的信息不再追问。每次写操作使用最新 GET 或 run 输出中的 `version`。

| 方法与路径 | body / 结果 |
| --- | --- |
| GET /api/goals | 目标列表，包含规划状态 |
| POST /api/goals | `{"title":"学习 RAG","desired_outcome":"完成检索 demo"}`，返回 201 和 goal_id |
| GET /api/goals/{goal_id} | 当前目标、问题、图谱及 version |
| POST /api/goals/{goal_id}/planning-runs | `request_id`、`expected_version`、`user_text`；结构化回答可带 `response_to_run_id` 与 `answers: [{question_id,value,skipped}]`；返回 202 run，结果见 `output.planning_agent` |
| PATCH /api/goals/{goal_id} | `{"expected_version":0,"current_level":"会 Python"}`；撤销确认、清空旧草稿与问题，保留累计澄清轮次 |
| POST /api/goals/{goal_id}/clarify | `{"request_id":"clarify-1","expected_version":1}`，返回 202 run |
| POST /api/goals/{goal_id}/confirm | `{"expected_version":2}` 仍有效；也可携带 title、desired_outcome、current_level、time_budget_minutes、constraints、skipped_fields，一次保存并显式确认 |
| POST /api/goals/{goal_id}/graph-drafts | `{"request_id":"graph-1","expected_version":3}`，返回 202 run；node_count 可选，默认 10、限 1–30；feedback 可选，最长 2000 字符，有反馈时要求已有草稿 |
| GET /api/goals/{goal_id}/graph | 当前规划状态，与目标 GET 相同结构 |
| PATCH /api/goals/{goal_id}/graph | `{"expected_version":4,"nodes":[...],"edges":[...]}`，提交完整草稿，可增删改 |
| POST /api/goals/{goal_id}/graph/publish | `{"expected_version":5,"expected_revision":0}`，发布并初始化学习快照 |
| GET /api/goals/{goal_id}/graph/citations/{citation_id}?version={version} | 使用当前规划 version 定位图谱原文；版本变化返回 409，需刷新图谱 |

表中版本号示例按各步成功写入递增。节点要求 id、title、explanation、learning_outcome、正整数 estimated_minutes 和 0–5 priority；依赖只允许 prerequisite，source 为 target 的前置，拒绝环、自环、未知节点和重复边。结构化候选至多修复一次，模型调用/修复共享 run 预算；run 输出保存本次提交快照。推荐仍先考虑近期答错，再按优先级、预计分钟与 ID 排序。

`skipped_fields` 只允许 desired_outcome、current_level、time_budget_minutes；填写字段后会清除对应跳过标记。修改目标并确认只推进一次 version；有实际目标变化才清空旧草稿。反馈和当前图谱作为业务数据进入模型上下文，重试保留完整输入；预算、取消、版本冲突、SQLite 恢复与明确发布边界保持不变。实践与验证文字是建议，不代表练习已生成或用户能力已被验证。

规划任务内部按目标串行，共用全应用两并发和取消规则；公开 run 的 `task_ref` 为 `goal:{goal_id}`，不需要节点或 session_id。查询、SSE、取消与相同请求去重沿用 run API。版本过期或发布后直接覆盖返回 409，无效 body/图谱返回 422。目标 PATCH 至少包含一个字段；仅 time_budget_minutes 可用 null 清空，title 必须非空，其余文本/列表可用空字符串或空列表清空。

图谱按显式目标绑定检索；无绑定时 `source_mode: general`，即非基于上传资料。有绑定时最多检索五块、每块320字符，实际片段进入模型上下文，标 `documents`，每节点必须选择本次来源的 `citation_ids`；有绑定但空召回时明确失败，不调用模型。目标声明的 document_ids 未完成绑定时仍返回 grounding_unavailable。run 的 `output.planning.graph.citation_map` 与当前图谱保存来源表，发布保留来源；人工编辑或接受提案保留原文定位、标 `edited`，修改后的内容不继承资料生成声明。未知、重复或正文未列入 citation_ids 的引用拒绝保存。

图谱 GET 动态更新来源 valid/stale/unavailable；定位使用当前 planning version，当前仅持久化一份图谱快照，旧 version 返回 409。HTTP/模型不能覆盖已发布路线，后续修改走持久提案HTTP和人工审核入口。内部兼容方法 update_node/add_dependency 仍可把发布快照转回草稿，不能视为公开产品入口。

目标、问题和图谱可从 SQLite 重启恢复，旧快照启动时补默认字段；real API 的 run/root/请求去重也可恢复。未提交失败可用新 request_id 和 retry_of_run_id 重试；取消与提交存在窄窗口，取消后先 GET 最新规划，版本改变时需重新审核并创建新任务，不能盲用旧版本重试。发布与学习初始化分属两次仓库写入，进程中断可能留下已发布但未初始化的状态；启动通过 `ensure_goal` 仅补建缺失的学习状态，不覆盖已有成绩。初次发布仍非跨仓库原子操作；提案接受已同事务更新图谱/学习版本并保留历史。

## 生成练习与作答

real API 的按钮出题入口是 `POST /api/goals/{goal_id}/nodes/{node_id}/exercises`，body 为 `{"session_id":"practice-1","request_id":"generate-1","count":1,"purpose":"practice"}`，题量限 1–3，返回 202 run；查询和 SSE 沿用 `/api/runs/{run_id}`。教学对话在节点 run body 中设置 `mode: teaching`，与按钮共用 `GenerateExercise`。`npm run dev` 使用 SQLite 业务 fixture，独立 `dev:api` 才仅用于 echo 协议演示；上面的 demo 也可离线复现闭环。

教学工具结果只给模型 `exercise_ids`、`source_mode` 和作答回执；题干/选项仍在公共 `output.exercises` 与学习内容题卡，不从 API 删除。宿主将最近已讲解 assistant 正文（最多 6000 UTF-8 字节）作为生成器避重复数据，按钮路径只采同会话/目标/节点最近已完成讲解；客户端不能传入或覆盖这一内部参数。生成器要求用新数值/场景，精确题干重复会进入现有一次 repair，失败不保存半批；这不是任意等价解答的检测器。工具前演示与保存回执共同保留在教学终态文本中；仍可用回执 ID 继续创建学习包。

`GET` 同一节点 exercises 路径列出当前内容版本题目；`GET /api/goals/{goal_id}/exercises/{exercise_id}` 读取公共题目。提交 `POST /api/goals/{goal_id}/exercises/{exercise_id}/attempts`，body 为 `{"submission_id":"answer-1","selected_option_id":"b"}`。题目、工具结果、run 与 SSE 不包含正式答案/解析；提交反馈才返回。重复 submission 同输入返回原结果，不同输入返回 409；同题仅首次作答计入掌握度，旧版本拒绝作答。 `GET /api/goals/{goal_id}/exercises/{exercise_id}/feedback`只读返回已有最后反馈（历史可回顾）；未答为`feedback:null`，不泄答案、不改掌握度。

主循环、工具内生成和至多一次 JSON 修复共用每 run 六次模型调用上限与 usage。候选整批校验通过才原子保存。练习只检索显式节点绑定的资料，目标绑定不会自动继承；无节点绑定时标 `source_mode: general`，有绑定时实际片段进入生成上下文，每题标 `documents` 并保存 citation_ids/citation_map。有绑定但空召回明确失败；repair 使用原来源表，保存前重查绑定和原文内容。失败/取消/预算耗尽后，用新 request ID 和 `retry_of_run_id` 显式重试，保留原 session、输入和 root task；已经保存的批次按稳定 operation key 复用。省略 retry 字段表示新任务，可生成新题；完全重复题拒绝保存。

`GET /api/goals/{goal_id}/exercises/{exercise_id}/citations/{citation_id}` 定位该题原文。题目 GET 动态返回来源状态与 unverified_citation_ids，解绑/删除/内容变化后定位返回 409，未知编号返回 404。图谱、每题与回答的 C1 分别属于各自产物，不能用回答的 output.citation_map 定位题目引用。程序只校验来源存在、绑定、版本/hash/位置；引用是否支持内容仍需语义评估，尚无真实模型验证。

operation 与题目（含来源表）、业务 API 的 run/root/session/协议历史均持久化于 SQLite；重启后可查询旧 run 并显式 retry，启动不自动执行模型。预算已有六次共享模型调用、八步、十二次工具调用、每次请求 12,000 估算输入 token 限制和 120 秒协作 deadline；输入按 UTF-8 bytes/3 估算（含工具 schema），并非供应商 tokenizer。最旧历史按完整回合裁剪，必要业务上下文和当前输入仍超限则拒绝调用。deadline 在协作检查点生效，不能硬打断阻塞模型/工具；独立 tool timeout、实际累计输入/输出 token 硬预算和生成提交跨document/业务事务仍不具备（提案接受的planning/learning事务已有）。

## 生成学习包与事件 ACK

real API 的 `POST /api/goals/{goal_id}/nodes/{node_id}/lessons` 接受 `{"session_id":"lesson-1","request_id":"generate-1","purpose":"学习当前节点","exercise_ids":[]}`，返回 202 run；完成后读取 `output.lesson`。题卡只引用显式选择的同目标/节点/内容版本已有题目，最多三道；题目生成与正式作答仍走 exercises/attempts。教学工具 `create_lesson` 与按钮使用同一用例和共享模型预算。

| 方法与路径 | 结果 |
| --- | --- |
| GET /api/goals/{goal_id}/nodes/{node_id}/lessons | 该节点包列表，version 降序，包含历史包 |
| GET /api/goals/{goal_id}/lessons/{package_id} | 固定组件、来源表、outdated |
| GET /api/goals/{goal_id}/lessons/{package_id}/citations/{citation_id} | 由该包来源表定位原文 |
| POST /api/goals/{goal_id}/lessons/{package_id}/events | ACK 首次事件，不调用模型、不写成绩 |

schema_version 1 支持 markdown、quiz_choice、stepper、comparison_table，章节 ID 固定为 chapter；含章节最多20块。无绑定为 general，有绑定时实际检索片段进入上下文并保存独立 citation_map；空召回失败，最多一次 repair，保存前复验上下文、来源与题目。包不可覆盖，显式新任务生成新 ID 和递增 version；同 root task 同参数复用，异参数冲突。

事件 body 示例：`{"event_id":"read-1","package_version":1,"component_id":"chapter","action":"mark_read","payload":{}}`。stepper 使用 `step_changed` 与 `{"step":0}`（从0开始）；`request_explanation` 使用空 payload。ACK 本身不调用模型。重复 event_id 且包/version/组件/action 相同返回首次 payload，冲突返回409；非法动作/字段/版本返回422。过期包或旧 schema 包只读，拒绝新事件，已保存事件仍可重试。历史包从 SQLite 重启恢复，来源删除后标 unavailable。

先 ACK 一个 request_explanation 或 step_changed 事件，再提交解释：

```json
{
  "request_id": "explain-1",
  "mode": "explanation",
  "goal_id": "demo-goal",
  "node_id": "document-loading",
  "source_event_id": "explain-event-1",
  "explanation_slot": "initial"
}
```

路径为 `POST /api/sessions/{session_id}/runs`，返回202；解释不接受客户端 user_text，服务端从已保存事件、包和公共题目构造输入。首次 run、初始输入与 `(goal_id, event_id, slot)` 关联在同一 SQLite 短事务提交，模型执行在事务外。同事件/slot 用新 request_id 仍返回最近一次 attempt，跨 session 或不同输入冲突；新 slot 创建新逻辑任务。失败/取消/中断不会因换 request_id 自动执行，须显式提供 `retry_of_run_id`，保留 root 和原输入。原始 request_id 始终指向原 attempt；业务去重返回的额外 request_id 不另存别名。学习上下文过期时拒绝新解释，历史已完成结果仍可读取。React学习包/解释已接入；持久event/slot/request支持显式恢复/重解释，schema0/过期包只读，未知组件安全占位。

## 图谱调整提案

前缀`/api/goals/{goal_id}/graph-proposals`：

| 方法与后缀 | 契约 |
| --- | --- |
| GET / | `{proposals:[...]}`持久列表 |
| GET /{id} | scoped详情 |
| POST / | `{request_id,base_revision,rationale,operations}`，201 pending |
| POST /generate | `{session_id,request_id,purpose,retry_of_run_id?}`，202 proposal run |
| POST /{id}/decision | `{decision:"accept"\|"reject",expected_revision}`，proposal/planning/learning_reset |

仅add_node/update_node/add_dependency/remove_dependency四操作，拒绝额外字段/null/无字段update、环与删除已有学习节点。update可改title/explanation/learning_outcome/priority/estimated_minutes；新增node引用仅用图谱已有有效来源，不声称新资料生成。节点ID禁止URL分隔/转义及`./..`。

教学propose_graph_change绑定goal，与普通POST/生成按钮共用创建用例；模型没有decision/attempt工具。生成共享budget、最多一次repair；稳定root key同输入复用、异参数409。接受在BEGIN IMMEDIATE内原子保存planning/learning/proposal；并发只推进一次，过期base持久conflicted+409，同向决定幂等/反向冲突。内容/依赖更新全局content_revision，历史题/attempt/package保留但只读、当前统计重算；priority/minutes不失效内容。图谱仅当前快照，无完整历史仓库。
