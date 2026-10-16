from __future__ import annotations

import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, TextMessage, ToolCall, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, PreparedRun, RunRequest
from learngraph_lite.application.document_agent import DocumentTurn
from learngraph_lite.application.documents import DocumentAccessError, DocumentService, InMemoryDocumentRepository
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.planning import PlanningService, candidate_rag_graph
from learngraph_lite.bootstrap import build_learning_loop, create_real_app
from learngraph_lite.domain.documents import chunk_document
from learngraph_lite.infrastructure import SQLiteDocumentRepository, SQLiteLearningRepository, SQLitePlanningRepository


def seed(database, goal_id="g1"):
    planning, learning = SQLitePlanningRepository(database), SQLiteLearningRepository(database)
    service = PlanningService(planning)
    service.create_goal(goal_id, "资料学习", desired_outcome="RAG", current_level="Python", time_budget_minutes=600)
    service.confirm_goal(goal_id)
    draft = candidate_rag_graph(goal_id)
    service.save_graph_draft(goal_id, draft.nodes, draft.edges)
    LearningService(learning).start_goal(service.publish_graph(goal_id, expected_revision=0))
    documents = SQLiteDocumentRepository(database)
    docs = DocumentService(documents)
    for suffix, text in (("a", "alpha 清洗原文。"), ("b", "beta 分块原文。")):
        document_id = goal_id + suffix
        docs.upload_text(document_id, suffix, text)
        docs.bind_goal(goal_id, document_id)
        docs.bind_node(goal_id, "document-loading", document_id)
    return planning, learning, documents


def request(goal_id="g1", key="r1"):
    return RunRequest(goal_id, "依据资料解释", key, goal_id=goal_id, node_id="document-loading")


def call(name, args, call_id):
    return ToolCall(call_id, name, json.dumps(args))


class ScriptedModel:
    def __init__(self, responses, *, with_skills=False):
        self.responses = iter(responses)
        self.transcripts = []
        self.closed = False
        self.with_skills = with_skills

    def complete(self, messages, tools):
        expected = {
            "get_learning_context", "get_next_action", "search_documents", "read_document_chunk",
        }
        if self.with_skills:
            expected.add("read_skill")
        assert {tool["function"]["name"] for tool in tools} == expected
        self.transcripts.append(messages)
        return next(self.responses)

    def close(self):
        self.closed = True


def test_sqlite_document_turn_repairs_arguments_and_reuses_numbered_sources():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        seed(database)
        # An unbound document must never become a source, even with an exact match.
        DocumentService(SQLiteDocumentRepository(database)).upload_text("hidden", "hidden", "alpha beta hidden")
        model = ScriptedModel([
            ModelResponse(tool_calls=(call("read_document_chunk", {"citation_id": "C1"}, "unknown"),
                                      call("search_documents", {"query": "alpha", "goal_id": "g2"}, "scope"))),
            ModelResponse(tool_calls=(call("search_documents", {"query": "alpha"}, "a"),
                                      call("search_documents", {"query": "beta"}, "b"))),
            ModelResponse(tool_calls=(call("search_documents", {"query": "alpha"}, "again"),
                                      call("read_document_chunk", {"citation_id": "C1"}, "read"))),
            ModelResponse(content="清洗 [C1]；分块 [C2]；未知 [C99]。"),
        ])
        # Reopen all repositories before entering the Agent loop.
        loop = build_learning_loop(model, SQLitePlanningRepository(database), SQLiteLearningRepository(database),
                                   SQLiteDocumentRepository(database))
        try:
            record = loop.run(request())
            assert record.status == "completed", record.error
            sources = record.output["citation_map"]
            assert list(sources) == ["C1", "C2"]
            assert [source["document_id"] for source in sources.values()] == ["g1a", "g1b"]
            assert all(source["status"] == "valid" and source["cited"] for source in sources.values())
            assert record.output["unverified_citation_ids"] == ["C99"]
            transcript = model.transcripts[-1]
            results = [json.loads(message.content) for message in transcript if message.role == "tool"]
            assert "source_not_found" in results[0]["error"]
            assert "invalid arguments" in results[1]["error"]
            assert results[2]["sources"] == results[4]["sources"]
            assert results[5]["text"] == "alpha 清洗原文。"
            assert [message.tool_call_id for message in transcript if message.role == "tool"] == [
                "unknown", "scope", "a", "b", "again", "read",
            ]
            terminal = loop.events(record.run_id)[-1]
            assert terminal.payload["output"] == record.output
            terminal.payload["output"]["citation_map"].clear()
            snapshot = loop.get_run(record.run_id)
            snapshot.output["citation_map"].clear()
            assert len(loop.get_run(record.run_id).output["citation_map"]) == 2
            assert len(loop.events(record.run_id)[-1].payload["output"]["citation_map"]) == 2
        finally:
            loop.close()


