# LearnGraph Lite 从零实现计划

> 本计划保留最初实施及 2026-10-14 验收的阶段事实；后续规划 Agent、Skill、统一工作台已在独立计划推进。当前状态统一见[质量与验收](../../QUALITY_SCORE.md)。旧阶段的“未执行／未完成”仅适用于当时，不作为当前缺口列表；本总计划因真实质量评估与最终交接尚未完成继续保持 active。

## 真实浏览器 P0 与 P1 产品体验（已完成，2026-10-14）

- 用户授权：补齐真实浏览器 P0 验收与 P1 产品体验；沿用本地单用户、现有 React/SQLite/AgentLoop，不增加 P2、登录、云部署或外部写入。真实调用限于现有模型配置、独立测试数据库及非敏感样例，不读取/上传日常资料，不推送或部署。
- 起点：`c0ba6c4`，119 Python/19 Node/11 fixture/mock 浏览器用例与一次真实 P0 HTTP 通过。已有资料/学习包 HTTP，提案只有离线规则；不能把后端用例当作产品体验完成。
- UI 决定：复用现有 indigo/green、系统字体与工作台布局。已查 ui-ux-pro-max 设计系统和 React async/forms 建议，采纳对比度、明确 loading/empty/error、键盘焦点、窄屏标签及 reduced-motion，不引入外部字体请求或无关重设计。
- [x] 资料闭环：列表/上传/解析状态/reparse，目标和节点显式绑定，分页分块原文；回答、图谱、练习、学习包各自产物引用定位。未知来源不可点击，失效显示409降级，删除和目标解绑需明确确认。
- [x] 学习包闭环：固定四类组件、版本/历史只读、正式题卡作答、ACK与解释分离；持久event_id/slot/request_id，响应丢失不自动增费、事件不计成绩。新题/工具产物完成后只读刷新；未知组件安全占位，历史反馈按题目ID读取，未答不泄露答案。
- [x] 提案闭环：pending/accepted/rejected/conflicted持久化、严格四操作、稳定root operation key；按钮/教学工具共用用例。接受/拒绝显式HTTP，scope/base revision校验，规划/学习/提案同SQLite短事务，模型在事务外；保留历史、明示内容失效，不破坏性删除已学习节点。
- [x] 浏览器验收：fixture P1全旅程、错误/重复/刷新/版本冲突及四屏宽；opt-in真实Chromium从首页实际输入点击开始，不预置接口结果、不mock模型。独立数据库、有界付费、脱敏证据；一次通过不代表20例质量评估。
- [x] 回归与审查：139 Python、19 Node、web build、34 fixture/mock E2E、20/20离线评估及import边界通过；安全/一致性/恢复审查实际缺陷已修并补回归。相关demo/文档/diff收口见本节末尾。
- 并行分工：资料前端、学习包前端、提案后端各自独立文件；主负责共享契约、只读补口、fixture、提案UI、真实入口、集成与记录。子任务不各自提交、不读`.env`/日常数据库、不发真实请求，不并发占用同一E2E端口。

### 验收与审查修复

- `npm.cmd run ci`：139 Python、19 Node通过，import/文档骨架/仓库/Action检查通过；`npm.cmd run check:web`：TypeScript/Vite通过；`npm.cmd run test:e2e`：34 passed；`npm.cmd run eval:offline`：20/20。34条离线浏览器证据为13 P0、3资料、13学习包、5提案，与下述1条真实证据分开。
- 初轮两处P0旧测试把所有session当教学session，导致mock查询/计数误伤独立学习包模式；收窄作用域后仍验证聊天和练习同bounded session。首轮P1提案旅程暴露新题后学习包列表未刷新，修复只读结果信号；不是改成功预期掩盖业务失败。
- 审查修复：新增节点citation tuple导致strict HTTP响应500；教学生成在检查与初始化之间可切换图谱；click event误作retry ID；接受响应丢失未同步父图谱；终态GET失败遗留running/人工查询不刷新产物；旧包列表覆盖新版本。对应HTTP/竞态和浏览器回归均通过。
- 节点ID拒绝URL分隔/转义及`./..`，防路由重解释，128字符/中文仍可用。安全子审查首次未返回结论，补审当前源/tests后明确未发现可复现新问题（静态结论，不代替动态测试或全量diff证明）。
- 既有TestClient弃用提示和Uvicorn shutdown graceful timeout/CancelledError仍出现；CI退出码0，保留技术债，不隐藏成已解决。

### 真实 Chromium 浏览器 P0

- `npm.cmd run smoke:p0:browser:real`（2026-10-14 03:21–03:22 UTC）一次通过：首页创建 → 真实澄清 → UI保存/明确确认 → 三节点生成 → 人工标题修改/发布 → 真实`create_exercise` → 选择公开第一选项并提交 → 反馈/1样本/规则推荐 → 按钮第二题 → 刷新保留对话/两题/反馈且0 POST。375/768/1024/1440无溢出、无外站浏览器请求。核心写操作全部来自UI，仅最后GET脱敏计数和完成run证据。
- 模型`deepseek-flash`，provider host `api.deepseek.com`，6次模型调用（全旅程计数上限14），usage input 8926 / output 4391 / total 13317；4个run均completed。教学本次直接调用出题工具，不强求冗余上下文工具调用，服务器已装配上下文。
- 本地证据：`.local/p0-browser-real-2026-10-14T03-21-51-970Z.json`、同名`.sqlite3`与`-completed.png`；原始报告/截图/库/Key不提交。目标`78cd2b34-3f71-47ae-aaeb-96cad2fac1d7`，仅非敏感Python列表/元组样例。浏览器/API由Playwright启停，retries=0，fixture8000/5173与real8010/5183隔离。
- 截图抽查：可变性、原地修改/重绑定示例、两道题和已提交反馈可读；首选项本次答对，但仍仅1样本/学习中，不能称掌握。本次没有真实生成P1资料型内容/学习包/提案，P1证据来自真实业务HTTP+fixture模型及明确标注的异常mock。
- 剩余：P1真实引用语义、解释/题目/组件/提案质量、20例真实评估、M5最终交接；真实取消/失败/重试、多供应商未验收。全局content_revision的语义/依赖变更保守使所有旧内容只读，不做节点级最小迁移；priority/minutes只改计划修订。初次publish/ensure_goal仍两次写入，提案接受才保证跨聚合原子性；图谱/资料完整版本仓库、生成提交跨资料窄窗口仍见技术债。

### 收口记录

- 已同步README、架构、质量评分、测试指南、history和学习笔记；`demo:fixture`、`demo:learning-agent`、`check:docs`、`check:repo`、`git diff --check`均通过，8000/8010/5173/5183无遗留监听。不重复收费旅程，最终本地提交与工作区状态由交付消息给出；原始真实证据/Key不入Git，不推送或部署。

## P0 基线固化与真实模型验证（已完成，2026-10-14）

