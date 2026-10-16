from __future__ import annotations

import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import Budget, ModelResponse, ToolCall
from learngraph_lite.agent_core.gateway import BudgetedModelGateway
from learngraph_lite.application.agent import RunAdmissionError, RunRequest
from learngraph_lite.application.exercise_generation import ExerciseError, GenerateExercise
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.bootstrap import build_learning_loop, create_real_app
from learngraph_lite.infrastructure import SQLiteLearningRepository, SQLitePlanningRepository, SQLiteRunRepository


def seed(database=None):
    planning = SQLitePlanningRepository(database) if database else InMemoryPlanningRepository()
    learning = SQLiteLearningRepository(database) if database else InMemoryLearningRepository()
    service = PlanningService(planning)
    service.create_goal("g1", "学习 RAG", desired_outcome="demo", current_level="Python", time_budget_minutes=1200)
    service.confirm_goal("g1")
    graph = candidate_rag_graph("g1")
    service.save_graph_draft("g1", graph.nodes, graph.edges)
    LearningService(learning).start_goal(service.publish_graph("g1", 0))
    return planning, learning


def batch(prompt="生成题一", *, correct="b"):
    return json.dumps({"exercises": [{"prompt": prompt,
        "options": [{"id": "a", "text": "选项甲"}, {"id": "b", "text": "选项乙"}],
        "correct_option_id": correct, "explanation": "PRIVATE-EXPLANATION-42"}]}, ensure_ascii=False)


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def request(mode="exercise", key="r1"):
    return RunRequest("s1", "出一道题", key, mode=mode, goal_id="g1", node_id="document-loading")


def tool_call(args=None, call_id="create"):
    return ModelResponse(tool_calls=(ToolCall(call_id, "create_exercise", json.dumps(args or {})),),
                         usage={"output_tokens": 2})


