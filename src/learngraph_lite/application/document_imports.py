"""Bounded local upload jobs; original bytes and terminal state survive restart."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from threading import RLock, Semaphore
from typing import Callable, Protocol
from uuid import uuid4

from learngraph_lite.application.documents import DocumentAccessError, DocumentRepository, DocumentService
from learngraph_lite.application.planning import PlanningService
from learngraph_lite.domain.documents import Document, DocumentChunk, DocumentKind, chunk_document, parse_text_document


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 200000
MAX_PDF_PAGES = 100


@dataclass(frozen=True)
class UploadRecord:
    document_id: str
    filename: str
    kind: DocumentKind | None
    status: str
    size_bytes: int
    content_hash: str
    revision: int = 1
    reason: str | None = None


class ParseError(ValueError):
    def __init__(self, code: str, *, unsupported: bool = False):
        super().__init__(code)
        self.code, self.unsupported = code, unsupported


class UploadRepository(DocumentRepository, Protocol):
    def create_upload(self, record: UploadRecord, original: bytes) -> None: ...

    def get_upload(self, document_id: str) -> UploadRecord: ...

    def list_uploads(self, offset: int, limit: int) -> tuple[tuple[UploadRecord, ...], int]: ...

    def document_bindings(self, document_id: str) -> tuple[dict, ...]: ...

    def original_bytes(self, document_id: str) -> bytes: ...

    def transition_upload(self, document_id: str, expected: tuple[str, ...], status: str) -> bool: ...

    def finish_upload(self, document_id: str, status: str, reason: str | None,
                      document: Document | None = None, chunks: tuple[DocumentChunk, ...] = ()) -> None: ...

    def recover_uploads(self) -> None: ...

    def document_chunks(self, document_id: str) -> tuple[DocumentChunk, ...]: ...

    def delete_document(self, document_id: str) -> None: ...


class DocumentImports:
    def __init__(self, repository: UploadRepository, parser: Callable[[bytes, DocumentKind], str],
                 planning: PlanningService):
        self._repository, self._parser, self._planning = repository, parser, planning
        self.documents = DocumentService(repository)
        self._lock = RLock()
        self._closed = False
        self._slots = Semaphore(4)
        repository.recover_uploads()
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="document-parse")

    def upload(self, filename: str, original: bytes) -> dict:
        if len(original) > MAX_UPLOAD_BYTES:
            raise DocumentAccessError("upload_too_large", "File exceeds 10MB.")
        # A display name is never interpreted as a server path.
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:255] or "upload"
        extension = filename.rsplit(".", 1)[-1].casefold()
        kind = {"txt": DocumentKind.TEXT, "md": DocumentKind.MARKDOWN, "markdown": DocumentKind.MARKDOWN,
                "pdf": DocumentKind.PDF_TEXT}.get(extension)
        record = UploadRecord(str(uuid4()), filename, kind, "uploaded", len(original),
                              hashlib.sha256(original).hexdigest())
        with self._lock:
            self._reserve()
            try:
                self._repository.create_upload(record, original)
                self._workers.submit(self._parse, record.document_id)
            except Exception:
                self._slots.release()
                raise
        return asdict(record)

    def get(self, document_id: str) -> dict:
        return asdict(self._record(document_id))

    def list(self, *, offset: int = 0, limit: int = 50) -> dict:
        if offset < 0 or not 1 <= limit <= 50:
            raise DocumentAccessError("invalid_document_request", "Invalid document page.")
        records, total = self._repository.list_uploads(offset, limit)
        return {"documents": [asdict(record) for record in records], "total": total, "offset": offset}

    def bindings(self, document_id: str) -> dict:
        self._record(document_id)
        return {"bindings": list(self._repository.document_bindings(document_id))}

    def bound(self, goal_id: str, node_id: str | None = None) -> dict:
        self._scope(goal_id, node_id)
        return {"document_ids": sorted(self._repository.bound_document_ids(goal_id, node_id))}

    def chunks(self, document_id: str, *, offset: int = 0, limit: int = 50) -> dict:
        self._ready(document_id)
        if offset < 0 or not 1 <= limit <= 50:
            raise DocumentAccessError("invalid_document_request", "Invalid chunk page.")
        chunks = self._repository.document_chunks(document_id)
        return {"document_id": document_id, "total": len(chunks), "offset": offset,
                "chunks": [{**asdict(chunk), "text_hash": hashlib.sha256(chunk.text.encode()).hexdigest()}
                           for chunk in chunks[offset:offset + limit]]}

    def reparse(self, document_id: str) -> dict:
        with self._lock:
            record = self._record(document_id)
            if record.status in {"ready", "uploaded", "parsing"}:
                return asdict(record)
            self._reserve()
            try:
                if self._repository.transition_upload(document_id, ("failed", "unsupported"), "uploaded"):
                    self._workers.submit(self._parse, document_id)
                else:
                    self._slots.release()
            except Exception:
                self._slots.release()
                raise
            return self.get(document_id)

    def delete(self, document_id: str) -> None:
        self._record(document_id)
        self._repository.delete_document(document_id)

    def bind(self, goal_id: str, document_id: str, node_id: str | None = None, *, remove: bool = False) -> dict:
        self._scope(goal_id, node_id)
        if not remove:
            self._ready(document_id)
        if node_id is None:
            (self.documents.unbind_goal if remove else self.documents.bind_goal)(goal_id, document_id)
        else:
            if not remove and document_id not in self._repository.bound_document_ids(goal_id):
                raise DocumentAccessError("goal_binding_required", "Bind the document to this goal first.")
            (self.documents.unbind_node if remove else self.documents.bind_node)(goal_id, node_id, document_id)
        return {"document_ids": sorted(self._repository.bound_document_ids(goal_id, node_id))}

    def search(self, goal_id: str, query: str, *, node_id: str | None = None, limit: int = 5) -> dict:
        self._scope(goal_id, node_id)
        hits = self.documents.search(goal_id, query, node_id=node_id, limit=limit)
        return {"hits": [asdict(hit) for hit in hits], "empty": not hits}

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._workers.shutdown(wait=True)

    def _reserve(self) -> None:
        if self._closed:
            raise DocumentAccessError("shutting_down", "Document service is closing.")
        if not self._slots.acquire(blocking=False):
            raise DocumentAccessError("document_capacity_exceeded", "Document parsing queue is full.")

    def _record(self, document_id: str) -> UploadRecord:
        try:
            return self._repository.get_upload(document_id)
        except KeyError as exc:
            raise DocumentAccessError("document_not_found", "Document does not exist.") from exc

    def _ready(self, document_id: str) -> None:
        if self._record(document_id).status != "ready":
            raise DocumentAccessError("document_not_ready", "Document is not ready.")

    def _scope(self, goal_id: str, node_id: str | None) -> None:
        state = self._planning.get_state(goal_id)
        if node_id is not None and (state.graph is None or not any(node.id == node_id for node in state.graph.nodes)):
            raise DocumentAccessError("node_not_found", "Node does not exist in this goal.")

    def _parse(self, document_id: str) -> None:
        try:
            if not self._repository.transition_upload(document_id, ("uploaded",), "parsing"):
                return
            record = self._repository.get_upload(document_id)
            if record.kind is None:
                raise ParseError("unsupported_format", unsupported=True)
            text = self._parser(self._repository.original_bytes(document_id), record.kind)
            if len(text) > MAX_TEXT_CHARS:
                raise ParseError("text_limit_exceeded")
            document = parse_text_document(document_id, record.filename, text, kind=record.kind)
            self._repository.finish_upload(document_id, "ready", None, document, chunk_document(document))
        except ParseError as exc:
            self._repository.finish_upload(document_id, "unsupported" if exc.unsupported else "failed", exc.code)
        except Exception:
            self._repository.finish_upload(document_id, "failed", "parse_failed")
        finally:
            self._slots.release()