- 用户授权：修复测试配置隔离、固化当前 React P0 本地 Git 基线，并使用已有配置验证真实模型 P0；允许有界真实 API 调用，不推送、部署或公开本地配置/资料。
- 范围：沿用已有 React P0 和同一 history；不扩展 P1。真实验证使用独立测试数据库与非敏感学习目标，fixture 与真实证据分别记录。
- [x] 配置隔离：缺配置测试 mock `_load_dotenv`，不读开发者 `.env`；新增临时目录配置/进程变量优先级与无配置回归，gateway 构造使用 mock，不访问供应商。
- [x] 离线基线：最终 `npm.cmd run ci` 通过 119 Python、19 Node、import/文档/仓库/Action 检查；`check:web`、11 个 P0 E2E、20/20 离线 fixture 评估与 `git diff --check` 通过。提交仅包含 P0 源码/测试/锁文件/文档，排除凭据、数据库和生成制品。
- [x] 真实验证：`npm.cmd run smoke:real` 普通回答/原生 echo 工具回合通过；`npm.cmd run smoke:p0:real -- --database .local/p0-baseline-real.sqlite3 --report .local/p0-baseline-real.json` 通过。真实模型生成澄清/三节点图谱，显式确认、编辑发布，教学实际调用 get_learning_context/create_exercise，正式作答/规则推荐、按钮再出题、重复请求/交卷及 SQLite 重开通过，无自动重试。
- [x] P0 审查收敛：SafeMarkdown 禁用 img，测试拦截所有外站；未确认 POST 独立保存完整输入与原 request_id，先 GET 再显式重发，不猜测历史任务。旧列表快照失效保护、规划按 goal/graph 独立保留 dirty、超长节点使用持久 UUID session（兼容有效旧 session）。明确 4xx 拒绝解锁并恢复输入，只有 transport/5xx 不确定结果留 pending；失败 run 的 retry 才创建新 request_id。新增9个浏览器回归，总计11通过，不扩展 P1。
- [x] 收口：同步 README、架构、阶段指南、质量评分、技术债、history/学习笔记；先提交本地 P0 基线 `4c95770`（119 Python/19 Node/11 E2E 等通过且工作区干净），再执行真实调用。真实记录单独提交，不推送或部署，Key/数据库/生成报告均留在忽略目录。
- 失败与修复：本轮前次检查为 116 collected/1 failed，`patch.dict(os.environ, clear=True)` 未隔离根 `.env`；临时 mock loader 后定向通过，本轮正式修复并增加独立回归后 117 项通过。既有 TestClient 弃用提示与关闭测试的 graceful timeout/CancelledError 仍出现，CI exit 0，不据此承诺无日志告警。
- 真实验收入口：新增 opt-in `smoke:p0:real`，复用生产 HTTP 装配与真实 gateway；独立新数据库/脱敏 JSON 报告，整条旅程最多12次模型调用，重开数据库禁止任何新模型调用。两项 driver 离线测试使用明确标记 fixture 验证入口本身，不算真实模型结果。该入口不进入默认 CI。
- 浏览器失败收敛：首轮9项为7 passed/2 failed；响应丢失时 SSE snapshot 清掉 pending 的错误提示，改为有 pending 时保留错误。规划回归先保存目标会依法撤销确认，测试补显式重新确认后保存草稿，不绕过业务规则；再补422/409拒绝回归，最终11 passed。最后 build、119 Python/19 Node CI 和 diff 检查通过。

### 真实验收证据与边界

- 日期：2026-10-14 UTC；供应商 host 为 `api.deepseek.com`，模型 `deepseek-flash`，Chat Completions/function calling/stream_options.include_usage；网络 timeout 60 秒、max_tokens 4096。仅证明这一配置本次可用，不推论所有兼容供应商/模型。
- 供应商协议 smoke：普通短答与原生 echo 工具后回答通过；工具回合 usage 为 input 768/output 100/total 868，普通短答 usage 未在该命令汇总。它与下面 P0 usage 分开，不估算没有价格表支持的费用。
- P0 HTTP suite：`real-p0-http`；独立目标“理解 Python 列表与元组的区别”，无资料绑定（general）。P0 脚本7次真实模型调用，恢复阶段0次；usage 为 input 9030/output 4080/total 13110。这是单次小样本连通/业务验收，不是20例真实评估或稳定性成功率。

| 阶段 | run ID | 结果 | 阶段耗时（秒） |
| --- | --- | --- | --- |
| 澄清 | 58c3b667-6d36-4a30-87b8-d5340e730bdc | completed，仅提问不确认 | 2.678 |
| 图谱 | f60f96ac-6f71-4ce6-80f6-1ca9aced8907 | completed，三节点 draft，随后显式编辑发布 | 8.348 |
| 教学 | 430c95cc-c2b9-45e3-abfe-c1b1eba16f77 | completed，context/create_exercise 均成功，有 message.delta | 11.603 |
| 按钮出题 | 26588b03-636b-4b85-ba87-e4193f32160c | completed，第二题独立保存 | 4.945 |

- 原始脱敏证据：`.local/p0-baseline-real.json`；数据：`.local/p0-baseline-real.sqlite3`。均不提交。目标 ID 为 `d5a5fc2b-8976-4b61-93a2-7c8b03b155d5`，验证先选择公共第一个选项，不读取私有答案来“保证答对”；本次反馈正确，1个有效样本仍为学习中，不把一次正确说成掌握。
- React 真实结果恢复走查：为该独立测试目标映射已完成教学 session，页面显示 Real、三节点、真实回答、两题、已保存反馈、1个样本和下一步理由；重开页面保持，恢复目标的网络请求为 GET。未重新发起模型任务；该走查不是从头到尾的真实浏览器自动化 E2E。11项自动化浏览器回归仍属于 fixture/mock。
- 内容抽查：路线覆盖序列基础→可变性/引用→场景选择，两题围绕差异/应用场景，未发现明显错项或正式答案字段泄漏。最终教学回复偏重题卡，并展示 source_mode/citation_map/题目ID等技术用语，后续可改善讲解与表达；不把该抽查扩展为生成质量结论。
- 未覆盖：P1 上传资料的真实引用语义、学习包/事件解释质量、提案链路、真实异常/取消/重试及20例模型评估。已有协作预算并非硬截止。最终更新文档及离线报告措辞：离线 suite 只声明自己未运行真实调用，不再擅自声称环境没有 Key；定向报告测试、离线评估、文档与 diff 检查通过，没有新增业务代码，不重复已通过的全套测试。测试用本地 API/Vite 已停止。

## React P0 实现与上轮验收（2026-10-13）

- 用户授权：继续推进 React P0，覆盖首页、目标澄清确认、可编辑图谱与显式发布、节点对话、文本流/工具状态/停止、练习反馈与规则进度推荐、SQLite 刷新恢复。
- 实现：React 19/TypeScript/Vite（7.3.7）工作区、React Flow、禁 raw HTML 的 Markdown、键盘节点列表与窄屏工作台；后端沿用 AgentLoop/业务用例，加入有界输入、协议历史、SSE cursor 恢复与 SQLite 业务 fixture。私有结构化生成不进入文本流。
- 上轮验证（历史证据）：116 个 Python、19 个 Node 测试，web 类型检查/build、1 个 Playwright P0 E2E（375/768/1024/1440 响应式）、20/20 fixture 评估及 fixture/demo 已通过。浏览器主流程覆盖目标→图谱→节点流→按钮练习/反馈→刷新→停止/重试；不据此宣称对话工具出题和模型失败重试覆盖充分。
- 边界：fixture 证明确定性 UI/API 协议，不证明真实模型质量、供应商兼容或引用语义。真实供应商 smoke 未执行；P1 资料原文页、学习包固定组件前端、提案 HTTP/前端与 M5 最终交接未完成。

## React P0 进展检查修复（2026-10-13，本轮）

