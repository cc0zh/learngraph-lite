from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import Budget, ModelResponse, ToolCall
from learngraph_lite.agent_core.budget import BudgetExceeded
from learngraph_lite.agent_core.gateway import BudgetedModelGateway
from learngraph_lite.agent_core.tools import ToolError
from learngraph_lite.application.agent import RunRequest, TERMINAL_STATUSES
from learngraph_lite.application.documents import DocumentService, InMemoryDocumentRepository
from learngraph_lite.application.document_agent import DocumentTurn
from learngraph_lite.application.exercise_generation import GenerateExercise
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.lesson_generation import GenerateLesson
from learngraph_lite.application.lessons import InMemoryLessonRepository, LessonState
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.application.proposal_generation import GenerateProposal, proposal_operation_key
from learngraph_lite.application.proposals import GraphProposalService, InMemoryProposalCoordinator, InMemoryProposalRepository, ProposalError
from learngraph_lite.bootstrap import build_learning_loop, create_business_fixture_app
from learngraph_lite.domain.lessons import LessonPackage
from learngraph_lite.infrastructure.persistence import SQLiteLearningRepository, SQLiteLessonRepository, SQLitePlanningRepository
from learngraph_lite.infrastructure.proposal_persistence import SQLiteProposalRepository
from learngraph_lite.infrastructure.run_persistence import SQLiteRunRepository
from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel
from learngraph_lite.presentation.http import create_app


def seed(database=None):
    planning = SQLitePlanningRepository(database) if database else InMemoryPlanningRepository()
    learning = SQLiteLearningRepository(database) if database else InMemoryLearningRepository()
    service = PlanningService(planning)
    service.create_goal("g1", "学习 RAG", desired_outcome="demo", current_level="Python", time_budget_minutes=1200)
    service.confirm_goal("g1")
    graph = candidate_rag_graph("g1")
    service.save_graph_draft("g1", graph.nodes, graph.edges)
    LearningService(learning).start_goal(service.publish_graph("g1", 0))
    if database:
        repository = SQLiteProposalRepository(database)
        coordinator = repository
    else:
        repository = InMemoryProposalRepository()
        coordinator = InMemoryProposalCoordinator(repository, planning, learning)
    return planning, learning, GraphProposalService(repository, coordinator)


def test_add_node_proposal_create_list_get_accept_public_projection_is_json_compatible():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "add-node.sqlite3"
        seed(database)
        with TestClient(create_business_fixture_app(database=database), base_url="http://localhost") as api:
            response = api.post("/api/goals/g1/graph-proposals", json={"request_id": "add-node",
                "base_revision": 1, "rationale": "补充验证节点", "operations": [{"kind": "add_node",
                    "node": {"id": "extra", "title": "验证", "estimated_minutes": 5}}]})
            assert response.status_code == 201, response.text
            proposal = response.json()
            assert proposal["operations"][0]["node"]["citation_ids"] == []
            assert api.get("/api/goals/g1/graph-proposals").json() == {"proposals": [proposal]}
            assert api.get(f"/api/goals/g1/graph-proposals/{proposal['id']}").json() == proposal
            accepted = api.post(f"/api/goals/g1/graph-proposals/{proposal['id']}/decision",
                                json={"decision": "accept", "expected_revision": 1})
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["proposal"]["status"] == "accepted"
            assert any(node["id"] == "extra" for node in accepted.json()["planning"]["graph"]["nodes"])
            assert api.get("/api/goals/g1/nodes/extra/context").status_code == 200


def test_teaching_generators_cannot_switch_revision_between_scope_check_and_generate():
    for name, generator_type, inputs in (
        ("create_exercise", GenerateExercise, {"count": 1, "purpose": "practice"}),
        ("create_lesson", GenerateLesson, {"purpose": "lesson", "exercise_ids": []}),
    ):
        planning, learning, proposals = seed()
        lessons = InMemoryLessonRepository()
        context = LearningContext(planning, learning, lessons=lessons, proposals=proposals)
        control = Budget()
        prepared = context.prepare(BudgetedModelGateway(BusinessFixtureModel(), control),
            RunRequest("scope-race", "生成", "one", mode="teaching", goal_id="g1", node_id="chunking"), "root")
        original = generator_type.generate

        def advance_then_generate(generator, *positional, **keywords):
            proposal = proposals.create("g1", "advance", {**args(), "operations": [
                {"kind": "update_node", "node_id": "chunking", "title": "新内容版本"}]})
            proposals.decide("g1", proposal["id"], "accept", 1)
            return original(generator, *positional, **keywords)

        with patch.object(generator_type, "generate", advance_then_generate):
            try:
                prepared.runner._tools.get(name).execute(inputs)
            except ToolError as exc:
                assert "stale_run_context" in str(exc)
            else:
                raise AssertionError("teaching generator silently switched to a new graph")
        assert control.model_calls == 0 and learning.get("g1").exercises == {}
        assert lessons.state("g1").packages == {}


