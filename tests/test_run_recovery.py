from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier, Event
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, RunAdmissionError, RunRecord, RunRequest
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.lessons import LessonError, LessonService
from learngraph_lite.application.planning import PlanningService
from learngraph_lite.bootstrap import build_learning_loop, create_real_app
from learngraph_lite.domain.learning import GraphNode
from learngraph_lite.domain.lessons import ComponentKind, LessonComponent, LessonEvent, LessonPackage
from learngraph_lite.infrastructure import (
    SQLiteLearningRepository, SQLiteLessonRepository, SQLitePlanningRepository, SQLiteRunRepository,
)
from learngraph_lite.presentation.http import create_app


class Model:
    def __init__(self, *, blocked=False, failing=False):
        self.started = Event()
        self.release = Event()
        if not blocked:
            self.release.set()
        self.failing = failing
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("test did not release model")
        if self.failing:
            raise RuntimeError("fixture provider failure")
        return ModelResponse(content="解释已完成", usage={"output_tokens": 2})

    def close(self):
        pass


def seed(database):
    planning = SQLitePlanningRepository(database)
    learning = SQLiteLearningRepository(database)
    lessons = SQLiteLessonRepository(database)
    service = PlanningService(planning)
    service.create_goal("g", "RAG", desired_outcome="demo", current_level="Python", time_budget_minutes=100)
    service.confirm_goal("g")
    service.save_graph_draft("g", (GraphNode("n", "引用", 20), GraphNode("other", "其他", 10)), ())
    learner = LearningService(learning)
    learner.start_goal(service.publish_graph("g", 0))
    setup = LessonService(lessons, learner, AgentLoop(AgentRunner(Model(), ToolRegistry())))
    setup.save_package(LessonPackage("p", "g", "n", 1, "## 定位引用", (
        LessonComponent("steps", ComponentKind.STEPPER, {"steps": [
            {"title": "检索", "description": "检索已绑定资料", "slots": {}},
            {"title": "定位", "description": "保留来源偏移", "slots": {"text": "引用原文"}},
        ]}),)))
    setup.ack_event("g", LessonEvent("ev", "p", "steps", "step_changed", {"step": 1}))
    return planning, learning, lessons


def assembly(database, model, repositories):
    planning, learning, lessons = repositories
    loop = build_learning_loop(model, planning, learning, lessons=lessons, runs=SQLiteRunRepository(database))
    service = LessonService(lessons, LearningService(learning), loop, LearningContext(planning, learning).context)
    return loop, service


