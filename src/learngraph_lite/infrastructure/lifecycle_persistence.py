"""Scoped hard deletion on one SQLite connection, retaining only ID tombstones."""

from contextlib import closing
from collections.abc import Iterable
import json
from pathlib import Path
import sqlite3

from learngraph_lite.application.conversations import ConversationError
from learngraph_lite.application.lifecycle import DeletedScope
from learngraph_lite.application.planning import PlanningError


def initialize_lifecycle(connection) -> None:
    connection.execute("create table if not exists deleted_sessions (session_id text primary key)")
    connection.execute("create table if not exists deleted_goals (goal_id text primary key)")
    connection.execute("create table if not exists deleted_runs (run_id text primary key)")


def require_live_goal(connection, goal_id: str) -> None:
    if connection.execute("select 1 from deleted_goals where goal_id=?", (goal_id,)).fetchone():
        raise PlanningError("goal_deleted", "Goal was deleted; use a new goal identity.")


def require_live_runs(connection, run_ids: Iterable[str]) -> None:
    for run_id in run_ids:
        if connection.execute("select 1 from deleted_runs where run_id=?", (run_id,)).fetchone():
            raise PlanningError("run_deleted", "Run was deleted; reload before saving its cached results.")


def operation_run_ids(keys: Iterable[str]) -> Iterable[str]:
    for key in keys:
        try:
            parts = json.loads(key)
        except (ValueError, TypeError):
            continue
        if isinstance(parts, list) and parts and isinstance(parts[0], str):
            yield parts[0]


class SQLiteLifecycleRepository:
    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        with closing(self._connect()) as connection, connection:
            initialize_lifecycle(connection)

    def _connect(self):
        connection = sqlite3.connect(self._database_path)
        connection.execute("pragma foreign_keys = on")
        return connection

    @staticmethod
    def _scope(connection, sessions: set[str], goal_id: str | None = None):
        requests = [(run_id, json.loads(raw)) for run_id, raw in connection.execute(
            "select run_id, request_json from agent_runs")]
        if goal_id is not None:
            sessions.update(row[0] for row in connection.execute(
                "select session_id from conversations where goal_id=?", (goal_id,)))
            sessions.update(request["session_id"] for _, request in requests if request.get("goal_id") == goal_id)
        while True:
            children = {request["session_id"] for _, request in requests if request.get("parent_session_id") in sessions}
            if children <= sessions:
                break
            sessions.update(children)
        runs = {run_id for run_id, request in requests if request["session_id"] in sessions}
        return DeletedScope(frozenset(sessions), frozenset(runs))

    @staticmethod
    def _delete_runs(connection, scope: DeletedScope):
        # Generation products are shared node assets, but their request/retry
        # fingerprints (including free-text purpose) belong to the deleted runs.
        for table in ("learning_generation_operations", "lesson_generation_operations", "proposal_operations"):
            for goal_id, key in connection.execute(f"select goal_id, operation_key from {table}").fetchall():
                try:
                    parts = json.loads(key)
                except (ValueError, TypeError):
                    continue
                if isinstance(parts, list) and parts and parts[0] in scope.run_ids:
                    connection.execute(f"delete from {table} where goal_id=? and operation_key=?", (goal_id, key))
        for goal_id, raw in connection.execute("select goal_id, run_ids_json from learning_states").fetchall():
            cache = json.loads(raw)
            removed = {key for key, run_id in cache.get("run_ids_by_key", {}).items() if run_id in scope.run_ids}
            if removed:
                for key in removed:
                    cache["run_ids_by_key"].pop(key, None)
                    cache.get("final_text_by_key", {}).pop(key, None)
                connection.execute("update learning_states set run_ids_json=? where goal_id=?", (json.dumps(cache), goal_id))
        for run_id in scope.run_ids:
            connection.execute("insert or ignore into deleted_runs values (?)", (run_id,))
            connection.execute("delete from lesson_run_tasks where root_task_id=?", (run_id,))
            connection.execute("delete from lesson_explanations where run_id=?", (run_id,))
            connection.execute("delete from agent_run_events where run_id=?", (run_id,))
            connection.execute("delete from agent_runs where run_id=?", (run_id,))
        for session_id in scope.session_ids:
            connection.execute("delete from conversations where session_id=?", (session_id,))
            connection.execute("insert or ignore into deleted_sessions values (?)", (session_id,))

    def delete_conversation(self, session_id: str) -> DeletedScope:
        if session_id.startswith("planning:"):
            raise ConversationError("planning_conversation", "Delete the goal instead of its planning conversation.")
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            if connection.execute("select 1 from deleted_sessions where session_id=?", (session_id,)).fetchone():
                return DeletedScope(frozenset({session_id}))
            scope = self._scope(connection, {session_id})
            exists = connection.execute("select 1 from conversations where session_id=?", (session_id,)).fetchone()
            if not exists and not scope.run_ids:
                raise ConversationError("conversation_not_found", "Conversation does not exist.")
            self._delete_runs(connection, scope)
            return scope

    def delete_goal(self, goal_id: str, expected_version: int) -> DeletedScope:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            if connection.execute("select 1 from deleted_goals where goal_id=?", (goal_id,)).fetchone():
                return DeletedScope(frozenset({f"planning:{goal_id}"}))
            row = connection.execute("select version from planning_states where goal_id=?", (goal_id,)).fetchone()
            if row is None:
                raise PlanningError("goal_not_found", "Goal does not exist.")
            if row[0] != expected_version:
                raise PlanningError("version_conflict", "Goal changed; refresh before deleting.")
            scope = self._scope(connection, {f"planning:{goal_id}"}, goal_id)
            self._delete_runs(connection, scope)
            for table in (
                "lesson_run_tasks", "lesson_explanations", "lesson_events", "lesson_generation_operations",
                "lesson_packages", "learning_attempts", "learning_generation_operations", "learning_exercises",
                "learning_states", "proposal_operations", "graph_proposals", "node_document_bindings",
                "goal_document_bindings", "workbench_goal_operations", "planning_states",
            ):
                connection.execute(f"delete from {table} where goal_id=?", (goal_id,))
            connection.execute("insert into deleted_goals values (?)", (goal_id,))
            return scope
