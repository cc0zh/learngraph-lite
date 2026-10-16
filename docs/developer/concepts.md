# 领域概念：什么属于目标，什么属于一次对话

LearnGraph Lite 是本机单用户学习应用，不是任意聊天都能改业务数据的通用 Agent。它把“讨论学习目标”“发布知识图谱”“围绕节点教学”“正式作答产生证据”分开：模型可以建议、解释和创建待审核产物，确认、发布、评分和版本规则由程序控制。

本页先建立修改业务所需的词汇；目录与责任见[架构与源码地图](architecture.md)，按动作追踪见[关键调用链](flows.md)。字段和请求示例以 [API 手册](../api-guide.md)为参考，当前入口以工作区源码为准。

## 用一个例子串起来

假设你要“学习 RAG 的检索部分”，创建目标后获得 `goal_id=G`（实际由客户端生成 UUID）。规划会话固定为 `planning:G`。Agent 提出“文档切块 → 检索”两个节点，`chunking → retrieval` 表示前者是后者的前置，不是目录父子关系。

你确认目标、审核并发布图谱后，在 `retrieval` 上新开会话 A，再新开会话 B：

- A、B 的聊天记录、输入草稿和模型有限历史各自独立。
- 在 A 中生成的练习 E、学习包 L，以及 E 的正式作答，B 也能读取，因为它们属于目标/节点，不属于聊天。
- 右侧查看 `chunking` 不会把 A 改绑到该节点；必须显式开始该节点的新学习会话。
- A 的回答、E 和 L 都可能出现 `[C1]`，但三个 C1 来自各自产物的来源表，不能互相替用。

这几个区分可以防止最常见的两类错误：把界面当前浏览位置当业务作用域，把“说已掌握”当已保存的学习证据。

## 目标、图谱与版本不是同一个东西

| 概念 | 实际含义与所有者 | 改动时要注意 |
| --- | --- | --- |
| 目标草稿 `GoalDraft` | `domain/learning/goals.py` 中的学习意图、范围、起点、可选投入和跳过字段；由 `PlanningService` 管理 | 自述基础未验证，不能写入掌握度；目标确认不是图谱发布 |
| 规划状态 `PlanningState` | `application/planning.py` 聚合目标、澄清轮次/问题、当前图谱和 `version` | 每次规划写入推进 version，用 `expected_version` 防止旧页面覆盖新状态 |
| 图谱 `GraphSnapshot` | `domain/learning/graph.py` 的目标级小型有向无环图，状态为 draft/published | 节点 1–30 个，只支持 prerequisite；生成只保存草稿，发布须用户明确操作 |
| 节点 `GraphNode` | 图谱内的知识单元，有标题、说明、学习成果、优先级和预计分钟 | `node_id` 在目标图谱内唯一，不是全局主题库 ID，也不是会话 ID |
| 图谱 `revision` | 图谱发布/提案修订使用的版本，提案以 `base_revision` 对照 | 规划字段 version、图谱 revision 不可互换 |
| 图谱 `content_revision` | 内容有效性的全局版本；题目和学习包记住生成时版本 | 内容/依赖提案推进它，旧题/包保留但只读；priority/minutes 修改不使内容失效 |
| 学习状态 `LearningState` | `application/learning.py` 的学习图谱、私有题目、作答与生成操作 | 读取要求学习快照与当前发布图谱相符；不能遇到冲突就重置成绩 |

上述 Python 路径均位于 `src/learngraph_lite/`。规划仓库目前只保存**当前**图谱快照，不是完整图谱版本档案。版本是并发保护和内容有效性规则，不表示已有任意历史回滚功能。

## 会话、任务与请求身份

`Conversation` 是持久会话目录元数据；`RunRecord` 是一次执行记录。会话可以一条消息都没有，run 完成也不等于业务发生了一次新写入。

