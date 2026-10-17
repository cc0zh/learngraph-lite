# 架构总览

LearnGraph Lite是本地单用户学习Agent Web应用。React P0/P1及统一图谱工作台已接通：目标/图谱、独立会话、节点教学/练习/推荐、资料/引用、固定组件学习包/ACK/解释、图谱提案/人工审核。SQLite支持业务与运行恢复；提案接受原子迁移规划与学习版本。最新离线验收与工作台边界见下节；历史真实P0 HTTP/浏览器证据早于工作台改动，不能代替新流程真实质量验收。P1真实质量、20例真实评估和M5最终交接未完成。

产品要求与原始实施建议见[产品规格](从零构建功能文档.md)；本文记录当前采用的实现与差异，避免把目录名或设计建议误当作架构完成。实际 API/操作维护在 [API 手册](api-guide.md)，恢复手册见 [RELIABILITY.md](RELIABILITY.md)，当前验证状态只维护在[质量与验收](QUALITY_SCORE.md)。

## 统一图谱学习工作台

唯一业务界面 `/` 使用 `frontend/src/workbench/`：左侧图谱/会话目录，中间规划对话或独立节点聊天与学习内容标签，右侧图谱/浏览节点。资料列表/原文与图谱管理以 `tool=documents|document|graph` 在同一工作台主区打开，返回保留 `goal/session`。`navigation.ts` 区分 UI query 与 API 路径，原文 `document/chunk`、绑定 `source_goal/source_node` 独立于聊天范围；资料选择不能改写会话焦点。

会话元数据是作用域事实，不能被第二个 URL 参数或临时浏览节点覆盖。旧 `/library`、`/goals/:id/plan|learn`、`/documents[/:id]` 只在启动时只读归一化到工作台，不保留旧页面、固定问卷或自动创建替代会话。旧学习链接优先恢复本浏览器已选节点对应的既有 session；无记录时只浏览图谱，历史会话仍可从目录继续。业务 API、持久模型和历史数据未删除。

`GraphManagement` 承载直接目标表单、显式生成/反馈修订、节点/前置编辑、发布和 `ProposalPanel`；已发布图谱不能直接编辑。保存使用编辑起点 version，读到新版本保留本地输入但禁止覆盖；未保存编辑离开工具须确认。`Conversation` 在作答后读取确定性 next-action，展示练习熟练标准与推荐，查看推荐只浏览节点，不调用模型。

`ConversationService` 组合独立 SQLite 会话元数据、规划目录与旧运行只读发现；目录只归集普通 runner/teaching，不把教材/解释/提案当独立聊天。每个目标派生 `planning:{goal_id}`；learning/general 可在尚无 run 时持久存在。创建要求客户端 UUID，指纹相同幂等，变化则409。受管理会话所有 run 写入在入队前检查不可变 goal/node，普通会话不能发起教学；底层未注入目录的装配保留兼容行为。单数据库仍只支持一个 API 进程。

首页默认创建学习主题，普通聊天通过显式 `mode=chat` 进入；已发布规划提供主区节点入口，已有节点会话优先继续，但不合并历史，也不因导航发起教学。`useDeletion` 保存尚未确认的删除身份及已知 session IDs，读取核对与再次确认分离；仅成功删除或 GET 确认 404 后清理本浏览器作用域草稿/命令。页面内已删 session 标记阻止迟到 POST 回执重新写回命令缓存，不替代服务端持久准入保护。

生命周期通过应用层 `LifecycleRepository` 端口协调，SQLite 适配器在同连接短事务硬清聚合及专属运行记录，独立上传资料保留。锁顺序为 ConversationService 的 RLock → AgentLoop 的 Condition：检查真实活跃线程、提交删除、成功后清理 loop 内存记录，期间不准入同范围任务。SQLite 写入检查仅 ID 的 goal/session/run 删除标记，拒绝迟到重建及旧 SDK 回答缓存投影；持久化 run/submit 的准入事务复核目录与父作用域，不从 loop 锁内回调目录锁。不提供通用回收站或多进程删除协调。规划会话随主题清理，不能单删。

新教材/解释子 run 保存不可变 parent_session_id 并纳入请求指纹；旧无父关系子 run 仅在主题清理时可靠归集，不猜测跨会话归属。具体删除 API 及响应不确定行为见 [API 手册](api-guide.md)。

