"""Short SQLite transactions for conversation metadata and workbench goal creation."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3

from learngraph_lite.application.conversations import Conversation, ConversationError
from learngraph_lite.application.planning import PlanningState
from learngraph_lite.infrastructure.persistence import SQLitePlanningRepository
from learngraph_lite.infrastructure.lifecycle_persistence import require_live_goal


class SQLiteConversationRepository:
    def __init__(self, database_path: str | Path):
        self._database_path = str(database_path)
        self._planning = SQLitePlanningRepository(database_path)
        with closing(self._connect()) as connection, connection:
            connection.execute("""create table if not exists conversations (
                session_id text primary key, kind text not null check(kind in ('learning', 'general')),
                title text not null, goal_id text, node_id text, created_at text not null,
                fingerprint text not null,
                check((kind='general' and goal_id is null and node_id is null)
                   or (kind='learning' and goal_id is not null and node_id is not null)))""")
            connection.execute("""create table if not exists workbench_goal_operations (
                goal_id text primary key, title text not null, created_at text not null)""")

    def _connect(self):
        return sqlite3.connect(self._database_path)

    @staticmethod
    def _record(row) -> Conversation:
        return Conversation(*row[:5], datetime.fromisoformat(row[5]))

    def list(self) -> tuple[Conversation, ...]:
        with closing(self._connect()) as connection:
            return tuple(self._record(row) for row in connection.execute(
                "select session_id, kind, title, goal_id, node_id, created_at from conversations"))

    def get(self, session_id: str) -> Conversation | None:
        with closing(self._connect()) as connection:
            row = connection.execute("select session_id, kind, title, goal_id, node_id, created_at "
                                     "from conversations where session_id=?", (session_id,)).fetchone()
            return self._record(row) if row else None

    def fingerprint(self, session_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute("select fingerprint from conversations where session_id=?", (session_id,)).fetchone()
            return row[0] if row else None

    def create(self, record: Conversation, fingerprint: str) -> Conversation:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            if connection.execute("select 1 from deleted_sessions where session_id=?", (record.session_id,)).fetchone():
                raise ConversationError("scope_deleted", "Conversation was deleted; use a new identity.")
            if record.goal_id is not None:
                require_live_goal(connection, record.goal_id)
            row = connection.execute("select session_id, kind, title, goal_id, node_id, created_at, fingerprint "
                                     "from conversations where session_id=?", (record.session_id,)).fetchone()
            if row:
                if row[6] != fingerprint:
                    raise ConversationError("conversation_conflict", "Conversation creation input differs.")
                return self._record(row)
            connection.execute("insert into conversations values (?, ?, ?, ?, ?, ?, ?)",
                (record.session_id, record.kind, record.title, record.goal_id, record.node_id,
                 record.created_at.isoformat(), fingerprint))
            return record

    def create_goal(self, goal_id: str, title: str, state: PlanningState, created_at: datetime) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("begin immediate")
            require_live_goal(connection, goal_id)
            row = connection.execute("select title from workbench_goal_operations where goal_id=?", (goal_id,)).fetchone()
            if row:
                if row[0] != title:
                    raise ConversationError("goal_creation_conflict", "Goal ID was already used with a different title.")
                return
            if connection.execute("select 1 from planning_states where goal_id=?", (goal_id,)).fetchone():
                raise ConversationError("goal_creation_conflict", "Goal was not created by this workbench operation.")
            # Like proposal review, this infrastructure coordinator writes planning
            # and its operation marker on one connection; no model runs here.
            self._planning._save(connection, goal_id, state)
            connection.execute("insert into workbench_goal_operations values (?, ?, ?)",
                               (goal_id, title, created_at.isoformat()))

    def goal_created_at(self, goal_id: str) -> datetime | None:
        with closing(self._connect()) as connection:
            row = connection.execute("select created_at from workbench_goal_operations where goal_id=?", (goal_id,)).fetchone()
            return datetime.fromisoformat(row[0]) if row else None