def args(**update):
    return {"base_revision": 1, "rationale": "改进路线", "operations": [
        {"kind": "update_node", "node_id": "chunking", **(update or {"title": "分块原理"})}]}


def error(code, call):
    try:
        call()
    except ProposalError as exc:
        assert exc.code == code, (exc.code, str(exc))
    else:
        raise AssertionError(f"expected {code}")


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


def candidate(**update):
    value = args(**update)
    value.pop("base_revision")
    return ModelResponse(content=json.dumps(value, ensure_ascii=False), usage={"output_tokens": 5})


def assert_public(value):
    text = json.dumps(value, default=str, ensure_ascii=False)
    for private in ("correct_option_id", "PRIVATE-ANSWER", "decision_revision", "fingerprint", "protocol_messages"):
        assert private not in text


def test_strict_operations_fields_limits_scope_cycles_and_citations():
    planning, learning, proposals = seed()
    original = deepcopy(learning.get("g1"))
    invalid_operations = [
        {"kind": "delete_node", "node_id": "chunking"},
        {"kind": "update_node", "node_id": "chunking"},
        {"kind": "update_node", "node_id": "chunking", "title": None},
        {"kind": "update_node", "node_id": "chunking", "mastery": "proficient"},
        {"kind": "update_node", "node_id": "chunking", "priority": True},
        {"kind": "update_node", "node_id": "chunking", "estimated_minutes": 0},
        {"kind": "update_node", "node_id": "chunking", "title": "x" * 2001},
        {"kind": "update_node", "node_id": "missing", "title": "x"},
        {"kind": "add_node", "node": {"id": "chunking", "title": "duplicate", "estimated_minutes": 5}},
        *[{"kind": "add_node", "node": {"id": unsafe, "title": "unsafe route", "estimated_minutes": 5}}
          for unsafe in ("..", ".", "node/../../other", "node?query", "node#fragment", "%2e%2e", "node\\path")],
        {"kind": "add_node", "node": {"id": "new", "title": "x [C1]", "estimated_minutes": 5, "citation_ids": ["C1"]}},
        {"kind": "add_dependency", "edge": {"source": "citations", "target": "rag-goal"}},
        {"kind": "add_dependency", "edge": {"source": "rag-goal", "target": "rag-goal"}},
        {"kind": "add_dependency", "edge": {"source": "unknown", "target": "chunking"}},
        {"kind": "remove_dependency", "edge": {"source": "rag-goal", "target": "chunking", "kind": "other"}},
        {"kind": "add_node", "node": {"id": "new", "title": "new", "estimated_minutes": 2}, "node_id": "chunking"},
    ]
    for index, operation in enumerate(invalid_operations):
        error("invalid_proposal", lambda: proposals.create("g1", str(index), {**args(), "operations": [operation]}))
    for fields in ({"goal_id": "g2"}, {"base_revision": True}, {"rationale": " "}, {"operations": []},
                   {"operations": args()["operations"] * 61}):
        error("invalid_proposal", lambda: proposals.create("g1", "invalid", {**args(), **fields}))
    too_many = [{"kind": "add_node", "node": {"id": f"new{i}", "title": "x", "estimated_minutes": 5}}
                for i in range(23)]
    error("invalid_proposal", lambda: proposals.create("g1", "limit", {**args(), "operations": too_many}))
    assert proposals.list_proposals("g1") == {"proposals": []}
    assert learning.get("g1") == original
    error("goal_not_found", lambda: proposals.create("g2", "missing", args()))


