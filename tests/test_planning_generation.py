from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import Budget, ModelResponse
from learngraph_lite.application.agent import RunAdmissionError, RunRequest
from learngraph_lite.application.learning import InMemoryLearningRepository
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningError, PlanningService
from learngraph_lite.application.planning_generation import CandidateGraph
from learngraph_lite.bootstrap import build_learning_loop, create_real_app
from learngraph_lite.domain.learning import GraphNode, GraphStatus, MasteryState
from learngraph_lite.domain.learning.recommendations import recommend_next_action
from learngraph_lite.infrastructure import SQLitePlanningRepository


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def complete(self, messages, tools):
        assert tools == ()
        self.calls.append(messages)
        response = next(self.responses)
        return response() if callable(response) else ModelResponse(content=response, usage={"output_tokens": 4})

    def close(self):
        self.closed = True


def graph_json(count=2, cycle=False):
    return json.dumps({"nodes": [{"id": f"n{i}", "title": f"节点{i}", "explanation": "解释",
                      "learning_outcome": "能完成对应实践", "estimated_minutes": 20, "priority": i % 6}
                     for i in range(count)],
        "edges": ([{"source": "n0", "target": "n1"}, {"source": "n1", "target": "n0"}] if cycle else
                  [{"source": f"n{i}", "target": f"n{i+1}"} for i in range(count - 1)])}, ensure_ascii=False)


def setup(repository=None, confirmed=False):
    repository = repository or InMemoryPlanningRepository()
    service = PlanningService(repository)
    service.create_goal("g1", "学习 RAG")
    if confirmed:
        service.confirm_goal("g1")
    return repository, service


def request(service, mode="graph", key="r1", goal_id="g1", count=2):
    return RunRequest(f"planning:{goal_id}", "规划", key, mode=mode, goal_id=goal_id,
                      task_ref=f"goal:{goal_id}", planning_version=service.get_state(goal_id).version,
                      graph_node_count=count)


def test_clarification_is_suggestion_only_bounded_and_skippable():
    repository, service = setup()
    question = json.dumps({"questions": [{"field": "desired_outcome", "question": "希望做出什么？"}]})
    model = Model(["{}", question, question])
    loop = build_learning_loop(model, repository, InMemoryLearningRepository())
    try:
        budget = Budget()
        first = loop.run(request(service, "clarify"), budget)
        assert first.status == "completed", first.error
        assert budget.model_calls == 2 and first.usage == {"output_tokens": 8}
        state = service.get_state("g1")
        assert state.questions == ("希望做出什么？",) and state.clarification_round == 1
        assert not state.goal.confirmed and not state.goal.desired_outcome and state.goal.assumptions
        assert first.output["planning"]["version"] == state.version
        second = loop.run(request(service, "clarify", "r2"))
        assert second.status == "completed" and service.get_state("g1").clarification_round == 2
        try:
            loop.run(request(service, "clarify", "r3"))
        except PlanningError as exc:
            assert exc.code == "clarification_limit"
        else:
            raise AssertionError("third round accepted")
        service.confirm_goal("g1", service.get_state("g1").version)
        assert service.get_state("g1").questions == () and service.get_state("g1").goal.assumptions
        assert len(model.calls) == 3
    finally:
        loop.close()

    repository, service = setup()
    service.edit_goal("g1", 0, desired_outcome="demo", current_level="Python", time_budget_minutes=100)
    model = Model([])
    loop = build_learning_loop(model, repository, InMemoryLearningRepository())
    try:
        result = loop.run(request(service, "clarify"))
        assert result.status == "completed" and not model.calls
        assert service.get_state("g1").clarification_round == 0
    finally:
        loop.close()


def test_graph_repair_retry_failure_budget_and_cancel_never_publish():
    for responses, expected, max_calls in (([graph_json(cycle=True), graph_json()], "completed", 6),
                                            (["{}", "{}", graph_json()], "failed", 6),
                                            (["{}"], "budget_exceeded", 1)):
        repository, service = setup(confirmed=True)
        model = Model(responses)
        loop = build_learning_loop(model, repository, InMemoryLearningRepository())
        original = request(service)
        budget = Budget(max_model_calls=max_calls)
        try:
            result = loop.run(original, budget)
            assert result.status == expected, result.error
            assert not budget.model_calls > max_calls
            assert service.get_state("g1").goal.confirmed
            if expected == "completed":
                graph = service.current_graph("g1")
                assert graph.status == GraphStatus.DRAFT and graph.revision == graph.content_revision == 0
                assert graph.nodes[0].explanation and graph.nodes[0].learning_outcome
                assert len(model.calls) == 2 and result.output["source_mode"] == "general"
                assert loop.run(original).run_id == result.run_id
            else:
                assert service.current_graph("g1") is None
                if expected == "failed":
                    retry = loop.run(replace(original, idempotency_key="retry", retry_of_run_id=result.run_id))
                    assert retry.status == "completed" and retry.root_task_id == result.root_task_id
        finally:
            loop.close()

    repository, service = setup(confirmed=True)
    budget = Budget()
    def cancel():
        budget.cancelled = True
        return ModelResponse(content=graph_json())
    loop = build_learning_loop(Model([cancel]), repository, InMemoryLearningRepository())
    try:
        assert loop.run(request(service), budget).status == "cancelled"
        assert service.current_graph("g1") is None
    finally:
        loop.close()


