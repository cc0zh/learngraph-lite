# LearnGraph Lite 文档

LearnGraph Lite 是本地单用户学习 Agent：把学习意图变成可审核的知识图谱，再围绕节点对话、阅读、练习与反馈。按你要做的事选择入口，不必先读完源码和历史记录。

## 从你要做的事开始

### 先跑起来

从[安装与首次运行](developer/getting-started.md)启动无 Key 工作台，走一遍创建目标、审核图谱与节点学习。需要接入真实模型时再看[运行模式与配置](developer/configuration.md)；启动遇阻先看[排错](developer/troubleshooting.md)。

### 理解核心机制

从[核心机制总览](core/index.md)按能力查阅：目标如何变成图谱、学习成绩如何产生、资料怎样进入回答、学习包如何追问，以及 Agent 任务怎样恢复。不必先读函数级调用链。

### 修改与验证功能

先用[领域概念](developer/concepts.md)确认状态归属，再通过[架构与源码地图](developer/architecture.md)和[关键调用链](developer/flows.md)定位修改点，按[第一次业务改动](developer/change-guide.md)与[测试与验证](developer/testing.md)完成改动。

## 按能力查阅

| 想理解什么 | 核心机制 |
| --- | --- |
| 谁确认目标、谁发布图谱，发布后怎样调整？ | [目标规划与图谱审核](core/planning.md) |
| 为什么聊天独立，题目和成绩却能共享？ | [节点教学、练习与掌握度](core/learning.md) |
| 上传的资料何时生效，引用能证明什么？ | [资料检索与引用](core/documents.md) |
| 学习内容如何阅读、交互和针对性追问？ | [学习包与交互解释](core/lessons.md) |
| 模型与工具怎样循环，失败后如何恢复？ | [Agent 执行、取消与恢复](core/agent-loop.md) |
| Skill 如何按需加载，会不会增加权限？ | [应用 Agent Skill](agent-skills.md) |

## 新开发者的完整阅读路径

1. [安装与首次运行](developer/getting-started.md)：准备环境，启动 fixture，走一遍工作台。
2. [核心机制总览](core/index.md)与[领域概念](developer/concepts.md)：先了解学习闭环，再区分目标、节点、会话、run 和共享学习状态。
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