def test_pending_reject_accept_conflicted_and_decision_idempotency():
    planning, learning, proposals = seed()
    original_plan = planning.get("g1")
    original_learning = deepcopy(learning.get("g1"))
    proposal = proposals.create("g1", "request:one", args())
    assert proposal["status"] == "pending"
    assert proposals.create("g1", "request:one", args())["id"] == proposal["id"]
    error("operation_conflict", lambda: proposals.create("g1", "request:one", args(title="other")))
    assert planning.get("g1") == original_plan and learning.get("g1") == original_learning
    rejected = proposals.decide("g1", proposal["id"], "reject", 1)
    assert not rejected["learning_reset"] and rejected["proposal"]["status"] == "rejected"
    assert proposals.decide("g1", proposal["id"], "reject", 1) == rejected
    error("decision_conflict", lambda: proposals.decide("g1", proposal["id"], "accept", 1))
    assert planning.get("g1") == original_plan and learning.get("g1") == original_learning
    accepted = proposals.create("g1", "two", args(explanation="解释", learning_outcome="掌握分块", priority=3, estimated_minutes=20))
    other = proposals.create("g1", "three", args())
    result = proposals.decide("g1", accepted["id"], "accept", 1)
    assert result["learning_reset"] and result["proposal"]["status"] == "accepted"
    assert result["planning"]["graph"]["revision"] == 2
    assert planning.get("g1").graph == learning.get("g1").graph
    assert planning.get("g1").version == original_plan.version + 1
    assert proposals.decide("g1", accepted["id"], "accept", 1) == result
    error("decision_conflict", lambda: proposals.decide("g1", accepted["id"], "reject", 1))
    error("revision_conflict", lambda: proposals.decide("g1", other["id"], "accept", 1))
    assert proposals.get_proposal("g1", other["id"])["status"] == "conflicted"
    error("proposal_not_found", lambda: proposals.get_proposal("g2", accepted["id"]))


def test_add_and_remove_dependencies_and_add_node_publish_atomically():
    planning, learning, proposals = seed()
    operations = [
        {"kind": "add_node", "node": {"id": "extra", "title": "扩展", "estimated_minutes": 15}},
        {"kind": "add_dependency", "edge": {"source": "chunking", "target": "extra"}},
        {"kind": "remove_dependency", "edge": {"source": "document-loading", "target": "chunking"}},
    ]
    proposal = proposals.create("g1", "operations", {**args(), "operations": operations})
    result = proposals.decide("g1", proposal["id"], "accept", 1)
    graph = planning.get("g1").graph
    assert graph.status == "published" and graph.content_revision == 2
    assert "extra" in {node.id for node in graph.nodes}
    assert ("chunking", "extra") in {(edge.source, edge.target) for edge in graph.edges}
    assert ("document-loading", "chunking") not in {(edge.source, edge.target) for edge in graph.edges}
    assert result["learning_reset"] and learning.get("g1").graph == graph


def test_stale_creation_and_expected_revision_save_conflict_on_reopen():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "proposal.sqlite3"
        planning, learning, proposals = seed(database)
        error("revision_conflict", lambda: proposals.create("g1", "old", {**args(), "base_revision": 0}))
        pending = proposals.create("g1", "current", args())
        error("revision_conflict", lambda: proposals.decide("g1", pending["id"], "reject", 0))
        repository = SQLiteProposalRepository(database)
        reopened = GraphProposalService(repository, repository)
        assert [p["status"] for p in reopened.list_proposals("g1")["proposals"]] == ["conflicted", "conflicted"]
        error("revision_conflict", lambda: reopened.create("g1", "old", {**args(), "base_revision": 0}))
        assert planning.get("g1").graph.revision == 1 and learning.get("g1").graph.revision == 1


def test_sqlite_atomic_accept_rollback_reopen_and_concurrent_decisions():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "atomic.sqlite3"
        planning, learning, proposals = seed(database)
        original_plan = planning.get("g1")
        original_learning = learning.get("g1")
        first = proposals.create("g1", "first", args())
        second = proposals.create("g1", "second", args(title="另一个标题"))
        repository = proposals._coordinator
        save = repository._learning._save

        def fail_after_write(connection, goal_id, state):
            save(connection, goal_id, state)
            raise RuntimeError("simulated storage failure")
        with patch.object(repository._learning, "_save", fail_after_write):
            try:
                proposals.decide("g1", first["id"], "accept", 1)
            except RuntimeError:
                pass
            else:
                raise AssertionError("failure was not injected")
        repository = SQLiteProposalRepository(database)
        reopened = GraphProposalService(repository, repository)
        assert planning.get("g1") == original_plan and learning.get("g1") == original_learning
        assert reopened.get_proposal("g1", first["id"])["status"] == "pending"
        barrier = Barrier(2)

        def decide(proposal):
            barrier.wait()
            try:
                return reopened.decide("g1", proposal["id"], "accept", 1)["proposal"]["status"]
            except ProposalError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(decide, (first, second)))
        assert sorted(results) == ["accepted", "revision_conflict"]
        assert planning.get("g1").graph.revision == 2 and learning.get("g1").graph == planning.get("g1").graph
        accepted = next(p for p in reopened.list_proposals("g1")["proposals"] if p["status"] == "accepted")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: reopened.decide("g1", accepted["id"], "accept", 1), range(2)))
        assert results[0] == results[1] and planning.get("g1").graph.revision == 2


