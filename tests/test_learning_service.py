from __future__ import annotations

from learngraph_lite.agent_core import AgentRunner, ModelResponse, TextMessage, ToolRegistry
from learngraph_lite.application.agent import AgentLoop
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.domain.learning import MasteryState


class NodeTutorModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(content=f"节点讲解：{messages[-1].content}")


def published_graph():
    planning = PlanningService(InMemoryPlanningRepository())
    planning.create_goal("g1", "四周做出 RAG 应用", desired_outcome="demo", current_level="Python", time_budget_minutes=1200)
    planning.confirm_goal("g1")
    graph = candidate_rag_graph("g1")
    planning.save_graph_draft("g1", graph.nodes, graph.edges)
    return planning.publish_graph("g1", expected_revision=0)


def service() -> LearningService:
    loop = AgentLoop(AgentRunner(NodeTutorModel(), ToolRegistry()))
    learning = LearningService(InMemoryLearningRepository(), loop)
    learning.start_goal(published_graph())
    return learning


def test_node_learning_uses_agent_loop_and_request_id_idempotency():
    learning = service()
    first = learning.learn_node("g1", "rag-goal", "解释目标边界", "req-1")
    second = learning.learn_node("g1", "rag-goal", "换一个问题", "req-1")
    assert first == "节点讲解：解释目标边界"
    assert second == first


def test_exercise_public_dto_hides_answer_and_server_scores_first_attempt_only():
    learning = service()
    public = learning.create_fixture_exercise("g1", "rag-goal", "e1", "RAG 回答应如何处理来源？")
    assert not hasattr(public, "correct_option_id")

    first = learning.submit_answer("g1", "e1", "b", "a1")
    retry = learning.submit_answer("g1", "e1", "a", "a2")
    assert first.is_correct is True
    assert first.counted is True
    assert retry.is_correct is False
    assert retry.counted is False


def test_mastery_and_next_action_follow_prerequisites_and_wrong_answers():
    learning = service()
    for index, option in enumerate(("b", "b", "b"), start=1):
        learning.create_fixture_exercise("g1", "rag-goal", f"e{index}", f"题目 {index}")
        learning.submit_answer("g1", f"e{index}", option, f"a{index}")
    state, sample_count, accuracy = learning.mastery("g1", "rag-goal")
    assert state == MasteryState.PROFICIENT
    assert sample_count == 3
    assert accuracy == 1.0

    action = learning.next_action("g1", available_minutes=10)
    assert action.node_id == "document-loading"
    assert action.action_type == "short_explanation"
    assert "limited_time" in action.reason_codes

    learning.create_fixture_exercise("g1", "document-loading", "wrong-1", "资料加载错误会怎样？")
    learning.submit_answer("g1", "wrong-1", "a", "wrong-a1")
    action = learning.next_action("g1", available_minutes=60)
    assert action.node_id == "document-loading"
    assert action.action_type == "practice"
    assert "recent_wrong" in action.reason_codes


def test_new_counted_wrong_answer_can_lower_mastery():
    learning = service()
    for index, option in enumerate(("b", "b", "b", "b"), start=1):
        learning.create_fixture_exercise("g1", "rag-goal", f"right-{index}", f"正确题 {index}")
        learning.submit_answer("g1", f"right-{index}", option, f"right-a{index}")
    state, sample_count, accuracy = learning.mastery("g1", "rag-goal")
    assert state == MasteryState.PROFICIENT
    assert sample_count == 4
    assert accuracy == 1.0

    learning.create_fixture_exercise("g1", "rag-goal", "wrong-new", "新题答错会怎样？")
    learning.submit_answer("g1", "wrong-new", "a", "wrong-new-a1")
    state, sample_count, accuracy = learning.mastery("g1", "rag-goal")
    assert state == MasteryState.PROFICIENT
    assert sample_count == 5
    assert accuracy == 0.8

    learning.create_fixture_exercise("g1", "rag-goal", "wrong-new-2", "再错一道会怎样？")
    learning.submit_answer("g1", "wrong-new-2", "a", "wrong-new-a2")
    state, sample_count, accuracy = learning.mastery("g1", "rag-goal")
    assert state == MasteryState.LEARNING
    assert sample_count == 5
    assert accuracy == 0.6


def test_duplicate_exercise_and_stale_version_are_rejected():
    learning = service()
    learning.create_fixture_exercise("g1", "rag-goal", "e1", "重复题？")
    try:
        learning.create_fixture_exercise("g1", "rag-goal", "e2", "重复题？")
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate exercise should fail")

    state = learning._repository.get("g1")
    state.graph = type(state.graph)(
        goal_id=state.graph.goal_id,
        nodes=state.graph.nodes,
        edges=state.graph.edges,
        status=state.graph.status,
        revision=state.graph.revision + 1,
        content_revision=state.graph.content_revision + 1,
    )
    try:
        learning.submit_answer("g1", "e1", "b", "a1")
    except ValueError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale exercise should fail")