def assert_public(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    assert "correct_option_id" not in text and "PRIVATE-EXPLANATION-42" not in text


def test_direct_and_tutor_generation_share_budget_repair_and_private_projection():
    for mode in ("exercise", "teaching"):
        planning, learning = seed()
        responses = [ModelResponse(content=batch(correct="missing"), usage={"output_tokens": 3}),
                     ModelResponse(content=batch(), usage={"output_tokens": 5})]
        if mode == "teaching":
            responses = [tool_call()] + responses + [tool_call(call_id="repeat"), ModelResponse(content="题目已保存。", usage={"output_tokens": 7})]
        model = ScriptedModel(responses)
        loop = build_learning_loop(model, planning, learning)
        budget = Budget()
        try:
            result = loop.run(request(mode), budget)
            assert result.status == "completed", result.error
            assert budget.model_calls == (5 if mode == "teaching" else 2)
            assert result.usage == {"output_tokens": 19 if mode == "teaching" else 8}
            assert result.output["source_mode"] == "general"
            assert len(result.output["exercises"]) == 1
            state = learning.get("g1")
            assert len(state.exercises) == 1 and len(state.generation_operations) == 1
            assert next(iter(state.exercises.values())).correct_option_id == "b"
            assert_public(result.output)
            assert_public([event.payload for event in loop.events(result.run_id)])
            if mode == "teaching":
                assert_public([message.content for message in model.calls[-1][0] if message.role == "tool"])
                assert not any("PRIVATE-EXPLANATION-42" in message.content for message in model.calls[-1][0])
            assert loop.run(request(mode)).run_id == result.run_id
        finally:
            loop.close()


def test_tutor_hands_recent_and_current_examples_to_generator_but_receives_only_ids():
    planning, learning = seed()
    earlier = "演示：x = (2, 4, 6)，x[1:] 为 (4, 6)。"
    current = "演示：s = (10, 20, 30, 40)，s[-2] 为 30。"
    new_prompt = "独立练习标记：u = (3, 5, 7)，u[:2] 是什么？"
    model = ScriptedModel([
        ModelResponse(content=earlier),
        ModelResponse(content=current, tool_calls=(ToolCall("new", "create_exercise", "{}"),)),
        ModelResponse(content=batch(new_prompt)),
        ModelResponse(content="已保存，请在题卡作答。"),
    ])
    loop = build_learning_loop(model, planning, learning)
    try:
        assert loop.run(request("teaching", "intro")).status == "completed"
        result = loop.run(request("teaching", "practice"))
        assert result.status == "completed", result.error
        generator_input = json.loads(model.calls[2][0][1].content)
        assert generator_input["taught_examples"] == [earlier, current]
        assert result.final_text == current + "\n\n已保存，请在题卡作答。"
        receipt = json.loads(next(m.content for m in model.calls[3][0] if m.role == "tool" and m.tool_call_id == "new"))
        assert receipt["exercise_ids"] == [result.output["exercises"][0]["id"]]
        assert receipt["source_mode"] == "general" and "exercises" not in receipt
        assert all(new_prompt not in m.content and "选项甲" not in m.content for m in model.calls[3][0])
        assert result.output["exercises"][0]["prompt"] == new_prompt
        assert len(learning.get("g1").exercises) == 1 and not learning.get("g1").attempts
    finally:
        loop.close()


def test_illustrated_prompt_is_repaired_once_and_never_saved_as_formal_practice():
    for repaired in (True, False):
        planning, learning = seed()
        example = "先看例子：计算 s[1:3] 的结果。已讲过答案。"
        duplicate = "计算 s[1:3] 的结果。"
        model = ScriptedModel([
            ModelResponse(content=example, tool_calls=(ToolCall("new", "create_exercise", "{}"),)),
            ModelResponse(content=batch(duplicate)),
            ModelResponse(content=batch("改用新数据，计算 u[::2]。" if repaired else duplicate)),
            ModelResponse(content="处理完成"),
        ])
        loop = build_learning_loop(model, planning, learning)
        try:
            result = loop.run(request("teaching"))
            stored = list(learning.get("g1").exercises.values())
            assert all(item.prompt != duplicate for item in stored)
            assert len(stored) == (1 if repaired else 0)
            assert len(learning.get("g1").generation_operations) == (1 if repaired else 0)
            assert "已讲解" in model.calls[2][0][-1].content
            if repaired:
                assert len(result.output["exercises"]) == 1
            else:
                assert "exercises" not in result.output
        finally:
            loop.close()

def test_button_practice_uses_only_completed_teaching_from_same_session_and_node():
    planning, learning = seed()
    model = ScriptedModel([
        ModelResponse(content="本会话已讲解：切片例子甲"),
        ModelResponse(content="其他会话的讲解不应带入"),
        ModelResponse(content=batch("新场景题")),
    ])
    loop = build_learning_loop(model, planning, learning)
    try:
        loop.run(request("teaching", "intro"))
        loop.run(replace(request("teaching", "other"), session_id="other-session"))
        result = loop.run(request("exercise", "button"))
        assert result.status == "completed", result.error
        assert json.loads(model.calls[2][0][1].content)["taught_examples"] == ["本会话已讲解：切片例子甲"]
    finally:
        loop.close()


def test_python_reference_reaches_tutor_and_generator_without_optional_skill_loading():
    planning, learning = seed()
    context = LearningContext(planning, learning)
    initial = context.context("g1", "document-loading")
    initial["goal"]["title"] = "Python 列表与元组"
    model = ScriptedModel([ModelResponse(content=batch())])
    gateway = BudgetedModelGateway(model, Budget())
    with patch.object(context, "context", return_value=initial):
        prepared = context.prepare(gateway, request("teaching"), "root")
        assert "tuple 切片不保证新对象" in prepared.messages[0].content
        assert "不要续写题干" in prepared.messages[0].content
        GenerateExercise(learning, context.context).generate("g1", "document-loading", "root", {}, gateway)
    assert "tuple 切片不保证新对象" in model.calls[0][0][0].content


def test_streamed_demonstration_survives_terminal_snapshot_and_sqlite_reopen():
    class StreamingModel(ScriptedModel):
        def stream_complete(self, messages, tools, on_delta):
            response = self.complete(messages, tools)
            if response.content:
                on_delta(response.content)
            return response

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "practice.sqlite3"
        planning, learning = seed(database)
        demo = "先看演示：x=(2,4,6)，x[1:] 得到 (4,6)。"
        acknowledgement = "新练习已保存，请在题卡作答。"
        model = StreamingModel([
            ModelResponse(content=demo, tool_calls=(ToolCall("create", "create_exercise", "{}"),)),
            ModelResponse(content=batch("独立题：y=(3,5,7)，y[-1] 是什么？")),
            ModelResponse(content=acknowledgement),
        ])
        loop = build_learning_loop(model, planning, learning, runs=SQLiteRunRepository(database))
        try:
            result = loop.run(replace(request("teaching"), stream=True))
            assert result.status == "completed", result.error
            assert result.final_text == demo + "\n\n" + acknowledgement
            deltas = [event.payload["text"] for event in loop.events(result.run_id) if event.type == "message.delta"]
            assert deltas == [demo, acknowledgement]
            terminal = loop.events(result.run_id)[-1]
            assert terminal.payload["final_text"] == result.final_text
            assert len(terminal.payload["output"]["exercises"]) == 1
        finally:
            loop.close()
        restored = build_learning_loop(ScriptedModel([]), planning, learning, runs=SQLiteRunRepository(database))
        try:
            assert restored.get_run(result.run_id).final_text == result.final_text
            assert len(restored.get_run(result.run_id).output["exercises"]) == 1
        finally:
            restored.close()


def test_tutor_generation_and_repair_keep_six_call_shared_budget():
    # Main loop + generation + repair consume exactly six calls; the seventh is blocked.
    for complete_on_sixth in (True, False):
        planning, learning = seed()
        responses = [tool_call(), ModelResponse(content="bad"), ModelResponse(content=batch()),
                     tool_call(call_id="repeat-1"), tool_call(call_id="repeat-2"),
                     ModelResponse(content="完成") if complete_on_sixth else tool_call(call_id="repeat-3")]
        model = ScriptedModel(responses)
        loop = build_learning_loop(model, planning, learning)
        budget = Budget()
        try:
            result = loop.run(request("teaching"), budget)
            assert result.status == ("completed" if complete_on_sixth else "budget_exceeded"), result.error
            assert len(model.calls) == budget.model_calls == 6
            assert len(learning.get("g1").exercises) == 1
        finally:
            loop.close()


def test_validation_budget_and_model_failures_do_not_save_partial_questions():
    cases = [
        ([ModelResponse(content="bad"), ModelResponse(content="bad")], Budget(), "failed", 2),
        ([ModelResponse(content="bad")], Budget(max_model_calls=1), "budget_exceeded", 1),
        ([RuntimeError("provider unavailable")], Budget(), "failed", 1),
        ([], Budget(cancelled=True), "cancelled", 0),
        ([tool_call(), ModelResponse(content="bad")], Budget(max_model_calls=2), "budget_exceeded", 2),
    ]
    for index, (responses, budget, expected, count) in enumerate(cases):
        planning, learning = seed()
        model = ScriptedModel(responses)
        loop = build_learning_loop(model, planning, learning)
        try:
            result = loop.run(request("teaching" if index == 4 else "exercise"), budget)
            assert result.status == expected, result.error
            assert len(model.calls) == count == budget.model_calls
            assert result.output == {} and not learning.get("g1").exercises
            assert len([event for event in loop.events(result.run_id) if event.type != "run.started"]) == 1
        finally:
            loop.close()


def test_failed_tutor_retry_reuses_saved_artifact_and_regenerate_uses_new_root():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "learn.sqlite3"
        planning, learning = seed(database)
        model = ScriptedModel([tool_call(), ModelResponse(content=batch()),
                               tool_call(), ModelResponse(content="完成"), ModelResponse(content=batch("生成题二"))])
        loop = build_learning_loop(model, planning, learning)
        try:
            failed = loop.run(request("teaching"), Budget(max_model_calls=2))
            assert failed.status == "budget_exceeded"
            saved = next(iter(learning.get("g1").exercises))
            retry = loop.run(replace(request("teaching", "r2"), retry_of_run_id=failed.run_id))
            assert retry.status == "completed" and retry.root_task_id == failed.root_task_id
            assert retry.output["exercises"][0]["id"] == saved
            assert len(model.calls) == 4  # Cached tool result makes no private generation call.
            regenerated = loop.run(request("exercise", "r3"))
            assert regenerated.status == "completed" and regenerated.root_task_id != failed.root_task_id
            assert len(SQLiteLearningRepository(database).get("g1").exercises) == 2
            try:
                loop.run(replace(request("teaching", "bad-retry"), retry_of_run_id=retry.run_id))
            except RunAdmissionError as exc:
                assert exc.code == "invalid_retry"
            else:
                raise AssertionError("completed run cannot be retried")
        finally:
            loop.close()


def test_operation_conflict_and_concurrent_sqlite_commit_preserve_one_batch():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "learn.sqlite3"
        planning, learning = seed(database)
        barrier = threading.Barrier(2)

        class RacingModel:
            def complete(self, messages, tools):
                barrier.wait(timeout=3)
                return ModelResponse(content=batch(threading.current_thread().name))

        def generate():
            repository = SQLiteLearningRepository(database)
            generator = GenerateExercise(repository, LearningContext(planning, repository).context)
            return generator.generate("g1", "document-loading", "root", {}, BudgetedModelGateway(RacingModel(), Budget()))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(generate) for _ in range(2)]
            results = [future.result(timeout=5) for future in futures]
        assert results[0] == results[1]
        assert len(learning.get("g1").exercises) == 1
        generator = GenerateExercise(learning, LearningContext(planning, learning).context)
        unused = ScriptedModel([])
        try:
            generator.generate("g1", "document-loading", "root", {"count": 2}, BudgetedModelGateway(unused, Budget()))
        except ExerciseError as exc:
            assert exc.code == "operation_conflict"
        else:
            raise AssertionError("same operation must reject changed parameters")
        assert not unused.calls


