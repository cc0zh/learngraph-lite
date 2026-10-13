from __future__ import annotations

import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import Budget, ModelResponse, ToolCall
from learngraph_lite.agent_core.gateway import budgeted
from learngraph_lite.application.agent import RunRequest
from learngraph_lite.application.documents import DocumentService, InMemoryDocumentRepository
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.lesson_generation import GenerateLesson
from learngraph_lite.application.lessons import InMemoryLessonRepository, LessonError, LessonService
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService
from learngraph_lite.bootstrap import build_learning_loop, create_real_app
from learngraph_lite.domain.learning import GraphNode
from learngraph_lite.domain.lessons import LessonEvent
from learngraph_lite.infrastructure import (
    SQLiteDocumentRepository, SQLiteLearningRepository, SQLiteLessonRepository, SQLitePlanningRepository,
)


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


def seed(database=None, bound=True):
    planning = SQLitePlanningRepository(database) if database else InMemoryPlanningRepository()
    learning = SQLiteLearningRepository(database) if database else InMemoryLearningRepository()
    documents = SQLiteDocumentRepository(database) if database else InMemoryDocumentRepository()
    lessons = SQLiteLessonRepository(database) if database else InMemoryLessonRepository()
    service = PlanningService(planning)
    service.create_goal("g", "RAG", desired_outcome="引用定位", current_level="Python", time_budget_minutes=100)
    service.confirm_goal("g")
    service.save_graph_draft("g", (GraphNode("n", "RAG 资料学习", 20), GraphNode("other", "其他节点", 10)), ())
    learner = LearningService(learning)
    learner.start_goal(service.publish_graph("g", 0))
    learner.create_fixture_exercise("g", "n", "e", "保留 RAG 引用偏移？")
    learner.create_fixture_exercise("g", "other", "other-e", "其他题目")
    docs = DocumentService(documents)
    docs.upload_text("a", "a", "RAG alpha 原文保留偏移与引用定位。")
    docs.upload_text("b", "b", "beta 回答专用原文。")
    docs.upload_text("hidden", "hidden", "RAG 隐藏资料不得检索。")
    if bound:
        for doc in ("a", "b"):
            docs.bind_goal("g", doc)
            docs.bind_node("g", "n", doc)
    return planning, learning, documents, lessons


def candidate(ids=("C1",), exercise_id="e", **changes):
    data = {"schema_version": 1, "title": "理解引用", "markdown": "## 引用" + (" [C1]" if ids else ""),
            "citation_ids": list(ids), "components": [
                {"id": "note", "kind": "markdown", "props": {"text": "保留来源偏移"}},
                {"id": "quiz", "kind": "quiz_choice", "props": {"exercise_id": exercise_id}},
                {"id": "steps", "kind": "stepper", "props": {"steps": [
                    {"title": "检索", "description": "找片段", "slots": {"text": "RAG"}},
                    {"title": "回答", "description": "标引用", "slots": {}}]}},
                {"id": "table", "kind": "comparison_table", "props": {"columns": ["方式", "依据"],
                    "rows": [["引用", "原文"]]}},
            ]}
    data.update(changes)
    return ModelResponse(content=json.dumps(data, ensure_ascii=False))


def request(key="r", mode="lesson", **changes):
    return RunRequest("s", "生成", key, goal_id="g", node_id="n", mode=mode,
                      lesson_exercise_ids=("e",), **changes)