工作台目标创建使用 `POST /api/workbench/goals`：目标与首次 title 指纹在同一个 `BEGIN IMMEDIATE` 中保存；同 ID 同输入返回最新规划，旧入口已占用该 ID 或指纹变化返回409，不把新规划写入放入该事务。客户端在 POST 前保存创建身份、首轮 request_id；元数据确认后转交既有 run 恢复机制。刷新仅查询；待恢复目标不能从 fallback 发起另一首轮。429 保留原命令，确定性拒绝至少保留完整草稿，迟到成功不能清空新草稿。

界面统一但 transcript 不合并：旧 runner 续聊沿用 runner，新节点会话用 teaching。节点题目、成绩、教材仍由原仓库共享；学习包生成/解释使用按 conversation 持久的子 session。解释结果与来源相邻，步骤事件可共享，但其初始 slot 每条会话独立，避免服务端 `(goal,event,slot)` 幂等键跨会话冲突。未引入跨会话长期记忆。

规划提示词和共享 goal-planning Skill 优先组织主题范围与知识结构，不强制成果/预算；嵌入审核按知识节点展示，不默认按投入和阶段排任务。领域仍为小型、无环 prerequisite 图，没有新增 hierarchy/related 关系或自动扩展已发布图谱。实现决策见[工作台计划](exec-plans/completed/unified-learning-workbench.md)，当前测试数量不在此重复维护。

规划工具 `generate_route_draft` 的附加文字按服务端当前图谱状态分流：没有草稿时作为 `initial_guidance` 传给生成器，有草稿时才是 `feedback`，并附上当前图谱；模型填入非空 feedback 不能把首次创建误判为修订，也不能丢弃其范围要求。兼容直接 `/graph-drafts` 的修改反馈仍要求已有草稿，确认、版本和 published 保护不变。决策见[变更记录](histories/2026-10/20261016-1338-initial-graph-guidance.md)。

## 顶层结构

- src/learngraph_lite/agent_core/：通用 AgentRunner、工具注册表、模型协议和预算控制。不能导入 LearnGraph 领域、HTTP、ORM 或基础设施。
- src/learngraph_lite/domain/：学习领域纯规则，例如图谱校验和掌握度计算。不能导入 Agent 内核、应用层或基础设施。
- src/learngraph_lite/application/：应用用例与编排。当前包含 AgentLoop，负责运行准入、幂等、预算注入、运行摘要、公共事件和唯一终态。
- src/learngraph_lite/infrastructure/：基础设施适配器。当前有 `SQLitePlanningRepository` 保存目标草稿、澄清轮次和当前图谱快照；`SQLiteDocumentRepository` 保存原文件、解析状态、文本/chunk、目标/节点绑定和 jieba/FTS5 BM25 索引；`SubprocessDocumentParser` 使用 pypdf/UTF-8 解码与有限子进程超时；`SQLiteLearningRepository` 保存学习图谱、私有练习、作答和节点学习请求幂等结果；`SQLiteLessonRepository` 保存学习页 package、事件 ACK 和解释任务幂等/失败重试状态；`SQLiteRunRepository` 保存运行输入、session/root、协议历史、结果与事件；`OpenAIChatGateway` 适配官方模型 SDK。新增`SQLiteProposalRepository`注入短事务协调端口，同连接更新提案/规划/学习。React P1已接通，完整schema/图谱与资料历史迁移仍未实现。
- src/learngraph_lite/presentation/：公共 DTO/SSE 编码与 FastAPI app factory。路由只校验输入、映射应用错误、编码快照/事件，不执行模型或修改终态。
- src/learngraph_lite/bootstrap.py：显式装配 fixture 模型与独立 real HTTP factory。真实配置只在装配时读取，SDK 懒导入；fixture 不依赖 SDK 导入，也不会回退到真实模式。导入包本身不启动 Web 或数据库。
- tests/：同时保留模板 Node 工具测试与新增 Python 架构/内核/领域测试。
- scripts/check-python-boundaries.py：轻量 AST import 边界检查。

React 的未确认 POST 输入以原 request_id 保存到 localStorage，刷新只 GET；用户查询后显式同 ID 重发，由后端幂等定位任务。明确 HTTP 4xx 拒绝与网络/5xx 不确定结果分开；旧列表查询用版本淘汰，规划表单和草稿独立保护未保存编辑。合法旧节点 session 保留历史，超长作用域改为持久 UUID。SafeMarkdown 同时禁 raw HTML 与 img，避免模型图片自动外连；浏览器测试拦截非本机请求。

