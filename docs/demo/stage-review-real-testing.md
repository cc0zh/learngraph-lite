# 测试与阶段验收指南

## P0/P1 产品体验与验收

当前状态、测试数量和最近证据只维护在[质量与验收](../QUALITY_SCORE.md)；本文负责复现步骤，不累加历史计数。唯一 `/` 是学习工作台，资料和图谱管理在主区通过 `tool` 切换；旧页面地址只读兼容跳转，不保留固定问卷。

付费浏览器脚本已用自然目标/出题输入完成真实小样本，链路通过；当时内容有同题演示提前提示答案和 tuple 切片概念错误。后续已做讲解上下文/题目回执隔离、精确重复保护和主题参考修复，未再次付费验证，不记默认答案保护或教学质量通过。内部名称可见由用户接受，不作为本次修复要求。详情见[质量与验收](../QUALITY_SCORE.md)；P1 真实语义质量、20 例真实评估和 M5 交接仍未完成。

### 用户旅程与协议测试分开

- 产品旅程的输入只表达学习需求，如“能举个简单的例子讲讲，再出一道单选练习让我试试吗？”；不得告诉模型工具名、参数、应该出哪种审核卡或替产品补充“不许自动发布/不许泄漏答案”指令。安全边界应来自产品，而非测试作者扮演的用户。
- 工具名可以出现在系统工具说明及测试断言中。检查本轮实际 completed 的工具、新增产物 ID 和持久状态，不把工具名可见、任务完成或已有题目当作本轮生成成功。
- 浏览器真实输入集中在 `frontend/real-tests/user-inputs.json` 并有离线守卫；运行前可设 `LEARNGRAPH_REAL_BROWSER_APPROVED=1` 后执行 `node node_modules/@playwright/test/cli.js test --config frontend/playwright.real.config.ts --list` 检查发现/导入（不启动服务或模型），结束后清除此环境变量。实际付费仍须使用已授权的专用入口。发布前只读核对 draft 状态；公共答案字段隔离与回复语义泄漏分别检查——本轮虽没有直接说选项，例子已给出同题所需结果，不能记默认保护通过。
- 明确指令调用 echo、指定工具顺序的手工编排是协议测试，可以保留，但必须与自然用户旅程、统计语义评估分开报告。fixture/mock 即便输入自然也不能证明真实模型会自主选工具。

## 离线回归（默认不收费）

在仓库根目录按 [README](../../README.md) 准备 Node/Python/uv，再执行：

```powershell
npm.cmd ci
uv sync --locked --group dev
npx.cmd playwright install chromium
npm.cmd run check
npm.cmd run test:e2e
npm.cmd run eval:offline
```

Windows 使用 `.cmd`；macOS/Linux 使用 `npm`、`npx`，Linux CI 安装浏览器时用 `npx playwright install --with-deps chromium`。浏览器安装需要下载，但 fixture/mock 测试本身不请求模型供应商。

- `check` = `ci` + 前端构建；`ci` 包含文档骨架/本地 Markdown 链接、仓库/Action/Python import 检查、Python 与 Node 测试，不含浏览器和离线评估。Python 使用仓库自带测试加载器，未依赖 pytest。
- `test:e2e` 启动独立业务 fixture API/Vite，拒绝复用已运行服务；默认端口 8000/5173、数据库 `.local/e2e.sqlite3`，不会连接 real。若日常开发服务占端口，先停止它，或同时指定 `LEARNGRAPH_E2E_API_PORT`、`LEARNGRAPH_E2E_WEB_PORT` 和独立 `LEARNGRAPH_E2E_DATABASE_PATH`。
- 列举用例使用 `npm.cmd run test:e2e -- --list`；定向回归如 `npm.cmd run test:e2e -- --grep "workbench:"`。不要同时运行两套使用相同端口/数据库的 E2E。
- 规划对话、高级图谱管理和节点对话全部在工作台验证；旧路由只测只读定位及历史兼容。迁移固定问卷用例到直接目标表单，保留版本/dirty/恢复约束；fixture 测链路，mock 专测异常协议，真实模型内容另评估。
- 文档门禁不访问外链、不验证章节锚点，也不证明内容一致；仍需人工核对。完整流水线范围见 [CI/CD](../CICD.md)。

## 可测试的能力与边界

| 范围 | 当前状态 |
| --- | --- |
| 独立 Agent 内核 | 原生工具回合、严格参数、六次共享模型调用/八步/十二次工具调用；12,000 估算输入 token 上限与 120 秒协作 deadline 已具备，无硬中断/独立 tool timeout/完整累计 token 预算 |
| 目标与图谱 | 默认原生工具规划对话、动态问题/目标/路线卡、结构化答复与差异；确定性确认/发布；兼容原最多两轮直接澄清与手动编辑 |
| 节点学习 | 上下文、资料问答、引用定位、练习生成/作答、掌握度与下一步推荐 |
| 资料 | React列表/上传/解析状态/显式目标与节点绑定/分页纯文本原文/引用；TXT/Markdown/文本PDF、FTS5，无OCR |
| 学习包 | 四类固定组件、已有公共题卡、版本/历史反馈、ACK与解释独立会话；恢复event/slot/request，ACK不改成绩；真实内容质量未验收 |
| SQLite | planning/document/learning/lesson/run/proposal/conversation可重开，未完成run转interrupted；提案接受规划/学习/状态同事务，初次publish仍两写 |
| 浏览器验收 | fixture/mock 用例含统一工作台、P0/P1旅程、恢复与版本边界，375–1440响应式（学习包额外320）；另有当前工作台 opt-in 真实小样本和补充只读复核，范围及原失败见质量记录 |