def test_generation_output_keeps_commit_snapshot_during_later_edit():
    question = json.dumps({"questions": [{"field": "desired_outcome", "question": "期望产出？"}]})
    for mode, response in (("clarify", question), ("graph", graph_json())):
        repository, service = setup(confirmed=mode == "graph")
        original = request(service, mode)
        mutate = repository.mutate
        edited = False

        def edit_after_commit(goal_id, update):
            nonlocal edited
            result = mutate(goal_id, update)
            if not edited:
                edited = True
                service.edit_goal(goal_id, repository.get(goal_id).version, title="后续编辑")
            return result

        loop = build_learning_loop(Model([response]), repository, InMemoryLearningRepository())
        try:
            with patch.object(repository, "mutate", side_effect=edit_after_commit):
                result = loop.run(original)
            assert result.status == "completed", result.error
            saved = result.output["planning"]
            assert saved["goal"]["title"] == "学习 RAG"
            assert saved["version"] == original.planning_version + 1
            assert service.get_state("g1").version == saved["version"] + 1
            assert service.get_state("g1").goal.title == "后续编辑"
            if mode == "graph":
                assert len(saved["graph"]["nodes"]) == 2 and service.current_graph("g1") is None
            else:
                assert saved["questions"] == ("期望产出？",) and not service.get_state("g1").questions
        finally:
            loop.close()


def test_sqlite_generation_conflicts_and_publication_are_atomic():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "planning.sqlite3"
        repository, service = setup(SQLitePlanningRepository(database), confirmed=True)
        another = PlanningService(SQLitePlanningRepository(database))
        entered, release = threading.Event(), threading.Event()
        def blocked():
            entered.set()
            assert release.wait(5)
            return ModelResponse(content=graph_json())
        loop = build_learning_loop(Model([blocked]), repository, InMemoryLearningRepository())
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(loop.run, request(service))
                assert entered.wait(5)
                another.edit_goal("g1", 1, title="用户修改后的目标")
                release.set()
                result = future.result(timeout=5)
                assert result.status == "failed" and "version changed" in result.error, (result.status, result.error)
                assert service.current_graph("g1") is None and service.get_state("g1").goal.title == "用户修改后的目标"
        finally:
            release.set()
            loop.close()
        service.confirm_goal("g1")
        graph = CandidateGraph.model_validate_json(graph_json()).graph()
        service.save_graph_draft("g1", graph.nodes, graph.edges)
        version = service.get_state("g1").version
        barrier = threading.Barrier(2)
        def publish(planner):
            barrier.wait(5)
            try:
                return planner.publish_graph("g1", 0, version).status
            except PlanningError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, (service, another)))
        assert sorted(results) == ["planning_conflict", "published"]
        assert service.get_state("g1").version == version + 1
        before = service.get_state("g1")
        def fail(state):
            state.questions = ("should roll back",)
            raise ValueError("abort")
        try:
            repository.mutate("g1", fail)
        except ValueError:
            pass
        else:
            raise AssertionError("failed mutation accepted")
        assert repository.get("g1") == before