def wait_terminal(loop, run_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = loop.get_run(run_id)
        if record.status not in {"queued", "running"}:
            return record
        loop.wait_events(run_id, loop.snapshot(run_id)[1], 0.02)
    raise AssertionError("run did not finish")


def error(code, action, exception=RunAdmissionError):
    try:
        action()
    except exception as exc:
        assert exc.code == code, (exc.code, str(exc))
    else:
        raise AssertionError(f"expected {code}")


def explain(service, request_id="r", slot="initial", retry=None, session="s"):
    return service.submit_explanation(session, "g", "n", "ev", slot, request_id, retry)


def test_run_reopen_recovers_input_result_events_session_scope_and_interrupted_retry():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.db"
        repository = SQLiteRunRepository(database)
        model = Model()
        loop = AgentLoop(AgentRunner(model, ToolRegistry()), repository=repository)
        request = RunRequest("done-session", "saved input", "done")
        done = loop.run(request)
        cancelled = loop.run(RunRequest("cancel-session", "cancel", "cancel"), Budget(cancelled=True))
        loop.close()
        for status in ("queued", "running"):
            pending = RunRecord(status, status, status, root_task_id=status)
            repository.admit(RunRequest(status, "initial " + status, status), pending)
        restored_model = Model()
        restored = AgentLoop(AgentRunner(restored_model, ToolRegistry()), repository=SQLiteRunRepository(database))
        try:
            assert restored_model.calls == []
            assert restored.get_run(done.run_id) == done
            assert restored.request(done.run_id) == request
            assert len(restored.events(done.run_id)) == 2
            assert restored.get_run(cancelled.run_id).status == "cancelled"
            assert restored.run(request).run_id == done.run_id
            assert restored_model.calls == []
            for status in ("queued", "running"):
                assert restored.get_run(status).status == "interrupted"
                assert restored.events(status)[-1].type == "run.interrupted"
                original = restored.request(status)
                error("invalid_retry", lambda: restored.run(replace(original, user_text="changed",
                    idempotency_key="bad", retry_of_run_id=status)))
                retry = restored.run(replace(original, idempotency_key="retry", retry_of_run_id=status))
                assert retry.status == "completed" and retry.root_task_id == status
                assert len(restored.list_runs(status)) == 2
            scoped = RunRecord("scoped", "bound", "completed", goal_id="g", node_id="n", root_task_id="scoped")
            repository.admit(RunRequest("bound", "bound", "b", goal_id="g", node_id="n"), scoped)
        finally:
            restored.close()
        reopened = AgentLoop(AgentRunner(Model(), ToolRegistry()), repository=SQLiteRunRepository(database))
        try:
            error("session_scope_conflict", lambda: reopened.run(RunRequest("bound", "other", "other")))
            assert all(item[1].status not in {"queued", "running"} for item in repository.load())
        finally:
            reopened.close()


def test_explanation_concurrent_new_request_ids_reuse_one_durable_task_and_keep_ack_updates():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.db"
        repositories = seed(database)
        model = Model(blocked=True)
        loop, service = assembly(database, model, repositories)
        try:
            barrier = Barrier(6)

            def submit(index):
                barrier.wait(timeout=3)
                return explain(service, "request-" + str(index)).run_id

            with ThreadPoolExecutor(max_workers=6) as pool:
                ids = tuple(pool.map(submit, range(6)))
            assert len(set(ids)) == 1 and model.started.wait(1)
            initial = loop.request(ids[0])
            assert '"step": 1' in initial.user_text and "保留来源偏移" in initial.user_text
            assert "correct_option_id" not in initial.user_text
            service.ack_event("g", LessonEvent("extra", "p", "chapter", "mark_read", {}))
            assert len(SQLiteRunRepository(database).load()) == 1
            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute("select root_task_id, initial_input from lesson_run_tasks").fetchone() == (
                    ids[0], initial.user_text)
            model.release.set()
            done = wait_terminal(loop, ids[0])
            assert done.status == "completed"
            assert len(model.calls) == 1
        finally:
            model.release.set()
            loop.close()
        new_model = Model()
        reopened, service = assembly(database, new_model, repositories)
        try:
            assert explain(service, "new-request").run_id == ids[0]
            assert new_model.calls == []
            assert reopened.get_run(ids[0]).usage == {"output_tokens": 2}
            error("idempotency_conflict", lambda: explain(service, "different-session", session="other"))
            assert "extra" in repositories[2].state("g").events
        finally:
            reopened.close()


def test_explanation_admission_and_state_event_transactions_rollback_without_false_success():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.db"
        repositories = seed(database)
        model = Model()
        loop, service = assembly(database, model, repositories)
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("""create trigger reject_admission before insert on agent_runs
                begin select raise(abort, 'injected insert failure'); end""")
        error("storage_unavailable", lambda: explain(service))
        assert model.calls == [] and loop.list_runs("s") == ()
        with closing(sqlite3.connect(database)) as connection, connection:
            assert connection.execute("select count(*) from lesson_run_tasks").fetchone()[0] == 0
            connection.execute("drop trigger reject_admission")
            connection.execute("""create trigger reject_terminal before insert on agent_run_events
                when new.seq=2 begin select raise(abort, 'injected event failure'); end""")
        record = explain(service)
        assert wait_terminal(loop, record.run_id).status == "interrupted"
        error("shutting_down", lambda: explain(service, "another"))
        loop.close()
        with closing(sqlite3.connect(database)) as connection, connection:
            durable = json.loads(connection.execute("select record_json from agent_runs").fetchone()[0])
            assert durable["status"] == "running" and durable["final_text"] == ""
            assert connection.execute("select count(*) from agent_run_events").fetchone()[0] == 1
            connection.execute("drop trigger reject_terminal")
        reopened, service = assembly(database, Model(), repositories)
        try:
            assert reopened.get_run(record.run_id).status == "interrupted"
            retry = explain(service, "retry", retry=record.run_id)
            assert wait_terminal(reopened, retry.run_id).status == "completed"
            assert retry.root_task_id == record.run_id
        finally:
            reopened.close()


def test_explanation_failed_cancelled_attempts_require_explicit_retry_and_preserve_root():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.db"
        repositories = seed(database)
        model = Model(failing=True)
        loop, service = assembly(database, model, repositories)
        first = explain(service)
        assert wait_terminal(loop, first.run_id).status == "failed"
        loop.close()
        model = Model(blocked=True)
        loop, service = assembly(database, model, repositories)
        try:
            assert explain(service, "duplicate").run_id == first.run_id and model.calls == []
            error("invalid_retry", lambda: explain(service, "bad-slot", slot="other", retry=first.run_id))
            second = explain(service, "retry", retry=first.run_id)
            assert second.root_task_id == first.run_id and model.started.wait(1)
            assert loop.cancel(second.run_id).status == "cancelled"
            error("session_busy", lambda: explain(service, "too-early", retry=second.run_id))
            model.release.set()
            loop.close()
        finally:
            model.release.set()
            loop.close()
        good_model = Model()
        loop, service = assembly(database, good_model, repositories)
        try:
            third = explain(service, "third", retry=second.run_id)
            assert wait_terminal(loop, third.run_id).status == "completed"
            assert third.root_task_id == first.run_id
            assert loop.request(third.run_id).user_text == loop.request(first.run_id).user_text
            assert explain(service, "duplicate-after-retry").run_id == third.run_id
            error("invalid_retry", lambda: explain(service, "fourth", retry=first.run_id))
            new_slot = explain(service, "new-slot", slot="next")
            assert wait_terminal(loop, new_slot.run_id).status == "completed"
            assert new_slot.root_task_id == new_slot.run_id != first.run_id
            assert len(good_model.calls) == 2
        finally:
            loop.close()


def test_explanation_http_uses_saved_event_validates_scope_and_restores_sse_snapshot():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.db"
        repositories = seed(database)
        model = Model()
        loop, service = assembly(database, model, repositories)
        body = {"request_id": "r", "mode": "explanation", "goal_id": "g", "node_id": "n",
                "source_event_id": "ev", "explanation_slot": "initial"}
        with TestClient(create_app(loop, lesson_events=service), base_url="http://localhost") as client:
            for changes, status, code in (
                ({"user_text": "forged event"}, 422, "invalid_request"),
                ({"source_event_id": None}, 422, "invalid_request"),
                ({"node_id": "other"}, 409, "event_conflict"),
                ({"source_event_id": "missing"}, 404, "event_not_found"),
            ):
                response = client.post("/api/sessions/s/runs", json={**body, **changes})
                assert response.status_code == status, response.text
                assert response.json()["error"]["code"] == code
            assert model.calls == []
            response = client.post("/api/sessions/s/runs", json=body)
            assert response.status_code == 202, response.text
            run_id = response.json()["run_id"]
            assert wait_terminal(loop, run_id).status == "completed"
            service.ack_event("g", LessonEvent("read", "p", "chapter", "mark_read", {}))
            error("invalid_lesson_event", lambda: service.submit_explanation("s", "g", "n", "read", "initial", "read"), LessonError)
        restored_model = Model()
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=restored_model):
            with TestClient(create_real_app(database=database), base_url="http://localhost") as client:
                runs = client.get("/api/sessions/s/runs").json()
                assert len(runs) == 1 and runs[0]["root_task_id"] == run_id
                assert runs[0]["final_text"] == "解释已完成"
                response = client.post("/api/sessions/s/runs", json={**body, "request_id": "after-restart"})
                assert response.status_code == 202 and response.json()["run_id"] == run_id
                frames = client.get(f"/api/runs/{run_id}/events").text
                assert "event: run.snapshot" in frames and '"status": "completed"' in frames
                assert restored_model.calls == []

        repository = SQLiteRunRepository(database)
        request = RunRequest("stopped", "interrupted input", "pending")
        repository.admit(request, RunRecord("pending", "stopped", "queued", root_task_id="pending"))
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=restored_model):
            with TestClient(create_real_app(database=database), base_url="http://localhost") as client:
                pending = client.get("/api/runs/pending").json()
                assert pending["status"] == "interrupted" and pending["root_task_id"] == "pending"
                assert '"status": "interrupted"' in client.get("/api/runs/pending/events").text
                assert restored_model.calls == []


