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


def test_missing_goal_inputs_are_transparent_and_skips_do_not_claim_ability():
    fields = ("desired_outcome", "current_level", "time_budget_minutes")
    draft = build_goal_draft("学习音乐", skipped_fields=fields)
    assumptions = " ".join(draft.assumptions)
    assert draft.skipped_fields == fields and draft.time_budget_minutes is None
    assert draft.desired_outcome == draft.current_level == ""
    assert len([item for item in draft.assumptions if "主动跳过" in item]) == 3
    assert "不假设已具备" in assumptions and "通用学习目标" in assumptions and "240 分钟" in assumptions
    assert "四周" not in assumptions and "项目" not in assumptions
    assert clarification_questions(draft, 0) == ()
    assert confirm_goal(draft).skipped_fields == fields
    self_report = build_goal_draft("学习音乐", current_level="  我已经很熟练  ")
    assert self_report.current_level == "我已经很熟练"
    assert any("用户自述" in item and "尚未验证" in item for item in self_report.assumptions)
    partial = build_goal_draft("学习音乐", skipped_fields=("current_level",))
    assert {item.field for item in clarification_questions(partial, 0)} == {"desired_outcome", "time_budget_minutes"}
    filled = build_goal_draft("学习音乐", desired_outcome="能解释节奏", current_level="Python",
                             time_budget_minutes=60, skipped_fields=fields)
    assert filled.skipped_fields == () and not any("主动跳过" in item for item in filled.assumptions)
    assert any("用户自述" in item and "尚未验证" in item for item in filled.assumptions)
    whitespace = build_goal_draft("学习音乐", current_level="  ", skipped_fields=("current_level",))
    assert whitespace.skipped_fields == ("current_level",)
    for invalid in (None, "current_level", ("title",), ("current_level", "current_level"), (False,)):
        try:
            build_goal_draft("学习", skipped_fields=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid skipped_fields accepted: {invalid}")


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
