# 开发者文档

LearnGraph Lite 是本地单用户学习 Agent Web 应用：把学习意图变成可审核的知识图谱，再围绕节点开展对话、阅读、练习与反馈。这里帮助你从第一次启动走到第一次业务改动，而不是要求你先读完全部历史记录。

**第一次加入项目？从[安装与首次运行](developer/getting-started.md)开始。** 不需要模型 Key，就能运行确定性的演示流程。

## 推荐阅读路径

1. [安装与首次运行](developer/getting-started.md)：准备环境，启动 fixture，走一遍工作台。
2. [核心概念](developer/concepts.md)：区分目标、节点、会话、run 和共享学习状态。
3. [架构与源码地图](developer/architecture.md)：理解各层责任，找到你的修改入口。
4. [关键业务链路](developer/flows.md)：沿一次请求追踪 UI、HTTP、应用服务、模型与数据库。
5. [完成第一次业务改动](developer/change-guide.md)：以修改推荐规则为例，确定边界、补测试、更新文档。
6. [测试与验证](developer/testing.md)：根据改动选择验证，不把离线成功当作真实模型质量证明。

建议边读边打开源码：能说清“状态属于谁、谁有权写、失败怎样恢复”，比记住所有文件名更重要。

## 按问题查阅

| 你的问题 | 阅读入口 |
| --- | --- |
| 环境装好后，为什么启动失败？ | [常见问题与排错](developer/troubleshooting.md)、[Windows 指南](WINDOWS.md) |
| 如何选择 fixture / real、数据库和模型配置？ | [运行模式与配置](developer/configuration.md) |
| 如何修改页面、API、规则或 Agent 工具？ | [业务改动指南](developer/change-guide.md) |
| API 的请求字段、版本冲突、SSE 和引用定位是什么？ | [API 手册](api-guide.md)，完整 schema 见运行中的 OpenAPI |
| 如何新增或调整 Skill？ | [应用 Agent Skill](agent-skills.md) |
| 取消、重试、重启和预算有哪些限制？ | [恢复与可靠性](RELIABILITY.md) |
| 现在到底验证到了哪一步？ | [质量与验收](QUALITY_SCORE.md)，这是当前状态的唯一入口 |
| 如何维护这套文档、运行文档站？ | [文档维护指南](developer/documentation.md) |

## 深入参考与协作

- 系统设计：[架构详细参考](ARCHITECTURE.md)、[产品原则](PRODUCT_SENSE.md)、[产品规格](从零构建功能文档.md)。规格是目标要求，不等于全部实现。
- 开发规则：[贡献指南](../CONTRIBUTING.md)、[Agent 任务入口](../AGENTS.md)、[编码纪律](CODING_BEHAVIOR.md)、[仓库协作](REPO_COLLAB_GUIDE.md)。
- 安全与交付：[安全约束](SECURITY.md)、[供应链安全](SUPPLY_CHAIN_SECURITY.md)、[CI/CD](CICD.md)、[开源复用](references/open-source-reuse.md)。
- 理解与演进：[代码理解方法](code-understanding/README.md)、[计划规则](PLANS_GUIDE.md)、[技术债](exec-plans/tech-debt-tracker.md)、[学习记录](learnings/README.md)、[变更记录规则](HISTORY_GUIDE.md)。

## 阅读前的边界

- 仅供本机单用户研究与开发，没有登录与公开部署的访问控制；同一 SQLite 只支持一个 API 进程。
- fixture 不访问模型供应商；real 会发送数据并可能产生费用。默认验证不运行付费入口。
- Agent 可以生成草稿和提案，目标确认、图谱发布和提案决定由人执行。正式作答才更新成绩。
- 资料引用可定位不代表语义已经验证；会话历史不是跨会话长期记忆；刷新不会自动续跑旧任务。

文档结构参考 [CountBot 文档](https://countbot.cn/docs/) 的“概览 → 上手 → 核心机制 → 开发参考”阅读组织；内容、能力和验收均以本仓库为准，不引入参考项目的团队、渠道或记忆能力。