def test_explanation_public_quiz_version_checks_and_persisted_capacity_limits():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.db"
        repositories = seed(database)
        model = Model(blocked=True)
        loop, service = assembly(database, model, repositories)
        learning = LearningService(repositories[1])
        public = learning.create_fixture_exercise("g", "n", "question", "解释题卡中的 RAG 选项")
        service.save_package(LessonPackage("quiz-package", "g", "n", 1, "题卡", (
            LessonComponent("quiz", ComponentKind.QUIZ_CHOICE, {"exercise_id": public.id}),)))
        service.ack_event("g", LessonEvent("quiz-event", "quiz-package", "quiz", "request_explanation", {}))
        try:
            first = explain(service)
            assert model.started.wait(1)
            error("session_busy", lambda: explain(service, "same-session", slot="other"))
            second = service.submit_explanation("second", "g", "n", "quiz-event", "initial", "second")
            error("capacity_exceeded", lambda: service.submit_explanation("third", "g", "n", "quiz-event", "other", "third"))
            text = loop.request(second.run_id).user_text
            assert public.prompt in text and "correct_option_id" not in text
            assert "RAG 学习节点要求回答" not in text
            model.release.set()
            assert wait_terminal(loop, first.run_id).status == "completed"
            assert wait_terminal(loop, second.run_id).status == "completed"
            original = repositories[2].state("g").events["ev"]
            def alter(state):
                state.events["ev"] = replace(original, package_version=99)
            repositories[2].mutate("g", alter)
            error("event_conflict", lambda: explain(service, "bad-version"), LessonError)
            repositories[2].mutate("g", lambda state: state.events.update({"ev": original}))
            # Re-ACK with different payload keeps the first durable step.
            accepted = service.ack_event("g", replace(original, payload={"step": 0}))
            assert accepted.payload == {"step": 1}
            planner = PlanningService(repositories[0])
            state = planner.get_state("g")
            # Inject an accepted content revision without using the unpublished-draft API.
            updated = replace(state.graph, nodes=(GraphNode("n", "语义已修订", 20), GraphNode("other", "其他", 10)),
                              revision=state.graph.revision + 1, content_revision=state.graph.content_revision + 1)
            repositories[0].mutate("g", lambda current: setattr(current, "graph", updated))
            learning.start_goal(updated)
            assert explain(service, "historical-duplicate").run_id == first.run_id
            error("outdated_lesson", lambda: explain(service, "stale", slot="new"), LessonError)
            assert len(model.calls) == 2
        finally:
            model.release.set()
            loop.close()


