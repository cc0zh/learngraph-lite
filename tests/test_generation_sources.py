from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import Budget, ModelResponse, ToolCall
from learngraph_lite.application.agent import RunRequest
from learngraph_lite.application.documents import DocumentService, InMemoryDocumentRepository
from learngraph_lite.application.exercise_generation import GenerateExercise
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningError, PlanningService
from learngraph_lite.bootstrap import build_learning_loop, create_real_app
from learngraph_lite.domain.learning import GraphNode, GraphValidationError
from learngraph_lite.domain.learning.proposals import GraphOperation, GraphOperationKind, apply_operations
from learngraph_lite.infrastructure import SQLiteDocumentRepository, SQLiteLearningRepository, SQLitePlanningRepository


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        response = next(self.responses)
        return response() if callable(response) else response

    def close(self):
        pass


def graph(ids=("C1",)):
    return ModelResponse(content=json.dumps({"nodes": [{"id": "n", "title": "RAG 资料学习",
        "explanation": "从资料理解检索", "learning_outcome": "RAG 引用定位", "estimated_minutes": 20,
        "priority": 1, "citation_ids": list(ids)}], "edges": []}, ensure_ascii=False))


def exercise(ids=("C1",), prompt="RAG 片段如何定位？", explanation="PRIVATE-EXPLANATION-42"):
    return ModelResponse(content=json.dumps({"exercises": [{"prompt": prompt,
        "options": [{"id": "a", "text": "丢弃偏移"}, {"id": "b", "text": "保留偏移"}],
        "correct_option_id": "b", "explanation": explanation, "citation_ids": list(ids)}]}, ensure_ascii=False))


def seed(database=None, published=False, bound=True):
    planning = SQLitePlanningRepository(database) if database else InMemoryPlanningRepository()
    learning = SQLiteLearningRepository(database) if database else InMemoryLearningRepository()
    documents = SQLiteDocumentRepository(database) if database else InMemoryDocumentRepository()
    service = PlanningService(planning)
    service.create_goal("g", "RAG", desired_outcome="引用定位", current_level="Python", time_budget_minutes=100)
    service.confirm_goal("g")
    if published:
        service.save_graph_draft("g", (GraphNode("n", "RAG 资料学习", 20),), ())
        LearningService(learning).start_goal(service.publish_graph("g", 0))
    docs = DocumentService(documents)
    docs.upload_text("a", "a", "RAG alpha 原文保留偏移与引用定位。")
    docs.upload_text("b", "b", "beta 回答专用原文。")
    docs.upload_text("hidden", "hidden", "RAG 隐藏资料不得检索。")
    if bound:
        for document_id in ("a", "b"):
            docs.bind_goal("g", document_id)
            if published:
                docs.bind_node("g", "n", document_id)
    return planning, learning, documents, service


def request(service, mode="graph", key="r"):
    return RunRequest("s", "生成", key, goal_id="g", node_id=None if mode == "graph" else "n", mode=mode,
                      task_ref="goal:g" if mode == "graph" else None,
                      planning_version=service.get_state("g").version if mode == "graph" else None,
                      graph_node_count=1)


def public(value):
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    assert "correct_option_id" not in encoded and "PRIVATE-EXPLANATION-42" not in encoded


def test_graph_grounding_repair_bounds_sqlite_publish_and_edit_provenance():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning, learning, documents, service = seed(database)
        docs = DocumentService(documents)
        for index in range(7):
            document_id = f"extra{index}"
            docs.upload_text(document_id, document_id, "RAG " + "原文" * 450)
            docs.bind_goal("g", document_id)
        model = Model([graph(("C99",)), graph()])
        loop = build_learning_loop(model, planning, learning, documents)
        try:
            budget = Budget()
            result = loop.run(request(service), budget)
            assert result.status == "completed", result.error
            assert budget.model_calls == 2
            first = json.loads(model.calls[0][0][1].content)
            repaired = json.loads(model.calls[1][0][1].content)
            assert first["sources"] == repaired["sources"] and len(first["sources"]) == 5
            assert sum(len(item["excerpt"]) for item in first["sources"]) <= 1600
            assert all(item["document_id"] != "hidden" for item in first["sources"])
            assert "RAG" in first["sources"][0]["excerpt"]
            saved = SQLitePlanningRepository(database).get("g").graph
            assert saved.source_mode == "documents" and saved.nodes[0].citation_ids == ("C1",)
            assert saved.citation_map == result.output["planning"]["graph"]["citation_map"]
            published = service.publish_graph("g", 0)
            assert published.citation_map == saved.citation_map and published.source_mode == "documents"
            proposal = apply_operations(published, (GraphOperation(GraphOperationKind.UPDATE_NODE,
                                        node_id="n", title="人工改名"),), validate=True)
            assert proposal.source_mode == "edited" and proposal.citation_map == saved.citation_map
            for invalid in (replace(saved.nodes[0], title="未知 [C99]"),
                            replace(saved.nodes[0], citation_ids=("C99",)),
                            replace(saved.nodes[0], citation_ids=("C1", "C1"))):
                try:
                    service.save_graph_draft("g", (invalid,), (), allow_published=True)
                except PlanningError as exc:
                    assert exc.code == "invalid_graph_citations"
                else:
                    raise AssertionError("invalid manual citation was saved")
                assert service.current_graph("g") == published
                try:
                    apply_operations(published, (GraphOperation(GraphOperationKind.ADD_NODE,
                                     node=replace(invalid, id="new")),), validate=True)
                except GraphValidationError:
                    pass
                else:
                    raise AssertionError("invalid proposal citation was accepted")
            # Legacy helper changes draft state; the original source remains locatable.
            edited = service.update_node("g", "n", title="人工改名")
            assert edited.source_mode == "edited" and edited.nodes[0].citation_ids == ("C1",)
            assert edited.citation_map == saved.citation_map
        finally:
            loop.close()