- 诉求：修正进度文档损坏和完成状态夸大，补齐教学对话真正执行出题工具与模型失败/显式重试的验收缺口；沿用本计划与同一 React history，不另开任务记录，不提交 Git。
- 代码修复范围（主 agent 实施）：React 节点聊天提交 mode: teaching，并显示/恢复 teaching 会话；业务 fixture 按原生工具协议实际调用 create_exercise，工具与按钮复用 GenerateExercise；浏览器补对话出题、模型失败/重试与刷新恢复覆盖。完成状态和验证须在下列条目补录，不把预期当成已通过。
- 文档修复：README 补业务 UI fixture/付费 real 入口及独立 echo fixture 区别；修复计划/history/学习笔记中的字面量 Unicode/换行损坏，核对真实问号占位；更新架构、测试指南与技术债的预算/历史/P1/供应商边界。
- 已具备预算：六次共享模型调用、八步、十二次工具调用、每次调用 12,000 估算输入 token 上限（消息和工具 schema 按 UTF-8 bytes/3）及 120 秒协作 deadline。按最旧完整用户回合裁剪历史；必要上下文超限则拒绝调用。usage 汇总不等于实际累计 token 硬预算，deadline 不会硬中断阻塞调用，独立 tool timeout 与完整累计输入/输出 token 预算仍不具备。
- 已具备历史：同 session、同 mode 的 completed 回合从最近八条运行记录中恢复完整 user/assistant/tool 协议，保留 tool_calls/tool_call_id 配对；失败/取消/未完成回合不进入下一轮历史。业务 SQLite 重启后可恢复记录与已完成协议历史，但不会自动继续模型执行。
- [x] 本轮实现确认：聊天 mode: teaching，兼容显示 runner/teaching；mastery 映射 unknown/proficient。业务 fixture 实际 context → create_exercise（内嵌生成）→ 最终回答，既有 Python fixture 测试扩展教学/按钮/答案隔离与恢复，总数仍为 116。
- [x] 本轮专项验证：`npm run test:py` 为 116 passed；`npm run test:e2e` 修复后 2 passed。首轮先改测试，2 failed 复现工具未调用与 teaching 结果被过滤，修复后通过。主 E2E 实际工具出题/作答恢复，另验证按钮生成第二题、停止重试和四屏宽；第二 E2E 为真实业务 fixture 设置 + mock 模型失败/完成 run DTO，只证明 UI 失败可见、retry 保留 mode/input、新 request/原 retry ID，不宣称真实模型证据。
- [x] 本轮其余代码验证：`npm.cmd run check:web`、`npm.cmd run eval:offline` 与 `npm.cmd run check:py-boundaries` 均通过；Node 测试已在全套 CI 中复验。
- [x] 本轮文档验证：文档检查、相对引用核对与 `git diff --check` 通过；新增记录已改为正常 UTF-8 中文，不再包含字面量 Unicode/换行转义。
- [ ] 真实供应商验证：未执行；需配置后单独记录 smoke/业务手测，fixture/MockTransport 不替代该证据。
- 记录索引：[React history](../../histories/2026-10/20261013-2115-react-p0.md)、[阶段测试指南](../../demo/stage-review-real-testing.md)、[验收学习速记](../../learnings/2026-10/20261013-react-p0-acceptance.md)。

> 历史边界：本计划保留各切片当时的实现、通过结果和未完成项；这些阶段事实不代表当前版本状态。2026-10-14 的真实证据见文首历史章节；当前进展统一见[质量与验收](../../QUALITY_SCORE.md)，不要以任何旧阶段的通过或未执行记录替代新流程验收。

## 运行恢复与事件解释切片（已完成）

- 用户已要求继续推进，撤销上轮暂停。本轮完成 run/session 作用域、请求输入、root 与公共结果的 SQLite 持久化，以及事件解释 HTTP；不进入 React 或真实供应商评估。
- 方案：沿用 AgentLoop 单进程、最多两条执行线程和标准库 SQLite。新增运行仓库端口；初始 run、输入与事件/slot 的逻辑任务关联在同一短事务提交，模型调用在事务外。事件已由 ACK 保存，解释只使用服务端保存的摘要。
- 恢复：启动将遗留 queued/running 标 interrupted，不自动续跑或重新调用模型；完成结果可查，重复请求返回已有任务。失败/取消/中断显式 retry 保留 root 和初始输入，新 slot 才创建新解释任务。
- 验收：并发不同 request_id 的事件/slot 去重、跨包/节点/版本校验、事务故障回滚、运行/输入/root 重开、SSE 快照、session 作用域及全局容量、解释失败/取消/中断显式重试，生成已提交产物在重试中复用；相关测试、CI、离线评估与演示通过后同步文档、history、学习记录并提交。
- 限制：单 API 进程；不恢复模型流或跨进程 worker；有限会话历史组装、token/context/deadline 预算仍待后续。真实供应商未验证。
- 实现：RunRepository 与 SQLiteRunRepository 接通 real factory，保存完整请求/session作用域/root、公共结果/usage和seq事件。恢复不调用模型，遗留任务转interrupted；GET session runs、旧run与SSE快照可读。准入失败原子回滚；终态保存失败不发布完成结果，live转interrupted并关闭新准入，durable保留上一状态待存储修复后重启。
- 解释：HTTP拒绝客户端user_text，从已保存ACK/组件/公共题卡构造输入，校验节点/包版本/当前学习快照；首次事件关联、run和输入同SQLite短事务提交。业务键(goal,event,slot)在锁内并发复用最新attempt，跨session/不同输入冲突；显式retry保留root和原输入，新slot新任务。额外业务重复request ID不存别名，原始request ID仍返回原attempt。旧explain_event仅兼容离线demo/eval，不作为新HTTP实现。
- 上游核验：读取nanobot固定commit的session/manager.py，参考SessionStore端口与先保存后更新内存；不复制/安装，不引入JSONL checkpoint或外部任务队列，记录见[复用说明](../../references/open-source-reuse.md)。
- 测试收敛：新增7个聚合测试，覆盖completed/cancelled/queued/running重开、原输入/root/作用域/事件、6线程不同request ID同slot单次执行、ACK并发不丢关联、准入与状态/事件故障回滚、失败/取消/中断重试、HTTP错误码/列表/SSE/real factory恢复、公共题卡/包版本/过期/并发限额、产物已提交但run结果未保存时零模型调用复用。
- 验证：专项7项通过；`npm.cmd run ci`通过111个Python、19个Node测试及Python import边界、文档/仓库/Action检查；`eval:offline`为20/20；`demo:fixture`、`demo:learning-agent`、`smoke:fixture`均exit 0。TestClient弃用提示与关闭测试预期graceful timeout/CancelledError仍存在，smoke终端中文显示乱码。真实供应商smoke/demo未执行。
- 最后审查：提交run路由改为同步def，使同步SQLite准入/解释读取运行在FastAPI线程池；变更后`test:py`再次111项通过。文档骨架、相对引用路径与`git diff --check`通过。
- 失败与修复：首次旧104项回归有1项错误码失败，session作用域校验抢在不存在节点校验前返回409，恢复validate先行后最终全套通过。新增专项第6项误用已发布图谱的草稿API，改为显式注入已接受内容revision场景；PowerShell中文字符串替换未命中，改用apply_patch后7项通过。恢复构造中持有Condition锁再提交interrupted，避免notify_all无锁。
- 收尾：同步README、架构、技术债、[真实测试指南](../../demo/stage-review-real-testing.md)、[history](../../histories/2026-10/20261013-2055-run-recovery-explanations.md)与[逻辑任务/attempt学习笔记](../../learnings/2026-10/task-and-attempt-recovery.md)。本轮完成下一切片后恢复用户要求的暂缓，供阶段总结与真实测试；不进入React或其他阶段，P0/P1/M5尚未全部验收。

## 学习包生成与事件 HTTP 切片（已完成）

