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
from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel
from learngraph_lite.infrastructure.run_persistence import SQLiteRunRepository


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


def test_confirm_merges_once_preserves_unchanged_draft_and_rolls_back_conflicts():
    with tempfile.TemporaryDirectory() as directory:
        for repository in (InMemoryPlanningRepository(), SQLitePlanningRepository(Path(directory) / "planning.db")):
            service = PlanningService(repository)
            service.create_goal("g", "学习音乐", document_ids=("d1",))
            with patch.object(repository, "mutate", wraps=repository.mutate) as mutate:
                goal = service.confirm_goal("g", 0, title="节奏入门", desired_outcome="解释节拍",
                    current_level="没有学过", time_budget_minutes=60, constraints="无需乐器",
                    skipped_fields=["time_budget_minutes"])
                assert mutate.call_count == 1
            assert goal.confirmed and goal.document_ids == ("d1",)
            assert goal.skipped_fields == () and service.get_state("g").version == 1
            graph = CandidateGraph.model_validate_json(graph_json()).graph()
            service.save_graph_draft("g", graph.nodes, graph.edges)
            previous = service.get_state("g")
            service.confirm_goal("g", previous.version)
            assert service.current_graph("g") == previous.graph
            service.confirm_goal("g", previous.version + 1, title="  节奏入门  ", desired_outcome="解释节拍")
            assert service.current_graph("g") == previous.graph
            before = service.get_state("g")
            for version, fields, code in ((before.version - 1, {"title": "过期编辑"}, "planning_conflict"),
                                          (before.version, {"title": ""}, None)):
                try:
                    service.confirm_goal("g", version, **fields)
                except ValueError as exc:
                    assert code is None or exc.code == code
                else:
                    raise AssertionError("invalid confirmation accepted")
                assert service.get_state("g") == before
            service.confirm_goal("g", before.version, constraints="每天练习", time_budget_minutes=None)
            edited = service.get_state("g")
            assert edited.version == before.version + 1 and edited.graph is None
            assert edited.goal.confirmed and edited.goal.time_budget_minutes is None
            service.save_graph_draft("g", graph.nodes, graph.edges)
            service.publish_graph("g", 0)
            published = service.get_state("g")
            try:
                service.confirm_goal("g", published.version, current_level="绕过发布限制")
            except PlanningError as exc:
                assert exc.code == "graph_published"
            else:
                raise AssertionError("published goal edit accepted")
            assert service.get_state("g") == published
            service.confirm_goal("g", published.version)  # Legacy reconfirmation never replaces the published graph.
            assert service.current_graph("g") == published.graph


def test_sqlite_concurrent_confirm_edits_have_one_atomic_winner():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "planning.db"
        service = PlanningService(SQLitePlanningRepository(database))
        service.create_goal("g", "学习")
        barrier = threading.Barrier(2)
        def confirm(title):
            barrier.wait(5)
            try:
                PlanningService(SQLitePlanningRepository(database)).confirm_goal("g", 0, title=title)
                return "confirmed"
            except PlanningError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(confirm, ("音乐", "绘画"))) == ["confirmed", "planning_conflict"]
        saved = service.get_state("g")
        assert saved.version == 1 and saved.goal.confirmed and saved.goal.title in {"音乐", "绘画"}


