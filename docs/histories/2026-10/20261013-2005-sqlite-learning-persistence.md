## [2026-10-13 20:05] | Task: SQLite learning persistence

### 🤖 Execution Context

- **Agent ID**: `Codex`
- **Base Model**: `GPT-6`
- **Runtime**: `Codex CLI / Windows PowerShell`

### 📥 User Query

> 继续推进 LearnGraph Lite 作为 Agent 应用开发方向的简历作品；补齐学习进度相关的本地持久化切片，并按 docs 记录。

### 🛠 Changes Overview

**Scope:** learning application port, SQLite infrastructure, tests, docs

**Key Actions:**

- **Repository port**: 给 `LearningService` 拆出 `LearningRepository` protocol，并在学习、出题、作答后保存状态。
- **SQLite persistence**: 新增 `SQLiteLearningRepository`，持久化学习图谱、私有练习、作答和节点学习请求幂等结果。
- **Recovery tests**: 覆盖重新实例化 repository 后恢复掌握度、下一步推荐、同题重答不重复计分，以及缺失目标报错。
- **Docs**: 更新 README、ARCHITECTURE 和执行计划，明确当前仍是最小 SQLite repository，不是完整业务 schema 或迁移体系。

### 🧠 Design Intent (Why)

P0 闭环要求刷新后恢复学习结果。仅保存练习和作答还不够，节点学习请求的幂等响应也需要跨 repository 恢复；否则重启后同一 request_id 会重新触发模型。此切片保存 final_text 映射，保持 fixture 和未来真实模型路径的幂等语义一致。

### 📁 Files Modified

- `src/learngraph_lite/application/learning.py`
- `src/learngraph_lite/infrastructure/persistence.py`
- `src/learngraph_lite/infrastructure/__init__.py`
- `tests/test_sqlite_learning.py`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/exec-plans/active/learngraph-lite-implementation.md`
- `docs/learnings/2026-10/persist-idempotent-results.md`