## 依赖方向

允许方向：

    presentation -> application -> domain
    presentation -> application -> agent_core
    infrastructure -> application/domain/agent_core 的端口或协议
    bootstrap -> presentation/application/infrastructure

当前 SQLite 边界覆盖 planning/document/learning/lesson/run/proposal/conversation。React 复用业务 API，所有模型调用在写事务外；各写入的一致性边界见下文与[恢复手册](RELIABILITY.md)，不能概括为所有业务都已跨聚合原子化。

当前离线检查覆盖：

- agent_core 禁止导入 application、domain、infrastructure、presentation。
- domain 禁止导入 agent_core、application、infrastructure、presentation。
- application 禁止导入 infrastructure、presentation。

这些检查只证明当前 Python import 边界，不能证明未来 HTTP、数据库和前端边界自动成立；新增适配器时需要继续补测试。

## 当前运行拓扑

M1 fixture smoke 使用 python -m learngraph_lite.bootstrap：bootstrap 装配 fixture model、AgentRunner 和 echo tool，AgentLoop 创建一次 run，Runner 完成模型-工具-模型回合。fixture 输出必须标记为演示模式，不能作为真实模型能力证明。

`OpenAIChatGateway` 位于 infrastructure，使用官方 SDK 将 Chat Completions 映射到内核协议。`TextMessage` 保存 assistant 的完整 `tool_calls`，Runner 先追加 assistant 消息，再按原始 `tool_call_id` 追加对应结果；多个调用和错误参数也按相同顺序配对。`Tool.from_model` 由 Pydantic 生成 schema，执行时禁止额外字段和隐式类型转换，校验错误作为 tool 消息供模型修正；原有 dict schema 工具仍可使用。

真实入口从环境变量显式创建 gateway、SQLite planning/learning/document/lesson/run repository 和 AgentLoop，缺失模型配置时启动失败。数据库默认 `.local/learngraph.sqlite3`，可由 `LEARNGRAPH_DATABASE_PATH` 指定；启动不创建演示目标或重置成绩。无作用域请求使用 echo registry；节点请求进入 `LearningContext.prepare()`，装配独立 Runner，默认使用只读业务工具，显式 teaching模式增加练习/学习包生成与propose_graph_change待审核工具。SDK 关闭隐式重试、设置有限网络超时和 `max_tokens` 输出上限（默认 4096），超时/连接/HTTP 错误转换成不带供应商原始响应的失败信息；截断、空结果和不支持的调用拒绝视为成功。lifespan 先关闭 loop 并等待 worker 退出，再关闭 SDK 客户端。`scripts/run-model-smoke.py` 提供普通回答与工具回合验证，`scripts/run-real-p0-smoke.py` 使用生产 HTTP 装配、真实 gateway 和有界计数包装器验证独立 P0 数据；本轮真实配置证据见执行计划，不以 MockTransport 或一条旅程代替通用兼容性/质量结论。 `scripts/real_browser_app.py`与opt-in Playwright使用同装配和14-call meter，从UI写操作验证独立P0数据；不进入默认CI。

`LearningContext` 复用 planning repository 与 `LearningService`，要求已确认目标、已发布图谱、合法节点以及与学习状态完全一致的图谱快照。场景先按“版本化 system 指令 → JSON 业务数据 → 当前用户输入”装配；Loop 在当前输入之前插入同 session、同 mode 的 completed 回合协议历史，保留 user/assistant/tool 和 assistant tool_calls/tool_call_id 配对。最近八条运行记录是候选窗口，失败/取消/未完成与不同 mode 不纳入历史；输入超限时按完整用户回合裁剪，保留必要业务上下文和当前任务，不是无限长期记忆。上下文仅投影当前节点、直接前置依赖和计分后的表现，不包含练习私有答案。`get_learning_context` / `get_next_action` 闭包绑定本次目标/节点，Pydantic schema 不暴露作用域参数；推荐调用领域规则，模型不能写成绩或重定义推荐算法。每次调用检查当前发布状态与版本，过期工具错误回注模型；不自动重置或迁移成绩。

