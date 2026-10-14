"""Atomic proposal/planning/learning review on one SQLite connection."""

from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from learngraph_lite.application.proposals import ProposalReviewState
from learngraph_lite.domain.learning import GraphEdge, GraphNode
from learngraph_lite.domain.learning.proposals import GraphOperation, GraphOperationKind, GraphProposal, ProposalStatus
from learngraph_lite.infrastructure.persistence import SQLiteLearningRepository, SQLitePlanningRepository


class SQLiteProposalRepository:
    """Repository and injected short-transaction coordinator.

    The application callback owns rules; this adapter only loads and writes the
    three aggregates. A conflicted result is committed before the caller raises.
    """

    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._planning = SQLitePlanningRepository(database_path)
        self._learning = SQLiteLearningRepository(database_path)
        with closing(self._connect()) as connection, connection:
            connection.execute("""create table if not exists graph_proposals (
                proposal_id text primary key, goal_id text not null references planning_states(goal_id),
                proposal_json text not null)""")
            connection.execute("""create table if not exists proposal_operations (
                goal_id text not null references planning_states(goal_id), operation_key text not null,
                fingerprint text not null, proposal_id text not null references graph_proposals(proposal_id),
                primary key(goal_id, operation_key))""")

    def _connect(self):
        connection = sqlite3.connect(self._database_path)
        connection.execute("pragma foreign_keys = on")
        return connection

    def get(self, proposal_id: str) -> GraphProposal:
        with closing(self._connect()) as connection:
            row = connection.execute("select proposal_json from graph_proposals where proposal_id=?",
                                     (proposal_id,)).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            return _proposal_from_json(json.loads(row[0]))

    def list(self, goal_id: str) -> tuple[GraphProposal, ...]:
        with closing(self._connect()) as connection:
            return self._list(connection, goal_id)

    @staticmethod
    def _list(connection, goal_id):
        return tuple(_proposal_from_json(json.loads(row[0])) for row in connection.execute(
            "select proposal_json from graph_proposals where goal_id=? order by rowid", (goal_id,)))

    def operation(self, goal_id: str, key: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute("select fingerprint, proposal_id from proposal_operations "
                                     "where goal_id=? and operation_key=?", (goal_id, key)).fetchone()
            return {"fingerprint": row[0], "id": row[1]} if row else None

    def transact(self, goal_id, update):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            planning = self._planning._get(connection, goal_id)
            try:
                learning = self._learning._get(connection, goal_id)
            except KeyError:
                learning = None
            state = ProposalReviewState(planning, learning,
                {item.id: item for item in self._list(connection, goal_id)},
                {row[0]: {"fingerprint": row[1], "id": row[2]} for row in connection.execute(
                    "select operation_key, fingerprint, proposal_id from proposal_operations where goal_id=?", (goal_id,))})
            previous = deepcopy(state)
            result = update(state)
            if state.planning != previous.planning:
                self._planning._save(connection, goal_id, state.planning)
            if state.learning is not None and state.learning != previous.learning:
                self._learning._save(connection, goal_id, state.learning)
            for proposal in state.proposals.values():
                if previous.proposals.get(proposal.id) != proposal:
                    connection.execute("insert into graph_proposals(proposal_id, goal_id, proposal_json) values (?, ?, ?) "
                        "on conflict(proposal_id) do update set proposal_json=excluded.proposal_json",
                        (proposal.id, goal_id, json.dumps(asdict(proposal), ensure_ascii=False, sort_keys=True)))
            for key, operation in state.operations.items():
                if previous.operations.get(key) != operation:
                    connection.execute("insert into proposal_operations(goal_id, operation_key, fingerprint, proposal_id) "
                                       "values (?, ?, ?, ?)", (goal_id, key, operation["fingerprint"], operation["id"]))
            return result


def _proposal_from_json(data: dict) -> GraphProposal:
    operations = []
    for item in data["operations"]:
        item = {**item, "kind": GraphOperationKind(item["kind"])}
        if item.get("node") is not None:
            item["node"] = GraphNode(**{**item["node"], "citation_ids": tuple(item["node"].get("citation_ids", ()))})
        if item.get("edge") is not None:
            item["edge"] = GraphEdge(**item["edge"])
        operations.append(GraphOperation(**item))
    return GraphProposal(id=data["id"], goal_id=data["goal_id"], base_revision=data["base_revision"],
                         operations=tuple(operations), rationale=data["rationale"], status=ProposalStatus(data["status"]),
                         decision_revision=data.get("decision_revision"), learning_reset=data.get("learning_reset", False))