def test_no_binding_empty_search_and_strict_arguments_do_not_issue_sources():
    with tempfile.TemporaryDirectory() as directory:
        planning, learning, documents = seed(Path(directory) / "test.sqlite3")
        docs = DocumentService(documents)
        for bound in (True, False):
            if not bound:
                docs.unbind_node("g1", "document-loading", "g1a")
                docs.unbind_goal("g1", "g1b")
            model = ScriptedModel([
                ModelResponse(tool_calls=(call("search_documents", {"query": "zzzz"}, "search"),
                                          call("search_documents", {"query": " ", "limit": "5"}, "bad"))),
                ModelResponse(content="资料不足。非基于上传资料：可先整理文本。"),
            ])
            loop = build_learning_loop(model, planning, learning, documents)
            try:
                record = loop.run(request())
                assert record.status == "completed"
                assert record.output == {"citation_map": {}, "unverified_citation_ids": []}
                results = [json.loads(message.content) for message in model.transcripts[-1] if message.role == "tool"]
                if bound:
                    assert results[0] == {"sources": [], "empty": True}
                else:
                    assert "no_documents_bound" in results[0]["error"]
                assert "invalid arguments" in results[1]["error"]
            finally:
                loop.close()


def expect_document_error(handler, code):
    try:
        handler()
    except DocumentAccessError as exc:
        assert exc.code == code
    else:
        raise AssertionError(f"expected {code}")


def test_changed_and_unbound_sources_are_rechecked_before_read_and_completion():
    with tempfile.TemporaryDirectory() as directory:
        for repository in (InMemoryDocumentRepository(), SQLiteDocumentRepository(Path(directory) / "test.sqlite3")):
            docs = DocumentService(repository)
            original = docs.upload_text("d", "title", "alpha original")
            docs.bind_goal("g", "d")
            docs.bind_node("g", "n", "d")
            turn = DocumentTurn(docs, "g", "n")
            assert turn.search({"query": "alpha", "limit": 5})["sources"][0]["id"] == "C1"
            docs.upload_text("d", "title", "alpha changed")  # Legacy same-version overwrite.
            expect_document_error(lambda: turn.read({"citation_id": "C1"}), "source_stale")
            assert turn.search({"query": "alpha", "limit": 5})["sources"][0]["id"] == "C2"
            output = turn.project_output("old [C1], current [C2]")
            assert output["citation_map"]["C1"]["status"] == "stale"
            assert output["unverified_citation_ids"] == ["C1"]
            upgraded = replace(original, version=2)
            repository.save_document(upgraded, chunk_document(upgraded))
            expect_document_error(lambda: turn.read({"citation_id": "C2"}), "source_stale")
            assert turn.search({"query": "alpha", "limit": 5})["sources"][0]["id"] == "C3"
            docs.unbind_goal("g", "d")
            expect_document_error(lambda: turn.read({"citation_id": "C3"}), "source_unavailable")
            output = turn.project_output("[C3] [C0]")
            assert output["citation_map"]["C3"]["status"] == "unavailable"
            assert output["unverified_citation_ids"] == ["C0", "C3"]
            # Goal removal also clears old node bindings; rebinding only the goal cannot resurrect them.
            docs.bind_goal("g", "d")
            assert repository.bound_document_ids("g", "n") == set()


