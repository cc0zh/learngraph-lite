from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import AgentRunner, ModelResponse, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, RunRecord, RunRequest
from learngraph_lite.application.conversations import ConversationService
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.planning import PlanningService
from learngraph_lite.bootstrap import _create_business_app, build_fixture_loop, create_real_app
from learngraph_lite.domain.learning import GraphNode
from learngraph_lite.infrastructure import SQLiteLearningRepository, SQLitePlanningRepository, SQLiteRunRepository
from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel
from learngraph_lite.infrastructure.conversation_persistence import SQLiteConversationRepository
from learngraph_lite.presentation.http import create_app


class RecordingModel:
    """Only deterministic fixture responses; records each model input for isolation checks."""

    def __init__(self):
        self.calls = []
        self.closed = False

    def complete(self, messages, tools):
        self.calls.append(messages)
        if not tools:
            return BusinessFixtureModel().complete(messages, tools)
        return ModelResponse("fixture answer: " + messages[-1].content)

    def close(self):
        self.closed = True


def seed(database):
    planning = PlanningService(SQLitePlanningRepository(database))
    learning = LearningService(SQLiteLearningRepository(database))
    for goal_id in ("g", "g2"):
        planning.create_goal(goal_id, f"目标 {goal_id}")
        planning.confirm_goal(goal_id)
        planning.save_graph_draft(goal_id, (GraphNode("n", "节点", 20), GraphNode("other", "其他", 10)), ())
        learning.start_goal(planning.publish_graph(goal_id, 0))
    planning.create_goal("draft", "未发布")
    return planning, learning


def create(client, session_id=None, **fields):
    return client.post("/api/conversations", json={"session_id": session_id or str(uuid4()), **fields})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


def wait_done(client, response):
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        record = client.get(f"/api/runs/{run_id}").json()
        if record["status"] not in {"queued", "running"}:
            assert record["status"] == "completed", record
            return record
        time.sleep(0.01)
    raise AssertionError("fixture run did not finish")


def post_turn(client, session, text, **fields):
    return wait_done(client, client.post(f"/api/sessions/{session}/runs", json={
        "request_id": str(uuid4()), "user_text": text, **fields,
    }))


def test_conversation_api_empty_sessions_planning_projection_and_sqlite_reopen_are_read_only():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        model = RecordingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            assert client.get("/api/conversations").json() == []
            # The old creation endpoint still creates only a goal, not a run.
            goal = client.post("/api/goals", json={"title": "新目标"}).json()
            planning_id = "planning:" + goal["goal_id"]
            planning = client.get(f"/api/conversations/{planning_id}").json()
            assert planning["kind"] == "planning" and planning["title"] == "新目标"
            assert planning["goal_id"] == goal["goal_id"] and planning["node_id"] is None
            assert datetime.fromisoformat(planning["created_at"]).year == 1970
            assert client.get(f"/api/sessions/{planning_id}/runs").json() == []
            response = create(client, title="空对话")
            assert response.status_code == 201, response.text
            general = response.json()
            session = general["session_id"]
            assert general["kind"] == "general" and general["goal_id"] is None and general["node_id"] is None
            assert datetime.fromisoformat(general["created_at"]).tzinfo is not None
            assert client.get(f"/api/sessions/{session}/runs").json() == []
            assert len(client.get("/api/conversations").json()) == 2
            assert_error(client.get("/api/conversations/missing"), 404, "conversation_not_found")
            assert model.calls == []
        # Exercise the official real factory with a fixture gateway; no config/provider access.
        restored = RecordingModel()
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=restored):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as client:
            assert client.get(f"/api/conversations/{session}").json() == general
            assert client.get(f"/api/conversations/{planning_id}").json() == planning
            assert client.get(f"/api/sessions/{session}/runs").json() == []
            assert model.calls == restored.calls == []


