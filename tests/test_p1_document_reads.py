"""Persistent product reads; no provider or private document content in listings."""

from pathlib import Path
import tempfile
from contextlib import closing

from fastapi.testclient import TestClient

from learngraph_lite.bootstrap import create_business_fixture_app
from learngraph_lite.infrastructure.persistence import SQLiteDocumentRepository
from learngraph_lite.application.document_imports import UploadRecord
from learngraph_lite.domain.documents import DocumentKind


def test_document_listing_pagination_bindings_and_reopen():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "reads.sqlite3"
        app = create_business_fixture_app(database=database)
        with TestClient(app, base_url="http://localhost") as client:
            created = client.post("/api/goals", json={"title": "资料学习"}).json()
            goal = created["goal_id"]
            confirmed = client.post(f"/api/goals/{goal}/confirm", json={"expected_version": created["version"]}).json()
            draft = client.patch(f"/api/goals/{goal}/graph", json={"expected_version": confirmed["version"],
                "nodes": [{"id": "n", "title": "资料检索", "estimated_minutes": 10, "priority": 3,
                           "explanation": "读取原文", "learning_outcome": "核查引用"}], "edges": []})
            assert draft.status_code == 200, draft.text
            repository = SQLiteDocumentRepository(database)
            for index in range(3):
                record = UploadRecord(f"d{index}", f"example{index}.txt", DocumentKind.TEXT,
                                      "failed", 6, "digest", reason="interrupted")
                repository.create_upload(record, b"secret")
            page = client.get("/api/documents?limit=2").json()
            assert page["total"] == 3 and page["offset"] == 0
            assert [item["document_id"] for item in page["documents"]] == ["d2", "d1"]
            assert "secret" not in str(page) and "original" not in str(page)
            assert client.get("/api/documents?offset=2&limit=2").json()["documents"][0]["document_id"] == "d0"
            assert client.get("/api/documents?limit=51").status_code == 422
            assert client.get("/api/documents?offset=-1").status_code == 422
            assert client.get("/api/documents/unknown/bindings").status_code == 404
            assert client.get(f"/api/goals/{goal}/document-bindings?node_id=unknown").status_code == 404
            assert client.get(f"/api/goals/{goal}/document-bindings").json() == {"document_ids": []}
            # Read routes cannot leak binding original bytes or enqueue parse/model work.
            with closing(repository._connect()) as connection, connection:
                connection.execute("insert into goal_document_bindings values (?, ?)", (goal, "d1"))
                connection.execute("insert into node_document_bindings values (?, ?, ?)", (goal, "n", "d1"))
            assert client.get("/api/documents/d1/bindings").json() == {
                "bindings": [{"goal_id": goal, "node_id": None}, {"goal_id": goal, "node_id": "n"}]}
            assert client.get(f"/api/goals/{goal}/document-bindings?node_id=n").json() == {"document_ids": ["d1"]}
        with TestClient(create_business_fixture_app(database=database), base_url="http://localhost") as reopened:
            assert reopened.get("/api/documents").json()["total"] == 3
            assert reopened.get(f"/api/goals/{goal}/document-bindings?node_id=n").json() == {"document_ids": ["d1"]}