| 身份/字段 | 谁分配、在哪个范围有效 | 用途与误用风险 |
| --- | --- | --- |
| `goal_id` | 工作台创建前由客户端生成 UUID；`ConversationService.create_goal` 保存 | 同 ID 同首次 title 幂等返回最新规划；不是让重发覆盖当前目标标题 |
| `session_id` | 新 learning/general 会话由客户端生成 UUID；planning 派生为 `planning:{goal_id}` | 会话目录固定 kind、goal/node；不能随 URL 或浏览节点改绑。旧兼容 session 仍可发现 |
| `request_id` | 客户端在 POST 前生成并保存；run 内部映射为 `RunRequest.idempotency_key` | `(session_id, request_id)` 相同且完整输入相同返回原 attempt；异输入冲突。不确定结果先查询再显式同 ID 重发 |
| `run_id` | `AgentLoop._admit` 分配 UUID | 标识一次执行 attempt，用于 GET/SSE/取消；不是“同一逻辑任务”的稳定身份 |
| `root_task_id` | 首次等于 run_id；显式 retry 沿用原 root | 生成产物按稳定操作键复用，避免“产物已存但运行结果丢失”后重复生成 |
| `retry_of_run_id` | 客户端显式指定失败/取消/预算耗尽/中断的 attempt | 新 request_id、新 run_id，保留原 session、完整输入和 root；省略它代表新任务，不是重试 |
| `task_ref` | HTTP 为目标级任务设置 `goal:{goal_id}` | planning/clarify/graph/proposal 可无节点；普通节点请求必须 goal/node 成对 |
| generation operation key | 生成用例按 root、操作、节点/内容版本和固定 slot 等构造 | 同键同参数复用，同键异参数冲突；它与 HTTP request 去重不是一层机制 |

### 会话类型和运行模式要分开看

- 目录类型是 `planning / learning / general`。目录只发现普通 runner/teaching 聊天，不把教材、解释或提案生成当新聊天。
- run 模式还有 `exercise / lesson / explanation / proposal / clarify / graph` 等。它决定装配哪个用例/工具，不是前端标签名。
- 新节点聊天默认 `teaching`，增加出题、生成学习包和创建图谱提案工具；`runner` 的节点工具只读。旧 runner 会话继续用原模式，不自动升级。
- 续聊只恢复同 session、同 mode 的 completed 协议回合，在最近运行窗口和输入预算内裁剪；没有跨会话长期记忆。

例如 A 中有一条 teaching 回合和一条按钮出题 exercise run，下一条 teaching 只能继承完成的 teaching 协议，不会把按钮生成的私有候选混进聊天历史。

## 正式练习、掌握度与推荐

`ExercisePrivate` 含正确选项和解析，保存在服务端；`ExercisePublic` 只给题干、选项、版本和来源。题目 ID 由服务端生成，属于 goal/node/content_revision。聊天里模型口头出的题不自动变成正式题，必须经 `GenerateExercise.generate` 校验保存。

正式作答通过 `submission_id` 去重，映射成 `Attempt.id`。同目标内相同 submission、同题同选项复用，改变题目或选项冲突；同一道题只有首次作答 `counted=true`。重答能保存反馈，不反复加分。判断只看私有答案，不调用模型。

掌握度来自 `domain/learning/mastery.py::score_mastery`：当前内容版本、不同题目的有效首次作答取最近五题；无样本为 unknown，至少三题且正确率不低于 80% 才为 proficient，其余为 learning。例如三道不同题全对可达练习熟练标准，同题重复答对三次仍只有一个样本。这个标准不是能力认证。

`recommend_next_action` 先排除已熟练节点并检查前置熟练条件，再考虑近期错题、priority、预计分钟和 ID；时间不足可返回短解释。它是确定性领域规则，模型只能调用并解释结果，不能自行重定义排序或写成绩。

## 学习包、ACK 与解释任务

学习包不是任意可执行 HTML，而是版本化固定组件：markdown、quiz_choice、stepper、comparison_table。`package_id` 标识一个不可覆盖的包，包 `version` 是同节点生成序号，`schema_version` 是渲染契约，二者都不是 graph content_revision。题卡只引用已存在的公共正式题。

- `event_id` 在目标内标识一次包组件事件，携带 package/version/component/action/payload。ACK 首次原子保存；同 ID 同包/版本/组件/action 返回首次 payload，不覆盖为后来传入的 payload。
- `mark_read` 和 `step_changed` 是交互记录，不是作答证据；ACK 不调用模型、不改掌握度。
- 解释先 ACK，再以 `(goal_id, event_id, explanation_slot)` 建逻辑任务；输入由服务端的包、组件、事件和公共题目构造，HTTP 不接收客户端解释正文。
- 同 event/slot 即使换 request_id 也复用最近 attempt；失败仍要显式 retry，新 slot 才是新解释。前端以会话隔离子 session/初始 slot，避免两个会话争用同一业务键。

