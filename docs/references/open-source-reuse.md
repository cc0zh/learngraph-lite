# 开源复用记录

本文件记录 LearnGraph Lite 计划复用或参考的外部项目。只有实际验证过的能力才能写成“已采用”；尚未下载、安装或运行的内容只列为候选或规格来源。

| 项目 | 计划用途 | 状态 | 许可证/版本证据 | 备注 |
| --- | --- | --- | --- | --- |
| HKUDS/nanobot | 参考 AgentLoop / AgentRunner 职责拆分 | 已核验固定 commit 的 README、docs/architecture.md、nanobot/agent/loop.py、nanobot/agent/runner.py 与 LICENSE；只参考架构分层，不复制源码 | MIT；commit 23941355a8932609d7fc7ba2820f162d1ea7bea5；LICENSE 为 “MIT License, Copyright (c) 2025-present Xubin Ren and the nanobot contributors” | architecture.md 明确：AgentLoop 管 channel-facing turn、session、workspace、context 和 outbound；AgentRunner 管 provider/tool loop、streaming、tool call、runtime limits。与本项目当前轻量 Loop/Runner 拆分一致；不整包引入，不复制记忆/渠道/定时任务外壳。GitHub tree API 本轮受 rate limit，未取得完整目录树。 |
| Python 标准库 | M0/M1 dataclass、AST import 边界检查、fixture smoke | 已采用 | 随 Python 3.13.5 环境提供 | 当前阶段尽量减少依赖，后续 FastAPI/SDK/解析库再锁版本 |

待 M2 之后继续补充：FastAPI、React/TypeScript、SQLite FTS5、PDF/text parser、Schema 校验、图布局和 UI 基础库。