HTTP context/next-action复用应用用例，同步SQLite读取不占用ASGI事件循环。只读规划/学习仍分别读取，并发版本变化时明确拒绝而不重置。`scripts/run-learning-agent-demo.py`复现fixture工具回合，拒绝覆盖已有库；可选真实资料问答需单独验收。

`DocumentTurn` 按本轮目标/节点注册 `search_documents` / `read_document_chunk`，复用 DocumentService 和 SQLite FTS5。检索最多返回 5 个片段，服务端分配本轮稳定 C1 等编号；读取只能使用已发出的编号。资料是数据，不是指令。完成时扫描 `[C1]` 等标记，校验绑定、文档版本、片段内容摘要值与引用位置，生成来源表、cited/status 和未验证编号；不校验回答是否被原文语义支持。旧同版本覆盖可被检测，完整资料版本管理仍待实现。

AgentLoop 会保存 run_id、session_id、内部目标/节点作用域、终态、摘要、usage、场景公共 output 和递增 seq 事件。`PreparedRun.project_output` 在 Runner 完成后、终态锁外生成结果，Loop 不包含引用业务规则；取消后不发布晚到来源，投影异常走同一 failed 终态。GET/快照/事件复制嵌套结果，避免调用方污染内部来源表。presentation 层把应用记录投影成公共 run DTO 与 SSE frame，不读取 Runner transcript，不承担业务终态写入。

HTTP 原文定位只接受 run_id 与本轮 citation_id，从保存的来源表和作用域调用应用用例，再次检查当前绑定、版本、内容与位置。未知编号返回 404，解绑/内容过期返回 409；GET run 中的来源状态保留完成时快照，原文点击反映当前可用性。同步 SQLite 读取在同步路由中执行；HTTP 和 SSE 保留相同来源表字段，包括无页码时的 null。

HTTP 的 `submit()` 在锁内原子检查请求去重/输入冲突、session 作用域和 session/全局准入，再交给最多两个工作线程执行；不会等待模型返回。节点学习目标/节点必须成对，同 session 不能切换作用域；clarify/graph 为目标级例外，要求 task_ref=goal:{goal_id} 且没有 node_id，HTTP 内部使用 planning:{goal_id} 串行化。场景准备在工作线程中执行，失败沿用唯一终态路径。同步 `run()` 继续供离线用例使用。公开取消终态与实际调用退出分开：取消唤醒订阅者并设置预算标志，只有工作线程退出才释放名额。晚到结果不会覆盖已提交终态。

SSE 原子捕获运行快照与事件序号，从该序号后等待新事件；状态和最后事件序号一起读取，避免终态与发流竞争导致漏发。等待通过异步线程桥接进行，不阻塞 ASGI 事件循环。每次重连读取当前快照，并按 cursor 补发有界事件窗口内的缺口；超出窗口时依赖快照恢复当前状态，而非无限 token 重放。HTTP 边界限制本机 Host 与浏览器同源写请求。

Uvicorn 先等待 HTTP/SSE 连接结束才触发 lifespan shutdown，本地启动命令设置 2 秒 graceful shutdown，避免活跃 SSE 无限挡住生命周期关闭。其他启动器也需设置有限的连接关闭等待时间。随后 lifespan 会停止准入、取消活动 run 并等待工作线程退出；同步阻塞模型/工具必须自行设置有限超时，Python 线程无法强行打断供应商调用。

 fixture HTTP 的 run/事件/请求去重及 session 作用域保存在内存；real HTTP 由 RunRepository / SQLiteRunRepository 持久化。启动恢复会将遗留 queued/running 标为 interrupted，不自动继续模型执行；业务 fixture 同样使用 SQLite；React P0 fixture 浏览器主流程、教学工具出题与失败/重试专项已通过，完整验证结果见执行计划。

运行准入使用 `BEGIN IMMEDIATE` 保存请求/queued记录；状态更新与新增一个递增事件也同事务提交，成功后才更新内存并唤醒订阅者。终态持久失败时 live 状态为 interrupted，停止新准入，保留 durable 的上一状态；该失败通知只在内存中，修复存储后重启会持久化 interrupted。不会把未保存的完成结果报告为成功。显式 retry 创建新 attempt、保留 root 与完整初始输入；持久生成 operation 使练习/学习包产物在重试时可复用。所有模型调用在事务外；后续节点回合可从已完成运行恢复协议历史，但启动恢复不会继续执行旧模型流或未完成任务。

