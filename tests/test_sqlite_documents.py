from __future__ import annotations

import tempfile
from pathlib import Path

from learngraph_lite.application.documents import DocumentService
from learngraph_lite.domain.documents import Citation, DocumentKind
from learngraph_lite.infrastructure import SQLiteDocumentRepository


def test_sqlite_document_repository_restores_bindings_and_searches_with_fts5():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        docs = DocumentService(SQLiteDocumentRepository(database))
        document = docs.upload_text(
            "d1",
            "RAG notes",
            (
                "RAG 系统先检索资料片段，再生成带引用的回答。\n"
                "Chunking controls retrieval quality."
            ),
            kind=DocumentKind.MARKDOWN,
        )
        docs.bind_goal("g1", "d1")
        docs.bind_node("g1", "citations", "d1")

        restored = DocumentService(SQLiteDocumentRepository(database))
        zh_hits = restored.search("g1", "检索 引用", node_id="citations")
        en_hits = restored.search("g1", "chunking retrieval", node_id="citations")
        located = restored.locate(zh_hits[0].citation)
        stale = Citation(
            id=zh_hits[0].citation.id,
            document_id=zh_hits[0].citation.document_id,
            document_version=0,
            chunk_id=zh_hits[0].citation.chunk_id,
            quote=zh_hits[0].citation.quote,
            start_offset=zh_hits[0].citation.start_offset,
            end_offset=zh_hits[0].citation.end_offset,
            page_number=zh_hits[0].citation.page_number,
        )
        try:
            restored.locate(stale)
        except ValueError as exc:
            assert "stale" in str(exc)
        else:
            raise AssertionError("stale citation should fail")

    assert zh_hits
    assert zh_hits[0].citation.document_id == document.id
    assert "检索" in zh_hits[0].chunk.text
    assert en_hits
    assert en_hits[0].score > 0
    assert located.id == zh_hits[0].chunk.id


def test_sqlite_document_repository_keeps_node_scope_and_empty_recall_explicit():
    with tempfile.TemporaryDirectory() as tmpdir:
        docs = DocumentService(SQLiteDocumentRepository(Path(tmpdir) / "learngraph.db"))
        docs.upload_text("d1", "RAG notes", "只讨论检索和引用。")
        docs.bind_goal("g1", "d1")

        try:
            docs.search("g1", "检索", node_id="citations")
        except ValueError as exc:
            assert "no documents bound" in str(exc)
        else:
            raise AssertionError("unbound node search should fail")

        docs.bind_node("g1", "citations", "d1")
        assert docs.search("g1", "完全无关", node_id="citations") == ()


def test_sqlite_document_repository_requires_goal_binding_before_node_binding():
    with tempfile.TemporaryDirectory() as tmpdir:
        docs = DocumentService(SQLiteDocumentRepository(Path(tmpdir) / "learngraph.db"))
        docs.upload_text("d1", "RAG notes", "资料内容。")

        try:
            docs.bind_node("g1", "citations", "d1")
        except ValueError as exc:
            assert "bound to goal" in str(exc)
        else:
            raise AssertionError("node binding should require goal binding first")
