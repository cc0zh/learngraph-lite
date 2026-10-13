# M4C 图谱提案与人工审核离线切片

## 用户诉求

继续按 docs/从零构建功能文档.md 实现 LearnGraph Lite，推进图谱提案与人工审核，确保 Agent 只能创建提案，不能直接改已发布图谱。

## 本次结果

- 新增 GraphProposal、GraphOperation 和 ProposalStatus 领域模型。
- 支持 add_node、update_node、add_dependency、remove_dependency 四类最小提案操作。
- 新增 GraphProposalService，创建提案时校验作用域、pending 状态、操作合法性和应用后的图谱合法性。
- 接受提案时校验 base_revision；旧 revision 标记 conflicted 并返回原图，不覆盖当前图谱。
- 拒绝提案只改变 proposal 状态，不产生图谱副作用。
- 测试覆盖接受、拒绝、冲突和成环非法提案。

## 设计动机

图谱变更属于用户确认后的业务状态，不能由 Agent 直接写入发布图。提案模型把“模型建议”和“用户决策”拆开，既保留可解释差异，也能用 revision 避免覆盖用户已发布的新版本。

## 关键文件

- src/learngraph_lite/domain/learning/proposals.py
- src/learngraph_lite/application/proposals.py
- tests/test_graph_proposals.py
- docs/exec-plans/active/learngraph-lite-implementation.md

## 验证

- python scripts/run-python-tests.py：通过，29 Python tests passed。
- python scripts/check-python-boundaries.py：通过。
- npm.cmd run ci：通过，包含 29 个 Python 测试和 19 个 Node 模板工具测试。
