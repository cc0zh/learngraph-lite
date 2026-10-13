"""Application services for document upload, binding, retrieval and citations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from learngraph_lite.domain.documents import (
    Citation,
    Document,
    DocumentChunk,
    DocumentKind,
    chunk_document,
    make_citation,
    parse_text_document,
    tokenize,
)


@dataclass(frozen=True)
class SearchHit:
    chunk: DocumentChunk
    score: float
    citation: Citation


@dataclass(frozen=True)
class ChunkSearchResult:
    chunk: DocumentChunk
    score: float


class DocumentAccessError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DocumentRepository(Protocol):
    def save_document(self, document: Document, chunks: tuple[DocumentChunk, ...]) -> None: ...

    def bind_to_goal(self, goal_id: str, document_id: str) -> None: ...

    def bind_to_node(self, goal_id: str, node_id: str, document_id: str) -> None: ...

    def unbind_from_goal(self, goal_id: str, document_id: str) -> None: ...

    def unbind_from_node(self, goal_id: str, node_id: str, document_id: str) -> None: ...

    def bound_document_ids(self, goal_id: str, node_id: str | None = None) -> set[str]: ...

    def search_chunks(self, document_ids: set[str], query_tokens: set[str], limit: int) -> tuple[ChunkSearchResult, ...]: ...

    def resolve_citation(self, citation: Citation) -> DocumentChunk: ...


@dataclass
class InMemoryDocumentRepository:
    documents: dict[str, Document] = field(default_factory=dict)
    chunks_by_document: dict[str, tuple[DocumentChunk, ...]] = field(default_factory=dict)
    goal_bindings: dict[str, set[str]] = field(default_factory=dict)
    node_bindings: dict[tuple[str, str], set[str]] = field(default_factory=dict)

    def save_document(self, document: Document, chunks: tuple[DocumentChunk, ...]) -> None:
        self.documents[document.id] = document
        self.chunks_by_document[document.id] = chunks

    def bind_to_goal(self, goal_id: str, document_id: str) -> None:
        self._require_document(document_id)
        self.goal_bindings.setdefault(goal_id, set()).add(document_id)

    def bind_to_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        self._require_document(document_id)
        if document_id not in self.goal_bindings.get(goal_id, set()):
            raise ValueError("document must be bound to goal before binding to node")
        self.node_bindings.setdefault((goal_id, node_id), set()).add(document_id)

    def bound_document_ids(self, goal_id: str, node_id: str | None = None) -> set[str]:
        ids = set(self.goal_bindings.get(goal_id, set()))
        if node_id is not None:
            ids &= self.node_bindings.get((goal_id, node_id), set())
        return ids

    def unbind_from_goal(self, goal_id: str, document_id: str) -> None:
        self.goal_bindings.get(goal_id, set()).discard(document_id)
        for (bound_goal, _), documents in self.node_bindings.items():
            if bound_goal == goal_id:
                documents.discard(document_id)

    def unbind_from_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        self.node_bindings.get((goal_id, node_id), set()).discard(document_id)

    def chunks_for(self, document_ids: set[str]) -> tuple[DocumentChunk, ...]:
        chunks: list[DocumentChunk] = []
        for document_id in sorted(document_ids):
            chunks.extend(self.chunks_by_document.get(document_id, ()))
        return tuple(chunks)

    def search_chunks(self, document_ids: set[str], query_tokens: set[str], limit: int) -> tuple[ChunkSearchResult, ...]:
        results: list[ChunkSearchResult] = []
        for chunk in self.chunks_for(document_ids):
            chunk_tokens = tokenize(chunk.text)
            chunk_text = chunk.text.casefold()
            score = sum(1 for token in query_tokens if token in chunk_tokens or token in chunk_text)
            if score > 0:
                results.append(ChunkSearchResult(chunk=chunk, score=score))
        results.sort(key=lambda result: (-result.score, result.chunk.document_id, result.chunk.index))
        return tuple(results[:limit])

    def resolve_citation(self, citation: Citation) -> DocumentChunk:
        document = self.documents.get(citation.document_id)
        if document is None:
            raise ValueError("unknown citation document")
        if document.version != citation.document_version:
            raise ValueError("citation document version is stale")
        for chunk in self.chunks_by_document.get(citation.document_id, ()):
            if chunk.id == citation.chunk_id and chunk.document_version == citation.document_version:
                return chunk
        raise ValueError("citation chunk is missing")

    def _require_document(self, document_id: str) -> None:
        if document_id not in self.documents:
            raise ValueError(f"unknown document: {document_id}")


class DocumentService:
    def __init__(self, repository: DocumentRepository):
        self._repository = repository

    def upload_text(self, document_id: str, title: str, content: str, *, kind: DocumentKind = DocumentKind.TEXT) -> Document:
        document = parse_text_document(document_id, title, content, kind=kind)
        self._repository.save_document(document, chunk_document(document))
        return document

    def bind_goal(self, goal_id: str, document_id: str) -> None:
        self._repository.bind_to_goal(goal_id, document_id)

    def bind_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        self._repository.bind_to_node(goal_id, node_id, document_id)

    def unbind_goal(self, goal_id: str, document_id: str) -> None:
        self._repository.unbind_from_goal(goal_id, document_id)

    def unbind_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        self._repository.unbind_from_node(goal_id, node_id, document_id)

    def search(self, goal_id: str, query: str, *, node_id: str | None = None, limit: int = 5) -> tuple[SearchHit, ...]:
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 5:
            raise DocumentAccessError("invalid_document_request", "Query must contain 1–500 characters; limit is 1–5.")
        document_ids = self._repository.bound_document_ids(goal_id, node_id)
        if not document_ids:
            raise DocumentAccessError("no_documents_bound", "no documents bound to this scope")
        query_tokens = set(tokenize(query)[:64])
        if not query_tokens:
            return ()
        results = self._repository.search_chunks(document_ids, query_tokens, limit)
        return tuple(
            SearchHit(chunk=result.chunk, score=result.score, citation=make_citation(f"src-{index + 1}", result.chunk))
            for index, result in enumerate(results)
        )

    def locate(self, citation: Citation) -> DocumentChunk:
        return self._repository.resolve_citation(citation)

    def locate_bound(self, goal_id: str, node_id: str, citation: Citation) -> DocumentChunk:
        if citation.document_id not in self._repository.bound_document_ids(goal_id, node_id):
            raise DocumentAccessError("source_unavailable", "Source is no longer bound to this node.")
        try:
            return self.locate(citation)
        except ValueError as exc:
            raise DocumentAccessError("source_stale", "Source version or chunk is no longer available.") from exc

    def answer_with_citations(self, goal_id: str, node_id: str, question: str) -> tuple[str, tuple[Citation, ...]]:
        hits = self.search(goal_id, question, node_id=node_id)
        if not hits:
            return "没有在已绑定资料中找到足够依据，不能给出带引用的回答。", ()
        citations = tuple(hit.citation for hit in hits)
        joined = "；".join(hit.chunk.text[:80].replace("\n", " ") for hit in hits)
        return f"根据已绑定资料：{joined}", citations