def test_learning_conversation_creation_is_idempotent_and_scope_and_fingerprint_are_immutable():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        planning, learning = seed(database)
        model = RecordingModel()
        session = str(uuid4())
        general_id = str(uuid4())
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            first = create(client, session, goal_id="g", node_id="n").json()
            assert first["kind"] == "learning" and first["title"] == "学习：节点"
            assert create(client, session, goal_id="g", node_id="n").json() == first
            assert create(client, general_id).status_code == 201
            assert create(client, general_id, goal_id=None, node_id=None).status_code == 201
            for fields in ({}, {"goal_id": "g", "node_id": "other"}, {"goal_id": "g2", "node_id": "n"},
                           {"goal_id": "g", "node_id": "n", "title": "学习：节点"}):
                assert_error(create(client, session, **fields), 409, "conversation_conflict")
            assert_error(create(client, general_id, goal_id="g", node_id="n"), 409, "conversation_conflict")
            assert_error(create(client, "planning:g", goal_id="g", node_id="n"), 409, "conversation_conflict")
            # Exact replay still reads a historical identity after the graph becomes a draft.
            planning.update_node("g", "n", title="后来改名")
            assert create(client, session, goal_id="g", node_id="n").json() == first
            assert model.calls == [] and learning.context("g", "n")["node"]["sample_count"] == 0
        with TestClient(_create_business_app(RecordingModel(), "fixture", database), base_url="http://localhost") as client:
            assert create(client, session, goal_id="g", node_id="n").json() == first
            assert_error(create(client, session, goal_id="g2", node_id="n"), 409, "conversation_conflict")


def test_creation_rejects_invalid_unknown_and_unpublished_scope_without_running_a_model():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        seed(database)
        model = RecordingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            for fields, status, code in (
                ({"goal_id": "missing", "node_id": "n"}, 404, "goal_not_found"),
                ({"goal_id": "g", "node_id": "missing"}, 404, "node_not_found"),
                ({"goal_id": "draft", "node_id": "n"}, 409, "graph_not_published"),
                ({"goal_id": "g"}, 422, "invalid_conversation"),
                ({"node_id": "n"}, 422, "invalid_conversation"),
            ):
                assert_error(create(client, **fields), status, code)
            for fields in ({"title": "  "}, {"title": 42}, {"unexpected": "value"}):
                assert_error(create(client, **fields), 422, "invalid_request")
            assert_error(create(client, "not-a-uuid"), 422, "invalid_conversation")
            assert len(client.get("/api/conversations").json()) == 3
            assert model.calls == []


def test_all_write_run_endpoints_validate_managed_scope_before_queue_or_model():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        seed(database)
        model = RecordingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            session = create(client, goal_id="g", node_id="n").json()["session_id"]
            general = create(client).json()["session_id"]
            for selected in (session, general, "planning:g", "planning:nonexistent"):
                for mode in ("runner", "teaching", "explanation"):
                    body = {"request_id": str(uuid4()), "mode": mode, "goal_id": "g", "node_id": "other"}
                    if mode == "explanation":
                        body.update(source_event_id="not-an-event", explanation_slot="initial")
                    else:
                        body["user_text"] = "forged scope"
                    assert_error(client.post(f"/api/sessions/{selected}/runs", json=body),
                                 409, "conversation_scope_conflict")
                for operation in ("exercises", "lessons"):
                    assert_error(client.post(f"/api/goals/g/nodes/other/{operation}", json={
                        "session_id": selected, "request_id": str(uuid4()),
                    }), 409, "conversation_scope_conflict")
                assert_error(client.post("/api/goals/g/graph-proposals/generate", json={
                    "session_id": selected, "request_id": str(uuid4()),
                }), 409, "conversation_scope_conflict")
                assert client.get(f"/api/sessions/{selected}/runs").json() == []
            assert_error(client.post(f"/api/sessions/{session}/runs", json={
                "request_id": "missing-scope", "user_text": "hello",
            }), 409, "conversation_scope_conflict")
            # A general runner remains usable, and cannot silently become teaching.
            post_turn(client, general, "ordinary general chat")
            assert_error(client.post(f"/api/sessions/{general}/runs", json={
                "request_id": "teaching", "user_text": "teach", "mode": "teaching",
            }), 409, "conversation_scope_conflict")
            assert len(model.calls) == 1


