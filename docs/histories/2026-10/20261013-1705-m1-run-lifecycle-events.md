# M1 运行生命周期与公共事件投影离线切片

## 用户诉求

继续按 LearnGraph Lite 执行计划开发 Agent 应用简历作品，补强 Agent 运行生命周期、摘要、取消和 SSE 边界，并按 docs 记录。

## 本次结果

- 扩展 AgentLoop：按 run_id 查询运行记录，保存递增 seq 事件，记录 summary、usage、updated_at。
- 将预算耗尽从通用 failed 投影为应用终态 budget_exceeded，取消投影为 run.cancelled。
- 新增 presentation 公共 run DTO 与 SSE 编码 helper，验证公共事件不暴露 Runner transcript 或内部 tool_call_id。
- 当前环境未安装 FastAPI/Starlette；本切片只验证应用生命周期和 presentation 编码，不声称已完成真实 HTTP 路由。

## 设计动机

AgentRunner 只处理通用模型—工具循环；浏览器可见的运行摘要、终态和 SSE 事件应由应用层统一收束，再由 presentation 层做薄投影。这样后续接 FastAPI 时不需要把业务终态写入路由，也不会把内核 transcript 直接转发给前端。

## 关键文件

- src/learngraph_lite/application/agent/loop.py
- src/learngraph_lite/presentation/sse.py
- tests/test_agent_lifecycle.py
- docs/exec-plans/active/learngraph-lite-implementation.md
- docs/ARCHITECTURE.md
- README.md

## 验证

- python scripts/run-python-tests.py：通过，32 Python tests passed。
- python scripts/check-python-boundaries.py：通过，输出 Python import boundaries passed。
- npm.cmd run ci：通过，包含 Python 边界检查、32 个 Python 测试和 19 个 Node 模板工具测试。
