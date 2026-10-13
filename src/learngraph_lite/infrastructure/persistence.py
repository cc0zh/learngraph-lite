"""SQLite persistence adapters for local LearnGraph Lite state."""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from learngraph_lite.application.planning import PlanningState
from learngraph_lite.domain.learning import GoalDraft, GraphEdge, GraphNode, GraphSnapshot, GraphStatus


class SQLitePlanningRepository:
    """Persist goal planning state with the Python standard library.

    This is the first narrow SQLite adapter. It intentionally covers only the
    planning state already exercised by the application layer: goal draft,
    clarification round and the current graph snapshot.
    """

    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._initialize()

    def save(self, goal_id: str, state: PlanningState) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    insert into planning_states(goal_id, goal_json, graph_json, clarification_round)
                    values (?, ?, ?, ?)
                    on conflict(goal_id) do update set
                        goal_json = excluded.goal_json,
                        graph_json = excluded.graph_json,
                        clarification_round = excluded.clarification_round
                    """,
                    (
                        goal_id,
                        json.dumps(_goal_to_json(state.goal), ensure_ascii=False, sort_keys=True),
                        json.dumps(_graph_to_json(state.graph), ensure_ascii=False, sort_keys=True) if state.graph else None,
                        state.clarification_round,
                    ),
                )

    def get(self, goal_id: str) -> PlanningState:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "select goal_json, graph_json, clarification_round from planning_states where goal_id = ?",
                (goal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown goal: {goal_id}")
        goal_json, graph_json, clarification_round = row
        return PlanningState(
            goal=_goal_from_json(json.loads(goal_json)),
            graph=_graph_from_json(json.loads(graph_json)) if graph_json else None,
            clarification_round=int(clarification_round),
        )

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    create table if not exists planning_states (
                        goal_id text primary key,
                        goal_json text not null,
                        graph_json text,
                        clarification_round integer not null
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


def _goal_to_json(goal: GoalDraft) -> dict:
    data = asdict(goal)
    data["document_ids"] = list(goal.document_ids)
    data["assumptions"] = list(goal.assumptions)
    return data


def _goal_from_json(data: dict) -> GoalDraft:
    return GoalDraft(
        title=data["title"],
        desired_outcome=data.get("desired_outcome", ""),
        current_level=data.get("current_level", ""),
        time_budget_minutes=data.get("time_budget_minutes"),
        constraints=data.get("constraints", ""),
        document_ids=tuple(data.get("document_ids", ())),
        assumptions=tuple(data.get("assumptions", ())),
        confirmed=bool(data.get("confirmed", False)),
    )


def _graph_to_json(graph: GraphSnapshot | None) -> dict | None:
    if graph is None:
        return None
    return {
        "goal_id": graph.goal_id,
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
        "status": graph.status.value,
        "revision": graph.revision,
        "content_revision": graph.content_revision,
    }


def _graph_from_json(data: dict) -> GraphSnapshot:
    return GraphSnapshot(
        goal_id=data["goal_id"],
        nodes=tuple(GraphNode(**node) for node in data.get("nodes", ())),
        edges=tuple(GraphEdge(**edge) for edge in data.get("edges", ())),
        status=GraphStatus(data["status"]),
        revision=int(data.get("revision", 0)),
        content_revision=int(data.get("content_revision", 0)),
    )
