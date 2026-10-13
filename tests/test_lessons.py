from __future__ import annotations

from learngraph_lite.agent_core import AgentRunner, ModelResponse, TextMessage, ToolRegistry
from learngraph_lite.application.agent import AgentLoop
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.lessons import InMemoryLessonRepository, LessonService
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.domain.lessons import ComponentKind, LessonComponent, LessonEvent, LessonPackage


class ExplainModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.calls += 1
        return ModelResponse(content="解释完成")


class FailingModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        raise RuntimeError("temporary failure")


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
            LessonComponent("choice-1", ComponentKind.MARKDOWN, {"text": "带引用的回答可定位来源。"}),
            LessonComponent("step-1", ComponentKind.STEPPER, {"steps": [
                {"title": name, "description": "理解" + name, "slots": {}} for name in ("检索", "引用", "回答")]}),
            LessonComponent("table-1", ComponentKind.COMPARISON_TABLE, {"columns": ["策略", "优点"], "rows": [["分块", "可定位"]]}),
        ),
    )


def services(model=None):
    model = model or ExplainModel()
    loop = AgentLoop(AgentRunner(model, ToolRegistry()))
    learning = LearningService(InMemoryLearningRepository(), loop)
    learning.start_goal(published_graph())
    lessons = LessonService(InMemoryLessonRepository(), learning, loop)
    return lessons, learning, model


def test_lesson_package_rejects_unknown_or_executable_content():
    lessons, _, _ = services()
    saved = lessons.save_package(lesson_package())
    assert saved.components[0].kind == ComponentKind.MARKDOWN

    bad = LessonPackage(
        id="bad",
        goal_id="g1",
        node_id="citations",
        graph_content_revision=1,
        markdown="<script>alert(1)</script>",
        components=(),
    )
    try:
        lessons.save_package(bad)
    except ValueError as exc:
        assert "executable" in str(exc)
    else:
        raise AssertionError("script markdown should fail")

    bad_component = LessonPackage(
        id="bad-component",
        goal_id="g1",
        node_id="citations",
        graph_content_revision=1,
        markdown="ok",
        components=(LessonComponent("x", ComponentKind.CHOICE_CARD, {"prompt": "x", "options": ["a", "b"], "onClick": "evil()"}),),
    )
    try:
        lessons.save_package(bad_component)
    except ValueError as exc:
        assert "executable" in str(exc)
    else:
        raise AssertionError("executable component prop should fail")


def test_lesson_events_are_idempotent_and_do_not_change_scores():
    lessons, learning, _ = services()
    lessons.save_package(lesson_package())
    before = learning.mastery("g1", "citations")
    event = LessonEvent("event-1", "lp1", "step-1", "step_changed", {"step": 0})
    first = lessons.ack_event("g1", event)
    second = lessons.ack_event("g1", LessonEvent("event-1", "lp1", "step-1", "step_changed", {"step": 1}))
    after = learning.mastery("g1", "citations")
    assert first == second
    assert before == after


def test_lesson_choice_submission_reuses_formal_learning_scoring():
    lessons, learning, _ = services()
    learning.create_fixture_exercise("g1", "citations", "e1", "引用回答应该怎样？")
    attempt = lessons.submit_choice_answer("g1", "e1", "b", "a1")
    assert attempt.counted is True
    assert attempt.is_correct is True


def test_explanation_run_is_idempotent_by_event_and_slot_and_retry_after_failure():
    lessons, _, model = services()
    lessons.save_package(lesson_package())
    event = lessons.ack_event("g1", LessonEvent("event-1", "lp1", "step-1", "request_explanation", {}))

    first_run_id = lessons.explain_event("g1", event.id, "step-1", "req-1")
    second_run_id = lessons.explain_event("g1", event.id, "step-1", "req-2")
    assert second_run_id == first_run_id
    assert model.calls == 1

    failing_lessons, _, _ = services(FailingModel())
    failing_lessons.save_package(lesson_package())
    failing_lessons.ack_event("g1", event)
    try:
        failing_lessons.explain_event("g1", event.id, "step-1", "req-1")
    except RuntimeError as exc:
        assert "temporary failure" in str(exc)
    else:
        raise AssertionError("failed explanation should be visible")
