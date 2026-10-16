# 修复首次建图被误判为图谱反馈

## 用户诉求

使用真实模型时遇到 `graph_required: Graph feedback requires an existing draft graph.`。

## 原因与修复

规划 Agent 的 `generate_route_draft` 同时承担首次创建与草稿修订；模型可能在首次调用的 feedback 参数中填入建图要求。此前直接传给严格反馈生成器，因没有旧图谱被拒绝。

- `application/planning_agent.py` 根据当前服务端图谱快照分流：无图谱时文字作为首次要求，有图谱时才作为修订反馈；补充参数说明和规划指令。
- `application/planning_generation.py` 增加有界 `initial_guidance`，作为业务数据进入生成上下文，不丢弃首次范围要求；保留直接反馈必须已有草稿、确认、版本校验、发布保护和预算规则。
- `tests/test_planning_agent.py` 新增三项回归：首次带非空feedback、已有草稿修订/目标修改后重新建图、不能绕过用户确认。未修改前复现原graph_required错误，修复后通过。

## 验证与范围

- 两个规划测试文件共32项通过；`npm.cmd run ci`通过，含234 Python、19 Node、import boundaries及仓库检查。
- `npm.cmd run eval:offline`：20/20通过；文档骨架与`git diff --check`通过。
- 本次仅后端适配与文档改动，不改前端、`.env`、用户数据库或依赖；未调用真实模型、未自动重试用户任务、未部署或提交Git。
- 保留既有Starlette弃用告警、Windows symlink平台跳过及SSE关闭测试日志，不影响检查通过。该局部修复沿用既有“宿主状态决定操作语义”的设计，不另写重复学习文档。
