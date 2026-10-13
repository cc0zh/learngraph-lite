from __future__ import annotations

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, TextMessage, Tool, ToolCall, ToolError, ToolRegistry


class ScriptedModel:
    def __init__(self, responses: list[ModelResponse]):
        self.responses = responses
        self.calls = 0

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.calls += 1
        return self.responses.pop(0)


def registry() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(
        Tool(
            name="add",
            description="Add two numbers.",
            input_schema={"type": "object"},
            handler=lambda args: {"sum": args["a"] + args["b"]},
        )
    )
    tools.register(
        Tool(
            name="explode",
            description="Raise a tool error.",
            input_schema={"type": "object"},
            handler=lambda args: (_ for _ in ()).throw(ToolError("boom")),
        )
    )
    return tools


def test_runner_returns_plain_answer_without_tools():
    runner = AgentRunner(ScriptedModel([ModelResponse(content="hello")]), registry())
    result = runner.run((TextMessage(role="user", content="hi"),))
    assert result.status == "completed"
    assert result.final_text == "hello"


def test_runner_round_trips_tool_result_with_full_tool_call_id():
    model = ScriptedModel(
        [
            ModelResponse(tool_calls=(ToolCall(id="call-123", name="add", arguments='{"a":2,"b":3}'),)),
            ModelResponse(content="sum is 5"),
        ]
    )
    result = AgentRunner(model, registry()).run((TextMessage(role="user", content="add"),))
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert result.status == "completed"
    assert tool_messages[0].tool_call_id == "call-123"
    assert '"sum": 5' in tool_messages[0].content


def test_runner_reports_unknown_tool_and_bad_json_to_model():
    model = ScriptedModel(
        [
            ModelResponse(
                tool_calls=(
                    ToolCall(id="missing", name="missing", arguments="{}"),
                    ToolCall(id="bad-json", name="add", arguments='{"a":'),
                )
            ),
            ModelResponse(content="handled"),
        ]
    )
    result = AgentRunner(model, registry()).run((TextMessage(role="user", content="tools"),))
    assert result.status == "completed"
    assert any("unknown tool" in error for error in result.errors)
    assert any("invalid JSON" in error for error in result.errors)


def test_runner_stops_on_budget_or_cancel():
    model = ScriptedModel([ModelResponse(tool_calls=(ToolCall(id="1", name="add", arguments='{"a":1,"b":1}'),))])
    result = AgentRunner(model, registry()).run(
        (TextMessage(role="user", content="add"),),
        budget=Budget(max_model_calls=1, max_tool_calls=0, max_steps=2),
    )
    assert result.status == "failed"
    assert "tool call budget exhausted" in result.errors[-1]

    cancelled = AgentRunner(ScriptedModel([]), registry()).run(
        (TextMessage(role="user", content="hi"),),
        budget=Budget(cancelled=True),
    )
    assert cancelled.status == "cancelled"
