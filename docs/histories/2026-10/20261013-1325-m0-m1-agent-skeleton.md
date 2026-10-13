# M0/M1 Agent 骨架

## 用户诉求

从空项目实现 LearnGraph Lite。项目定位为 Agent 应用开发方向的简历作品，优先遵循 docs/从零构建功能文档.md，避免企业平台化；适当 commit，测试逐步增长并阶段性收敛。

## 本次结果

- 建立 Python 分层骨架：agent_core、domain、application、infrastructure、presentation 和显式 bootstrap。
- 实现最小独立 AgentRunner、工具注册表、预算/取消和应用层 AgentLoop。
- 增加纯领域图谱校验与掌握度规则，证明领域规则不依赖模型运行。
- 增加 Python import 边界检查、M0/M1 测试、执行计划、架构说明和开源复用记录。

## 设计动机

先交付离线可验证的 M0/M1 切片，避免在模板态一次性引入 FastAPI/React/SQLite 后无法区分架构边界是否成立。fixture 模型只用于协议与生命周期测试，不作为真实模型能力证明。

## 关键文件

- src/learngraph_lite/agent_core/
- src/learngraph_lite/application/agent/loop.py
- src/learngraph_lite/domain/learning/
- scripts/check-python-boundaries.py
- tests/test_agent_core.py
- tests/test_agent_loop.py
- tests/test_learning_domain.py
- docs/exec-plans/active/learngraph-lite-implementation.md

## 验证

- python scripts/check-python-boundaries.py：通过。
- python scripts/run-python-tests.py：通过，9 Python tests passed。
- python -X utf8 scripts/run-fixture-smoke.py：通过。
- npm.cmd run ci：通过，包含 Python 与 Node 检查。