模型协议测试使用 MockTransport，失败/重试与部分浏览器边界使用 mock DTO，浏览器主闭环使用 fixture；这些离线证据不代表真实供应商兼容、生成质量或引用语义支持。回归覆盖未送达/响应丢失、同 ID 恢复、查询门禁、旧历史竞态、422/409解锁、超长节点和 dirty 编辑；真实验证与离线 E2E 分开记录。

## 先启动业务 UI（无需 Key）

运行 `npm run dev`（Windows 可用 `npm.cmd run dev`），打开 <http://127.0.0.1:5173>。它同时启动 Vite 和 SQLite 业务 fixture API，页面必须标记 fixture；独立 `npm run dev:api` 仅演示 echo run 协议，不提供业务 UI 验收。配置好下面的真实模型变量后，可用 `npm run dev -- --real` 启动付费真实业务 UI；当前配置不因历史 smoke 通过就自动保证连通。

浏览器验收检查真实工具活动及持久产物，不接受口头“已生成”。默认mock失败/完成DTO只证明UI/协议；教学、学习包生成、解释、提案各自会话。终态SSE携带公共结果，GET暂失败也解除running；人工查询新终态同样刷新产物。ACK/重解释/提案接受不得刷新自动POST。

按 session、同 mode 恢复 completed 回合的完整协议历史；不是只保存最终文本，也不恢复半截流。最近运行窗口和 12k 估算输入预算限制模型输入，裁剪按完整用户回合进行。120 秒 deadline 只在协作检查点阻止继续，不能硬打断阻塞工具/网络；供应商 timeout 与单次输出上限不等于完整 run token/time 硬预算。

## 先验证供应商和资料问答

使用支持 Chat Completions、function tool calling 和 max_tokens 的模型。配置可放当前终端环境变量或根 `.env`，前者优先，不提交密钥；详情见 [API 手册](../api-guide.md)。下面每条命令都会发起真实请求，可能产生费用，应按需要单独选择，而不是作为默认回归整段执行。

```powershell
$env:MODEL_API_KEY = '<你的 API Key>'
$env:MODEL_NAME = '<模型名>'
# 可选：$env:MODEL_BASE_URL = 'https://供应商地址/v1'
npm.cmd run smoke:real
npm.cmd run smoke:p0:real
npm.cmd run smoke:p0:browser:real
npm.cmd run demo:learning-agent -- --real
```

第一条只验证协议，故可以明确要求 echo；第二条新SQLite验证P0 HTTP（最多12请求），教学问题已改成自然出题需求；第三条新库/独立8010与5183验证P0 UI（最多14请求，不自动重跑）；第四条仅为fixture数据的真实资料问答演示，本轮未执行，`completed` 不代表检索、引用支持或推荐合格，输出明确 `quality_assessed: false`。付费入口默认CI不调用，P1质量仍需下面手测。

## 启动 API 并测试学习包

快速使用独立演示数据（数据库路径必须尚不存在）：

```powershell
npm.cmd run demo:learning-agent -- --database .local/stage-review.sqlite3
$env:LEARNGRAPH_DATABASE_PATH = '.local/stage-review.sqlite3'
npm.cmd run dev:api:real
```

这个初始化命令不调用供应商。浏览器打开 <http://127.0.0.1:8000/docs>；fixture API 的 dev:api 仅演示run协议，不能替代这个业务入口。也可按[README](../../README.md)使用工作台创建目标，或按 [API 手册](../api-guide.md)生成、审核并发布图谱、上传并绑定真实资料。只使用获授权的非敏感样例，不能把日常资料默认发给供应商。

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

手工协议/编排测试：POST sessions/{id}/runs，body带request_id、user_text、goal_id=demo-goal、node_id=document-loading、mode=teaching，可以明确要求先生成练习，再调用create_lesson引用该题；这种输入不属于自然用户旅程。自然需求应另用“给我一份带练习的简短学习材料”等表述并观察实际选择。两者都应检查工具、run输出与持久产物，不把模型口头“已生成”当作证据。

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

记录供应商、模型名、测试日期、非敏感配置、run/package ID、状态/usage和具体问题即可；区分真实调用与 fixture 数据，说明哪些业务未测。React P0/P1自动化入口为npm.cmd run test:e2e（fixture/mock）；真实P0 UI为独立opt-in smoke:p0:browser:real。P1可在React资料/学习包/提案面板走查，但其真实内容仍须语义评估；fixture不等价于真实质量。