def test_planning_http_full_journey_validates_and_restores_without_resetting_learning():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "app.sqlite3"
        questions = json.dumps({"questions": [{"field": "desired_outcome", "question": "期望产出？"}]})
        model = Model([questions, graph_json(10)])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            assert api.post("/api/goals", json={"title": "   "}).status_code == 422
            created = api.post("/api/goals", json={"title": "学习 RAG"})
            assert created.status_code == 201
            goal_id = created.json()["goal_id"]
            base = f"/api/goals/{goal_id}"
            assert len(api.get("/api/goals").json()) == 1
            assert api.get("/api/goals/missing").status_code == 404
            assert api.patch(base, json={"expected_version": 0, "title": None}).status_code == 422
            assert api.patch(base, json={"expected_version": 0}).status_code == 422
            assert api.get(base).json() == created.json()
            assert api.post(base + "/graph-drafts", json={"request_id": "early", "expected_version": 0}).status_code == 409
            body = {"request_id": "clarify", "expected_version": 0}
            submitted = api.post(base + "/clarify", json=body)
            assert submitted.status_code == 202
            run_id = submitted.json()["run_id"]
            with api.stream("GET", f"/api/runs/{run_id}/events") as stream:
                assert "期望产出" in stream.read().decode()
            result = api.get(f"/api/runs/{run_id}").json()
            assert result["task_ref"] == f"goal:{goal_id}" and result["output"]["planning"]["clarification_round"] == 1
            assert api.post(base + "/clarify", json=body).json()["run_id"] == run_id
            assert api.patch(base, json={"expected_version": 0, "title": "stale"}).status_code == 409
            edited = api.patch(base, json={"expected_version": 1, "desired_outcome": "demo"}).json()
            assert not edited["goal"]["confirmed"] and edited["questions"] == []
            confirmed = api.post(base + "/confirm", json={"expected_version": 2}).json()
            assert confirmed["goal"]["confirmed"] and confirmed["version"] == 3
            body = {"request_id": "graph", "expected_version": 3}
            submitted = api.post(base + "/graph-drafts", json=body)
            assert submitted.status_code == 202
            run_id = submitted.json()["run_id"]
            with api.stream("GET", f"/api/runs/{run_id}/events") as stream:
                assert '"source_mode": "general"' in stream.read().decode()
            generated = api.get(f"/api/runs/{run_id}").json()["output"]["planning"]
            assert len(generated["graph"]["nodes"]) == 10 and generated["version"] == 4
            graph = generated["graph"]
            invalid = {"expected_version": 4, "nodes": graph["nodes"], "edges": [{"source": "n0", "target": "n0"}]}
            assert api.patch(base + "/graph", json=invalid).status_code == 422
            assert api.get(base).json()["version"] == 4
            graph["nodes"][0]["title"] = "审核后节点"
            edited = api.patch(base + "/graph", json={"expected_version": 4, "nodes": graph["nodes"], "edges": graph["edges"]}).json()
            assert edited["version"] == 5
            assert api.post(base + "/graph/publish", json={"expected_version": 4, "expected_revision": 0}).status_code == 409
            published = api.post(base + "/graph/publish", json={"expected_version": 5, "expected_revision": 0}).json()
            assert published["graph"]["status"] == "published" and published["graph"]["revision"] == 1
            assert api.get(base + "/nodes/n0/context").status_code == 200
            assert api.patch(base + "/graph", json={"expected_version": 6, "nodes": graph["nodes"], "edges": graph["edges"]}).status_code == 409
            assert api.patch(base, json={"expected_version": 6, "title": "overwrite"}).status_code == 409
        assert model.closed
        restored = Model([])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=restored):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            assert api.get(base).json() == published
            assert api.get(base + "/nodes/n0/context").json()["node"]["title"] == "审核后节点"
            assert not restored.calls


def test_planning_uses_shared_admission_and_rejects_false_document_grounding():
    repository, service = setup(confirmed=True)
    for goal_id in ("g2", "g3"):
        service.create_goal(goal_id, "学习")
        service.confirm_goal(goal_id)
    release, entered1, entered2 = threading.Event(), threading.Event(), threading.Event()
    def blocked(entered):
        def respond():
            entered.set()
            assert release.wait(5)
            return ModelResponse(content=graph_json())
        return respond
    loop = build_learning_loop(Model([blocked(entered1), blocked(entered2)]), repository, InMemoryLearningRepository())
    try:
        first = loop.submit(request(service))
        assert entered1.wait(5)
        try:
            loop.submit(request(service, key="other"))
        except RunAdmissionError as exc:
            assert exc.code == "session_busy"
        else:
            raise AssertionError("concurrent planning accepted")
        loop.submit(request(service, goal_id="g2"))
        assert entered2.wait(5)
        loop.cancel(first.run_id)
        try:
            loop.submit(request(service, goal_id="g3"))
        except RunAdmissionError as exc:
            assert exc.code == "capacity_exceeded"
        else:
            raise AssertionError("cancelled worker released its slot too early")
    finally:
        release.set()
        loop.close()
    assert service.current_graph("g1") is None
    service.create_goal("docs", "基于资料", document_ids=("d1",))
    service.confirm_goal("docs")
    model = Model([])
    loop = build_learning_loop(model, repository, InMemoryLearningRepository())
    try:
        try:
            loop.run(request(service, goal_id="docs"))
        except PlanningError as exc:
            assert exc.code == "grounding_unavailable"
        else:
            raise AssertionError("fake grounding accepted")
        assert not model.calls
    finally:
        loop.close()


def test_legacy_planning_migration_and_priority_keep_existing_semantics():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "old.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            with connection:
                connection.execute("create table planning_states(goal_id text primary key, goal_json text not null, graph_json text, clarification_round integer not null)")
                connection.execute("insert into planning_states values (?, ?, ?, ?)",
                    ("old", json.dumps({"title": "旧目标", "confirmed": True}), json.dumps({"goal_id": "old",
                        "nodes": [{"id": "a", "title": "旧节点", "estimated_minutes": 20}], "edges": [],
                        "status": "published", "revision": 1, "content_revision": 1}), 1))
        service = PlanningService(SQLitePlanningRepository(database))
        state = service.get_state("old")
        assert state.version == 0 and state.questions == ()
        assert state.graph.nodes[0].explanation == "" and state.graph.nodes[0].priority == 0
        graph = replace(state.graph, nodes=(GraphNode("a", "快速节点", 5, priority=0), GraphNode("b", "重点节点", 20, priority=5)))
        assert recommend_next_action(graph=graph, mastery_by_node={}).node_id == "b"
        assert recommend_next_action(graph=graph, mastery_by_node={}, recent_wrong_node_ids=("a",)).node_id == "a"
        assert recommend_next_action(graph=graph, mastery_by_node={"b": MasteryState.PROFICIENT}).node_id == "a"
        assert asdict(graph.nodes[1])["priority"] == 5
