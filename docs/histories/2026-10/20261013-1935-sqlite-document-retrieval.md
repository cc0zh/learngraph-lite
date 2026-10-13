## [2026-10-13 19:35] | Task: SQLite document retrieval

### 🤖 Execution Context

- **Agent ID**: `Codex`
- **Base Model**: `GPT-6`
- **Runtime**: `Codex CLI / Windows PowerShell`

### 📥 User Query

> 继续推进 LearnGraph Lite 作为 Agent 应用开发方向的简历作品；优先补能离线验证、贴近 P1 资料引用能力的切片，并按 docs 记录。

### 🛠 Changes Overview

**Scope:** document application port, SQLite infrastructure, tests, docs

**Key Actions:**

- **Repository port**: 给 document application service 拆出 `DocumentRepository` protocol 和 `search_chunks` 端口。
- **SQLite FTS5 adapter**: 新增 `SQLiteDocumentRepository`，持久化文本资料、chunk、目标/节点绑定，并用 FTS5 索引 chunk token。
- **Recovery tests**: 覆盖重新实例化 repository 后仍能按绑定作用域检索、定位引用和拒绝过期引用。
- **Docs**: 更新 README、ARCHITECTURE 和执行计划，明确 FTS5 最小适配器已完成，真实 PDF 与前端原文页仍待实现。

### 🧠 Design Intent (Why)

M4A 已有内存检索闭环，但作品需要展示资料引用能力可以落到本地持久化。此切片沿用现有 `tokenize()`，把 token 串写入 FTS5，避免引入中文分词第三方依赖；应用层仍只依赖 repository port，方便后续替换更强检索。

### 📁 Files Modified

- `src/learngraph_lite/application/documents.py`
- `src/learngraph_lite/infrastructure/persistence.py`
- `src/learngraph_lite/infrastructure/__init__.py`
- `tests/test_sqlite_documents.py`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/exec-plans/active/learngraph-lite-implementation.md`
- `docs/learnings/2026-10/sqlite-fts5-token-index.md`
