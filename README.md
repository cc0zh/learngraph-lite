# mini-learngraph4

LearnGraph Lite 是一个本地单用户运行的学习 Agent 应用，目标是把学习目标变成可审核知识路线，并用轻量 Agent 循环支持资料学习、练习反馈和下一步建议。完整产品规格见 docs/从零构建功能文档.md。

当前仓库已建立 Python 分层骨架、独立 AgentRunner、应用层 AgentLoop、学习领域规则、资料/学习页/图谱提案离线切片、planning/document/learning/lesson 的最小 SQLite 持久化、FastAPI run 生命周期与实时 SSE，以及 OpenAI-compatible 原生工具调用适配器。React、完整业务 HTTP/SQLite、真实模型 smoke 和 M5 评估交接仍按 docs/exec-plans/active/learngraph-lite-implementation.md 推进。

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

real API 使用相同的提交/查询/SSE 路径，`/api/model/status` 返回 `mode: real`、`configured: true`，只表示配置已装配，不表示供应商连通或认证成功。当前只注册用于协议验证的 `echo` 工具，尚未接入学习业务工具。SDK 隐式重试关闭，应用关闭会先等待工作线程退出再关闭客户端；fixture 入口保持独立。

配置完成后可手动运行 `npm.cmd run smoke:real`（macOS/Linux 使用 `npm run smoke:real`）。它会产生真实 API 请求和费用，依次验证普通回答、原生 echo 调用及工具结果后的回答；不进入默认 CI。本次尚未执行真实供应商 smoke，离线 SDK 协议测试不能替代这项证据。

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
- npm.cmd run release-package

## 当前架构

- src/learngraph_lite/agent_core/：独立 Agent 内核，包含模型协议、工具注册表、Runner 和预算控制。
- src/learngraph_lite/application/：应用编排。当前 AgentLoop 负责 run 准入、幂等、预算注入、运行摘要、公共事件和终态。
- src/learngraph_lite/domain/：学习领域纯规则，例如图谱校验和掌握度计算。
- src/learngraph_lite/presentation/：包含公共 run DTO、SSE 编码和 FastAPI 查询/后台提交/取消/事件路由；HTTP 只调用应用层 AgentLoop。
- src/learngraph_lite/infrastructure/：基础设施适配器。当前包含 planning/document/learning/lesson 的最小 SQLite repository、SQLite FTS5 检索与官方 OpenAI SDK Chat Completions gateway；完整业务持久化、真实 PDF 解析和前端原文页仍待接入。

更多边界见 docs/ARCHITECTURE.md。

## 项目约定

- 从 AGENTS.md 查阅协作规则；docs/ 是仓库知识正式来源。
- 阶段计划维护在 docs/exec-plans/active/learngraph-lite-implementation.md。
- 开源复用记录维护在 docs/references/open-source-reuse.md。
- 离线评估集在 evals/cases/offline-m5.json，运行 npm.cmd run eval:offline 会生成 evals/reports/offline-fixture-report.md。
- 离线演示脚本运行 npm.cmd run demo:fixture，会生成 docs/demo/fixture-demo.md；它只用于无 Key 本地复现，不代表真实模型输出。
- 未配置真实模型 Key 时只能使用明确标记的 fixture 模式，不能把 fixture 结果当成真实模型能力。
