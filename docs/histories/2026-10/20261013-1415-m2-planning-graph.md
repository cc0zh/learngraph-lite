# M2 目标规划与图谱离线切片

## 用户诉求

继续按 docs/从零构建功能文档.md 从空项目实现 LearnGraph Lite，阶段推进目标澄清、确认和图谱草稿/发布规则，并保持文档与测试同步。

## 本次结果

- 新增目标草稿、最多两轮澄清、跳过时 assumptions、目标确认规则。
- 新增图谱 Snapshot、draft/published 状态、revision/content_revision、发布校验和 revision 冲突。
- 新增应用层 PlanningService 与内存仓库，覆盖目标创建、澄清回答、确认、图谱草稿保存、节点编辑、发布和当前图谱读取。
- 候选 RAG 图谱改为 8 个节点，符合规格中默认 8 到 15 个节点的下限。
- 记录 GitHub raw 读取 nanobot 源码失败的事实；未把外部源码二次核验写成已完成。

## 设计动机

M2 先实现无 HTTP/SQLite 的领域与应用用例，确保业务规则可测、可迁移。后续接 FastAPI 和持久化时复用同一用例，不把路由或数据库实现当成业务规则来源。

## 关键文件

- src/learngraph_lite/domain/learning/goals.py
- src/learngraph_lite/domain/learning/graph.py
- src/learngraph_lite/application/planning.py
- tests/test_goal_planning.py
- docs/exec-plans/active/learngraph-lite-implementation.md

## 验证

- python scripts/run-python-tests.py：通过，13 Python tests passed。
- python scripts/check-python-boundaries.py：通过。
- npm.cmd run ci：通过，包含 13 个 Python 测试和 19 个 Node 模板工具测试。
