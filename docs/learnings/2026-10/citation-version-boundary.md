# 引用必须绑定内容版本

## 是什么

引用不只是 document_id 和一句 quote。可核查引用至少需要 document_id、document_version、chunk_id、文本范围和可展示摘录。这样当资料被重新解析、重传或切块策略变化时，系统能判断旧引用是否仍然有效。

## 为什么需要

RAG 应用最容易出现“看起来有引用，但引用已经不是同一份内容”的问题。即使是本地简历作品，也要让回答边界可信：找不到资料就说找不到，引用版本过期就拒绝定位，而不是继续展示旧 chunk。

## 怎么用

- 上传时生成 Document version 和 DocumentChunk。
- 检索返回 SearchHit，同时附带 Citation。
- 定位时先检查 document_version，再检查 chunk_id。
- 空召回返回无引用回答，不能伪造 citation。

## 常见陷阱

- 只保存文件 ID 不算 grounding，因为回答无法证明读取了哪个片段。
- 中文查询不能只按空格分词，否则“引用定位”这类短查询容易漏召回。
- PDF 页码属于定位元数据，文本抽取阶段就要保留下来；没有真实 PDF parser 时应明确标注只支持 PDF_TEXT。
