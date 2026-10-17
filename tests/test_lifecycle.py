from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import time
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import AgentRunner, ModelResponse, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, DirectResult, RunAdmissionError, RunRecord, RunRequest
from learngraph_lite.application.conversations import ConversationService
from learngraph_lite.application.document_imports import UploadRecord
from learngraph_lite.application.documents import DocumentService
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.lifecycle import DeletedScope
from learngraph_lite.application.planning import PlanningError, PlanningService
from learngraph_lite.bootstrap import _create_business_app, build_learning_loop, create_real_app
from learngraph_lite.domain.documents import DocumentKind
from learngraph_lite.domain.learning import GraphNode
from learngraph_lite.infrastructure import SQLiteDocumentRepository, SQLiteLearningRepository, SQLiteLessonRepository, SQLitePlanningRepository
from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel
from learngraph_lite.infrastructure.conversation_persistence import SQLiteConversationRepository
from learngraph_lite.infrastructure.lifecycle_persistence import SQLiteLifecycleRepository
from learngraph_lite.infrastructure.proposal_persistence import SQLiteProposalRepository
from learngraph_lite.infrastructure.run_persistence import SQLiteRunRepository
from learngraph_lite.presentation.http import create_app


class OfflineModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if tools or len(messages) < 2 or messages[0].role != "system":
            return ModelResponse("offline chat")
        return BusinessFixtureModel().complete(messages, tools)

    def close(self):
        pass


class BlockingModel(OfflineModel):
    def __init__(self):
        super().__init__()
        self.started, self.release = Event(), Event()

    def complete(self, messages, tools):
        self.started.set()
        assert self.release.wait(5), "test did not release the offline worker"
        return super().complete(messages, tools)


def seed(database):
    planning = PlanningService(SQLitePlanningRepository(database))
    learning = LearningService(SQLiteLearningRepository(database))
    for goal_id in ("g", "other"):
        planning.create_goal(goal_id, goal_id)
        planning.confirm_goal(goal_id)
        planning.save_graph_draft(goal_id, (GraphNode("n", "节点", 20),), ())
        learning.start_goal(planning.publish_graph(goal_id, 0))
    planning.create_goal("draft", "未完成草稿")
    return planning


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


def conversation(client, goal_id=None):
    body = {"session_id": str(uuid4())}
    if goal_id:
        body.update(goal_id=goal_id, node_id="n")
    response = client.post("/api/conversations", json=body)
    assert response.status_code == 201, response.text
    return body["session_id"]


def done(client, response, expected="completed"):
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        record = client.get(f"/api/runs/{run_id}").json()
        if record["status"] not in {"queued", "running"}:
            assert record["status"] == expected, record
            return record
        time.sleep(0.005)
    raise AssertionError("offline worker did not finish")


def chat(client, session_id, goal_id=None):
    body = {"request_id": str(uuid4()), "user_text": "private conversation text"}
    if goal_id:
        body.update(goal_id=goal_id, node_id="n", mode="teaching")
    return done(client, client.post(f"/api/sessions/{session_id}/runs", json=body))


def delete_when_exited(client, path, body=None):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.request("DELETE", path, json=body)
        if response.status_code != 409 or response.json()["error"]["code"] != "session_busy":
            return response
        time.sleep(0.005)
    raise AssertionError("offline worker did not exit")


def contents(database):
    with closing(sqlite3.connect(database)) as connection:
        tables = [row[0] for row in connection.execute("select name from sqlite_master where type='table'")]
        return {table: sorted(connection.execute(f'select * from "{table}"').fetchall(), key=repr) for table in tables}