def public(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    assert "correct_option_id" not in text and "PRIVATE-EXPLANATION" not in text


def test_grounded_lesson_repair_bounds_operations_versions_and_sqlite_reopen():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning, learning, documents, lessons = seed(database)
        docs = DocumentService(documents)
        for index in range(6):
            doc = f"extra{index}"
            docs.upload_text(doc, doc, "RAG " + "原文" * 450)
            docs.bind_goal("g", doc)
            docs.bind_node("g", "n", doc)
        context = LearningContext(planning, learning, documents)
        generator = GenerateLesson(lessons, learning, context.context, documents)
        model = Model([candidate(("C99",)), candidate(), candidate()])
        gateway = budgeted(model, Budget())
        first = generator.generate("g", "n", "root", {"exercise_ids": ["e"]}, gateway)
        assert gateway.budget.model_calls == 2
        inputs = [json.loads(call[0][1].content) for call in model.calls]
        assert inputs[0]["sources"] == inputs[1]["sources"] and len(inputs[0]["sources"]) == 5
        assert sum(len(item["excerpt"]) for item in inputs[0]["sources"]) <= 1600
        assert all(item["document_id"] != "hidden" for item in inputs[0]["sources"])
        assert inputs[0]["exercises"][0]["id"] == "e"
        public(inputs)
        assert generator.generate("g", "n", "root", {"exercise_ids": ["e"]}, gateway) == first
        assert len(model.calls) == 2
        try:
            generator.generate("g", "n", "root", {"purpose": "另一个用途"}, gateway)
        except LessonError as exc:
            assert exc.code == "operation_conflict"
        else:
            raise AssertionError("different operation parameters were accepted")
        second = generator.generate("g", "n", "new-root", {"exercise_ids": ["e"]}, gateway)
        assert first["lesson"]["version"] == 1 and second["lesson"]["version"] == 2
        assert first["lesson"]["id"] != second["lesson"]["id"]
        reopened = GenerateLesson(SQLiteLessonRepository(database), SQLiteLearningRepository(database),
                                  context.context, SQLiteDocumentRepository(database))
        assert reopened.get_package("g", first["lesson"]["id"]) == first["lesson"]
        assert reopened.generate("g", "n", "root", {"exercise_ids": ["e"]}, gateway) == first
        assert len(model.calls) == 3
        assert [item["version"] for item in reopened.list_packages("g", "n")["lessons"]] == [2, 1]


def test_lesson_validation_general_empty_retrieval_budget_and_stale_inputs():
    planning, learning, documents, lessons = seed(bound=False)
    loop = build_learning_loop(Model([candidate(())]), planning, learning, documents, lessons)
    try:
        result = loop.run(request())
        assert result.status == "completed" and result.output["lesson"]["source_mode"] == "general"
    finally:
        loop.close()
    invalid_candidates = [
        candidate(), candidate((), components=[{"id": "q", "kind": "quiz_choice",
            "props": {"exercise_id": "e", "correct_option_id": "b"}}]),
        candidate((), exercise_id="other-e"), candidate((), components=[{"id": "x", "kind": "unknown", "props": {}}]),
        candidate((), components=[{"id": "x", "kind": "stepper", "props": {"steps": [
            {"title": "x", "description": "x", "slots": {}}] * 13}}]),
        candidate((), components=[{"id": "x", "kind": "comparison_table",
            "props": {"columns": ["x", "y"], "rows": [["x"]]}}]),
        candidate((), components=[{"id": "chapter", "kind": "markdown", "props": {"text": "x"}}]),
        candidate((), markdown="[C99]"), candidate((), components=[{"id": "x", "kind": "markdown", "props": {"text": "x"}}] * 20),
    ]
    generator = GenerateLesson(lessons, learning, LearningContext(planning, learning).context, documents)
    before = lessons.state("g")
    for index, invalid in enumerate(invalid_candidates):
        model = Model([invalid, invalid])
        try:
            generator.generate("g", "n", f"invalid{index}", {"exercise_ids": ["e"]}, budgeted(model, Budget()))
        except LessonError as exc:
            assert exc.code == "invalid_lesson_candidate"
        else:
            raise AssertionError("invalid candidate was saved")
        assert len(model.calls) == 2 and lessons.state("g") == before
    for args in ({"exercise_ids": ["e", "e"]}, {"exercise_ids": ["other-e"]}, {"exercise_ids": ["missing"]}):
        model = Model([])
        try:
            generator.generate("g", "n", "input", args, budgeted(model, Budget()))
        except LessonError:
            pass
        else:
            raise AssertionError("invalid exercise scope was accepted")
        assert not model.calls
    for mutation in ("unbind", "replace", "goal", "graph", "exercise", "cancel", "empty", "budget"):
        p, l, d, repo = seed()
        budget = Budget(max_model_calls=1 if mutation == "budget" else 6)
        def change():
            if mutation == "unbind":
                DocumentService(d).unbind_node("g", "n", "a")
            elif mutation == "replace":
                DocumentService(d).upload_text("a", "a", "RAG changed offsets")
            elif mutation == "goal":
                p.mutate("g", lambda state: setattr(state, "goal", replace(state.goal, title="新目标")))
            elif mutation == "graph":
                p.mutate("g", lambda state: setattr(state, "graph", replace(state.graph, revision=2)))
            elif mutation == "exercise":
                l.mutate("g", lambda state: state.exercises.pop("e"))
            elif mutation == "cancel":
                budget.cancelled = True
            return candidate(("C99",) if mutation == "budget" else ("C1",))
        if mutation == "empty":
            DocumentService(d).upload_text("a", "a", "zebra")
        model = Model([change])
        loop = build_learning_loop(model, p, l, d, repo)
        try:
            record = loop.run(request(), budget)
            assert record.status in {"failed", "cancelled", "budget_exceeded"}, (mutation, record)
            assert not repo.state("g").packages, mutation
            if mutation == "empty":
                assert not model.calls
        finally:
            loop.close()


def test_teaching_lesson_and_exercise_use_shared_gateway_and_separate_c1_tables():
    planning, learning, documents, lessons = seed()
    def tool(name, args):
        return ModelResponse(tool_calls=(ToolCall(name, name, json.dumps(args)),))
    question = ModelResponse(content=json.dumps({"exercises": [{"prompt": "RAG 引用如何定位？",
        "options": [{"id": "a", "text": "丢弃偏移"}, {"id": "b", "text": "保留偏移"}],
        "correct_option_id": "b", "explanation": "PRIVATE-EXPLANATION", "citation_ids": ["C1"]}]}))
    def choose_lesson():
        exercise_id = next(key for key in learning.get("g").exercises if key not in {"e", "other-e"})
        return tool("create_lesson", {"exercise_ids": [exercise_id]})
    def lesson_reply():
        exercise_id = next(key for key in learning.get("g").exercises if key not in {"e", "other-e"})
        return candidate(exercise_id=exercise_id)
    model = Model([tool("search_documents", {"query": "beta", "limit": 5}),
        tool("create_exercise", {}), question, choose_lesson, lesson_reply, ModelResponse(content="回答依据 [C1]")])
    loop = build_learning_loop(model, planning, learning, documents, lessons)
    try:
        budget = Budget(max_model_calls=6)
        result = loop.run(request(mode="teaching"), budget)
        assert result.status == "completed", result.error
        assert budget.model_calls == 6 and budget.tool_calls == 3
        output = result.output
        assert output["citation_map"]["C1"]["document_id"] == "b"
        assert output["exercises"][0]["citation_map"]["C1"]["document_id"] == "a"
        assert output["lesson"]["citation_map"]["C1"]["document_id"] == "a"
        public(output)
        assert output["lesson"]["components"][1]["props"]["exercise_id"] == output["exercises"][0]["id"]
        assert "correct_option_id" not in json.dumps(json.loads(model.calls[4][0][1].content)["exercises"])
    finally:
        loop.close()


def test_http_sse_lesson_events_formal_attempts_historical_view_and_source_deletion():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning, learning, documents, lessons = seed(database)
        model = Model([candidate(), candidate()])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            body = {"session_id": "s", "request_id": "r", "exercise_ids": ["e"]}
            submitted = api.post("/api/goals/g/nodes/n/lessons", json=body)
            assert submitted.status_code == 202, submitted.text
            run_url = "/api/runs/" + submitted.json()["run_id"]
            stream = api.get(run_url + "/events")
            assert "run.completed" in stream.text
            public(stream.text)
            record = api.get(run_url).json()
            assert record["status"] == "completed", record
            package = record["output"]["lesson"]
            url = "/api/goals/g/lessons/" + package["id"]
            assert api.get(url).json() == package
            assert api.post("/api/goals/g/nodes/n/lessons", json=body).json()["run_id"] == record["run_id"]
            assert api.get(url + "/citations/C1").status_code == 200
            assert api.get(url + "/citations/C99").status_code == 404
            assert api.get("/api/goals/other/lessons/" + package["id"]).status_code == 404
            events_url = url + "/events"
            event = {"event_id": "event", "package_version": 1, "component_id": "steps",
                     "action": "step_changed", "payload": {"step": 0}}
            first = api.post(events_url, json=event)
            assert first.status_code == 200, first.text
            assert api.post(events_url, json={**event, "payload": {"step": 1}}).json() == first.json()
            assert api.post(events_url, json={**event, "component_id": "quiz"}).status_code == 409
            for changes in ({"package_version": 2}, {"component_id": "missing"}, {"action": "mark_read"},
                            {"payload": {"step": True}}, {"payload": {"step": 2}}, {"payload": {"mastery": 100}},
                            {"component_id": "quiz", "action": "step_changed"}):
                response = api.post(events_url, json={**event, "event_id": "bad", **changes})
                assert response.status_code == 422, response.text
            assert api.post(events_url, json={**event, "event_id": "read", "component_id": "chapter",
                                              "action": "mark_read", "payload": {}}).status_code == 200
            assert len(model.calls) == 1 and not learning.get("g").attempts
            attempt = api.post("/api/goals/g/exercises/e/attempts",
                               json={"submission_id": "answer", "selected_option_id": "b"})
            assert attempt.status_code == 200 and attempt.json()["attempt"]["is_correct"]
            body["request_id"] = "regenerate"
            second = api.post("/api/goals/g/nodes/n/lessons", json=body)
            api.get("/api/runs/" + second.json()["run_id"] + "/events")
            assert [item["version"] for item in api.get("/api/goals/g/nodes/n/lessons").json()["lessons"]] == [2, 1]
            # A semantic graph change must allow historical reading even before learning migration.
            planning.mutate("g", lambda state: setattr(state, "graph", replace(state.graph, content_revision=2, revision=2)))
            assert api.get(url).json()["outdated"]
            assert api.get("/api/goals/g/nodes/n/lessons").json()["lessons"][0]["outdated"]
            assert api.post(events_url, json={**event, "event_id": "new"}).status_code == 409
            assert api.post(events_url, json=event).json() == first.json()
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=Model([])):
            reopened = create_real_app(database=database)
        with TestClient(reopened, base_url="http://localhost") as api:
            assert api.get(url).json()["outdated"]
            documents.delete_document("a")
            saved = api.get(url).json()
            assert saved["citation_map"]["C1"]["status"] == "unavailable"
            assert saved["unverified_citation_ids"] == ["C1"]
            assert api.get(url + "/citations/C1").status_code == 409
            public(saved)