def test_committed_exercise_and_lesson_are_reused_after_run_result_interruption():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.db"
        repositories = seed(database)

        class GeneratingModel(Model):
            def complete(self, messages, tools):
                self.calls.append((messages, tools))
                schema = messages[0].content
                if "CandidateBatch" in schema:
                    value = {"exercises": [{"prompt": "怎样保留引用？", "options": [
                        {"id": "a", "text": "丢弃偏移"}, {"id": "b", "text": "保存偏移"}],
                        "correct_option_id": "b", "explanation": "PRIVATE-EXPLANATION"}]}
                else:
                    value = {"schema_version": 1, "title": "引用", "markdown": "保留偏移。",
                             "components": [], "citation_ids": []}
                return ModelResponse(content=json.dumps(value, ensure_ascii=False))

        model = GeneratingModel()
        for mode in ("exercise", "lesson"):
            loop, _ = assembly(database, model, repositories)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("""create trigger reject_result before insert on agent_run_events
                    when new.seq=2 begin select raise(abort, 'lost result'); end""")
            request = RunRequest(mode, "生成", "first", mode=mode, goal_id="g", node_id="n")
            record = loop.run(request)
            assert record.status == "interrupted"
            assert len(model.calls) == (1 if mode == "exercise" else 2)
            if mode == "exercise":
                saved_ids = set(repositories[1].get("g").exercises)
            else:
                saved_ids = set(repositories[2].state("g").packages)
            loop.close()
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("drop trigger reject_result")
            restored_model = Model(failing=True)
            loop, _ = assembly(database, restored_model, repositories)
            try:
                retry = loop.run(replace(request, idempotency_key="retry", retry_of_run_id=record.run_id))
                assert retry.status == "completed", retry.error
                assert retry.root_task_id == record.root_task_id
                assert restored_model.calls == []
                if mode == "exercise":
                    assert set(repositories[1].get("g").exercises) == saved_ids
                    assert {item["id"] for item in retry.output["exercises"]} == saved_ids
                else:
                    assert set(repositories[2].state("g").packages) == saved_ids
                    assert retry.output["lesson"]["id"] in saved_ids
                text = json.dumps(retry.output, ensure_ascii=False)
                assert "correct_option_id" not in text and "PRIVATE-EXPLANATION" not in text
            finally:
                loop.close()
