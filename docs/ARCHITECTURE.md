# 架构总览

LearnGraph Lite 是本地单用户运行的学习 Agent Web 应用。当前已建立 Python 分层骨架、独立 Agent 内核、应用层 AgentLoop、领域学习规则、FastAPI 运行生命周期与实时 SSE、planning/document/learning/lesson 最小 SQLite 持久化、OpenAI-compatible 适配器和离线测试；React、完整业务 HTTP/持久化与真实供应商 smoke 仍按执行计划推进。

正式规格以 docs/从零构建功能文档.md 为准。本文记录当前实现边界，避免把目录名误当作架构完成。

## 顶层结构

- src/learngraph_lite/agent_core/：通用 AgentRunner、工具注册表、模型协议和预算控制。不能导入 LearnGraph 领域、HTTP、ORM 或基础设施。
- src/learngraph_lite/domain/：学习领域纯规则，例如图谱校验和掌握度计算。不能导入 Agent 内核、应用层或基础设施。
- src/learngraph_lite/application/：应用用例与编排。当前包含 AgentLoop，负责运行准入、幂等、预算注入、运行摘要、公共事件和唯一终态。
- src/learngraph_lite/infrastructure/：基础设施适配器。当前有 `SQLitePlanningRepository` 保存目标草稿、澄清轮次和当前图谱快照；`SQLiteDocumentRepository` 保存文本资料、chunk、目标/节点绑定，并用 SQLite FTS5 做最小检索索引；`SQLiteLearningRepository` 保存学习图谱、私有练习、作答和节点学习请求幂等结果；`SQLiteLessonRepository` 保存学习页 package、事件 ACK 和解释任务幂等/失败重试状态；`OpenAIChatGateway` 适配官方模型 SDK。完整业务 SQLite schema、真实 PDF 解析和前端原文页仍待接入。
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

当前 SQLite 持久化边界：已覆盖 M2 planning state 的 `save/get` repository port、M4A document repository 的文本资料/chunk/绑定/引用定位/FTS5 检索、M3 learning repository 的学习图谱/私有练习/作答/节点学习请求幂等结果，以及 M4B lesson repository 的 package、事件 ACK、解释 run 与失败重试最小状态。它没有引入 ORM、迁移工具或 P1 全量业务表，也不覆盖完整运行生命周期、HTTP/React 或完整 schema 迁移。

当前离线检查覆盖：

- agent_core 禁止导入 application、domain、infrastructure、presentation。
- domain 禁止导入 agent_core、application、infrastructure、presentation。
- application 禁止导入 infrastructure、presentation。

这些检查只证明当前 Python import 边界，不能证明未来 HTTP、数据库和前端边界自动成立；新增适配器时需要继续补测试。

## 当前运行拓扑

M1 fixture smoke 使用 python -m learngraph_lite.bootstrap：bootstrap 装配 fixture model、AgentRunner 和 echo tool，AgentLoop 创建一次 run，Runner 完成模型-工具-模型回合。fixture 输出必须标记为演示模式，不能作为真实模型能力证明。

`OpenAIChatGateway` 位于 infrastructure，使用官方 SDK 将 Chat Completions 映射到内核协议。`TextMessage` 保存 assistant 的完整 `tool_calls`，Runner 先追加 assistant 消息，再按原始 `tool_call_id` 追加对应结果；多个调用和错误参数也按相同顺序配对。`Tool.from_model` 由 Pydantic 生成 schema，执行时禁止额外字段和隐式类型转换，校验错误作为 tool 消息供模型修正；原有 dict schema 工具仍可使用。

真实入口从环境变量显式创建 gateway、Runner、echo registry 和 AgentLoop，缺失配置时启动失败。SDK 关闭隐式重试、设置有限网络超时和 `max_tokens` 输出上限，超时/连接/HTTP 错误转换成不带供应商原始响应的失败信息；截断、空结果和不支持的调用拒绝视为成功。lifespan 先关闭 loop 并等待 worker 退出，再关闭 SDK 客户端。`scripts/run-model-smoke.py` 提供自选的普通回答与工具回合验证，当前只有官方 SDK + MockTransport 的离线协议证据。

AgentLoop 会保存 run_id、session_id、终态、摘要、usage 和递增 seq 事件。presentation 层只把这些应用层记录投影成公共 run DTO 与 SSE frame，不读取 Runner transcript，不承担业务终态写入。

HTTP 的 `submit()` 在锁内原子检查请求去重/输入冲突和 session/全局准入，再交给最多两个工作线程执行；不会等待模型返回。同步 `run()` 继续供离线用例使用。公开取消终态与实际调用退出分开：取消唤醒订阅者并设置预算标志，只有工作线程退出才释放名额。晚到结果不会覆盖已提交终态。

SSE 原子捕获运行快照与事件序号，从该序号后等待新事件；状态和最后事件序号一起读取，避免终态与发流竞争导致漏发。等待通过异步线程桥接进行，不阻塞 ASGI 事件循环。每次重连重新读取当前快照，忽略历史游标，不提供重放。HTTP 边界限制本机 Host 与浏览器同源写请求。

Uvicorn 先等待 HTTP/SSE 连接结束才触发 lifespan shutdown，本地启动命令设置 2 秒 graceful shutdown，避免活跃 SSE 无限挡住生命周期关闭。其他启动器也需设置有限的连接关闭等待时间。随后 lifespan 会停止准入、取消活动 run 并等待工作线程退出；同步阻塞模型/工具必须自行设置有限超时，Python 线程无法强行打断供应商调用。

此 HTTP 切片的 run/事件/请求去重保存在进程内存中；不覆盖完整 session 业务、run 重启恢复或 token streaming。已有学习业务 repository 未在 HTTP factory 装配，真实入口的 echo 也仅用于协议验证。