## 共享 Skill

交互 Agent 已接入共享 Skill，详见[技能说明](agent-skills.md)：应用层 `SkillTurn` 过滤模式、构造摘要、注册 read_skill 并记录使用元数据；基础设施 `FileSkillCatalog` 安全解析可信仓库目录并固定启动快照。技能不新增工具权限，agent_core 不认识技能目录。`PreparedRun.prepare_history` 将旧技能工具正文替换为历史提示而保留协议配对；历史持久记录不被改写。显式技能只从本轮用户聊天输入识别，学习包事件解释的合成输入不触发；内层生成用例不自动继承技能。官方 real/业务 fixture factory 装配，独立 echo fixture 和未注入 catalog 的底层用例保持独立。

## 图谱提案与前端恢复

`GraphProposalService`依赖注入`ProposalCoordinator`，`SQLiteProposalRepository`在一个`BEGIN IMMEDIATE`连接读取/更新planning、learning、proposal及操作去重。生成/repair在事务外，模型只创建pending；严格四操作和base revision接受审核，conflicted提交后再返回409。接受显式迁移全局内容版本，保留题目/attempt/package历史；metadata只改计划revision。该事务不等于初次publish或所有资料/生成提交都已跨聚合原子化。

React恢复分层：公共终态SSE先应用已保存payload，后续GET失败不遗留running；history查询发现新终态触发一次产物刷新。学习包GET使用epoch，选择与loading/error不能被旧请求覆盖；稳定event/slot/request恢复与显式新slot分开。提案接受响应丢失通过只读图谱/列表同步，不猜测写入未执行或自动重发决定。

## 资料导入与解析

`DocumentImports` 在应用层检查文件大小、生成 UUID、保存原 bytes 并投递任务；两条解析线程、四个活动/排队名额，上传不调用 AgentLoop 或模型。`SubprocessDocumentParser` 在独立 Python 子进程中使用 pypdf 或严格 UTF-8/BOM 解码，20 秒超时由 subprocess.run 终止并回收。HTTP lifespan 等待导入线程关闭，单次解析受超时约束。

SQLite 状态按 uploaded→parsing→ready/failed/unsupported 转移。启动同步把遗留任务标 failed/interrupted，reparse 复用 bytes，ready 不重跑，revision 保持 1。成功状态、全文、chunk 和 FTS 写入在一个事务完成；保存失败一起回滚。完成写入要求当前仍是 parsing，解析中删除后晚到结果不复活资料。恢复假设同一数据库仅有一个 API 进程，不支持多个进程共享解析队列。

Markdown 按 ATX 标题切块并忽略代码围栏，PDF 按显式页码标记切块；chunk 保存原文精确 offsets、heading/page_number 和文本 SHA256。jieba search 分词用于索引和查询，参数化 MATCH 词表达式，SQL BM25 排序与 top5 限额，每块默认最多 320 字符；分值不是置信度。非 ready 上传排除检索，旧 upload_text 文本入口兼容保留。FTS5 不可用时启动失败并给出安装提示。

上传 HTTP 仅接收 multipart bytes；绑定/搜索在应用层检查目标/节点存在。SQLite 绑定校验和写入持有同一写事务；React documents模块支持上传/list/轮询/显式绑定/分页纯文本原文和产物引用；卸载停止读取，刷新只GET，删除/解绑明确确认。

## 共享预算与结构化生成

`BudgetedModelGateway` 位于通用内核，为一次 run 的所有模型请求计数并累积 usage。Runner 复用同一包装器，教学工具和直接生成用例使用父 run 的 gateway；包装器禁止切换预算，避免重复计数。JSON 修复最多一次且计入次数，输入超限按最旧完整用户回合裁剪。预算数值与取消/超时的操作边界集中见[恢复手册](RELIABILITY.md)，不能把 usage 汇总或 SDK timeout 当作硬预算。

`GenerateExercise` 位于 application：请求结构化候选，经严格 schema 和现有领域规则校验，生成服务端题目 ID，再通过 learning repository `mutate` 原子保存整批私有题目和 operation。模型调用在事务外，保存前重读规划版本，事务内检查最新学习图谱、取消和重复题。SQLite 使用 `BEGIN IMMEDIATE` 与 `learning_generation_operations` 的 `(goal_id, operation_key)` 主键；首次作答和 submission 去重也在同一学习事务完成。planning/learning 分别读取仍留下并发规划变更的窄窗口，后续需统一同步协议。

