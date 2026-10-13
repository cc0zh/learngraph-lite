# 架构总览

LearnGraph Lite 是本地单用户运行的学习 Agent Web 应用。当前仓库处于 M0/M1 起步阶段：已建立 Python 分层骨架、独立 Agent 内核、应用层 AgentLoop、少量纯领域规则和离线测试；FastAPI、React、SQLite、资料解析和 P1 功能仍按执行计划推进。

正式规格以 docs/从零构建功能文档.md 为准。本文记录当前实现边界，避免把目录名误当作架构完成。

## 顶层结构

- src/learngraph_lite/agent_core/：通用 AgentRunner、工具注册表、模型协议和预算控制。不能导入 LearnGraph 领域、HTTP、ORM 或基础设施。
- src/learngraph_lite/domain/：学习领域纯规则，例如图谱校验和掌握度计算。不能导入 Agent 内核、应用层或基础设施。
- src/learngraph_lite/application/：应用用例与编排。当前包含 AgentLoop，负责运行准入、幂等、预算注入和唯一终态。
- src/learngraph_lite/infrastructure/：后续放模型 SDK、SQLite、文档解析、检索等适配器。
- src/learngraph_lite/presentation/：后续放 FastAPI 路由、SSE DTO 与前端入口适配。
- src/learngraph_lite/bootstrap.py：显式装配 fixture 模型和工具，供 M1 smoke 使用；导入包本身不启动 Web 或数据库。
- tests/：同时保留模板 Node 工具测试与新增 Python 架构/内核/领域测试。
- scripts/check-python-boundaries.py：轻量 AST import 边界检查。

## 依赖方向

允许方向：

    presentation -> application -> domain
    presentation -> application -> agent_core
    infrastructure -> application/domain/agent_core 的端口或协议
    bootstrap -> presentation/application/infrastructure

当前离线检查覆盖：

- agent_core 禁止导入 application、domain、infrastructure、presentation。
- domain 禁止导入 agent_core、application、infrastructure、presentation。
- application 禁止导入 infrastructure、presentation。

这些检查只证明当前 Python import 边界，不能证明未来 HTTP、数据库和前端边界自动成立；新增适配器时需要继续补测试。

## 当前运行拓扑

M1 fixture smoke 使用 python -m learngraph_lite.bootstrap：bootstrap 装配 fixture model、AgentRunner 和 echo tool，AgentLoop 创建一次 run，Runner 完成模型-工具-模型回合。fixture 输出必须标记为演示模式，不能作为真实模型能力证明。
