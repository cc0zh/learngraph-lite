from __future__ import annotations

import tempfile
from pathlib import Path

from learngraph_lite.application.planning import PlanningService, candidate_rag_graph
from learngraph_lite.infrastructure import SQLitePlanningRepository


def test_sqlite_planning_repository_restores_confirmed_goal_and_published_graph():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        service = PlanningService(SQLitePlanningRepository(database))
        service.create_goal(
            "g1",
            "四周做出 RAG 应用",
            desired_outcome="demo",
            current_level="Python",
            time_budget_minutes=1200,
            document_ids=("d1",),
        )
        service.confirm_goal("g1")
        graph = candidate_rag_graph("g1")
        service.save_graph_draft("g1", graph.nodes, graph.edges)
        published = service.publish_graph("g1", expected_revision=0)

        restored = PlanningService(SQLitePlanningRepository(database))
        restored_graph = restored.current_graph("g1")
        restored_goal = restored.confirm_goal("g1")

    assert restored_graph == published
    assert restored_goal.confirmed
    assert restored_goal.document_ids == ("d1",)


def test_sqlite_planning_repository_reports_unknown_goal():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = PlanningService(SQLitePlanningRepository(Path(tmpdir) / "learngraph.db"))
        try:
            service.current_graph("missing")
        except KeyError as exc:
            assert "unknown goal" in str(exc)
        else:
            raise AssertionError("missing goal should fail")