按钮 `mode=exercise` 走 Loop direct handler；教学 `mode=teaching` 注册闭包绑定节点的 `create_exercise`，调用相同用例。operation key 使用 root task、操作类型、节点、内容版本和固定 purpose slot；count/purpose 属于 fingerprint，同键不同参数冲突。失败任务显式 retry 创建新 run 并保留 root；新任务创建新 root。私有候选及修复对话不回注教学 transcript，公共 run/output 保留题目及来源表，但教学工具仅返回 exercise_ids/source_mode 回执，不把新题干和选项交回 tutor 续写解法；create_lesson 仍可引用回执 ID。提交反馈才返回答案。每题和回答的 C1 独立，题目来源不能并入回答表；生成 registry 与 real API 的 root/run 均可重读恢复。

工具可显式启用通用 `with_context`：Runner 在严格参数校验后通过独立参数提供宿主 transcript，模型 schema 不暴露可伪造的 messages。教学应用只提取最近 assistant 正文、限 6000 UTF-8 字节，交给出题器作避重复数据；按钮出题只取同 session/goal/node 最近八条记录内已完成教学/runner 的正文。生成器要求换用独立数值/场景，并把归一化后已包含于讲解的题干纳入一次 repair 校验，不判定任意语义等价。教学 Runner 单独启用 `retain_tool_text`，终态保留本轮工具前的演示及最终回执，不丢讲解、不拼接历史；普通/规划 Runner 默认行为不变。`teaching_guidance` 还按 Python 列表/元组主题注入已核对的浅拷贝/身份参考，不依赖可选 Skill 是否读取。提示和精确重复保护不构成模型正确性或默认不泄漏的保证，真实修复效果见质量记录。

兼容直接 clarify/graph 入口的 `GeneratePlanning` 复用 Loop direct handler、共享 BudgetedModelGateway 与严格 Pydantic 候选。旧澄清只对缺失且未主动跳过的字段提问，最多两轮；直接图谱入口默认十节点（规划 Agent 则自行选择 1–30），校验依赖和环，只保存 draft。`graph_feedback` 保存为 run 输入并参与去重/重试，当前草稿与用户反馈作为业务数据进入模型上下文，不能自动发布。模型调用在事务外，提交通过 planning repository `mutate` 在锁内或 SQLite `BEGIN IMMEDIATE` 中核对 expected_version、业务状态与取消；成功递增 version，失败回滚。run 输出取本次保存的快照，避免再次读取混入后续编辑。

React 规划默认由专用规划 Agent 驱动连续对话；直接目标表单及高级图谱编辑在工作台“图谱管理”，不再保留固定三题向导。目标级 `mode=planning` 与兼容 clarify/graph API 共用 `planning:{goal_id}` 串行会话；通过 PreparedRun 装配独立 Runner、当前领域快照与当前用户输入，复用有限 completed 协议历史、预算和 SSE。工具仅能读取、发问、提出目标草稿或生成路线草稿，没有确认/发布能力。发问与目标审核通过通用工具结束轮次语义由宿主强制停止，补齐同批未执行工具的协议结果，不把等待状态交给提示词保障。

动态问题、目标/路线审核卡及程序计算的图谱差异保存在 `output.planning_agent`。结构化答案引用原 run 与问题 ID，后端核对目标、版本和跳过/自定义值；旧卡不能静默覆盖当前方案。UI 以对话为主线，当前目标/路线作为可审核产物；用户点“确认目标并生成图谱”先调用确定性 confirm，再显式授权下一轮规划请求。挂载与刷新只 GET，确认丢失不自动重发、继续请求丢失沿用同 ID 显式恢复。模型或前端不能靠“用户说好”替代确认。

confirm API 在一个 mutate 中合并摘要并明确确认，不要求先 PATCH 再确认。跳过字段独立保存在 GoalDraft JSON，填写后清除；assumptions 是派生说明，SQLite 读取重建以避免旧“有能力/四周”假设进入生成上下文。自述基础始终未验证，不修改学习掌握状态。路线阶段用稳定拓扑排序显示投入与实践验证建议；Agent 选择节点数量，修订可缩减数量并说明差异，纯解释无需写图谱。已发布路线仍只经提案调整。验收见[Agent 主导规划](exec-plans/completed/agent-led-planning.md)，手动入口验收见[引导式规划计划](exec-plans/completed/guided-planning.md)。

