from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from learngraph_lite.agent_core import ModelResponse, ToolCall
from learngraph_lite.application.document_imports import DocumentImports, MAX_UPLOAD_BYTES, ParseError, UploadRecord
from learngraph_lite.application.documents import DocumentAccessError, DocumentService
from learngraph_lite.application.planning import PlanningService
from learngraph_lite.bootstrap import build_fixture_loop, create_real_app
from learngraph_lite.domain.documents import DocumentKind, chunk_document, parse_text_document, tokenize
from learngraph_lite.domain.learning import GraphNode
from learngraph_lite.infrastructure import SQLiteDocumentRepository, SQLitePlanningRepository
from learngraph_lite.infrastructure.document_parser import SubprocessDocumentParser, extract
from learngraph_lite.presentation.http import create_app


def planning(database):
    service = PlanningService(SQLitePlanningRepository(database))
    service.create_goal("g1", "学习资料", desired_outcome="能解释", current_level="入门", time_budget_minutes=60)
    service.confirm_goal("g1")
    service.save_graph_draft("g1", (GraphNode("n1", "引用", 10),), ())
    return service


def pdf(pages=("alpha retrieval", "beta citations"), *, encrypted=False):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            content = DecodedStreamObject()
            content.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = content
    if encrypted:
        writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def wait_status(get, document_id, expected=None):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = get(document_id)
        if result["status"] not in {"uploaded", "parsing", "queued", "running"}:
            if expected:
                assert result["status"] == expected, result
            return result
        time.sleep(0.01)
    raise AssertionError("parse job did not finish")


def expect_error(code, action):
    try:
        action()
    except (DocumentAccessError, ParseError) as exc:
        assert exc.code == code, exc
    else:
        raise AssertionError(f"expected {code}")


def test_http_upload_pdf_bind_search_agent_citation_and_deletion():
    class Model:
        def __init__(self):
            self.calls = 0
            self.closed = False

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(tool_calls=(ToolCall("search", "search_documents", '{"query":"beta"}'),))
            return ModelResponse(content="资料第二页解释 citations [C1]。")

        def close(self):
            self.closed = True

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "db.sqlite"
        service = planning(database)
        model = Model()
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as client:
            version = service.get_state("g1").version
            assert client.post("/api/goals/g1/graph/publish", json={"expected_version": version, "expected_revision": 0}).status_code == 200
            uploaded = client.post("/api/documents", files={"file": ("../../资料.pdf", pdf(), "application/pdf")})
            assert uploaded.status_code == 202, uploaded.text
            document_id = uploaded.json()["document_id"]
            assert uploaded.json()["filename"] == "资料.pdf" and uploaded.json()["status"] == "uploaded"
            get = lambda identifier: client.get(f"/api/documents/{identifier}").json()
            assert wait_status(get, document_id, "ready")["revision"] == 1
            assert model.calls == 0
            chunks = client.get(f"/api/documents/{document_id}/chunks").json()["chunks"]
            assert [chunk["page_number"] for chunk in chunks] == [1, 2]
            assert all(chunk["text_hash"] == hashlib.sha256(chunk["text"].encode()).hexdigest() for chunk in chunks)
            for body in ({"document_id": document_id}, {"document_id": document_id, "node_id": "n1"}):
                assert client.post("/api/goals/g1/document-bindings", json=body).status_code == 200
            hits = client.post("/api/goals/g1/document-search", json={"query": "beta", "node_id": "n1"}).json()["hits"]
            assert len(hits) == 1 and hits[0]["citation"]["page_number"] == 2
            assert client.post(f"/api/documents/{document_id}/reparse").json()["status"] == "ready"
            run = client.post("/api/sessions/s1/runs", json={"request_id": "r1", "user_text": "beta 是什么", "goal_id": "g1", "node_id": "n1"})
            assert run.status_code == 202, run.text
            run_id = run.json()["run_id"]
            completed = wait_status(lambda identifier: client.get(f"/api/runs/{identifier}").json(), run_id, "completed")
            source = completed["output"]["citation_map"]["C1"]
            assert source["status"] == "valid" and source["page_number"] == 2
            assert client.get(f"/api/runs/{run_id}/citations/C1").status_code == 200
            assert client.delete(f"/api/documents/{document_id}").status_code == 200
            assert client.get(f"/api/runs/{run_id}/citations/C1").json()["error"]["code"] == "source_unavailable"
            assert client.get(f"/api/documents/{document_id}").status_code == 404
            markdown = "# 基础\nalpha 检索。\n```text\n# 示例而非标题\n```\n## 引用 ##\nbeta 来源定位。"
            uploaded = client.post("/api/documents", files={"file": ("资料.md", markdown.encode())}).json()
            identifier = uploaded["document_id"]
            wait_status(get, identifier, "ready")
            chunks = client.get(f"/api/documents/{identifier}/chunks").json()["chunks"]
            assert [chunk["heading"] for chunk in chunks] == ["基础", "引用"]
            assert all(markdown[chunk["start_offset"]:chunk["end_offset"]] == chunk["text"] for chunk in chunks)
            for body in ({"document_id": identifier}, {"document_id": identifier, "node_id": "n1"}):
                assert client.post("/api/goals/g1/document-bindings", json=body).status_code == 200
            model.calls = 0
            run = client.post("/api/sessions/s1/runs", json={"request_id": "r2", "user_text": "beta", "goal_id": "g1", "node_id": "n1"})
            run_id = run.json()["run_id"]
            completed = wait_status(lambda identifier: client.get(f"/api/runs/{identifier}").json(), run_id, "completed")
            source = completed["output"]["citation_map"]["C1"]
            assert source["heading"] == "引用" and source["page_number"] is None
            located = client.get(f"/api/runs/{run_id}/citations/C1").json()
            assert located["heading"] == "引用" and located["source"] == source
            with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
                snapshot = next(line for line in stream.iter_lines() if line.startswith("data: "))
                assert json.loads(snapshot[6:])["payload"]["output"] == completed["output"]
        assert model.closed


