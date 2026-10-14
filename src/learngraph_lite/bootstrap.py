"""Explicit local assembly for M1 smoke checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from learngraph_lite.agent_core import AgentRunner, ModelResponse, TextMessage, Tool, ToolCall, ToolRegistry
from learngraph_lite.agent_core.models import ModelGateway
from learngraph_lite.agent_core.gateway import budgeted
from learngraph_lite.application.agent import AgentLoop, DirectResult, RunRepository, RunRequest
from learngraph_lite.application.exercise_generation import GenerateExercise
from learngraph_lite.application.lesson_generation import GenerateLesson
from learngraph_lite.application.lessons import LessonError, LessonRepository, LessonService
from learngraph_lite.application.documents import DocumentRepository
from learngraph_lite.application.document_imports import DocumentImports
from learngraph_lite.application.learning import LearningRepository, LearningService
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.planning import PlanningRepository, PlanningService
from learngraph_lite.application.planning_generation import GeneratePlanning
from learngraph_lite.application.proposals import GraphProposalService
from learngraph_lite.application.proposal_generation import GenerateProposal


def _load_dotenv() -> None:
    """Load simple KEY=VALUE settings without overriding the process environment."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator or not name.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name.strip(), value)


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
                        documents: DocumentRepository | None = None,
                        lessons: LessonRepository | None = None,
                        runs: RunRepository | None = None,
                        proposals: GraphProposalService | None = None) -> AgentLoop:
    context = LearningContext(planning, learning, documents, lessons, proposals)
    generator = GenerateExercise(learning, context.context, documents)
    planner = GeneratePlanning(PlanningService(planning), documents)

    def plan(request, budget, root_task_id):
        gateway = budgeted(model, budget)
        if request.mode == "clarify":
            result = planner.clarify(request.goal_id, request.planning_version, gateway)
        else:
            result = planner.graph(request.goal_id, request.planning_version, request.graph_node_count, gateway)
        return DirectResult("规划建议已保存，请审核后确认或发布。", result, dict(gateway.usage))

    def generate(request, budget, root_task_id):
        gateway = budgeted(model, budget)
        result = generator.generate(request.goal_id, request.node_id, root_task_id,
                                    {"count": request.exercise_count, "purpose": request.exercise_purpose}, gateway)
        label = "基于上传资料" if result["source_mode"] == "documents" else "非基于上传资料"
        return DirectResult(f"练习已保存（{label}）。", result, dict(gateway.usage))

    def validate(request):
        if request.mode == "proposal":
            if proposals is None:
                raise ValueError("Proposal generation is not configured.")
            proposals.published(request.goal_id)
        if request.mode == "lesson" and lessons is None:
            raise ValueError("Lesson generation is not configured.")
        if request.mode in {"exercise", "lesson", "teaching", "explanation"}:
            current = context.context(request.goal_id, request.node_id)
            if request.mode == "explanation":
                if lessons is None:
                    raise LessonError("lesson_not_found", "Lesson explanations are not configured.")
                state = lessons.state(request.goal_id)
                event = state.events.get(request.source_event_id)
                if event is None:
                    raise LessonError("event_not_found", "Unknown lesson event.")
                package = state.packages[event.package_id]
                if package.graph_content_revision != current["content_revision"]:
                    raise LessonError("outdated_lesson", "Historical lessons cannot start a new explanation.")
        elif request.mode in {"clarify", "graph"}:
            planner.validate(request.goal_id, request.mode, request.planning_version)

    handlers = {"exercise": generate, "clarify": plan, "graph": plan}
    if proposals is not None:
        proposal_generator = GenerateProposal(proposals)

        def generate_proposal(request, budget, root_task_id):
            gateway = budgeted(model, budget)
            result = proposal_generator.generate(request.goal_id, root_task_id,
                {"purpose": request.proposal_purpose}, gateway)
            return DirectResult("图谱提案已保存，等待用户审核；当前路线尚未改变。", result, dict(gateway.usage))
        handlers["proposal"] = generate_proposal
    if lessons is not None:
        lesson_generator = GenerateLesson(lessons, learning, context.context, documents)

        def generate_lesson(request, budget, root_task_id):
            gateway = budgeted(model, budget)
            result = lesson_generator.generate(request.goal_id, request.node_id, root_task_id,
                {"purpose": request.lesson_purpose, "exercise_ids": list(request.lesson_exercise_ids)}, gateway)
            label = "基于上传资料" if result["source_mode"] == "documents" else "非基于上传资料"
            return DirectResult(f"学习页已保存（{label}）。", result, dict(gateway.usage))
        handlers["lesson"] = generate_lesson

    def prepare(request, budget, root):
        validate(request)
        return context.prepare(budgeted(model, budget), request, root)

    return AgentLoop(AgentRunner(model, build_echo_tools()), direct_handlers=handlers, validate_run=validate,
                     prepare_run=prepare, repository=runs)


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

    _load_dotenv()
    api_key = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("MODEL_NAME")
    if not api_key or not model:
        raise RuntimeError("real model mode requires MODEL_API_KEY (or OPENAI_API_KEY) and MODEL_NAME")
    return OpenAIChatGateway(
        api_key=api_key,
        model=model,
        base_url=os.environ.get("MODEL_BASE_URL"),
        timeout=float(os.environ.get("MODEL_TIMEOUT_SECONDS", "30")),
        max_output_tokens=int(os.environ.get("MODEL_MAX_OUTPUT_TOKENS", "4096")),
    )