def test_history_preserved_stats_recomputed_old_questions_and_lessons_read_only():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "history.sqlite3"
        planning, learning, proposals = seed(database)
        practice = LearningService(learning)
        for index in range(3):
            exercise = practice.create_fixture_exercise("g1", "chunking", f"e{index}", f"题目{index}")
            practice.submit_answer("g1", exercise.id, "b", f"a{index}")
        assert practice.mastery("g1", "chunking") == ("proficient", 3, 1.0)
        lesson_repository = SQLiteLessonRepository(database)
        package = LessonPackage("old-package", "g1", "chunking", 1, "旧教材", ())
        lesson_repository.save("g1", LessonState(packages={package.id: package}))
        before = learning.get("g1")
        metadata = proposals.create("g1", "metadata", args(priority=5, estimated_minutes=12))
        assert not proposals.decide("g1", metadata["id"], "accept", 1)["learning_reset"]
        assert practice.mastery("g1", "chunking") == ("proficient", 3, 1.0)
        semantic = proposals.create("g1", "semantic", {**args(title="新的学习定义"), "base_revision": 2})
        assert proposals.decide("g1", semantic["id"], "accept", 2)["learning_reset"]
        practice.ensure_goal(planning.get("g1").graph)
        state = SQLiteLearningRepository(database).get("g1")
        assert state.exercises == before.exercises and state.attempts == before.attempts
        assert practice.mastery("g1", "chunking") == ("unknown", 0, 0.0)
        context = LearningContext(planning, learning)
        exercises = GenerateExercise(learning, context.context)
        assert exercises.get_exercise("g1", "e0")["graph_content_revision"] == 1
        assert exercises.list_exercises("g1", "chunking")["exercises"] == []
        try:
            practice.submit_answer("g1", "e0", "b", "new-old-answer")
        except ValueError as exc:
            assert "stale" in str(exc)
        else:
            raise AssertionError("old question accepted answer")
        lessons = GenerateLesson(lesson_repository, learning, context.context)
        assert lessons.get_package("g1", "old-package")["outdated"]
        assert lesson_repository.state("g1").packages["old-package"] == package
        new = practice.create_fixture_exercise("g1", "chunking", "new", "新版题目")
        practice.submit_answer("g1", new.id, "b", "new-attempt")
        assert practice.mastery("g1", "chunking") == ("learning", 1, 1.0)


def test_missing_or_stale_learning_is_not_implicitly_reset_on_accept_or_context():
    planning, learning, proposals = seed()
    proposal = proposals.create("g1", "one", args())
    original = learning.get("g1")
    learning.save("g1", replace(original, graph=replace(original.graph, revision=0)))
    error("stale_learning_graph", lambda: proposals.decide("g1", proposal["id"], "accept", 1))
    LearningService(learning).ensure_goal(planning.get("g1").graph)
    assert learning.get("g1").graph.revision == 0
    try:
        LearningContext(planning, learning).context("g1", "chunking")
    except ValueError as exc:
        assert exc.code == "stale_learning_graph"
    else:
        raise AssertionError("context silently reset progress")
    learning._states.pop("g1")
    error("stale_learning_graph", lambda: proposals.decide("g1", proposal["id"], "accept", 1))
    assert proposals.get_proposal("g1", proposal["id"])["status"] == "pending"


