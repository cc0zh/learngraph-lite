from __future__ import annotations

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, TextMessage, Tool, ToolCall, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, RunRequest
from learngraph_lite.presentation import encode_sse, public_run, public_run_event


class UsageModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(content="完成学习建议", usage={"input_tokens": 7, "output_tokens": 3})


class ToolLoopModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(tool_calls=(ToolCall(id="tool-private-id", name="echo", arguments='{"text":"x"}'),))


def test_loop_records_public_lifecycle_events_and_summary():
    loop = AgentLoop(AgentRunner(UsageModel(), ToolRegistry()))
    record = loop.run(RunRequest(session_id="s1", user_text="学 RAG", idempotency_key="k1"))

    assert record.status == "completed"
    assert record.summary == "run completed"
    assert record.usage == {"input_tokens": 7, "output_tokens": 3}

    events = loop.events(record.run_id)
    assert [event.type for event in events] == ["run.started", "run.completed"]
    assert events[0].seq == 1
    assert events[1].payload["final_text"] == "完成学习建议"

    dto = public_run(record)
    assert dto["status"] == "completed"
    assert dto["summary"] == "run completed"
    assert dto["usage"] == {"input_tokens": 7, "output_tokens": 3}


def test_budget_failure_is_projected_as_budget_exceeded_terminal_state():
    tools = ToolRegistry()
    tools.register(Tool("echo", "Echo text.", {"type": "object"}, lambda args: args))
    loop = AgentLoop(AgentRunner(ToolLoopModel(), tools))

    record = loop.run(
        RunRequest(session_id="s1", user_text="loop", idempotency_key="k2"),
        budget=Budget(max_model_calls=1, max_tool_calls=0, max_steps=2),
    )

    assert record.status == "budget_exceeded"
    assert "tool call budget exhausted" in record.summary
    assert loop.events(record.run_id)[-1].type == "run.budget_exceeded"


def test_cancelled_run_and_sse_projection_do_not_expose_transcript_or_tool_ids():
    loop = AgentLoop(AgentRunner(ToolLoopModel(), ToolRegistry()))
    record = loop.run(
        RunRequest(session_id="s1", user_text="cancel", idempotency_key="k3"),
        budget=Budget(cancelled=True),
    )

    assert record.status == "cancelled"
    event = loop.events(record.run_id)[-1]
    public_event = public_run_event(event)
    frame = encode_sse(event)

    assert public_event["type"] == "run.cancelled"
    assert "messages" not in public_event["payload"]
    assert "tool-private-id" not in frame
    assert frame.startswith(f"id: {event.seq}\nevent: run.cancelled\n")