def test_cancel_and_changed_graph_after_model_return_cannot_save_questions():
    for change_graph in (False, True):
        planning, learning = seed()
        entered, release = threading.Event(), threading.Event()

        class BlockingModel:
            def complete(self, messages, tools):
                entered.set()
                assert release.wait(timeout=3)
                return ModelResponse(content=batch())

        loop = build_learning_loop(BlockingModel(), planning, learning)
        try:
            record = loop.submit(request())
            assert entered.wait(timeout=3)
            if change_graph:
                PlanningService(planning).update_node("g1", "document-loading", title="新草稿")
            else:
                assert loop.cancel(record.run_id).status == "cancelled"
            release.set()
            if change_graph:
                loop.wait_events(record.run_id, 1, timeout=3)
                assert loop.get_run(record.run_id).status == "failed"
            assert not learning.get("g1").exercises
        finally:
            release.set()
            loop.close()
        assert not learning.get("g1").exercises


def test_http_sse_generation_public_read_and_atomic_attempt_feedback():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "learn.sqlite3"
        _, learning = seed(database)
        model = ScriptedModel([ModelResponse(content=batch())])
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=model):
            app = create_real_app(database=database)
        with TestClient(app, base_url="http://localhost") as api:
            base = "/api/goals/g1/nodes/document-loading/exercises"
            body = {"session_id": "s1", "request_id": "r1"}
            submitted = api.post(base, json=body)
            assert submitted.status_code == 202
            run_url = "/api/runs/" + submitted.json()["run_id"]
            frames = api.get(run_url + "/events").text
            completed = api.get(run_url).json()
            assert completed["status"] == "completed", completed
            assert_public(completed)
            assert_public(frames)
            question = completed["output"]["exercises"][0]
            assert question in api.get(base).json()["exercises"]
            question_url = "/api/goals/g1/exercises/" + question["id"]
            assert api.get(question_url).json() == question
            assert api.post(base, json=body).json()["run_id"] == completed["run_id"]
            conflict = api.post(base, json={**body, "count": 2})
            assert conflict.status_code == 409
            assert api.post(base, json={**body, "request_id": "bad", "count": True}).status_code == 422
            assert api.post("/api/goals/g1/nodes/missing/exercises", json={**body, "request_id": "missing"}).status_code == 404
            assert api.get("/api/goals/g2/exercises/" + question["id"]).status_code == 404
            attempt = {"submission_id": "a1", "selected_option_id": "b"}
            feedback = api.post(question_url + "/attempts", json=attempt)
            assert feedback.status_code == 200
            assert feedback.json()["attempt"]["counted"] and feedback.json()["attempt"]["is_correct"]
            assert feedback.json()["explanation"] == "PRIVATE-EXPLANATION-42"
            assert api.post(question_url + "/attempts", json=attempt).json() == feedback.json()
            assert api.post(question_url + "/attempts", json={**attempt, "selected_option_id": "a"}).status_code == 409
            assert api.post(question_url + "/attempts", json={**attempt, "submission_id": "a2", "is_correct": True}).status_code == 422
            assert_public(api.get(run_url).json())
        assert model.closed
        generator = GenerateExercise(learning, LearningContext(SQLitePlanningRepository(database), learning).context)
        generated = generator.generate("g1", "document-loading", "fresh", {},
                                       BudgetedModelGateway(ScriptedModel([ModelResponse(content=batch("新并发题"))]), Budget()))
        exercise_id = generated["exercises"][0]["id"]
        barrier = threading.Barrier(2)

        def answer(index):
            repository = SQLiteLearningRepository(database)
            barrier.wait(timeout=3)
            return LearningService(repository).submit_answer("g1", exercise_id, "a", f"concurrent-{index}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(answer, range(2)))
        assert sum(item.counted for item in attempts) == 1
        assert len(learning.get("g1").attempts) == 3
