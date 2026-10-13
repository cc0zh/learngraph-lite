# 开源复用记录

本文件记录 LearnGraph Lite 计划复用或参考的外部项目。只有实际验证过的能力才能写成“已采用”；尚未下载、安装或运行的内容只列为候选或规格来源。

| 项目 | 计划用途 | 状态 | 许可证/版本证据 | 备注 |
| --- | --- | --- | --- | --- |
| HKUDS/nanobot | 参考 AgentLoop / AgentRunner 职责拆分 | 规格已锁定；本轮 GitHub 页面请求未及时返回，尚未二次源码核验 | docs/从零构建功能文档.md 记录 commit 23941355a8932609d7fc7ba2820f162d1ea7bea5 | 不整包引入，不复制记忆/渠道/定时任务外壳；当前实现为自研轻量内核 |
| Python 标准库 | M0/M1 dataclass、AST import 边界检查、fixture smoke | 已采用 | 随 Python 3.13.5 环境提供 | 当前阶段尽量减少依赖，后续 FastAPI/SDK/解析库再锁版本 |

待 M2 之后继续补充：FastAPI、React/TypeScript、SQLite FTS5、PDF/text parser、Schema 校验、图布局和 UI 基础库。
