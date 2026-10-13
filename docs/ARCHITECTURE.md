# 架构总览

LearnGraph Lite 是本地单用户运行的学习 Agent Web 应用。当前已建立 Python 分层骨架、独立 Agent 内核、应用层 AgentLoop、领域学习规则、FastAPI 运行生命周期与实时 SSE、planning/document/learning/lesson 最小 SQLite 持久化、OpenAI-compatible 适配器和离线测试；React、完整业务 HTTP/持久化与真实供应商 smoke 仍按执行计划推进。

正式规格以 docs/从零构建功能文档.md 为准。本文记录当前实现边界，避免把目录名误当作架构完成。

## 顶层结构

- src/learngraph_lite/agent_core/：通用 AgentRunner、工具注册表、模型协议和预算控制。不能导入 LearnGraph 领域、HTTP、ORM 或基础设施。
- src/learngraph_lite/domain/：学习领域纯规则，例如图谱校验和掌握度计算。不能导入 Agent 内核、应用层或基础设施。
- src/learngraph_lite/application/：应用用例与编排。当前包含 AgentLoop，负责运行准入、幂等、预算注入、运行摘要、公共事件和唯一终态。
- src/learngraph_lite/infrastructure/：基础设施适配器。当前有 `SQLitePlanningRepository` 保存目标草稿、澄清轮次和当前图谱快照；`SQLiteDocumentRepository` 保存原文件、解析状态、文本/chunk、目标/节点绑定和 jieba/FTS5 BM25 索引；`SubprocessDocumentParser` 使用 pypdf/UTF-8 解码与有限子进程超时；`SQLiteLearningRepository` 保存学习图谱、私有练习、作答和节点学习请求幂等结果；`SQLiteLessonRepository` 保存学习页 package、事件 ACK 和解释任务幂等/失败重试状态；`OpenAIChatGateway` 适配官方模型 SDK。完整业务 SQLite schema 和前端原文页仍待接入。
- src/learngraph_lite/presentation/：公共 DTO/SSE 编码与 FastAPI app factory。路由只校验输入、映射应用错误、编码快照/事件，不执行模型或修改终态。
- src/learngraph_lite/bootstrap.py：显式装配 fixture 模型与独立 real HTTP factory。真实配置只在装配时读取，SDK 懒导入；fixture 不依赖 SDK 导入，也不会回退到真实模式。导入包本身不启动 Web 或数据库。
- tests/：同时保留模板 Node 工具测试与新增 Python 架构/内核/领域测试。
- scripts/check-python-boundaries.py：轻量 AST import 边界检查。

## 依赖方向

允许方向：

    presentation -> application -> domain
    presentation -> application -> agent_core
    infrastructure -> application/domain/agent_core 的端口或协议
    bootstrap -> presentation/application/infrastructure

当前 SQLite 持久化边界：已覆盖 M2 planning state 的 `save/get/create/list_ids/mutate` repository port，包含独立 version、澄清轮次/问题和图谱快照；M4A document repository 的原始 BLOB/解析状态/文本/chunk/绑定/引用定位/FTS5 检索；M3 learning repository 的学习图谱/私有练习/作答/节点学习请求幂等结果；以及 M4B lesson repository 的 package、事件 ACK、解释 run 与失败重试最小状态。planning 启动时补旧表缺失列，旧节点/图谱可读取默认新增字段；learning 启动补 exercise 的 sources_json，空旧 metadata 默认 general，保存每题的来源模式、引用 IDs 与表；document 启动补 hash/heading 列并在分词版本标记变化时重建索引。它没有引入 ORM、迁移工具或 P1 全量业务表，也不覆盖完整运行生命周期、React 或完整 schema 迁移。

当前离线检查覆盖：

- agent_core 禁止导入 application、domain、infrastructure、presentation。
- domain 禁止导入 agent_core、application、infrastructure、presentation。
- application 禁止导入 infrastructure、presentation。

这些检查只证明当前 Python import 边界，不能证明未来 HTTP、数据库和前端边界自动成立；新增适配器时需要继续补测试。

## 当前运行拓扑

M1 fixture smoke 使用 python -m learngraph_lite.bootstrap：bootstrap 装配 fixture model、AgentRunner 和 echo tool，AgentLoop 创建一次 run，Runner 完成模型-工具-模型回合。fixture 输出必须标记为演示模式，不能作为真实模型能力证明。

