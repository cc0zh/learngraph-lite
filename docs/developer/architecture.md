# 架构与源码地图：从一个业务动作进入代码

先读[领域概念](concepts.md)，再用本页决定“这次需求应放在哪一层”。本页是新人阅读地图，不替代[架构总览](../ARCHITECTURE.md)的设计记录；具体时间顺序见[关键调用链](flows.md)。源码路径用行内代码，供在编辑器中打开，不作为文档站页面链接。

## 本页解决什么问题

- 当前工作台入口在哪里，页面和工具如何定位？
- UI、HTTP、应用用例、领域规则与 Agent 内核各负责什么？
- 修改一个能力，应从哪些源码与测试开始，事务保护到哪里？

只想理解某项能力的正常流程，请先看[核心机制](../core/index.md)；本页面向已经准备定位代码的读者。

## 当前界面只有一个工作台

`frontend/src/main.tsx::App` 只在 `/` 渲染 `Workbench`；其他未识别路径显示“页面不存在”。当前源码不是“目标列表首页加多张规划/学习页面”：

- 左侧是图谱/会话目录；中间是规划聊天、节点聊天/学习内容或工具；右侧是图谱和浏览节点。
- `frontend/src/workbench/navigation.ts::workbenchHref` 用根路径 query 表达位置，`navigateWorkbench` 保持单工作台导航并支持离开编辑的拦截。
- `canonicalWorkbenchURL` 把旧 `/goals/:id/plan`、`/goals/:id/learn`、`/documents` 等书签转换为根路径参数，`/library` 转成 `/`。这是只读定位兼容，不会创建替代目标/会话或自动执行模型。
- 例如 `/?goal=G&session=S&tool=graph` 在同一工作台打开图谱管理，资料入口使用 `tool=documents`；`source_goal/source_node` 是资料工具的来源定位，不是会话改绑参数。
- `frontend/src/pages/` 当前只保留嵌入式 `AgentPlanning.tsx` 和展示用 `RouteOverview.tsx`。旧 `Home.tsx`、`GoalGuide.tsx`、`Planning.tsx`、`Learning.tsx` 已移除，不应按历史 README 继续寻找独立页面。

**为什么先讲入口？** 修改按钮时若找错已删除的页面，会漏掉真实的 query 导航、作用域校验和恢复逻辑。前端路由变化也不意味着 `/api/...` 业务 API 已删除。

## 两条循环：业务用例与 Agent 执行

可以把系统画成下面两条路径，二者只在应用层交汇：

```text
React 工作台 → HTTP DTO → 应用用例 → 领域规则 → 仓库端口 → SQLite 适配器
                              ↓
                         AgentLoop（准入/状态/恢复）
                              ↓
                   PreparedRun 或 direct handler
                              ↓
                AgentRunner / 共享预算 gateway → 模型与工具
```

HTTP 不等待模型完成，先返回 run；GET/SSE 读取公开状态。正式确认、作答、事件 ACK、提案决定等确定性用例不需要模型。模型工具也要调用相同业务用例，不能开一条“聊天专用的写库捷径”。

## 责任边界：在哪里写，在哪里不写

下表后端路径均相对 `src/learngraph_lite/`。

| 层/目录 | 应负责 | 不应负责 |
| --- | --- | --- |
| `frontend/src/` | 浏览/草稿、显式授权、HTTP/SSE 状态、恢复身份、固定组件和安全 Markdown | 计算权威成绩、决定引用有效、靠 URL 改会话作用域、刷新自动重做写入 |
| `presentation/http.py`、`presentation/sse.py` | 严格请求 DTO、错误到状态码、HTTP → RunRequest、公共 DTO/SSE 投影、本机同源限制 | 模型循环、业务评分、直接改 run 终态或读取私有 transcript 给浏览器 |
| `application/` | 用例编排、作用域/版本/幂等、模型候选校验、公开结果投影、仓库端口 | 导入具体 SQLite 或 FastAPI，把并发保护交给 prompt |
| `application/agent/loop.py` | run 准入、会话串行/全局限额、唯一终态、取消、历史与恢复 | 图谱/题目/引用的领域规则；它通过 `PreparedRun.project_output` 委托业务投影 |
| `domain/` | 纯数据和规则：图谱、题目判分、掌握度、推荐、提案操作、学习包事件 | 调 HTTP/SDK、读环境变量、认识 Agent 内核或数据库 |
| `agent_core/` | 通用模型协议、原生工具调用配对、Runner、工具 schema、预算与输入裁剪 | 认识 LearnGraph 的目标/节点、FastAPI、SQLite 或 Skill 目录 |
| `infrastructure/` | SQLite 端口实现、OpenAI SDK、资料解析子进程、可信 Skill 文件读取 | 反向决定产品确认/发布流程；外部 I/O 细节不应泄漏到领域层 |
| `bootstrap.py` | 显式构造模型、仓库、应用服务、HTTP factory 和关闭顺序 | 包导入时自动启动服务或把 real 缺配置静默降级为 fixture |