def test_concurrent_lesson_generation_ack_rollback_and_explanation_preserves_updates():
    with tempfile.TemporaryDirectory() as directory:
        for database in (None, Path(directory) / "test.sqlite3"):
            planning, learning, documents, lessons = seed(database, bound=False)
            context = LearningContext(planning, learning, documents)
            barrier = Barrier(2)
            def generate(index):
                def reply():
                    barrier.wait(timeout=5)
                    return candidate(())
                generator = GenerateLesson(lessons, learning, context.context, documents)
                return generator.generate("g", "n", str(index), {"exercise_ids": ["e"]}, budgeted(Model([reply]), Budget()))
            with ThreadPoolExecutor(max_workers=2) as executor:
                outputs = list(executor.map(generate, range(2)))
            assert sorted(item["lesson"]["version"] for item in outputs) == [1, 2]
            package = outputs[0]["lesson"]
            ack_barrier = Barrier(2)
            def acknowledge(index):
                ack_barrier.wait(timeout=5)
                return service.ack_event("g", LessonEvent(str(index), package["id"], "steps", "step_changed",
                                                         {"step": index}, package["version"]))
            def explain_reply():
                service.ack_event("g", LessonEvent("during-model", package["id"], "chapter", "mark_read", {}, package["version"]))
                return ModelResponse(content="解释完成")
            loop = build_learning_loop(Model([explain_reply]), planning, learning, documents, lessons)
            service = LessonService(lessons, LearningService(learning), loop, context.context)
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    accepted = list(executor.map(acknowledge, range(2)))
                assert len(lessons.state("g").events) == 2
                service.explain_event("g", accepted[0].id, "initial", "r")
                state = lessons.state("g")
                assert len(state.packages) == 2 and len(state.events) == 3 and state.explanation_runs
                def fail(current):
                    current.packages.clear()
                    raise ValueError("rollback")
                try:
                    lessons.mutate("g", fail)
                except ValueError:
                    pass
                assert lessons.state("g") == state
                if database:
                    assert SQLiteLessonRepository(database).state("g") == state
            finally:
                loop.close()


