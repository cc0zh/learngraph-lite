# mini-learngraph4

LearnGraph Lite 是一个本地单用户运行的学习 Agent 应用，目标是把学习目标变成可审核知识路线，并用轻量 Agent 循环支持资料学习、练习反馈和下一步建议。完整产品规格见 docs/从零构建功能文档.md。

当前仓库已建立 Python 分层骨架、独立 AgentRunner、应用层 AgentLoop、学习领域规则、资料/学习页/图谱提案离线切片、planning state 最小 SQLite 持久化、fixture smoke 和离线测试。FastAPI、React、完整业务 SQLite 持久化、真实模型 smoke 和 M5 评估交接仍按 docs/exec-plans/active/learngraph-lite-implementation.md 推进。

## 开发准备

需要 Node.js 22+、Python 3.13+、Git；完整打包还需要 tar。当前离线检查不需要安装 npm 或 Python 第三方依赖。

Windows 常用入口：

- npm.cmd run ci
- npm.cmd run smoke:fixture

macOS/Linux 使用 npm。Windows 环境问题见 docs/WINDOWS.md。

## 常用命令

- npm.cmd run ci
- npm.cmd run test
- npm.cmd run test:py
- npm.cmd run check:py-boundaries
- npm.cmd run smoke:fixture
- npm.cmd run eval:offline
- npm.cmd run demo:fixture
- npm.cmd run release-package

## 当前架构

- src/learngraph_lite/agent_core/：独立 Agent 内核，包含模型协议、工具注册表、Runner 和预算控制。
- src/learngraph_lite/application/：应用编排。当前 AgentLoop 负责 run 准入、幂等、预算注入、运行摘要、公共事件和终态。
- src/learngraph_lite/domain/：学习领域纯规则，例如图谱校验和掌握度计算。
- src/learngraph_lite/presentation/：当前包含公共 run DTO 与 SSE 编码；真实 HTTP 路由后续接入。
- src/learngraph_lite/infrastructure/：基础设施适配器。当前包含 planning state 的最小 SQLite repository；模型 SDK、完整业务持久化、文档解析和检索适配器仍待接入。

更多边界见 docs/ARCHITECTURE.md。

## 项目约定

- 从 AGENTS.md 查阅协作规则；docs/ 是仓库知识正式来源。
- 阶段计划维护在 docs/exec-plans/active/learngraph-lite-implementation.md。
- 开源复用记录维护在 docs/references/open-source-reuse.md。
- 离线评估集在 evals/cases/offline-m5.json，运行 npm.cmd run eval:offline 会生成 evals/reports/offline-fixture-report.md。
- 离线演示脚本运行 npm.cmd run demo:fixture，会生成 docs/demo/fixture-demo.md；它只用于无 Key 本地复现，不代表真实模型输出。
- 未配置真实模型 Key 时只能使用明确标记的 fixture 模式，不能把 fixture 结果当成真实模型能力。
