"""Document parsing, chunking and citation primitives."""

from __future__ import annotations

import logging
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
    heading: str | None = None


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
    heading: str | None = None


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
    sections = tuple(
        (page, start + local_start, start + local_end, heading)
        for page, start, end in _page_sections(document.text)
        for _, local_start, local_end, heading in (
            _heading_sections(document.text[start:end]) if document.kind == DocumentKind.MARKDOWN else
            ((None, 0, end - start, None),)
        )
    )
    for page_number, section_start, section_end, heading in sections:
        _append_chunks(
            chunks,
            document=document,
            span_start=section_start,
            span_end=section_end,
            page_number=page_number,
            heading=heading,
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
    heading: str | None,
    max_chars: int,
    overlap: int,
) -> None:
    start = span_start
    while start < span_end:
        end = min(span_end, start + max_chars)
        if end < span_end:
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
                    end_offset=start + leading + len(text),
                    page_number=page_number,
                    heading=heading,
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
        heading=chunk.heading,
    )


def tokenize(text: str) -> tuple[str, ...]:
    import jieba

    jieba.setLogLevel(logging.WARNING)
    return tuple(token for token in jieba.cut_for_search(text.casefold(), HMM=False)
                 if re.fullmatch(r"[a-z0-9_\u4e00-\u9fff]+", token))


def _page_sections(text: str) -> tuple[tuple[int | None, int, int], ...]:
    markers = list(re.finditer(r"\f|(?:^|\n)\s*---\s*page\s+(\d+)\s*---\s*\n", text, flags=re.IGNORECASE))
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


def _heading_sections(text: str) -> tuple[tuple[None, int, int, str | None], ...]:
    starts: list[tuple[int, str | None]] = [(0, None)]
    fence: str | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, rest = marker.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None:
            heading = re.match(r"^ {0,3}#{1,6}[ \t]+(.+)$", line)
            if heading:
                label = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(1)).strip()
                if offset == 0:
                    starts.clear()
                starts.append((offset, label))
        offset += len(line)
    return tuple((None, start, starts[index + 1][0] if index + 1 < len(starts) else len(text), heading)
                 for index, (start, heading) in enumerate(starts))