def node_assets(client, parent):
    exercise = done(client, client.post("/api/goals/g/nodes/n/exercises", json={
        "session_id": str(uuid4()), "parent_session_id": parent, "request_id": "exercise",
    }))
    exercise_id = exercise["output"]["exercises"][0]["id"]
    response = client.post(f"/api/goals/g/exercises/{exercise_id}/attempts", json={
        "submission_id": "answer", "selected_option_id": "b",
    })
    assert response.status_code == 200, response.text
    lesson = done(client, client.post("/api/goals/g/nodes/n/lessons", json={
        "session_id": str(uuid4()), "parent_session_id": parent, "request_id": "lesson",
        "exercise_ids": [exercise_id],
    }))
    package = lesson["output"]["lesson"]
    response = client.post(f"/api/goals/g/lessons/{package['id']}/events", json={
        "event_id": "event", "package_version": package["version"], "component_id": "steps",
        "action": "step_changed", "payload": {"step": 1},
    })
    assert response.status_code == 200, response.text
    explanation = done(client, client.post(f"/api/sessions/{uuid4()}/runs", json={
        "request_id": "explanation", "mode": "explanation", "goal_id": "g", "node_id": "n",
        "source_event_id": "event", "explanation_slot": "initial", "parent_session_id": parent,
    }))
    return exercise, lesson, explanation


def add_sources(database):
    documents = SQLiteDocumentRepository(database)
    raw = b"source material remains searchable"
    documents.create_upload(UploadRecord("doc", "source.txt", DocumentKind.TEXT, "ready", len(raw), "hash"), raw)
    DocumentService(documents).upload_text("doc", "source.txt", raw.decode())
    for goal_id in ("g", "other"):
        documents.bind_to_goal(goal_id, "doc")
        documents.bind_to_node(goal_id, "n", "doc")
    return documents


def test_conversation_delete_hard_removes_runs_children_caches_but_retains_shared_node_assets():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        seed(database)
        model = OfflineModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            a, b = conversation(client, "g"), conversation(client, "g")
            first, kept = chat(client, a, "g"), chat(client, b, "g")
            generated = node_assets(client, a)
            # An old UUID with no parent marker is deliberately not guessed/adopted.
            unowned = done(client, client.post("/api/goals/g/nodes/n/lessons", json={
                "session_id": str(uuid4()), "request_id": "unowned",
            }))
            documents = add_sources(database)
            before = contents(database)
            calls = model.calls
            response = delete_when_exited(client, f"/api/conversations/{a}", {})
            assert response.json() == {"deleted": True, "session_id": a}, response.text
            assert client.delete(f"/api/conversations/{a}").json() == response.json()
            error(client.get(f"/api/conversations/{a}"), 404, "conversation_not_found")
            assert client.get(f"/api/sessions/{a}/runs").json() == []
            for record in (first, *generated):
                error(client.get(f"/api/runs/{record['run_id']}"), 404, "run_not_found")
                assert client.get(f"/api/sessions/{record['session_id']}/runs").json() == []
                error(client.get(f"/api/runs/{record['run_id']}/events"), 404, "run_not_found")
            assert client.get(f"/api/runs/{kept['run_id']}").status_code == 200
            assert client.get(f"/api/runs/{unowned['run_id']}").status_code == 200
            assert {item["session_id"] for item in client.get("/api/conversations").json()} == {
                "planning:g", "planning:other", "planning:draft", b,
            }
            after = contents(database)
            for table in ("planning_states", "learning_exercises", "learning_attempts", "lesson_packages", "lesson_events",
                          "documents", "document_uploads", "document_chunks", "document_chunks_fts",
                          "goal_document_bindings", "node_document_bindings"):
                assert before[table] == after[table], table
            assert after["lesson_run_tasks"] == []
            assert after["learning_generation_operations"] == []
            assert len(after["lesson_generation_operations"]) == 1  # only the unowned request remains
            assert documents.original_bytes("doc") == b"source material remains searchable"
            assert model.calls == calls  # deletion never invokes a gateway
            error(client.post("/api/conversations", json={"session_id": a, "goal_id": "g", "node_id": "n"}),
                  409, "scope_deleted")
            error(client.post(f"/api/sessions/{a}/runs", json={"request_id": "late", "user_text": "late"}),
                  409, "scope_deleted")
            error(client.post(f"/api/sessions/{generated[2]['session_id']}/runs", json={
                "request_id": "late-retry", "user_text": "late", "retry_of_run_id": generated[2]["run_id"],
            }), 409, "scope_deleted")
        with TestClient(_create_business_app(OfflineModel(), "fixture", database), base_url="http://localhost") as client:
            assert client.get(f"/api/sessions/{a}/runs").json() == []
            error(client.post(f"/api/sessions/{a}/runs", json={"request_id": "after-restart", "user_text": "late"}),
                  409, "scope_deleted")
            assert client.delete(f"/api/conversations/{a}").status_code == 200