允许依赖方向是 `presentation → application → domain/agent_core`，基础设施实现内层端口，bootstrap 装配所有层。`scripts/check-python-boundaries.py` 和 `tests/test_architecture.py` 检查 Python import 边界；它们不自动证明 HTTP、前端或事务边界正确。

## 实际目录导航

| 要找的能力 | 核心文件 |
| --- | --- |
| 工作台位置、创建、目录、浏览与焦点 | `frontend/src/workbench/Workbench.tsx`、`navigation.ts` |
| 节点对话和节点共享内容 | `frontend/src/workbench/Conversation.tsx` |
| 规划聊天卡片、确认和发布 | `frontend/src/pages/AgentPlanning.tsx` |
| 手工目标/图谱编辑、草稿冲突保护、提案入口 | `frontend/src/workbench/GraphManagement.tsx` |
| 前端请求/恢复、公共类型 | `frontend/src/api.ts`、`useRuns.ts`、`types.ts` |
| 固定学习包、正式题卡、事件身份 | `frontend/src/lessons/LessonPanel.tsx`、`QuizCard.tsx`、`persistence.ts` |
| 上传、绑定、原文与产物来源 | `frontend/src/documents/` |
| 图谱提案审核 | `frontend/src/proposals/ProposalPanel.tsx` |
| 会话元数据及创建/入队保护 | `application/conversations.py`、`infrastructure/conversation_persistence.py` |
| 规划用例与模型场景 | `application/planning.py`、`planning_agent.py`、`planning_generation.py` |
| 教学上下文与只读/写工具装配 | `application/learning_agent.py` |
| 题目生成、作答、学习统计 | `application/exercise_generation.py`、`learning.py`、`domain/learning/` |
| 学习包、ACK 和解释 | `application/lesson_generation.py`、`lessons.py`、`domain/lessons.py` |
| 资料导入、检索与来源校验 | `application/document_imports.py`、`documents.py`、`document_agent.py`、`generation_sources.py` |
| 图谱提案生成和原子审核 | `application/proposal_generation.py`、`proposals.py`、`infrastructure/proposal_persistence.py` |
| run 生命周期与持久恢复 | `application/agent/loop.py`、`infrastructure/run_persistence.py` |
| 通用执行、预算与供应商适配 | `agent_core/runner.py`、`tools.py`、`gateway.py`、`context.py`、`budget.py`、`infrastructure/openai_gateway.py` |
| 共享 Skill | `application/skills.py`、`infrastructure/file_skills.py`、`skills/` |

`infrastructure/persistence.py` 当前集中实现 planning/document/learning/lesson 仓库，不是一个通用 ORM。run、proposal、conversation 使用各自文件。`tests/` 有 Python 业务/协议测试和 Node 工具测试；`frontend/tests/` 是默认 fixture/mock Playwright 测试；`frontend/real-tests/` 是付费 opt-in 浏览器旅程；`evals/` 是评估输入和运行器。测试文件的存在不等于本轮已经执行。

## 从启动看真实对象如何接起来

1. `bootstrap.py::create_business_fixture_app` 用确定性 `BusinessFixtureModel`；`create_real_app` 经 `build_real_gateway` 显式读取环境和 `.env`，构造 `OpenAIChatGateway`。独立 `create_fixture_app` 仅装配 echo 协议示例，不是完整业务 UI 后端。
2. 二者的业务入口进入 `_create_business_app`：同一数据库路径构造 SQLite planning/learning/document/lesson/proposal 仓库、Skill catalog，并用 `LearningService.ensure_goal` 为已发布但缺学习状态的目标补建快照，不覆盖已有成绩。
3. `build_learning_loop` 创建 `LearningContext`、`PlanningContext`，注册 exercise/lesson/clarify/graph/proposal 的 direct handlers；teaching/planning 等装配独立 `PreparedRun` 与 Runner。它们共用本次 run 的预算 gateway。
4. `SQLiteRunRepository` 交给 `AgentLoop` 恢复旧记录，遗留 queued/running 变 interrupted；之后构造 `ConversationService`、`DocumentImports`，注入 `presentation/http.py::create_app`。没有恢复时自动继续模型流。
5. HTTP lifespan 关闭时先 `loop.close`，再关闭资料线程，最后关闭 gateway。启动命令给活跃 HTTP/SSE 连接有限 graceful shutdown 等待；协作取消不是强杀阻塞线程。

根目录 `npm run dev` 启动工作台和业务 fixture；`dev:api` 是独立 echo，`dev:api:real` 使用真实模型。完整配置、费用和 API 操作见 [API 手册](../api-guide.md)，Windows 命令入口见 [Windows 指南](../WINDOWS.md)。不要为阅读代码误启动付费 smoke。