def test_old_history_discovery_filters_non_chat_modes_and_cannot_be_overwritten():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        planning, _ = seed(database)
        repository = SQLiteRunRepository(database)
        legacy_uuid = str(uuid4())
        # Persist old snapshots without using the new directory. Even a proposal-only
        # UUID is reserved against adoption, though it is not an ordinary chat entry.
        hidden_uuid = str(uuid4())
        for session, mode, goal_id, node_id, text in (
            (legacy_uuid, "teaching", "g", "n", "旧学习"),
            (legacy_uuid, "teaching", "g", "n", "旧学习第二轮"),
            ("old-runner", "runner", "g", "other", "旧只读对话"),
            ("old-general", "runner", None, None, "旧普通聊天"),
            ("old-lesson", "lesson", "g", "n", ""),
            ("old-explanation", "explanation", "g", "n", ""),
            ("old-exercise", "exercise", "g", "n", ""),
            (hidden_uuid, "proposal", "g", None, ""),
            ("planning:g", "planning", "g", None, "旧规划"),
        ):
            run_id = str(uuid4())
            repository.admit(RunRequest(session, text, run_id, mode=mode, goal_id=goal_id, node_id=node_id),
                RunRecord(run_id, session, "completed", mode=mode, user_text=text,
                          goal_id=goal_id, node_id=node_id, root_task_id=run_id))
        model = RecordingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            records = {record["session_id"]: record for record in client.get("/api/conversations").json()}
            assert set(records) == {"planning:g", "planning:g2", "planning:draft", legacy_uuid, "old-runner", "old-general"}
            assert records[legacy_uuid]["legacy"] is True and records[legacy_uuid]["kind"] == "learning"
            assert records["old-general"]["kind"] == "general"
            assert records["planning:g"]["created_at"] != "1970-01-01T00:00:00Z"
            assert_error(create(client, legacy_uuid, goal_id="g", node_id="n"), 409, "conversation_conflict")
            assert_error(create(client, hidden_uuid), 409, "conversation_conflict")
            # Remove the old node from a newly published graph. Historical entries
            # and run lists remain available without resetting attempts or history.
            planning.update_node("g", "n", title="transition to draft")
            planning.save_graph_draft("g", (GraphNode("other", "其他", 10),), ())
            planning.publish_graph("g", 1)
            assert client.get(f"/api/conversations/{legacy_uuid}").json()["node_id"] == "n"
            assert len(client.get(f"/api/sessions/{legacy_uuid}/runs").json()) == 2
            assert_error(client.post(f"/api/sessions/{legacy_uuid}/runs", json={
                "request_id": "new", "user_text": "继续", "mode": "teaching", "goal_id": "g", "node_id": "n",
            }), 404, "node_not_found")
            assert model.calls == []


