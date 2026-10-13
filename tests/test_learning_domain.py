from __future__ import annotations

from learngraph_lite.domain.learning.graph import GraphDraft, GraphEdge, GraphNode, validate_graph
from learngraph_lite.domain.learning.mastery import AttemptResult, MasteryState, score_mastery


def test_graph_validation_rejects_missing_endpoint_and_cycles():
    graph = GraphDraft(
        nodes=(GraphNode("a", "A", 10), GraphNode("b", "B", 10)),
        edges=(GraphEdge("a", "b"), GraphEdge("b", "a"), GraphEdge("a", "missing")),
    )
    errors = validate_graph(graph)
    assert "graph must be acyclic" in errors
    assert "edge endpoint missing: a->missing" in errors


def test_mastery_uses_distinct_recent_first_attempts():
    state, sample_count, accuracy = score_mastery(
        (
            AttemptResult("e1", True),
            AttemptResult("e1", False),
            AttemptResult("e2", True),
            AttemptResult("e3", True),
        )
    )
    assert state == MasteryState.PROFICIENT
    assert sample_count == 3
    assert accuracy == 1.0

    state, sample_count, accuracy = score_mastery((AttemptResult("e1", False),))
    assert state == MasteryState.LEARNING
    assert sample_count == 1
    assert accuracy == 0.0