def test_confirm_http_optional_edits_skips_and_strict_validation():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "app.db"
        model = Model([])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            created = api.post("/api/goals", json={"title": "音乐", "skipped_fields": ["current_level"]}).json()
            base = f"/api/goals/{created['goal_id']}"
            assert created["goal"]["skipped_fields"] == ["current_level"]
            invalid_skips = [None, "current_level", ["title"], [True], [1], ["current_level", "current_level"],
                             [" current_level"], ["desired_outcome", "current_level", "time_budget_minutes", "title"]]
            for skipped in invalid_skips:
                payload = {"skipped_fields": skipped}
                assert api.post("/api/goals", json={"title": "无效", **payload}).status_code == 422
                assert api.patch(base, json={"expected_version": 0, **payload}).status_code == 422
                assert api.post(base + "/confirm", json={"expected_version": 0, **payload}).status_code == 422
            for payload in ({}, {"expected_version": "0"}, {"expected_version": True}, {"expected_version": -1},
                            {"expected_version": 0, "title": " "}, {"expected_version": 0, "current_level": 123},
                            {"expected_version": 0, "time_budget_minutes": "60"},
                            {"expected_version": 0, "time_budget_minutes": True},
                            {"expected_version": 0, "time_budget_minutes": 0},
                            {"expected_version": 0, "document_ids": []}, {"expected_version": 0, "confirmed": True},
                            {"expected_version": 0, "constraints": "x" * 2001}):
                assert api.post(base + "/confirm", json=payload).status_code == 422
            for name in ("title", "desired_outcome", "current_level", "constraints", "skipped_fields"):
                assert api.post(base + "/confirm", json={"expected_version": 0, name: None}).status_code == 422
            assert api.get(base).json() == created and not model.calls
            response = api.post(base + "/confirm", json={"expected_version": 0, "title": "节奏",
                "desired_outcome": "解释节拍", "current_level": "新手", "time_budget_minutes": 60,
                "constraints": "无需乐器", "skipped_fields": ["time_budget_minutes"]})
            assert response.status_code == 200, response.text
            confirmed = response.json()
            assert confirmed["version"] == 1 and confirmed["goal"]["confirmed"]
            assert confirmed["goal"]["skipped_fields"] == []
            assert confirmed["goal"]["current_level"] == "新手" and confirmed["questions"] == []
            assert api.post(base + "/confirm", json={"expected_version": 0, "title": "过期"}).status_code == 409
            assert api.get(base).json() == confirmed
            legacy = api.post(base + "/confirm", json={"expected_version": 1})
            assert legacy.status_code == 200 and legacy.json()["version"] == 2
            cleared = api.patch(base, json={"expected_version": 2, "skipped_fields": []}).json()
            assert cleared["goal"]["skipped_fields"] == [] and not cleared["goal"]["confirmed"]
            final = api.post(base + "/confirm", json={"expected_version": 3, "time_budget_minutes": None}).json()
            assert final["version"] == 4 and final["goal"]["time_budget_minutes"] is None
            # Filling an input clears its skip flag in create, PATCH and atomic confirm alike.
            filled = api.post("/api/goals", json={"title": "绘画", "desired_outcome": "解释色彩",
                "skipped_fields": ["desired_outcome", "current_level", "time_budget_minutes"]}).json()
            filled_base = f"/api/goals/{filled['goal_id']}"
            assert filled["goal"]["skipped_fields"] == ["current_level", "time_budget_minutes"]
            patched = api.patch(filled_base, json={"expected_version": 0, "current_level": "新手"}).json()
            assert patched["goal"]["skipped_fields"] == ["time_budget_minutes"]
            supplied = api.post(filled_base + "/confirm", json={"expected_version": 1, "time_budget_minutes": 120}).json()
            assert supplied["version"] == 2 and supplied["goal"]["skipped_fields"] == []
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=Model([])):
            restored = create_real_app(database=database)
        with TestClient(restored, base_url="http://localhost") as api:
            assert api.get(base).json() == final


def test_skips_avoid_clarification_and_prompt_marks_self_report_unverified():
    repository, service = setup()
    service.edit_goal("g1", 0, skipped_fields=["desired_outcome", "current_level", "time_budget_minutes"])
    model = Model([graph_json(), graph_json()])
    loop = build_learning_loop(model, repository, InMemoryLearningRepository())
    try:
        clarification = loop.run(request(service, "clarify"))
        assert clarification.status == "completed" and model.calls == []
        assert service.get_state("g1").clarification_round == 0
        service.confirm_goal("g1", 1)
        result = loop.run(request(service, key="missing"))
        assert result.status == "completed", result.error
        instruction, context = model.calls[0][0].content, json.loads(model.calls[0][1].content)
        assert context["goal"]["time_budget_minutes"] is None and context["planning_reference_minutes"] == 240
        assert context["goal"]["current_level"] == "" and len(context["goal"]["skipped_fields"]) == 3
        assert "缺失基础不能假设" in instruction and "不得当作已验证能力" in instruction
        assert "必要性" in instruction and "学习顺序" in instruction and "可观察" in instruction and "实践或验证" in instruction
        service.confirm_goal("g1", service.get_state("g1").version, current_level="我已精通")
        result = loop.run(request(service, key="reported"))
        assert result.status == "completed", result.error
        context = json.loads(model.calls[1][1].content)
        assert context["goal"]["current_level"] == "我已精通"
        assert any("用户自述" in item and "尚未验证" in item for item in context["goal"]["assumptions"])
        assert "current_level 仅为用户自述，未经验证" in model.calls[1][0].content
    finally:
        loop.close()


def test_feedback_requires_draft_and_fixture_changes_only_feedback_generation():
    repository, service = setup(confirmed=True)
    loop = build_learning_loop(BusinessFixtureModel(), repository, InMemoryLearningRepository())
    try:
        original = request(service)
        try:
            loop.run(replace(original, graph_feedback="太难，请增加基础"))
        except PlanningError as exc:
            assert exc.code == "graph_required"
        else:
            raise AssertionError("feedback accepted without graph")
        generated = loop.run(original)
        assert generated.status == "completed", generated.error
        before = service.current_graph("g1")
        assert before.nodes[0].title == "目标与边界" and before.nodes[0].estimated_minutes == 20
        result = loop.run(replace(request(service, key="feedback"), graph_feedback="太难，请增加基础"))
        assert result.status == "completed", result.error
        after = service.current_graph("g1")
        assert after.nodes[0].title == "基础练习：目标与边界" and after.nodes[0].estimated_minutes == 10
        assert after.status == GraphStatus.DRAFT and after.revision == after.content_revision == 0
        assert after.nodes[0].priority == 5 and after != before
    finally:
        loop.close()