def test_real_parser_formats_limits_unsupported_and_killable_timeout():
    parser = SubprocessDocumentParser()
    for kind in (DocumentKind.TEXT, DocumentKind.MARKDOWN):
        assert parser("\ufeff# 中文检索\r\nUTF-8".encode(), kind) == "# 中文检索\r\nUTF-8"
    cases = [(b"\xff", DocumentKind.TEXT, "invalid_utf8"), (b"\x00abc", DocumentKind.TEXT, "unreadable_text"),
             (b"", DocumentKind.TEXT, "empty_document"), (b"broken", DocumentKind.PDF_TEXT, "invalid_pdf"),
             (pdf(("",)), DocumentKind.PDF_TEXT, "needs_ocr"),
             (pdf(encrypted=True), DocumentKind.PDF_TEXT, "encrypted_pdf")]
    for original, kind, code in cases:
        expect_error(code, lambda: parser(original, kind))
    expect_error("page_limit_exceeded", lambda: extract(pdf(("",) * 101), DocumentKind.PDF_TEXT))
    expect_error("text_limit_exceeded", lambda: parser(b"x" * 200001, DocumentKind.TEXT))
    # A real child cannot finish its Python startup within this timeout.
    expect_error("parse_timeout", lambda: SubprocessDocumentParser(timeout_seconds=0.000001)(b"abc", DocumentKind.TEXT))


def test_restart_reparse_original_ready_idempotence_and_persistence():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "db.sqlite"
        repository = SQLiteDocumentRepository(database)
        service = planning(database)
        raw = "检索资料。".encode()
        record = UploadRecord("interrupted", "资料.txt", DocumentKind.TEXT, "parsing", len(raw), hashlib.sha256(raw).hexdigest())
        repository.create_upload(record, raw)
        calls = []

        def parser(original, kind):
            calls.append(original)
            return extract(original, kind)

        imports = DocumentImports(repository, parser, service)
        try:
            assert imports.get(record.document_id)["reason"] == "interrupted"
            assert imports.get(record.document_id)["status"] == "failed"
            imports.reparse(record.document_id)
            assert wait_status(imports.get, record.document_id, "ready")["revision"] == 1
            assert imports.reparse(record.document_id)["status"] == "ready"
            assert calls == [raw] and repository.original_bytes(record.document_id) == raw
            imports.bind("g1", record.document_id)
        finally:
            imports.close()
        restored = DocumentImports(SQLiteDocumentRepository(database), parser, service)
        try:
            assert restored.get(record.document_id)["status"] == "ready"
            assert restored.search("g1", "检索")["hits"]
            restored.reparse(record.document_id)
            assert calls == [raw]
            uploaded = restored.upload("bad.bin", b"abc")
            failed = wait_status(restored.get, uploaded["document_id"], "unsupported")
            assert failed["reason"] == "unsupported_format"
            expect_error("document_not_ready", lambda: restored.bind("g1", uploaded["document_id"]))
        finally:
            restored.close()


