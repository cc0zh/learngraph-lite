"""Application services for document upload, binding, retrieval and citations."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    score: int
    citation: Citation


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

    def chunks_for(self, document_ids: set[str]) -> tuple[DocumentChunk, ...]:
        chunks: list[DocumentChunk] = []
        for document_id in sorted(document_ids):
            chunks.extend(self.chunks_by_document.get(document_id, ()))
        return tuple(chunks)

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
    def __init__(self, repository: InMemoryDocumentRepository):
        self._repository = repository

    def upload_text(self, document_id: str, title: str, content: str, *, kind: DocumentKind = DocumentKind.TEXT) -> Document:
        document = parse_text_document(document_id, title, content, kind=kind)
        self._repository.save_document(document, chunk_document(document))
        return document

    def bind_goal(self, goal_id: str, document_id: str) -> None:
        self._repository.bind_to_goal(goal_id, document_id)

    def bind_node(self, goal_id: str, node_id: str, document_id: str) -> None:
        self._repository.bind_to_node(goal_id, node_id, document_id)

    def search(self, goal_id: str, query: str, *, node_id: str | None = None, limit: int = 3) -> tuple[SearchHit, ...]:
        document_ids = self._repository.bound_document_ids(goal_id, node_id)
        if not document_ids:
            raise ValueError("no documents bound to this scope")
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return ()
        hits: list[SearchHit] = []
        for chunk in self._repository.chunks_for(document_ids):
            chunk_tokens = tokenize(chunk.text)
            chunk_text = chunk.text.casefold()
            score = sum(1 for token in query_tokens if token in chunk_tokens or token in chunk_text)
            if score > 0:
                hits.append(SearchHit(chunk=chunk, score=score, citation=make_citation(f"src-{len(hits) + 1}", chunk)))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.document_id, hit.chunk.index))
        return tuple(hits[:limit])

    def locate(self, citation: Citation) -> DocumentChunk:
        return self._repository.resolve_citation(citation)

    def answer_with_citations(self, goal_id: str, node_id: str, question: str) -> tuple[str, tuple[Citation, ...]]:
        hits = self.search(goal_id, question, node_id=node_id)
        if not hits:
            return "没有在已绑定资料中找到足够依据，不能给出带引用的回答。", ()
        citations = tuple(hit.citation for hit in hits)
        joined = "；".join(hit.chunk.text[:80].replace("\n", " ") for hit in hits)
        return f"根据已绑定资料：{joined}", citations
