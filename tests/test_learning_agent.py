from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import Budget, ModelResponse, ToolCall
from learngraph_lite.application.agent import RunAdmissionError, RunRequest
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.learning_agent import LearningContext, LearningContextError
from learngraph_lite.application.planning import PlanningService, candidate_rag_graph
from learngraph_lite.bootstrap import build_learning_loop, create_real_app
from learngraph_lite.infrastructure import SQLiteLearningRepository, SQLitePlanningRepository


def setup_goal(database: Path, goal_id: str = "g1", *, start_learning: bool = True):
    planning_repository = SQLitePlanningRepository(database)
    learning_repository = SQLiteLearningRepository(database)
    planning = PlanningService(planning_repository)
    planning.create_goal(goal_id, f"目标 {goal_id}", desired_outcome="RAG demo", current_level="Python",
                         time_budget_minutes=1200)
    planning.confirm_goal(goal_id)
    draft = candidate_rag_graph(goal_id)
    planning.save_graph_draft(goal_id, draft.nodes, draft.edges)
    learning = LearningService(learning_repository)
    graph = planning.publish_graph(goal_id, expected_revision=0)
    if not start_learning:
        return planning_repository, learning_repository
    learning.start_goal(graph)
    for index in range(3):
        learning.create_fixture_exercise(goal_id, "rag-goal", f"e{index}", f"引用题 {index}")
        learning.submit_answer(goal_id, f"e{index}", "b", f"a{index}")
    return planning_repository, learning_repository


class ReadingModel:
    def __init__(self, *, barrier=None, repair_scope=False):
        self.barrier = barrier
        self.repair_scope = repair_scope
        self.closed = False
        self.transcripts = []

    def close(self):
        self.closed = True

    def complete(self, messages, tools):
        names = {tool["function"]["name"] for tool in tools}
        assert names == {"get_learning_context", "get_next_action"}
        for tool in tools:
            schema = tool["function"]["parameters"]
            assert schema["additionalProperties"] is False
            assert not {"goal_id", "node_id"} & set(schema.get("properties", {}))
        self.transcripts.append(messages)
        results = [json.loads(message.content) for message in messages if message.role == "tool"]
        if not results:
            assert messages[0].role == "system"
            initial = json.loads(messages[1].content.removeprefix("learning_context: "))
            assert initial["node"]["id"] == "document-loading"
            assert messages[2].content == "当前问题"
            if self.barrier is not None:
                self.barrier.wait(timeout=3)
            if self.repair_scope:
                return ModelResponse(tool_calls=(ToolCall("bad", "get_learning_context", '{"goal_id":"g2"}'),))
        if not results or (self.repair_scope and len(results) == 1):
            return ModelResponse(tool_calls=(
                ToolCall("context", "get_learning_context", "{}"),
                ToolCall("next", "get_next_action", '{"available_minutes":10}'),
            ))
        context, action = results[-2:]
        return ModelResponse(content=json.dumps({"goal_id": context["goal_id"], "action": action}))


def request(session="s1", goal_id="g1", node_id="document-loading", key="r1"):
    return RunRequest(session, "当前问题", key, goal_id=goal_id, node_id=node_id)


def test_learning_tools_use_persisted_progress_and_repair_scope_arguments():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        setup_goal(database)
        # Reopen repositories to prove this is persisted business data.
        planning, learning = SQLitePlanningRepository(database), SQLiteLearningRepository(database)
        context = LearningContext(planning, learning)
        model = ReadingModel(repair_scope=True)
        with_loop = build_learning_loop(model, planning, learning)
        try:
            record = with_loop.run(request())
            assert record.status == "completed", record.error
            assert "invalid arguments" in record.error
            assert json.loads(record.final_text) == {
                "goal_id": "g1", "action": json.loads(json.dumps(context.next_action("g1", "document-loading", 10))),
            }
        finally:
            with_loop.close()
        data = context.context("g1", "document-loading")
        assert data["node"]["mastery"] == "unknown"
        assert data["prerequisites"][0]["mastery"] == "proficient"
        assert data["prerequisites"][0]["sample_count"] == 3
        public_text = json.dumps(data)
        assert not any(key in public_text for key in ("correct_option_id", "exercises", "attempts", "final_text"))
        assert len(learning.get("g1").attempts) == 3
        transcript = model.transcripts[-1]
        assert [message.tool_call_id for message in transcript if message.role == "tool"] == ["bad", "context", "next"]


