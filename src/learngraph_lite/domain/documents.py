"""Document parsing, chunking and citation primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class DocumentKind(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    PDF_TEXT = "pdf_text"


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    kind: DocumentKind
    text: str
    version: int = 1


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    document_id: str
    document_version: int
    index: int
    text: str
    start_offset: int
    end_offset: int
    page_number: int | None = None


@dataclass(frozen=True)
class Citation:
    id: str
    document_id: str
    document_version: int
    chunk_id: str
    quote: str
    start_offset: int
    end_offset: int
    page_number: int | None = None


def parse_text_document(document_id: str, title: str, content: str, *, kind: DocumentKind = DocumentKind.TEXT) -> Document:
    if kind not in {DocumentKind.TEXT, DocumentKind.MARKDOWN, DocumentKind.PDF_TEXT}:
        raise ValueError(f"unsupported document kind: {kind}")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("document text is empty")
    return Document(id=document_id, title=title.strip() or document_id, kind=kind, text=normalized)


def chunk_document(document: Document, *, max_chars: int = 320, overlap: int = 40) -> tuple[DocumentChunk, ...]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")

    chunks: list[DocumentChunk] = []
    sections = _page_sections(document.text)
    for page_number, section_start, section_end in sections:
        _append_chunks(
            chunks,
            document=document,
            span_start=section_start,
            span_end=section_end,
            page_number=page_number,
            max_chars=max_chars,
            overlap=overlap,
        )
    return tuple(chunks)


def _append_chunks(
    chunks: list[DocumentChunk],
    *,
    document: Document,
    span_start: int,
    span_end: int,
    page_number: int | None,
    max_chars: int,
    overlap: int,
) -> None:
    start = span_start
    while start < span_end:
        end = min(span_end, start + max_chars)
        if end < len(document.text):
            boundary = max(
                document.text.rfind("\n", start, end),
                document.text.rfind("。", start, end),
                document.text.rfind(".", start, end),
            )
            if boundary > start + max_chars // 2:
                end = boundary + 1
        raw = document.text[start:end]
        text = raw.strip()
        if text:
            leading = len(raw) - len(raw.lstrip())
            chunks.append(
                DocumentChunk(
                    id=f"{document.id}:c{len(chunks) + 1}",
                    document_id=document.id,
                    document_version=document.version,
                    index=len(chunks),
                    text=text,
                    start_offset=start + leading,
                    end_offset=end,
                    page_number=page_number,
                )
            )
        if end >= span_end:
            break
        start = max(span_start, end - overlap)


def make_citation(citation_id: str, chunk: DocumentChunk, quote: str | None = None) -> Citation:
    selected = (quote or chunk.text[:120]).strip()
    local_start = chunk.text.find(selected)
    if local_start < 0:
        local_start = 0
    start = chunk.start_offset + local_start
    return Citation(
        id=citation_id,
        document_id=chunk.document_id,
        document_version=chunk.document_version,
        chunk_id=chunk.id,
        quote=selected,
        start_offset=start,
        end_offset=start + len(selected),
        page_number=chunk.page_number,
    )


def tokenize(text: str) -> tuple[str, ...]:
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.casefold())
    tokens: list[str] = []
    for word in words:
        tokens.append(word)
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            tokens.extend(word[index] for index in range(len(word)))
            tokens.extend(word[index : index + 2] for index in range(max(0, len(word) - 1)))
    return tuple(tokens)


def _page_sections(text: str) -> tuple[tuple[int | None, int, int], ...]:
    markers = list(re.finditer(r"\f|\n\s*---\s*page\s+(\d+)\s*---\s*\n", text, flags=re.IGNORECASE))
    if not markers:
        return ((None, 0, len(text)),)
    sections: list[tuple[int | None, int, int]] = []
    page: int | None = 1
    start = 0
    for match in markers:
        if start < match.start():
            sections.append((page, start, match.start()))
        page = int(match.group(1)) if match.group(1) else (page or 0) + 1
        start = match.end()
    if start < len(text):
        sections.append((page, start, len(text)))
    return tuple(sections)
