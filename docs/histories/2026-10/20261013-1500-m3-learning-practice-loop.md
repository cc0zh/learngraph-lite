# M3 节点学习与练习反馈离线闭环

## 用户诉求

继续按 docs/从零构建功能文档.md 实现 LearnGraph Lite，推进 P0 的节点 Agent 学习、练习判分、掌握度和下一步建议闭环，并保持测试增长和文档记录。

## 本次结果

- 新增单选题 ExercisePrivate/ExercisePublic，Public DTO 不暴露 correct_option_id 和 explanation。
- 新增服务端判分规则，客户端只提交 selected_option_id；同一 exercise 只有首次作答计入掌握度。
- 新增题干/选项归一化哈希，拒绝同节点当前版本下完全重复题。
- 新增旧 graph content_revision 题目提交拒绝。
- 新增 deterministic next_action，按前置依赖、近期错题和可用分钟返回推荐。
- 新增 LearningService，复用 AgentLoop 作为节点学习入口，并用 request_id 保持同一逻辑请求幂等。
- 补充新题答错可降低掌握度的测试，避免沿用只增不减规则。

## 设计动机

P0 的评分与推荐必须是确定性业务规则，不能由模型自行决定；Agent 负责讲解和组织反馈，判分、计分、版本和下一步排序由领域/应用层控制。当前先用内存仓库和 fixture 题目证明闭环，后续再接 HTTP、SQLite 和真实模型生成。

## 关键文件

- src/learngraph_lite/domain/learning/exercises.py
- src/learngraph_lite/domain/learning/recommendations.py
- src/learngraph_lite/application/learning.py
- tests/test_learning_service.py
- docs/exec-plans/active/learngraph-lite-implementation.md

## 验证

- python scripts/run-python-tests.py：通过，18 Python tests passed。
- python scripts/check-python-boundaries.py：通过。
- npm.cmd run ci：通过，包含 18 个 Python 测试和 19 个 Node 模板工具测试。
