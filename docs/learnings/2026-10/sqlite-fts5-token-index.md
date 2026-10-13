# 用 FTS5 存 token 串支持最小中文检索

## 是什么

SQLite FTS5 能提供轻量全文检索，但默认 tokenizer 对中文词边界不够理想。LearnGraph Lite 的最小适配器没有引入分词库，而是复用领域层已有的 `tokenize()`：保存 chunk 原文到普通表，同时把中英文 token 串写入 FTS5 表用于 MATCH 查询。

## 为什么需要

作品阶段需要展示“资料引用可以持久化并检索”，但还不需要做完整搜索平台。直接依赖 SQLite FTS5 可以保持本地单用户、无服务依赖；复用已有 token 规则能让内存检索和 SQLite 检索在中英文样例上行为接近。

## 怎么想

- 普通表保存权威数据：document、chunk、offset、page_number 和绑定关系。
- FTS 表保存检索索引：chunk_id、document_id 和 token 串。
- 搜索时先用 FTS5 缩小候选，再用同一套 `query_tokens` 计算 score 并排序。
- Citation 定位仍回普通表校验 document version，不能只相信 FTS 命中。

## 取舍

这个方案适合最小本地作品切片，不等于成熟中文搜索。它不做 BM25 调参、语义召回、重排或复杂分词；后续如果引入成熟中文分词或向量检索，应保留 repository port，让应用层调用方式不变。