def test_generation_one_repair_budget_and_stable_root_payload_conflict():
    planning, learning, proposals = seed()
    generator = GenerateProposal(proposals)
    model = ScriptedModel([ModelResponse(content='{"operations":[],"rationale":"x"}'), candidate(), candidate(title="新任务")])
    budget = Budget()
    gateway = BudgetedModelGateway(model, budget)
    result = generator.generate("g1", "root", {"purpose": "改进"}, gateway)
    assert budget.model_calls == 2 and len(model.calls) == 2
    assert "CandidateProposal" in model.calls[0][0][0].content
    assert "context" in json.loads(model.calls[0][0][1].content)
    assert generator.generate("g1", "root", {"purpose": "改进"}, gateway) == result
    assert len(model.calls) == 2
    error("operation_conflict", lambda: generator.generate("g1", "root", {"purpose": "不同"}, gateway))
    another = generator.generate("g1", "new-root", {"purpose": "改进"}, gateway)
    assert another["proposal"]["id"] != result["proposal"]["id"]
    assert planning.get("g1").graph.revision == 1 and learning.get("g1").graph.revision == 1
    assert_public(result)
    for max_calls in (1, 6):
        _, _, failed = seed()
        model = ScriptedModel([ModelResponse(content="not JSON"), ModelResponse(content="not JSON")])
        control = Budget(max_model_calls=max_calls)
        try:
            GenerateProposal(failed).generate("g1", "root", {}, BudgetedModelGateway(model, control))
        except Exception as exc:
            assert "budget" in str(exc) if max_calls == 1 else getattr(exc, "code", None) == "invalid_proposal_candidate"
        else:
            raise AssertionError("invalid generation succeeded")
        assert len(model.calls) == min(2, max_calls) and failed.list_proposals("g1")["proposals"] == []


def test_generation_models_are_outside_sqlite_transaction_and_stale_base_is_persisted():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "outside.sqlite3"
        planning, learning, proposals = seed(database)
        class ConcurrentModel:
            def complete(self, messages, tools):
                winner = proposals.create("g1", "other", args(priority=3))
                proposals.decide("g1", winner["id"], "accept", 1)
                return candidate()
        error("revision_conflict", lambda: GenerateProposal(proposals).generate(
            "g1", "root", {}, BudgetedModelGateway(ConcurrentModel(), Budget())))
        statuses = [item["status"] for item in proposals.list_proposals("g1")["proposals"]]
        assert statuses == ["accepted", "conflicted"]
        assert planning.get("g1").graph.revision == 2 and learning.get("g1").graph.revision == 2


def test_teaching_tool_only_bound_scope_root_dedup_and_retry_after_saved_write():
    planning, learning, proposals = seed()
    context = LearningContext(planning, learning, proposals=proposals)
    request = RunRequest("s1", "调整路线", "one", mode="teaching", goal_id="g1", node_id="chunking")
    gateway = BudgetedModelGateway(ScriptedModel([]), Budget())
    teaching = context.prepare(gateway, request, "root")
    tool = teaching.runner._tools.get("propose_graph_change")
    assert tool is not None and "goal_id" not in tool.input_schema["properties"]
    for mode in ("runner", "explanation"):
        prepared = context.prepare(gateway, replace(request, mode=mode), "root")
        assert prepared.runner._tools.get("propose_graph_change") is None
    result = tool.execute(args())
    assert tool.execute(args()) == result
    cancelled = context.prepare(gateway, request, "cancelled-root").runner._tools.get("propose_graph_change")
    gateway.budget.cancelled = True
    try:
        cancelled.execute(args())
    except BudgetExceeded:
        pass
    else:
        raise AssertionError("cancelled tool saved a proposal")
    gateway.budget.cancelled = False
    assert len(proposals.list_proposals("g1")["proposals"]) == 1
    try:
        tool.execute({**args(), "goal_id": "g2"})
    except ToolError:
        pass
    else:
        raise AssertionError("client scope allowed")
    try:
        tool.execute(args(title="different"))
    except ToolError as exc:
        assert "operation_conflict" in str(exc)
    else:
        raise AssertionError("different tool payload overwritten")
    call = ModelResponse(tool_calls=(ToolCall("call", "propose_graph_change", json.dumps(args())),))
    model = ScriptedModel([call, RuntimeError("after saved proposal"), call, ModelResponse(content="等待用户审核"),
                           call, ModelResponse(content="新提案")])
    loop = build_learning_loop(model, planning, learning, proposals=proposals)
    try:
        first = loop.run(request)
        assert first.status == "failed"
        saved = proposals.list_proposals("g1")["proposals"][-1]
        retry = loop.run(replace(request, idempotency_key="retry", retry_of_run_id=first.run_id))
        assert retry.status == "completed", retry.error
        assert retry.root_task_id == first.root_task_id and retry.output["proposal"]["id"] == saved["id"]
        fresh = loop.run(replace(request, idempotency_key="fresh"))
        assert fresh.status == "completed" and fresh.output["proposal"]["id"] != saved["id"]
        assert len(model.calls) == 6 and planning.get("g1").graph.revision == 1
        assert_public(retry.output)
        assert_public([event.payload for event in loop.events(retry.run_id)])
    finally:
        loop.close()


