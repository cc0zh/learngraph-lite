## [2026-10-13 20:35] | Task: SQLite lesson persistence

### 🤖 Execution Context

- **Agent ID**: `Codex`
- **Base Model**: `GPT-6`
- **Runtime**: `Codex CLI / Windows PowerShell`

### 📥 User Query

> 继续推进 LearnGraph Lite 作为 Agent 应用开发方向的简历作品；补齐学习页相关的本地持久化切片，并按 docs 记录。

### 🛠 Changes Overview

**Scope:** lesson application port, SQLite infrastructure, tests, docs

**Key Actions:**

- **Repository port**: 给 `LessonService` 拆出 `LessonRepository` protocol，并在保存 package、ACK 事件和解释任务状态变化后保存 lesson state。
- **SQLite persistence**: 新增 `SQLiteLessonRepository`，持久化 lesson package、事件 ACK、解释 run 幂等结果和失败重试状态。
- **Recovery tests**: 覆盖重新实例化 repository 后恢复 package/event/explanation run，以及失败解释任务重启后可 retry 并在成功后保持幂等。
- **Docs**: 更新 README、ARCHITECTURE 和执行计划，明确当前是 M4B lesson state 的最小 SQLite repository，不是 React/HTTP 或完整业务 schema。

### 🧠 Design Intent (Why)

M4B 的学习页事件需要刷新后保持 ACK 幂等，解释任务也需要保留成功 run_id 和失败可重试状态。此切片先把后端 lesson state 持久化，保持无依赖离线路径可验证，同时不提前声明 React 固定组件渲染器、HTTP ACK 路由或浏览器 E2E 已完成。

### 📁 Files Modified

- `src/learngraph_lite/application/lessons.py`
- `src/learngraph_lite/infrastructure/persistence.py`
- `src/learngraph_lite/infrastructure/__init__.py`
- `tests/test_sqlite_lessons.py`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/exec-plans/active/learngraph-lite-implementation.md`