def test_failed_parse_retry_queue_bound_and_delete_during_parse():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "db.sqlite"
        repository = SQLiteDocumentRepository(database)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def parser(original, kind):
            calls.append(original)
            if original == b"retry" and calls.count(original) == 1:
                raise ParseError("parse_timeout")
            if original == b"hold":
                entered.set()
                assert release.wait(10)
            return "检索原文"

        imports = DocumentImports(repository, parser, planning(database))
        try:
            retry = imports.upload("retry.txt", b"retry")["document_id"]
            assert wait_status(imports.get, retry, "failed")["reason"] == "parse_timeout"
            imports.reparse(retry)
            assert wait_status(imports.get, retry, "ready")["revision"] == 1
            held = [imports.upload("hold.txt", b"hold")["document_id"] for _ in range(4)]
            assert entered.wait(5)
            expect_error("document_capacity_exceeded", lambda: imports.upload("extra.txt", b"extra"))
            expect_error("document_not_ready", lambda: imports.bind("g1", held[0]))
            imports.delete(held[0])
            release.set()
            for identifier in held[1:]:
                wait_status(imports.get, identifier, "ready")
        finally:
            release.set()
            imports.close()
        expect_error("document_not_found", lambda: imports.get(held[0]))
        assert repository.document_chunks(held[0]) == ()
        expect_error("shutting_down", lambda: imports.upload("closed.txt", b"a"))


def test_http_input_scope_binding_unbinding_and_search_bounds():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "db.sqlite"
        repository = SQLiteDocumentRepository(database)
        imports = DocumentImports(repository, extract, planning(database))
        app = create_app(build_fixture_loop(), document_imports=imports)
        with TestClient(app, base_url="http://localhost") as client:
            assert client.post("/api/documents", files={"file": ("big.txt", b"x" * (MAX_UPLOAD_BYTES + 1))}).status_code == 413
            assert client.post("/api/documents", json={"path": "file.txt"}).status_code == 422
            uploaded = client.post("/api/documents", files={"file": ("资料.md", "中文检索与引用。".encode())}).json()
            identifier = uploaded["document_id"]
            wait_status(imports.get, identifier, "ready")
            binding = {"document_id": identifier, "node_id": "n1"}
            assert client.post("/api/goals/g1/document-bindings", json=binding).json()["error"]["code"] == "goal_binding_required"
            assert client.post("/api/goals/missing/document-bindings", json={"document_id": identifier}).status_code == 404
            assert client.post("/api/goals/g1/document-bindings", json={**binding, "node_id": "missing"}).status_code == 404
            assert client.post("/api/goals/g1/document-bindings", json={"document_id": identifier}).status_code == 200
            assert client.post("/api/goals/g1/document-bindings", json=binding).status_code == 200
            for query in ("检索", '检索" OR * NEAR(foo) --'):
                assert client.post("/api/goals/g1/document-search", json={"query": query, "node_id": "n1"}).status_code == 200
            assert client.post("/api/goals/g1/document-search", json={"query": "检索", "limit": 6}).status_code == 422
            assert client.post("/api/goals/g1/document-search", json={"query": " "}).status_code == 422
            assert client.request("DELETE", "/api/goals/g1/document-bindings", json={"document_id": identifier}).json()["document_ids"] == []
            expect_error("no_documents_bound", lambda: imports.search("g1", "检索", node_id="n1"))


