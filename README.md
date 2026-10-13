# mini-learngraph4

LearnGraph Lite 是一个本地单用户运行的学习 Agent 应用，目标是把学习目标变成可审核知识路线，并用轻量 Agent 循环支持资料学习、练习反馈和下一步建议。完整产品规格见 docs/从零构建功能文档.md。

当前仓库已建立 Python 分层骨架、独立 AgentRunner、应用层 AgentLoop、学习领域规则、资料/学习页/图谱提案离线切片、planning/document/learning/lesson 的最小 SQLite 持久化、FastAPI run 生命周期与实时 SSE、OpenAI-compatible 原生工具调用适配器，以及节点上下文、下一步推荐、资料检索、回答引用和结构化练习生成。React、完整业务 HTTP/SQLite、真实模型 smoke 和 M5 评估交接仍按 docs/exec-plans/active/learngraph-lite-implementation.md 推进。

## 开发准备

需要 Node.js 22+、Python 3.13+、uv、Git；完整打包还需要 tar。后端依赖固定在 pyproject.toml 和 uv.lock；当前没有 npm 第三方依赖安装步骤。

先安装锁定的 Python 开发依赖：

```powershell
uv sync --locked --group dev
```

Windows 常用入口：

- npm.cmd run ci
- npm.cmd run smoke:fixture

macOS/Linux 使用 npm。Windows 环境问题见 docs/WINDOWS.md。

## 启动本地 fixture API

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

HTTP 只接受 localhost、127.0.0.1 和 ::1 的 Host；浏览器写请求必须同源。没有 Origin 的本地命令行请求可用。未来前端通过 Vite 代理同源调用；当前不启用跨源访问。

SSE 首帧是 `run.snapshot`，随后接收新生命周期事件和心跳；重连获取当前快照，不重放历史事件。连接断开不取消任务。当前只支持生命周期流，未接入 token 流、会话业务存储或 run 重启恢复；fixture API 也未连接已有学习业务 repository。

## 启动真实模型 API

使用独立入口，后端从环境变量读取配置；缺少 Key 或模型名时启动失败。先执行上述 `uv sync --locked --group dev`，再在 PowerShell 中设置：

```powershell
$env:MODEL_API_KEY = '<你的 API Key>'
$env:MODEL_NAME = '<支持 Chat Completions 和 function tool calling 的模型名>'
# 可选：$env:MODEL_BASE_URL = 'https://供应商地址/v1'
npm.cmd run dev:api:real
```

macOS/Linux 对应设置 `export MODEL_API_KEY='...'` 和 `export MODEL_NAME='...'`，然后运行 `npm run dev:api:real`。`OPENAI_API_KEY` 可作为 Key 备用变量；`MODEL_BASE_URL` 未设置时使用 SDK 默认 OpenAI endpoint。`MODEL_TIMEOUT_SECONDS` 默认 30 秒，为 SDK 网络操作超时，并非整个 run 的硬截止时间；`MODEL_MAX_OUTPUT_TOKENS` 默认 1024，经 `max_tokens` 传递。仅支持接受该参数的 Chat Completions 模型；不宣称所有兼容 endpoint 或模型均可用。

real API 使用相同的提交/查询/SSE 路径，`/api/model/status` 返回 `mode: real`、`configured: true`，只表示配置已装配，不表示供应商连通或认证成功。不带目标/节点的请求使用普通回答与协议验证 `echo`；带作用域的请求装配节点上下文，注册 `get_learning_context`、`get_next_action`、`search_documents` 和 `read_document_chunk`。SDK 隐式重试关闭，应用关闭会先等待工作线程退出再关闭客户端；fixture API 仍只用于协议演示。

配置完成后可手动运行 `npm.cmd run smoke:real`（macOS/Linux 使用 `npm run smoke:real`）。它会产生真实 API 请求和费用，依次验证普通回答、原生 echo 调用及工具结果后的回答；不进入默认 CI。本次尚未执行真实供应商 smoke，离线 SDK 协议测试不能替代这项证据。

## 复现节点学习 Agent

无需 Key 的 SQLite 演示：

```powershell
npm.cmd run demo:learning-agent
```

脚本创建临时数据库，确认 fixture 目标、发布 8 节点图谱并记录 3 次示例作答，绑定一份资料清洗笔记。随后通过原生工具协议读取上下文、十分钟下一步推荐，检索并读取资料片段，生成带 `[C1]` 的回答及来源表，演示空召回，再完成按钮/教学工具出题、提交答案和推荐闭环。输出标记 `mode: fixture` 和 `data: fixture-seeded SQLite`。这验证应用调用链，不代表真实模型能力。

要把演示数据留给 real API，先使用一个尚不存在的数据库文件：

```powershell
npm.cmd run demo:learning-agent -- --database .local/learning-demo.sqlite3
$env:LEARNGRAPH_DATABASE_PATH = '.local/learning-demo.sqlite3'
npm.cmd run dev:api:real
```

脚本拒绝覆盖已有文件。real API 默认数据库为 `.local/learngraph.sqlite3`；启动仅初始化表，不创建目标或重置成绩。当前尚无完整规划 HTTP，可用上述脚本初始化独立演示数据。

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

`goal_id` / `node_id` 必须一起提供，同 session 绑定同一个目标/节点；换节点需新 session。上下文包含已确认目标、发布版本、当前节点、直接前置依赖与练习表现，不包含私有答案。推荐针对整个目标，使用已有服务端规则；`available_minutes` 可省略，提供时必须为正整数。节点不存在返回 404，未发布/未初始化/版本过期的只读请求返回 409；run 内装配失败记录为 `failed`。图谱变化不会自动清空或迁移学习成绩，需后续显式同步用例。