def test_two_same_node_conversations_keep_transcripts_separate_but_share_exercises_lessons_and_grades():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        seed(database)
        model = RecordingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            a, b = [create(client, goal_id="g", node_id="n").json()["session_id"] for _ in range(2)]
            scope = {"goal_id": "g", "node_id": "n", "mode": "teaching"}
            post_turn(client, a, "A_ONLY", **scope)
            post_turn(client, b, "B_ONLY", **scope)
            assert all("A_ONLY" not in message.content for message in model.calls[-1])
            post_turn(client, a, "A_FOLLOWUP", **scope)
            texts = [message.content for message in model.calls[-1]]
            assert "A_ONLY" in texts and not any("B_ONLY" in text for text in texts)
            assert len(client.get(f"/api/sessions/{a}/runs").json()) == 2
            assert len(client.get(f"/api/sessions/{b}/runs").json()) == 1
            base = "/api/goals/g/nodes/n"
            exercise_run = wait_done(client, client.post(base + "/exercises", json={"session_id": a, "request_id": "exercise"}))
            exercise = exercise_run["output"]["exercises"][0]
            # Node facts are not partitioned by session: both sessions see these IDs.
            assert client.get(base + "/exercises").json()["exercises"][0]["id"] == exercise["id"]
            feedback = client.post(f"/api/goals/g/exercises/{exercise['id']}/attempts", json={
                "submission_id": "answer", "selected_option_id": "b",
            })
            assert feedback.status_code == 200, feedback.text
            lesson_run = wait_done(client, client.post(base + "/lessons", json={
                "session_id": b, "request_id": "lesson", "exercise_ids": [exercise["id"]],
            }))
            lesson = lesson_run["output"]["lesson"]
            assert client.get(base + "/lessons").json()["lessons"][0]["id"] == lesson["id"]
            assert client.get(base + "/context").json()["node"]["sample_count"] == 1
            # A legitimate managed-session explanation passes the same directory
            # check, but still uses only a persisted, server-constructed event.
            ack = client.post(f"/api/goals/g/lessons/{lesson['id']}/events", json={
                "event_id": "explain-event", "package_version": lesson["version"],
                "component_id": "steps", "action": "step_changed", "payload": {"step": 1},
            })
            assert ack.status_code == 200, ack.text
            explanation = wait_done(client, client.post(f"/api/sessions/{b}/runs", json={
                "request_id": "explain", "mode": "explanation", "goal_id": "g", "node_id": "n",
                "source_event_id": "explain-event", "explanation_slot": "initial",
            }))
            assert explanation["session_id"] == b and explanation["mode"] == "explanation"
            # Exercise/lesson runs never enter a teaching transcript.
            post_turn(client, b, "B_FOLLOWUP", **scope)
            texts = [message.content for message in model.calls[-1]]
            assert "B_ONLY" in texts and not any("A_ONLY" in text for text in texts)
            assert not any("生成练习" == text or "生成学习页" == text for text in texts)
            assert len(client.get("/api/conversations").json()) == 5
        restored_model = RecordingModel()
        with TestClient(_create_business_app(restored_model, "fixture", database), base_url="http://localhost") as client:
            post_turn(client, a, "A_AFTER_REOPEN", **scope)
            texts = [message.content for message in restored_model.calls[-1]]
            assert "A_ONLY" in texts and not any("B_ONLY" in text for text in texts)
            assert client.get(base + "/context").json()["node"]["sample_count"] == 1


def test_managed_historical_removed_node_stays_readable_but_new_teaching_run_is_rejected():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        planning, _ = seed(database)
        model = RecordingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            record = create(client, goal_id="g", node_id="n").json()
            session = record["session_id"]
            post_turn(client, session, "saved history", goal_id="g", node_id="n", mode="teaching")
            planning.update_node("g", "n", title="transition to draft")
            planning.save_graph_draft("g", (GraphNode("other", "其他", 10),), ())
            planning.publish_graph("g", 1)
            assert client.get(f"/api/conversations/{session}").json() == record
            assert record in client.get("/api/conversations").json()
            assert len(client.get(f"/api/sessions/{session}/runs").json()) == 1
            assert_error(client.post(f"/api/sessions/{session}/runs", json={
                "request_id": "new", "user_text": "new", "mode": "teaching", "goal_id": "g", "node_id": "n",
            }), 404, "node_not_found")
            assert len(model.calls) == 1