def test_goal_delete_cleans_every_exclusive_table_preserves_other_goal_general_and_original_sources():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        seed(database)
        with TestClient(_create_business_app(OfflineModel(), "fixture", database), base_url="http://localhost") as client:
            a, other, general = conversation(client, "g"), conversation(client, "other"), conversation(client)
            chat(client, a, "g")
            kept = (chat(client, other, "other"), chat(client, general))
            generated = node_assets(client, a)
            unowned = done(client, client.post("/api/goals/g/nodes/n/lessons", json={
                "session_id": str(uuid4()), "request_id": "unowned",
            }))
            proposal = client.post("/api/goals/g/graph-proposals", json={
                "request_id": "proposal", "base_revision": 1, "rationale": "adjust metadata",
                "operations": [{"kind": "update_node", "node_id": "n", "title": "new title"}],
            })
            assert proposal.status_code == 201, proposal.text
            documents = add_sources(database)
            version = client.get("/api/goals/g").json()["version"]
            error(client.delete("/api/conversations/planning:g"), 409, "planning_conversation")
            before = contents(database)
            error(client.request("DELETE", "/api/goals/g", json={"expected_version": version - 1}), 409, "version_conflict")
            assert contents(database) == before
            response = delete_when_exited(client, "/api/goals/g", {"expected_version": version})
            assert response.json() == {"deleted": True, "goal_id": "g"}, response.text
            assert client.request("DELETE", "/api/goals/g", json={"expected_version": 0}).json() == response.json()
            error(client.get("/api/goals/g"), 404, "goal_not_found")
            assert client.get("/api/goals/other").status_code == 200
            assert client.get("/api/goals/draft").status_code == 200
            for record in (*generated, unowned):
                error(client.get(f"/api/runs/{record['run_id']}"), 404, "run_not_found")
            for record in kept:
                assert client.get(f"/api/runs/{record['run_id']}").status_code == 200
            assert {item["session_id"] for item in client.get("/api/conversations").json()} == {
                "planning:other", "planning:draft", other, general,
            }
            after = contents(database)
            for table, rows in after.items():
                if table in {"deleted_sessions", "deleted_goals"}:
                    assert all(len(row) == 1 for row in rows)  # IDs only, no hidden retained transcript
            with closing(sqlite3.connect(database)) as connection:
                for (table,) in connection.execute("select name from sqlite_master where type='table'"):
                    columns = {row[1] for row in connection.execute(f'pragma table_info("{table}")')}
                    if "goal_id" in columns and table != "deleted_goals":
                        assert connection.execute(f'select count(*) from "{table}" where goal_id=?', ("g",)).fetchone()[0] == 0, table
            for table in ("document_uploads", "documents", "document_chunks", "document_chunks_fts"):
                assert before[table] == after[table], table
            assert documents.original_bytes("doc") == b"source material remains searchable"
            assert documents.search_chunks({"doc"}, {"source"}, 5)
            assert documents.bound_document_ids("other", "n") == {"doc"}
            assert documents.bound_document_ids("g") == set()
            error(client.post(f"/api/sessions/{uuid4()}/runs", json={
                "request_id": "late", "user_text": "late", "goal_id": "g", "node_id": "n",
            }), 409, "scope_deleted")
        # Same lifecycle is installed by the official real factory; replace only
        # its gateway, never load credentials or touch a daily database/provider.
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=OfflineModel()):
            with TestClient(create_real_app(database=database), base_url="http://localhost") as client:
                assert client.get("/api/model/status").json()["mode"] == "real"
                assert client.request("DELETE", "/api/goals/g", json={"expected_version": 0}).status_code == 200
                assert client.get("/api/goals/other").status_code == 200
                assert client.request("DELETE", "/api/goals/draft", json={"expected_version": 0}).status_code == 200


