# 关键调用链：从用户动作到可恢复的业务结果

本页帮助你回答：一次用户动作经过哪些层、在哪里真正写入、响应丢失后怎样恢复、用哪些测试验证。只想先理解使用过程，请从[核心机制总览](../core/index.md)进入；本页保留函数级追踪，不把摘要当作完整协议。

## 按动作选择调用链

| 用户动作 | 调用链入口 |
| --- | --- |
| 创建目标、审核草稿并发布 | [规划与发布](#规划与发布路径) |
| 节点对话、出题、交卷与查看建议 | [教学与作答](#教学与作答路径) |
| 阅读学习包、记录交互并追问 | [学习包与解释](#学习包与解释路径) |
| 上传、绑定资料与打开引用 | [资料与引用](#资料与引用路径) |
| 接受或拒绝已发布图谱的变更 | [提案审核](#提案审核路径) |
| 查询 run、接收 SSE、取消与恢复 | [运行与恢复](#正常执行与流式读取) |

阅读约定：下文后端简写路径相对 `src/learngraph_lite/`，前端和测试使用仓库根路径。每条链按执行顺序列出函数、协议转换、提交点和失败边界；测试名称是可定位的契约证据，**不是本页宣称已重新执行或真实模型验收通过**。当前结论只维护在[质量与验收](../QUALITY_SCORE.md)。

贯穿例子：目标 G 是“学习 RAG 检索”，图谱节点为 `chunking → retrieval`；用户在 retrieval 开会话 S，生成题 E、包 L，检索资料 D。G/S/E/L/D 是可读占位名，实际创建身份按[领域概念](concepts.md)的 UUID/作用域规则生成。目录责任见[架构与源码地图](architecture.md)。

## 1. 从一句意图到用户审核发布

```text
学习意图 → 目标草稿 → 用户确认
                         ↓
              图谱草稿 → 用户审核发布
```

**先抓住三件事：**Agent 只提出草稿，确认和发布由用户决定；目标与图谱状态分别保存；发布响应丢失先查询，初次发布与学习初始化不是一个原子事务。使用说明见[目标规划与图谱审核](../core/planning.md)。

### 规划与发布路径

1. **先保存创建身份，再创建目标。** `frontend/src/workbench/Workbench.tsx::create` 把 goal UUID、title、首轮 request ID 写 localStorage，调用 `POST /api/workbench/goals`。`presentation/http.py::create_workbench_goal` 将严格 DTO 交给 `ConversationService.create_goal`（`application/conversations.py`）；`SQLiteConversationRepository.create_goal`（`infrastructure/conversation_persistence.py`）在一个短事务保存 `planning_states` 与 `workbench_goal_operations`。这里没有模型调用。
2. **首轮进入规划会话。** `Workbench.tsx::initialRun` 先保存完整 command，再 POST `/api/goals/G/planning-runs`。`http.py::agent_planning` 转成 `RunRequest(mode="planning", session_id="planning:G", task_ref="goal:G", planning_version=...)`，经 `ConversationService.admit` 和 `AgentLoop.submit` 准入后返回 202，而非等待图谱生成。
3. **装配目标级 Agent。** `bootstrap.py::build_learning_loop` 的 `prepare` 调用 `application/planning_agent.py::PlanningContext.prepare`，生成 system 指令、JSON 规划快照和当前输入。`AgentLoop._execute` 在当前输入之前插入同 session/mode 的有限 completed 协议历史，再调用 `agent_core/runner.py::AgentRunner.run`。
4. **发问或提出目标草稿。** 工具闭包 `ask`、`propose` 分别对应 `request_clarification`、`propose_goal_draft`。后者调用 `PlanningService.edit_goal` 保存未确认草稿；二者声明 `ends_turn=True`，Runner 在成功工具后结束本轮，并补齐同批未执行工具的协议结果，不占着 worker 等用户回答。卡片进入 `output.planning_agent`。
5. **结构化回答和明确确认是两件事。** `frontend/src/pages/AgentPlanning.tsx::send` 可带 `response_to_run_id` 和问题 ID/值/跳过；`PlanningContext.validate` 校验原卡片、目标、版本、问题集合和是否被新卡取代。`AgentPlanning.tsx::confirmGoal` 则调用确定性 `/confirm`；`http.py::confirm_goal → PlanningService.confirm_goal` 在一次 mutate 内合并字段并确认。模型没有确认工具。
6. **明确授权后才生成路线。** 前端确认成功后显式发下一轮规划请求；`PlanningContext.prepare` 内 `generate` 调用 `application/planning_generation.py::GeneratePlanning.graph`。初次工具附加文字作为 `initial_guidance`，已有草稿才作为 `feedback`，由服务端快照决定分支。模型候选经严格 schema、图规则、来源校验，至多一次 repair，共享本次 run 预算；`PlanningService.save_graph_draft` 在提交时核对版本与取消，只存 draft。`route_changes` 计算实际差异，不依赖模型自报差异。
7. **发布是独立确定性动作。** `AgentPlanning.tsx::publish` 或 `frontend/src/workbench/GraphManagement.tsx::write` POST `/graph/publish`，带 `expected_version` 与 `expected_revision`。`http.py::publish_graph → PlanningService.publish_graph → domain/learning/graph.py::publish_graph` 校验并发布，再由装配的 `LearningService.ensure_goal` 初始化缺失学习状态。发布不会自动开始节点教学。

### 规划的不变量与分叉

- 创建同 ID/同首次 title 返回最新规划，不把它还原到 version 0；同 ID 异 title、或被其他创建入口占用，返回冲突。
- 目标未确认不能生成图谱；普通模型输出“用户同意”不能替代确定性 confirm。规划工具没有 publish 能力。
- 每轮规划工具至多一次写入；旧卡不能覆盖新方案。规划、旧 clarify/graph 共用 `planning:G` 串行会话。
- 所有模型调用在事务外，保存前复核 version/取消；已发布图谱不能走生成或公开 PATCH 覆盖，须走提案。
- 初次发布与 ensure_goal 是两次写入，不是跨仓库原子事务。中断后启动只补缺失学习状态，不重置成绩；响应丢失先 GET 核对，不自动再发布。

### 规划相关测试

- `tests/test_conversations.py::test_workbench_goal_creation_is_atomic_idempotent_recoverable_and_keeps_first_title_fingerprint`：目标与创建指纹、重放及恢复。
- `tests/test_planning_agent.py::test_native_ends_turn_question_skips_generation_batch_and_preserves_pairs`、`test_structured_answers_checked_by_host_before_model_with_ids_and_skips`：宿主结束轮次与卡片身份。
- 同文件 `test_first_route_tool_treats_feedback_as_initial_guidance_without_dropping_it`、`test_initial_route_guidance_does_not_bypass_user_confirmation`、`test_published_goal_cannot_be_rewritten_by_planning_tools`：首次附加要求、确认和发布边界。
- `frontend/tests/agent-planning.spec.ts`、`frontend/tests/workbench.spec.ts`：显式审核、创建/确认响应丢失、刷新只读和迟到结果保护新草稿。

## 2. 从节点教学到正式作答与推荐

```text
开始节点对话 → 教学与正式出题
                         ↓ 用户交卷
              程序判分 → 掌握度与建议
```

**先抓住三件事：**浏览节点不改绑对话；题目和成绩属于节点，聊天属于会话；只有有效正式作答计分，不由模型或阅读次数决定。使用说明见[节点教学、练习与掌握度](../core/learning.md)。

### 教学与作答路径

1. **选择节点不等于开始学习。** `Workbench.tsx` 的浏览状态只改变右侧显示；用户点开始学习才执行 `startLearning → create`，POST `/api/conversations` 保存绑定 G/retrieval 的 S，再由 `initialRun` 发首条 teaching。后端 `http.py::create_conversation → ConversationService.create` 校验已确认目标、已发布图谱、节点和客户端 UUID。
2. **续聊使用会话事实。** `frontend/src/workbench/Conversation.tsx::WorkbenchConversation` 从目录元数据取 goal/node，`send` 经 `frontend/src/useRuns.ts::execute` POST `/api/sessions/S/runs`。`http.py::submit_run` 将 DTO 转 RunRequest，`ConversationService.admit` 入队前禁止 scope 变化；新节点会话用 teaching，旧 runner 会话续原 mode。
3. **构造不泄答案的教学上下文。** `application/learning_agent.py::LearningContext.prepare → context → LearningService.context` 校验规划/学习图谱完全一致，只投影当前节点、直接前置和正式作答统计。工具闭包绑定 G/retrieval，不给模型传入可改写 goal/node 的 schema；工具调用时再检查快照是否过期。
4. **教学出题和按钮出题汇入一个用例。** teaching 的 `create_exercise` 闭包调用 `application/exercise_generation.py::GenerateExercise.generate`；工作台“生成练习”由 `http.py::generate_exercises` 建 `mode=exercise` run，进入 `bootstrap.py::build_learning_loop` 的 `generate` direct handler，调用同一方法。
5. **先严格候选，后原子保存。** `GenerateExercise.generate` 用本次 run 共享 gateway，校验题量、选项、答案存在、重复题和来源，至多 repair 一次。服务端分配题 ID；仓库 mutate 内再核对图谱、取消、operation 和重复题，整批题与 operation 一起保存。返回 `ExercisePrivate.to_public`，私有候选/修复消息不回注教学 transcript。
6. **交卷不经过模型。** `frontend/src/lessons/QuizCard.tsx::answer` 先为 E/选项保存 submission ID，POST `/api/goals/G/exercises/E/attempts`。`http.py::submit_answer → GenerateExercise.submit_answer → application/learning.py::LearningService.submit_answer → domain/learning/exercises.py::judge_attempt`，在学习事务内完成去重与首次计分。响应才包含正确选项和解析。
7. **刷新读取证据和推荐。** `WorkbenchConversation::refresh` 读取 context、exercises、next-action；`LearningContext.next_action → LearningService.next_action → domain/learning/recommendations.py::recommend_next_action`。掌握度由 `domain/learning/mastery.py::score_mastery` 计算。点击“查看推荐节点”只调用 onBrowse，不自动创建会话或请求模型。

### 教学与作答的不变量与分叉

- 同节点多个 session 分享题/包/成绩，不分享 transcript。URL 的另一 goal 和临时浏览节点不能覆盖目录作用域。
- 普通 runner 节点工具只读；teaching 才有生成/提案能力，但没有作答、改分或决定提案工具。
- 正式题未作答不公开答案；同 submission 同输入返回旧结果，异输入冲突；同题重答不重复计分，旧内容版本拒绝新作答。
- 练习熟练依据当前版本最近五道不同题的有效首次作答，至少三题且正确率 ≥80%；聊天、自述和阅读 ACK 都不计分。
- retry 保留 root，已保存批次可复用；想再出一批需新任务，而不是换参数冒充同 root 的 retry。

### 教学与作答相关测试

- `tests/test_conversations.py::test_two_same_node_conversations_keep_transcripts_separate_but_share_exercises_lessons_and_grades`：跨会话隔离与节点共享同时成立。
- `tests/test_learning_agent.py::test_learning_context_rejects_missing_unpublished_and_stale_snapshots`：未发布/过期上下文拒绝。
- `tests/test_exercise_generation.py::test_direct_and_tutor_generation_share_budget_repair_and_private_projection`、`test_http_sse_generation_public_read_and_atomic_attempt_feedback`：两入口汇合、私有隔离与交卷。
- `tests/test_learning_domain.py`、`tests/test_sqlite_learning.py`：评分/推荐、首次作答和持久规则；`frontend/tests/single-workbench.spec.ts` 检查推荐浏览不触发模型，`workbench.spec.ts` 检查浏览/焦点与会话隔离。

## 3. 学习包生成、事件 ACK 与独立解释

```text
学习包 → 组件交互 → 保存事件 ACK
                         ↓ 请求解释
              服务端构造输入 → 独立任务
```

**先抓住三件事：**学习包使用固定组件；ACK 保存交互但不计成绩；解释基于持久事件建立任务，失败需要显式重试，不能换请求 ID 绕过去重。使用说明见[学习包与交互解释](../core/lessons.md)。

### 学习包与解释路径

1. `frontend/src/lessons/LessonPanel.tsx::LessonPanelContent.generate` 请求节点 lessons；`http.py::generate_lesson` 建 lesson run，经 bootstrap 的 `generate_lesson` direct handler 到 `application/lesson_generation.py::GenerateLesson.generate`。teaching 的 `create_lesson` 也进入同一用例。
2. 生成器仅拿同节点/内容版本已选题的 public DTO，经固定组件联合 schema、来源和预算校验；`SQLiteLessonRepository.mutate`（`infrastructure/persistence.py`）保存新 package 和 generation operation。包不覆盖，新任务新 ID/version；组件含 chapter 总数有上限。
3. 用户点读完、改变步骤或请求解释，`LessonPanel.tsx` 的 `MarkRead.mark`、`Stepper.change`、`Explanation.explain` 使用 `frontend/src/lessons/persistence.ts` 保存事件身份并 ACK。`http.py::lesson_event → application/lessons.py::LessonService.ack_event → domain/lessons.py::ack_event` 校验包、组件、动作和版本，在 mutate 内保存首个 payload。
4. 请求解释须 ACK 成功后 POST `/api/sessions/{explanationSession}/runs`，带 mode、goal/node、source_event_id 和 explanation_slot，不带 user_text。`http.py::submit_run → LessonService.submit_explanation` 从持久事件、组件和公共题目构造输入，再交 `AgentLoop.submit`。
5. `infrastructure/run_persistence.py::SQLiteRunRepository.admit` 在同一事务校验持久 ACK 并写 `lesson_run_tasks` 与首个 `agent_runs`。执行时 `LearningContext.prepare` 装配 explanation 场景，只读教学上下文；结果仍走公共 run/SSE。前端按 conversation 建持久子 session/slot，把解释留在来源旁，不混入主 teaching transcript。

### 学习包与解释的不变量与分叉

- ACK 不调用模型、不写成绩。正式 quiz 交卷仍走链路 2；包不会凭空生成一份可计分的题卡。
- 同 event/包/version/component/action 重试返回首次 payload，不能把后来的 step payload 覆盖进去；解释使用持久事实而非客户端自报正文。
- `(goal,event,slot)` 是解释业务键；新 request ID 不绕过去重，返回最近 attempt。失败/取消/中断必须显式 retry，新 slot 才重新解释；跨 session 争用同键冲突。
- 过期/schema0 包只读；新解释在准入与执行前检查学习版本。历史已完成解释和已答题反馈仍可读。

### 学习包与解释相关测试

- `tests/test_lesson_generation.py::test_http_sse_lesson_events_formal_attempts_historical_view_and_source_deletion`、`test_concurrent_lesson_generation_ack_rollback_and_explanation_preserves_updates`：交互/计分分离、并发保存。
- `tests/test_run_recovery.py::test_explanation_concurrent_new_request_ids_reuse_one_durable_task_and_keep_ack_updates`、`test_explanation_failed_cancelled_attempts_require_explicit_retry_and_preserve_root`：解释业务幂等和 retry。
- `frontend/tests/lessons.spec.ts`：ACK/解释响应丢失、步骤身份、旧列表淘汰、历史反馈与各自产物 C1；`frontend/tests/workbench.spec.ts`：跨会话解释隔离。

## 4. 从上传资料到引用原文

```text
上传解析 → 显式绑定 → 范围内检索
                         ↓ 保存来源
              点击引用 → 复验与原文定位
```

**先抓住三件事：**上传不自动绑定，节点不自动继承所有目标资料；引用编号归属各自产物；定位验证来源身份和内容，不证明原文语义支持结论。使用说明见[资料检索与引用](../core/documents.md)。

### 资料与引用路径

1. `frontend/src/documents/Documents.tsx` 上传 multipart bytes；`http.py::upload_document` 有界读取并通过线程桥调用 `application/document_imports.py::DocumentImports.upload`。应用生成 document UUID、保存原 bytes/状态，再投解析队列，不经过 AgentLoop 或模型。
2. `DocumentImports._parse` 调 `infrastructure/document_parser.py::SubprocessDocumentParser.__call__`，独立子进程严格解码 UTF-8/BOM 或用 pypdf 解析文本 PDF；按 Markdown 标题/PDF 页码等切块。`SQLiteDocumentRepository.finish_upload`（`infrastructure/persistence.py`）同事务保存 ready、全文、chunk、hash 与 FTS 索引；失败走 failed/unsupported。
3. 用户明确绑定。`frontend/src/documents/DocumentBindings.tsx → http.py::bind_document → DocumentImports.bind` 校验目标/节点并写绑定。先目标绑定，再追加节点绑定；目标绑定用于图谱，节点绑定用于节点问答/题/包，不会自动继承到所有节点。
4. 教学的 `LearningContext.prepare` 注册 `application/document_agent.py::DocumentTurn.register` 的 `search_documents/read_document_chunk`。`DocumentTurn.search → application/documents.py::DocumentService.search → SQLiteDocumentRepository.search_chunks` 用 jieba search 分词和 FTS5 BM25 排序，单次 top5、每块 excerpt 最多 320 字符；服务端为本轮分配 C1 等稳定编号。`read` 只接受本轮发过的 citation ID。
5. 回答完成后 `DocumentTurn.project_output → project_sources → locate_source` 扫描正文标记并复核绑定、revision、hash、offset/位置，输出 `citation_map` 和 `unverified_citation_ids`。`PreparedRun.project_output` 交给 Loop 保存公开结果；取消后不会发布晚到的来源表。
6. 图谱/题/包生成使用 `application/generation_sources.py::GenerationSources`，复用 DocumentTurn 的有界检索。候选只能选本次来源，documents 每项至少一个 ID；repair 用同一表，提交前 `check_current` 复验。各自产物分别持久来源表，不合并到回答表。
7. 用户点原文：`frontend/src/documents/Citations.tsx::locate` 调产物对应 endpoint；`http.py` 的 `locate_citation/locate_graph_citation/locate_exercise_citation/locate_lesson_citation` 从已保存来源决定 scope，再经 `LearningContext.locate_run_source → locate_source` 复验并返回纯文本位置。图谱额外核对当前 planning version。

### 资料与引用的不变量与分叉

- 资料只是数据，不是模型系统指令；没有绑定/问答空召回不能编来源。生成时无绑定为 general，有绑定但空召回明确失败，不偷偷退回通用生成。
- C1 只在所属回答/产物内有效；未知编号 404，解绑/删除/内容过期通常 409；图谱旧 version 也为 409。有效定位不证明语义支持。
- GET run 来源保留完成时快照，原文点击按当前状态重查。人工图谱编辑标 edited，不继承原资料生成声明。
- 解析成功要求当前仍 parsing；解析中删除后晚到结果不能复活。重启将未完成解析标失败，显式 reparse 复用原 bytes；ready 不重跑。
- 当前无 OCR/Office，上传资料 revision 固定 1，更新需重新上传/绑定；资料复验和业务提交之间仍有跨仓库并发窄窗口。

### 资料与引用相关测试

- `tests/test_document_imports.py::test_http_upload_pdf_bind_search_agent_citation_and_deletion`、`test_real_parser_formats_limits_unsupported_and_killable_timeout`：上传解析与真实本地 parser；这里的 real parser 不等于真实模型。
- `tests/test_document_agent.py::test_concurrent_document_turns_keep_local_source_ids_and_bound_documents`、`test_http_sse_answer_sources_and_original_location_revalidate_saved_scope`：本轮编号和定位复验。
- `tests/test_generation_sources.py::test_direct_and_tool_grounding_share_gateway_keep_answer_and_question_c1_separate`、`test_changed_bindings_or_same_version_content_during_generation_reject_commit`：来源隔离与生成提交保护。
- `frontend/tests/documents.spec.ts`、`frontend/tests/lessons.spec.ts`：纯文本原文、绑定/解绑/删除和产物来源展示。

## 5. 已发布图谱的提案审核

```text
Agent 提案 → pending → 用户审核
                         ↓ 接受并校验版本
              原子更新提案 / 图谱 / 学习快照
```

**先抓住三件事：**模型不能决定提案；过期提案不能覆盖新图谱；接受时保留历史，内容版本变化后重算当前统计。响应丢失先只读核对，不自动重复决定。使用说明见[图谱审核机制](../core/planning.md#谁决定-保存什么)。

### 提案审核路径

1. teaching 的 `LearningContext.prepare` 内 `propose_graph_change` 直接调用 `GraphProposalService.create`（`application/proposals.py`）；`frontend/src/proposals/ProposalPanel.tsx` 的生成按钮则经 `http.py::generate_proposal` 建 proposal run，由 `application/proposal_generation.py::GenerateProposal.generate` 调同一创建用例。兼容手工 HTTP `http.py::create_proposal` 也能提交结构化操作。三者只保存 pending，模型候选生成和 repair 都在事务外，不改已发布图谱。
2. 用户审核，`http.py::decide_proposal` 接受 decision/expected_revision，调用 `GraphProposalService.decide`。应用在 coordinator 回调内比较 proposal base 与当前图谱 revision；只有合法 accept 才执行 `domain/learning/proposals.py::accept_proposal`。
3. `infrastructure/proposal_persistence.py::SQLiteProposalRepository.transact` 在一个 `BEGIN IMMEDIATE` 连接读取并更新 planning、learning、proposal 和操作去重；应用用 `application/learning.py::migrate_learning_graph` 更新学习快照。事务成功后返回 planning 与 learning_reset。
4. 接受响应丢失，ProposalPanel 通过只读图谱/提案列表核对结果，不自动再次发送决定。过期 base 保存 conflicted，事务完成后才返回冲突给客户端。

### 提案的不变量与分叉

- 模型只能创建 pending，没有 decision 工具；拒绝不改图谱或成绩。只支持四类操作，不支持删除已有学习节点。
- 同向同 revision 决定幂等，反向决定冲突；学习快照缺失/过期不能隐式重置后接受。
- 内容/依赖更新推进全局 content_revision，保留旧题/attempt/package，但旧内容不再计入当前统计；priority/minutes 只变 revision。
- 这是已实现的跨聚合原子事务，不能类推到初次 publish 或所有资料生成提交。

### 提案相关测试

- `tests/test_p1_proposals.py::test_sqlite_atomic_accept_rollback_reopen_and_concurrent_decisions`、`test_history_preserved_stats_recomputed_old_questions_and_lessons_read_only`：回滚/并发/历史。
- 同文件 `test_missing_or_stale_learning_is_not_implicitly_reset_on_accept_or_context`、`test_generation_models_are_outside_sqlite_transaction_and_stale_base_is_persisted`：快照和事务边界。
- `frontend/tests/proposals.spec.ts`：接受响应丢失只读核对、pending/拒绝和过期冲突。

## 6. run、SSE、取消与刷新恢复

```text
保存请求身份 → run 准入 → 执行并保存状态
                              ↓
                   GET / SSE 读取当前结果
```

**先抓住三件事：**刷新只读，不自动调用模型；结果不确定时恢复原请求，明确失败后才关联原任务重试；公开取消不代表阻塞调用已退出，也不代表业务从未提交。机制说明见[Agent 执行、取消与恢复](../core/agent-loop.md)。

### 正常执行与流式读取

1. `frontend/src/useRuns.ts::submit` 先持久保存 `{path,body}` 和 request ID，后 POST。`presentation/http.py::submit_run` 等路由先经会话作用域校验，再调用 `application/agent/loop.py::AgentLoop.submit → _admit`：锁内检查请求去重/冲突、版本/场景、session scope、同 session 一个和全局两个活动名额。
2. 新 run 在 `SQLiteRunRepository.admit` 中保存 request+queued，成功后才注册并交最多两个线程的 executor；HTTP 返回公共 run。确定性拒绝不应被前端当成“未知是否执行”，429 则保留原命令供显式恢复。
3. `AgentLoop._execute` 先 `_emit(run.started)`，再走 direct handler 或 PreparedRun/Runner；模型/工具使用同一 `BudgetedModelGateway`。工具内生成和一次 JSON repair 也计入同一预算，不另开不受限模型循环。
4. 流式 progress 由 `_progress` 维护有界 partial_text/tool_activity/事件窗口；完成后 `_finish → _emit → SQLiteRunRepository.save` 将状态与新增生命周期事件同事务保存，再更新 live 状态并唤醒订阅者。`presentation/sse.py::public_run/encode_snapshot/encode_sse` 只投影公开状态，不返回完整内部协议或隐藏思维链。
5. `http.py::run_events` 通过 `AgentLoop.snapshot` 原子取得 record+cursor，首帧永远是 `run.snapshot`。之后用 `asyncio.to_thread(loop.wait_events, ...)` 等新事件，不堵 ASGI 循环；当前连接的 cursor 超出窗口时补最新 snapshot，终态与序号一起检查以免漏终态。
6. `useRuns` 先应用终态 SSE 内已保存的 output/text/usage，再尝试详情 GET；GET 失败也不回到 running。`notifyTerminal` 对新终态触发一次业务产物刷新；旧 GET 用 query version 淘汰，不能覆盖新状态。

**重连的准确语义：** 当前 `run_events` 每条新连接从最新 snapshot 的 cursor 开始，没有读取客户端 `Last-Event-ID` 来跨连接重放历史 token。连接内部按 cursor 追新事件/缺口；断线后依当前快照恢复状态。不要把它实现成或描述成无限 token 日志重放。

### 取消和故障分叉

- `http.py::cancel_run → AgentLoop.cancel` 先提交 cancelled 并设置协作标志；阻塞模型调用实际退出前 `_active` 名额不释放。晚到结果不能覆盖终态；`_release` 在 worker 退出时执行。
- `_emit` 持久失败时，live 标 interrupted 并停止新准入，不把未保存结果报 completed；durable 仍是上一状态，修存储后重启再恢复。
- `AgentLoop` 初始化从 repository load 恢复输入、结果和事件，把遗留 queued/running 标 interrupted，不重新请求模型。completed 的有限协议历史可用于后续新回合，不是继续未完成流。

### 刷新后如何决定下一步

| 已知情况 | 当前调用/身份 | 不应做的事 |
| --- | --- | --- |
| POST 响应丢失、网络/5xx 不确定 | `useRuns.refresh` 只 GET；用户查询后 `recover` 显式重发相同 command/request_id，后端幂等定位原 attempt | 由刷新自动重发、用文本猜匹配 run、生成新 request_id 假装恢复 |
| 429 | 保留同一 pending command，显式恢复 | 清空完整输入或自动重试循环 |
| 明确 409/422 等拒绝 | 保留可编辑草稿，读最新版本并重新审核 | 强行覆盖新版本、一直重发旧写入 |
| failed/cancelled/budget_exceeded/interrupted | `useRuns.retry` 复制本浏览器已保存 command，换 request_id 并带 retry_of_run_id；Loop 保留原 root/input | retry completed，或在旧阻塞 worker 未退出时抢占名额 |
| 产物已存，运行结果中断 | 显式 retry 后生成用例按 root operation 复用已保存题/包 | 一律重新生成，或假定 cancelled 表示业务绝未提交 |
| 解释相同 event/slot | 业务键复用最近 attempt，失败仍显式 retry | 换 request_id 绕开失败重试要求，误用另一会话的初始 slot |

浏览器本地 command 丢失时，当前 UI 不能替你构造旧任务 retry 输入；后端虽保存初始输入，前端没有通用“恢复任意浏览器草稿”功能。运维限制和故障处置见[稳定性与恢复](../RELIABILITY.md)。

### 运行与恢复相关测试

- `tests/test_http_runs.py::test_idempotency_conflict_and_session_and_global_capacity_admission`、`test_cancel_keeps_terminal_state_and_capacity_until_blocking_call_returns`：准入与公开取消/实际退出分离。
- 同文件 `test_lifespan_closes_loop_and_real_tcp_sse_supports_disconnect_and_reconnect`、`test_real_tcp_stream_receives_started_heartbeat_and_one_terminal_in_order`：真实本地 TCP，不是真实模型能力测试。
- `tests/test_run_recovery.py::test_run_reopen_recovers_input_result_events_session_scope_and_interrupted_retry`、`test_explanation_admission_and_state_event_transactions_rollback_without_false_success`、`test_committed_exercise_and_lesson_are_reused_after_run_result_interruption`：重开、持久失败与产物复用。
- `tests/test_p0_streaming.py::test_stream_snapshot_history_and_terminal_state_survive_sqlite_reopen`；`frontend/tests/recovery.spec.ts`、`workbench.spec.ts`：快照/历史恢复、丢响应、429、旧 GET 和终态刷新。

## 开始修改前，先选一条链验证理解

可以用[路径叙事模板](../code-understanding/trace-path.md)自检：“我修改的是哪一步？写入前最后一次版本/取消检查在哪？响应丢失会怎样？对应测试有没有同时断言正常与失败路径？”不要只改最终显示文案却漏掉真实结果来源，也不要只补 prompt 就声称建立了安全或幂等边界。

这些链路已接通不等于无风险：没有硬打断阻塞调用、独立工具 timeout 或实际累计 token 硬预算；初次发布两写、跨资料/业务提交窄窗口、完整历史/迁移仍有限制。当前工作台/Agent/Skill、P1 内容与引用语义、真实异常/取消/重试和 20 例真实评估仍需另行验收。用[质量与验收](../QUALITY_SCORE.md)和[技术债](../exec-plans/tech-debt-tracker.md)区分“实现存在”“离线契约证据”“当前真实质量结论”。
