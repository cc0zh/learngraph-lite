"""pypdf/text extraction in a child process with a killable wall time limit."""

from __future__ import annotations

import io
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from learngraph_lite.application.document_imports import MAX_PDF_PAGES, MAX_TEXT_CHARS, ParseError
from learngraph_lite.domain.documents import DocumentKind


class SubprocessDocumentParser:
    def __init__(self, *, timeout_seconds: float = 20):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("parser timeout must be positive")
        self.timeout_seconds = timeout_seconds

    def __call__(self, original: bytes, kind: DocumentKind) -> str:
        try:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2]) + os.pathsep + environment.get("PYTHONPATH", "")
            result = subprocess.run(
                [sys.executable, "-m", "learngraph_lite.infrastructure.document_parser", kind.value],
                input=original, capture_output=True, timeout=self.timeout_seconds, check=False, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            # subprocess.run kills and reaps the child before raising.
            raise ParseError("parse_timeout") from exc
        if result.returncode != 0:
            raise ParseError("parse_failed")
        try:
            output = json.loads(result.stdout)
            if "error" in output:
                raise ParseError(output["error"], unsupported=output["unsupported"])
            return output["text"]
        except (ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, ParseError):
                raise
            raise ParseError("parse_failed") from exc


def extract(original: bytes, kind: DocumentKind) -> str:
    if kind == DocumentKind.PDF_TEXT:
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(original))
            if reader.is_encrypted:
                raise ParseError("encrypted_pdf", unsupported=True)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ParseError("page_limit_exceeded")
            pages = []
            length = 0
            for page in reader.pages:
                text = page.extract_text() or ""
                length += len(text) + 1
                if length > MAX_TEXT_CHARS:
                    raise ParseError("text_limit_exceeded")
                pages.append(text)
            if not any(page.strip() for page in pages):
                raise ParseError("needs_ocr", unsupported=True)
            # Leading/trailing empty pages retain their page number through explicit markers.
            text = "".join(f"\n--- page {index + 1} ---\n{page}" for index, page in enumerate(pages))
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError("invalid_pdf", unsupported=True) from exc
    else:
        try:
            text = original.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ParseError("invalid_utf8", unsupported=True) from exc
    if len(text) > MAX_TEXT_CHARS:
        raise ParseError("text_limit_exceeded")
    if not text.strip():
        raise ParseError("empty_document", unsupported=True)
    if "\ufffd" in text or any(ord(char) < 32 and char not in "\n\r\t\f" for char in text):
        raise ParseError("unreadable_text", unsupported=True)
    return text


if __name__ == "__main__":
    try:
        output = {"text": extract(sys.stdin.buffer.read(), DocumentKind(sys.argv[1]))}
    except ParseError as exc:
        output = {"error": exc.code, "unsupported": exc.unsupported}
    except Exception:
        output = {"error": "parse_failed", "unsupported": False}
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode("utf-8"))
