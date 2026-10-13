# M4A 资料解析、检索与引用离线切片

## 用户诉求

继续按 docs/从零构建功能文档.md 实现 LearnGraph Lite，推进资料上传解析、检索、引用定位和 grounding 边界；不把未完成的 PDF/SQLite/前端能力写成已完成。

## 本次结果

- 新增 Document、DocumentChunk、Citation 领域模型。
- 支持 TXT/Markdown/PDF_TEXT 文本解析、分块和页码标记识别。
- 新增简单中英文 token 检索，中文同时索引单字与 bigram，避免短中文查询完全召回失败。
- 新增目标/节点资料绑定；未绑定资料时拒绝检索。
- 新增带引用回答的离线应用服务；空召回时明确说明不能给出带引用回答。
- 新增引用定位和旧 document_version 引用拒绝。

## 设计动机

M4A 的重点是让资料引用可核查，而不是一开始就引入复杂检索栈。先用内存仓库和 deterministic 检索把绑定、版本、引用定位这些业务边界跑通，后续再替换为 SQLite FTS5 和真实文件解析适配器。

## 关键文件

- src/learngraph_lite/domain/documents.py
- src/learngraph_lite/application/documents.py
- tests/test_documents.py
- docs/exec-plans/active/learngraph-lite-implementation.md

## 验证

- python scripts/run-python-tests.py：通过，21 Python tests passed。
- python scripts/check-python-boundaries.py：通过。
- npm.cmd run ci：通过，包含 21 个 Python 测试和 19 个 Node 模板工具测试。

## 未完成项

- 真实 PDF 二进制解析未实现；当前只有 PDF_TEXT，即已抽取文本模式。
- SQLite FTS5 和前端资料页未接入。
- 资料型学习页 grounding 属于 M4B。
