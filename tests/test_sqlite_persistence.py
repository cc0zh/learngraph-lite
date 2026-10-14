from __future__ import annotations

import tempfile
import json
import sqlite3
from contextlib import closing
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


def test_sqlite_skipped_fields_restore_merge_clear_and_legacy_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        service = PlanningService(SQLitePlanningRepository(database))
        service.create_goal("g", "学习音乐", skipped_fields=("current_level", "time_budget_minutes"))
        service.confirm_goal("g", 0, desired_outcome="能解释节奏")
        restored = PlanningService(SQLitePlanningRepository(database))
        state = restored.get_state("g")
        assert state.version == 1 and state.goal.confirmed
        assert state.goal.skipped_fields == ("current_level", "time_budget_minutes")
        assert state.goal.time_budget_minutes is None and state.goal.desired_outcome == "能解释节奏"
        assert state.goal.assumptions == service.get_state("g").goal.assumptions
        restored.edit_goal("g", 1, constraints="每天练习")
        assert restored.get_state("g").goal.skipped_fields == state.goal.skipped_fields
        restored.confirm_goal("g", 2, skipped_fields=[])
        assert PlanningService(SQLitePlanningRepository(database)).get_state("g").goal.skipped_fields == ()
        # Simulate a pre-skipped_fields JSON row, without changing its schema.
        with closing(sqlite3.connect(database)) as connection, connection:
            data = json.loads(connection.execute("select goal_json from planning_states where goal_id='g'").fetchone()[0])
            data.pop("skipped_fields")
            connection.execute("update planning_states set goal_json=? where goal_id='g'", (json.dumps(data),))
        assert PlanningService(SQLitePlanningRepository(database)).get_state("g").goal.skipped_fields == ()


def test_sqlite_legacy_assumptions_rebuild_without_changing_graph_or_version():
    with tempfile.TemporaryDirectory() as tmpdir:
        database = Path(tmpdir) / "learngraph.db"
        service = PlanningService(SQLitePlanningRepository(database))
        service.create_goal("missing", "音乐")
        service.confirm_goal("missing", 0)
        service.create_goal("reported", "RAG", current_level="Python", desired_outcome="解释检索", time_budget_minutes=60,
                            document_ids=("d1",))
        service.confirm_goal("reported", 0)
        graph = candidate_rag_graph("reported")
        service.save_graph_draft("reported", graph.nodes, graph.edges)
        service.publish_graph("reported", 0)
        before = {goal_id: service.get_state(goal_id) for goal_id in ("missing", "reported")}
        with closing(sqlite3.connect(database)) as connection, connection:
            for goal_id in before:
                data = json.loads(connection.execute("select goal_json from planning_states where goal_id=?", (goal_id,)).fetchone()[0])
                data["assumptions"] = ["默认按有基础但未系统实践处理。", "默认按四周学习计划拆分。"]
                if goal_id == "reported":
                    data["skipped_fields"] = ["current_level", "desired_outcome", "time_budget_minutes"]
                else:
                    data.pop("skipped_fields")
                connection.execute("update planning_states set goal_json=? where goal_id=?", (json.dumps(data), goal_id))
        restored = PlanningService(SQLitePlanningRepository(database))
        for goal_id, previous in before.items():
            state = restored.get_state(goal_id)
            assert state == previous and state.goal.confirmed
            assert state.graph == previous.graph and state.version == previous.version
            assert state.goal.skipped_fields == ()
            assert not any("四周" in item or "有基础但未系统实践" in item for item in state.goal.assumptions)
        missing = " ".join(restored.get_state("missing").goal.assumptions)
        assert "不假设已具备" in missing and "240 分钟" in missing
        assert restored.get_state("missing").goal.time_budget_minutes is None
        reported = restored.get_state("reported").goal
        assert reported.current_level == "Python" and reported.document_ids == ("d1",)
        assert any("用户自述" in item and "尚未验证" in item for item in reported.assumptions)
