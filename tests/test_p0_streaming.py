from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile

import httpx
from fastapi.testclient import TestClient

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, TextMessage, ToolCall, ToolRegistry
from learngraph_lite.agent_core.budget import BudgetExceeded
from learngraph_lite.agent_core.context import fit_context
from learngraph_lite.application.agent import AgentLoop, RunRequest
from learngraph_lite.bootstrap import build_echo_tools, create_business_fixture_app
from learngraph_lite.infrastructure.openai_gateway import ModelGatewayError, OpenAIChatGateway
from learngraph_lite.infrastructure.run_persistence import SQLiteRunRepository


def chunk(delta, finish=None, usage=None):
    return {"id": "stream", "object": "chat.completion.chunk", "created": 0, "model": "test",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], "usage": usage}


def wire(items):
    return "".join("data: " + json.dumps(item) + "\n\n" for item in items) + "data: [DONE]\n\n"


def test_native_sdk_stream_aggregates_tools_without_leaking_arguments_and_counts_usage():
    requests = []
    replies = [wire([
        chunk({"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "echo", "arguments": '{"text":'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"secret-tool-input"}'}}]}, "tool_calls"),
    ]), wire([chunk({"content": "hello "}), chunk({"content": "world"}, "stop",
                {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12})])]

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=replies.pop(0))

    gateway = OpenAIChatGateway(api_key="test", model="test", http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    events = []
    try:
        result = AgentRunner(gateway, build_echo_tools()).run((TextMessage("user", "hello"),),
            on_progress=lambda kind, payload: events.append((kind, payload)))
        assert result.status == "completed" and result.final_text == "hello world"
        assert result.usage == {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12}
        assert [kind for kind, _ in events] == ["tool.started", "tool.finished", "message.delta", "message.delta"]
        assert "secret-tool-input" not in json.dumps(events)
        assert requests[0]["stream"] and requests[0]["stream_options"] == {"include_usage": True}
        assert requests[1]["messages"][-1]["tool_call_id"] == "call-1"
    finally:
        gateway.close()


def test_incomplete_native_stream_never_executes_a_fragmented_tool():
    for reply in [wire([chunk({"tool_calls": [{"index": 0, "id": "c", "type": "function", "function": {"name": "echo", "arguments": '{"text":'}}]})]),
                  wire([chunk({"content": "partial"}, "length")])]:
        gateway = OpenAIChatGateway(api_key="test", model="test", http_client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=reply))))
        events = []
        try:
            try:
                AgentRunner(gateway, build_echo_tools()).run((TextMessage("user", "hello"),),
                    on_progress=lambda kind, payload: events.append(kind))
            except ModelGatewayError:
                pass
            else:
                raise AssertionError("incomplete stream accepted")
            assert "tool.started" not in events
        finally:
            gateway.close()


def test_context_keeps_required_context_and_current_tool_group_and_deadline_stops_calls():
    messages = (TextMessage("system", "instructions"), TextMessage("user", "business context"),
        TextMessage("user", "old" * 2000), TextMessage("assistant", "", tool_calls=(ToolCall("old", "echo", "{}"),)),
        TextMessage("tool", "result", tool_call_id="old"), TextMessage("user", "current"),
        TextMessage("assistant", "", tool_calls=(ToolCall("new", "echo", "{}"),)), TextMessage("tool", "result", tool_call_id="new"))
    fitted = fit_context(messages, (), 500)
    assert fitted == (*messages[:2], *messages[5:])
    try:
        fit_context((TextMessage("user", "required" * 3000),), (), 100)
    except BudgetExceeded:
        pass
    else:
        raise AssertionError("oversized current input accepted")

    class ForbiddenModel:
        def complete(self, messages, tools):
            raise AssertionError("deadline must stop before provider call")

    result = AgentRunner(ForbiddenModel(), ToolRegistry()).run((TextMessage("user", "hi"),), Budget(max_seconds=0))
    assert result.status == "failed" and "deadline budget exhausted" in result.errors