实现位置是 `application/lesson_generation.py`、`application/lessons.py` 和 `frontend/src/lessons/`。历史包和已答反馈可读，过期/旧 schema 包不接受新事件；正式作答另按题目的内容版本校验，旧版本题目拒绝新作答。

## 资料、绑定与引用的边界

`document_id` 标识本地上传资料，`chunk_id` 标识切块；绑定不是上传的副作用。先绑定目标，才能追加该目标内的节点绑定。图谱生成只看目标绑定；节点问答、练习和学习包看显式节点绑定，不能因为目标绑定了文档就默认所有节点继承。

引用 `C1` 是服务端为**当前回答或当前产物**分配的局部编号；完整身份是“所属 run/图谱当前 version/exercise/package + C1”。来源表记录 document/chunk、文档 revision、offset、页码/标题、内容 SHA256、cited 和状态。

`valid` 表示当前仍能按绑定、版本、hash 和位置找到原文；`stale / unavailable` 表示内容变更或来源不可用。它不证明原文在语义上支持结论。run GET 保留完成时来源快照，点击原文会重新验证当前状态；题目、包和图谱的来源读取也会投影当前可用性。

例如题 E 的 C1 指向“切块笔记”，回答的 C1 指向“检索笔记”，应各用自身 citation endpoint，不能合并成一个“当前会话 C1”。人工编辑图谱会保留原定位表并标记 `edited`，不继承“资料已支持修改后内容”的声明。

## 图谱提案为何不是直接修改

已发布图谱不能由规划生成覆盖。`GraphProposalService` 先保存 pending 提案，仅支持 add_node、update_node、add_dependency、remove_dependency；模型没有接受/拒绝工具。用户审核时校验 base/expected revision，再原子更新提案、规划和学习快照。

这让“Agent 建议补一个前置节点”不等于“成绩被悄悄清空”。语义/依赖变化推进全局内容版本，历史题、attempt 和学习包保留，当前统计按版本重新计算；元数据调整只推进图谱修订。旧提案冲突会持久保存 conflicted，而不是覆盖新图谱。

## 从业务任务找概念和文件

| 想改什么 | 先确认的概念 | 源码入口 |
| --- | --- | --- |
| 浏览另一节点后继续原对话 | 浏览位置 ≠ 会话作用域 | `frontend/src/workbench/Workbench.tsx`、`application/conversations.py` |
| 用户填写了基础，是否免学前置 | 自述 ≠ 正式证据 | `domain/learning/goals.py`、`domain/learning/mastery.py` |
| 新增教学出题能力 | 公共题目 ≠ 私有候选 | `application/learning_agent.py`、`application/exercise_generation.py` |
| 重试后不重复保存产物 | request 去重 ≠ root operation 复用 | `application/agent/loop.py`、`infrastructure/run_persistence.py` |
| 调整学习包交互或来源展示 | ACK ≠ 作答；引用局部归属 | `application/lessons.py`、`frontend/src/lessons/`、`frontend/src/documents/Citations.tsx` |

后端简写路径均相对 `src/learngraph_lite/`；具体测试与执行顺序见[关键调用链](flows.md)。

## 已知边界与质量口径

系统只支持本机单用户、一个 API 进程配一个 SQLite；没有账号/多租户、跨会话长期记忆、任意组件执行、层级/相关关系图谱、自动扩展已发布图谱、OCR/Office 导入或完整图谱/资料历史版本仓库。初次发布与学习初始化仍是两次写入；资料复验与业务提交也不是统一事务。

fixture/mock 测试是契约证据，不是教学质量证明。历史真实 P0 结果早于当前工作台/规划 Agent/Skill，不能替代当前默认流程真实验收；P1 语义质量、20 例真实评估与最终交接仍未完成。持续状态只看[质量与验收](../QUALITY_SCORE.md)，限制看[技术债](../exec-plans/tech-debt-tracker.md)，故障操作看[稳定性与恢复](../RELIABILITY.md)。