def test_http_contract_status_codes_generate_sse_and_public_dto():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "http.sqlite3"
        planning, learning, proposals = seed(database)
        model = ScriptedModel([candidate(title="模型建议")])
        loop = build_learning_loop(model, planning, learning, runs=SQLiteRunRepository(database), proposals=proposals)
        app = create_app(loop, planning=PlanningService(planning), proposals=proposals)
        with TestClient(app, base_url="http://127.0.0.1", headers={"origin": "http://127.0.0.1"}) as client:
            path = "/api/goals/g1/graph-proposals"
            assert client.get(path).json() == {"proposals": []}
            response = client.post(path, json={"request_id": "one", **args()})
            assert response.status_code == 201, response.text
            proposal = response.json()
            assert set(proposal) == {"id", "goal_id", "base_revision", "operations", "rationale", "status"}
            assert client.get(f"{path}/{proposal['id']}").json() == proposal
            assert client.get(f"/api/goals/other/graph-proposals/{proposal['id']}").status_code == 404
            assert client.post(path, json={"request_id": "one", **args(title="different")}).status_code == 409
            assert client.post(path, json={"request_id": "bad", **args(), "decision": "accept"}).status_code == 422
            assert client.post(path, json={"request_id": "stale", **args(), "base_revision": 0}).status_code == 409
            generation = client.post(f"{path}/generate", json={"session_id": "proposal-session", "request_id": "gen", "purpose": "改进"})
            assert generation.status_code == 202, generation.text
            run_id = generation.json()["run_id"]
            assert generation.json()["mode"] == "proposal" and generation.json()["node_id"] is None
            cursor = 0
            while loop.get_run(run_id).status not in TERMINAL_STATUSES:
                events = loop.wait_events(run_id, cursor, 5)
                assert events
                cursor = events[-1].seq
            public = client.get(f"/api/runs/{run_id}").json()
            assert public["status"] == "completed", public
            generated = public["output"]["proposal"]
            assert generated["status"] == "pending" and planning.get("g1").graph.revision == 1
            sse = client.get(f"/api/runs/{run_id}/events").text
            assert "run.snapshot" in sse and generated["id"] in sse
            assert_public(public)
            assert_public(sse)
            result = client.post(f"{path}/{generated['id']}/decision", json={"decision": "accept", "expected_revision": 1})
            assert result.status_code == 200, result.text
            assert result.json()["learning_reset"] and result.json()["planning"]["graph"]["revision"] == 2
            assert client.post(f"{path}/{generated['id']}/decision", json={"decision": "accept", "expected_revision": 1}).json() == result.json()
            assert client.post(f"{path}/{generated['id']}/decision", json={"decision": "reject", "expected_revision": 1}).status_code == 409
            assert client.post(f"{path}/{proposal['id']}/decision", json={"decision": "accept", "expected_revision": 1}).status_code == 409
        repository = SQLiteProposalRepository(database)
        assert repository.get(generated["id"]).status == "accepted"
        recovered = build_learning_loop(ScriptedModel([]), planning, learning, runs=SQLiteRunRepository(database),
                                        proposals=GraphProposalService(repository, repository))
        try:
            assert recovered.get_run(run_id).output["proposal"]["id"] == generated["id"]
        finally:
            recovered.close()


def test_business_factory_assembles_proposal_routes_without_reading_environment_or_daily_database():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "fixture.sqlite3"
        seed(database)
        with TestClient(create_business_fixture_app(database=database), base_url="http://127.0.0.1") as client:
            response = client.get("/api/goals/g1/graph-proposals")
            assert response.status_code == 200 and response.json() == {"proposals": []}