- 范围：沿用 shared gateway、GenerationSources 和 direct/tool 同用例；生成固定 Markdown/quiz_choice/stepper/comparison_table，题卡只引用同目标/节点/内容 revision 的已有题，不含答案。top5 来源与一次 repair 共用来源表；保存前复验资料与业务版本。
- 持久化：教学包 schema/version/source metadata、generation operation 和事件版本；SQLite 短事务与内存 mutate 防止不同会话保存/ACK 覆盖。同任务同配置复用，异配置冲突；显式新任务生成新包版本。旧包可查看并标 outdated。
- HTTP：按需生成、节点列表、包详情、包引用定位和事件 ACK；限定组件对应动作/payload，ACK 不改成绩，作答仍走 attempts。模型不参与普通 ACK。
- 验收：grounding/repair/预算、题目作用域与版本、未知组件和字段、幂等/并发、SQLite 重开/旧 schema、HTTP/SSE/删除降级与事件不改成绩；通过 CI/离线评估/demo 后同步文档与 commit。
- 边界：保留旧离线解释用例但不提供解释 HTTP；其尚未满足事件关联、初始 run 和输入同事务要求。run/session 持久化与解释并发/失败重试留下一切片，不以进程内去重宣称 M4B 完成。本轮无需新增外部依赖。
- 实现：GenerateLesson 严格候选与一次 repair，按钮/教学工具共用 gateway；schema/version、独立来源表、题目 public DTO、generation operation、HTTP 列表/详情/引用/ACK 接通 real factory。内存仓库深拷贝与 RLock，SQLite BEGIN IMMEDIATE 防止生成/ACK 丢更新；旧 schema 自动补列并只读，历史包在节点删除或 learning 未同步时仍可读取。
- 测试收敛：新增6个聚合行为测试，覆盖来源 top5/1600、修复、参数冲突/版本/重开、非法候选/跨节点题目、生成期间上下文/来源/题目变更、空召回零调用/预算、teaching共享六次调用与各产物C1隔离、HTTP/SSE/ACK不计分/正式作答、并发生成和ACK/回滚/解释期间ACK保留、旧schema迁移。
- 验证：专项6项通过；`npm.cmd run ci` 通过104个Python、19个Node及Python import边界、文档/仓库/Action检查；`eval:offline` 为20/20；`demo:fixture`、`demo:learning-agent`、`smoke:fixture` 均exit 0。TestClient httpx弃用提示与关闭测试预期graceful timeout/CancelledError仍存在，smoke终端中文显示乱码。真实供应商调用未运行。
- 失败与修复：首轮98项Python回归9项失败，旧choice_card/select/字符串steps fixture与demo/eval未适配新schema；改用quiz_choice/markdown、step_changed和结构化steps后最终CI通过。新增专项初轮HTTP作答断言误读顶层is_correct，按既有attempt反馈结构修正后6项通过；PowerShell中文批量替换未生效，改用apply_patch完成编辑。
- 文档与暂停：同步README、架构、技术债与[history索引](../../histories/2026-10/20261013-2020-lesson-generation-http.md)，提炼短事务增量更新学习笔记。[阶段总结与真实测试](../../demo/stage-review-real-testing.md) 提供已有命令与学习包手测步骤。最终文档骨架、引用路径和diff检查通过。本切片收尾提交后按用户要求暂停整体goal，不进入解释/run持久化或React阶段；P0/P1/M5尚未全部完成。

## 资料型图谱与练习生成切片（已完成）

- 范围：复用显式目标/节点绑定检索，top5、每片段320字符；图谱与练习模型上下文包含真实资料，repair 共用来源表。无绑定标 general，有绑定空召回明确失败。
- 来源：服务端生成 citation map，候选只能选择本次来源 ID；图谱版本、每题和回答分别保存来源表。保存前复验绑定、版本、hash/offset；发布保留图谱来源，人工修改保留来源表并标 edited，清除生成来源声明。
- 验收：上下文原文、未知/越界引用、空召回、稳定 repair、产物 C1 不串、SQLite 重开/旧 schema、生成期间解绑/覆盖、HTTP/SSE 公共投影和删除后定位降级；相关测试、CI、离线评估/演示通过后同步文档并提交。
- 边界：不增加独立模型队列或平台；沿用共享 gateway/budget 和 generation operation。跨资料/业务仓库仍存在保存前校验后的并发窄窗口，引用程序校验不证明语义支持。学习页 grounding、React、运行持久化与真实供应商验收仍待后续。
- 实现：GenerationSources 输入实际检索片段，候选只选来源 ID；图谱快照与每题分别持久 citation_map，公共练习/工具结果仍不含正式答案与私有解析。GET 图谱/题目动态投影来源状态；图谱定位核对 planning version，题目定位按 exercise_id 隔离。SQLite 自动补 sources_json 并兼容旧图谱/练习 metadata。
- 审查修复：人工编辑与提案共用纯领域引用校验，拒绝未知正文标记、越界与重复 IDs；图谱 GET 改为单份规划快照，避免版本/来源混读。保留已有引用表并标 edited，以维持原文定位，但不宣称编辑内容仍由资料生成。
- 测试收敛：新增 6 个聚合行为测试，覆盖真实上下文/top5/1600限额、隐藏资料排除、稳定 repair、direct/teaching 共享预算、回答/每题 C1 隔离、空召回零调用、general 伪造引用、生成期间解绑/同版本覆盖/新增绑定、人工与提案引用、HTTP/SSE、单次规划读取、SQLite 重开/旧 schema 与来源删除降级；没有逐字段拆测试。
- 验证：`npm.cmd run ci` 通过 98 个 Python、19 个 Node 测试及文档/仓库/Action、Python import 边界检查；`eval:offline` 为20/20；`demo:fixture`、`demo:learning-agent`、`smoke:fixture` 全部 exit 0。TestClient httpx 弃用提示、关闭测试的预期 graceful timeout/CancelledError 和 smoke 终端中文乱码仍存在，不影响上述退出结果。无供应商 Key，真实模型 smoke/demo 未运行。
- 失败与修复：首轮92项 Python 回归有1项 demo fixture 失败，因候选未选择真实来源 ID；更新 fixture 和旧 general 断言后全套98项通过。专项首次执行缺 task_ref，修正后6项通过；定向 uv 命令曾遇缓存权限，经批准执行。当前成功结果包含最后的审查修复。
- 文档：同步 README 接口/模式、架构与技术债，补 history 索引和产物引用作用域学习速记；`npm.cmd run check:docs` 与 `git diff --check` 通过。总目标保持 active，本切片不代表 P0/P1/M5 已全部验收。

## 资料上传与检索 HTTP 切片（已完成）