planning version 覆盖目标/问题/草稿的每次写入，graph revision/content_revision 则沿用领域发布/提案语义。发布同时核对 planning version 与 graph revision；HTTP/模型拒绝覆盖 published，内部旧 update_node/add_dependency 仍保留转回 draft 的兼容行为。real/业务 fixture 在发布后及启动时调用 `ensure_goal`，仅在缺少学习状态时初始化，不覆盖已有成绩；初次发布两次写入仍非原子；提案接受已同事务显式迁移学习图谱/保留历史，语义/依赖使全局content_revision推进、旧题/包只读，metadata仅推进revision。

`GenerationSources` 为图谱/练习/学习包复用 DocumentTurn 的有界检索与服务端编号：图谱只查目标绑定，练习与学习包只查显式节点绑定；query 截至500字符，top5、每块320字符，总片段最多1600字符。无绑定标 general；有绑定且空召回不调用模型，明确失败。实际片段进入生成上下文，候选只能选择此次引用 ID，documents 模式每项至少一个；正文标记必须列入该项 IDs，未知/重复引用拒绝。repair 共用同一来源表。保存前复验绑定集合和文档版本/hash/offset，但 document 与业务仓库不是同一事务，仍有并发变更窄窗口。

`GenerateLesson` 复用 shared gateway 和严格 Pydantic 固定组件联合类型，章节加组件最多20块。quiz_choice 只引用请求选中的同节点/内容版本已有题目，模型只接收 public DTO。模型调用在事务外，保存前复验预算、目标/图谱、资料与题目；lesson repository 的 mutate 在内存 RLock 或 SQLite BEGIN IMMEDIATE 中保存包和 generation operation，同节点 version 递增。内存仓库返回深拷贝，异常不提交；SQLite 为旧包补 metadata_json、事件补 package_version，schema0 包只读兼容 choice_card。

生成按钮与教学 create_lesson 调用相同用例，包、每题与回答分别保存来源表。历史包即使节点移除或学习快照尚未同步仍可读取，标 outdated；新事件检查当前 planning/learning 状态与包版本，首次 ACK 原子保存，重复 ID 返回首次 payload，不调用模型或修改成绩。旧离线 explain_event 仅兼容既有 demo/eval；HTTP 通过 submit_explanation 从持久 ACK、包组件与公共题卡构造输入，拒绝客户端 user_text，只接受 request_explanation/step_changed。新解释在准入和执行前检查当前学习版本。

`lesson_run_tasks` 独立保存 `(goal_id,event_id,slot)`、root 和初始输入，不参与旧 lesson 表全量重写。SQLiteRunRepository 在同一短事务核对持久 ACK 的节点/包版本，提交逻辑关联与首次 run/request；重试核对原 root/input。Loop 在锁内按业务键复用最近 attempt，多个 request ID 不重复执行；跨 session/不同输入冲突，额外 request ID 不存别名，首次 request ID 仍指向首次 attempt。失败/取消/中断需显式 retry，新 slot 创建新任务。旧任务读取可复用完成结果，但不绕过新解释的当前版本校验。React lessons模块固定组件/历史题反馈/事件ACK/独立解释会话已接通；event/slot/request持久、显式恢复/新slot，列表epoch淘汰旧GET，终态事件/人工查询刷新产物。真实P1解释质量尚未验收。

图谱快照和每题分别持久来源表，发布保留图谱来源；人工修改/提案保留表、标 edited（无表为 general），不继承生成来源声明，同时校验引用 IDs 与正文标记。图谱 GET 从单份规划快照投影来源当前状态；图谱定位接口核对 planning version，旧版本返回409，当前没有图谱历史仓库。每题定位由 exercise_id 决定作用域，公共题目与幂等复用动态投影来源状态。未知引用404，解绑/删除/内容过期409；程序校验不证明原文语义支持。规划未保存失败可保留 root 显式 retry；没有持久 generation operation，提交后取消需先读取最新规划并重新审核版本。三节点 general P0 样例已真实通过，更多节点/资料型输出空间与生成质量仍待评估。