def test_graph_citation_snapshot_is_not_new_source_authority_and_is_revalidated():
    planning, learning, proposals = seed()
    repository = InMemoryDocumentRepository()
    documents = DocumentService(repository)
    documents.upload_text("d1", "资料", "分块依赖完整资料原文。")
    documents.bind_goal("g1", "d1")
    turn = DocumentTurn(documents, "g1", None)
    source = turn.search({"query": "分块", "limit": 1})["sources"][0]
    graph = planning.get("g1").graph
    graph = replace(graph, citation_map={"C1": {key: value for key, value in source.items() if key != "excerpt"}})
    planning.mutate("g1", lambda state: setattr(state, "graph", graph))
    LearningService(learning).migrate_graph(graph)
    proposals = GraphProposalService(proposals._repository, proposals._coordinator, repository)
    operation = {"kind": "add_node", "node": {"id": "new", "title": "原文 [C1]", "estimated_minutes": 15,
                                                "citation_ids": ["C1"]}}
    for node in ({**operation["node"], "citation_ids": ["C2"]},
                 {**operation["node"], "citation_ids": ["C1", "C1"]},
                 {**operation["node"], "citation_ids": []}):
        error("invalid_proposal", lambda: proposals.create("g1", "bad-source", {
            **args(), "operations": [{"kind": "add_node", "node": node}]}))
    pending = proposals.create("g1", "valid-source", {**args(), "operations": [operation]})
    documents.unbind_goal("g1", "d1")
    error("stale_proposal_sources", lambda: proposals.decide("g1", pending["id"], "accept", 1))
    assert proposals.get_proposal("g1", pending["id"])["status"] == "pending"
    assert planning.get("g1").graph.revision == 1
    documents.bind_goal("g1", "d1")
    proposals.decide("g1", pending["id"], "accept", 1)
    published = planning.get("g1").graph
    assert published.citation_map == graph.citation_map and published.source_mode == "edited"
    documents.unbind_goal("g1", "d1")
    projection = LearningContext(planning, learning, repository).project_graph_sources(published)
    assert projection["citation_map"]["C1"]["status"] == "unavailable"
    assert projection["unverified_citation_ids"] == ["C1"]


def test_concurrent_duplicate_operations_have_one_durable_proposal_and_payload_conflict():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "dedup.sqlite3"
        _, _, proposals = seed(database)
        barrier = Barrier(2)

        def create(_):
            barrier.wait()
            repository = SQLiteProposalRepository(database)
            return GraphProposalService(repository, repository).create("g1", proposal_operation_key("root"), args())
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, range(2)))
        assert results[0] == results[1] and len(proposals.list_proposals("g1")["proposals"]) == 1
        error("operation_conflict", lambda: proposals.create("g1", proposal_operation_key("root"), args(priority=2)))


def test_historical_feedback_is_read_only_scoped_and_never_discloses_unanswered_answers():
    planning, learning, proposals = seed()
    practice = LearningService(learning)
    practice.create_fixture_exercise("g1", "chunking", "answered", "作答题目")
    practice.create_fixture_exercise("g1", "chunking", "unanswered", "未作答题目")
    practice.submit_answer("g1", "answered", "a", "first")
    last = practice.submit_answer("g1", "answered", "b", "second")
    proposal = proposals.create("g1", "change", args())
    proposals.decide("g1", proposal["id"], "accept", 1)
    context = LearningContext(planning, learning)
    before = deepcopy(learning.get("g1"))
    assert context.exercise_feedback("g1", "unanswered") == {"feedback": None}
    feedback = context.exercise_feedback("g1", "answered")["feedback"]
    assert feedback["attempt"]["id"] == last.id and feedback["correct_option_id"] == "b"
    loop = build_learning_loop(ScriptedModel([]), planning, learning)
    with TestClient(create_app(loop, learning_context=context), base_url="http://127.0.0.1") as client:
        assert client.get("/api/goals/g1/exercises/unanswered/feedback").json() == {"feedback": None}
        response = client.get("/api/goals/g1/exercises/answered/feedback")
        assert response.status_code == 200 and response.json()["feedback"]["attempt"]["id"] == last.id
        assert client.get("/api/goals/g2/exercises/answered/feedback").status_code == 404
        assert client.get("/api/goals/g1/exercises/missing/feedback").status_code == 404
    assert learning.get("g1") == before
    assert practice.mastery("g1", "chunking") == ("unknown", 0, 0.0)