## 事务到底保护什么

| 一致性边界 | 当前保证 | 不要推论为 |
| --- | --- | --- |
| 工作台目标创建 | `SQLiteConversationRepository.create_goal` 同事务保存规划初态与首次 title 指纹 | 目标创建和首次模型执行是一个事务 |
| 普通业务写入 | planning/learning/lesson 的 `mutate` 用短事务；题目批次与 operation、作答去重与首次计分同事务 | 所有聚合共用一个全局事务 |
| run 准入/状态 | request+queued 保存后入队；状态和新增生命周期事件同事务提交，成功后通知订阅者 | 每个 token 都是 durable 事件，或者公开 completed 可先于持久成功 |
| 提案接受 | 一个 `BEGIN IMMEDIATE` 连接更新 proposal/planning/learning，保留历史 | 初次 publish 也已原子化 |
| 初次 publish | 保存发布图谱后调用 `ensure_goal`，启动仅补缺失状态 | 两次写入之间没有中断窗口 |
| 资料型生成 | 模型在事务外；提交前复验绑定、版本、hash、offset | 资料仓库与业务提交没有并发窄窗口 |

模型网络调用不放进 SQLite 写事务，否则长调用会持锁拖住全部写入。与此同时，“提交前复验”不能替代真正的跨仓库原子协议；扩展业务前要先判断需求落在哪个一致性边界。

## 新人建议读源码顺序

1. **确认你在改哪个动作。** 打开 `main.tsx`、`Workbench.tsx`、`navigation.ts`，用“在节点 retrieval 点击开始学习”描述入口，而不是泛读全部组件。
2. **找 HTTP 转换。** 到 `presentation/http.py` 找对应 route 和 body model，再找 `RunRequest` 或确定性服务调用；同时看 `frontend/src/types.ts` 与公共 DTO。
3. **追应用用例。** 教学读 `LearningContext.prepare`，规划读 `PlanningContext.prepare`，作答读 `GenerateExercise.submit_answer`。先看输入/输出与失败分叉，再深入模型提示词。
4. **看规则及提交点。** 去 `domain/learning/` 找判分/推荐/图谱规则，然后找仓库 `mutate` 或 coordinator；确认版本、取消与幂等检查在何时生效。
5. **用测试反证理解。** 先读对应 `tests/test_*.py`，再看 `frontend/tests/` 的响应丢失、刷新和旧请求覆盖测试。链路和代表性测试列在[关键调用链](flows.md)。

例如“让十分钟推荐更合适”应先看 `domain/learning/recommendations.py` 和 `tests/test_learning_domain.py`，不是先修改教学 prompt；“让推荐按钮打开节点”则看 `Conversation.tsx::onBrowse` 到 Workbench 的浏览状态，不能顺手发起教学。

## 按任务选择修改面和验证面

| 任务 | 主要修改面 | 至少阅读/选择的测试 |
| --- | --- | --- |
| 改工作台工具导航或浏览焦点 | `navigation.ts`、`Workbench.tsx` | `frontend/tests/single-workbench.spec.ts`、`workbench.spec.ts` |
| 改规划问题、目标确认或路线生成 | planning_agent/planning_generation、AgentPlanning | `tests/test_planning_agent.py`、`test_planning_generation.py`、`frontend/tests/agent-planning.spec.ts` |
| 增加教学工具 | learning_agent、共享用例、严格 tool schema | `tests/test_learning_agent.py`、相关生成测试、`test_conversations.py` |
| 改正式评分/推荐 | domain learning、LearningService | `tests/test_learning_domain.py`、`test_learning_service.py`、`test_sqlite_learning.py` |
| 改引用或资料绑定 | document_agent/generation_sources/documents 与资料 UI | `tests/test_generation_sources.py`、`test_document_agent.py`、`frontend/tests/documents.spec.ts` |
| 改恢复/取消或解释身份 | AgentLoop、run repository、useRuns、LessonPanel | `tests/test_run_recovery.py`、`test_http_runs.py`、`frontend/tests/recovery.spec.ts`、`lessons.spec.ts` |
| 改持久结构或提案接受 | persistence/proposal coordinator 与兼容读取 | `tests/test_p1_proposals.py`、相关 SQLite 重开/回滚测试 |

代码纪律见[编码行为](../CODING_BEHAVIOR.md)和[编码规范入口](../coding-standards/README.md)。不要把 Python import 检查、fixture 旅程或一条真实旅程当成系统全质量证明；实际最新执行记录统一看[质量与验收](../QUALITY_SCORE.md)。当前真实模型语义质量、完整历史/迁移、多进程和硬中断等限制见[技术债](../exec-plans/tech-debt-tracker.md)与[稳定性与恢复](../RELIABILITY.md)。