def test_stream_snapshot_history_and_terminal_state_survive_sqlite_reopen():
    class Model:
        def __init__(self):
            self.inputs = []

        def stream_complete(self, messages, tools, on_delta):
            self.inputs.append(messages)
            for _ in range(700):
                on_delta("x")
            return ModelResponse("x" * 700)

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "run.sqlite3"
        model = Model()
        request = RunRequest("s", "first", "one", stream=True)
        loop = AgentLoop(AgentRunner(model, ToolRegistry()), repository=SQLiteRunRepository(database))
        first = loop.run(request)
        assert first.partial_text == "x" * 700 and first.status == "completed"
        assert len(loop.events(first.run_id)) <= 513
        assert loop.snapshot(first.run_id)[1] == 702
        loop.close()
        restored = AgentLoop(AgentRunner(model, ToolRegistry()), repository=SQLiteRunRepository(database))
        try:
            assert restored.get_run(first.run_id) == first
            assert restored.run(request).run_id == first.run_id
            second = restored.run(replace(request, user_text="second", idempotency_key="two"))
            assert second.status == "completed"
            assert [m.content for m in model.inputs[-1]] == ["first", "x" * 700, "second"]
        finally:
            restored.close()


def test_business_fixture_teaching_and_button_generation_restore_feedback_without_exposing_answers():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "business.sqlite3"
        with TestClient(create_business_fixture_app(database=database), base_url="http://localhost") as api:
            plan = api.post("/api/goals", json={"title": "P0", "desired_outcome": "demo", "current_level": "Python", "time_budget_minutes": 30}).json()
            goal = plan["goal_id"]
            plan = api.post(f"/api/goals/{goal}/confirm", json={"expected_version": plan["version"]}).json()
            plan = api.patch(f"/api/goals/{goal}/graph", json={"expected_version": plan["version"], "nodes": [
                {"id": "n", "title": "node", "explanation": "example", "learning_outcome": "explain", "estimated_minutes": 20, "priority": 3}], "edges": []}).json()
            api.post(f"/api/goals/{goal}/graph/publish", json={"expected_version": plan["version"], "expected_revision": plan["graph"]["revision"]}).raise_for_status()
            teaching = api.post("/api/sessions/s/runs", json={"request_id": "teach", "user_text": "给我一道练习",
                "goal_id": goal, "node_id": "n", "mode": "teaching"}).json()
            api.get(f'/api/runs/{teaching["run_id"]}/events').raise_for_status()
            completed = api.get(f'/api/runs/{teaching["run_id"]}').json()
            assert completed["status"] == "completed", completed
            assert {item["name"] for item in completed["tool_activity"].values()} == {"get_learning_context", "create_exercise"}
            assert len(completed["output"]["exercises"]) == 1
            assert "correct_option_id" not in json.dumps(completed)
            run = api.post(f"/api/goals/{goal}/nodes/n/exercises", json={"session_id": "s", "request_id": "q"}).json()
            # SSE waits for the server-side terminal event, without polling sleeps.
            assert "run.completed" in api.get(f'/api/runs/{run["run_id"]}/events').text or api.get(f'/api/runs/{run["run_id"]}').json()["status"] == "completed"
            listing = api.get(f"/api/goals/{goal}/nodes/n/exercises").json()
            assert len(listing["exercises"]) == 2
            assert listing["feedback"] == {} and "correct_option_id" not in json.dumps(listing)
            exercise = listing["exercises"][0]["id"]
            feedback = api.post(f"/api/goals/{goal}/exercises/{exercise}/attempts", json={"submission_id": "a", "selected_option_id": "b"}).json()
            assert feedback["attempt"]["counted"] and feedback["attempt"]["is_correct"]
        with TestClient(create_business_fixture_app(database=database), base_url="http://localhost") as api:
            listing = api.get(f"/api/goals/{goal}/nodes/n/exercises").json()
            assert listing["feedback"][exercise] == feedback
            assert api.get(f"/api/goals/{goal}/nodes/n/context").json()["node"]["sample_count"] == 1