def test_direct_and_tool_grounding_share_gateway_keep_answer_and_question_c1_separate():
    for mode in ("exercise", "teaching"):
        planning, learning, documents, service = seed(published=True)
        responses = [exercise(("C99",)), exercise()]
        if mode == "teaching":
            responses = [ModelResponse(tool_calls=(ToolCall("search", "search_documents", '{"query":"beta"}'),)),
                         ModelResponse(tool_calls=(ToolCall("create", "create_exercise", "{}"),))] + responses + [
                         ModelResponse(content="资料回答 [C1]；请按题目自己的来源表核查练习。")]
        model = Model(responses)
        loop = build_learning_loop(model, planning, learning, documents)
        try:
            budget = Budget()
            result = loop.run(request(service, mode), budget)
            assert result.status == "completed", result.error
            assert budget.model_calls == (5 if mode == "teaching" else 2)
            question = result.output["exercises"][0]
            assert question["source_mode"] == result.output["source_mode"] == "documents"
            assert question["citation_map"]["C1"]["document_id"] == "a"
            generation = [messages for messages, tools in model.calls if not tools]
            source_data = json.loads(generation[0][1].content)["sources"]
            assert "alpha 原文" in source_data[0]["excerpt"]
            assert source_data == json.loads(generation[1][1].content)["sources"]
            if mode == "teaching":
                assert result.output["citation_map"]["C1"]["document_id"] == "b"
                assert result.output["unverified_citation_ids"] == []
                public([message.content for message in model.calls[-1][0] if message.role == "tool"])
            else:
                assert "citation_map" not in result.output
            public(result.output)
            public([event.payload for event in loop.events(result.run_id)])
        finally:
            loop.close()


def test_empty_retrieval_and_general_false_citations_never_save():
    for mode in ("graph", "exercise"):
        for empty in (True, False):
            planning, learning, documents, service = seed(published=mode == "exercise", bound=False)
            if empty:
                docs = DocumentService(documents)
                docs.upload_text("unrelated", "unrelated", "zzzz isolated")
                docs.bind_goal("g", "unrelated")
                if mode == "exercise":
                    docs.bind_node("g", "n", "unrelated")
            invalid = graph() if mode == "graph" else exercise((), prompt="伪造 [C1]")
            model = Model([] if empty else [invalid, invalid])
            loop = build_learning_loop(model, planning, learning, documents)
            try:
                result = loop.run(request(service, mode))
                assert result.status == "failed", result.error
                assert len(model.calls) == (0 if empty else 2)
                if empty:
                    assert "没有召回依据" in result.error
                assert not learning.get("g").exercises if mode == "exercise" else service.current_graph("g") is None
            finally:
                loop.close()


def test_changed_bindings_or_same_version_content_during_generation_reject_commit():
    for mode in ("graph", "exercise"):
        for mutation in ("unbind", "overwrite", "bind_during_general"):
            general = mutation == "bind_during_general"
            planning, learning, documents, service = seed(published=mode == "exercise", bound=not general)
            docs = DocumentService(documents)

            def change():
                if mutation == "unbind":
                    if mode == "graph":
                        docs.unbind_goal("g", "a")
                    else:
                        docs.unbind_node("g", "n", "a")
                elif mutation == "overwrite":
                    docs.upload_text("a", "a", "RAG 同 revision 不同原文。")
                else:
                    docs.bind_goal("g", "a")
                    if mode == "exercise":
                        docs.bind_node("g", "n", "a")
                return graph(() if general else ("C1",)) if mode == "graph" else exercise(() if general else ("C1",))

            model = Model([change])
            loop = build_learning_loop(model, planning, learning, documents)
            try:
                result = loop.run(request(service, mode))
                assert result.status == "failed", result.error
                assert len(model.calls) == 1
                assert not learning.get("g").exercises if mode == "exercise" else service.current_graph("g") is None
            finally:
                loop.close()


