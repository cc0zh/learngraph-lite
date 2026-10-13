# 开源复用记录

本文件记录 LearnGraph Lite 计划复用或参考的外部项目。只有实际验证过的能力才能写成“已采用”；尚未下载、安装或运行的内容只列为候选或规格来源。

| 项目 | 计划用途 | 状态 | 许可证/版本证据 | 备注 |
| --- | --- | --- | --- | --- |
| HKUDS/nanobot | 参考 AgentLoop / AgentRunner 职责拆分 | 已核验固定 commit 的 README、docs/architecture.md、nanobot/agent/loop.py、nanobot/agent/runner.py 与 LICENSE；只参考架构分层，不复制源码 | MIT；commit 23941355a8932609d7fc7ba2820f162d1ea7bea5；LICENSE 为 “MIT License, Copyright (c) 2025-present Xubin Ren and the nanobot contributors” | architecture.md 明确：AgentLoop 管 channel-facing turn、session、workspace、context 和 outbound；AgentRunner 管 provider/tool loop、streaming、tool call、runtime limits。与本项目当前轻量 Loop/Runner 拆分一致；不整包引入，不复制记忆/渠道/定时任务外壳。GitHub tree API 本轮受 rate limit，未取得完整目录树。 |
| Python 标准库 | M0/M1 dataclass、AST import 边界检查、fixture smoke | 已采用 | 随 Python 3.13.5 环境提供 | 当前阶段尽量减少依赖，后续 FastAPI/SDK/解析库再锁版本 |
| [FastAPI](https://github.com/fastapi/fastapi) / [Starlette](https://github.com/encode/starlette) | HTTP app factory、Pydantic 入参/OpenAPI、lifespan、StreamingResponse、TestClient | 已采用官方包；未摘取源码 | FastAPI 0.143.0，MIT；Starlette 1.8.0，BSD-3-Clause，传递依赖由 uv.lock 固定 | 2026-10-13 阅读 FastAPI 官方 [流式响应](https://fastapi.tiangolo.com/advanced/custom-response/) 与 [生命周期](https://fastapi.tiangolo.com/advanced/events/) 示例，核验安装包 LICENSE 和 metadata；流式事件、状态与取消仍由本项目应用层负责。 |
| [Uvicorn](https://github.com/encode/uvicorn) | 本地原生 ASGI 服务与真实 TCP SSE 集成测试 | 已采用官方包 | 0.54.0，BSD-3-Clause；已读安装包 LICENSE | 本地入口仅绑定 127.0.0.1，测试使用临时端口，无容器或外部服务。 |
| [HTTPX](https://github.com/encode/httpx) | TestClient 与真实 TCP 流测试 | 已采用官方开发依赖 | 0.28.1，BSD-3-Clause；已读安装包 LICENSE | Starlette 1.8.0 提示 TestClient 未来改用 httpx2；当前组合仍可运行，后续升级时一并验证。 |
| [Pydantic](https://github.com/pydantic/pydantic) | HTTP 输入/公共响应与工具参数 schema | 已采用并声明直接依赖 | 2.14.1，MIT；已读安装包 LICENSE，版本由 uv.lock 固定 | `Tool.from_model` 复用 model_json_schema/model_validate；工具执行禁止额外字段和类型强转，不替代应用层准入/幂等检查。 |
| [openai/openai-python](https://github.com/openai/openai-python/tree/v1.109.1) | Chat Completions 模型协议与原生 tool calling | 已采用官方 SDK，不摘取源码 | 1.109.1，Apache-2.0；2026-10-13 核验安装包 LICENSE、metadata、构造器和 completions.create 参数 | SDK metadata 要求 `httpx>=0.23,<1`、`pydantic>=1.9,<3`，实际锁定安装与现有 HTTPX 0.28.1/Pydantic 2.14.1 共存；为稳定现有 HTTP 栈采用此固定版本，不宣称它是最新版。关闭 SDK 重试，设置 timeout/max_tokens，显式 close；测试使用真实 SDK + HTTPX MockTransport，仅证明离线协议行为。 |
| [run-llama/llama_index](https://github.com/run-llama/llama_index/tree/5b7b6e323e1da3edd787a2104a89257c14f026d0) | 参考检索来源编号与引用回答的分工 | 已读固定 commit 的 CitationQueryEngine 与 LICENSE；只参考思路，不复制或安装框架 | MIT，Copyright (c) Jerry Liu；commit 5b7b6e323e1da3edd787a2104a89257c14f026d0 | 2026-10-13 核验下方原始源码；本项目使用已有 DocumentService/FTS5 与 run 局部来源表，不引入额外分块/合成框架。 |

后续继续补充 React/TypeScript、PDF parser、图布局和 UI 基础库。当前 SQLite/FTS5 使用 Python 标准库适配；锁文件固定 HTTP 切片的依赖树，本记录不代表对所有传递依赖完成独立源码审计。

2026-10-13 补充核验 nanobot 同一固定 commit 的 [`nanobot/agent/context.py`](https://github.com/HKUDS/nanobot/blob/23941355a8932609d7fc7ba2820f162d1ea7bea5/nanobot/agent/context.py)：`TranscriptInput` 保存 history/current_message/runtime_context_blocks，`ContextBuilder.build_transcript()` 在进入 Runner 前装配系统指令、历史和当前输入，并保留新一轮边界。本项目仅参考上下文装配分工，以 `LearningContext.prepare()` 组装学习业务数据与当前输入；不复制源码，不引入 memory、skills、workspace、媒体或历史会话模块。已实现与测试的 SQLite fixture 回合不构成真实供应商能力证据。

LlamaIndex [`citation_query_engine.py`](https://github.com/run-llama/llama_index/blob/5b7b6e323e1da3edd787a2104a89257c14f026d0/llama-index-core/llama_index/core/query_engine/citation_query_engine.py) 的 `_create_citation_nodes()` 为来源加入 `Source N`，`CITATION_QA_TEMPLATE` 要求仅使用所给来源并加 numbered citations；retrieve/synthesize 分离。源码同时提醒重新切片时不能复制旧完整 offsets。本项目仅参考先编号再回答：C1 由本轮实际检索结果产生，原文版本、内容与位置由服务端复验；编号存在性不证明语义支持。许可证原文见固定版本的 [LICENSE](https://github.com/run-llama/llama_index/blob/5b7b6e323e1da3edd787a2104a89257c14f026d0/LICENSE)。