def test_graph_feedback_http_context_persistence_retry_fingerprint_and_publish_restriction():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "app.db"
        model = Model([graph_json(), "{}", "{}"])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            created = api.post("/api/goals", json={"title": "音乐"}).json()
            base = f"/api/goals/{created['goal_id']}"
            api.post(base + "/confirm", json={"expected_version": 0})
            initial = {"request_id": "initial", "expected_version": 1, "node_count": 2}
            for invalid in (None, 123, True, "x" * 2001):
                assert api.post(base + "/graph-drafts", json={**initial, "feedback": invalid}).status_code == 422
            missing = api.post(base + "/graph-drafts", json={**initial, "feedback": "太难"})
            assert missing.status_code == 409 and missing.json()["error"]["code"] == "graph_required"
            assert model.calls == []
            submitted = api.post(base + "/graph-drafts", json=initial)
            assert submitted.status_code == 202
            run_id = submitted.json()["run_id"]
            api.get(f"/api/runs/{run_id}/events")
            draft = api.get(base).json()
            assert draft["version"] == 2 and draft["graph"]["status"] == "draft"
            body = {"request_id": "feedback", "expected_version": 2, "node_count": 2,
                    "feedback": "太难，请补基础并聚焦节奏练习"}
            submitted = api.post(base + "/graph-drafts", json=body)
            assert submitted.status_code == 202
            failed_id = submitted.json()["run_id"]
            api.get(f"/api/runs/{failed_id}/events")
            assert api.get(f"/api/runs/{failed_id}").json()["status"] == "failed"
            assert api.get(base).json() == draft
            for messages in model.calls[1:]:  # Initial attempt and its single schema repair share the context.
                context = json.loads(messages[1].content)
                assert context["feedback"] == body["feedback"] and context["current_graph"] == draft["graph"]
                assert "调整难度、范围、基础铺垫或重点" in messages[0].content
            assert api.post(base + "/graph-drafts", json=body).json()["run_id"] == failed_id
            conflict = api.post(base + "/graph-drafts", json={**body, "feedback": "另一条意见"})
            assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
        stored = {record.run_id: request for request, record, _ in SQLiteRunRepository(database).load()}
        assert stored[failed_id].graph_feedback == body["feedback"]
        restored_model = Model([graph_json()])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=restored_model):
            restored = create_real_app(database=database)
        with TestClient(restored, base_url="http://localhost") as api:
            assert api.get(base).json() == draft
            retry = {**body, "request_id": "retry", "retry_of_run_id": failed_id}
            rejected = api.post(base + "/graph-drafts", json={**retry, "feedback": "不同反馈"})
            assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "invalid_retry"
            assert not restored_model.calls
            submitted = api.post(base + "/graph-drafts", json=retry)
            assert submitted.status_code == 202, submitted.text
            retry_id = submitted.json()["run_id"]
            api.get(f"/api/runs/{retry_id}/events")
            result = api.get(f"/api/runs/{retry_id}").json()
            assert result["status"] == "completed" and result["root_task_id"] == failed_id
            saved = result["output"]["planning"]
            assert saved["version"] == 3 and saved["graph"]["status"] == "draft"
            assert saved["graph"]["revision"] == saved["graph"]["content_revision"] == 0
            context = json.loads(restored_model.calls[0][1].content)
            assert context["feedback"] == body["feedback"] and context["current_graph"] == draft["graph"]
            stale = api.post(base + "/graph-drafts", json={**body, "request_id": "stale"})
            assert stale.status_code == 409 and stale.json()["error"]["code"] == "planning_conflict"
            published = api.post(base + "/graph/publish", json={"expected_version": 3, "expected_revision": 0}).json()
            blocked = api.post(base + "/graph-drafts", json={**body, "request_id": "published", "expected_version": 4})
            assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "graph_published"
            blocked = api.post(base + "/confirm", json={"expected_version": 4, "title": "绕过发布"})
            assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "graph_published"
            assert api.get(base).json() == published and len(restored_model.calls) == 1
        stored = {record.run_id: request for request, record, _ in SQLiteRunRepository(database).load()}
        assert stored[retry_id].graph_feedback == body["feedback"]