def test_concurrent_document_turns_keep_local_source_ids_and_bound_documents():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning, learning, documents = seed(database)
        seed(database, "g2")
        barrier = threading.Barrier(2)

        class ConcurrentModel:
            def complete(self, messages, tools):
                results = [json.loads(message.content) for message in messages if message.role == "tool"]
                if not results:
                    barrier.wait(timeout=3)
                    return ModelResponse(tool_calls=(call("search_documents", {"query": "alpha"}, "search"),))
                assert results[0]["sources"][0]["id"] == "C1"
                return ModelResponse(content="原文 [C1]")

        loop = build_learning_loop(ConcurrentModel(), planning, learning, documents)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(loop.run, request(goal)) for goal in ("g1", "g2")]
                records = [future.result(timeout=5) for future in futures]
            assert [record.status for record in records] == ["completed", "completed"]
            assert [record.output["citation_map"]["C1"]["document_id"] for record in records] == ["g1a", "g2a"]
        finally:
            loop.close()


def test_http_sse_answer_sources_and_original_location_revalidate_saved_scope():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        _, _, documents = seed(database)
        model = ScriptedModel([
            ModelResponse(tool_calls=(call("search_documents", {"query": "alpha"}, "search"),)),
            ModelResponse(content="原文 [C1]；伪造 [C99]。"),
        ], with_skills=True)
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            body = {"request_id": "r1", "user_text": "依据资料解释", "goal_id": "g1", "node_id": "document-loading"}
            submitted = api.post("/api/sessions/g1/runs", json=body)
            assert submitted.status_code == 202
            base = f"/api/runs/{submitted.json()['run_id']}"
            with api.stream("GET", base + "/events") as stream:
                frames = [json.loads(line.removeprefix("data: ")) for line in stream.read().decode().splitlines()
                          if line.startswith("data: ")]
            completed = api.get(base).json()
            assert completed["status"] == "completed"
            assert frames[-1]["payload"]["output"] == completed["output"]
            assert completed["output"]["unverified_citation_ids"] == ["C99"]
            original = api.get(base + "/citations/C1")
            assert original.status_code == 200
            assert original.json()["text"] == "alpha 清洗原文。"
            assert original.json()["source"] == completed["output"]["citation_map"]["C1"]
            assert api.get(base + "/citations/C99").status_code == 404
            assert api.get("/api/runs/missing/citations/C1").status_code == 404
            docs = DocumentService(documents)
            docs.upload_text("g1a", "title", "alpha 改过的内容。")
            stale = api.get(base + "/citations/C1")
            assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_stale"
            docs.unbind_node("g1", "document-loading", "g1a")
            unavailable = api.get(base + "/citations/C1")
            assert unavailable.status_code == 409 and unavailable.json()["error"]["code"] == "source_unavailable"
            assert api.get(base).json()["output"] == completed["output"]  # Completion snapshot is immutable.
        assert model.closed


def test_output_projection_cannot_override_cancellation_and_failures_have_one_terminal():
    entered, release = threading.Event(), threading.Event()

    class AnswerModel:
        def complete(self, messages, tools):
            return ModelResponse(content="answer")

    runner = AgentRunner(AnswerModel(), ToolRegistry())

    def project(text):
        entered.set()
        assert release.wait(timeout=3)
        return {"sources": [text]}

    loop = AgentLoop(runner, prepare_run=lambda req, budget, root: PreparedRun(runner, (TextMessage("user", "x"),), project))
    try:
        record = loop.submit(request())
        assert entered.wait(timeout=3)
        assert loop.cancel(record.run_id).status == "cancelled"
        release.set()
    finally:
        release.set()
        loop.close()
    assert loop.get_run(record.run_id).output == {}
    assert [event.type for event in loop.events(record.run_id)] == ["run.started", "run.cancelled"]

    def fail(text):
        raise RuntimeError("projection failed")

    loop = AgentLoop(runner, prepare_run=lambda req, budget, root: PreparedRun(runner, (TextMessage("user", "x"),), fail))
    try:
        failed = loop.run(request())
        assert failed.status == "failed" and failed.output == {} and failed.error == "projection failed"
        assert [event.type for event in loop.events(failed.run_id)] == ["run.started", "run.failed"]
        budget = loop.run(request(key="budget"), Budget(max_model_calls=0))
        assert budget.status == "budget_exceeded" and budget.output == {}
    finally:
        loop.close()