def test_draft_empty_conversation_tombstones_idempotency_unknown_ids_and_strict_versions():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        model = OfflineModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            goal = str(uuid4())
            body = {"goal_id": goal, "title": "private draft"}
            assert client.post("/api/workbench/goals", json=body).status_code == 201
            empty = conversation(client)
            error(client.delete("/api/conversations/missing"), 404, "conversation_not_found")
            error(client.request("DELETE", "/api/goals/missing", json={"expected_version": 0}), 404, "goal_not_found")
            for invalid in ({}, {"expected_version": "0"}, {"expected_version": True}, {"expected_version": -1},
                            {"expected_version": 0, "extra": 1}):
                error(client.request("DELETE", f"/api/goals/{goal}", json=invalid), 422, "invalid_request")
            assert client.delete(f"/api/goals/{goal}").status_code == 422
            assert client.request("DELETE", f"/api/goals/{goal}", json={"expected_version": 0}).status_code == 200
            assert client.delete(f"/api/conversations/{empty}").status_code == 200
            error(client.post("/api/workbench/goals", json=body), 409, "goal_deleted")
            error(client.post("/api/conversations", json={"session_id": empty}), 409, "scope_deleted")
            assert model.calls == 0
            assert client.get("/api/conversations").json() == []
        # Durable guards cover a new service instance, legacy goal creation and
        # stale aggregate snapshots, not just the original in-memory directory.
        planning = SQLitePlanningRepository(database)
        error_service = PlanningService(planning)
        try:
            error_service.create_goal(goal, "late replay")
        except PlanningError as exc:
            assert exc.code == "goal_deleted"
        else:
            raise AssertionError("deleted goal was recreated")
        with TestClient(_create_business_app(OfflineModel(), "fixture", database), base_url="http://localhost") as client:
            error(client.post("/api/workbench/goals", json=body), 409, "goal_deleted")
            error(client.post("/api/conversations", json={"session_id": empty}), 409, "scope_deleted")


def test_active_and_cancelled_but_unexited_child_workers_block_conversation_and_goal_deletion():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        planning = seed(database)
        model = BlockingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            parent, unrelated = conversation(client, "g"), conversation(client)
            response = client.post("/api/goals/g/nodes/n/lessons", json={
                "session_id": str(uuid4()), "parent_session_id": parent, "request_id": "blocking",
            })
            assert response.status_code == 202, response.text
            run_id = response.json()["run_id"]
            try:
                assert model.started.wait(2)
                for _ in range(2):
                    error(client.delete(f"/api/conversations/{parent}"), 409, "session_busy")
                    error(client.request("DELETE", "/api/goals/g", json={"expected_version": planning.describe("g")["version"]}),
                          409, "session_busy")
                    assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
                assert client.delete(f"/api/conversations/{unrelated}").status_code == 200
                assert client.get("/api/goals/g").status_code == 200
            finally:
                model.release.set()
            assert delete_when_exited(client, f"/api/conversations/{parent}").status_code == 200
            error(client.get(f"/api/runs/{run_id}"), 404, "run_not_found")
            assert client.get("/api/goals/g/nodes/n/lessons").json()["lessons"] == []