def test_concurrent_learning_runs_keep_server_bound_scopes_and_session_identity():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning, learning = setup_goal(database)
        setup_goal(database, "g2")
        loop = build_learning_loop(ReadingModel(barrier=threading.Barrier(2)), planning, learning)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                pending = [executor.submit(loop.run, request(session=goal, goal_id=goal)) for goal in ("g1", "g2")]
                records = [future.result(timeout=5) for future in pending]
            assert [record.status for record in records] == ["completed", "completed"]
            assert [json.loads(record.final_text)["goal_id"] for record in records] == ["g1", "g2"]
            for bad_request, code in (
                (request(session="g1", goal_id="g2", key="new"), "session_scope_conflict"),
                (request(session="g1", node_id="rag-goal", key="new"), "session_scope_conflict"),
                (request(session="g1", goal_id="g2"), "idempotency_conflict"),
                (RunRequest("missing-pair", "x", "r", goal_id="g1"), "invalid_scope"),
            ):
                try:
                    loop.run(bad_request)
                except RunAdmissionError as exc:
                    assert exc.code == code
                else:
                    raise AssertionError(f"expected {code}")
        finally:
            loop.close()


def test_learning_context_rejects_missing_unpublished_and_stale_snapshots():
    with tempfile.TemporaryDirectory() as directory:
        planning_repository, learning_repository = setup_goal(Path(directory) / "test.sqlite3")
        context = LearningContext(planning_repository, learning_repository)
        planning = PlanningService(planning_repository)
        planning.create_goal("unconfirmed", "未确认的目标")
        setup_goal(Path(directory) / "test.sqlite3", "unstarted", start_learning=False)
        for goal_id, node_id, code in (("missing", "rag-goal", "goal_not_found"),
                                      ("g1", "missing", "node_not_found"),
                                      ("unconfirmed", "rag-goal", "graph_not_published"),
                                      ("unstarted", "rag-goal", "learning_not_started")):
            try:
                context.context(goal_id, node_id)
            except LearningContextError as exc:
                assert exc.code == code
            else:
                raise AssertionError(code)

        class ToolOnlyModel:
            def complete(self, messages, tools):
                return ModelResponse(tool_calls=(ToolCall("context", "get_learning_context", "{}"),))

        prepared = context.prepare(ToolOnlyModel(), request())
        planning.update_node("g1", "rag-goal", title="已修改目标边界")
        try:
            context.context("g1", "document-loading")
        except LearningContextError as exc:
            assert exc.code == "graph_not_published"
        else:
            raise AssertionError("draft was accepted")
        graph = planning.publish_graph("g1", expected_revision=1)
        for read in (context.context, context.next_action):
            try:
                read("g1", "document-loading")
            except LearningContextError as exc:
                assert exc.code == "stale_learning_graph"
            else:
                raise AssertionError("stale graph was accepted")
        model = ReadingModel()
        loop = build_learning_loop(model, planning_repository, learning_repository)
        try:
            failed = loop.run(request())
            assert failed.status == "failed" and not model.transcripts
        finally:
            loop.close()
        # Refresh only in this test, then check that an existing turn remains pinned.
        LearningService(learning_repository).start_goal(graph)
        result = prepared.runner.run(prepared.messages, Budget(max_steps=1))
        assert "stale_run_context" in result.messages[-1].content


def test_real_http_factory_shares_learning_reads_and_maps_scope_errors():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning, learning = setup_goal(database)
        context = LearningContext(planning, learning)
        model = ReadingModel()
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            base = "/api/goals/g1/nodes/document-loading"
            assert api.get(base + "/context").json() == json.loads(json.dumps(context.context("g1", "document-loading")))
            assert api.get(base + "/next-action?available_minutes=10").json() == json.loads(json.dumps(context.next_action("g1", "document-loading", 10)))
            assert api.get(base + "/next-action?available_minutes=0").status_code == 422
            assert api.get("/api/goals/g1/nodes/missing/context").status_code == 404
            body = {"request_id": "r1", "user_text": "当前问题", "goal_id": "g1", "node_id": "document-loading"}
            submitted = api.post("/api/sessions/s1/runs", json=body)
            assert submitted.status_code == 202
            with api.stream("GET", f"/api/runs/{submitted.json()['run_id']}/events") as stream:
                assert "completed" in stream.read().decode()
            changed = api.post("/api/sessions/s1/runs", json={**body, "request_id": "r2", "node_id": "rag-goal"})
            assert changed.status_code == 409 and changed.json()["error"]["code"] == "session_scope_conflict"
            body.pop("node_id")
            assert api.post("/api/sessions/s2/runs", json=body).status_code == 422
            PlanningService(planning).update_node("g1", "rag-goal", title="改动")
            unpublished = api.get(base + "/context")
            assert unpublished.status_code == 409 and unpublished.json()["error"]["code"] == "graph_not_published"
        assert model.closed


def test_learning_agent_demo_refuses_existing_database():
    script = Path(__file__).resolve().parents[1] / "scripts" / "run-learning-agent-demo.py"
    spec = importlib.util.spec_from_file_location("learning_agent_demo", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "demo.sqlite3"
        result = module.run_demo(database)
        assert result["mode"] == "fixture" and result["status"] == "completed"
        assert "short_explanation:document-loading" in result["final_text"]
        before = database.read_bytes()
        try:
            module.run_demo(database)
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing database was overwritten")
        assert database.read_bytes() == before