- 范围：UTF-8 TXT/Markdown、文本型 PDF；服务端 ID、10MB/100页/200000字符限额；原文件保存到 SQLite BLOB，异步解析状态与有界工作线程，PDF 在可终止子进程中解析；重启恢复 interrupted，原文件 reparse，ready 不重复解析。
- 检索：复用 jieba 与 SQLite FTS5 BM25，统一索引/查询分词、安全 MATCH、top5 与文本上限；只检索显式绑定资料。HTTP 绑定/搜索在应用层检查目标/节点存在，上传不调用模型。
- 验收：上传→状态→原文→绑定→搜索→现有 Agent 引用；真实小型 PDF、扫描/加密/坏编码/限额/超时/重启/重试/删除及引用失效聚合测试；CI、离线评估与演示通过后同步文档并提交。
- 边界：本轮不实现资料型图谱/练习/学习页生成、React、session/run 持久化或真实供应商验证；总目标持续 active。
- 实现：`DocumentImports` 与 `SubprocessDocumentParser` 接通 multipart 上传、状态/chunks、reparse、删除及目标/节点绑定/搜索；real factory 与现有 Agent 共用 SQLite document repository。成功状态、全文/chunk/FTS 同事务提交，绑定校验与写入同一写事务；删除后的解析结果不复活。页码、ATX heading、精确 offsets 与 SHA256 贯通检索和 HTTP/SSE 来源定位。
- 测试收敛：新增 7 个聚合行为测试，覆盖真实两页 PDF 与 Markdown 上传→发布/绑定→检索→Agent 引用→定位→删除降级，以及格式/坏编码/扫描/加密/限额/超时、重启/原文件重试、队列准入、解析中删除、绑定范围、jieba/BM25、旧 schema/index 升级、故障回滚与绑定/删除并发；复用现有评估用例，不为每个字段独立建测试。
- 验证：`npm.cmd run test:py` 为 92 passed；`npm.cmd run ci` 通过 92 个 Python、19 个 Node 测试及 Python import 边界、文档/仓库/Action 检查；`npm.cmd run eval:offline` 为 20/20；`demo:fixture`、`demo:learning-agent`、`smoke:fixture` 均 exit 0。锁定依赖已安装并核验所用 API/许可。TestClient httpx 弃用提示与关闭测试的预期 graceful timeout/CancelledError 仍存在，smoke 终端中文显示乱码，不影响上述退出结果。
- 失败与修复：初轮 91 测试遇到 Windows SQLite 连接未关闭，改用显式 closing；本轮首轮 92 测试有 4 个失败，分别修正 SSE 测试的 payload.output 路径、绑定错误文案兼容，以及 Markdown 先按 page marker 再按 heading 切块。独立离线评估曾为 19/20（document_upload_chunks），修复后最终 20/20；上述成功结果均来自修复后执行。
- 限制：无 OCR；乱码拒绝仅 replacement/control chars 启发式；Markdown 仅 ATX 标题。HTTP 文件固定 revision 1，更新内容需重新上传/绑定；恢复假设同一数据库仅一个 API 进程，不支持多进程任务归属。引用可定位不证明语义支持；无供应商 Key，真实模型 smoke/demo 未运行。
- 文档收尾：同步 README 接口示例、架构、技术债、三项锁定依赖复用记录、history 与 ready 原子提交学习笔记；修复复用表格中断并更新当前验收限制。最终 `npm.cmd run check:docs` 与 `git diff --check` 通过；仅修改文档后未重复代码全套检查。

## 目标、范围与风险

- 目标与验收标准：依据 docs/从零构建功能文档.md 从模板项目实现 LearnGraph Lite，最终达到 P0+P1 与 M5 交付：本地原生启动、无 Key 确定性测试、真实模型 smoke 证据、小型评估集/报告、README、复用许可记录、演示脚本、已知局限、分层依赖检查与内核独立运行证据。
- 包含：M0 工程与能力探针；M1 独立 AgentRunner/AgentLoop/fixture smoke；M2 目标与图谱；M3 P0 节点学习与练习闭环；M4A 资料引用；M4B 声明式学习页与解释幂等；M4C 图谱提案审核；M5 回归、真实评估与交接。
- 不包含：登录/权限体系、Android、语音、Docker/沙箱执行、长期记忆、企业级安全平台、任意代码执行。
- 风险及缓解：外部网络不稳定时，不编造 GitHub 或模型核验证据；先实现离线 fixture 与领域接口，并把真实模型/外部源码核验列为待补证据。阶段功能不以 fixture 冒充真实模型能力。
- 已有授权与需要确认的边界：用户已授权本地实现、测试和适当 commit；发布、部署、外部写入、真实供应商 Key 配置和破坏性操作需另行确认或凭已有环境能力执行。

## 进度与决定

- [x] M0：读取功能规格、仓库约束，确认当前仓库仍是模板态。
- [x] M0：建立执行计划、架构说明、开源复用记录和第一条 history。
- [x] M1：新增 agent_core，用 fake/fixture 模型测试普通回答、工具回注、未知工具、坏 JSON、预算和取消。
- [x] M1：新增应用层 AgentLoop，测试幂等、直接生成路径和 Runner 路径分离。
- [x] M1：新增少量纯领域规则，证明判分/图谱校验不依赖模型或 Runner。
- [x] M1：新增轻量 import 边界检查并接入 CI。
- [x] M1：补 HTTP/SSE 最小生命周期、运行摘要与取消状态的真实路由测试；已完成 FastAPI app factory、后台提交、查询/取消、快照/心跳/后续事件、重连和真实 TCP 关闭验证。
- [x] M2：目标澄清、确认、图谱草稿/编辑/发布、revision、规划离线 E2E 与 planning state 最小 SQLite 持久化。
- [x] M3：节点 Agent 学习、单选题生成、服务端判分、进度、下一步离线闭环与 learning state 最小 SQLite 持久化。
- [x] M4A：TXT/Markdown 文档解析、分块、简单中英文检索、绑定、引用定位、空召回离线切片与 SQLite FTS5 最小适配器。
- [x] M4B：声明式学习页、固定组件、事件 ACK、解释任务幂等离线切片与 lesson state 最小 SQLite 持久化。
- [x] M4C：图谱提案、差异审核、接受/拒绝、base_revision 冲突离线切片。
- [ ] M5：全量回归、真实模型 smoke、20 例评估集与演示交接；已完成 20 例离线 fixture 评估集、可生成报告脚本和可复现 fixture demo，真实模型 smoke 与浏览器演示交接仍待完成。
- 2026-10-13：采用轻量 Python 分层骨架先完成 M0/M1 离线可验证切片；FastAPI/React/SQLite 仍按后续阶段引入，避免在模板态一次性拉入未验证依赖。
- 2026-10-13：已通过 GitHub raw 核验 nanobot 固定 commit 的 README、architecture.md、agent/loop.py、agent/runner.py 和 LICENSE；复用记录已更新。GitHub tree API 受 rate limit，未取得完整目录树。
- 2026-10-13：M2 离线切片完成目标草稿、最多两轮澄清、目标确认、8 节点候选图谱、草稿编辑、发布校验、revision 冲突与刷新恢复所需的内存仓库；HTTP/SQLite/前端 E2E 待后续阶段接入。
- 2026-10-13：M3 离线闭环完成节点 Agent 学习入口、单选题 Public/Private DTO、服务端判分、同题首次作答计分、重复题拒绝、旧内容版本拒绝、掌握度可升可降、按前置依赖/错题/时间预算推荐下一步；HTTP/SSE 与真实模型路径仍待后续接入。
- 2026-10-13：M4A 离线切片完成 TXT/Markdown/PDF-text 文档模型、分块、中文/英文关键词检索、目标/节点绑定、引用定位、空召回说明和旧引用版本拒绝；真实 PDF 二进制解析和前端原文页仍待接入。
- 2026-10-13：M4B 离线切片完成声明式 LessonPackage、固定组件 schema 校验、Markdown/组件可执行字段拒绝、事件 ACK 幂等、学习页事件不改成绩、正式作答复用 LearningService、解释 run 按 source_event_id/slot 幂等；前端渲染器和真实路由仍待接入。
- 2026-10-13：M4C 离线切片完成 GraphProposal、add/update node、add/remove dependency、pending/accepted/rejected/conflicted 状态、base_revision 冲突、接受才改图、拒绝无副作用、非法操作和成环校验。
- 2026-10-13：M1 生命周期补强完成 AgentLoop run_id 查询、seq 事件、运行摘要、usage 汇总、预算耗尽映射、取消终态和 presentation 公共 DTO/SSE 编码；当前环境无 FastAPI/Starlette，真实 HTTP 路由测试仍待后续依赖接入。
- 2026-10-13：M5 离线评估切片新增 evals/cases/offline-m5.json、evals/run.py 和固定报告，覆盖规划、图谱、学习、资料、学习页、提案和运行生命周期 20 个 deterministic case；报告明确真实模型 smoke 未运行。
- 2026-10-13：M5 fixture demo 切片新增 scripts/run-fixture-demo.py 和 docs/demo/fixture-demo.md，串起目标确认、图谱发布、资料引用、空召回、节点学习、练习掌握、下一步、声明式学习页与图谱提案；输出明确标记为 deterministic fixture demo。
- 2026-10-13：SQLite planning persistence 最小切片完成 `SQLitePlanningRepository`，用标准库 sqlite3 持久化目标草稿、澄清轮次和当前图谱快照，验证重新实例化 repository 后可恢复已确认目标与已发布图谱；完整业务 SQLite schema、迁移、练习/资料/事件持久化仍待后续接入。
- 2026-10-13：SQLite document retrieval 最小切片完成 `SQLiteDocumentRepository`，持久化文本资料、chunk、目标/节点绑定和引用定位，并用 FTS5 索引现有 `tokenize()` 结果支持中英文检索；真实 PDF 二进制解析、前端原文页、完整业务持久化仍待后续接入。
- 2026-10-13：SQLite learning persistence 最小切片完成 `SQLiteLearningRepository`，持久化学习图谱、私有练习、作答和节点学习请求幂等结果，验证重新实例化 repository 后可恢复掌握度、下一步推荐和同题重答计分规则；学习页事件、运行生命周期和完整业务 schema 仍待后续接入。
- 2026-10-13：SQLite lesson persistence 最小切片完成 `SQLiteLessonRepository`，持久化 lesson package、事件 ACK、解释 run 和失败重试状态，验证重新实例化 repository 后可恢复事件幂等和解释重试；React 固定组件渲染器、HTTP ACK 路由、浏览器 E2E 和完整业务 schema 仍待后续接入。
- 2026-10-13：HTTP/SSE 最小切片完成 FastAPI app factory、明确 fixture 启动入口、后台 run 准入和相同输入去重、取消后的名额保持、原子快照/事件 cursor 与实时心跳、本机 Host/同源写请求边界；本地入口设置有限 Uvicorn 连接关闭等待，再由 lifespan 协作取消并等待工作线程退出。引入锁定的 FastAPI/Uvicorn 与开发 HTTPX，CI/发布校验显式安装 uv 与 Python 依赖。实现仍未连接学习业务 repository。