`OpenAIChatGateway` 位于 infrastructure，使用官方 SDK 将 Chat Completions 映射到内核协议。`TextMessage` 保存 assistant 的完整 `tool_calls`，Runner 先追加 assistant 消息，再按原始 `tool_call_id` 追加对应结果；多个调用和错误参数也按相同顺序配对。`Tool.from_model` 由 Pydantic 生成 schema，执行时禁止额外字段和隐式类型转换，校验错误作为 tool 消息供模型修正；原有 dict schema 工具仍可使用。

真实入口从环境变量显式创建 gateway、SQLite planning/learning/document/lesson repository 和 AgentLoop，缺失模型配置时启动失败。数据库默认 `.local/learngraph.sqlite3`，可由 `LEARNGRAPH_DATABASE_PATH` 指定；启动不创建演示目标或重置成绩。无作用域请求使用 echo registry；节点请求进入 `LearningContext.prepare()`，装配独立 Runner，默认使用只读业务工具，显式 teaching 模式增加练习与学习包生成工具。SDK 关闭隐式重试、设置有限网络超时和 `max_tokens` 输出上限（默认 4096），超时/连接/HTTP 错误转换成不带供应商原始响应的失败信息；截断、空结果和不支持的调用拒绝视为成功。lifespan 先关闭 loop 并等待 worker 退出，再关闭 SDK 客户端。`scripts/run-model-smoke.py` 提供自选的普通回答与工具回合验证，当前供应商协议只有官方 SDK + MockTransport 的离线证据。

`LearningContext` 复用 planning repository 与 `LearningService`，要求已确认目标、已发布图谱、合法节点以及与学习状态完全一致的图谱快照。初始消息按“版本化 system 指令 → JSON 业务数据 → 当前用户输入”装配；不加载历史对话。上下文仅投影当前节点、直接前置依赖和计分后的表现，不包含练习私有答案。`get_learning_context` / `get_next_action` 闭包绑定本次目标/节点，Pydantic schema 不暴露作用域参数；推荐调用领域规则，模型不能写成绩或重定义推荐算法。每次调用检查当前发布状态与版本，过期工具错误回注模型；不自动重置或迁移成绩。

HTTP 的 context/next-action 路由复用相同用例，有限的同步 SQLite 读取由 FastAPI 同步路由执行，不占用 ASGI 事件循环。当前 planning/learning repository 仍分别读取，不提供跨仓库事务或并发发布同步协议；完整图谱变更与学习状态迁移需后续实现。`scripts/run-learning-agent-demo.py` 可复现 SQLite fixture 工具回合，拒绝覆盖已有文件；可选真实模型调用仍未执行。

`DocumentTurn` 按本轮目标/节点注册 `search_documents` / `read_document_chunk`，复用 DocumentService 和 SQLite FTS5。检索最多返回 5 个片段，服务端分配本轮稳定 C1 等编号；读取只能使用已发出的编号。资料是数据，不是指令。完成时扫描 `[C1]` 等标记，校验绑定、文档版本、片段内容摘要值与引用位置，生成来源表、cited/status 和未验证编号；不校验回答是否被原文语义支持。旧同版本覆盖可被检测，完整资料版本管理仍待实现。

AgentLoop 会保存 run_id、session_id、内部目标/节点作用域、终态、摘要、usage、场景公共 output 和递增 seq 事件。`PreparedRun.project_output` 在 Runner 完成后、终态锁外生成结果，Loop 不包含引用业务规则；取消后不发布晚到来源，投影异常走同一 failed 终态。GET/快照/事件复制嵌套结果，避免调用方污染内部来源表。presentation 层把应用记录投影成公共 run DTO 与 SSE frame，不读取 Runner transcript，不承担业务终态写入。

HTTP 原文定位只接受 run_id 与本轮 citation_id，从保存的来源表和作用域调用应用用例，再次检查当前绑定、版本、内容与位置。未知编号返回 404，解绑/内容过期返回 409；GET run 中的来源状态保留完成时快照，原文点击反映当前可用性。同步 SQLite 读取在同步路由中执行；HTTP 和 SSE 保留相同来源表字段，包括无页码时的 null。

