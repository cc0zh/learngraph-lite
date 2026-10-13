from __future__ import annotations

from learngraph_lite.application.documents import DocumentService, InMemoryDocumentRepository
from learngraph_lite.domain.documents import Citation, DocumentKind


def service() -> DocumentService:
    return DocumentService(InMemoryDocumentRepository())


def test_upload_chunks_and_search_chinese_and_english_bound_to_node():
    docs = service()
    docs.upload_text(
        "d1",
        "RAG notes",
        "RAG 系统先检索资料片段，再生成带引用的回答。\nChunking controls retrieval quality.",
        kind=DocumentKind.MARKDOWN,
    )
    docs.bind_goal("g1", "d1")
    docs.bind_node("g1", "citations", "d1")

    zh_hits = docs.search("g1", "检索 引用", node_id="citations")
    assert zh_hits
    assert zh_hits[0].citation.document_id == "d1"
    assert "检索" in zh_hits[0].chunk.text

    en_hits = docs.search("g1", "chunking retrieval", node_id="citations")
    assert en_hits
    assert en_hits[0].score >= 1


def test_unbound_documents_and_empty_recall_are_explicit():
    docs = service()
    docs.upload_text("d1", "RAG notes", "只讨论检索和引用。")

    try:
        docs.search("g1", "检索", node_id="citations")
    except ValueError as exc:
        assert "no documents bound" in str(exc)
    else:
        raise AssertionError("unbound search should fail")

    docs.bind_goal("g1", "d1")
    docs.bind_node("g1", "citations", "d1")
    assert docs.search("g1", "完全无关", node_id="citations") == ()
    answer, citations = docs.answer_with_citations("g1", "citations", "完全无关")
    assert "不能给出带引用" in answer
    assert citations == ()


def test_citation_location_and_stale_version_detection():
    docs = service()
    document = docs.upload_text("d1", "Paged text", "第一页内容\n--- page 2 ---\n第二页讲引用定位。")
    docs.bind_goal("g1", "d1")
    docs.bind_node("g1", "citations", "d1")
    hit = docs.search("g1", "引用定位", node_id="citations")[0]
    located = docs.locate(hit.citation)
    assert located.id == hit.chunk.id
    assert located.document_version == document.version
    assert located.page_number == 2

    stale = Citation(
        id=hit.citation.id,
        document_id=hit.citation.document_id,
        document_version=0,
        chunk_id=hit.citation.chunk_id,
        quote=hit.citation.quote,
        start_offset=hit.citation.start_offset,
        end_offset=hit.citation.end_offset,
        page_number=hit.citation.page_number,
    )
    try:
        docs.locate(stale)
    except ValueError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale citation should fail")