## 历史验收与交接

以下命令/数量保留各早期阶段事实；当前验收看文首 React 节，本轮检查不重写历史通过记录。

- 已执行的命令及结果：
  - python scripts/check-python-boundaries.py：通过，输出 Python import boundaries passed。
  - python scripts/run-python-tests.py：通过，9 Python tests passed。
  - python -X utf8 scripts/run-fixture-smoke.py：通过，输出“工具结果已收到，继续学习下一步。”
  - npm.cmd run ci：M0/M1 通过，包含 Python 边界检查、9 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M2 后通过，包含 Python 边界检查、13 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M3 后通过，包含 Python 边界检查、18 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M4A 后通过，包含 Python 边界检查、21 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M4B 后通过，包含 Python 边界检查、25 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M4C 后通过，包含 Python 边界检查、29 个 Python 测试和 19 个 Node 模板工具测试。
  - python scripts/run-python-tests.py：M1 生命周期补强后通过，32 Python tests passed。
  - python scripts/check-python-boundaries.py：M1 生命周期补强后通过，输出 Python import boundaries passed。
  - npm.cmd run ci：M1 生命周期补强后通过，包含 Python 边界检查、32 个 Python 测试和 19 个 Node 模板工具测试。
  - python evals/run.py：M5 离线评估切片通过，输出 20/20 offline fixture eval cases passed，并生成 evals/reports/offline-fixture-report.md。
  - python scripts/run-python-tests.py：M5 离线评估切片通过，34 Python tests passed。
  - npm.cmd run ci：M5 离线评估切片通过，包含 Python 边界检查、34 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run demo:fixture：M5 fixture demo 切片通过，生成 docs/demo/fixture-demo.md。
  - python scripts/run-python-tests.py：M5 fixture demo 切片通过，36 Python tests passed。
  - npm.cmd run ci：M5 fixture demo 切片通过，包含 Python 边界检查、36 个 Python 测试和 19 个 Node 模板工具测试。
  - python scripts/run-python-tests.py：SQLite planning persistence 切片通过，38 Python tests passed。
  - python scripts/check-python-boundaries.py：SQLite planning persistence 切片通过，输出 Python import boundaries passed。
  - python scripts/run-python-tests.py：SQLite document retrieval 切片通过，41 Python tests passed。
  - python scripts/check-python-boundaries.py：SQLite document retrieval 切片通过，输出 Python import boundaries passed。
  - npm.cmd run check:docs：SQLite document retrieval 切片通过，输出文档骨架检查通过。
  - npm.cmd run ci：SQLite document retrieval 切片通过，包含 Python 边界检查、41 个 Python 测试和 19 个 Node 模板工具测试。
  - python scripts/run-python-tests.py：SQLite learning persistence 切片通过，45 Python tests passed。
  - python scripts/check-python-boundaries.py：SQLite learning persistence 切片通过，输出 Python import boundaries passed。
  - npm.cmd run check:docs：SQLite learning persistence 切片通过，输出文档骨架检查通过。
  - npm.cmd run ci：SQLite learning persistence 切片通过，包含 Python 边界检查、45 个 Python 测试和 19 个 Node 模板工具测试。
  - python scripts/run-python-tests.py：SQLite lesson persistence 切片通过，47 Python tests passed。
  - python scripts/check-python-boundaries.py：SQLite lesson persistence 切片通过，输出 Python import boundaries passed。
  - npm.cmd run check:docs：SQLite lesson persistence 切片通过，输出文档骨架检查通过。
  - npm.cmd run ci：SQLite lesson persistence 切片通过，包含 Python 边界检查、47 个 Python 测试和 19 个 Node 模板工具测试。
  - uv sync --locked --group dev / uv lock --check：HTTP/SSE 锁定依赖安装与一致性检查通过。
  - npm.cmd run ci：HTTP/SSE 切片通过，包含 Python 边界检查、57 个 Python 测试（新增 10 个 HTTP/TCP 用例）和 19 个 Node 模板工具测试；shutdown 用例主动触发 graceful timeout，预期的 ASGI CancelledError 日志不代表测试失败。
  - npm.cmd run eval:offline：HTTP/SSE 切片回归通过，20/20 offline fixture eval cases passed。
  - npm.cmd run smoke:fixture：通过；独立 Uvicorn 进程与真实 TCP 手工 smoke 也通过 model/status、202 提交和 SSE 完成。
  - npm.cmd run check:docs / npm.cmd run check:actions / git diff --check：文档骨架、Action 固定 SHA 和空白检查通过。
- 当前未执行的检查、阻塞和遗留事项（替代旧阶段过时汇总，不改变其验收事实）：
  - 本轮教学对话工具出题与失败/显式重试修复的代码回归待执行，结果补在文首待验证条目。
  - 真实供应商 smoke/demo 与引用语义/生成质量验证未执行。
  - P1 资料原文页、学习包固定组件前端、提案 HTTP/前端和 M5 最终交接未完成。规划/学习/资料/学习包/运行与解释 HTTP 已接通 SQLite，不能再写成仅内存或未实现 React。
  - 已具备估算输入上限、协作 deadline、已完成协议历史与 SSE cursor 有界恢复；无阻塞调用硬中断、独立 tool timeout 或完整累计 token 硬预算。
  - 图谱发布/学习初始化、资料校验/业务提交仍无跨仓库事务；完整版本历史/schema 迁移及成绩迁移协议未完成。
  - nanobot tree API 完整目录树未取得；SDK MockTransport 不证明供应商兼容，TestClient 弃用提示与 shutdown 预期日志见既有历史结果。