HTTP 的 `submit()` 在锁内原子检查请求去重/输入冲突、session 作用域和 session/全局准入，再交给最多两个工作线程执行；不会等待模型返回。节点学习目标/节点必须成对，同 session 不能切换作用域；clarify/graph 为目标级例外，要求 task_ref=goal:{goal_id} 且没有 node_id，HTTP 内部使用 planning:{goal_id} 串行化。场景准备在工作线程中执行，失败沿用唯一终态路径。同步 `run()` 继续供离线用例使用。公开取消终态与实际调用退出分开：取消唤醒订阅者并设置预算标志，只有工作线程退出才释放名额。晚到结果不会覆盖已提交终态。

SSE 原子捕获运行快照与事件序号，从该序号后等待新事件；状态和最后事件序号一起读取，避免终态与发流竞争导致漏发。等待通过异步线程桥接进行，不阻塞 ASGI 事件循环。每次重连重新读取当前快照，忽略历史游标，不提供重放。HTTP 边界限制本机 Host 与浏览器同源写请求。

Uvicorn 先等待 HTTP/SSE 连接结束才触发 lifespan shutdown，本地启动命令设置 2 秒 graceful shutdown，避免活跃 SSE 无限挡住生命周期关闭。其他启动器也需设置有限的连接关闭等待时间。随后 lifespan 会停止准入、取消活动 run 并等待工作线程退出；同步阻塞模型/工具必须自行设置有限超时，Python 线程无法强行打断供应商调用。

此 HTTP 切片的 run/事件/请求去重及 session 作用域保存在进程内存中；不覆盖完整 session 业务、历史对话、run 重启恢复或 token streaming。真实入口已装配目标澄清/图谱规划、planning/learning/document/lesson 场景、资料上传/解析/绑定/搜索、资料型图谱/练习/学习包生成与作答、学习包事件 ACK；解释 HTTP、提案 HTTP 与 React 待后续。当前按用户要求暂停开发以进行阶段总结和真实测试。

## 资料导入与解析

`DocumentImports` 在应用层检查文件大小、生成 UUID、保存原 bytes 并投递任务；两条解析线程、四个活动/排队名额，上传不调用 AgentLoop 或模型。`SubprocessDocumentParser` 在独立 Python 子进程中使用 pypdf 或严格 UTF-8/BOM 解码，20 秒超时由 subprocess.run 终止并回收。HTTP lifespan 等待导入线程关闭，单次解析受超时约束。

SQLite 状态按 uploaded→parsing→ready/failed/unsupported 转移。启动同步把遗留任务标 failed/interrupted，reparse 复用 bytes，ready 不重跑，revision 保持 1。成功状态、全文、chunk 和 FTS 写入在一个事务完成；保存失败一起回滚。完成写入要求当前仍是 parsing，解析中删除后晚到结果不复活资料。恢复假设同一数据库仅有一个 API 进程，不支持多个进程共享解析队列。

Markdown 按 ATX 标题切块并忽略代码围栏，PDF 按显式页码标记切块；chunk 保存原文精确 offsets、heading/page_number 和文本 SHA256。jieba search 分词用于索引和查询，参数化 MATCH 词表达式，SQL BM25 排序与 top5 限额，每块默认最多 320 字符；分值不是置信度。非 ready 上传排除检索，旧 upload_text 文本入口兼容保留。FTS5 不可用时启动失败并给出安装提示。

上传 HTTP 仅接收 multipart bytes；绑定/搜索在应用层检查目标/节点存在，节点绑定需先绑定目标。SQLite 绑定校验和写入持有同一写事务，避免删除/解绑之间留下孤立绑定。删除同时移除原文件、文本、索引和所有绑定，历史来源点击降级；React 原文查看器仍待后续。

`BudgetedModelGateway` 位于通用内核，为一次 run 的所有模型请求计数并累积 usage。Runner 复用同一包装器，教学工具和直接生成用例使用父 run 的 gateway；包装器禁止切换预算，避免重复计数。默认模型调用上限六次，JSON 修复最多一次且计入次数。当前尚无 token/context/deadline 控制；供应商网络 timeout 不等于 run deadline。

`GenerateExercise` 位于 application：请求结构化候选，经严格 schema 和现有领域规则校验，生成服务端题目 ID，再通过 learning repository `mutate` 原子保存整批私有题目和 operation。模型调用在事务外，保存前重读规划版本，事务内检查最新学习图谱、取消和重复题。SQLite 使用 `BEGIN IMMEDIATE` 与 `learning_generation_operations` 的 `(goal_id, operation_key)` 主键；首次作答和 submission 去重也在同一学习事务完成。planning/learning 分别读取仍留下并发规划变更的窄窗口，后续需统一同步协议。