def test_legacy_lesson_schema_migration_readonly_and_removed_node_history():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "legacy.sqlite3"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("""create table lesson_packages (goal_id text, package_id text, node_id text,
                graph_content_revision integer, markdown text, components_json text, primary key(goal_id, package_id))""")
            connection.execute("""create table lesson_events (goal_id text, event_id text, package_id text,
                component_id text, action text, payload_json text, primary key(goal_id, event_id))""")
            connection.execute("insert into lesson_packages values (?, ?, ?, ?, ?, ?)",
                ("g", "old", "n", 1, "旧内容", json.dumps([{"id": "q", "kind": "choice_card",
                    "props": {"prompt": "旧题", "options": ["a", "b"]}}])))
        planning, learning, documents, lessons = seed(database, bound=False)
        context = LearningContext(planning, learning)
        generator = GenerateLesson(lessons, learning, context.context)
        package = generator.get_package("g", "old")
        assert package["schema_version"] == 0 and package["outdated"] and package["source_mode"] == "general"
        loop = build_learning_loop(Model([]), planning, learning, lessons=lessons)
        service = LessonService(lessons, LearningService(learning), loop, context.context)
        try:
            try:
                service.ack_event("g", LessonEvent("new", "old", "q", "request_explanation", {}))
            except LessonError as exc:
                assert exc.code == "invalid_lesson_event"
            else:
                raise AssertionError("legacy lesson accepted a new event")
            planning.mutate("g", lambda state: setattr(state, "graph", replace(state.graph,
                nodes=tuple(node for node in state.graph.nodes if node.id != "n"))))
            assert generator.get_package("g", "old")["outdated"]
            assert generator.list_packages("g", "n")["lessons"][0]["id"] == "old"
        finally:
            loop.close()