- 必要的复验方式：
  - uv sync --locked --group dev
  - uv run --locked python scripts/run-python-tests.py
  - uv run --locked python scripts/check-python-boundaries.py
  - npm.cmd run eval:offline
  - npm.cmd run demo:fixture
  - npm.cmd run ci
  - 后续阶段按本计划逐项补充 E2E 与真实模型记录。

## HTTP/SSE 实施切片（已完成）

- 范围：FastAPI app factory、后台 run、查询/取消、实时生命周期 SSE、fixture 启动入口、锁定依赖与 CI 安装。复用官方 StreamingResponse/lifespan/TestClient，不添加任务队列平台。
- 验收：阻塞模型下 POST 及时返回 202；重复提交不重跑；同 session 409、全局 429；取消终态不被晚到结果覆盖，调用退出前不释放名额；真实 TCP SSE 在模型结束前收到快照、started 和 heartbeat；关机协作停止。
- 证据：tests/test_http_runs.py 覆盖上述边界、唯一终态、断线不取消/重连只取快照、Host/Origin 和活跃 SSE 下的关闭；独立 Uvicorn 进程 smoke 验证本地 factory。README 给出锁定依赖安装与提交/查询/SSE 命令。
- 限制：本切片不宣称 token streaming、run 重启恢复、完整业务 HTTP/React 或真实模型能力；这些仍属于总计划待办。

## 原生模型与工具调用切片（已完成）

- 定位：优先补简历作品的 Agent 核心调用链，复用 OpenAI 官方 SDK 和 Pydantic，不扩展企业平台、安全治理或多供应商管理。
- 调研：重读 nanobot 固定 commit `23941355a8932609d7fc7ba2820f162d1ea7bea5` 的 runner 与 OpenAI Python SDK 官方示例；重点参考 assistant/tool 消息回注顺序、SDK timeout、关闭隐式重试和显式连接清理。GitHub tree API 仍受限，不把猜测路径当核验结果。
- [x] 用 Pydantic 参数模型生成工具 schema 并执行严格校验；保留完整 assistant tool_calls 与对应 tool_call_id，参数错误回注供模型修正。
- [x] 引入官方 OpenAI-compatible Chat Completions 适配器，明确模型/endpoint/key 配置、有限 timeout/output 上限、关闭 SDK 隐式重试、usage 与可读失败。
- [x] 提供独立真实模式启动和可复现 smoke 脚本（普通回答 + 原生 tool calling）；未配置时明确失败，保持 fixture 入口可独立运行。真实供应商执行仍待 Key。
- [x] 用官方 SDK 的模拟 HTTP transport 验证完整请求/回注与错误边界；合并同类验证为少量行为测试，完成后执行一次全套 CI 与 20 例离线回归。
- [x] 更新复用记录、架构、README、history/学习笔记并随本切片提交。本轮不配置外部 Key，不把模拟服务或 SDK 协议测试称为真实供应商 smoke。
- 已收敛：上一 HTTP/SSE 切片独立提交 `7dd6126`，基线 57 Python + 19 Node 测试通过；后续测试增长以新增行为边界为依据。
- 验证：`uv sync --locked --group dev` 成功；核验安装 SDK 的 metadata、LICENSE 与所用参数。`npm.cmd run ci` 通过文档/仓库/Action 检查、Python import 边界、61 个 Python 测试和 19 个 Node 测试；`npm.cmd run eval:offline` 通过 20/20，`npm.cmd run smoke:fixture` 成功。
- 协议证据：官方 SDK + HTTPX MockTransport 验证多工具消息配对、错误参数修复、usage 汇总、实际 HTTP 请求参数、超时/连接/HTTP 错误脱敏和零重试；real factory 测试验证缺配置失败、有限超时配置和 lifespan 客户端清理。
- 剩余范围：真实供应商 smoke 未执行；当前 real 入口仅注册 echo，使用 `max_tokens` 的 Chat Completions，未接业务工具、Responses API 或 token streaming。React、完整业务 HTTP/SQLite 与 M5 最终交接继续按总计划推进。

## 节点学习上下文与只读业务工具切片（已完成）

- 原因：此前节点入口只发送用户文本，真实 API 只装配 echo；需让 Agent 读取已确认目标、已发布节点、前置依赖和持久化练习表现，并复用服务端推荐规则。
- 范围：应用层上下文装配与 `get_learning_context` / `get_next_action` 工具；Loop 按请求准备独立 Runner；真实 API 使用已有 SQLite repository；HTTP 节点上下文/推荐与 Agent 工具复用同一用例。演示脚本提供明确标记的离线闭环和可选真实调用。
- 不在本切片内：生成/资料工具、会话历史持久化、完整规划 HTTP、React 与 token streaming。后续按总计划继续实施，不能据此宣称 P0/P1 已完成。
- 参考：2026-10-13 已通过 GitHub raw 读取 nanobot 固定 commit `23941355a8932609d7fc7ba2820f162d1ea7bea5` 的 `nanobot/agent/context.py`，参考系统指令/业务数据/当前输入在进入 Runner 前装配的分工；不摘取其记忆、skills、媒体或 workspace 能力。
- [x] 实现每次请求独立的上下文/工具集合，绑定目标/节点，校验发布状态、完整图谱快照和 run 内版本；工具 schema 不接受作用域参数，不注册业务写入工具。
- [x] real factory 使用 SQLite planning/learning repository；HTTP context/next-action 与工具复用 `LearningContext`。新增 `demo:learning-agent`，默认临时 SQLite，指定新路径可保留演示数据，拒绝覆盖已有文件；可选 --real 不进入默认验证。
- [x] 以 5 个行为测试聚合持久数据工具回合/参数修复、barrier 并发隔离与 session 绑定、未发布/缺失/过期拒绝、real HTTP factory 共用用例与错误映射、demo 防覆盖；原测试/demo/eval 调用方迁移到场景装配，未放宽断言。
- [x] 同步 README、架构、来源、tech debt、history/learning，完成审查。本切片独立提交，总计划仍 active。
- 验证：`npm.cmd run ci` 通过文档/仓库/Action 检查、Python import 边界、66 个 Python 测试与 19 个 Node 测试；`npm.cmd run eval:offline` 通过 20/20；`smoke:fixture`、`demo:fixture` 与 `demo:learning-agent` 全通过。既有 shutdown 测试的 graceful timeout/CancelledError 与 TestClient 弃用提示仍是已知输出；退出码为 0。
- 测试收敛：只新增 5 个覆盖不同边界的行为测试，沿用原有 HTTP 生命周期、SDK 序列化与领域算法验证；未为相同规则再建镜像测试。旧离线评测与 demo 的生成文件无内容变化。
- 限制：真实供应商 smoke/业务 demo 未执行。数据在分别读取的 SQLite repository 中，没有跨仓库事务或图谱迁移协议；`start_goal` 会重置学习状态，只用于首次初始化或隔离 fixture，不能作为只读上下文的自动修复。历史对话、资料/出题工具、完整规划/练习 HTTP、React 与 M5 最终交接仍待后续切片。

## Agent 资料检索与回答引用切片（已完成）