按钮 `mode=exercise` 走 Loop direct handler；教学 `mode=teaching` 注册闭包绑定节点的 `create_exercise`，调用相同用例。operation key 使用 root task、操作类型、节点、内容版本和固定 purpose slot；count/purpose 属于 fingerprint，同键不同参数冲突。失败任务显式 retry 创建新 run 并保留 root；新任务创建新 root。私有候选及修复对话不回注教学 transcript，ToolResult/公共 DTO 只含公共题目及其来源表，提交反馈才返回答案。每题和回答的 C1 独立，题目来源不能并入回答表；生成 registry 可重读恢复，但 root/run 关联仍未持久化。

`GeneratePlanning` 复用 Loop direct handler、共享 BudgetedModelGateway 与严格 Pydantic 候选。澄清只对缺失字段提问，最多两轮；图谱默认十节点，包含解释、学习结果与优先级，校验依赖和环，只保存 draft。模型调用在事务外，提交通过 planning repository `mutate` 在锁内或 SQLite `BEGIN IMMEDIATE` 中核对 expected_version、业务状态与取消；成功递增 version，失败回滚。run 输出取本次保存的快照，避免再次读取混入后续编辑。

planning version 覆盖目标/问题/草稿的每次写入，graph revision/content_revision 则沿用领域发布/提案语义。发布同时核对 planning version 与 graph revision；HTTP/模型拒绝覆盖 published，内部旧 update_node/add_dependency 仍保留转回 draft 的兼容行为。real HTTP 首次发布后调用 start_goal 初始化学习快照，两次写入并非跨仓库原子事务；中间退出会导致节点上下文拒绝未初始化状态，尚无恢复/迁移协议。

`GenerationSources` 为图谱/练习/学习包复用 DocumentTurn 的有界检索与服务端编号：图谱只查目标绑定，练习与学习包只查显式节点绑定；query 截至500字符，top5、每块320字符，总片段最多1600字符。无绑定标 general；有绑定且空召回不调用模型，明确失败。实际片段进入生成上下文，候选只能选择此次引用 ID，documents 模式每项至少一个；正文标记必须列入该项 IDs，未知/重复引用拒绝。repair 共用同一来源表。保存前复验绑定集合和文档版本/hash/offset，但 document 与业务仓库不是同一事务，仍有并发变更窄窗口。

`GenerateLesson` 复用 shared gateway 和严格 Pydantic 固定组件联合类型，章节加组件最多20块。quiz_choice 只引用请求选中的同节点/内容版本已有题目，模型只接收 public DTO。模型调用在事务外，保存前复验预算、目标/图谱、资料与题目；lesson repository 的 mutate 在内存 RLock 或 SQLite BEGIN IMMEDIATE 中保存包和 generation operation，同节点 version 递增。内存仓库返回深拷贝，异常不提交；SQLite 为旧包补 metadata_json、事件补 package_version，schema0 包只读兼容 choice_card。

生成按钮与教学 create_lesson 调用相同用例，包、每题与回答分别保存来源表。历史包即使节点移除或学习快照尚未同步仍可读取，标 outdated；新事件检查当前 planning/learning 状态与包版本，首次 ACK 原子保存，重复 ID 返回首次 payload，不调用模型或修改成绩。旧离线 explain_event 已改为增量 mutate，避免模型返回后覆盖期间 ACK；它仍未把事件/slot、root task、首个 run 和输入原子关联，且无可恢复 run 存储，因此没有解释 HTTP，也不视为完整 M4B 验收。

图谱快照和每题分别持久来源表，发布保留图谱来源；人工修改/提案保留表、标 edited（无表为 general），不继承生成来源声明，同时校验引用 IDs 与正文标记。图谱 GET 从单份规划快照投影来源当前状态；图谱定位接口核对 planning version，旧版本返回409，当前没有图谱历史仓库。每题定位由 exercise_id 决定作用域，公共题目与幂等复用动态投影来源状态。未知引用404，解绑/删除/内容过期409；程序校验不证明原文语义支持。规划未保存失败可保留 root 显式 retry；没有持久 generation operation，提交后取消需先读取最新规划并重新审核版本。真实模型输出空间与生成质量仍待供应商验证。
