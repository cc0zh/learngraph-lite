## [2026-10-13 21:15] | Task: 接入原生模型与工具调用

### 📥 User Query

> 继续项目开发，补齐 Agent 核心模型与工具调用链路，维护可验证的作品和文档。

### 🛠 Changes Overview

补齐 assistant/tool 消息配对与严格 Pydantic 工具参数校验，新增官方 OpenAI SDK Chat Completions 适配器、独立 real API factory、普通回答/原生工具回合 smoke 入口和 SDK MockTransport 行为测试。fixture 保持独立，不宣称已取得真实供应商证据。

实现范围、验收证据和剩余限制统一维护于 [execution plan](../../exec-plans/active/learngraph-lite-implementation.md#原生模型与工具调用切片已完成)。通用协议知识见 [学习笔记](../../learnings/2026-10/assistant-tool-call-transcript.md)。
