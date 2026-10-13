"""Explicit local assembly for M1 smoke checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from learngraph_lite.agent_core import AgentRunner, ModelResponse, TextMessage, Tool, ToolCall, ToolRegistry
from learngraph_lite.agent_core.models import ModelGateway
from learngraph_lite.agent_core.gateway import budgeted
from learngraph_lite.application.agent import AgentLoop, DirectResult, RunRequest
from learngraph_lite.application.exercise_generation import GenerateExercise
from learngraph_lite.application.documents import DocumentRepository
from learngraph_lite.application.learning import LearningRepository
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.planning import PlanningRepository


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


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=1000)


def build_echo_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool.from_model(
            name="echo",
            description="Return the input text to verify a native tool calling round trip.",
            input_model=EchoInput,
            handler=lambda args: {"text": args["text"]},
        )
    )
    return registry


def build_fixture_loop() -> AgentLoop:
    return AgentLoop(AgentRunner(FixtureModel(), build_echo_tools()))


def build_learning_loop(model: ModelGateway, planning: PlanningRepository, learning: LearningRepository,
                        documents: DocumentRepository | None = None) -> AgentLoop:
    context = LearningContext(planning, learning, documents)
    generator = GenerateExercise(learning, context.context)

    def generate(request, budget, root_task_id):
        gateway = budgeted(model, budget)
        result = generator.generate(request.goal_id, request.node_id, root_task_id,
                                    {"count": request.exercise_count, "purpose": request.exercise_purpose}, gateway)
        return DirectResult("练习已保存（非基于上传资料）。", result, dict(gateway.usage))

    def validate(request):
        if request.mode in {"exercise", "teaching"}:
            context.context(request.goal_id, request.node_id)

    return AgentLoop(AgentRunner(model, build_echo_tools()), direct_handlers={"exercise": generate}, validate_run=validate,
                     prepare_run=lambda request, budget, root: context.prepare(budgeted(model, budget), request, root))


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


def build_real_gateway():
    from learngraph_lite.infrastructure.openai_gateway import OpenAIChatGateway

    api_key = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("MODEL_NAME")
    if not api_key or not model:
        raise RuntimeError("real model mode requires MODEL_API_KEY (or OPENAI_API_KEY) and MODEL_NAME")
    return OpenAIChatGateway(
        api_key=api_key,
        model=model,
        base_url=os.environ.get("MODEL_BASE_URL"),
        timeout=float(os.environ.get("MODEL_TIMEOUT_SECONDS", "30")),
        max_output_tokens=int(os.environ.get("MODEL_MAX_OUTPUT_TOKENS", "1024")),
    )


def create_real_app(*, database: str | Path | None = None):
    """Explicit real-model factory; missing configuration fails at startup."""
    from learngraph_lite.presentation.http import create_app
    from learngraph_lite.infrastructure import SQLiteDocumentRepository, SQLiteLearningRepository, SQLitePlanningRepository

    gateway = build_real_gateway()
    try:
        database_path = Path(database or os.environ.get("LEARNGRAPH_DATABASE_PATH", ".local/learngraph.sqlite3"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
        planning = SQLitePlanningRepository(database_path)
        learning = SQLiteLearningRepository(database_path)
        documents = SQLiteDocumentRepository(database_path)
        loop = build_learning_loop(gateway, planning, learning, documents)
        return create_app(loop, model_mode="real", model_configured=True, on_close=gateway.close,
                          learning_context=LearningContext(planning, learning, documents),
                          exercises=GenerateExercise(learning, LearningContext(planning, learning).context))
    except Exception:
        gateway.close()
        raise


if __name__ == "__main__":
    print(smoke())