def test_jieba_bm25_top_five_old_index_rebuild_and_offsets():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "db.sqlite"
        repository = SQLiteDocumentRepository(database)
        docs = DocumentService(repository)
        for index in range(7):
            text = "\n--- page 2 ---\n检索 alpha beta   \n" if index == 0 else "alpha " + "noise " * (index * 10)
            docs.upload_text(str(index), "doc", text)
            docs.bind_goal("g1", str(index))
        hits = docs.search("g1", "alpha")
        assert len(hits) == 5 and all(hit.score > 0 for hit in hits)
        assert hits[0].chunk.document_id == "0"
        assert len("".join(hit.chunk.text for hit in hits)) <= 1600
        assert "检索" in tokenize("中文检索与引用")
        chunk = repository.document_chunks("0")[0]
        assert chunk.page_number == 2
        with closing(sqlite3.connect(database)) as connection, connection:
            text = connection.execute("select text from documents where document_id = '0'").fetchone()[0]
            assert text[chunk.start_offset:chunk.end_offset] == chunk.text
            connection.execute("delete from document_chunks_fts")
            connection.execute("delete from document_index_metadata")
        reopened = SQLiteDocumentRepository(database)
        assert DocumentService(reopened).search("g1", "检索")
        with closing(sqlite3.connect(database)) as connection, connection:
            stored = connection.execute("select text_hash from document_chunks where chunk_id = ?", (chunk.id,)).fetchone()[0]
            assert stored == hashlib.sha256(chunk.text.encode()).hexdigest()
        old_database = Path(directory) / "old.sqlite"
        with closing(sqlite3.connect(old_database)) as connection, connection:
            connection.execute("""create table document_chunks (
                chunk_id text primary key, document_id text, document_version integer, chunk_index integer,
                text text, start_offset integer, end_offset integer, page_number integer)""")
            connection.execute("insert into document_chunks values ('old:c1', 'old', 1, 0, '旧检索', 0, 3, null)")
        upgraded = SQLiteDocumentRepository(old_database)
        assert upgraded.document_chunks("old")[0].heading is None
        assert upgraded.search_chunks({"old"}, {"检索"}, 5)


def test_ready_commit_rollback_and_binding_delete_serialization():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "db.sqlite"
        repository = SQLiteDocumentRepository(database)
        record = UploadRecord("atomic", "atomic.txt", DocumentKind.TEXT, "parsing", 3, "hash")
        repository.create_upload(record, b"abc")
        document = parse_text_document("atomic", "atomic.txt", "原子检索")
        save = repository._save_document

        def fail_after_save(connection, document, chunks):
            save(connection, document, chunks)
            raise RuntimeError("storage failure")

        with patch.object(repository, "_save_document", side_effect=fail_after_save):
            try:
                repository.finish_upload("atomic", "ready", None, document, chunk_document(document))
            except RuntimeError:
                pass
            else:
                raise AssertionError("expected storage failure")
        assert repository.get_upload("atomic").status == "parsing"
        assert repository.document_chunks("atomic") == ()
        assert repository.search_chunks({"atomic"}, {"检索"}, 5) == ()
        repository.finish_upload("atomic", "ready", None, document, chunk_document(document))
        repository.bind_to_goal("g1", "atomic")
        assert repository.search_chunks({"atomic"}, {"检索"}, 5)
        # Even an existing index is unavailable when upload metadata is not ready.
        assert repository.transition_upload("atomic", ("ready",), "failed")
        assert repository.search_chunks({"atomic"}, {"检索"}, 5) == ()
        expect_error("document_not_ready", lambda: repository.bind_to_node("g1", "n1", "atomic"))
        assert repository.transition_upload("atomic", ("failed",), "ready")
        checked, release, deleting = threading.Event(), threading.Event(), threading.Event()
        require = repository._require_document

        def pause_binding(connection, identifier):
            require(connection, identifier)
            checked.set()
            assert release.wait(5)

        def delete():
            deleting.set()
            repository.delete_document("atomic")

        with ThreadPoolExecutor(max_workers=2) as workers, patch.object(repository, "_require_document", side_effect=pause_binding):
            binding = workers.submit(repository.bind_to_node, "g1", "n1", "atomic")
            try:
                assert checked.wait(5)
                deletion = workers.submit(delete)
                assert deleting.wait(5)
            finally:
                release.set()
            binding.result(timeout=5)
            deletion.result(timeout=5)
        assert repository.bound_document_ids("g1") == set()
        assert repository.bound_document_ids("g1", "n1") == set()
        expect_error("document_not_found", lambda: repository.bind_to_goal("g1", "atomic"))