def test_http_artifact_scopes_sse_reopen_and_removed_source_degrade():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        _, _, documents, _ = seed(database)
        model = Model([graph(), exercise(), exercise(prompt="另一题如何引用？")])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            generated = api.post("/api/goals/g/graph-drafts", json={"request_id": "graph", "expected_version": 1, "node_count": 1})
            assert generated.status_code == 202, generated.text
            run_url = "/api/runs/" + generated.json()["run_id"]
            assert "citation_map" in api.get(run_url + "/events").text
            completed = api.get(run_url).json()
            assert completed["status"] == "completed", completed
            version = completed["output"]["planning"]["version"]
            citation_url = "/api/goals/g/graph/citations/C1"
            assert "alpha 原文" in api.get(citation_url, params={"version": version}).json()["text"]
            published = api.post("/api/goals/g/graph/publish", json={"expected_version": version, "expected_revision": 0})
            assert published.status_code == 200, published.text
            assert api.get(citation_url, params={"version": version}).status_code == 409
            version = published.json()["version"]
            assert api.get(citation_url, params={"version": version}).status_code == 200
            DocumentService(documents).bind_node("g", "n", "a")
            urls = []
            for index in range(2):
                submitted = api.post("/api/goals/g/nodes/n/exercises", json={"session_id": "s", "request_id": f"e{index}"})
                assert submitted.status_code == 202
                run_url = "/api/runs/" + submitted.json()["run_id"]
                public(api.get(run_url + "/events").text)
                result = api.get(run_url).json()
                assert result["status"] == "completed", result
                question = result["output"]["exercises"][0]
                question_url = "/api/goals/g/exercises/" + question["id"]
                assert api.get(question_url).json() == question
                assert api.get(question_url + "/citations/C1").status_code == 200
                assert api.get(question_url + "/citations/C99").status_code == 404
                urls.append(question_url)
            with patch.object(PlanningService, "get_state", autospec=True,
                              side_effect=lambda current, goal_id: current._repository.get(goal_id)) as read:
                snapshot = api.get("/api/goals/g/graph").json()
                assert snapshot["graph"]["source_mode"] == "documents" and snapshot["version"] == version
                assert read.call_count == 1

        # Immutable questions survive a factory/repository reopen without any model call.
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=Model([])):
            reopened = create_real_app(database=database)
        with TestClient(reopened, base_url="http://localhost") as api:
            assert api.get(urls[0] + "/citations/C1").status_code == 200
            documents.delete_document("a")
            for url in urls:
                question = api.get(url).json()
                assert question["citation_map"]["C1"]["status"] == "unavailable"
                assert question["unverified_citation_ids"] == ["C1"]
                assert api.get(url + "/citations/C1").status_code == 409
                public(question)
            assert api.get(citation_url, params={"version": version}).status_code == 409
            assert api.get("/api/goals/g/graph").json()["graph"]["citation_map"]["C1"]["status"] == "unavailable"


def test_legacy_exercise_schema_defaults_and_idempotent_sources_after_reopen():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("""create table learning_exercises (
                goal_id text, exercise_id text, node_id text, graph_content_revision integer,
                prompt text, options_json text, correct_option_id text, explanation text,
                normalized_hash text, primary key(goal_id, exercise_id))""")
            connection.commit()
        planning, learning, documents, service = seed(database, published=True)
        model = Model([exercise()])
        loop = build_learning_loop(model, planning, learning, documents)
        try:
            result = loop.run(request(service, "exercise"))
            assert result.status == "completed", result.error
            question = result.output["exercises"][0]
            reopened = SQLiteLearningRepository(database)
            context = LearningContext(SQLitePlanningRepository(database), reopened, SQLiteDocumentRepository(database))
            generator = GenerateExercise(reopened, context.context, SQLiteDocumentRepository(database))
            saved = generator.get_exercise("g", question["id"])
            assert saved == question
            key, operation = next(iter(reopened.get("g").generation_operations.items()))
            assert generator._existing(reopened.get("g"), key, operation["fingerprint"])["exercises"][0] == saved
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("update learning_exercises set sources_json = '{}' where exercise_id = ?", (question["id"],))
                connection.commit()
            legacy = generator.get_exercise("g", question["id"])
            assert legacy["source_mode"] == "general" and legacy["citation_ids"] == () and legacy["citation_map"] == {}
        finally:
            loop.close()
