from __future__ import annotations

import tempfile
from pathlib import Path

from learngraph_lite.agent_core import ModelResponse, TextMessage
from learngraph_lite.bootstrap import build_learning_loop
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.domain.learning import MasteryState
from learngraph_lite.infrastructure import SQLiteLearningRepository


class NodeTutorModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(content=f"节点讲解：{messages[-1].content}")


class FailingThenPassingModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return ModelResponse(content=f"恢复后讲解：{messages[-1].content}")


def published_graph(repository=None):
    planning = PlanningService(repository or InMemoryPlanningRepository())
    planning.create_goal("g1", "四周做出 RAG 应用", desired_outcome="demo", current_level="Python", time_budget_minutes=1200)
    planning.confirm_goal("g1")
    graph = candidate_rag_graph("g1")
    planning.save_graph_draft("g1", graph.nodes, graph.edges)
    return planning.publish_graph("g1", expected_revision=0)


def service(database: Path) -> LearningService:
    return service_with_model(database, NodeTutorModel())


def service_with_model(database: Path, model) -> LearningService:
    planning, repository = InMemoryPlanningRepository(), SQLiteLearningRepository(database)
    published_graph(planning)
    return LearningService(repository, build_learning_loop(model, planning, repository))


def test_sqlite_learning_repository_restores_mastery_and_next_action():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        learning = service(database)
        learning.start_goal(published_graph())
        learning.learn_node("g1", "rag-goal", "解释目标边界", "req-1")
        for index in range(1, 4):
            learning.create_fixture_exercise("g1", "rag-goal", f"e{index}", f"题目 {index}")
            learning.submit_answer("g1", f"e{index}", "b", f"a{index}")

        restored = service(database)
        repeat = restored.learn_node("g1", "rag-goal", "换一个问题", "req-1")
        state, sample_count, accuracy = restored.mastery("g1", "rag-goal")
        action = restored.next_action("g1", available_minutes=10)

    assert repeat == "节点讲解：解释目标边界"
    assert state == MasteryState.PROFICIENT
    assert sample_count == 3
    assert accuracy == 1.0
    assert action.node_id == "document-loading"
    assert action.action_type == "short_explanation"


def test_sqlite_learning_repository_preserves_exercises_and_duplicate_attempt_rules():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        learning = service(database)
        learning.start_goal(published_graph())
        learning.create_fixture_exercise("g1", "rag-goal", "e1", "重复提交如何计分？")
        first = learning.submit_answer("g1", "e1", "b", "a1")

        restored = service(database)
        retry = restored.submit_answer("g1", "e1", "a", "a2")
        state, sample_count, accuracy = restored.mastery("g1", "rag-goal")

    assert first.counted is True
    assert retry.counted is False
    assert retry.is_correct is False
    assert state == MasteryState.LEARNING
    assert sample_count == 1
    assert accuracy == 1.0


def test_sqlite_learning_repository_does_not_persist_failed_learning_text_as_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        model = FailingThenPassingModel()
        learning = service_with_model(database, model)
        learning.start_goal(published_graph())
        failed_text = learning.learn_node("g1", "rag-goal", "第一次失败", "req-1")

        restored = service_with_model(database, model)
        retry_text = restored.learn_node("g1", "rag-goal", "重试成功", "req-1")

    assert failed_text == ""
    assert retry_text == "恢复后讲解：重试成功"
    assert model.calls == 2


def test_sqlite_learning_repository_reports_unknown_goal():
    with tempfile.TemporaryDirectory() as tmpdir:
        learning = service(Path(tmpdir) / "learngraph.db")
        try:
            learning.mastery("missing", "rag-goal")
        except KeyError as exc:
            assert "unknown learning goal" in str(exc)
        else:
            raise AssertionError("missing learning goal should fail")
