# 完成第一次业务改动

先把需求改写成可验证的行为，再选代码入口。不要因为看到了某个按钮，就把规则、权限和持久化全部写进它的点击事件。

## 按修改类型定位

| 想改什么 | 从哪里读 | 必须一起检查 |
| --- | --- | --- |
| 工作台布局、切换与 URL | `frontend/src/workbench/Workbench.tsx`、`navigation.ts` | 浏览节点与会话作用域分离、脏编辑保护、移动端 |
| 规划对话与审核卡 | `frontend/src/pages/AgentPlanning.tsx`、`application/planning_agent.py` | 用户确认与模型提议分离、过期卡、首次生成与修订 |
| 请求字段与状态码 | `presentation/http.py`、`presentation/sse.py` | 应用用例、公共 DTO、`frontend/src/types.ts` 和 OpenAPI |
| 推荐、图谱合法性、掌握度 | `domain/`、`application/learning.py` | 纯规则、确定性测试，不依赖模型自述 |
| 新 Agent 工具 | `application/learning_agent.py` 或 `planning_agent.py` | schema、闭包作用域、预算、幂等、公共输出 |
| 新增学习包组件 | `domain/` 中的 lesson 类型、`application/lesson_generation.py`、`frontend/src/lessons/` | 严格 schema、历史兼容、安全渲染、ACK 允许动作 |
| 资料检索与来源 | `application/document_agent.py`、`application/generation_sources.py`、`infrastructure/persistence.py` | 显式绑定、版本/hash、来源表归属和失效 |
| 持久化和恢复 | `infrastructure/*persistence.py`、`bootstrap.py` | 旧库读取、事务边界、重启与同 ID 重试 |

表中 Python 路径相对 `src/learngraph_lite/`。打开文件前先看[架构地图](architecture.md)；更完整的协议查 [API 手册](../api-guide.md)。

## 示例：调整下一步推荐规则

假设需求是“有近期答错节点时优先复习，否则按现有排序选可学节点”。当前规则可能已经满足这条要求：**先读现有代码和测试，不能把假设当成缺陷。**

1. 写一个固定输入：两个节点、明确依赖、掌握状态与一次作答。说明期望推荐哪个节点，以及为什么。
2. 从 `domain/` 的推荐规则及 `tests/test_learning_domain.py` 入手，先用测试证明所需差异。若无需改动，保留结论，不重复实现。
3. 让纯规则保持不依赖 HTTP、SQLite 和 Agent。通过 `application/learning.py` 检查 API 与工具使用的是同一用例，不另写一套提示词排序。
4. 检查只读 context/next-action 是否仍不修改成绩；“看过章节”与“我已经掌握”不能被当作正式作答。
5. 定向运行测试，再执行完整 `check`。若推荐结果展示或交互改变，补浏览器回归。
6. 同步规则说明和 history；若改变产品取舍，更新相应产品/架构文档，不在多页复制当前验收数字。

这个例子重点是“确定性事实由程序控制”。模型可以解释推荐，不应重新定义计分或绕过依赖规则。

## 增加 API 或 Agent 工具

新增写能力前，先回答：

- 谁授权这次写入？是用户明确操作，还是模型只能提出待审核候选？
- 业务规则属于哪个应用用例？HTTP 与工具是否调用同一个用例？
- 身份是什么？重复请求如何复用、不同输入如何冲突、失败后何时才能重试？
- 是否需要固定目标/节点作用域？不要让模型参数任意选择另一个用户上下文。
- 哪个事务保存结果？模型调用必须放在事务外。已有跨聚合原子性不能推论为所有写入都原子化。
- 公共响应是否会泄漏私有答案、内部 transcript、供应商原始错误或敏感资料？

工具使用严格 Pydantic 参数与受控注册；每轮显式装配。需要写教学产物时复用现有生成用例及父 run 的预算，不私自创建第二个 gateway。工具只返回有限公共结果，不能凭模型“已完成”的文字证明数据库已写入。

新增流程知识而非新权限时，优先考虑 [Skill](../agent-skills.md)。Skill 是可信指南，不能授予模型原先没有的工具权限。

## 前端修改的恢复纪律

- 页面挂载、刷新和导航只读取；不要在 effect 中自动发起生成、ACK、接受提案或重试。
- 提交前保存稳定 request ID 和必要输入；网络/5xx 不确定结果与确定性 4xx 拒绝分开处理。
- SSE 终态先应用保存的 payload，后续 GET 失败不能让页面卡在 running。
- 避免旧请求覆盖新选择、编辑草稿或新版本；沿用版本/epoch 等淘汰机制。
- 浏览节点不改聊天作用域；共享的是节点教材、题目和成绩，不是自动合并的 transcript。
- Markdown 不允许模型 HTML、自动外连图片或可执行组件；沿用 `SafeMarkdown` 和固定组件协议。

## 提交前自检

能否用一句话说清行为变化？测试是否覆盖正常、冲突、重复及恢复？有没有意外改变旧数据读取、作用域或权限？

验证步骤见[测试与验证](testing.md)，协作规则见[贡献指南](../../CONTRIBUTING.md)。跨多轮或高风险改动先建 [execution plan](../PLANS_GUIDE.md)。代码和流程变更按 [history 规则](../HISTORY_GUIDE.md)留记录；只有明确授权才发布、部署或执行收费验证。
