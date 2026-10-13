from __future__ import annotations

from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.domain.learning import GraphEdge, GraphNode, GraphStatus, RevisionConflict, clarification_questions
from learngraph_lite.domain.learning.goals import build_goal_draft, confirm_goal


def test_goal_clarification_is_limited_to_two_rounds_and_three_questions():
    draft = build_goal_draft("学习 RAG")
    first_round = clarification_questions(draft, round_index=0)
    assert len(first_round) == 3
    assert clarification_questions(draft, round_index=2) == ()


def test_goal_confirmation_requires_title_and_positive_budget():
    assert confirm_goal(build_goal_draft("学习 RAG", time_budget_minutes=60)).confirmed
    try:
        confirm_goal(build_goal_draft("", time_budget_minutes=60))
    except ValueError as exc:
        assert "title" in str(exc)
    else:
        raise AssertionError("empty title should fail")

    try:
        confirm_goal(build_goal_draft("学习 RAG", time_budget_minutes=0))
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("zero budget should fail")


def test_planning_service_requires_confirmed_goal_before_graph_and_publishes_revision():
    service = PlanningService(InMemoryPlanningRepository())
    draft, questions = service.create_goal("g1", "四周做出 RAG 应用")
    assert not draft.confirmed
    assert len(questions) == 3

    graph = candidate_rag_graph("g1")
    try:
        service.save_graph_draft("g1", graph.nodes, graph.edges)
    except ValueError as exc:
        assert "confirmed" in str(exc)
    else:
        raise AssertionError("unconfirmed goal should not allow graph generation")

    service.answer_clarification(
        "g1",
        desired_outcome="做出可解释 RAG demo",
        current_level="有 Python 基础",
        time_budget_minutes=1200,
    )
    service.confirm_goal("g1")
    snapshot = service.save_graph_draft("g1", graph.nodes, graph.edges)
    assert snapshot.status == GraphStatus.DRAFT
    assert snapshot.revision == 0
    assert len(snapshot.nodes) == 8

    edited = service.update_node("g1", "chunking", title="面向引用的分块策略")
    assert edited.revision == 0
    assert any(node.title == "面向引用的分块策略" for node in edited.nodes)

    published = service.publish_graph("g1", expected_revision=0)
    assert published.status == GraphStatus.PUBLISHED
    assert published.revision == 1
    assert published.content_revision == 1
    assert service.current_graph("g1") == published


def test_publish_rejects_invalid_graph_and_revision_conflict():
    service = PlanningService(InMemoryPlanningRepository())
    service.create_goal("g1", "学习 RAG", desired_outcome="demo", current_level="Python", time_budget_minutes=100)
    service.confirm_goal("g1")
    service.save_graph_draft(
        "g1",
        (GraphNode("a", "A", 10), GraphNode("b", "B", 10)),
        (GraphEdge("a", "b"), GraphEdge("b", "a")),
    )
    try:
        service.publish_graph("g1", expected_revision=0)
    except ValueError as exc:
        assert "acyclic" in str(exc)
    else:
        raise AssertionError("cyclic graph should fail")

    service.save_graph_draft("g1", (GraphNode("a", "A", 10),), ())
    published = service.publish_graph("g1", expected_revision=0)
    assert published.revision == 1

    try:
        service.publish_graph("g1", expected_revision=0)
    except RevisionConflict as exc:
        assert exc.actual_revision == 1
    else:
        raise AssertionError("stale revision should conflict")