- 目标：节点 Agent 实际读取显式绑定资料；每轮稳定分配 C1 等引用，回答来源可从 HTTP/SSE 取得并定位原文。未知、解绑和过期来源不得成为有效引用。
- 参考：已读取 LlamaIndex 固定 commit `5b7b6e323e1da3edd787a2104a89257c14f026d0` 的 `citation_query_engine.py` 与 MIT LICENSE；参考检索结果先编号再进入回答上下文的分工，不复制源码、不引入其框架。存在性校验不证明语义支持。
- [x] 接入两只资料只读工具，复用 DocumentService/SQLite FTS5；严格参数、绑定范围、结果限额、run 内稳定来源表与完成时验证。
- [x] Loop 接受场景产出的公共结果，不内嵌引用规则；HTTP/SSE 返回来源表，原文定位再次检查绑定与内容版本。
- [x] 演示串起真实 SQLite 检索、读取、回答与空召回；新增少量行为测试覆盖多次检索、跨范围/未知引用、内容改变/解绑、并发隔离、HTTP/SSE。
- [x] 执行 CI、离线评估和 demo；同步文档/history/learning 并提交。
- 验证：`npm.cmd run ci` 通过（72 Python + 19 Node）；`eval:offline` 通过 20/20；`demo:learning-agent`、`demo:fixture`、`smoke:fixture` 通过；`git diff --check` 通过。真实供应商 smoke/demo 未运行。
- 修复与收敛：首次 Python 回归发现 HTTP 递归删去来源中的 `page_number:null`，与 SSE 不一致；改用 exclude_unset 后 72 项全通过。只新增 6 个聚合行为测试，覆盖检索/参数修复/稳定来源、无资料/空召回、变更/解绑、并发、HTTP/SSE/定位、结果投影取消/异常/预算，复用既有生命周期与 SDK 测试。
- 范围边界：本切片不完成 PDF/上传解析、jieba/BM25 升级、图谱/出题/学习页 grounding、React 或真实供应商评测；总体计划保持 active。

## 练习生成与共享调用预算切片（已完成）

- 原因：现有出题仅为 fixture，直接任务与工具内模型调用尚未共享预算；新增真正调用 ModelGateway 的结构化生成用例，贯通生成、私有答案保存、公共题目与确定性作答。
- [x] BudgetedModelGateway 统一计数与 usage，Runner/工具内部生成/至多一次修复共用父 run 预算；直接任务接入同一 Loop 生命周期。
- [x] GenerateExercise 复用 Pydantic 与现有领域规则；稳定 operation key、原子保存、当前内容版本校验、公共/私有字段隔离。按钮和教学工具调用同一用例。
- [x] HTTP 生成/题目读取/作答接入已有 SQLite；验证共享预算、修复失败不保存、取消、幂等冲突、并发与答案隔离。教学工具仅在明确教学模式开放，资料问答沿用只读集合。
- [x] 更新 demo、文档/history/learning，执行 CI/离线评估并提交。
- 范围：本切片先生成明确标为“非基于上传资料”的练习；资料型练习 grounding、图谱规划完整 HTTP、会话持久化、React 与真实供应商证据继续留在总计划。
- 验证：`npm.cmd run ci` 通过（78 Python + 19 Node、文档/仓库/Action 检查与 Python import 边界）；`eval:offline` 为 20/20；`demo:fixture`、`smoke:fixture` 通过；`demo:learning-agent` 修复时间序列化后通过。既有 shutdown graceful timeout/ASGI CancelledError 与 TestClient 弃用提示仍出现，退出码为 0。真实供应商 smoke/demo 未运行。
- 失败记录：首次新测试因复用原 session/request 请求缺失节点而得到幂等冲突 409，改为独立 request ID 后验证 404；独立 demo 暴露新增反馈 datetime 不能 JSON 序列化，改为 ISO 时间并在原 demo 测试中验证整个输出可序列化。
- 修复后验证：定向 `uv run python -c` 先遇缓存权限，获准后因没有设置 src import path 而失败；改回项目正式 `npm.cmd run test:py`，78 项通过。demo 命令、文档骨架与 diff 检查均通过；未重新运行与最终序列化修复无关的 Node/eval。
- 测试收敛：新增六个聚合行为测试，覆盖直接/工具共用预算、一次修复、失败无半批、六次成功/第七次阻止、retry 复用/新 root、SQLite 竞争及冲突、取消/规划变化、HTTP/SSE 公共投影与并发首答；复用现有生命周期、SDK 与领域规则测试。SQLite registry 使用独立复合主键，模型调用不持有事务。
- 限制：只实现调用/步骤/工具次数与协作取消，尚无 token/context/deadline；run/root 关联仅内存，不能通过旧 run ID 跨进程 retry；planning/learning 无跨仓库事务，保存前重读不能消除并发规划变更的窄窗口。整体计划仍 active。

## 目标澄清与图谱生成 HTTP 切片（已完成）

- 范围：目标列表/创建/编辑/确认，最多两轮模型澄清，结构化图谱生成、草稿替换/发布；复用 Loop、共享 gateway、Pydantic 与 SQLite。模型结果最多修复一次，不能自动确认或发布。
- [x] 增加独立 planning version 与原子 mutate，验证生成期间编辑、同时发布和失败回滚；兼容旧 SQLite 快照。
- [x] 补齐节点解释、学习结果与优先级，更新直接消费者保留字段；目标/图谱 HTTP 严格 Schema，版本冲突返回 409。
- [x] 直接规划任务共用全局准入、预算与取消；验证两轮上限、候选失败不保存、取消、HTTP/SSE 和重启恢复。
- [x] 同步文档/history/learning，完成相关检查、CI/eval/demo 并独立提交。
- 边界：本轮图谱生成仅 general；有 document_ids 的目标拒绝生成，避免假 grounding。已发布路线不允许整批草稿覆盖，后续修改走现有提案用例；前端、资料型规划、session/run 持久化、真实供应商验证仍待后续。
- 审查修复：生成输出改为本次提交快照，避免保存后重读混入后续编辑；空目标 PATCH 返回 422；内部兼容 update_node/add_dependency 保留 published 转 draft 行为，HTTP/模型禁止直接覆盖。real gateway 输出上限默认调整为 4096，尚未经真实模型验证。
- 一致性限制：首次 HTTP 发布后初始化学习快照，两仓库写入非原子，中断恢复与成绩迁移仍待后续。资料绑定重查也非同事务；规划未提交失败可 retry，提交后取消需先 GET 最新规划并重新审核版本，没有持久生成 operation。
- 测试收敛：新增七个聚合行为测试，覆盖澄清/跳过、图谱修复/共享预算/retry/取消、提交快照竞争、SQLite 编辑/发布竞争与回滚、HTTP 全流程/重启、共用准入及 grounding 拒绝、旧表迁移与推荐优先级；复用已有生命周期/SDK/领域规则测试。
- 验证：`npm.cmd run ci` 通过文档/仓库/Action 检查、Python import 边界、85 个 Python 测试与 19 个 Node 测试；`eval:offline` 为 20/20；`demo:fixture`、`demo:learning-agent` 与 `smoke:fixture` 均退出 0（后者终端中文显示乱码）。离线报告/demo 生成文件无内容变化；既有 shutdown graceful timeout/CancelledError 和 TestClient 弃用提示仍出现。真实供应商 smoke/demo 未运行。
- 失败及修复：首轮新增测试三个失败，分别使用了不存在的 Budget.cancel()、过早 close 触发取消、Windows sqlite connection 未显式关闭；修正测试的取消标志、执行等待与 closing 后 84 项通过。审查增加提交快照竞争用例并修正实现后，CI 85 项通过。总体 P0/P1/M5 仍未完成。