def test_goal_transaction_failure_rolls_back_sqlite_and_does_not_purge_loop_or_directory():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        seed(database)
        with TestClient(_create_business_app(OfflineModel(), "fixture", database), base_url="http://localhost",
                        raise_server_exceptions=False) as client:
            parent = conversation(client, "g")
            record = chat(client, parent, "g")
            node_assets(client, parent)
            add_sources(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("""create trigger fail_delete before delete on planning_states
                    begin select raise(abort, 'injected deletion failure'); end""")
            before = contents(database)
            version = client.get("/api/goals/g").json()["version"]
            response = delete_when_exited(client, "/api/goals/g", {"expected_version": version})
            assert response.status_code == 500, response.text
            assert contents(database) == before
            assert client.get(f"/api/runs/{record['run_id']}").json()["final_text"] == record["final_text"]
            assert client.get(f"/api/conversations/{parent}").status_code == 200
            assert client.get("/api/goals/g").status_code == 200
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("drop trigger fail_delete")
            assert client.request("DELETE", "/api/goals/g", json={"expected_version": version}).status_code == 200


def test_parent_scope_is_immutable_cannot_adopt_another_conversation_and_survives_restart():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        seed(database)
        with TestClient(_create_business_app(OfflineModel(), "fixture", database), base_url="http://localhost") as client:
            a, b, other = conversation(client, "g"), conversation(client, "g"), conversation(client, "other")
            child = str(uuid4())
            body = {"session_id": child, "parent_session_id": a, "request_id": "first"}
            first = done(client, client.post("/api/goals/g/nodes/n/lessons", json=body))
            assert client.post("/api/goals/g/nodes/n/lessons", json=body).json()["run_id"] == first["run_id"]
            error(client.post("/api/goals/g/nodes/n/lessons", json={**body, "parent_session_id": b}),
                  409, "session_scope_conflict")
            error(client.post("/api/goals/g/nodes/n/lessons", json={**body, "parent_session_id": other}),
                  409, "conversation_scope_conflict")
            error(client.post("/api/goals/g/nodes/n/lessons", json={**body, "session_id": b}),
                  409, "conversation_scope_conflict")
            error(client.post("/api/goals/g/nodes/n/lessons", json={**body, "parent_session_id": "missing"}),
                  404, "conversation_not_found")
            assert client.delete(f"/api/conversations/{b}").status_code == 200
            assert client.get(f"/api/runs/{first['run_id']}").status_code == 200
        with TestClient(_create_business_app(OfflineModel(), "fixture", database), base_url="http://localhost") as client:
            error(client.post("/api/goals/g/nodes/n/lessons", json={**body, "parent_session_id": other}),
                  409, "conversation_scope_conflict")
            error(client.post("/api/goals/g/nodes/n/lessons", json={**body, "parent_session_id": None}),
                  409, "session_scope_conflict")
            assert client.delete(f"/api/conversations/{a}").status_code == 200
            error(client.get(f"/api/runs/{first['run_id']}"), 404, "run_not_found")
            # Even a never-before-seen child command cannot revive a deleted parent.
            error(client.post("/api/goals/g/nodes/n/lessons", json={**body, "session_id": str(uuid4())}),
                  404, "conversation_not_found")


def test_in_memory_loop_queued_cancelled_worker_cache_cleanup_and_late_retry():
    model = BlockingModel()
    loop = AgentLoop(AgentRunner(model, ToolRegistry()))
    loop._executor = ThreadPoolExecutor(max_workers=1)  # deterministically leave attempt B queued
    committed = []
    try:
        first = loop.submit(RunRequest("a", "first", "a"))
        assert model.started.wait(2)
        queued_request = RunRequest("b", "queued", "b")
        queued = loop.submit(queued_request)
        assert queued.status == "queued"
        for cancel in (False, True):
            if cancel:
                assert loop.cancel(queued.run_id).status == "cancelled"
            try:
                loop.delete_scope(lambda: committed.append(True), session_id="b")
            except RunAdmissionError as exc:
                assert exc.code == "session_busy"
            else:
                raise AssertionError("queued/live worker did not block deletion")
        assert committed == []
        model.release.set()
        with loop._condition:
            assert loop._condition.wait_for(lambda: not loop._active, timeout=3)
        loop.delete_scope(lambda: DeletedScope(), session_id="b")
        assert loop.list_runs("b") == ()
        assert queued.run_id not in loop._events_by_run
        assert "b" not in loop._session_scopes
        assert ("b", "b") not in loop._records_by_key
        assert loop.get_run(first.run_id).status == "completed"
        for request in (queued_request, replace(queued_request, idempotency_key="retry", retry_of_run_id=queued.run_id)):
            try:
                loop.submit(request)
            except RunAdmissionError as exc:
                assert exc.code == "scope_deleted"
            else:
                raise AssertionError("late request resurrected an in-memory session")
    finally:
        model.release.set()
        loop.close()


def test_failed_retry_history_and_legacy_result_caches_are_removed_without_reviving_after_restart():
    class FailOnce(OfflineModel):
        def complete(self, messages, tools):
            if self.calls == 0:
                self.calls += 1
                raise RuntimeError("private failure text")
            return super().complete(messages, tools)

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        seed(database)
        model = FailOnce()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            session = conversation(client, "g")
            body = {"request_id": "first", "user_text": "private input", "goal_id": "g", "node_id": "n", "mode": "teaching"}
            failed = done(client, client.post(f"/api/sessions/{session}/runs", json=body), "failed")
            retried = done(client, client.post(f"/api/sessions/{session}/runs", json={
                **body, "request_id": "retry", "retry_of_run_id": failed["run_id"],
            }))
            assert retried["root_task_id"] == failed["run_id"]
            learning = SQLiteLearningRepository(database)
            state = learning.get("g")
            state.run_ids_by_key["legacy-request"] = retried["run_id"]
            state.final_text_by_key["legacy-request"] = "private cached body"
            state.generation_operations[json.dumps([failed["run_id"], "exercise", "n", 1, "practice"])] = {
                "fingerprint": "private request purpose", "ids": [],
            }
            learning.save("g", state)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("insert into lesson_explanations values (?, ?, ?, ?, ?)",
                                   ("g", "old-event", "slot", retried["run_id"], 0))
            assert delete_when_exited(client, f"/api/conversations/{session}").status_code == 200
            current = learning.get("g")
            assert current.run_ids_by_key == current.final_text_by_key == current.generation_operations == {}
            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute("select * from lesson_explanations").fetchall() == []
            assert client.get(f"/api/sessions/{session}/runs").json() == []
        model = OfflineModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            error(client.post(f"/api/sessions/{session}/runs", json={
                **body, "request_id": "late-retry", "retry_of_run_id": failed["run_id"],
            }), 409, "scope_deleted")
            error(client.post(f"/api/sessions/{uuid4()}/runs", json={
                **body, "request_id": "late-retry", "retry_of_run_id": failed["run_id"],
            }), 409, "invalid_retry")
            assert model.calls == 0


def test_tombstones_reject_stale_planning_learning_lesson_and_binding_writes_in_sqlite():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        seed(database)
        with TestClient(_create_business_app(OfflineModel(), "fixture", database), base_url="http://localhost") as client:
            parent = conversation(client, "g")
            node_assets(client, parent)
            documents = add_sources(database)
            planning, learning, lessons = SQLitePlanningRepository(database), SQLiteLearningRepository(database), SQLiteLessonRepository(database)
            stale = planning.get("g"), learning.get("g"), lessons.state("g")
            version = client.get("/api/goals/g").json()["version"]
            assert delete_when_exited(client, "/api/goals/g", {"expected_version": version}).status_code == 200
            before = contents(database)
            for write in (
                lambda: planning.save("g", stale[0]), lambda: planning.create("g", stale[0]),
                lambda: learning.save("g", stale[1]), lambda: lessons.save("g", stale[2]),
                lambda: lessons.mutate("g", lambda state: state.packages.update(stale[2].packages)),
                lambda: documents.bind_to_goal("g", "doc"), lambda: documents.bind_to_node("g", "n", "doc"),
                lambda: SQLiteConversationRepository(database).create_goal("g", "late", stale[0], datetime.now(UTC)),
            ):
                try:
                    write()
                except PlanningError as exc:
                    assert exc.code == "goal_deleted"
                else:
                    raise AssertionError("stale write recreated deleted goal data")
                assert contents(database) == before


def test_restart_interrupted_planning_run_is_deletable_and_never_recovered_again():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "lifecycle.sqlite3"
        seed(database)
        repository = SQLiteRunRepository(database)
        request = RunRequest("planning:draft", "private planning input", "first", mode="planning",
                             goal_id="draft", task_ref="goal:draft")
        run_id = str(uuid4())
        repository.admit(request, RunRecord(run_id, request.session_id, "queued", goal_id="draft",
                                           mode="planning", root_task_id=run_id))
        for attempt in range(2):
            model = OfflineModel()
            with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
                if attempt == 0:
                    assert client.get(f"/api/runs/{run_id}").json()["status"] == "interrupted"
                    assert client.request("DELETE", "/api/goals/draft", json={"expected_version": 0}).status_code == 200
                error(client.get(f"/api/runs/{run_id}"), 404, "run_not_found")
                assert client.get("/api/sessions/planning:draft/runs").json() == []
                assert "planning:draft" not in {item["session_id"] for item in client.get("/api/conversations").json()}
                assert model.calls == 0


def test_in_memory_deletion_serializes_admission_and_failed_commit_leaves_records_intact():
    model = OfflineModel()
    loop = AgentLoop(AgentRunner(model, ToolRegistry()))
    request = RunRequest("a", "original", "first")
    first = loop.run(request)
    entered, release = Event(), Event()

    def failed_commit():
        raise RuntimeError("transaction rolled back")

    def commit():
        entered.set()
        assert release.wait(3)
        return DeletedScope()

    try:
        try:
            loop.delete_scope(failed_commit, session_id="a")
        except RuntimeError:
            pass
        assert loop.get_run(first.run_id).final_text == first.final_text
        assert loop.run(request).run_id == first.run_id
        with ThreadPoolExecutor(max_workers=2) as executor:
            deletion = executor.submit(lambda: loop.delete_scope(commit, session_id="a"))
            assert entered.wait(2)
            admission = executor.submit(lambda: loop.submit(RunRequest("a", "late", "late")))
            assert not admission.done()
            release.set()
            deletion.result()
            try:
                admission.result()
            except RunAdmissionError as exc:
                assert exc.code == "scope_deleted"
            else:
                raise AssertionError("racing admission escaped deletion")
        assert model.calls == 1
        assert loop.list_all_runs() == ()
    finally:
        release.set()
        loop.close()


def test_sse_subscription_closes_cleanly_if_completed_run_is_deleted_before_its_next_snapshot():
    model = BlockingModel()
    loop = AgentLoop(AgentRunner(model, ToolRegistry()))
    record = loop.submit(RunRequest("sse", "private input", "first"))
    assert model.started.wait(2)

    def delete_between_sse_reads(run_id, after_seq, timeout):
        model.release.set()
        with loop._condition:
            assert loop._condition.wait_for(lambda: not loop._active, timeout=3)
        loop.delete_scope(lambda: DeletedScope(), session_id="sse")
        return ()

    try:
        with patch.object(loop, "wait_events", side_effect=delete_between_sse_reads):
            with TestClient(create_app(loop), base_url="http://localhost") as client:
                response = client.get(f"/api/runs/{record.run_id}/events")
                assert response.status_code == 200
                assert "run.snapshot" in response.text
                error(client.get(f"/api/runs/{record.run_id}"), 404, "run_not_found")
    finally:
        model.release.set()
        loop.close()


def test_sdk_admission_checks_durable_parent_and_independent_conversation_scope_before_execution():
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "sdk-scope.sqlite3"
        planning = seed(database)
        SQLiteDocumentRepository(database)
        SQLiteLessonRepository(database)
        SQLiteProposalRepository(database)
        loop = AgentLoop(AgentRunner(OfflineModel(), ToolRegistry()), repository=SQLiteRunRepository(database),
                         direct_handlers={mode: lambda *_: DirectResult("offline child") for mode in ("lesson", "teaching")})
        directory = ConversationService(SQLiteConversationRepository(database), planning, loop, SQLiteLifecycleRepository(database))
        a = directory.create(str(uuid4()), "g", "n")
        b = directory.create(str(uuid4()), "other", "n")
        general = directory.create(str(uuid4()))
        invalid = (
            RunRequest(b.session_id, "cross-parent", "one", mode="lesson", goal_id="other", node_id="n", parent_session_id=a.session_id),
            RunRequest(b.session_id, "adopt metadata", "two", mode="lesson", goal_id="g", node_id="n", parent_session_id=a.session_id),
            RunRequest(str(uuid4()), "cross goal", "three", mode="lesson", goal_id="other", node_id="n", parent_session_id=a.session_id),
            RunRequest(str(uuid4()), "missing parent", "four", mode="lesson", goal_id="g", node_id="n", parent_session_id=str(uuid4())),
            RunRequest(str(uuid4()), "general parent", "five", mode="lesson", goal_id="g", node_id="n", parent_session_id=general.session_id),
            RunRequest(str(uuid4()), "wrong child mode", "six", mode="teaching", goal_id="g", node_id="n", parent_session_id=a.session_id),
            RunRequest(b.session_id, "metadata scope", "seven", mode="teaching", goal_id="g", node_id="n"),
            RunRequest(general.session_id, "general scope", "eight", mode="teaching", goal_id="g", node_id="n"),
        )
        try:
            for execute in (loop.run, loop.submit):
                for request in invalid:
                    try:
                        execute(request)
                    except RunAdmissionError as exc:
                        assert exc.code == "conversation_scope_conflict", exc.code
                    else:
                        raise AssertionError("SDK bypassed durable conversation/parent admission")
            assert loop.list_all_runs() == ()
            child = loop.run(RunRequest(str(uuid4()), "valid child", "valid", mode="lesson", goal_id="g", node_id="n", parent_session_id=a.session_id))
            assert child.status == "completed"
            directory.delete(a.session_id)
            assert directory.get(b.session_id) == b
            assert directory.get(general.session_id) == general
            assert loop.list_runs(child.session_id) == ()
        finally:
            loop.close()


def test_sdk_late_result_projection_and_stale_aggregate_cannot_restore_deleted_run_text():
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "sdk-projection.sqlite3"
        planning = seed(database)
        documents, lessons = SQLiteDocumentRepository(database), SQLiteLessonRepository(database)
        SQLiteProposalRepository(database)
        repository = SQLiteLearningRepository(database)
        model = OfflineModel()
        loop = build_learning_loop(model, SQLitePlanningRepository(database), repository, documents, lessons, SQLiteRunRepository(database))
        directory = ConversationService(SQLiteConversationRepository(database), planning, loop, SQLiteLifecycleRepository(database))
        service = LearningService(repository, loop)
        original = repository.mutate
        projecting, release = Event(), Event()

        def paused_projection(goal_id, update):
            projecting.set()
            assert release.wait(5), "test did not release the cached-result projection"
            return original(goal_id, update)

        try:
            with patch.object(repository, "mutate", side_effect=paused_projection), ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(service.learn_node, "g", "n", "private SDK answer", "sdk-projection")
                try:
                    assert projecting.wait(5)
                    run = loop.list_runs("g:n")[0]
                    stale = repository.get("g")
                    stale.run_ids_by_key["stale"] = run.run_id
                    stale.final_text_by_key["stale"] = run.final_text
                    directory.delete("g:n")
                finally:
                    release.set()
                try:
                    future.result(timeout=5)
                except PlanningError as exc:
                    assert exc.code == "run_deleted"
                else:
                    raise AssertionError("Late SDK projection restored a deleted answer")
            before = contents(database)
            try:
                repository.save("g", stale)
            except PlanningError as exc:
                assert exc.code == "run_deleted"
            else:
                raise AssertionError("Stale learning aggregate restored a deleted run cache")
            assert contents(database) == before
            assert repository.get("g").final_text_by_key == {}
            calls = model.calls
            try:
                service.learn_node("g", "n", "private SDK answer", "sdk-projection")
            except RunAdmissionError as exc:
                assert exc.code == "scope_deleted"
            else:
                raise AssertionError("Deleted SDK cached answer was returned")
            assert model.calls == calls
        finally:
            release.set()
            loop.close()