def create_real_app(*, database: str | Path | None = None):
    """Explicit real-model factory; missing configuration fails at startup."""
    return _create_business_app(build_real_gateway(), "real", database)


def create_business_fixture_app(*, database: str | Path | None = None):
    from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel

    return _create_business_app(BusinessFixtureModel(), "fixture",
        database or os.environ.get("LEARNGRAPH_DATABASE_PATH", ".local/fixture.sqlite3"))


def _create_business_app(gateway, mode: str, database):
    from learngraph_lite.presentation.http import create_app
    from learngraph_lite.infrastructure import SQLiteDocumentRepository, SQLiteLearningRepository, SQLiteLessonRepository, SQLitePlanningRepository
    from learngraph_lite.infrastructure.document_parser import SubprocessDocumentParser
    from learngraph_lite.infrastructure.run_persistence import SQLiteRunRepository
    from learngraph_lite.infrastructure.proposal_persistence import SQLiteProposalRepository

    imports = None
    try:
        database_path = Path(database or os.environ.get("LEARNGRAPH_DATABASE_PATH", ".local/learngraph.sqlite3"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
        planning = SQLitePlanningRepository(database_path)
        learning = SQLiteLearningRepository(database_path)
        documents = SQLiteDocumentRepository(database_path)
        lessons = SQLiteLessonRepository(database_path)
        proposal_repository = SQLiteProposalRepository(database_path)
        proposals = GraphProposalService(proposal_repository, proposal_repository, documents)
        learning_service = LearningService(learning)
        for item in PlanningService(planning).list_goals():
            state = planning.get(item["goal_id"])
            if state.graph is not None and state.graph.status.value == "published":
                learning_service.ensure_goal(state.graph)
        context = LearningContext(planning, learning, documents, lessons, proposals)
        loop = build_learning_loop(gateway, planning, learning, documents, lessons, SQLiteRunRepository(database_path), proposals)
        imports = DocumentImports(documents, SubprocessDocumentParser(), PlanningService(planning))
        return create_app(loop, model_mode=mode, model_configured=mode == "real", on_close=gateway.close,
                          learning_context=context,
                          exercises=GenerateExercise(learning, context.context, documents),
                          lessons=GenerateLesson(lessons, learning, context.context, documents),
                          lesson_events=LessonService(lessons, LearningService(learning), loop, context.context),
                          planning=PlanningService(planning), on_publish=learning_service.ensure_goal,
                          document_imports=imports, proposals=proposals)
    except Exception:
        if imports is not None:
            imports.close()
        gateway.close()
        raise


if __name__ == "__main__":
    print(smoke())
