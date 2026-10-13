from __future__ import annotations

import tempfile
from pathlib import Path

from learngraph_lite.agent_core import AgentRunner, ModelResponse, TextMessage, ToolRegistry
from learngraph_lite.application.agent import AgentLoop
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.lessons import LessonService
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.domain.lessons import ComponentKind, LessonComponent, LessonEvent, LessonPackage
from learngraph_lite.infrastructure import SQLiteLessonRepository


class ExplainModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.calls += 1
        return ModelResponse(content="解释完成")


class FailingThenPassingModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return ModelResponse(content="解释完成")


def published_graph():
    planning = PlanningService(InMemoryPlanningRepository())
    planning.create_goal("g1", "四周做出 RAG 应用", desired_outcome="demo", current_level="Python", time_budget_minutes=1200)
    planning.confirm_goal("g1")
    graph = candidate_rag_graph("g1")
    planning.save_graph_draft("g1", graph.nodes, graph.edges)
    return planning.publish_graph("g1", expected_revision=0)


def lesson_package() -> LessonPackage:
    return LessonPackage(
        id="lp1",
        goal_id="g1",
        node_id="citations",
        graph_content_revision=1,
        markdown="## 引用定位\n选择一个步骤查看解释。",
        components=(
            LessonComponent("choice-1", ComponentKind.CHOICE_CARD, {"prompt": "哪项更可靠？", "options": ["带引用", "无来源"]}),
            LessonComponent("step-1", ComponentKind.STEPPER, {"steps": ["检索", "引用", "回答"]}),
        ),
    )


def service(database: Path, model=None) -> LessonService:
    model = model or ExplainModel()
    loop = AgentLoop(AgentRunner(model, ToolRegistry()))
    learning = LearningService(InMemoryLearningRepository(), loop)
    learning.start_goal(published_graph())
    return LessonService(SQLiteLessonRepository(database), learning, loop)


def test_sqlite_lesson_repository_restores_package_event_and_explanation_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        lessons = service(database)
        saved = lessons.save_package(lesson_package())
        event = lessons.ack_event("g1", LessonEvent("event-1", "lp1", "step-1", "request_explanation", {"step": 1}))
        first_run_id = lessons.explain_event("g1", event.id, "step-1", "req-1")

        restored_model = ExplainModel()
        restored = service(database, restored_model)
        duplicate = restored.ack_event("g1", LessonEvent("event-1", "lp1", "step-1", "request_explanation", {"step": 2}))
        second_run_id = restored.explain_event("g1", event.id, "step-1", "req-2")
        restored_state = SQLiteLessonRepository(database).state("g1")

    assert restored_state.packages["lp1"] == saved
    assert duplicate == event
    assert second_run_id == first_run_id
    assert restored_model.calls == 0
    assert restored_state.packages["lp1"].markdown == "## 引用定位\n选择一个步骤查看解释。"


def test_sqlite_lesson_repository_restores_failed_explanation_for_retry():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        model = FailingThenPassingModel()
        lessons = service(database, model)
        lessons.save_package(lesson_package())
        event = lessons.ack_event("g1", LessonEvent("event-1", "lp1", "step-1", "request_explanation", {"step": 1}))
        try:
            lessons.explain_event("g1", event.id, "step-1", "req-1")
        except RuntimeError as exc:
            assert "temporary failure" in str(exc)
        else:
            raise AssertionError("failed explanation should be visible")

        assert SQLiteLessonRepository(database).state("g1").failed_explanations == {(event.id, "step-1")}
        restored = service(database, model)
        run_id = restored.explain_event("g1", event.id, "step-1", "req-2")
        repeated = restored.explain_event("g1", event.id, "step-1", "req-3")
        assert SQLiteLessonRepository(database).state("g1").failed_explanations == set()

    assert run_id == repeated
    assert model.calls == 2