def test_optional_directory_does_not_change_unmanaged_or_planning_apis_and_snapshot_is_detached():
    loop = build_fixture_loop()
    with TestClient(create_app(loop), base_url="http://localhost") as client:
        assert client.get("/api/conversations").status_code == 404
        post_turn(client, "old-unmanaged", "compatible")
        snapshots = loop.list_all_runs()
        snapshots[0].output["bad"] = True
        assert "bad" not in loop.get_run(snapshots[0].run_id).output
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        seed(database)
        model = RecordingModel()
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            # New guards do not disable the existing planning session contract.
            record = wait_done(client, client.post("/api/goals/draft/planning-runs", json={
                "expected_version": 0, "request_id": "planning", "user_text": "解释为什么",
            }))
            assert record["session_id"] == "planning:draft" and record["mode"] == "planning"
            assert client.get("/api/conversations/planning:draft").status_code == 200
            # Unmanaged old node sessions still have the ordinary public API.
            post_turn(client, "unmanaged-legacy", "old API", goal_id="g", node_id="n")


def test_workbench_goal_creation_is_atomic_idempotent_recoverable_and_keeps_first_title_fingerprint():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        model = RecordingModel()
        goal_id = str(uuid4())
        body = {"goal_id": goal_id, "title": "首次输入"}
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost") as client:
            response = client.post("/api/workbench/goals", json=body)
            assert response.status_code == 201, response.text
            first = response.json()
            assert first["goal_id"] == goal_id and first["version"] == 0 and first["graph"] is None
            assert client.get(f"/api/goals/{goal_id}").json() == first
            assert client.post("/api/workbench/goals", json=body).json() == first
            current = client.patch(f"/api/goals/{goal_id}", json={"expected_version": 0, "title": "后来编辑"}).json()
            assert current["version"] == 1
            assert client.post("/api/workbench/goals", json=body).json() == current
            assert_error(client.post("/api/workbench/goals", json={**body, "title": "后来编辑"}),
                         409, "goal_creation_conflict")
            old_goal = client.post("/api/goals", json={"title": "旧接口目标"}).json()
            assert_error(client.post("/api/workbench/goals", json={"goal_id": old_goal["goal_id"], "title": "旧接口目标"}),
                         409, "goal_creation_conflict")
            assert_error(client.post("/api/workbench/goals", json={"goal_id": "invalid", "title": "x"}),
                         422, "invalid_conversation")
            assert_error(client.post("/api/workbench/goals", json={"goal_id": str(uuid4()), "title": " "}),
                         422, "invalid_request")
            planning = client.get(f"/api/conversations/planning:{goal_id}").json()
            assert datetime.fromisoformat(planning["created_at"]).year > 1970
            assert client.get(f"/api/sessions/planning:{goal_id}/runs").json() == []
            assert model.calls == []
        restored_model = RecordingModel()
        with TestClient(_create_business_app(restored_model, "fixture", database), base_url="http://localhost") as client:
            assert client.get(f"/api/goals/{goal_id}").json() == current
            assert client.post("/api/workbench/goals", json=body).json() == current
            assert client.get(f"/api/conversations/planning:{goal_id}").json() == planning
            assert restored_model.calls == []


def test_sqlite_workbench_goal_concurrent_replay_and_failed_operation_roll_back_goal_together():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "conversations.sqlite3"
        repository = SQLiteConversationRepository(database)
        planning = PlanningService(SQLitePlanningRepository(database))
        loop = AgentLoop(AgentRunner(RecordingModel(), ToolRegistry()))
        service = ConversationService(repository, planning, loop)
        goal_id = str(uuid4())
        try:
            # Separate services/locks exercise the durable SQLite idempotency check,
            # not only the API process's creation lock.
            second = ConversationService(SQLiteConversationRepository(database), planning, loop)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda service: service.create_goal(goal_id, "concurrent"), (service, second)))
            assert results[0] == results[1]
            assert len(planning.list_goals()) == 1
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("""create trigger fail_workbench_operation before insert on workbench_goal_operations
                    begin select raise(abort, 'fixture storage failure'); end""")
            failed_id = str(uuid4())
            try:
                service.create_goal(failed_id, "must roll back")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("fixture write failure was swallowed")
            assert len(planning.list_goals()) == 1
            assert repository.goal_created_at(failed_id) is None
        finally:
            loop.close()