每轮独立装配工具与上下文，工具参数不接受目标/节点改写。资料只检索当前目标和节点均显式绑定的文档；`read_document_chunk` 只接受本轮检索返回的 `citation_id`。默认 `mode: runner` 使用只读工具，显式 `mode: teaching` 增加 `create_exercise`。目前不读取历史对话。可手动使用 `npm.cmd run demo:learning-agent -- --real` 调配置好的供应商，可能产生费用，业务数据仍是 fixture；真实模式只执行资料问答，本次未执行。

完成的节点回答在 GET run 与 SSE 中返回 `output.citation_map` 和 `output.unverified_citation_ids`。C1 等编号仅在本轮有效，来源记录含文档/片段 ID、版本、引用位置、内容摘要值、是否被引用及 `valid/stale/unavailable` 状态。未知编号保留为未验证，不提供来源；引用原文接口未知返回 404，内容变化或解绑返回 409。上面原文命令仅在本轮确实返回 C1 时可用。GET run 保留完成时快照，点击原文重新校验当前绑定和内容；无绑定/空召回要求明确说明资料不足，普通知识解释标注“非基于上传资料”。

当前检索沿用简单中英文 tokenize + SQLite FTS5，不是 jieba/BM25 升级。来源有效性只证明片段可定位，不证明原文支持回答语义；同版本覆盖通过片段摘要值和位置检测失效，完整文档版本管理、上传/PDF 与前端原文页仍待完成。

## 生成练习与作答

real API 的按钮出题入口是 `POST /api/goals/{goal_id}/nodes/{node_id}/exercises`，body 为 `{"session_id":"practice-1","request_id":"generate-1","count":1,"purpose":"practice"}`，题量限 1–3，返回 202 run；查询和 SSE 沿用 `/api/runs/{run_id}`。教学对话在节点 run body 中设置 `mode: teaching`，与按钮共用 `GenerateExercise`。fixture HTTP 启动入口仍只有 echo；离线闭环使用上面的 demo。

`GET` 同一节点 exercises 路径列出当前内容版本题目；`GET /api/goals/{goal_id}/exercises/{exercise_id}` 读取公共题目。提交 `POST /api/goals/{goal_id}/exercises/{exercise_id}/attempts`，body 为 `{"submission_id":"answer-1","selected_option_id":"b"}`。题目、工具结果、run 与 SSE 不包含正式答案/解析；提交反馈才返回。重复 submission 同输入返回原结果，不同输入返回 409；同题仅首次作答计入掌握度，旧版本拒绝作答。

主循环、工具内生成和至多一次 JSON 修复共用每 run 六次模型调用上限与 usage。候选整批校验通过才原子保存。练习当前标记 `source_mode: general`，即非基于上传资料。失败/取消/预算耗尽后，用新 request ID 和 `retry_of_run_id` 显式重试，保留原 session、输入和 root task；已经保存的批次按稳定 operation key 复用。省略 retry 字段表示新任务，可生成新题；完全重复题拒绝保存。

operation 与题目持久化于 SQLite；run/root 关联仍仅在当前进程可查询，重启后不能用旧 run ID 重试。当前只有调用次数/步骤/工具次数和协作取消限制，完整 token/context/deadline 预算、资料型题目 grounding 和跨 planning/learning 事务仍待完成。

## 常用命令

- npm.cmd run ci
- npm.cmd run test
- npm.cmd run test:py
- npm.cmd run dev:api
- npm.cmd run dev:api:real
- npm.cmd run check:py-boundaries
- npm.cmd run smoke:fixture
- npm.cmd run smoke:real
- npm.cmd run eval:offline
- npm.cmd run demo:fixture
- npm.cmd run demo:learning-agent
- npm.cmd run release-package

## 当前架构

- src/learngraph_lite/agent_core/：独立 Agent 内核，包含模型协议、工具注册表、Runner 和预算控制。
- src/learngraph_lite/application/：应用编排。当前 AgentLoop 负责 run 准入、幂等、预算注入、运行摘要、公共事件和终态。
- src/learngraph_lite/domain/：学习领域纯规则，例如图谱校验和掌握度计算。
- src/learngraph_lite/presentation/：包含公共 run DTO、SSE 编码、FastAPI run 路由、节点只读接口和练习生成/作答接口；HTTP 调用应用层用例。
- src/learngraph_lite/infrastructure/：基础设施适配器。当前包含 planning/document/learning/lesson 的最小 SQLite repository、SQLite FTS5 检索与官方 OpenAI SDK Chat Completions gateway；完整业务持久化、真实 PDF 解析和前端原文页仍待接入。

更多边界见 docs/ARCHITECTURE.md。

## 项目约定

- 从 AGENTS.md 查阅协作规则；docs/ 是仓库知识正式来源。
- 阶段计划维护在 docs/exec-plans/active/learngraph-lite-implementation.md。
- 开源复用记录维护在 docs/references/open-source-reuse.md。
- 离线评估集在 evals/cases/offline-m5.json，运行 npm.cmd run eval:offline 会生成 evals/reports/offline-fixture-report.md。
- 离线演示脚本运行 npm.cmd run demo:fixture，会生成 docs/demo/fixture-demo.md；它只用于无 Key 本地复现，不代表真实模型输出。
- 未配置真实模型 Key 时只能使用明确标记的 fixture 模式，不能把 fixture 结果当成真实模型能力。
