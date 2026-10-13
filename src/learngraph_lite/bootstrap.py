"""Explicit local assembly for M1 smoke checks."""

from __future__ import annotations

from dataclasses import dataclass

from learngraph_lite.agent_core import AgentRunner, ModelResponse, TextMessage, Tool, ToolCall, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, RunRequest


@dataclass
class FixtureModel:
    """Deterministic fixture model; UI/export must label this as fixture mode."""

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        if any(message.role == "tool" for message in messages):
            return ModelResponse(content="工具结果已收到，继续学习下一步。", usage={"output_tokens": 12})
        return ModelResponse(
            content="",
            tool_calls=(ToolCall(id="call-1", name="echo", arguments='{"text":"hello"}'),),
            usage={"output_tokens": 4},
        )


def build_fixture_loop() -> AgentLoop:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="Return the input text for fixture smoke checks.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args: {"text": args["text"]},
        )
    )
    return AgentLoop(AgentRunner(FixtureModel(), registry))


def smoke() -> str:
    loop = build_fixture_loop()
    record = loop.run(RunRequest(session_id="local", user_text="开始", idempotency_key="smoke"))
    if record.status != "completed":
        raise RuntimeError(record.error)
    return record.final_text


def create_fixture_app():
    """Explicit fixture-only HTTP factory for local startup, never a real-model fallback."""
    from learngraph_lite.presentation.http import create_app

    return create_app(build_fixture_loop(), model_mode="fixture")


if __name__ == "__main__":
    print(smoke())
